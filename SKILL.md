---
name: solidworks-modeling
description: "本机 SolidWorks 2022 全流程建模技能：从需求规划、齿廓/变形数学、COM 建模、装配配合、运动仿真，到校核出图。当用户要求用 SolidWorks 画零件/装配体/减速器/齿轮，或提到 SW 建模、拉伸、切除、旋转、放样、扫描、抽壳、圆角、倒角、拔模、阵列、镜像、钣金、焊件、曲面、孔向导、属性、配置、材料、装配、配合、运动仿真、工程图、BOM、渲染时调用。所有 API 签名基于本机 SW2022 实测；含 176 条踩坑速查与可复用脚本。"
metadata:
  category: engineering-cad
  verified_on: SOLIDWORKS 2022 SP5.0 / 30.5.0.0049 / typelib v30
  python: "3.12.4 / pywin32"
---

# SolidWorks 建模技能（本机 SW2022 实测）

## 铁律（违反必踩坑，共 8 条）

1. **不猜 API**：长参数方法先 `grep "def 名" 类型库`，接口归属必须查证。
   类型库：`%TEMP%\gen_py\3.12\83A33D31-...x0x30x0.py`
2. **不造轮子**：先读 `references/` 与 `scripts/`，已封装的不重写。
3. **不瞎试**：同一问题试错 2 次未通，立刻查 `references/pitfalls.md`，再查 GitHub。
4. **每步验证**：返回值不可信，判 None 不判真，用「体积+bbox+特征树」三重断言。
5. **先存后改**：已保存文档改动前必须备份；建完即存、存完即截、截完即关。
6. **选择集 mark 是命门**（GitHub wzyn 2199★ + 本机实测）：
   `Select2(append, mark)` 优先，面/边失效才退 `Select4(True, SelectData)`。
   - 拉伸/切除草图 = 0；放样截面 = 1；扫描轮廓 = 1；**扫描路径 = 4**
   - 圆周阵列轴 = 1、母特征 = 4；镜像基准面 = 1、被镜像特征 = 4
   - 抽壳要删的面 = 1；圆角/倒角边 = 0（本机）或 1（wzyn）
   - ★ 诊断/测量调用会清空选择集 —— 选完面立刻建特征，中间别插 `volume_mm3()`
7. **坐标映射先查表**（★ 建错方向的头号原因，本机实测）：

   | 基准面 | 草图 x → | 草图 y → | 拉伸方向 |
   |---|---|---|---|
   | Front | X | **Y** | **+Z** |
   | Top | X | **−Z** | **+Y** |
   | Right | **−Z** | Y | **+X** |

   **本机 Y 才是“上下”**，不是 Z。世界点 (x,y,z) → 草图：Front(x,y) / Top(x,−z) / Right(−z,y)。
   写草图前先对这张表，不确定就跑 `probe_axes.py`。
8. **装配一次成型**（2026-11-20 血泪）：插入 → `place_to` 摆位 → **`fix_all` 全部固定**
   → 加配合 → 出图 → 存盘，**同一个会话内完成**。
   中途不删配合、不存盘重开 —— 反复增删配合会让 `.SLDASM` 视口彻底锁死
   （四视图恒为同一张图，`ShowNamedView2`/`Orientation3`/`SaveAs3`/`SaveBMP` 全部失效，
   存盘重开也救不回来）。

---

## 快速开始

```python
import sys; sys.path.insert(0, r"SKILL_DIR/scripts")
import swlib_v2 as V

sw = V.connect(version=2022)              # ProgID=SldWorks.Application.30
m = V.new_part(sw)
with V.addtoDB(m) as skm:                 # ★ 关闭 1mm 吸附
    V.L.new_sketch(m, "Front Plane")
    V.circle(skm, 0, 0, 25)               # 第二组参数是圆周上一点，V.circle 已封装
    sk = V.last_sketch_name(m)
    skm.InsertSketch(True)
    V.extrude_checked(m, sk, 50)          # 内部 5 级选草图回退，失败抛异常

V.volume_check(m, 3.14159265*25*25*50)    # 体积校验
V.save_checked(m, r"C:\temp\cyl.SLDPRT")
```

