---
name: solidworks-assembly
description: "bbox 摆位、全部固定、同心/距离/重合配合、漂移检测、干涉检查。本机 SW2022 实测，依赖根技能 solidworks-modeling 的脚本。"
metadata:
  parent: solidworks-modeling
  status: verified
  verified_on: "SOLIDWORKS 2022 SP5 (30.5.0.0049)"
---

# 装配体与配合

## 何时调用

用户说：装配 / 配合 / 摆位 / 干涉 / 10 组配合 / 装配体

## 依赖根技能（不复制代码）

- `swlib_v2.py (place_to / fix_all / faces_of / plane_at / cyl_of / max_drift / interference_ok)`
- `test_assembly.py (端到端 15 断言)`

## 能力边界

- ★ 装配一次成型：插入→摆位→全部 Fix→配合→出图→存盘，同一会话
- 不固定就加配合会把零件拉散（实测 135mm）
- V.place 设组件原点，非对称件必须用 place_to 迭代 bbox
- IFace2.GetBox() 是零件局部坐标，不是世界坐标
- 圆阵列/镜像的母特征传切除特征名（类型名 ICE）

## 工作流

1. 插组件 + place_to 逐个 bbox 定位（dev <0.1mm）
2. fix_all 固定全部组件
3. faces_of + plane_at/cyl_of 挑面（sign=None 最稳）
4. 加配合，每条后 max_drift <1mm
5. interference_ok 验无干涉，存盘

## 覆盖能力

- `asm.insert`
- `asm.place`
- `asm.fix`
- `asm.mate.*`
- `export.step`

## 参考

- `references/example_belt_actuator.md`
- `references/pitfalls.md S5/S6/S12 章`

## 交付门禁

- 几何断言通过（体积 / bbox / 实体数）
- 过程有 `exec_trace` 留痕
- 交付文件通过 `artifact_freshness` 校验
- 无法验证的项目记 BLOCKED，不写 PASS
