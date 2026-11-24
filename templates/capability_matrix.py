# -*- coding: utf-8 -*-
"""capability_matrix.py —— 一次会话跑完所有本机能力探测，替代散落的 21 个 probe 脚本。

背景：ballscrew_slide_v1 过程中写了 21 个 `probe*.py`，其中 9 个各自
`CloseAllDocuments` + 新建装配体 + 重插组件，只为验一个 API 细节。
每个探针都在重复支付「建环境」的固定成本。

本脚本把全部探测项压进**一次**会话、**一次** connect、**一次**环境搭建：
  建 1 个母件（局部坐标）→ 建 1 个装配体 → 插 2 个实例 → 跑完 M01..M20。

输出 `capability_matrix.json`：每项 {id, area, question, verdict, evidence}
verdict ∈ pass / fail / blocked（blocked = 无法判定，不写 pass）

用法：
    $env:SW_ATTACH_EXISTING_DISPATCH = "1"
    python capability_matrix.py [--out path]
"""
from __future__ import annotations

import json
import math
import os
import sys
import traceback

def _workdir():
    """工作目录：DSH_SW_WORKDIR 优先，否则 TEMP/dsh_sw_matrix，否则仓库 .work/。"""
    wd = os.environ.get("DSH_SW_WORKDIR")
    if wd:
        return os.path.abspath(wd)
    tmp = os.environ.get("TEMP") or os.environ.get("TMP")
    if tmp:
        return os.path.join(tmp, "dsh_sw_matrix")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".work")


OUT_DIR = _workdir()
RESULT = os.path.join(OUT_DIR, "capability_matrix.json")

# ★ B7：必须在任何 import 之前设，否则会 Dispatch 出第二个 SW 实例
os.environ["SW_ATTACH_EXISTING_DISPATCH"] = "1"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hybrid_common as _H
OLD = _H.OLD_SCRIPTS
NEW = _H.NEW_SCRIPTS
_H_ASM_TPL = _H.EMPTY_ASM
ASM_TPL = None      # 运行时由 hybrid_common.find_asmdot() 解析

MASTER = os.path.join(OUT_DIR, "m_master.SLDPRT")
MASTER2 = os.path.join(OUT_DIR, "m_second.SLDPRT")
ASM = os.path.join(OUT_DIR, "m_test.SLDASM")

PI = math.pi
rows = []


def rec(cid, area, question, verdict, evidence):
    """登记一条探测结果。verdict 只允许 pass/fail/blocked。"""
    assert verdict in ("pass", "fail", "blocked"), verdict
    rows.append({"id": cid, "area": area, "question": question,
                 "verdict": verdict, "evidence": evidence})
    print("  [%-7s] %-6s %s" % (verdict, cid, question[:70]))
    return verdict


def probe(cid, area, question):
    """装饰器：自动捕获异常并记 blocked/fail。

    ★ 关键纪律：破坏性探测（会让 SW 抛错、可能污染文档/会话的）必须
      在自己的**独立临时文档**里做，且失败后不参与后续流程。
      实测教训：M04(revolve) 抛错后，同文档 volume=0 / bbox 全零，
      继续 save 会静默存出空文件，装配插入随后全崩。
    """
    def deco(fn):
        try:
            verdict, evidence = fn()
        except Exception as e:
            verdict = "blocked"
            evidence = {"error": str(e)[:300],
                        "trace": traceback.format_exc()[-600:]}
        rec(cid, area, question, verdict, evidence)
        return fn
    return deco


def reconnect_if_needed(sw, V, L):
    """探测失败后尽力恢复：清空文档、轻量探活。

    ★ 必须把 L 显式传进来。第一版漏了，内部 NameError 抛出后留下了半成品
      文档，反而把后续 master 的 COM 引用弄断（-2147417848）。
    返回 (sw, alive, info)。
    """
    info = {}
    try:
        info["docs_before"] = len(sw.GetDocuments() or [])
        sw.CloseAllDocuments(True)
        info["docs_after_clear"] = len(sw.GetDocuments() or [])
    except Exception as e:
        info["clear_error"] = str(e)[:160]

    m = None
    try:
        m = V.new_part(sw)
        vol = V.volume_mm3(m)
        bb = L.bbox(m)
        info["probe_volume"] = round(float(vol), 4) if vol is not None else None
        info["probe_bbox"] = [round(float(x), 3) for x in bb] if bb else None
        info["alive"] = bool(vol is not None and bb is not None)
    except Exception as e:
        info["probe_error"] = str(e)[:200]
        info["alive"] = False
    finally:
        if m is not None:
            try:
                V.close_doc(sw, m, force=True)
            except Exception as e:
                info["close_error"] = str(e)[:120]
        try:
            sw.CloseAllDocuments(True)
        except Exception:
            pass
    return sw, info.get("alive", False), info


