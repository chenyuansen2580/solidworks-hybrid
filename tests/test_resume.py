# -*- coding: utf-8 -*-
"""test_resume.py — AssemblySession 断点续建往返测试（不依赖 SolidWorks）。"""
import json
import os

from hybrid_reuse import AssemblySession

ALL_PARTS = ["base", "rail", "table", "screw", "motor"]
ALL_MATES = ["CC_screw_bk12", "CC_screw_coupling", "CO_rail_base", "CO_table_riser"]


def test_fresh_session_empty(tmp_path):
    s = AssemblySession(str(tmp_path / "state.json"))
    s.load(resume=False)
    assert s.pending_components(ALL_PARTS) == ALL_PARTS
    assert s.pending_mates(ALL_MATES) == ALL_MATES


def test_mark_and_persist(tmp_path):
    sp = str(tmp_path / "state.json")
    s = AssemblySession(sp, asm_path="T.SLDASM")
    s.load(resume=False)
    s.mark_component("base", instance="base-1")
    assert os.path.isfile(sp), "每步必须立即落盘"

    with open(sp, "r", encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["components"]["base"]["ok"] is True
    assert raw["asm_path"] == "T.SLDASM"


def test_resume_roundtrip(tmp_path):
    """模拟：跑到一半崩溃 -> 重开进程续建，只补缺口。"""
    sp = str(tmp_path / "state.json")

    # 第 1 轮：完成 3 组件 + 1 配合，2 条配合失败
    s1 = AssemblySession(sp)
    s1.load(resume=False)
    for p in ["base", "rail", "table"]:
        s1.mark_component(p, instance=p + "-1")
    s1.mark_mate("CC_screw_bk12", axis_dist_mm=0.0)
    s1.bump_attempt("CO_table_riser")
    s1.mark_failure("coincident", "CO_table_riser", "平面选不到")
    s1.bump_attempt("CO_table_riser")
    s1.mark_failure("coincident", "CO_table_riser", "平面选不到")

    # 第 2 轮：新进程续建
    s2 = AssemblySession(sp)
    s2.load(resume=True)
    assert s2.pending_components(ALL_PARTS) == ["screw", "motor"]
    assert s2.pending_mates(ALL_MATES) == [
        "CC_screw_coupling", "CO_rail_base", "CO_table_riser"]
    assert s2.state["attempts"]["CO_table_riser"] == 2

    # 补完
    for p in s2.pending_components(ALL_PARTS):
        s2.mark_component(p, instance=p + "-1")
    for k in s2.pending_mates(ALL_MATES):
        s2.mark_mate(k)

    summ = s2.summary(len(ALL_PARTS), len(ALL_MATES))
    assert summ["components_done"] == len(ALL_PARTS)
    assert summ["mates_done"] == len(ALL_MATES)


def test_attempt_cap_skips(tmp_path):
    """超过重试上限的配合不再出现在 pending 里，避免死循环。"""
    s = AssemblySession(str(tmp_path / "state.json"))
    s.load(resume=False)
    for _ in range(3):
        s.bump_attempt("CO_bad")
    assert "CO_bad" not in s.pending_mates(["CO_bad"], max_retry=3)
    assert s.pending_mates(["CO_other"], max_retry=3) == ["CO_other"]


def test_atomic_write_no_partial(tmp_path):
    """写入必须是原子的：不应留下 .tmp 残留。"""
    sp = str(tmp_path / "state.json")
    s = AssemblySession(sp)
    s.load(resume=False)
    for i in range(5):
        s.mark_component("p%d" % i)
    assert not os.path.exists(sp + ".tmp")
    with open(sp, "r", encoding="utf-8") as f:
        assert len(json.load(f)["components"]) == 5


def test_failure_records(tmp_path):
    s = AssemblySession(str(tmp_path / "state.json"))
    s.load(resume=False)
    s.bump_attempt("X")
    n = s.mark_failure("mate", "X", "boom")
    assert n == 1
    assert s.state["failures"][0]["error"] == "boom"
    assert s.state["failures"][0]["attempt"] == 1
