# -*- coding: utf-8 -*-
"""建模模板：用 solidworks-modeling / swlib_v2。

复制后改名，按实际零件修改。
"""
import os
import sys
import math

HERE = os.path.dirname(os.path.abspath(__file__))
COMMON = HERE          # 与本文件同目录；发布版从自身位置解析
if COMMON not in sys.path:
    sys.path.insert(0, COMMON)

import hybrid_common as H       # noqa: E402
H.setup()

with H.use_scripts("modeling"):
    import pythoncom             # noqa: E402
    pythoncom.CoInitialize()
    import swlib_v2 as V         # noqa: E402

# ---------------- 参数（示例：法兰 Ø60 x 8, bore Ø20.2, 4xØ6.5 @R22）
OD = 60.0
TH = 8.0
BORE = 20.2
HOLE_D = 6.5
HOLE_R = 22.0
OUT = os.path.join(HERE, "example_flange.SLDPRT")

theory = math.pi / 4 * (OD ** 2 - BORE ** 2) * TH \
         - 4 * math.pi / 4 * HOLE_D ** 2 * TH
bbox = [-OD / 2, -OD / 2, 0, OD / 2, OD / 2, TH]

sw = V.connect(version=2022, verbose=False, warn_multi=False)
m = V.new_part(sw)

# 一次草图拉伸：外圆 + 中心孔 + 4 孔
with V.addtoDB(m) as skm:
    V.L.new_sketch(m, "Front Plane")
    V.circle(skm, 0, 0, OD / 2)
    V.circle(skm, 0, 0, BORE / 2)
    for a in (45, 135, 225, 315):
        V.circle(skm, HOLE_R * math.cos(math.radians(a)),
                 HOLE_R * math.sin(math.radians(a)), HOLE_D / 2)
    sk = V.last_sketch_name(m)
    skm.InsertSketch(True)

V.extrude_checked(m, sk, TH)
V.volume_check(m, theory, tag="flange")
V.verify(m, volume=theory, bbox=bbox, bodies=1)
V.set_material(m, "6063-T5")
V.set_custom_props(m, {"PartNumber": "EX-01", "Description": "示例法兰",
                       "Project": "HYBRID", "Material": "6063-T5"})
V.add_configuration(m, "HYBRID")
rc, size = V.save_checked(m, OUT, rebuild=True)
print("saved:", OUT, size, "B")
V.close_doc(sw, m, force=True)