**装配最小闭环**（★ 顺序不能变：摆位 → 固定 → 配合 → 出图）

```python
asm = V.new_asm(sw)
title = V.com_member(V.wrap(asm, "IModelDoc2"), "GetTitle")
comps = {}
for key, path, R, tgt in LAYOUT:            # tgt = bbox 最小角目标点(mm)
    c = V.add_component(sw, asm, title, path)
    V.place_to(sw, c, R, tgt)               # ★ 迭代 bbox，不手算坐标
    comps[key] = c

V.fix_all(asm)                              # ★★ 必须全部固定，否则配合会把零件拉散

F = {k: V.faces_of(v) for k, v in comps.items()}   # 局部坐标面清单
box0 = V.all_boxes(asm)
# ... 加配合（AddMate5 + count_mates 判增量）...
print("漂移", V.max_drift(box0, V.all_boxes(asm)), "mm")   # 必须 <1mm

print(V.interference_ok(asm))               # (True, (None, None))
V.save_checked(asm, r"C:\temp\asm.SLDASM")
```

**环境自检**（按需选档，别每次都跑全量）

```bash
python scripts/run_all.py --static   # 0.7 秒，不开 SW ★ 每次改完先跑这个
python scripts/run_all.py --quick    # 9 分钟，+ assembly + doctest + capcheck ★ 日常够用
python scripts/run_all.py            # 6.5 分钟，全量 8 套件
python scripts/run_all.py --cold     # 10 分钟，每套件冷启（排障用）
python scripts/run_all.py --force    # 强制重跑（默认源文件没变会跳过）
```

| 档位 | 覆盖 | 何时用 |
|---|---|---|
| `--static` | 编译 + 导入 + 能力表 + 门禁 | 每次改完代码 |
| `--quick` | + smoke + features + **assembly** + **doctest** + **capcheck** | 改完 swlib_v2 主逻辑 |
| 全量 | + draft/sheetmetal/props/surface/motion | 发版前、改接口签名后 |

三种优化（原 10 分钟 → 0.7 秒 / 2.4 分钟 / 6.5 分钟）：
1. **静态层不开 SW**：0.7 秒拦掉 80% 破坏（语法错、函数被删、能力表被改坏）
2. **套件间不 kill SW**：首个冷启后共用实例，省掉 7 次冷启动
3. **增量跳过**：源文件没变且上次全过 → 直接跳过；`--force` 强制重跑

| 套件 | 覆盖 |
|---|---|
| smoke | 圆柱全链路：体积/bbox/四视图 |
| features | 旋转/抽壳/放样/扫描/圆角/倒角（dev 0.0000%） |
| draft | 梯形/圆台拔模等效 |
| sheetmetal | 钣金基体法兰（dev 0.0000%） |
| props | 属性/配置/材料回读 |
| surface | 曲面 + 结构件焊件 |
| motion | 装配体 + 运动算例 + 计算 |
| **assembly** | **端到端：摆位/固定/配合/漂移/干涉/四视图/工程图/重开** |
| **doctest** | **SKILL.md 里的示例代码实跑（6 组）** |
| **capcheck** | **能力表抽查：圆周阵列/镜像/孔向导/旋转曲面/焊件切割清单** |
| gate | 四级验证门禁降级逻辑 |

---

## 路由：按需求读哪份参考

