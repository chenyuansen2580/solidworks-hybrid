# -*- coding: utf-8 -*-
"""hybrid_reuse.py —— 重复几何复用 + 装配断点续建。

解决两类实测浪费（ballscrew_slide_v1，2026-11-23）：

  1) 重复建同形状零件
     35 件里只有 20 个唯一几何，15 件是纯平移副本 —— 白建 423 个特征(43%)、
     1.97 MB(44%)、以及约 43% 的建模时间。
     → plan_families() 自动按「与位置无关的形状签名」分组，只建母件；
       reuse_family() 用 SaveAs 派生副本并按偏移重画草图（或直接复用母件多实例）。

  2) 装配出错就整轮重来
     build_asm 无断点：插 35 件 → 35 次 Fix → 36 条配合 是一个原子块，
     歪一件就从头再来（实测返工 5 次全量）。
     → AssemblySession 把「已插入组件 / 已加配合 / 尝试次数」写 state.json，
       --resume 时跳过已完成项，只补做失败的那一条。

用法见文件末尾 __main__ 的 selftest。
"""
from __future__ import annotations

import hashlib
import json
import os

# ----------------------------------------------------------------- 形状签名
def _r(v, nd=3):
    return round(float(v), nd)


def shape_signature(part):
    """把零件压成「与位置无关」的签名。

    part 接受两种输入：
      * theory.json 里的单个零件 dict（含 terms + theory_bbox_mm）—— 推荐
      * 纯 terms 列表（无 bbox 时退化为只按形状类型分组，可能误并）

    归一化基准 = 该零件 theory_bbox_mm 的最小角，因此平移后签名不变。
    回转件（无 box 项）也能正确区分：走 revolve_seg 的 r_add/r_sub/len。
    """
    if isinstance(part, dict):
        terms = part.get("terms") or []
        bbox = part.get("theory_bbox_mm")
    else:
        terms, bbox = list(part or []), None

    if not terms:
        return ((), ())

    # 尺寸：优先用 theory_bbox_mm（对回转件也正确）
    if bbox and len(bbox) == 6:
        ox, oy, oz = float(bbox[0]), float(bbox[1]), float(bbox[2])
        size = (_r(float(bbox[3]) - ox), _r(float(bbox[4]) - oy),
                _r(float(bbox[5]) - oz))
    else:
        # 退化：从 box/hole 项推
        xs, ys, zs = [], [], []
        for t in terms:
            if t.get("kind") in ("box", "pocket") and t.get("bbox"):
                b = t["bbox"]
                xs += [b[0], b[3]]; ys += [b[1], b[4]]; zs += [b[2], b[5]]
        if not xs:
            return ((), tuple(sorted(str(t.get("kind")) for t in terms)))
        ox, oy, oz = min(xs), min(ys), min(zs)
        size = (_r(max(xs) - ox), _r(max(ys) - oy), _r(max(zs) - oz))

    axis_origin = {"X": ox, "Y": oy, "Z": oz}
    sig = []
    for t in terms:
        k = t.get("kind")
        if k in ("box", "pocket") and t.get("bbox"):
            b = t["bbox"]
            sig.append((k, _r(b[3] - b[0]), _r(b[4] - b[1]), _r(b[5] - b[2]),
                        _r(b[0] - ox), _r(b[1] - oy), _r(b[2] - oz)))
        elif k == "hole":
            c = t.get("center") or [0.0, 0.0]
            ax = t.get("axis")
            # 沿孔轴的起点 = 圆心的另一个坐标；这里用 center 归一 + len/r 足够判别
            sig.append(("hole", ax, _r(t.get("r") or 0.0),
                        _r(t.get("len") or 0.0),
                        _r(c[0] - ox), _r(c[1] - oy)))
        elif k == "revolve_seg":
            ax = t.get("axis")
            tt = t.get("t") or [0.0, 0.0]
            base = axis_origin.get(ax, 0.0)
            sig.append(("rev", ax, _r(t.get("r_add") or 0.0),
                        _r(t.get("r_sub") or 0.0),
                        _r(t.get("len") or 0.0),
                        _r(float(tt[0]) - base)))
        else:
            sig.append((k,))
    return size, tuple(sorted(sig, key=str))


