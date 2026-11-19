# -*- coding: utf-8 -*-
"""探测草图平面 → 世界坐标映射。建错方向的第一个排查工具。

用法：python probe_axes.py

输出三个基准面的「草图(x,y) → 世界坐标」和「拉伸方向」，用于核对建模契约。
本机 SW2022 实测结果（2026-11-19）：
    Front Plane: 草图(x,y) -> 世界(X,Y)，拉伸 -> +Z
    Top   Plane: 草图(x,y) -> 世界(X,-Z)，拉伸 -> +Y
    Right Plane: 草图(x,y) -> 世界(-Z,Y)，拉伸 -> +X
★ 本机 Y 才是“上下”方向，不是 Z。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import swlib_v2 as V  # noqa: E402


def main():
    sw = V.connect(version=2022)
    print("草图矩形 (x=0..60, y=0..40)，拉伸 20：\n")
    for plane in ("Front Plane", "Top Plane", "Right Plane"):
        m = V.new_part(sw, close_all=True)
        with V.addtoDB(m) as skm:
            V.L.new_sketch(m, plane)
            V.L.rect(skm, 0, 0, 60, 40)
            sk = V.last_sketch_name(m)
            skm.InsertSketch(True)
            V.extrude_checked(m, sk, 20)
        bb = V.L.bbox6(m)
        print("  %-12s -> bbox=%s" % (plane, tuple(round(x, 1) for x in bb)))
        V.close_doc(sw, m)
    print("\n解读：bbox = (xmin,ymin,zmin, xmax,ymax,zmax)")
    print(">>> PROBE AXES DONE")


if __name__ == "__main__":
    main()
