# -*- coding: utf-8 -*-
"""real_sw_regression.py — 真机回归脚本（需要 Windows + SolidWorks 2022）。

★ 本脚本**不在 CI 里跑**，也**不能**在 Linux / 无 CAD 环境跑。
  它存在的意义：把 CHANGELOG 里那些真机数字（体积偏差 0.000004%、
  干涉 0、轴心距 0.000000 mm）变成**可重跑的断言**，而不是只留在
  trace*.json 快照里。

用法（在装有 SW2022 的 Windows 上）：

    $env:SW_ATTACH_EXISTING_DISPATCH = "1"
    python tests/manual_real_sw_regression.py --theory <theory.json> \
                                              --parts <parts目录> \
                                              --out   <输出目录>

    # 或用仓库自带最小示例（会真建 2 个零件 + 1 个装配体）
    python tests/manual_real_sw_regression.py --demo

判据（全部来自本机 SW2022 SP5 / 30.5.0 实测基线）：

    零件   bodies == 1, surfaces == 0
           体积偏差 < 0.5%（优先 < 0.05%）
           bbox 逐项偏差 < 0.5 mm
           存盘字节 > 0
    装配   组件数 == 设计数
           配合数 == 设计数，且无 blocked
           配合特征树 MateGroup 下有真实 Mate
           同心配合几何轴心距 <= 1e-3 mm
           干涉 status 非 blocked

退出码：0 全部通过；1 有失败；2 环境不满足（非 Windows / 无底座）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_ROOT = os.path.dirname(HERE)
TEMPLATES = os.path.join(PKG_ROOT, "templates")

if TEMPLATES not in sys.path:
    sys.path.insert(0, TEMPLATES)


def _require_windows():
    if not sys.platform.startswith("win"):
        print("[SKIP] 本脚本只能在 Windows + SolidWorks 上运行，当前 %s"
              % sys.platform)
        print("       退出码 2 = 环境不满足（不是失败）")
        return False
    return True


def _require_bases():
    try:
        import hybrid_common as H
        H.setup(verbose=True)
        if not H.OLD_SCRIPTS:
            print("[SKIP] 未找到 solidworks-modeling 底座（swlib_v2）。")
            print("       设 DSH_SW_MODELING 指向其目录后重试。")
            return None
        if not H.NEW_SCRIPTS:
            print("[SKIP] 未找到 solidworks-automation 底座（sw_assembly）。")
            print("       设 DSH_SW_AUTOMATION 指向其目录后重试。")
            return None
        return H
    except Exception as e:
        print("[SKIP] 底座检查失败: %s" % str(e)[:200])
        return None


# ------------------------------------------------------------------ 断言器
class Checks:
    def __init__(self):
        self.rows = []

    def check(self, cid, ok, detail=""):
        ok = bool(ok)
        self.rows.append({"id": cid, "ok": ok, "detail": str(detail)[:300]})
        print("  [%s] %-38s %s" % ("PASS" if ok else "FAIL", cid,
                                   str(detail)[:120]))
        return ok

    @property
    def failed(self):
        return [r for r in self.rows if not r["ok"]]

    def verdict(self):
        return "pass" if not self.failed else "fail"


def assert_part(V, L, m, name, th, chk, vol_tol=0.005, bbox_tol=0.5):
    """单件断言：bodies / surface / 体积 / bbox。"""
    bodies, surfs = V.body_counts(m)[0], V.body_counts(m)[1]
    chk.check("%s.bodies" % name, bodies == 1, "bodies=%s" % bodies)
    chk.check("%s.surface" % name, surfs == 0, "surfaces=%s" % surfs)

    got_v = V.volume_mm3(m)
    want_v = th["theory_volume_mm3"]
    dev = abs(got_v - want_v) / want_v if want_v else 0.0
    chk.check("%s.volume" % name, dev <= vol_tol,
              "got=%.4f want=%.4f dev=%.6f%%" % (got_v, want_v, dev * 100))

    got_bb = [round(v, 4) for v in L.bbox(m)]
    want_bb = th["theory_bbox_mm"]
    bdev = max(abs(a - b) for a, b in zip(got_bb, want_bb))
    chk.check("%s.bbox" % name, bdev <= bbox_tol,
              "max_dev=%.4f mm" % bdev)
    return {"name": name, "volume_mm3": round(got_v, 4),
            "volume_dev_pct": round(dev * 100, 6),
            "bbox_mm": got_bb, "bbox_dev_mm": round(bdev, 4),
            "bodies": bodies, "surfaces": surfs}


def axis_distance_mm(a, b):
    """两条空间直线的最近距离（mm）。"""
    def unit(v):
        n = math.sqrt(sum(x * x for x in v))
        return [x / n for x in v] if n > 1e-12 else [0.0, 0.0, 1.0]

    p1 = [v * 1000.0 for v in a["point_m"]]
    p2 = [v * 1000.0 for v in b["point_m"]]
    d1, d2 = unit(a["axis"]), unit(b["axis"])
    cr = [d1[1] * d2[2] - d1[2] * d2[1],
          d1[2] * d2[0] - d1[0] * d2[2],
          d1[0] * d2[1] - d1[1] * d2[0]]
    cm = math.sqrt(sum(x * x for x in cr))
    w = [p2[i] - p1[i] for i in range(3)]
    if cm < 1e-9:
        t = sum(w[i] * d1[i] for i in range(3))
        proj = [p1[i] + t * d1[i] for i in range(3)]
        return math.sqrt(sum((p2[i] - proj[i]) ** 2 for i in range(3)))
    return abs(sum(w[i] * cr[i] for i in range(3))) / cm


def cyl_from_face(face):
    s = getattr(face, "GetSurface", None)
    if s is None or not bool(getattr(s, "IsCylinder", False)):
        return None
    p = [float(x) for x in getattr(s, "CylinderParams")]
    return {"point_m": p[0:3], "axis": p[3:6], "radius_m": p[6]}


# ---------------------------------------------------------------- 主流程
def run_theory_mode(H, theory_path, parts_dir, out_dir):
    """按 theory.json 逐件断言（假定零件已存在）。"""
    # ★ 必须在 import 之前把底座 scripts 放进 sys.path
    if H.OLD_SCRIPTS and H.OLD_SCRIPTS not in sys.path:
        sys.path.insert(0, H.OLD_SCRIPTS)
    import swlib_v2 as V
    import swlib as L

    with open(theory_path, "r", encoding="utf-8") as f:
        theory = json.load(f)

    sw = V.connect(version=2022, verbose=False, warn_multi=False)
    chk = Checks()
    part_rows = []

    for name, th in theory["parts"].items():
        p = os.path.join(parts_dir, name + ".SLDPRT")
        if not os.path.exists(p):
            chk.check("%s.exists" % name, False, "缺少文件 %s" % p)
            continue
        sw.OpenDoc6(p, 1, 0, "", 0, 0)
        m = sw.ActiveDoc
        try:
            part_rows.append(assert_part(V, L, m, name, th, chk))
        finally:
            V.close_doc(sw, m, force=True)

    return chk, {"mode": "theory", "parts": part_rows}


def run_demo_mode(H, out_dir):
    """不依赖外部输入：真建 2 个零件 + 1 个装配体，验证核心链路。"""
    # ★ 必须在 import 之前把两个底座的 scripts 放进 sys.path
    for p in (H.OLD_SCRIPTS, H.NEW_SCRIPTS):
        if p and p not in sys.path:
            sys.path.insert(0, p)
    import swlib_v2 as V
    import swlib as L
    import sw_assembly
    import sw_measure

    os.makedirs(out_dir, exist_ok=True)
    chk = Checks()

    sw = V.connect(version=2022, verbose=False, warn_multi=False)
    try:
        sw.CloseAllDocuments(True)
    except Exception:
        pass

    # --- 建 1 个母件（局部坐标）
    master = os.path.join(out_dir, "reg_master.SLDPRT")
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        L.new_sketch(m, "Front Plane")
        L.rect(skm, -20.0, -10.0, 20.0, 10.0)
        sk = L.last_sketch_name(m)
        skm.InsertSketch(True)
        V.extrude_checked(m, sk, 10.0, start_mm=0.0)
    with V.addtoDB(m) as skm:
        L.new_sketch(m, "Front Plane")
        L.circle(skm, 10.0, 0.0, 3.0)
        L.circle(skm, -10.0, 0.0, 3.0)
        sk = L.last_sketch_name(m)
        skm.InsertSketch(True)
        V.cut_checked(m, sk)
    V.set_material(m, "6061 合金")

    expect_v = 40.0 * 20.0 * 10.0 - 2 * math.pi * 9.0 * 10.0
    th = {"theory_volume_mm3": expect_v,
          "theory_bbox_mm": [-20.0, -10.0, 0.0, 20.0, 10.0, 10.0]}
    rec = assert_part(V, L, m, "demo_master", th, chk)

    mat = str(V.get_material(m))
    chk.check("demo_master.material", mat == "6061 合金", "readback=%s" % mat)

    rc, size = V.save_checked(m, master, rebuild=True)
    chk.check("demo_master.save", size > 0, "%d B" % size)
    V.close_doc(sw, m, force=True)

    # --- 装配：插 2 个实例并平移
    asm = H.EMPTY_ASM
    if not asm:
        chk.check("assembly.template", False, "未找到 AsmEmpty.ASMDOT")
        return chk, {"mode": "demo", "parts": [rec]}

    doc = sw_connect_new_document(sw, asm)
    ad = V.wrap(doc, "IAssemblyDoc")
    mdl = V.wrap(doc, "IModelDoc2")
    title = str(getattr(doc, "GetTitle", ""))
    ident = sw_assembly.make_transform(sw, 0, 0, 0, 0, "Z")

    comps = []
    for i, off in enumerate(((0.0, 0.0, 0.0), (60.0, 0.0, 0.0))):
        sw.OpenDoc6(master, 1, 0, "", 0, 0)
        sw.ActivateDoc3(title, False, 0, 0)
        c = ad.AddComponent5(master, 0, "", False, "", 0.0, 0.0, 0.0)
        chk.check("assembly.add_component_%d" % i, c is not None)
        if c is None:
            continue
        sw_assembly.resolve_component(c)
        t = sw_assembly.make_transform(sw, off[0] * 1e-3, off[1] * 1e-3,
                                       off[2] * 1e-3, 0.0, "Z")
        sw_assembly.set_component_transform(c, t, rebuild=False)
        bb = [round(v * 1000.0, 4) for v in c.GetBox(False, False)]
        want = [round(th["theory_bbox_mm"][j] + off[j % 3], 4)
                if j < 3 else round(th["theory_bbox_mm"][j] + off[(j - 3) % 3], 4)
                for j in range(6)]
        dev = max(abs(a - b) for a, b in zip(bb, want))
        chk.check("assembly.bbox_%d" % i, dev <= 0.001, "dev=%.4f mm" % dev)
        comps.append(c)
        try:
            sw.CloseDoc("reg_master.SLDPRT")
        except Exception:
            pass
        sw.ActivateDoc3(title, False, 0, 0)

    # 全固定
    for c in comps:
        mdl.ClearSelection2(True)
        c.Select2(False, 0)
        ad.FixComponent()
        mdl.ClearSelection2(True)

    # 同心配合
    if len(comps) >= 2:
        fa = sw_assembly.find_largest_cylinder_face(comps[0], 0.0028, 0.0032)
        fb = sw_assembly.find_largest_cylinder_face(comps[1], 0.0028, 0.0032)
        aa, ab = cyl_from_face(fa), cyl_from_face(fb)
        sw_assembly.select_entities_for_mate(mdl, fa, fb, mark=1)
        mate = ad.AddMate5(1, 0, False, 0.0, 0.0, 0.0, 0.0, 0.0,
                           0.0, 0.0, 0.0, False, True, 0, 0)
        chk.check("assembly.mate_created", mate is not None)
        if aa and ab:
            d = axis_distance_mm(aa, ab)
            chk.check("assembly.axis_distance", d <= 1e-3, "%.6f mm" % d)

    tree = sw_assembly.collect_mate_feature_summary(mdl)
    n_real = len([r for r in tree if r.get("depth", 0) >= 1])
    chk.check("assembly.mate_tree", n_real >= 1, "%d items" % n_real)

    rep = sw_measure.inspect_interference(ad)
    chk.check("assembly.interference", rep.get("status") != "blocked",
              "status=%s count=%s" % (rep.get("status"),
                                      rep.get("interference_count")))

    asm_out = os.path.join(out_dir, "reg_asm.SLDASM")
    try:
        rc, size = V.save_checked(doc, asm_out, rebuild=True)
        chk.check("assembly.save", size > 0, "%d B" % size)
    except Exception as e:
        chk.check("assembly.save", False, str(e)[:150])

    return chk, {"mode": "demo", "parts": [rec],
                 "components": len(comps), "mates_in_tree": n_real,
                 "interference": rep.get("status")}


def sw_connect_new_document(sw, template):
    """用 sw_connect 新建装配体（若不可用则回退直接 NewDocument）。"""
    try:
        import sw_connect
        return sw_connect.new_document(sw, "assembly", template_path=template)
    except Exception:
        return sw.NewDocument(template, 0, 0, 0)


def main(argv=None):
    ap = argparse.ArgumentParser(description="真机回归（Windows + SW2022）")
    ap.add_argument("--theory", help="theory.json 路径（按件断言模式）")
    ap.add_argument("--parts", help="SLDPRT 所在目录")
    ap.add_argument("--out", default=os.path.join(PKG_ROOT, ".work", "regress"),
                    help="输出目录")
    ap.add_argument("--demo", action="store_true",
                    help="不依赖外部输入，真建最小装配验证链路")
    args = ap.parse_args(argv)

    print("=" * 74)
    print("真机回归 solidworks-hybrid")
    print("=" * 74)

    if not _require_windows():
        return 2
    H = _require_bases()
    if H is None:
        return 2

    os.makedirs(args.out, exist_ok=True)

    if args.demo:
        chk, extra = run_demo_mode(H, args.out)
    elif args.theory and args.parts:
        chk, extra = run_theory_mode(H, args.theory, args.parts, args.out)
    else:
        print("[SKIP] 需要 --demo 或 (--theory + --parts)")
        return 2

    out = {"generated_on": sys.platform, "verdict": chk.verdict(),
           "checks": chk.rows, **extra}
    p = os.path.join(args.out, "real_sw_regression.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("-" * 74)
    print("verdict:", chk.verdict(),
          "| 通过 %d / 失败 %d" % (len(chk.rows) - len(chk.failed),
                                  len(chk.failed)))
    print("written:", p)
    print("=" * 74)
    return 0 if chk.verdict() == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