def plan_families(theory_parts):
    """按形状签名分组。返回 families: [{key, master, members, derived, ...}]。

    theory_parts: {name: {"terms": [...], "theory_bbox_mm": [...]}}
    """
    groups = {}
    for name, p in theory_parts.items():
        size, sig = shape_signature(p)
        groups.setdefault((size, sig), []).append(name)

    families = []
    for (size, sig), names in groups.items():
        names = sorted(names)
        families.append({
            "key": hashlib.sha1(repr((size, sig)).encode("utf-8")).hexdigest()[:12],
            "master": names[0],
            "members": names,
            "derived": names[1:],
            "shape_size_mm": list(size),
            "is_duplicate_group": len(names) > 1,
        })
    families.sort(key=lambda f: (-len(f["members"]), f["master"]))
    return families


def family_report(families):
    """把复用计划压成一行行可打印/可入库的统计。"""
    total = sum(len(f["members"]) for f in families)
    dup = sum(len(f["derived"]) for f in families)
    rows = []
    for f in families:
        if f["is_duplicate_group"]:
            rows.append({"master": f["master"], "count": len(f["members"]),
                         "derived": f["derived"],
                         "size_mm": f["shape_size_mm"]})
    return {"total_instances": total,
            "unique_shapes": len(families),
            "reusable_copies": dup,
            "saving_pct": round(100.0 * dup / total, 1) if total else 0.0,
            "groups": rows}


# ------------------------------------------------------------- 派生：平移副本
def translation_between(bbox_a, bbox_b):
    """两个同形状零件 bbox 的纯平移差 (mm)。"""
    if not bbox_a or not bbox_b:
        raise ValueError("需要两个 bbox")
    devs = [abs((bbox_b[i] - bbox_a[i]) - (bbox_b[3 + i] - bbox_a[3 + i]))
            for i in range(3)]
    if max(devs) > 1e-6:
        raise ValueError("两个 bbox 尺寸不同，不是纯平移副本 (dev=%s)" % devs)
    return [bbox_b[i] - bbox_a[i] for i in range(3)]


def derive_by_saveas(sw, V, master_path, out_path, offset_mm):
    """用 SaveAs 派生副本，再把草图整体平移 offset_mm。

    ★ 状态：**未实现，且不再需要**（2026-11-23 判定）。
      实测证明「同零件多实例」路径完全够用，见下。

    多实例路径已验证通过（`templates/verify_reuse.py`，结果 `trace_reuse.json`）：

      R1 同一 SLDPRT 在同一装配插 4 次 -> 得到 master_block-1..4，名称互异   pass
      R2 4 个实例 set_component_transform 平移后 bbox 与「母件+偏移」逐项比对
         max dev = 0.000000 mm                                              pass
      R3 4 个分开的实例，干涉 status=pass, count=0（复用不产生假干涉）      pass
      R4 负向对照：故意让第 5 个实例重叠 20 mm -> warn, count=1,
         max_volume = 3717.26 mm³（干涉判定在复用实例上照常生效）           pass
      R5 4 个实例 bbox 尺寸全等于母件（无变体）                              pass
      R6 复用实例上可正常建立 MateConcentric 并写入特征树                   pass

    结论：**优先用多实例**。只有当某个实例需要独立的 BOM 条目 / 独立自定义属性 /
    独立配置时，才需要真正的派生文件；那种场景建议在 design.yaml 里就拆成两个零件，
    而不是事后 SaveAs 派生（派生会带来面引用断链风险，本机未验证）。
    """
    raise NotImplementedError(
        "本机未验证 SaveAs+批量平移草图的可靠性；请改用『同零件多实例』：\n"
        "  只存 1 个 SLDPRT，装配里插 N 次，靠 set_component_transform 平移。\n"
        "  已实测 6/6 通过，见 verify_reuse.py / trace_reuse.json。")


# ------------------------------------------------------- 多实例复用（已验证）
def plan_instances(theory_parts):
    """把 plan_families() 的结果转成「装配实例表」。

    返回 [{part, master, offset_mm}]，offset 由 theory bbox 差值算出。
    这是 §0 推荐路径的输入：只建 master 那一件，其余全靠平移实例。
    """
    fams = plan_families(theory_parts)
    rows = []
    for f in fams:
        mb = theory_parts[f["master"]]["theory_bbox_mm"]
        for name in f["members"]:
            bb = theory_parts[name]["theory_bbox_mm"]
            off = [round(bb[i] - mb[i], 4) for i in range(3)]
            rows.append({"part": name, "master": f["master"],
                         "offset_mm": off, "is_master": name == f["master"]})
    return rows


