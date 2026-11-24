# -*- coding: utf-8 -*-
"""test_precheck.py — 解析干涉预检的正负对照（纯 Python，不依赖 SolidWorks）。

关键：既要能**检出真重叠**，也要能**不误报**不重叠的情况。
"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(PKG_ROOT, "templates", "precheck_interference.py")


def _write_theory(tmp_path, parts, name="theory.json"):
    p = tmp_path / name
    data = {"parts": parts}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return str(p)


def _block(name, x0, y0, z0, dx=10.0, dy=10.0, dz=10.0):
    return {
        "cn": name,
        "theory_bbox_mm": [x0, y0, z0, x0 + dx, y0 + dy, z0 + dz],
        "terms": [{"kind": "box",
                   "bbox": [x0, y0, z0, x0 + dx, y0 + dy, z0 + dz],
                   "volume": dx * dy * dz}],
    }


def _run(theory_path):
    """调用预检脚本。

    ★ 必须显式指定 encoding="utf-8" 与 errors="replace"：
      脚本输出含中文，Windows 默认 GBK 解码会抛 UnicodeDecodeError
      （在 Linux CI 上是 UTF-8 不会暴露，属于跨平台隐患）。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, SCRIPT, theory_path],
                       capture_output=True, text=True, timeout=120,
                       encoding="utf-8", errors="replace", env=env)
    outp = theory_path.replace(".json", "_precheck.json")
    data = None
    if os.path.isfile(outp):
        with open(outp, "r", encoding="utf-8") as f:
            data = json.load(f)
    return r, data


# ------------------------------------------------------------------ 负例
def test_no_overlap_no_false_positive(tmp_path):
    """完全分开的两个零件：不得报可疑。"""
    parts = {
        "a": _block("a", 0, 0, 0),
        "b": _block("b", 100, 0, 0),
    }
    tp = _write_theory(tmp_path, parts)
    r, data = _run(tp)
    assert data is not None, r.stdout + r.stderr
    assert data["bbox_intersecting_pairs"] == 0
    assert data["suspicious_candidates"] == 0
    assert data["verdict"] == "pass"
    assert r.returncode == 0


def test_touching_faces_not_suspicious(tmp_path):
    """恰好贴合（共面接触）：bbox 相交体积为 0，不应报可疑。"""
    parts = {
        "lower": _block("lower", 0, 0, 0, dz=10.0),
        "upper": _block("upper", 0, 0, 10.0, dz=10.0),
    }
    tp = _write_theory(tmp_path, parts)
    _, data = _run(tp)
    assert data["suspicious_candidates"] == 0
    assert data["verdict"] == "pass"


# ------------------------------------------------------------------ 正例
def test_real_overlap_detected(tmp_path):
    """真重叠（占较小件 >5%）：必须报可疑并返回非 0。"""
    parts = {
        "a": _block("a", 0, 0, 0),
        "b": _block("b", 5, 0, 0),      # 与 a 重叠 5x10x10 = 500 mm3 = 50%
    }
    tp = _write_theory(tmp_path, parts)
    r, data = _run(tp)
    assert data["suspicious_candidates"] == 1
    hit = data["suspicious"][0]
    assert {hit["a"], hit["b"]} == {"a", "b"}
    assert hit["ratio_of_smaller"] > 0.05
    assert data["verdict"] == "review"
    assert r.returncode == 1


def test_known_contact_whitelisted(tmp_path):
    """命中已知设计接触白名单：报为 expected，不算可疑。"""
    parts = {
        "ballscrew": _block("ballscrew", 0, 0, 0),
        "support_bk12": _block("support_bk12", 2, 0, 0),
    }
    tp = _write_theory(tmp_path, parts)
    _, data = _run(tp)
    assert data["known_contacts"] == 1
    assert data["suspicious_candidates"] == 0
    assert data["verdict"] == "pass"


def test_small_overlap_below_threshold(tmp_path):
    """重叠占比不足 5%：归入 unclassified，不进 suspicious。

    两个 100x100x100 的块（各 1e6 mm³），三轴各错位 97mm →
    只重叠 3x3x3 = 27 mm³，占较小件 0.0027%，远低于 5% 阈值。
    """
    parts = {
        "big_a": _block("big_a", 0, 0, 0, dx=100.0, dy=100.0, dz=100.0),
        "big_c": _block("big_c", 97, 97, 97, dx=100.0, dy=100.0, dz=100.0),
    }
    tp = _write_theory(tmp_path, parts)
    _, data = _run(tp)
    assert data["bbox_intersecting_pairs"] == 1, "应检出 bbox 相交"
    assert data["suspicious_candidates"] == 0, (
        "0.0027%% 重叠不应报可疑，实际 %s" % data["suspicious_candidates"])
    assert data["unclassified_contacts"] >= 1
    assert data["verdict"] == "pass"


def test_overlap_just_above_threshold(tmp_path):
    """重叠略超 5%：必须报可疑（阈值边界正向验证）。

    两件各 100x100x100；三轴各错位 95mm → 重叠 5x5x5=125，占 0.0125%。
    改用单轴错位 90（重叠 10x100x100 = 1e5，占 10%）确保超阈值。
    """
    parts = {
        "big_a": _block("big_a", 0, 0, 0, dx=100.0, dy=100.0, dz=100.0),
        "big_b": _block("big_b", 90, 0, 0, dx=100.0, dy=100.0, dz=100.0),
    }
    tp = _write_theory(tmp_path, parts)
    _, data = _run(tp)
    assert data["suspicious_candidates"] == 1
    assert data["verdict"] == "review"


# ------------------------------------------------------------------ 输出
def test_writes_precheck_json(tmp_path):
    parts = {"a": _block("a", 0, 0, 0)}
    tp = _write_theory(tmp_path, parts)
    r, data = _run(tp)
    assert os.path.isfile(tp.replace(".json", "_precheck.json"))
    assert data["part_count"] == 1
    assert "note" in data and "sw_measure" in data["note"]


def test_requires_argument():
    r = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True)
    assert r.returncode == 2
