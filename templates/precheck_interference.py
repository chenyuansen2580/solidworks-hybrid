# -*- coding: utf-8 -*-
"""precheck_interference.py —— 建模前的解析干涉预检（不碰 SolidWorks）。

背景：ballscrew_slide_v1 的 6 处假干涉是在**全量装配完成后**才发现的。
但 theory.json 里已有全部零件的理论 bbox 与实体分解，两两相交完全可以
纯解析算出来 —— 应该在建模前就跑，把设计级冲突提前到最便宜的阶段。

它不能替代 sw_measure.inspect_interference（那才是权威判据），
但能在花 30 分钟建 35 个零件之前，先花 0.1 秒发现明显撞车。

用法：
    python precheck_interference.py <theory.json> [--strict]

判读规则（重要，避免把正常工程接触误报成干涉）：
  * bbox 相交 ≠ 体积干涉。贴合面（导轨坐底座、垫块坐滑块）必然相交。
  * 因此只报「相交体积占较小件 > 阈值」的候选，供人工按配合意图判读。
  * 真正的判据仍是装配后的 sw_measure.inspect_interference。

退出码：0 = 无高风险候选；1 = 有需人工确认的候选（strict 模式下 2 = 失败）
"""
from __future__ import annotations

import itertools
import json
import os
import sys

# 已知「设计上就该接触」的零件对：不算冲突。可按项目调整。
DEFAULT_CONTACTS = {
    # 轴承 / 支撑座 抱轴
    ("ballscrew", "support_bk12"), ("ballscrew", "support_bf12"),
    ("ballscrew", "coupling"), ("ballscrew", "ballnut"),
    # 螺母抱箍
    ("ballnut", "nut_seat"), ("ballnut", "nut_seat_top"),
    ("ballscrew", "nut_seat"),
    # 电机止口 / 轴
    ("nema23_motor", "motor_mount"), ("nema23_motor", "coupling"),
    # 滑块夹轨
    ("rail_pos", "block_xn90_yp45"), ("rail_pos", "block_xp90_yp45"),
    ("rail_neg", "block_xn90_yn45"), ("rail_neg", "block_xp90_yn45"),
}