| 需求 | 读 | 关键内容 |
|---|---|---|
| 建模流程、验收纪律、交付清单 | `references/workflow.md` | 8 步流程、验收矩阵、三重断言 |
| 报错、返回 None、行为诡异 | `references/pitfalls.md` | **A~S 十九章 176 条速查** |
| 齿轮/齿廓/谐波变形 | `references/gears.md` | 渐开线包络、摆线 CTP、椭圆变形 |
| API 签名与接口归属 | `references/api-map.md` | 本机实测的接口归属表 + REA 2164 命令号 |
| 旋转/放样/扫描/抽壳/阵列/镜像/拔模/曲面/焊件/运动 | `references/features.md` | 12 种手法的选择集 mark 与完整参数 |
| **完整实战案例**（多基准面+加强筋+出图） | `references/example_bracket.md` | 电机支架：坐标契约、体积解析、5 个缺陷修复 |
| **全能力验收案例**（9 零件装配体） | `references/example_assembly.md` | 30 项 verified 全覆盖、9 个缺陷修复记录 |
| **最新全能力案例**（14 零件同步带模组） | `references/example_belt_actuator.md` | **31/31 当时清单全覆盖、14 件体积 0.000%、12 条新坑** |
| 建错方向 / 坐标不对 | `scripts/probe_axes.py` | 一键探测三基准面的轴映射 |
| **装配组合行为怎么验** | `scripts/test_assembly.py` | 端到端 9 项断言（摆位/固定/漂移/视图/重开） |

---

## 核心封装（scripts/swlib_v2.py，106 函数）

> 这里只列**每天都在用**的。旋转/放样/扫描/抽壳/圆角/阵列/镜像/拔模/曲面/焊件/
> 运动/齿轮等专业手法 → 见 `references/features.md`（含完整参数与 mark 表）。

**连接与自适应**
```python
V.connect(version=2022, wait_ready=30)    # 两级 fallback + 往返探测
V.com_member(obj, "RevisionNumber")       # 属性/方法自适应（不是方法！）
V.open_doc(sw, path, doc_type=1)          # ★ OpenDoc6 返回元组，内部已处理
V.com_call_arity(fm, "FeatureXxx", args)  # 跨 SW 版本参数个数漂移自适应
```

**草图**（★ 全部内置避坑）
```python
with V.addtoDB(m) as skm:                 # AddToDB=True，关 1mm 吸附
    V.L.new_sketch(m, "Front Plane")
    V.circle(skm, cx, cy, r)              # 传圆周上一点，不是半径
    V.spline(skm, pts)                    # 自动去重 tol=1e-5
    sk = V.last_sketch_name(m)            # 遍历特征树，不用 FeatureByPositionReverse
    skm.InsertSketch(True)
```

**特征**（★ 自动保证草图已选中）
```python
V.extrude_checked(m, sk, depth, start_mm=0)   # 5 级回退选草图，失败抛异常
V.cut_checked(m, sk, depth_mm=None)           # None=双向贯穿；reverse=True 走负法向
V.select_sketch(m, name, verbose=True)        # 单独调用时看走了哪条路径
```

**校核**
```python
V.volume_mm3(m)                       # 单位已统一（IMassProperty vs IBody2 差 1e9）
V.volume_check(m, theory, tag="x")    # 返回 (ok, 实测, 偏差%)
V.verify(m, volume=..., bbox=..., bodies=1)   # 体积按相对%、bbox 按绝对 mm
V.body_counts(m)                      # (实体数, 曲面体数)
V.capability_report()                 # 38 verified + 10 pilot + 3 not_implemented
V.require_verified("part.extrude")    # 交付门禁，pilot 直接拒绝
```

**装配**（★ 2026-11-20 新增 12 个封装 + 修 1 个，全部本机实测）
```python
comps = V.comps(asm)                  # {实例名: IComponent2}
V.count_mates(m)                      # 配合是否真建成（唯一可信判据）
V.set_component_color(comp, (0.92, 0.72, 0.30))  # 组件级上色（9元素+VARIANT）

# 摆位：★ place 设的是【组件原点】，非对称件必偏 → 用 place_to
V.place(sw, comp, V.rot_z(90), (x, y, z))
V.place_to(sw, comp, V.rot_x(-90), (0, 20, -10))  # 迭代 bbox 最小角到目标点
V.rot_x(90) / V.rot_y(90) / V.rot_z(90)          # 三个旋转矩阵构造器
V.fix_all(asm)                        # ★ 不固定则配合把零件拉散（实测 135mm）

# 挑面：★ IFace2.GetBox() 是【零件局部坐标】，不是世界坐标
F = V.faces_of(comp)                  # [{f, plane, cyl, box, dims, n, area}]
V.plane_at(F, "y", None, 10.0)        # 局部 y=10 的平面（sign=None 不校验朝向）
V.cyl_of(F, 12.0)                     # 恰好两维=Ø12 且面积最大（排除减重孔）

# 漂移检测
box0 = V.all_boxes(asm)               # = snapshot()，含 GetBox 3 级回退
V.max_drift(box0, V.all_boxes(asm))   # >1mm 即判该配合与摆放位置不一致
V.diff_snapshot(box0, V.all_boxes(asm))   # 逐组件明细 [(名, 偏差)]

# 干涉：★ 必须在 IAssemblyDoc 上（IModelDoc2 必抛，会误判成"有干涉"）
ok, raw = V.interference_ok(asm)      # (True, (None, None))
```

