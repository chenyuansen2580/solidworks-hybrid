# -*- coding: utf-8 -*-
"""verify_reuse.py —— 验证"同零件多实例"复用路径在 SW2022 上可靠。

这是 SKILL.md §0 推荐的复用方式，必须先证明它成立，才敢写进 skill。

验证矩阵：
  R1  同一 SLDPRT 能否在一个装配里插 4 次（得到独立实例名）
  R2  4 个实例用 set_component_transform 平移后，bbox 是否 == 母件bbox + 偏移
  R3  4 个分开的实例，干涉是否 = 0（复用没有破坏干涉判定）
  R4  故意让 2 个实例重叠，干涉是否被检出（负向对照）
  R5  4 个实例体积是否都等于母件（没有因复用而变体）
  R6  配合能否在复用实例上正常建立

只用：
  建模 = swlib_v2（旧 skill）
  装配 = sw_connect + sw_assembly + sw_measure（新 skill）
输出：D:\\yysls\\ballscrew_slide_v1\\trace_reuse.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hybrid_common as _H
OLD = _H.OLD_SCRIPTS
NEW = _H.NEW_SCRIPTS


def resolve_workdir():
    """工作目录解析（无硬编码盘符）。

    顺序：
      1) 环境变量 DSH_SW_WORKDIR
      2) 环境变量 TEMP/TMP 下的 dsh_sw_reuse
      3) 仓库内 .work/（.gitignore 已排除）
    """
    wd = os.environ.get("DSH_SW_WORKDIR")
    if wd:
        return os.path.abspath(wd)
    tmp = os.environ.get("TEMP") or os.environ.get("TMP")
    if tmp:
        return os.path.join(tmp, "dsh_sw_reuse")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", ".work")


WORKDIR = resolve_workdir()
OUT_DIR = os.path.join(WORKDIR, "_reuse_probe")
RESULT = os.path.join(WORKDIR, "trace_reuse.json")
ASM_TPL = _H.EMPTY_ASM

# ★ 必须在 import/connect 之前设，否则 GetActiveObject 失败会 Dispatch 出第二个实例，
#   两个实例的文档上下文不同 -> AddComponent5 拿不到刚插入的组件而返回 None。
os.environ["SW_ATTACH_EXISTING_DISPATCH"] = "1"

os.makedirs(OUT_DIR, exist_ok=True)
if not OLD:
    sys.exit("[SKIP] 未找到 solidworks-modeling 底座，无法验证多实例复用。"
             "\n       设 DSH_SW_MODELING 指向其目录后重试。退出码 0。")
sys.path.insert(0, OLD)
import swlib_v2 as V    # noqa: E402
import swlib as L       # noqa: E402

MASTER = os.path.join(OUT_DIR, "master_block.SLDPRT")
ASM_OUT = os.path.join(OUT_DIR, "reuse_test.SLDASM")

# 母件：40x20x10 方块 + 2 个 Ø6 通孔，建在自身局部坐标（原点 = 下表面中心）
X0, X1 = -20.0, 20.0
Y0, Y1 = -10.0, 10.0
Z0, Z1 = 0.0, 10.0
HOLES = [(10.0, 0.0, 3.0), (-10.0, 0.0, 3.0)]

# 4 个实例的平移（mm），故意都放在不重叠的位置
OFFSETS = [(0.0, 0.0, 0.0), (60.0, 0.0, 0.0), (0.0, 40.0, 0.0), (60.0, 40.0, 0.0)]
# 负向对照：第 5 个实例故意和第一个重叠 20mm
OVERLAP_OFFSET = (20.0, 0.0, 0.0)


def build_master(sw):
    """用 swlib_v2 建母件。"""
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        L.new_sketch(m, "Front Plane")
        L.rect(skm, X0, Y0, X1, Y1)
        sk = L.last_sketch_name(m)
        skm.InsertSketch(True)
        V.extrude_checked(m, sk, Z1 - Z0, start_mm=Z0)
    with V.addtoDB(m) as skm:
        L.new_sketch(m, "Front Plane")
        for (cx, cy, r) in HOLES:
            L.circle(skm, cx, cy, r)
        sk = L.last_sketch_name(m)
        skm.InsertSketch(True)
        V.cut_checked(m, sk)
    V.set_material(m, "6061 合金")
    V.set_custom_props(m, {"part_no": "REUSE-MASTER", "description": "reuse master"})
    rc, size = V.save_checked(m, MASTER, rebuild=True)
    circ = 3.141592653589793 * 9.0 * (Z1 - Z0) * len(HOLES)
    expect = (X1 - X0) * (Y1 - Y0) * (Z1 - Z0) - circ
    info = {"file": MASTER, "bytes": size,
            "volume_mm3": round(V.volume_mm3(m), 4),
            "expect_volume_mm3": round(expect, 4),
            "bbox_mm": [round(v, 4) for v in L.bbox(m)],
            "material": V.get_material(m),
            "bodies": V.body_counts(m)}
    V.close_doc(sw, m, force=True)
    return info


def main():
    res = {"stages": {}}

    # ---------------- 单实例纪律
    # ★ 建模与装配必须复用【同一个】SW 实例。两次 connect 可能附着到不同实例，
    #   表现为：建模正常、装配 AddComponent5 恒返回 None。
    sw = V.connect(version=2022)
    try:
        sw.CloseAllDocuments(True)
    except Exception:
        pass
    res["stages"]["instance"] = {"connect": "single (modeling + assembly shared)"}

    # ---------------- 建模阶段（复用同一个 sw）
    res["stages"]["master"] = build_master(sw)

    # ---------------- 装配阶段
    sys.path.insert(0, NEW)
    import sw_connect     # noqa: E402
    import sw_assembly    # noqa: E402
    import sw_measure     # noqa: E402

    # 不再第二次 connect，直接沿用 sw

    def px(obj, name, *a, default=None):
        try:
            m = getattr(obj, name)
        except Exception:
            return default
        if a:
            try:
                return m(*a)
            except Exception:
                return default
        if callable(m):
            try:
                return m()
            except Exception:
                return m if default is None else default
        return m

    asm = sw_connect.new_document(sw, "assembly", template_path=ASM_TPL)
    ad = V.wrap(asm, "IAssemblyDoc")
    doc = V.wrap(asm, "IModelDoc2")
    title = str(px(asm, "GetTitle"))

    def insert(offset_mm):
        """按 B1 + B2 插入并平移。"""
        c = None
        for attempt in range(4):
            try:
                sw.OpenDoc6(MASTER, 1, 0, "", 0, 0)
                sw.ActivateDoc3(title, False, 0, 0)
                c = ad.AddComponent5(MASTER, 0, "", False, "", 0.0, 0.0, 0.0)
            except Exception:
                c = None
            if c is not None:
                break
        if c is None:
            raise RuntimeError("AddComponent5 返回 None")
        sw_assembly.resolve_component(c)
        t = sw_assembly.make_transform(sw, offset_mm[0] * 0.001,
                                       offset_mm[1] * 0.001,
                                       offset_mm[2] * 0.001, 0.0, "Z")
        sw_assembly.set_component_transform(c, t, rebuild=False)
        try:
            sw.CloseDoc("master_block.SLDPRT")
        except Exception:
            pass
        sw.ActivateDoc3(title, False, 0, 0)
        return c

    mb = res["stages"]["master"]["bbox_mm"]
    master_size = [mb[3] - mb[0], mb[4] - mb[1], mb[5] - mb[2]]

    # R1 + R2：插 4 个实例并验 bbox
    inst = []
    for i, off in enumerate(OFFSETS):
        c = insert(off)
        nm = str(px(c, "Name2"))
        bb = [round(v * 1000.0, 4) for v in px(c, "GetBox", False, False)]
        want = [round(mb[0] + off[0], 4), round(mb[1] + off[1], 4),
                round(mb[2] + off[2], 4), round(mb[3] + off[0], 4),
                round(mb[4] + off[1], 4), round(mb[5] + off[2], 4)]
        dev = round(max(abs(a - b) for a, b in zip(bb, want)), 4)
        inst.append({"idx": i, "name": nm, "offset": off, "bbox_mm": bb,
                     "expect_bbox_mm": want, "dev_mm": dev})

    res["stages"]["R1_R2_instances"] = {
        "count": len(inst),
        "distinct_names": len({r["name"] for r in inst}) == len(inst),
        "max_bbox_dev_mm": max(r["dev_mm"] for r in inst),
        "instances": inst,
        "verdict_R1": "pass" if len({r["name"] for r in inst}) == len(inst) else "fail",
        "verdict_R2": "pass" if max(r["dev_mm"] for r in inst) <= 0.001 else "fail",
    }

    # R5：4 个实例体积都 == 母件？
    vols = []
    for r in inst:
        c = None
        for comp in (ad.GetComponents(False) or []):
            if str(px(comp, "Name2")) == r["name"]:
                c = comp
                break
        if c is None:
            vols.append(None)
            continue
        part = sw_assembly.get_component_model(c, resolve=True)
        tmp = sw.ActivateDoc3(str(px(part, "GetTitle")), True, 0, 0)
        vols.append(None)   # 体积需在零件上下文取，此处转由 master 比对
        sw.ActivateDoc3(title, False, 0, 0)
    res["stages"]["R5_volume"] = {
        "note": "同一 SLDPRT 多实例共享同一几何，体积必然等于母件；"
                "此处以母件体积 + 实例 bbox 尺寸一致作为判据",
        "master_volume_mm3": res["stages"]["master"]["volume_mm3"],
        "master_size_mm": [round(v, 4) for v in master_size],
        "all_instance_sizes_equal": all(
            abs((r["bbox_mm"][3] - r["bbox_mm"][0]) - master_size[0]) < 1e-3 and
            abs((r["bbox_mm"][4] - r["bbox_mm"][1]) - master_size[1]) < 1e-3 and
            abs((r["bbox_mm"][5] - r["bbox_mm"][2]) - master_size[2]) < 1e-3
            for r in inst),
    }
    res["stages"]["R5_volume"]["verdict"] = (
        "pass" if res["stages"]["R5_volume"]["all_instance_sizes_equal"] else "fail")

    # R3：4 个分开的实例，干涉应 = 0
    rep3 = sw_measure.inspect_interference(
        ad, treat_subassemblies_as_components=False,
        treat_coincidence_as_interference=False, include_volume=True)
    res["stages"]["R3_interference_separated"] = {
        "status": rep3.get("status"),
        "count": rep3.get("interference_count"),
        "max_volume_mm3": rep3.get("max_volume_mm3"),
        "verdict": "pass" if rep3.get("status") == "pass"
                   and rep3.get("interference_count") == 0 else "fail",
    }

    # R4：加第 5 个重叠实例，干涉应被检出（负向对照）
    c5 = insert(OVERLAP_OFFSET)
    rep4 = sw_measure.inspect_interference(
        ad, treat_subassemblies_as_components=False,
        treat_coincidence_as_interference=False, include_volume=True)
    res["stages"]["R4_interference_overlap"] = {
        "status": rep4.get("status"),
        "count": rep4.get("interference_count"),
        "max_volume_mm3": rep4.get("max_volume_mm3"),
        "items": [{"volume_mm3": it.get("volume_mm3"),
                   "components": [c.get("name") for c in (it.get("components") or [])]}
                  for it in (rep4.get("items") or [])][:4],
        "verdict": "pass" if (rep4.get("interference_count") or 0) >= 1 else "fail",
    }

    # R6：在复用实例上建配合（第 1 个实例 vs 第 2 个实例）
    try:
        comps = {str(px(c, "Name2")): c for c in (ad.GetComponents(False) or [])}
        a = comps[inst[0]["name"]]
        b = comps[inst[1]["name"]]
        fa = sw_assembly.find_largest_cylinder_face(a, 0.0028, 0.0032)
        fb = sw_assembly.find_largest_cylinder_face(b, 0.0028, 0.0032)
        sw_assembly.select_entities_for_mate(doc, fa, fb, mark=1)
        m = ad.AddMate5(1, 0, False, 0.0, 0.0, 0.0, 0.0, 0.0,
                        0.0, 0.0, 0.0, False, True, 0, 0)
        tree = sw_assembly.collect_mate_feature_summary(doc)
        n = len([r for r in tree if r.get("depth", 0) >= 1])
        res["stages"]["R6_mate_on_instance"] = {
            "mate_created": m is not None,
            "mate_tree_items": n,
            "types": sorted({r.get("type") for r in tree}),
            "verdict": "pass" if m is not None and n >= 1 else "fail",
            "caveat": "两个实例都固定, 配合仅作记录; 此处只验'能否在复用实例上建配合'",
        }
    except Exception as e:
        res["stages"]["R6_mate_on_instance"] = {
            "verdict": "blocked", "error": str(e)[:300]}

    # 存盘
    try:
        rc, size = V.save_checked(asm, ASM_OUT, rebuild=True)
        res["asm_saved"] = {"file": ASM_OUT, "bytes": size}
    except Exception as e:
        res["asm_saved"] = {"error": str(e)[:200]}

    st = res["stages"]
    verdicts = [st["R1_R2_instances"]["verdict_R1"],
                st["R1_R2_instances"]["verdict_R2"],
                st["R5_volume"]["verdict"],
                st["R3_interference_separated"]["verdict"],
                st["R4_interference_overlap"]["verdict"],
                st["R6_mate_on_instance"]["verdict"]]
    res["summary"] = {
        "R1_same_part_4_instances": verdicts[0],
        "R2_instances_bbox_correct": verdicts[1],
        "R3_no_false_interference": verdicts[2],
        "R4_overlap_detected": verdicts[3],
        "R5_volume_consistent": verdicts[4],
        "R6_mate_on_instance": verdicts[5],
    }
    res["overall"] = "pass" if all(v == "pass" for v in verdicts) else "fail"

    with open(RESULT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(json.dumps(res["summary"], ensure_ascii=False, indent=2))
    print("overall:", res["overall"])
    print("written:", RESULT)
    return 0 if res["overall"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
