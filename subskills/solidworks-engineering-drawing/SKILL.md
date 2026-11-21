---
name: solidworks-engineering-drawing
description: "零件图/装配图、四视图、PDF/BMP 证据、中文视图名、md5 互异校验。本机 SW2022 实测，依赖根技能 solidworks-modeling 的脚本。"
metadata:
  parent: solidworks-modeling
  status: verified
  verified_on: "SOLIDWORKS 2022 SP5 (30.5.0.0049)"
---

# SolidWorks 工程图与出图

## 何时调用

用户说：出图 / 工程图 / 四视图 / 渲染图 / PDF / 导出图纸

## 依赖根技能（不复制代码）

- `swlib_v2.py (drawing_view / view_name_of / set_view / save_png)`
- `artifact_freshness.py (交付文件新鲜度)`

## 能力边界

- 本机 SW 是中文界面，视图名必须中文：*等轴测 / *前视 / *上视
- CreateDrawViewFromModelView3 在 IDrawingDoc 上，不在 IModelDoc2
- 装配体出图用 ViewZoomtofit2 + ViewZoomout（Zoomin 会裁切）
- 四视图是否不同比 md5，不比文件大小
- 剖视图 / BOM 插表仍是 pilot / not_impl，不在本子技能交付范围

## 工作流

1. 确认模型已在会话打开并激活
2. 用 V.set_view / V.save_png 出四视图，校验 md5 互异
3. 用 V.drawing_view 插中文视图名（工程图须先存盘）
4. 导出 PDF / SLDDRW，回读文件大小 >0
5. 用 F.require_fresh 确认交付文件是本轮新增

## 覆盖能力

- `drawing.create`
- `export.png`
- `export.step`

## 参考

- `references/features.md 工程图章节`
- `references/pitfalls.md P2/S9 章`

## 交付门禁

- 几何断言通过（体积 / bbox / 实体数）
- 过程有 `exec_trace` 留痕
- 交付文件通过 `artifact_freshness` 校验
- 无法验证的项目记 BLOCKED，不写 PASS