def ov(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def bbox_volume(bb):
    return max(0.0, bb[3] - bb[0]) * max(0.0, bb[4] - bb[1]) * max(0.0, bb[5] - bb[2])


def solid_terms(part):
    """取出参与体积的实体段（box / revolve_seg），用于更细的相交估计。"""
    out = []
    for t in part.get("terms") or []:
        k = t.get("kind")
        if k == "box":
            b = t["bbox"]
            out.append(("box", b[0], b[1], b[2], b[3], b[4], b[5]))
        elif k == "revolve_seg":
            ax = t.get("axis")
            rr = max(float(t.get("r_add") or 0.0), float(t.get("r_sub") or 0.0))
            tt = t.get("t") or [0.0, 0.0]
            # 用轴向包络 + 半径建一个保守包围盒
            if ax == "X":
                out.append(("box", tt[0], -rr, -rr, tt[1], rr, rr))
            elif ax == "Y":
                out.append(("box", -rr, tt[0], -rr, rr, tt[1], rr))
            else:
                out.append(("box", -rr, -rr, tt[0], rr, rr, tt[1]))
    return out


def pair_overlap(a_terms, b_terms):
    """保守估计两零件实体的最大重叠体积（取逐段 bbox 相交后合并的近似值）。

    回转段的包围盒在装配坐标里其实是"以轴线为中心"的，
    与 theory bbox 的绝对坐标不同源，因此这里只用它做**同尺度**比较时
    才可靠；主判据仍用整体 bbox。为避免误报，本函数只用于排序提示。
    """
    best = 0.0
    for ta in a_terms:
        a = ta[1:]
        for tb in b_terms:
            b = tb[1:]
            ox = ov(a[0], a[3], b[0], b[3])
            oy = ov(a[1], a[4], b[1], b[4])
            oz = ov(a[2], a[5], b[2], b[5])
            if ox > 1e-6 and oy > 1e-6 and oz > 1e-6:
                best = max(best, ox * oy * oz)
    return best


def main():
    if len(sys.argv) < 2:
        print("usage: precheck_interference.py <theory.json> [--strict]")
        return 2
    path = sys.argv[1]
    strict = "--strict" in sys.argv
    with open(path, "r", encoding="utf-8") as f:
        theory = json.load(f)
    parts = theory["parts"]

    names = sorted(parts)
    vol = {n: bbox_volume(parts[n]["theory_bbox_mm"]) for n in names}

    hits = []
    total_pairs = 0
    for a, b in itertools.combinations(names, 2):
        total_pairs += 1
        A = parts[a]["theory_bbox_mm"]
        B = parts[b]["theory_bbox_mm"]
        ox = ov(A[0], A[3], B[0], B[3])
        oy = ov(A[1], A[4], B[1], B[4])
        oz = ov(A[2], A[5], B[2], B[5])
        if ox <= 1e-6 or oy <= 1e-6 or oz <= 1e-6:
            continue
        inter = ox * oy * oz
        smaller = min(vol[a], vol[b]) or 1.0
        ratio = inter / smaller
        hits.append({
            "a": a, "b": b,
            "bbox_overlap_mm3": round(inter, 3),
            "ratio_of_smaller": round(ratio, 4),
            "known_contact": (a, b) in DEFAULT_CONTACTS
                             or (b, a) in DEFAULT_CONTACTS,
        })

    # 分三档
    expected = [h for h in hits if h["known_contact"]]
    unknown = [h for h in hits if not h["known_contact"]]
    suspicious = [h for h in unknown if h["ratio_of_smaller"] > 0.05]

    out = {
        "theory": os.path.abspath(path),
        "part_count": len(parts),
        "pair_count": total_pairs,
        "bbox_intersecting_pairs": len(hits),
        "known_contacts": len(expected),
        "unclassified_contacts": len(unknown),
        "suspicious_candidates": len(suspicious),
        "verdict": "review" if suspicious else "pass",
        "note": "bbox 相交 != 体积干涉；本脚本只做建模前的早期筛查，"
                "最终判据是装配后的 sw_measure.inspect_interference",
        "suspicious": sorted(suspicious, key=lambda x: -x["ratio_of_smaller"]),
        "expected": sorted(expected, key=lambda x: -x["ratio_of_smaller"]),
        "unclassified": sorted(unknown, key=lambda x: -x["ratio_of_smaller"]),
    }

    print("=" * 74)
    print("零件 %d 件 / 两两组合 %d 对" % (out["part_count"], out["pair_count"]))
    print("bbox 相交 %d 对 -> 已知设计接触 %d / 未分类 %d / 可疑 %d"
          % (out["bbox_intersecting_pairs"], out["known_contacts"],
             out["unclassified_contacts"], out["suspicious_candidates"]))
    print("verdict:", out["verdict"])
    if suspicious:
        print("\n需人工确认的候选（bbox 重叠占较小件 > 5%，且不在已知接触表内）：")
        for h in out["suspicious"]:
            print("  %-22s %-22s overlap=%10.1f mm3  ratio=%.1f%%"
                  % (h["a"], h["b"], h["bbox_overlap_mm3"],
                     h["ratio_of_smaller"] * 100))
    if expected:
        print("\n已知设计接触（正常，不算干涉）：")
        for h in out["expected"]:
            print("  %-22s %-22s ratio=%.1f%%"
                  % (h["a"], h["b"], h["ratio_of_smaller"] * 100))

    outp = os.path.splitext(path)[0] + "_precheck.json"
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nwritten:", outp)

    if strict and suspicious:
        return 2
    return 1 if suspicious else 0


if __name__ == "__main__":
    sys.exit(main())
