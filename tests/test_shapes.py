# -*- coding: utf-8 -*-
"""test_shapes.py — 形状签名 / 分组 / 平移差 的纯逻辑测试。

覆盖需求：
  - shape_signature 平移不变性
  - plan_instances 分组正确性（4 零件 → 2 母件）
  - translation_between 正确性（含非纯平移的负例）
"""
import copy

import pytest

from hybrid_reuse import (family_report, instance_report, plan_families,
                          plan_instances, shape_signature,
                          translation_between)


# ------------------------------------------------------------------ 签名
def test_signature_translation_invariant(example_parts):
    """同一形状纯平移后，签名必须完全相同。"""
    a = shape_signature(example_parts["base_block_a"])
    b = shape_signature(example_parts["base_block_b"])
    c = shape_signature(example_parts["base_block_c"])
    assert a == b == c, "纯平移副本的签名应完全一致"


def test_signature_distinguishes_different_shapes(example_parts):
    """方块 vs 轴，签名必须不同。"""
    block = shape_signature(example_parts["base_block_a"])
    shaft = shape_signature(example_parts["shaft"])
    assert block != shaft


def test_signature_scale_sensitive(example_parts):
    """尺寸不同 -> 签名不同（防止只看拓扑的漏判）。"""
    p = copy.deepcopy(example_parts["base_block_a"])
    p["theory_bbox_mm"] = [-20.0, -10.0, 0.0, 30.0, 10.0, 10.0]  # X 拉长 10mm
    assert shape_signature(p) != shape_signature(example_parts["base_block_a"])


def test_signature_axis_flip_differs(example_parts):
    """镜像（轴向反号）不应被误判为同一形状。"""
    p = copy.deepcopy(example_parts["shaft"])
    p["terms"] = [dict(t) for t in p["terms"]]
    for t in p["terms"]:
        if t.get("kind") == "revolve_seg":
            t0, t1 = t["t"]
            t["t"] = [-t1, -t0]
    assert shape_signature(p) != shape_signature(example_parts["shaft"])


def test_signature_handles_empty():
    assert shape_signature({"terms": []}) == ((), ())
    assert shape_signature({}) == ((), ())


# ------------------------------------------------------------------ 分组
def test_plan_families_4_parts_2_shapes(example_parts):
    """4 零件 → 2 个唯一形状，其中 1 组含 3 个成员。"""
    fams = plan_families(example_parts)
    rep = family_report(fams)
    assert rep["total_instances"] == 4
    assert rep["unique_shapes"] == 2
    assert rep["reusable_copies"] == 2

    groups = [f for f in fams if f["is_duplicate_group"]]
    assert len(groups) == 1
    assert len(groups[0]["members"]) == 3
    assert groups[0]["master"] == "base_block_a"


def test_plan_families_covers_all(example_parts):
    """分组必须无遗漏、无重复。"""
    fams = plan_families(example_parts)
    covered = [n for f in fams for n in f["members"]]
    assert sorted(covered) == sorted(example_parts.keys())
    assert len(covered) == len(set(covered))


def test_plan_instances_4_parts_build_2(example_parts):
    """4 零件 / 4 实例 / 只建 2 件。"""
    rows = plan_instances(example_parts)
    rep = instance_report(rows)
    assert rep["instances"] == 4
    assert rep["to_build"] == 2
    assert rep["saved_parts"] == 2
    assert sorted(rep["masters"]) == ["base_block_a", "shaft"]


def test_plan_instances_offsets(example_parts):
    """每个副本的平移量必须与 bbox 差一致。"""
    rows = {r["part"]: r for r in plan_instances(example_parts)}
    assert rows["base_block_a"]["offset_mm"] == [0.0, 0.0, 0.0]
    assert rows["base_block_b"]["offset_mm"] == [60.0, 0.0, 0.0]
    assert rows["base_block_c"]["offset_mm"] == [0.0, 40.0, 0.0]
    assert rows["base_block_a"]["is_master"] is True
    assert rows["base_block_b"]["is_master"] is False


def test_plan_instances_rejects_list():
    """传 list 时必须报错（契约是 dict），避免 README 写错时静默错误。"""
    with pytest.raises(AttributeError):
        plan_instances([{"name": "x", "terms": [], "theory_bbox_mm": [0] * 6}])


# --------------------------------------------------------------- 平移差
def test_translation_between_ok():
    a = [0.0, 0.0, 0.0, 10.0, 20.0, 30.0]
    b = [5.0, -3.0, 2.0, 15.0, 17.0, 32.0]
    assert translation_between(a, b) == [5.0, -3.0, 2.0]


def test_translation_between_rejects_resize():
    """尺寸不同 -> 不是纯平移，必须抛 ValueError。"""
    a = [0.0, 0.0, 0.0, 10.0, 10.0, 10.0]
    b = [0.0, 0.0, 0.0, 20.0, 10.0, 10.0]
    with pytest.raises(ValueError):
        translation_between(a, b)


def test_translation_between_requires_bbox():
    with pytest.raises(ValueError):
        translation_between(None, [0, 0, 0, 1, 1, 1])