**出图**
```python
V.set_view(sw, m, "iso")              # 视图 ID：iso=7 front=1 top=5 right=4
V.save_png(sw, m, path, "iso")        # 激活→切视图→截图→回读大小
V.four_views(sw, m, outdir, prefix)   # 四视图
```
★ `SaveAs3` 不支持自定义分辨率，`w/h` 参数无效。
★ **装配体出图**（2026-11-20 修正：原来写 `ViewZoomin()` 是错的）：
```python
d = V.wrap(m, "IModelDoc2")
for v in ("iso", "front", "top", "right"):
    d.ShowNamedView2(V.VIEW_NAME[v], V.VIEW[v])
    d.ViewZoomtofit2()
    d.ViewZoomout()                          # ★ 退一步留边（Zoomin 会放大过头被裁）
    d.GraphicsRedraw2(); d.SaveAs3(path, 0, 0)
```
★ **工程图插视图**：本机 SW 是中文界面，视图名必须中文 + 宿主是 IDrawingDoc：
```python
v = V.drawing_view(dw, model_path, "*等轴测", 0.15, 0.13)   # 不是 *Isometric
V.view_name_of(v)                                          # "工程图视图1"
```
★ 四视图是否真的不同**比 md5 哈希，不比文件大小**。

**交付门禁**（`scripts/verify_gate.py`，移植 wzyn 2199★）
```python
from verify_gate import Gate, PASS, WARN, FAIL, BLOCKED
g = Gate("part")
g.check("volume", ok, "体积偏差 0.01%")
g.check("visual_review", None, "未目视复核", level=BLOCKED)  # 无法验证≠PASS
v = g.verdict()    # BLOCKED>FAIL>WARN>PASS；空结果一律 BLOCKED
```

**专业手法**（详见 `references/features.md`）
```python
V.revolve_checked(m, sk, 360)             # ★ 轮廓「X=半径、Y=轴线」，中心线沿 Y
V.loft_checked(m, [s1, s2])               # 平行截面，逐张 Select2(mark=1)
V.sweep_checked(m, prof, path)            # ★ 轮廓圆心必须精确落在路径起点
V.shell_checked(m, 2.0, faces=[face])     # 测量必须在选面【之前】做
V.fillet_checked(m, 5.0, edges=edges)     # ★ 多条边 append 逐次递增
V.chamfer_checked(m, 3.0, edges=edges)
V.circular_pattern_checked(m, feat, axis, 8)  # ★ 轴垂直于孔心连线；母特征传 ICE 名
V.mirror_checked(m, feat, "Right Plane")      # ★ 特征 mark=1 面 mark=2
V.draft_extrude(m, 40, 40, 20, 5)         # 棱柱拔模等效，dev -0.07%
V.draft_cone(m, 20, 15, 20)               # 圆台拔模，dev 0.0000%
V.sheetmetal_base_flange(m, sk, 2.0, radius_mm=2.0, length_mm=40)
V.surface_extrude(m, sk, 50)              # → (0实体, 1曲面)
V.surface_planar(m, sk) / V.surface_revolve(m, sk, 360)
V.structural_weldment(m, sk, prof, config="Al LS ANGLE SQR END 1 x 0.75 x 0.125")
V.weldment_cut_list(m)                    # 读 CutListFolder（存盘重开后才非空）
V.hole_wizard(...)                        # PILOT：本机不可用，用普通切除替代
V.motion_manager(asm) / V.create_motion_study(asm) / V.calculate_motion(ms)
```