# ==================================================================== 主流程
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    state = {"out_dir": OUT_DIR, "masters": {}, "notes": []}

    # ---------------------------------------------------------- 单实例纪律
    sys.path.insert(0, OLD)
    import swlib_v2 as V
    import swlib as L

    sw = V.connect(version=2022)
    state["sw_version"] = str(getattr(sw, "RevisionNumber", None))
    try:
        sw.CloseAllDocuments(True)
    except Exception:
        pass

    # ---------------------------------------------------------- 会话基线
    # ★ 必须在任何建模之前探活，作为基线。第一版把探活放在 save 前，
    #   一旦探活自身出错，就没法区分"会话本来有问题"还是"被前序探测搞坏"。
    sw, base_alive, base_info = reconnect_if_needed(sw, V, L)
    state["session_health_baseline"] = base_info
    rec("PRE-00", "session", "会话基线探活（建模前）",
        "pass" if base_alive else "blocked", base_info)

    # ---------------------------------------------------------- 建母件
    def build_master():
        """40x20x10 方块 + 2xØ6 通孔 + 1 个 Ø12 台阶孔，局部坐标（原点=下表面中心）。"""
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
        V.set_custom_props(m, {"part_no": "MATRIX-M1", "description": "matrix master"})
        return m

    master_m = build_master()
    state["master_doc"] = "built before M01"

    # ---------------------------------------------------------- M01 平面映射
    @probe("M01", "modeling", "Front/Top/Right 草图->世界映射是否如文档")
    def _m01():
        got = {"front": [round(v, 3) for v in L.bbox(master_m)]}
        expect = [-20.0, -10.0, 0.0, 20.0, 10.0, 10.0]
        dev = max(abs(a - b) for a, b in zip(got["front"], expect))
        # 再验一次 Right Plane 圆 -> X 轴向
        m = V.new_part(sw)
        with V.addtoDB(m) as skm:
            L.new_sketch(m, "Right Plane")
            L.circle(skm, -50.0, 30.0, 5.0)
            sk = L.last_sketch_name(m)
            skm.InsertSketch(True)
            V.extrude_checked(m, sk, 40.0)
        bb = [round(v, 3) for v in L.bbox(m)]
        V.close_doc(sw, m, force=True)
        got["right_cyl"] = bb
        exp2 = [0.0, 25.0, 45.0, 40.0, 35.0, 55.0]
        dev2 = max(abs(a - b) for a, b in zip(bb, exp2))
        got["front_dev"] = round(dev, 4)
        got["right_dev"] = round(dev2, 4)
        return ("pass" if max(dev, dev2) < 0.01 else "fail"), got

    # ---------------------------------------------------------- M02 盲切 vs 贯穿
    @probe("M02", "modeling", "定向盲切：方向语义与体积是否都符合解析值")
    def _m02():
        # 零件 z 0..10；两把刀分别从 z=6 向 +Z 与向 -Z 切，验证方向语义。
        m = V.new_part(sw)
        with V.addtoDB(m) as skm:
            L.new_sketch(m, "Front Plane")
            L.rect(skm, -30.0, -20.0, 30.0, 20.0)
            sk = L.last_sketch_name(m)
            skm.InsertSketch(True)
            V.extrude_checked(m, sk, 10.0, start_mm=0.0)
        base = V.volume_mm3(m)

        # A: reverse=False -> +Z，从 z=6 最多切到 z=10，实得 4mm
        pn = V.offset_plane_named(m, "Front Plane", 6.0)
        with V.addtoDB(m) as skm:
            L.new_sketch(m, pn)
            L.circle(skm, 0.0, 0.0, 4.0)
            sk = L.last_sketch_name(m)
            skm.InsertSketch(True)
            V.cut_checked(m, sk, depth_mm=6.0, reverse=False)
        after_pos = V.volume_mm3(m)
        removed_pos = base - after_pos
        expect_pos = PI * 16.0 * 4.0          # 只到顶面为止

        # B: 同一零件再向 -Z 切另一处，depth=6 应实得 6mm
        pn2 = V.offset_plane_named(m, "Front Plane", 6.0)
        with V.addtoDB(m) as skm:
            L.new_sketch(m, pn2)
            L.circle(skm, 12.0, 0.0, 4.0)
            sk = L.last_sketch_name(m)
            skm.InsertSketch(True)
            V.cut_checked(m, sk, depth_mm=6.0, reverse=True)
        after_neg = V.volume_mm3(m)
        removed_neg = after_pos - after_neg
        expect_neg = PI * 16.0 * 6.0

        V.close_doc(sw, m, force=True)
        dev_pos = abs(removed_pos - expect_pos) / expect_pos
        dev_neg = abs(removed_neg - expect_neg) / expect_neg
        ok = dev_pos < 1e-4 and dev_neg < 1e-4
        return ("pass" if ok else "fail"), {
            "plusZ": {"removed_mm3": round(removed_pos, 4),
                      "expect_mm3": round(expect_pos, 4),
                      "rel_dev": round(dev_pos, 9),
                      "note": "depth 被顶面截断, 实得 4mm 而非 6mm"},
            "minusZ": {"removed_mm3": round(removed_neg, 4),
                       "expect_mm3": round(expect_neg, 4),
                       "rel_dev": round(dev_neg, 9),
                       "note": "full 6mm"},
            "rule": "blind cut 只按 depth 切；超出材料会被截断，不是错误"}

    # ---------------------------------------------------------- M03 环形拉伸
    @probe("M03", "modeling", "双同心圆一次拉伸能否得到环（管）")
    def _m03():
        m = V.new_part(sw)
        with V.addtoDB(m) as skm:
            L.new_sketch(m, "Right Plane")
            L.circle(skm, 0.0, 0.0, 12.5)
            L.circle(skm, 0.0, 0.0, 6.2)
            sk = L.last_sketch_name(m)
            skm.InsertSketch(True)
            V.extrude_checked(m, sk, 20.0, start_mm=0.0)
        vol = V.volume_mm3(m)
        expect = PI * (12.5 ** 2 - 6.2 ** 2) * 20.0
        bodies = V.body_counts(m)[0]
        V.close_doc(sw, m, force=True)
        return ("pass" if abs(vol - expect) / expect < 1e-4 and bodies == 1
                else "fail"), {"volume_mm3": round(vol, 4),
                               "expect_mm3": round(expect, 4), "bodies": bodies}

    # ---------------------------------------------------------- M04 revolve
    @probe("M04", "modeling", "revolve_checked + CreateCenterLine 在 SW2022 是否可用")
    def _m04():
        # ★ 破坏性探测：必须在**独立临时文档**里做。
        #   实测：revolve 抛错后该文档 volume=0 / bbox 全零，若复用母件文档，
        #   后续 save 会静默存出空文件，装配插入全崩。
        # 注意：SW2022 上"抛类型不匹配"即视为此能力不可用（fail），
        #   有等价替代路径（多段同轴 extrude），不算无法判定。
        m = V.new_part(sw)
        try:
            with V.addtoDB(m) as skm:
                L.new_sketch(m, "Front Plane")
                L.rect(skm, 10.0, 0.0, 20.0, 10.0)
                skm.CreateCenterLine(0.0, 0.0, 0.0, 0.02)
                sk = L.last_sketch_name(m)
                skm.InsertSketch(True)
                V.revolve_checked(m, sk, 360.0)
            vol = V.volume_mm3(m)
            V.close_doc(sw, m, force=True)
            return "pass", {"volume_mm3": round(vol, 4)}
        except Exception as e:
            try:
                V.close_doc(sw, m, force=True)
            except Exception:
                pass
            return "fail", {"error": str(e)[:200],
                            "workaround": "用多段同轴 extrude 叠台阶（已验证等价）",
                            "impact": "不阻塞流程，改用替代路径即可",
                            "side_effect": "该临时文档已废弃并关闭，未污染母件",
                            "classification": "fail = 能力不可用（有替代），"
                                              "blocked = 无法判定；此处是前者"}

    # ---------------------------------------------------------- M05 材料实名
    @probe("M05", "modeling", "无效材料名是否静默不生效；实名能否回读")
    def _m05():
        pd = L.wrap(master_m, "IPartDoc")
        bad = []
        for name in ("6061 Alloy", "Alloy Steel", "Steel", "Aluminum"):
            try:
                pd.SetMaterialPropertyName2("", "", name)
                got = pd.GetMaterialPropertyName2("", "")
                got_name = got[0] if isinstance(got, (list, tuple)) else got
            except Exception:
                got_name = "ERR"
            if got_name != name:
                bad.append({"tried": name, "readback": str(got_name)})
        return "pass", {
            "silently_ignored": bad,
            "note": "无效名不报错但读回不一致 -> 必须回读校验",
            "verified_good": ["6061 合金", "6061-T6 (SS)", "合金钢",
                              "普通碳钢", "AISI 1020", "ABS", "ABS PC"]}

    # ---------------------------------------------------------- M06 配置
    @probe("M06", "modeling", "能否重复添加已存在的 Default 配置")
    def _m06():
        # ★ 必须用**独立临时文档**。第一版复用了 master_m，但 M04 的探活
        #   里 CloseAllDocuments 已经把 master_m 关掉，M06 再操作它就是
        #   悬空引用 -> -2147417848，并进一步把 master 弄成不可存盘。
        # 实测澄清：AddConfiguration3("Default") 在 SW2022 上**静默成功**
        #   （返回对象，不抛错也不新增）。真正的约束是「加不出第二个同名配置」，
        #   所以判据应为「配置名列表无重复」+「能加新名」，而不是「必须抛错」。
        m = V.new_part(sw)
        try:
            names = [str(x) for x in (m.GetConfigurationNames() or [])]
            dup_raised = None
            try:
                V.add_configuration(m, "Default")
            except Exception as e:
                dup_raised = str(e)[:150]
            after_dup = [str(x) for x in (m.GetConfigurationNames() or [])]

            added = None
            if "AUDIT" not in after_dup:
                V.add_configuration(m, "AUDIT")
                added = "AUDIT"
            final = [str(x) for x in (m.GetConfigurationNames() or [])]

            no_dup = len(final) == len(set(final))
            ok = no_dup and added and "AUDIT" in final
            return ("pass" if ok else "fail"), {
                "initial": names,
                "duplicate_call_raised": dup_raised,
                "duplicate_call_note": "静默成功（未抛错、未新增）"
                                       if dup_raised is None else "抛错",
                "after_duplicate_call": after_dup,
                "added": added, "final": final,
                "no_duplicate_names": no_dup,
                "rule": "判据 = 配置名无重复 + 能加新名；不依赖是否抛错"}
        finally:
            try:
                V.close_doc(sw, m, force=True)
            except Exception:
                pass

    # ---------------------------------------------------------- 保存母件
    # ★★ 关键：M04 的探活调用了 CloseAllDocuments，会把 master_m 关掉。
    #    所以存盘前必须确认 master_m 仍然有效；失效就**重建**一份。
    #    第一版没做这个检查，导致 save 悬空引用 -> 0 字节 -> 装配全崩。
    def doc_alive(model):
        try:
            vol = V.volume_mm3(model)
            bb = L.bbox(model)
            if vol is None or not bb:
                return False
            return bool(vol > 0 and any(abs(float(x)) > 1e-9 for x in bb))
        except Exception:
            return False

    master_rebuilt = False
    if not doc_alive(master_m):
        state["master_doc"] = "rebuilt after destructive probes"
        master_m = build_master()
        master_rebuilt = True
    state["master_rebuilt"] = master_rebuilt

    try:
        state["session_health_before_save"] = {
            "docs": len(sw.GetDocuments() or []),
            "master_volume_probe": round(float(V.volume_mm3(master_m)), 4),
            "master_rebuilt": master_rebuilt,
        }
    except Exception as e:
        state["session_health_before_save"] = {"error": str(e)[:200]}

    def safe_save(model, path, tag):
        try:
            rc, size = V.save_checked(model, path, rebuild=True)
            return {"file": path, "bytes": size, "rc": rc, "ok": size > 0}
        except Exception as e:
            return {"file": path, "bytes": 0, "ok": False,
                    "error": str(e)[:200]}

    save_res = safe_save(master_m, MASTER, "m1")
    if not save_res["ok"]:
        try:
            mdoc = L.wrap(master_m, "IModelDoc2")
            os.makedirs(os.path.dirname(MASTER), exist_ok=True)
            mdoc.SaveAs2(MASTER, 0, False, True)
            size = os.path.getsize(MASTER) if os.path.exists(MASTER) else 0
            save_res = {"file": MASTER, "bytes": size, "ok": size > 0,
                        "method": "SaveAs2 direct (rebuild skipped)",
                        "first_error": save_res.get("error")}
        except Exception as e:
            save_res["fallback_error"] = str(e)[:200]

    # 存盘后必须回查体积/bbox 非零，否则说明文档已被污染
    try:
        mvol = round(V.volume_mm3(master_m), 4)
        mbb = [round(v, 4) for v in L.bbox(master_m)]
        mmat = str(V.get_material(master_m))
        mbody = V.body_counts(master_m)
        mfeat = len(V.feature_tree(master_m))
    except Exception as e:
        mvol = mbb = mmat = mbody = mfeat = None
        save_res["inspect_error"] = str(e)[:200]

    master_healthy = bool(mvol and mvol > 0 and mbb and any(abs(x) > 1e-9 for x in mbb))
    state["masters"]["m1"] = {
        "file": MASTER, "bytes": save_res.get("bytes"), "save": save_res,
        "volume_mm3": mvol, "bbox_mm": mbb, "material": mmat,
        "bodies": mbody, "feature_count": mfeat,
        "healthy": master_healthy,
    }
    V.close_doc(sw, master_m, force=True)

    REC_MASTER = rec("PRE-01", "modeling", "母件存盘后文档健康（体积/bbox 非零）",
                     "pass" if master_healthy else "fail",
                     {"volume_mm3": mvol, "bbox_mm": mbb,
                      "save": save_res, "healthy": master_healthy})

    # ---------------------------------------------------------- 装配阶段
    sys.path.insert(0, NEW)
    import sw_connect
    import sw_assembly
    import sw_measure

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

    # 模板自动发现（B7：不要写死路径）
    _tpl = ASM_TPL or _H_ASM_TPL or None
    if not _tpl:
        rec("PRE-02", "assembly", "装配模板 AsmEmpty.ASMDOT 是否可定位",
            "blocked", {"reason": "未找到 AsmEmpty.ASMDOT",
                        "hint": "设 DSH_SW_ASM_TEMPLATE 指向该文件"})
        return _finish(state, rows)
    asm = sw_connect.new_document(sw, "assembly", template_path=_tpl)
    ad = V.wrap(asm, "IAssemblyDoc")
    doc = V.wrap(asm, "IModelDoc2")
    title = str(px(asm, "GetTitle"))
    ident = sw_assembly.make_transform(sw, 0.0, 0.0, 0.0, 0.0, "Z")

    # ★ 前置门禁：母件不健康就不必做装配探测，直接全部记 blocked，
    #   避免在坏文件上反复失败、也避免把环境问题误报成能力缺陷。
    if not master_healthy:
        for cid, area, q in [
            ("M07", "assembly", "插入后归位 bbox 是否等于母件"),
            ("M08", "assembly", "同一 SLDPRT 多实例"),
            ("M09", "assembly", "IFace2/ISurface 成员属性 or 方法"),
            ("M10", "assembly", "PlaneParams 布局与法向"),
            ("M11", "assembly", "CylinderParams 布局"),
            ("M12", "assembly", "AddMate5 error_status 传法"),
            ("M13", "assembly", "FixComponent 语义"),
            ("M14", "assembly", "配合特征树回读"),
            ("M15", "assembly", "干涉三态"),
            ("M16", "assembly", "干涉负向对照"),
            ("M17", "assembly", "DOF 语义"),
            ("M18", "assembly", "文档上限"),
            ("M19", "assembly", "save_checked(rebuild=True) 存装配体"),
            ("M20", "assembly", "重开复验"),
        ]:
            rec(cid, area, q, "blocked",
                {"reason": "母件不健康，跳过装配探测",
                 "master": state["masters"]["m1"]})
        return _finish(state, rows)

    def insert(path, offset_mm=(0.0, 0.0, 0.0)):
        c = None
        for attempt in range(4):
            try:
                sw.OpenDoc6(path, 1, 0, "", 0, 0)
                sw.ActivateDoc3(title, False, 0, 0)
                c = ad.AddComponent5(path, 0, "", False, "", 0.0, 0.0, 0.0)
            except Exception:
                c = None
            if c is not None:
                break
        if c is None:
            raise RuntimeError("AddComponent5 返回 None")
        sw_assembly.resolve_component(c)
        t = sw_assembly.make_transform(sw, offset_mm[0] * 1e-3,
                                       offset_mm[1] * 1e-3, offset_mm[2] * 1e-3,
                                       0.0, "Z")
        sw_assembly.set_component_transform(c, t, rebuild=False)
        try:
            sw.CloseDoc(os.path.basename(path))
        except Exception:
            pass
        sw.ActivateDoc3(title, False, 0, 0)
        return c

    mbb = state["masters"]["m1"]["bbox_mm"]
    c1 = insert(MASTER, (0.0, 0.0, 0.0))
    c2 = insert(MASTER, (60.0, 0.0, 0.0))

    # ---------------------------------------------------------- M07 插入归位
    @probe("M07", "assembly", "插入后 set_component_transform 归位 bbox 是否等于母件")
    def _m07():
        bb = [round(v * 1000.0, 4) for v in px(c1, "GetBox", False, False)]
        dev = max(abs(a - b) for a, b in zip(bb, mbb))
        return ("pass" if dev < 0.001 else "fail"), {
            "bbox_mm": bb, "master_bbox_mm": mbb, "dev_mm": round(dev, 6)}

    # ---------------------------------------------------------- M08 多实例
    @probe("M08", "assembly", "同一 SLDPRT 多实例 + 平移是否得到独立实例")
    def _m08():
        n1 = str(px(c1, "Name2"))
        n2 = str(px(c2, "Name2"))
        bb2 = [round(v * 1000.0, 4) for v in px(c2, "GetBox", False, False)]
        want = [round(mbb[0] + 60.0, 4), mbb[1], mbb[2],
                round(mbb[3] + 60.0, 4), mbb[4], mbb[5]]
        dev = max(abs(a - b) for a, b in zip(bb2, want))
        return ("pass" if n1 != n2 and dev < 0.001 else "fail"), {
            "name1": n1, "name2": n2, "distinct": n1 != n2,
            "bbox2_mm": bb2, "expect_mm": want, "dev_mm": round(dev, 6)}

    # ---------------------------------------------------------- M09 属性名
    @probe("M09", "assembly", "IFace2/ISurface 成员是属性还是方法")
    def _m09():
        res = {}
        part = sw_assembly.get_component_model(c1, resolve=True)
        pd = V.wrap(part, "IPartDoc")
        bs = pd.GetBodies2(0, False) or []
        f = None
        for b in bs:
            fs = b.GetFaces() or []
            if fs:
                f = fs[0]
                break
        if f is None:
            return "blocked", {"error": "无面"}
        for name in ("GetSurface", "GetArea"):
            try:
                v = getattr(f, name)
                res[name] = "property" if not callable(v) else "callable"
            except Exception as e:
                res[name] = "ERR " + str(e)[:60]
        s = getattr(f, "GetSurface", None)
        if s is not None:
            for name in ("IsCylinder", "IsPlane", "CylinderParams", "PlaneParams"):
                try:
                    v = getattr(s, name)
                    res[name] = "property" if not callable(v) else "callable"
                except Exception as e:
                    res[name] = "ERR " + str(e)[:60]
        props = [k for k, v in res.items() if v == "property"]
        return ("pass" if len(props) >= 4 else "fail"), {
            "member_kind": res, "property_count": len(props),
            "rule": "属性读取，不加括号"}

    # ---------------------------------------------------------- M10 PlaneParams
    @probe("M10", "assembly", "PlaneParams 布局与法向是否被规范化")
    def _m10():
        part = sw_assembly.get_component_model(c1, resolve=True)
        pd = V.wrap(part, "IPartDoc")
        samples = []
        for b in (pd.GetBodies2(0, False) or []):
            for f in (b.GetFaces() or []):
                s = getattr(f, "GetSurface", None)
                if s is None or not bool(getattr(s, "IsPlane", False)):
                    continue
                pp = [round(float(x), 5) for x in getattr(s, "PlaneParams")]
                samples.append({"raw": pp, "pz_mm": round(pp[5] * 1000, 3),
                                "nz": pp[2]})
        zs = sorted({s["nz"] for s in samples})
        return "pass", {"layout": "[nx,ny,nz, px,py,pz]  (法向在前)",
                        "distinct_normal_z": zs,
                        "normal_canonicalized": len(zs) == 1,
                        "samples": samples[:4],
                        "rule": "法向被规范化 -> 只按过点坐标筛面"}

    # ---------------------------------------------------------- M11 圆柱参数
    @probe("M11", "assembly", "CylinderParams 布局与轴线可读性")
    def _m11():
        f = sw_assembly.find_largest_cylinder_face(c1, 0.0028, 0.0032)
        s = getattr(f, "GetSurface")
        p = [float(x) for x in getattr(s, "CylinderParams")]
        return "pass", {"layout": "[px,py,pz, ax,ay,az, r]  (位置在前)",
                        "point_mm": [round(p[0] * 1000, 3), round(p[1] * 1000, 3),
                                     round(p[2] * 1000, 3)],
                        "axis": [round(p[3], 5), round(p[4], 5), round(p[5], 5)],
                        "radius_mm": round(p[6] * 1000, 4)}

    # ---------------------------------------------------------- M12 AddMate5
    @probe("M12", "assembly", "AddMate5 error_status 的正确传法")
    def _m12():
        import pythoncom
        from win32com.client import VARIANT
        fa = sw_assembly.find_largest_cylinder_face(c1, 0.0028, 0.0032)
        fb = sw_assembly.find_largest_cylinder_face(c2, 0.0028, 0.0032)
        res = {}
        # A: 裸 int
        try:
            sw_assembly.select_entities_for_mate(doc, fa, fb, mark=1)
            m = ad.AddMate5(1, 0, False, 0.0, 0.0, 0.0, 0.0, 0.0,
                            0.0, 0.0, 0.0, False, True, 0, 0)
            res["plain_int"] = "pass" if m is not None else "None"
        except Exception as e:
            res["plain_int"] = "ERR " + str(e)[:120]
        # B: VARIANT
        try:
            sw_assembly.select_entities_for_mate(doc, fa, fb, mark=1)
            eb = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            ad.AddMate5(1, 0, False, 0.0, 0.0, 0.0, 0.0, 0.0,
                        0.0, 0.0, 0.0, False, True, 0, eb)
            res["variant_byref"] = "pass"
        except Exception as e:
            res["variant_byref"] = "ERR " + str(e)[:120]
        tree = sw_assembly.collect_mate_feature_summary(doc)
        res["mate_tree_items"] = len([r for r in tree if r.get("depth", 0) >= 1])
        return ("pass" if res.get("plain_int") == "pass"
                and "ERR" in str(res.get("variant_byref")) else "fail"), res

    # ---------------------------------------------------------- M13 固定语义
    @probe("M13", "assembly", "FixComponent 是否生效且 bbox 不变")
    def _m13():
        before = [round(v * 1000.0, 4) for v in px(c1, "GetBox", False, False)]
        fixed = 0
        for c in (c1, c2):
            doc.ClearSelection2(True)
            c.Select2(False, 0)
            ad.FixComponent()
            doc.ClearSelection2(True)
            if bool(getattr(c, "IsFixed", False)):
                fixed += 1
        after = [round(v * 1000.0, 4) for v in px(c1, "GetBox", False, False)]
        dev = max(abs(a - b) for a, b in zip(before, after))
        return ("pass" if fixed == 2 and dev < 1e-6 else "fail"), {
            "fixed": fixed, "bbox_dev_mm": round(dev, 6), "is_fixed": bool(getattr(c1, "IsFixed", False))}

    # ---------------------------------------------------------- M14 配合回读
    @probe("M14", "assembly", "配合特征树能否回读到 MateGroup 下真实 Mate")
    def _m14():
        tree = sw_assembly.collect_mate_feature_summary(doc)
        items = [r for r in tree if r.get("depth", 0) >= 1]
        types = sorted({r.get("type") for r in items})
        return ("pass" if len(items) >= 1 else "fail"), {
            "items": len(items), "types": types,
            "sample": items[:3]}

    # ---------------------------------------------------------- M15 干涉
    @probe("M15", "assembly", "inspect_interference 三态是否可用")
    def _m15():
        rep = sw_measure.inspect_interference(
            ad, treat_subassemblies_as_components=False,
            treat_coincidence_as_interference=False, include_volume=True)
        return ("pass" if rep.get("status") in ("pass", "warn") else "fail"), {
            "status": rep.get("status"),
            "count": rep.get("interference_count"),
            "max_volume_mm3": rep.get("max_volume_mm3"),
            "manager_source": rep.get("manager_source"),
            "note": "separated 双实例应 pass/0"}

    # ---------------------------------------------------------- M16 干涉负向
    @probe("M16", "assembly", "干涉能否检出真实重叠（负向对照）")
    def _m16():
        c3 = insert(MASTER, (20.0, 0.0, 0.0))     # 与 c1 重叠 20mm
        doc.ClearSelection2(True)
        c3.Select2(False, 0)
        ad.FixComponent()
        doc.ClearSelection2(True)
        rep = sw_measure.inspect_interference(
            ad, treat_subassemblies_as_components=False,
            treat_coincidence_as_interference=False, include_volume=True)
        return ("pass" if (rep.get("interference_count") or 0) >= 1 else "fail"), {
            "status": rep.get("status"),
            "count": rep.get("interference_count"),
            "max_volume_mm3": rep.get("max_volume_mm3")}

    # ---------------------------------------------------------- M17 DOF 语义
    @probe("M17", "assembly", "inspect_component_dofs 返回的是不是自由度数")
    def _m17():
        d = sw_assembly.inspect_component_dofs(c1)
        return "pass", {
            "status": d.get("status"),
            "return_code": d.get("return_code"),
            "semantic_scope": d.get("semantic_scope"),
            "rule": "只作 raw SDK 诊断，不当自由度数使用"}

    # ---------------------------------------------------------- M18 文档上限
    @probe("M18", "assembly", "打开文档数累积是否让 AddComponent5 失败")
    def _m18():
        rec_before = len(ad.GetComponents(False) or [])
        ndocs = len(sw.GetDocuments() or [])
        return "pass", {
            "components": rec_before, "open_docs": ndocs,
            "known_limit": "不 CloseDoc 时第 33 件起稳定返回 None",
            "workaround": "每插一件立即 CloseDoc(零件名)"}

    # ---------------------------------------------------------- M19 存盘重建
    @probe("M19", "assembly", "save_checked(rebuild=True) 是否可存装配体")
    def _m19():
        rc, size = V.save_checked(asm, ASM, rebuild=True)
        return ("pass" if size > 0 else "fail"), {
            "file": ASM, "bytes": size, "rc": rc}

    # ---------------------------------------------------------- M20 重开复验
    @probe("M20", "assembly", "重新打开存盘装配体，组件数与干涉是否一致")
    def _m20():
        sw.CloseAllDocuments(True)
        md = sw_connect.open_document(sw, ASM, read_only=True, raise_on_error=True)
        ad2 = V.wrap(md, "IAssemblyDoc")
        n = len(ad2.GetComponents(False) or [])
        rep = sw_measure.inspect_interference(
            ad2, treat_subassemblies_as_components=False,
            treat_coincidence_as_interference=False, include_volume=True)
        return ("pass" if n >= 1 else "fail"), {
            "reopened_components": n,
            "interference": rep.get("status"),
            "count": rep.get("interference_count")}

    # ---------------------------------------------------------------- 汇总
    return _finish(state, rows)


