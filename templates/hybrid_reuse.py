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
import sys

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
    """⚠ 此路径未验证，禁止调用，请改用同零件多实例。

    用 SaveAs 派生副本，再把草图整体平移 offset_mm。

    ★ 状态：**未实现，且不再需要**（2026-11-23 判定）。
      实测证明「同零件多实例」路径完全够用，见下。
      SaveAs 派生会带来面引用断链风险，本机未验证，因此本函数直接抛
      NotImplementedError —— 读到函数名不要调它，用 plan_instances() +
      set_component_transform 平移实例即可。

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
# 仓库/包根目录（examples/ 在其下）
_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.dirname(_HERE)
_EXAMPLE = os.path.join(_PKG_ROOT, "examples", "theory.json")


def _builtin_minimal_theory():
    """内置最小示例：3 个零件（2 个互为纯平移副本 + 1 根不同形状的轴）。

    用途：外部 theory.json 缺失时的兜底，保证自检永远能跑断言而不是崩。
    与 examples/theory.json 的字段契约完全一致，只是件数更少。
    """
    def block(x0, y0):
        return {
            "cn": "内置方块 @(%g,%g)" % (x0, y0),
            "material": "6061 合金",
            "theory_volume_mm3": 8000.0,
            "volume_formula": "box",
            "theory_bbox_mm": [x0, y0, 0.0, x0 + 20.0, y0 + 10.0, 10.0],
            "bbox_size_mm": [20.0, 10.0, 10.0],
            "terms": [{"kind": "box",
                       "bbox": [x0, y0, 0.0, x0 + 20.0, y0 + 10.0, 10.0],
                       "volume": 8000.0}],
            "primitive_count": {"add": 1, "sub": 0},
            "issues": [],
            "hard_issues": [],
        }

    return {
        "meta": {"project": "builtin-minimal", "part_count": 3},
        "parts": {
            "blk_a": block(0.0, 0.0),
            "blk_b": block(40.0, 0.0),      # blk_a 的纯平移副本 (+40, 0, 0)
            "shaft": {
                "cn": "内置轴",
                "material": "合金钢",
                "theory_volume_mm3": 3141.59,
                "volume_formula": "π·r²·L",
                "theory_bbox_mm": [-50.0, -5.0, -5.0, 50.0, 5.0, 5.0],
                "bbox_size_mm": [100.0, 10.0, 10.0],
                "terms": [{"kind": "revolve_seg", "axis": "X",
                           "t": [-50.0, 50.0], "r_add": 5.0, "r_sub": 0.0,
                           "len": 100.0, "volume": 3141.59}],
                "primitive_count": {"add": 1, "sub": 0},
                "issues": [],
                "hard_issues": [],
            },
        },
    }


def resolve_theory_path(cli_arg=None):
    """解析 theory.json 路径。

    顺序：
      1) 命令行参数
      2) 环境变量 DSH_SW_THEORY
      3) 环境变量 DSH_SW_WORKDIR 下的 theory.json
      4) 仓库内 examples/theory.json
      返回 (path 或 None, 来源说明)
    """
    if cli_arg:
        return (cli_arg if os.path.isfile(cli_arg) else None), "argv"
    env_theory = os.environ.get("DSH_SW_THEORY")
    if env_theory:
        return (env_theory if os.path.isfile(env_theory) else None), "DSH_SW_THEORY"
    workdir = os.environ.get("DSH_SW_WORKDIR")
    if workdir:
        cand = os.path.join(workdir, "theory.json")
        return (cand if os.path.isfile(cand) else None), "DSH_SW_WORKDIR"
    if os.path.isfile(_EXAMPLE):
        return _EXAMPLE, "examples/theory.json"
    return None, "builtin"


def load_theory(cli_arg=None):
    """加载 theory.json；外部缺失时回退内置最小示例（不抛错）。

    返回 (theory_dict, info)；info 含 source / path / fell_back。
    """
    path, source = resolve_theory_path(cli_arg)
    if path is None:
        return _builtin_minimal_theory(), {
            "source": "builtin", "path": None, "fell_back": True,
            "reason": "未找到外部 theory.json（argv / DSH_SW_THEORY / "
                      "DSH_SW_WORKDIR / examples 均未命中）",
        }
    with open(path, "r", encoding="utf-8") as f:
        theory = json.load(f)
    return theory, {"source": source, "path": path, "fell_back": False}


def _selftest(argv=None):
    """自检：分组 / 实例 / 平移差 三组断言。不依赖 SolidWorks，不写死路径。

    退出码：0 = 全部 PASS（含回退到内置示例）
            1 = 断言失败
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    cli = argv[0] if argv and not argv[0].startswith("-") else None

    theory, info = load_theory(cli)
    parts = theory["parts"]
    print("theory 来源: %s%s" % (info["source"],
                                 ("  (%s)" % info["path"]) if info["path"] else ""))
    if info["fell_back"]:
        print("  [SKIP] %s -> 回退内置最小示例继续跑断言" % info["reason"])

    fams = plan_families(parts)
    rep = family_report(fams)
    print(json.dumps(rep, ensure_ascii=False, indent=2))

    fails = []

    # 断言 1：分组必须覆盖全部零件，且无重复
    covered = [n for f in fams for n in f["members"]]
    if sorted(covered) != sorted(parts.keys()):
        fails.append("分组漏件或多件: covered=%d parts=%d"
                     % (len(covered), len(parts)))
    if len(covered) != len(set(covered)):
        fails.append("同一零件被分到多个组")

    # 断言 2：副本必须是母件的纯平移
    for f in fams:
        mb = parts[f["master"]]["theory_bbox_mm"]
        for d in f["derived"]:
            db = parts[d]["theory_bbox_mm"]
            try:
                off = translation_between(mb, db)
            except ValueError as e:
                fails.append("%s 不是 %s 的纯平移: %s" % (d, f["master"], e))
                continue
            if all(abs(v) < 1e-9 for v in off):
                fails.append("%s 与 %s 偏移为零，不应拆成两件" % (d, f["master"]))

    # 断言 3：实例表自洽
    rows = plan_instances(parts)
    irep = instance_report(rows)
    if irep["instances"] != len(parts):
        fails.append("实例数 %d != 零件数 %d" % (irep["instances"], len(parts)))
    if irep["to_build"] != rep["unique_shapes"]:
        fails.append("要建件数 %d != 唯一形状数 %d"
                     % (irep["to_build"], rep["unique_shapes"]))
    if irep["saved_parts"] != rep["reusable_copies"]:
        fails.append("节省件数 %d != 可复用副本数 %d"
                     % (irep["saved_parts"], rep["reusable_copies"]))

    print()
    if fails:
        for x in fails:
            print("  [FAIL]", x)
        print("\n[FAIL] 自检未通过，共 %d 条" % len(fails))
        return 1

    print("[PASS] 覆盖 %d 件 / %d 个唯一形状 / 可复用 %d 件 (%.1f%%) / 要建 %d 件"
          % (rep["total_instances"], rep["unique_shapes"],
             rep["reusable_copies"], rep["saving_pct"], irep["to_build"]))
    return 0


if __name__ == "__main__":
    sys.exit(_selftest())