def instance_report(rows):
    masters = sorted({r["master"] for r in rows})
    return {"to_build": len(masters),
            "instances": len(rows),
            "saved_parts": len(rows) - len(masters),
            "masters": masters}


# --------------------------------------------------------------- 装配断点
class AssemblySession:
    """装配断点续建。

    每次插入组件 / 添加配合后立刻落盘 state.json；异常退出后
    `AssemblySession.load(..., resume=True)` 只补做未完成项。

    state 结构：
      {
        "asm_path": ...,
        "components": {"base": {"instance": "base-1", "ok": true}, ...},
        "mates":     {"CC_base_shaft": {"ok": true, "axis_dist_mm": 0.0}, ...},
        "attempts":  {"CC_base_shaft": 2},
        "failures":  [...]
      }
    """

    def __init__(self, state_path, asm_path=None):
        self.state_path = state_path
        self.state = {"asm_path": asm_path, "components": {}, "mates": {},
                      "attempts": {}, "failures": []}

    # ---------------- 持久化
    def load(self, resume=True):
        if resume and os.path.exists(self.state_path):
            with open(self.state_path, "r", encoding="utf-8") as f:
                self.state = json.load(f)
        return self.state

    def save(self):
        d = os.path.dirname(os.path.abspath(self.state_path))
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_path)       # 原子写，防半截文件
        return self.state_path

    # ---------------- 组件
    def component_done(self, key):
        return bool(self.state["components"].get(key, {}).get("ok"))

    def mark_component(self, key, instance=None, **extra):
        rec = {"ok": True, "instance": instance}
        rec.update(extra)
        self.state["components"][key] = rec
        self.save()
        return rec

    def pending_components(self, all_keys):
        return [k for k in all_keys if not self.component_done(k)]

    # ---------------- 配合
    def mate_done(self, key):
        return bool(self.state["mates"].get(key, {}).get("ok"))

    def mark_mate(self, key, **extra):
        rec = {"ok": True}
        rec.update(extra)
        self.state["mates"][key] = rec
        self.save()
        return rec

    def bump_attempt(self, key):
        n = int(self.state["attempts"].get(key, 0)) + 1
        self.state["attempts"][key] = n
        self.save()
        return n

    def mark_failure(self, stage, key, error, max_retry=3):
        self.state["failures"].append(
            {"stage": stage, "key": key, "error": str(error)[:400],
             "attempt": self.state["attempts"].get(key, 0)})
        self.save()
        return len(self.state["failures"])

    def pending_mates(self, all_keys, max_retry=3):
        """返回还需要做的配合（未完成且未超重试次数）。"""
        out = []
        for k in all_keys:
            if self.mate_done(k):
                continue
            if int(self.state["attempts"].get(k, 0)) >= max_retry:
                continue
            out.append(k)
        return out

    # ---------------- 汇总
    def summary(self, total_components, total_mates):
        return {
            "components_done": sum(1 for v in self.state["components"].values()
                                   if v.get("ok")),
            "components_total": total_components,
            "mates_done": sum(1 for v in self.state["mates"].values() if v.get("ok")),
            "mates_total": total_mates,
            "failures": len(self.state["failures"]),
            "attempts": self.state["attempts"],
        }


# ------------------------------------------------------------------ selftest
def _selftest():
    """用真实 theory.json 验证分组逻辑（不碰 SolidWorks）。"""
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else \
        r"D:\yysls\ballscrew_slide_v1\theory.json"
    with open(p, "r", encoding="utf-8") as f:
        theory = json.load(f)
    fams = plan_families(theory["parts"])
    rep = family_report(fams)
    print(json.dumps(rep, ensure_ascii=False, indent=2))

    # 断言：分组结果必须覆盖全部零件
    covered = [n for f in fams for n in f["members"]]
    assert sorted(covered) == sorted(theory["parts"].keys()), "分组漏件"
    print("\n[OK] 覆盖 %d 件 / %d 个唯一形状 / 可复用 %d 件 (%.1f%%)"
          % (rep["total_instances"], rep["unique_shapes"],
             rep["reusable_copies"], rep["saving_pct"]))


if __name__ == "__main__":
    _selftest()