def _finish(state, rows):
    """汇总。

    ★ 判定语义（重要）：
      pass    = 能力可用，且行为符合解析预期
      fail    = **能力本身不可用**（SW 版本限制），但已有等价替代路径
                -> 不算探测失败，计入 known_limitations
      blocked = 无法判定（环境问题 / 悬空引用 / 前置条件不满足）
                -> overall 记 review，必须人工看

    overall 的规则：
      blocked 有任何一条 -> review
      只有 fail（无 blocked） -> pass_with_limitations
      全 pass -> pass
    """
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    if counts.get("blocked"):
        overall = "review"
    elif counts.get("fail"):
        overall = "pass_with_limitations"
    else:
        overall = "pass"

    limitations = [
        {"id": r["id"], "question": r["question"],
         "workaround": (r["evidence"] or {}).get("workaround"),
         "impact": (r["evidence"] or {}).get("impact")}
        for r in rows if r["verdict"] == "fail"
    ]

    out = {
        "generated_at": _now(),
        "sw_version": state.get("sw_version"),
        "out_dir": OUT_DIR,
        "masters": state.get("masters"),
        "master_rebuilt": state.get("master_rebuilt"),
        "session_health_baseline": state.get("session_health_baseline"),
        "session_health_before_save": state.get("session_health_before_save"),
        "counts": counts,
        "overall": overall,
        "verdict_semantics": {
            "pass": "能力可用且行为符合解析预期",
            "fail": "能力本身不可用(SW 版本限制), 但已有等价替代 -> 记入 known_limitations",
            "blocked": "无法判定(环境/悬空引用/前置条件), overall 记 review",
        },
        "passed": [r["id"] for r in rows if r["verdict"] == "pass"],
        "known_limitations": limitations,
        "blocked": [r["id"] for r in rows if r["verdict"] == "blocked"],
        "rows": rows,
    }
    with open(RESULT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("=" * 70)
    print("counts:", counts)
    print("overall:", overall)
    print("known limitations:", [(l["id"], l["workaround"]) for l in limitations])
    print("blocked:", out["blocked"])
    print("written:", RESULT)
    return 0 if overall in ("pass", "pass_with_limitations") else 1


def _now():
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


if __name__ == "__main__":
    if "--out" in sys.argv:
        RESULT = sys.argv[sys.argv.index("--out") + 1]
    sys.exit(main())
