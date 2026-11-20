# SolidWorks Modeling Skill

本机 SolidWorks 2022 全流程建模技能：需求规划 → 齿廓/变形数学 → COM 建模 → 装配配合 → 运动仿真 → 校核 → 出图。

> 所有 API 签名、接口归属、参数顺序均基于 **SOLIDWORKS 2022 SP5 (30.5.0.0049)** 本机类型库实测。
> **不照抄 GitHub 上针对 SW2024/2026 的结论** —— 版本差异会直接导致失败。

## 环境要求

| 项 | 要求 | 说明 |
|---|---|---|
| 系统 | Windows 10/11 x64 | 走 COM 自动化，跨平台不可用 |
| CAD | SOLIDWORKS 2022 SP5（30.5.0.0049） | ProgID `SldWorks.Application.30`；换版本需改 `connect()` 的 version |
| Python | 3.12 x64 + **pywin32** | `pip install pywin32`；3.13 本机实测同样可跑，早绑定缓存目录随版本变化 |
| 选装 | numpy、shapely | **仅** `scripts/check_harmonic.py`（齿廓校核）需要，其余脚本零第三方依赖 |

## 能做什么

**建模（38 项 verified）**
- 基础特征：拉伸、切除（贯穿/盲孔）、旋转、放样、扫描、抽壳
- 修饰：圆角、倒角、**圆周阵列**、**镜像**、拔模（梯形/圆台等效法）
- 专用：钣金基体法兰、曲面（拉伸/平面区域/**旋转**）、结构件焊件、偏移基准面
- 已知不可用：孔向导（4 轮实测全部 None）、曲面加厚、API 上色、STL 导出
- 专业：渐开线齿轮（齿条包络 + 整圈拼接）、谐波齿轮（摆线 CTP + 椭圆变形）

**装配**：插入、**bbox 迭代摆位**、固定、组件上色、**同心/距离/重合配合（含平面重合）**、
位姿快照比对、**漂移检测**、干涉检查

**运动仿真**：运动算例创建、计算、播放、结果读取、AVI 导出

**属性**：自定义属性、配置、材料（含回读校验）

**出图**：四视图（含 fit 缩放）、工程图、自动标注、剖视图、STEP/PDF

**校核门禁**：三段式判据（None→命名→重建→回读）、四级验证（BLOCKED>FAIL>WARN>PASS）、跨版本参数个数自适应

## 快速开始

```python
import sys; sys.path.insert(0, r"<SKILL_DIR>/scripts")
import swlib_v2 as V

sw = V.connect(version=2022)              # ProgID=SldWorks.Application.30
m = V.new_part(sw)
with V.addtoDB(m) as skm:                 # ★ 关闭 1mm 吸附
    V.L.new_sketch(m, "Front Plane")
    V.circle(skm, 0, 0, 25)               # 传圆周上一点，不是半径
    sk = V.last_sketch_name(m)
    skm.InsertSketch(True)
    V.extrude_checked(m, sk, 50)          # 5 级选草图回退，失败抛异常

V.volume_check(m, 3.14159265*25*25*50)    # 体积校验
V.save_checked(m, r"C:\temp\cyl.SLDPRT")
```

## 自检（改完库必跑）

```bash
python scripts/run_all.py --static   # 0.7 秒，不开 SW ★ 每次改完先跑
python scripts/run_all.py --quick    # 2.4 分钟，smoke + features
python scripts/run_all.py            # 6.5 分钟，全量 8 套件
python scripts/run_all.py --force    # 强制重跑（源文件没变默认跳过）
```

| 套件 | 覆盖 |
|---|---|
| smoke | 圆柱全链路：体积/bbox/四视图 |
| features | 旋转/抽壳/放样/扫描/圆角/倒角（dev 0.0000%） |
| draft | 梯形/圆台拔模等效 |
| sheetmetal | 钣金基体法兰（dev 0.0000%） |
| props | 属性/配置/材料回读 |
| surface | 曲面 + 结构件焊件 |
| motion | 装配体 + 运动算例 + 计算 |
| gate | 四级验证门禁降级逻辑 |

## 目录结构

```
SKILL.md                  主入口：7 条铁律 + 快速开始 + 路由表 + 能力总览
references/
  workflow.md             8 步流程、坐标契约（含基准面映射表）、验收矩阵
  pitfalls.md             A~R 十八章 121 条踩坑速查
  features.md             13 种手法的选择集 mark 与完整参数
  api-map.md              接口归属表 + 参数签名陷阱 + 外部查证源
  gears.md                渐开线包络 + CTP 摆线 + 椭圆变形
  example_bracket.md      实战案例：电机支架（坐标契约+体积解析）
  example_assembly.md     全能力验收：9 零件装配体 30/30
scripts/
  run_all.py              一键自检（4 档速度）
  swlib_v2.py             核心封装（97 函数，按领域分区）
  swlib.py                底层接口（gencache QueryInterface 正路）
  verify_gate.py          四级交付门禁
  gearring.py             齿轮整圈齿廓拼接（补 gearmath 缺口）
  gearmath.py             渐开线几何（纯 Python）
  probe_axes.py           探测三基准面轴映射
  verify_all.py           行星减速器数学校核
  check_harmonic.py       谐波齿轮校核
  smoke_test.py           环境自检
  test_features.py        6 种基础手法实测
  test_draft.py           拔模等效实测
  test_sheetmetal.py      钣金实测
  test_props.py           属性/配置/材料实测
  test_surface.py         曲面 + 焊件实测
  test_motion.py          运动仿真实测
assets/
  harmonic_profiles.json  谐波齿廓点集（已降采样 1/4，138 KB）
```

## 四条最容易踩的坑

1. **坐标映射先查表**：本机 **Y 才是"上下"**，不是 Z。
   `Front(x,y)→XY 拉伸+Z` / `Top(x,-z)→XZ 拉伸+Y` / `Right(-z,y)→ZY 拉伸+X`。
   写错会得到躺倒的模型。

2. **选择集 mark 是命门**：`Select2(append, mark)` 优先；面/边退 `Select4(True, SelectData)`。
   扫描路径 mark=4、放样截面 mark=1、阵列轴 mark=1 母特征 mark=4、抽壳面 mark=1。
   **诊断/测量调用会清空选择集** —— 选完面立刻建特征。

3. **void API 不能靠返回值判成败**：`InsertFeatureShell`、`FeatureExtruRefSurface`、
   `InsertPlanarRefSurface` 成功也返回 None，必须用特征树/几何变化判据。

4. **接口归属必须查证**：`GetPartBox`→IPartDoc、`InsertFeatureShell`→IModelDoc2、
   `GetMotionStudyManager`→IModelDocExtension、`GetModeler`→**ISldWorks**、
   `FirstFeature`→IModelDoc2、`AddConfiguration3`→IModelDoc2。凭记忆写必翻车。

## 已知限制

**本机 API 走不通**（已试遍所有路径，不是用法问题）：

| 能力 | 现象 | 替代 |
|---|---|---|
| 渲染上色 | `GetDisplayStateSetting` 抛 −2147417851 | `set_material()` / `set_component_color()` |
| 曲面加厚 | `ThickenSheet` 恒返回 None | 用实体拉伸替代 |
| STL 导出 | COM 导 0 字节 | 界面导出或 STEP 转换 |
| 运动帧率 | `IMotionStudyProperties` 取不到 | 用默认帧率 |
| 剖视图 | 需先画剖面线，未端到端实测 | — |
| BOM 插表 | 数据能取，表格位置不可控 | 自建表格 |

## License

MIT

## 自检套件（10 个）

```bash
python scripts/run_all.py --static   # 0.7 秒，不开 SW ★ 每次改完先跑
python scripts/run_all.py --quick    # 9 分钟，6 个核心套件 ★ 日常够用
python scripts/run_all.py            # 13 分钟，全量 10 套件
python scripts/run_all.py --cold     # 每套件冷启（排障用）
```

| 套件 | 覆盖 | 时长 |
|---|---|---|
| smoke | 圆柱全链路：体积/bbox/四视图 | 47s |
| features | 旋转/抽壳/放样/扫描/圆角/倒角 | 122s |
| draft | 梯形/圆台拔模等效 | 52s |
| sheetmetal | 钣金基体法兰 | 42s |
| props | 属性/配置/材料 | 42s |
| surface | 曲面 + 结构件焊件 | 65s |
| motion | 装配体 + 运动算例 + 计算 | 66s |
| **assembly** | 端到端：摆位/固定/配合/漂移/干涉/四视图/工程图/重开 | 201s |
| **doctest** | SKILL.md 示例代码实跑（6 组） | 142s |
| **capcheck** | 能力表抽查：阵列/镜像/孔向导/曲面/焊件 | 167s |

后三个是 2026-11-20 加的，专门守「组合行为」「文档示例」「能力表真实性」——
这三类以前没有测试覆盖。

## 实战案例

| 案例 | 内容 |
|---|---|
| `references/example_belt_actuator.md` | **14 零件同步带模组**：31/31 能力覆盖、14 件体积全 0.000%、12 条新坑 |
| `references/example_assembly.md` | 9 零件装配体：30/30 能力覆盖（历史记录） |
| `references/example_bracket.md` | 电机支架：多基准面 + 加强筋 + 出图 |

## 踩坑速查

`references/pitfalls.md` —— **19 章 176 条**，全部本机实测。

最后三章是 2026-11-20 新增：
- **S13** mirror / circular_pattern 的 mark 与轴（两个都写反过）
- **S14** weldment_cut_list 是"读"不是"建"
- **S15** hole_wizard 在本机确实不可用（4 轮实测记录）