**齿轮整圈齿廓**（`scripts/gearring.py`）
```python
import gearmath as G
from gearring import full_ring, check_ring
p = G.GearParams(mn=2.5, z=24, bw=20, bore=10)   # ★ 参数名是 mn/bw，不是 m
g = G.GearGeom(p)
ring = full_ring(p, g, list(G.flank(p, g).pts))   # 整圈闭合点列（2761 点）
assert check_ring(ring, g)["r_ok"]
# ★ 中心孔必须和齿廓画在同一草图，一次拉伸 → solid=1
```

---

## 能力总览（38 verified / 10 pilot / 3 not_implemented）

> **2026-11-20 用 14 零件同步带模组做过全量验收：31/31 当时清单全覆盖，14 件体积全部 0.000%**；
> 之后 capcheck 又实证了 mirror / surface.revolve / plane_coincident 三项，能力表升至 38 verified。
> 详见 `references/example_belt_actuator.md`（主推案例）。
> 2026-11-19 的 9 零件装配体（30/30，`example_assembly.md`）作为历史记录保留。

| 领域 | verified | pilot（需人工复核） |
|---|---|---|
| **基础特征** | 拉伸、切除（贯穿/盲孔）、旋转、放样、扫描、抽壳 | — |
| **修饰** | 圆角、倒角、**圆周阵列**、**镜像**、拔模（等效法） | 孔向导、真拔模 |
| **专用** | 钣金基体法兰、曲面拉伸/平面/**旋转**、结构件焊件、偏移基准面 | 焊件切割清单 |
| **属性** | 自定义属性、配置、材料 | — |
| **装配** | 插入、定位、固定、组件上色、**同心/距离/重合配合（含平面重合）** | 轴向自动对齐（须手加距离配合） |
| **出图** | 四视图、PNG（含 fit）、STEP | 剖视图、自动标注、BOM 插表 |
| **运动** | 运动算例、计算 | 帧率、结果读取、AVI |
| **专业** | 渐开线齿轮、谐波变形、弧、样条 | — |
| **门禁** | 三段式判据、四级验证、跨版本 arity | — |

**⚠️ 本机不可用**：曲面加厚（`ThickenSheet` 恒 None）、渲染上色（`GetDisplayStateSetting` 抛异常）。

`V.capability_report()` 打印完整清单；`V.require_verified(名)` 作交付门禁。

---

## 建模标准顺序

```
坐标契约 → 参数表 → 验收矩阵 → 主基准体 → 凸台 → 切除/孔
→ 阵列 → 圆角倒角 → 外观 → 三重断言 → 四视图 → 交付
```

**关键**：引用基准面/轴/原点/命名草图，**不引用后面会被切掉的面**。

---

## 高频坑 Top 16（完整 176 条见 pitfalls.md）

| # | 现象 | 修复 |
|---|---|---|
| 1 | `FeatureExtrusion3` 静默返回 None | 前一步必须选中草图 → 用 `V.extrude_checked` |
| 2 | `AddToDB` 默认 False，1mm 吸附毁草图 | `with V.addtoDB(m)` |
| 3 | `CreateCircle` 第二组是圆周上一点 | 用 `V.circle` |
| 4 | 四视图看起来一样 | **比 md5 哈希，不比文件大小**（大小相同≠图相同） |
| 5 | 装配体 PNG 边缘零件被裁切 | `ViewZoomtofit2()` + **`ViewZoomout()`**（Zoomin 会放大过头），别依赖 `fit/margin` |
| 6 | 零件级颜色在装配体不继承 | 用 `V.set_component_color()`（组件级 + 9元素 VARIANT） |
| 7 | `SetSuppression2(0)` 不是固定 | 用 `IAssemblyDoc.FixComponent()`，需先选中 |
| 8 | `AddMate5` 返回值不可信 | 用 `V.count_mates()` 判增量；**并比对 `max_drift` 判零件有没有被拉走** |
| 9 | 旋转体体积偏差几百% | **旋转轴必须沿草图 Y 方向**，轮廓「X=半径、Y=轴线」 |
| 10 | 重建零件后装配体弹"内部 ID 不匹配" | 零件一次建好；必须重建先备份 SLDASM |
| 11 | 配合加完零件位置全乱、总漂移上百 mm | **先 `fix_all` 再加配合**；配合值必须等于摆放时的真实间隙 |
| 12 | 四视图恒为同一张图，所有视图 API 失效 | **装配一次成型**，别反复增删配合（`.SLDASM` 视口会锁死） |
| 13 | `IFace2.GetBox()` 挑面永远挑不到 | 返回的是**零件局部坐标**，不是装配世界坐标 |
| 14 | 干涉检查返回 `('ERROR', ...)` | `ToolsCheckInterference2` 在 **IAssemblyDoc** 上，用 `V.interference_ok()` |
| 15 | 工程图 `CreateDrawViewFromModelView3` 恒 False | 中文视图名 `*等轴测` + 宿主 **IDrawingDoc** + 模型须已存盘激活 |
| 16 | 闭环扫描恒返回 None | **轮廓圆心必须精确落在路径起点**；手写 `CreateArc2` 要 ×0.001（米） |

**接口归属速查**（凭记忆写必翻车，全部本机实测）：

| API | 真实宿主 | 常被误认为 |
|---|---|---|
| `GetPartBox` / `GetBodies2` | IPartDoc | IModelDoc2 |
| `GetComponents` / `FixComponent` / `AddComponent5` | IAssemblyDoc | IModelDoc2 |
| `InsertFeatureShell` / `AddConfiguration3` / `GetTitle` | IModelDoc2 | IAssemblyDoc / Extension |
| `GetMotionStudyManager` / `SetMaterialPropertyValues` | IModelDocExtension | IModelDoc2 / IAssemblyDoc |
| `SetMaterialPropertyValues2` | IComponent2 / IFace2 | IModelDoc2 |
| `GetModeler` | **ISldWorks** | IModelDoc2 |
| `ToolsCheckInterference2` | **IAssemblyDoc** | IModelDoc2（会抛 −2147352571） |
| `CreateDrawViewFromModelView3` | **IDrawingDoc** | IModelDoc2（AttributeError） |
| `InsertStructuralWeldment5` 的 `config` | 型材库配置名，默认 6 英寸 | — |
| `SetDisplayStateSpecMaterialPropertyValues`（不可用） | IModelDocExtension | — |

---

## 交付前检查

- [ ] 每个零件 `volume_check` 通过（偏差 <0.5%）
- [ ] 装配 `max_drift` <1mm（配合没把零件拉走）
- [ ] `interference_ok(asm)` 返回 `True`
- [ ] 四视图 **md5 互异**（不是比文件大小）
- [ ] 四视图非空且**目视**检查
- [ ] 渲染图有颜色（像素统计 colored>15% 或 bright>10%）
- [ ] 文件大小回读 >0
- [ ] 新坑已写入 `references/pitfalls.md`

---

## 已知限制（pilot 清单）

**本机环境下 API 走不通的**（不是用法问题，已验证遍所有路径）：

| 能力 | 现象 | 替代方案 |
|---|---|---|
| 渲染上色 | `GetDisplayStateSetting` 一律抛 −2147417851 | `set_material()` 或 `set_component_color()`（装配体） |
| 曲面加厚 | `ThickenSheet` 恒返回 None | 用实体拉伸替代，或界面手工加厚 |
| STL 导出 | COM 导 0 字节 | 界面导出或转 STEP 后外部转换 |
| 运动帧率 | `IMotionStudyProperties` 取不到 | 用默认帧率 |
| 剖视图 | 已封装但需先画剖面线，未端到端实测 | — |
| BOM 插表 | 数据能取，表格位置不可控 | 自建 BOM 表格 |

**版本相关**：
- 本机 SW2022，GitHub 上针对 2024/2026 的结论**必须重新实测**
- 孔向导 `StandardIndex` 须热身后才有效
- 运动马达创建未封装（只能建算例+计算）
