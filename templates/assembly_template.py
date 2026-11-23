# -*- coding: utf-8 -*-
"""装配模板：用 solidworks-automation / sw_connect + sw_assembly + sw_measure。

★ 本模板已按 2026-11-23 ballscrew_slide_v1 全流程实测校准。
  下面 6 条约束缺一不可，详见 ../references/hybrid-contract.md §6.1：
    B1 插入前 OpenDoc6 + ActivateDoc3；插入后立即 CloseDoc 释放窗口
    B2 插入后 set_component_transform(identity) 归位
    B3 AddMate5 的 error_status 传裸 int
    B4 GetSurface/IsCylinder/CylinderParams/GetArea 是属性，不加括号
    B5 PlaneParams 是 [法向, 过点] 且法向被规范化 -> 只按过点坐标筛面
    B6 先全固定再加配合（静态装配），否则平面配合会拉走零件并产生假干涉

复制后按实际装配修改。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMMON = HERE          # 与本文件同目录；发布版从自身位置解析
if COMMON not in sys.path:
    sys.path.insert(0, COMMON)

import hybrid_common as H       # noqa: E402
H.setup()

with H.use_scripts("assembly"):
    import pythoncom              # noqa: E402
    pythoncom.CoInitialize()
    import sw_connect             # noqa: E402
    import sw_assembly            # noqa: E402
    import sw_measure             # noqa: E402
    import swlib_v2 as V          # noqa: E402  (只借 wrap / save_checked，不建零件)

# ---------------- 参数
PARTS = [
    os.path.join(HERE, "01_base.SLDPRT"),
    os.path.join(HERE, "02_shaft.SLDPRT"),
]
ASM_OUT = os.path.join(HERE, "example_asm.SLDASM")

for p in PARTS:
    if not os.path.exists(p):
        raise SystemExit("缺零件: %s" % p)


# ---------------------------------------------------------------- 工具函数
def px(obj, name, *args, default=None):
    """读属性 / 调方法的双兼容取值（本机多用属性，见 B4）。"""
    try:
        m = getattr(obj, name)
    except Exception:
        return default
    if args:
        try:
            return m(*args)
        except Exception:
            return default
    if callable(m):
        try:
            return m()
        except Exception:
            return m if default is None else default
    return m


def insert_component(sw, ad, asm_title, path, *, retries=4, ident=None):
    """B1 + B2：插入组件并归位到建模坐标。

    - 插入前必须先 OpenDoc6 且把装配体 ActivateDoc3 回前台，否则返回 None；
    - 插入后立刻 CloseDoc 释放零件窗口，否则文档数累积到 ~33 件后稳定返回 None；
    - 插入后组件以自身 bbox 中心定位，必须 set_component_transform(identity) 归位。
    """
    name = os.path.basename(path)
    c = None
    for attempt in range(retries):
        try:
            sw.OpenDoc6(path, 1, 0, "", 0, 0)
            sw.ActivateDoc3(asm_title, False, 0, 0)
            c = ad.AddComponent5(path, 0, "", False, "", 0.0, 0.0, 0.0)
        except Exception:
            c = None
        if c is not None:
            break
        # 兜底：把所有零件窗口关掉，只留装配体
        try:
            for d in (sw.GetDocuments() or []):
                t = str(getattr(d, "GetTitle", ""))
                if t.lower().endswith(".sldprt"):
                    sw.CloseDoc(t)
            sw.ActivateDoc3(asm_title, False, 0, 0)
        except Exception:
            pass
        print("    retry insert %s (attempt %d)" % (name, attempt + 1))
    if c is None:
        raise RuntimeError("AddComponent5 返回 None: %s" % name)

    sw_assembly.resolve_component(c)
    if ident is not None:
        sw_assembly.set_component_transform(c, ident, rebuild=False)

    # B1：释放零件窗口
    try:
        sw.CloseDoc(name)
    except Exception:
        pass
    try:
        sw.ActivateDoc3(asm_title, False, 0, 0)
    except Exception:
        pass
    return c


def add_mate5(ad, mate_type, align=0, flip=False, lock_rotation=True, name=None):
    """B3：error_status 必须传裸 int，传 VARIANT 在 SW2022 会抛错。"""
    m = ad.AddMate5(int(mate_type), int(align), bool(flip),
                    0.0, 0.0, 0.0,
                    0.0, 0.0,
                    0.0, 0.0, 0.0,
                    False, bool(lock_rotation), 0,
                    0)
    if m is None:
        raise RuntimeError("AddMate5 返回 None (type=%s)" % mate_type)
    if name:
        try:
            m.Name = name
        except Exception:
            pass
    return m


def cyl_from_face(face):
    """B4：属性读取。CylinderParams = [px,py,pz, ax,ay,az, r]。"""
    s = getattr(face, "GetSurface", None)
    if s is None or not bool(getattr(s, "IsCylinder", False)):
        return None
    p = [float(x) for x in getattr(s, "CylinderParams")]
    return {"point_m": p[0:3], "axis": p[3:6], "radius_m": p[6]}


def scan_planar(comp, axis_idx, coord_mm, tol_mm=0.05, area_min_mm2=1.0):
    """B5：按「轴 + 平面过点坐标」找面；不按法向符号筛。

    PlaneParams = [nx,ny,nz, px,py,pz]  (法向在前)
    法向被 SW 规范化成正轴向，所以 sign 不可用。
    """
    part = sw_assembly.get_component_model(comp, resolve=True)
    pd = V.wrap(part, "IPartDoc")
    best = None
    for b in (pd.GetBodies2(0, False) or []):
        for f in (b.GetFaces() or []):
            s = getattr(f, "GetSurface", None)
            if s is None or not bool(getattr(s, "IsPlane", False)):
                continue
            pp = [float(x) for x in getattr(s, "PlaneParams")]
            n, p = pp[0:3], pp[3:6]
            if abs(abs(n[axis_idx]) - 1.0) > 1e-3:
                continue
            off = p[axis_idx] * 1000.0
            if abs(off - coord_mm) > tol_mm:
                continue
            a = float(getattr(f, "GetArea", 0.0) or 0.0) * 1e6
            if a < area_min_mm2:
                continue
            if best is None or a > best[0]:
                best = (a, f, off)
    return (best[1], best[2]) if best else (None, None)


# ---------------------------------------------------------------- 主流程
sw, _ = sw_connect.connect_solidworks(version=2022)
try:
    sw.CloseAllDocuments(True)
except Exception:
    pass

asm = sw_connect.new_document(sw, "assembly", template_path=H.EMPTY_ASM)
ad = V.wrap(asm, "IAssemblyDoc")
doc = V.wrap(asm, "IModelDoc2")
title = str(px(asm, "GetTitle"))
ident = sw_assembly.make_transform(sw, 0.0, 0.0, 0.0, 0.0, "Z")

comps = [insert_component(sw, ad, title, p, ident=ident) for p in PARTS]

# B6：先全固定，再加配合（静态装配）
for c in comps:
    doc.ClearSelection2(True)
    c.Select2(False, 0)
    ad.FixComponent()
    doc.ClearSelection2(True)

# 同心配合示例：按半径范围挑最大圆柱面
fa = sw_assembly.find_largest_cylinder_face(comps[0], 0.0099, 0.0101)
fb = sw_assembly.find_largest_cylinder_face(comps[1], 0.0099, 0.0101)
aa, ab = cyl_from_face(fa), cyl_from_face(fb)
sw_assembly.select_entities_for_mate(doc, fa, fb, mark=1)
mate = add_mate5(ad, sw_assembly.SW_MATE_CONCENTRIC,
                 lock_rotation=False, name="CC_demo")

rows = sw_assembly.collect_mate_feature_summary(doc)
n_mates = len([r for r in rows if r.get("depth", 0) >= 1])
print("mates:", n_mates)
if n_mates < 1:
    raise RuntimeError("配合特征树为空：配合没有真正写入")

if aa and ab:
    print("axis radius A/B mm: %.4f / %.4f"
          % (aa["radius_m"] * 1000, ab["radius_m"] * 1000))

rep = sw_measure.inspect_interference(ad)
print("interference:", rep.get("status"),
      rep.get("interference_count"), rep.get("max_volume_mm3"))
if rep.get("status") == "blocked":
    raise RuntimeError("干涉检查不可验证，不能写 pass")

# 存盘用旧 skill 的 save_checked（会先 ForceRebuild3 再存，避免存到旧细分几何）
rc, size = V.save_checked(asm, ASM_OUT, rebuild=True)
print("saved:", ASM_OUT, size, "B")
