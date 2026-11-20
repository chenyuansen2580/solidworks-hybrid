# SW2022 踩坑速查表

> 本机 SOLIDWORKS 2022 SP5 `30.5.0.0049` / Python 3.12 / pywin32 早绑定实测。
> ★ = 踩过最贵的坑。每条：现象 → 修复。

---

## A. 连接

| 现象 | 修复 |
|---|---|
| `GetActiveObject` 报 MK_E_UNAVAILABLE | 两级 fallback + 往返探测；`Dispatch` 会新开实例 |
| 多实例抢 ROT | 开工前查进程数，>1 先清理 |
| 动态层"找不到成员" / 早绑定 byref 炸 `int()` | 早绑定为主，byref 回退动态 |
| **`RevisionNumber` 早绑定是方法、动态是属性** | `V.com_member(sw,"RevisionNumber")` |
| 进程在但 ROT 未注册 | 先 `Start-Process SLDWORKS.exe` 等 15s，再 connect |
| **★★ `wrap()` 后任何方法报 `no attribute 'InvokeTypes'`** | **`win32com.client.CastTo(obj, iface)` 第二参期望 ProgID/CLSID，传接口名会得到残废对象**。正确做法：`gencache.EnsureModule(TLB,0,30,0)` → 取模块里的接口类 → `cls(obj._oleobj_.QueryInterface(pythonid.ID_IDispatch))` |
| 连接成功但 `RevisionNumber` 返回 method 对象 | 同上，wrap 坏了；修 wrap 后自然正常 |

---

## B. 草图

| 现象 | 根因 | 修复 |
|---|---|---|
| **折线画齿廓 → 7 个轮廓，拉伸 None** | `CreateLine` 端点不自动合并 | 用 `CreateSpline`；或**弧先画线后画** |
| 弧端点不合并、轮廓不闭合 | `CreateArc2` 端点只向已存在点合并 | `IModelDoc2.CreateArc2`；`Create3PointArc` 不可用 |
| 轮廓莫名开口 | 点距 <1e-5mm 样条退化被静默丢弃 | 画前用 `V.spline` 自动去重 |
| **精密小特征被吸歪** | `AddToDB` 默认 False，吸附约 1mm | `with V.addtoDB(m)` |
| **圆心偏移时半径算错** | `CreateCircle(cx,cy,cz,px,py,pz)` 第二组是**圆周上一点** | 用 `V.circle(skm,cx,cy,r)` |
| `CreateCornerRectangle` 不生成特征 | `AddToDB=True` 下偶发 | 小矩形改四条 `CreateLine` |

---

## C. 特征

| 现象 | 根因 | 修复 |
|---|---|---|
| **`FeatureExtrusion3` 静默返回 None，体积 0** | **没选中草图** | `V.extrude_checked` / `V.cut_checked` |
| 偏移拉伸不生效 | 第21参 `T0` 是 `swStartConditions_e` 枚举（3=偏移），第22参才是距离 | `start_mm` 参数已封装 |
| 贯穿只切一半 | `FeatureCut3` 的 `Sd=True` 是**单向** | 双向贯穿 `Sd=False + T1=T2=1` |
| `FeatureFillet` 类型不匹配 | 本机是 **7 参**（GitHub 的 4 参是 SW2024+） | `(Options,R1,Ftyp,OverflowType,Radii,SetBack,PointRadius)` |
| 圆角选择集为空 | `IEdge` 不继承 `IEntity` | `wrap(e,"IEntity").Select2(True,0)` |
| 取草图名拿到 `"Tables"` | `FeatureByPositionReverse(0)` 返回文件夹 | `V.last_sketch_name(m)` 遍历特征树 |
| 造孔要反复切除 | — | **多轮廓一次拉伸**（外环+内环+孔） |
| **两个独立草图不能一起拉伸** | — | 外轮廓+内孔必须画在**同一草图** |

---

## D. 选择与激活

| 现象 | 修复 |
|---|---|
| **`SelectByID2` 坐标精确也返回 False，选中数 0** | **文档未激活**：`ActivateDoc3` + `ShowNamedView2` + `ViewZoomtofit2` + `GraphicsRedraw2` |
| `IEntity.Select2` 对 `GetFaces()` 的面无效 | 面选择只能走 `SelectByID2("","FACE",x,y,z,...)` |
| 基准轴命中点落空 | 用 `ISurface.CylinderParams` 拿真实 `(轴点,轴向,半径)`，在**该面自身**轴向范围采样。**单位米**，bbox6 是毫米 |
| `FeatureByName` 不存在 | 不在 `IModelDoc2` 上，用特征树遍历 |

**草图选择 5 级回退**（`V.select_sketch` 已实现）：
```
1. FeatureByName → Select2
2. 遍历特征树找 ProfileFeature → Select2
3. GetSketchContours() 逐个 Select2
4. GetSketchRegions()  逐个 Select2
5. SelectByID2("SKETCH")     ← 最后手段
```

---

## E. 装配

| 现象 | 根因 | 修复 |
|---|---|---|
| `AddComponent5` 静默返回 None | 零件未载入内存 | 先 `OpenDoc6`，再插入，之后 `ActivateDoc3(装配体)` |
| 保存 rc=256 / 0 字节 | 后续操作作用在零件上 | 同上：每次插完切回装配体 |
| 摆位转置/跑到天边 | `ComposeTransform` 向量是旋转矩阵**列**，须传 `IMathVector` | `V.place()` 已封装；读回布局 `[R(9),T(3),1,0,0,0]` |
| 装配里 `SelectByID2("...@零件-1")` 选不中 | — | `IComponent2.FeatureByName` + `IFeature.Select2` |
| **配合"成功"但没建 / 报错但其实建了** | `AddMate5` 返回**元组** `(IMate2, errStatus)`；`errStatus=1` 才是 NoError | **唯一判据：`V.count_mates()` 增量 >0** |
| ErrorStatus 出参炸 `int()` | 传了 VARIANT | 传**普通 int** |
| 基准轴同心配合不建 | `RefAxis` 的 Select2 语义与面不同 | **基准面重合可靠** |
| **加基准面重合后行星轮全堆轴心** | 同名基准面都过各自中心，贴合=抹掉径向偏置 | 位姿已定就**别加会移动零件的配合**；必须做位姿快照比对 |
| **`SetSuppression2(0)` 后 GetBox 返回 None** | 那是**压缩**不是固定 | `IAssemblyDoc.FixComponent()`，需先选中；`IsFixed()` 只读 |
| 固定组件 `GetBox` 偶发 None | — | `V.snapshot` 已多参数兜底 |

---

## F. 外观

| 现象 | 根因 | 修复 |
|---|---|---|
| **零件设了颜色，装配体里还是灰/黑** | **零件级颜色在装配体不继承**（回读 `[-1,-1,-1]`） | 设**组件级** `IComponent2.SetMaterialPropertyValues2(arr,1,None)` |
| `SetMaterialPropertyValues` 找不到 | 接口归属 | `IModelDocExtension`(1参) / `IFace2`、`IComponent2`(`...Values2` 3参) |
| 回读 0.72 得 0.7176 | 8 位色量化（183/255） | 容差 0.02 |
| 颜色对了但暗面全黑 | SW 默认场景光弱 | `AddLightSource(名, 1=方向/2=点, 名)` 加 2~3 盏 |
| 半透明怎么设 | — | 颜色数组第 8 位是 Transparency：`[R,G,B,Amb,Dif,Spec,Shin,Transp,Emit]` |
| `SetDisplayMode(7)` 报 COM 转换错 | 需要 SHORT | `VARIANT(2, 7)`；`SHADED=3 / SHADED_EDGES=7` |

---

## G. 视图与出图

| 现象 | 修复 |
|---|---|
| **多张图文件大小完全一样** | `ShowNamedView2(name,-1)` **不切视图**。必须传 ID：**iso=7 front=1 top=5 right=4** |
| **装配截图存成别的文档** | `SaveAs3` 导的是**活动文档**，先 `ActivateDoc3(标题)` |
| 工程图尺寸值错 | 按 `IView.GetOrientationName()` 选投影轴：前视 X/Y、上视 X/Z、右视 Z/Y |
| BOM 表插了看不见 / 剖视返回 None | 插完 `ViewZoomtofit2()`；剖切线别 `ClearSelection2`；模板别回退到 A0 |
| **等轴测被遮挡件完全盖住 = 视觉上"没变化"** | 交付图必须有一张能看内部：半透明/隐藏遮挡件/换角度 |

---

## H. IO 与验证

| 现象 | 修复 |
|---|---|
| **保存/导出"成功"但文件 0 字节** | 每次回读 `os.path.getsize() > 0` |
| **中文 `.py` 被 PowerShell 改坏** | 用 `write`/`edit` 工具改文件；`$env:PYTHONIOENCODING="utf-8"` |
| `except: continue` 把"取不到"伪装成"没有" | except 后留可见失败信号 |
| 点集距离测不出"齿穿入齿" | 用**多边形重叠面积**判干涉 |
| 体积差 1e9 倍 | `IMassProperty.Volume` 已是 mm³；`IBody2.GetMassProperties[3]` 是 m³ |
| `GetBodies2` 找不到 | 在 **IPartDoc** 上，不在 IModelDoc2 |

**渲染客观验收**（别只靠眼睛）：
```python
nw = [c for c in px if not (c[0]>245 and c[1]>245 and c[2]>245)]
colored = [c for c in nw if max(c)-min(c) > 15]
bright  = [c for c in nw if 0.299*c[0]+0.587*c[1]+0.114*c[2] > 110]
# 判据：colored > 15% 或 bright > 10%
```

---

## I. 重建零件的代价

| 现象 | 修复 |
|---|---|
| **重跑零件脚本后装配体弹"内部 ID 不匹配"模态框，挂死所有 COM** | SW 给每个文档存内部 ID，同名重建=新 ID。① 改参数不改文件名 ② 必须重建先备份 SLDASM ③ 装配后别再动零件 |
| 装配脚本重复运行插成 2 倍组件 | 加幂等保护：检测配件已存在就跳过 |

**保护机制救了这一次**：位姿比对拦截了保存（dev>=1mm 拒存），磁盘文件保持正确。
**「先快照、后比对、超差拒存」必须一直留着。**

---

## J. 非拉伸类特征（2026-11-19 GitHub 三仓库 + 本机实测新增）

| 现象 | 根因 | 修复 |
|---|---|---|
| **旋转返回 None** | 草图缺中心线 / 轮廓跨轴 | 唯一一条 `CreateCenterLine`（单位是**米**），轮廓全在轴一侧 |
| **`FeatureRevolve2` 角度传 360 不转** | `Dir1Angle` 是弧度 | 传 `math.radians(360)`；库内 `revolve_checked` 已转换 |
| **放样返回 None（两个垂直基准面）** | 截面必须在平行平面 | 用 `V.offset_plane(base, dist)` 建偏移面再放样 |
| **放样只有第一张草图生效** | 多草图没逐张选中 | 每张 `Select2(True,1)` 追加；**本机 MultiSelect2+ISelectData.Mark 卡死，禁用** |
| **`InsertCutBlend4` 找不到成员** | SW2022 是 `InsertCutBlend`（12参），不是 4 | 用 `V.loft_checked(..., is_cut=True)` |
| **扫描返回 None（轮廓画在路径同平面）** | 轮廓平面没垂直于路径起始方向 | 路径 Front Plane 沿 X、轮廓 Right Plane（法向 X）；轮廓过路径起点 |
| **扫描路径选不中** | 路径 mark 错 / 用了 SELOBJGROUP | 路径线段 `Select2(append,4)`；**无需 SELOBJGROUP** |
| **抽壳"找不到成员"** | `InsertFeatureShell` 不在 IModelDocExtension | 在 **IModelDoc2** 上：`m.InsertFeatureShell(t, outward)` |
| **抽壳选了面却不生成特征** | ① 面没用 Select4+mark=1 ② 选面后调了 volume_mm3 清空选择集 ③ 旋转体端面被 SW 拒 | 面 `IEntity.Select4(True,SelectData)` mark=1；诊断全在选面前做；回转件改用带壁厚截面直接 revolve |
| **抽壳判断 `if not rc` 误报失败** | 返回类型 VT_VOID，成功也是 None | 查特征树新增 `Shell` 或体积变化，**不靠返回值** |
| **`IFace2.Select2` 报找不到成员** | IFace2 不继承 IEntity.Select2 | `V.wrap(face,"IEntity").Select4(True, selData)` |
| **圆角 SW2024/2026 传 7 参报 0x8002000F** | GitHub 说 4 参，本机 SW2022 是 7 参 | 按本机版本：SW2022 用 `fillet_checked`（7参）；别照抄 GitHub |
| **圆周阵列只复制一半/返回 None** | Spacing 传了 2π/n | 传总角度 2π + EqualSpacing=True |
| **`FeatureByName` 在 IModelDoc2 上找不到成员** | 真实宿主是 IPartDoc | 用 `V.feat_by_name(m, name)`（IPartDoc 优先 + 遍历回退） |
| **诊断/测量后特征突然失败** | CreateMassProperty/feature_tree 会清空选择集 | 选完目标立刻建特征，中间不插任何查询 |

## K. 钣金 / 属性 / 配置 / 材料（2026-11-19 wzyn+REA 实测新增）

| 现象 | 根因 | 修复 |
|---|---|---|
| **`InsertSheetMetalBaseFlange2` 返回 None** | 已废弃的长参数接口，Python IDispatch 下不可靠 | 走 FeatureData：`CreateDefinition(34=swFmBaseFlange)` → `IBaseFlangeFeatureData.Initialize` → 设属性 → `CreateFeature` |
| **`Initialize` 报"类型不匹配"(-2147352571)** | `CustomBendAllowance` 是 IDispatch(9,1)，传 None 不合法 | 传空 Dispatch：`VARIANT(VT_DISPATCH, None)` |
| **`AddConfiguration3` 找不到成员** | 它在 **IModelDoc2** 上，不在 IConfigurationManager | `wrap(m,"IModelDoc2").AddConfiguration3(...)` |
| **`Get6` 读属性拿到 2 而不是值** | 返回 `(返回码, 值, 解析值, 是否解析, 是否链接)`，值在**索引 1** | `r[1]`；索引 0 是状态码恒为 2 |
| **`GetMaterialPropertyName2` 比较失败** | 返回 `(材料名, 库名)` 二元组 | 取 `r[0]` 再比较 |
| 材料名写错不报错 | SW 静默忽略 | `set_material` 已内置回读校验，失败抛异常 |
| 空字符串属性被忽略 | `Add3` 不写空值 | 写前过滤 `v is None or v==""` |

## L. 曲面 / 焊件（2026-11-19 本机实测新增）

| 现象 | 根因 | 修复 |
|---|---|---|
| **曲面 API 全返回 None 但实际建成了** | `FeatureExtruRefSurface`/`InsertPlanarRefSurface` 返回 VT_VOID | 用 `body_counts()` 前后对比，别看返回值 |
| **`InsertPlanarRefSurface` 找不到成员** | 它在 **IModelDoc2** 上，不在 IFeatureManager | `wrap(m,"IModelDoc2").InsertPlanarRefSurface()` |
| **`FeatureExtruRefSurface` 参数个数报错** | 是 **21 参**，不是 23 | 末尾是 `CapEnd1,CapEnd2,DeleteOriginalFace,KnitResult` |
| **焊件 `InsertStructuralWeldment5` 返回 None** | `Groups` 传了 None | 必须先 `CreateStructuralMemberGroup()` 建组并打包成 **Dispatch SAFEARRAY** |
| **焊件建了组仍失败** | 缺焊件文件夹 | 先 `InsertWeldmentFeature()` |
| **`find_weldment_profiles` 找不到型材** | 库不在 lang 目录 | 本机在 `F:\SOLIDWORKS\data\weldment profiles\`（ansi/*.sldlfp） |

## M. 运动仿真 Motion（2026-11-19 本机实测新增）

| 现象 | 根因 | 修复 |
|---|---|---|
| **`GetMotionStudyManager` 找不到成员** | 它在 **IModelDocExtension** 上，不在 IAssemblyDoc | `wrap(asm,"IModelDoc2").Extension.GetMotionStudyManager()` |
| **Motion 接口全查不到** | 在独立类型库 `swmotionstudy.tlb`，不在 sldworks.tlb | 先 `makepy.GenerateFromTypeLibSpec(r"F:\SOLIDWORKS\swmotionstudy.tlb")` |
| **`new_asm()` 报 `GetTitle` 不存在** | swlib.py 用 `IAssemblyDoc.GetTitle()`，该接口没有此方法 | 已修：先 `wrap(doc,"IModelDoc2").GetTitle()` 再转 IAssemblyDoc |
| **`save_checked(asm, ...)` 报 `SaveAs2` 不存在** | `SaveAs2` 在 IModelDoc2，传进来的是 IAssemblyDoc | 已修：内部先 `wrap(m,"IModelDoc2")` |
| **`Calculate` 返回 False** | 缺马达 / 配合过约束 / 时间设置非法 | 先 `Activate()` 再 `Calculate()`；检查装配体自由度 |
| **帧率设不上** | `IMotionStudyProperties` 本机取不到 | 标 pilot，用默认帧率 |

## N. 坐标映射与上色（2026-11-19 电机支架实战新增）

### N1. 草图平面 → 世界坐标映射（★★ 最容易搞错，必查）

实测方法见 `probe_axes.py`。在草图 (x=0..60, y=0..40) 画矩形、拉伸 20：

| 基准面 | 草图 x → 世界 | 草图 y → 世界 | 拉伸方向 | 实测 bbox |
|---|---|---|---|---|
| **Front Plane** | X（不变） | **Y** | **+Z** | (0,0,0, 60,40,20) |
| **Top Plane** | X（不变） | **−Z** | **+Y** | (0,0,-40, 60,20,0) |
| **Right Plane** | **−Z** | Y（不变） | **+X** | (0,0,-60, 20,40,0) |

★ **本机 Y 才是“上下”方向**，不是 Z。按“Z 向上”写草图会得到躺倒的模型。
★ 世界点 (x,y,z) 画到对应草图：Front→(x,y)；Top→(x,−z)；Right→(−z,y)。

### N2. 加强筋必须画在 Right 平面

- 三角筋要形成“立板 ↔ 底板”的斜撑，三角形必须**垂直于立板**。
- 立板在 Front 平面（XY），筋就必须画在 **Right 平面（−Z,Y）**，沿 **+X** 拉伸。
- 画在 Front 平面 + 沿 Z 拉伸 → 三角形“平放”，筋变成贴在立板表面的薄片，不构成支撑。
- 对称双筋各用一次 `start_mm` 指定起点；**负的 start_mm 会让 extrude 返回 None**，
  改用 `start_mm=正数` 或分两次从不同侧拉伸。

### N3. 上色（★ 本机有硬限制）

| 尝试 | 结果 |
|---|---|
| `IModelDocExtension.SetMaterialPropertyValues(arr9, opt, None)` | 调用成功、回读正确，但**视口/PNG 颜色不变** |
| 只传 3 元素数组 | `类型不匹配 -2147352571`（必须 9 元素） |
| 传裸 list | 同样类型不匹配（必须 `VARIANT(VT_ARRAY|VT_R8)`） |
| CodeStack 官方范式 `GetDisplayStateSetting(任意值)` | **一律抛 -2147417851 服务器意外情况** |

**结论**：本机 SW2022 + Python IDispatch 下**无法通过 API 改变渲染颜色**。
可行替代：① `set_material()` 换材料自带外观（会重置自定义色，先材料后颜色）；
② 导出后用外部工具伪彩；③ 手工在 SW 界面设外观。默认灰白配色可接受。

### N4. 本次实战修正的 skill 缺陷

| 缺陷 | 修正 |
|---|---|
| `save_png` 完全忽略 `w/h` 参数 | 已加 `size_note` 提示；另提供 `set_image_size()` |
| `set_view` 用 `m.GetTitle()` | 改 `com_member(wrap(m,"IModelDoc2"),"GetTitle")`，兼容 IAssemblyDoc |
| `save_checked` 对 IAssemblyDoc 报 `SaveAs2` 不存在 | 内部先 `wrap(m,"IModelDoc2")` |
| `new_asm()` 报 `GetTitle` 不存在 | 先 wrap IModelDoc2 取标题 |
| 无 `open_doc` 封装 | `sw.OpenDoc6` 早绑定返回**元组** `(doc, errs, warns)`，必须取 `r[0]` |

## O. 9 零件装配体实战（2026-11-19，30 项能力全覆盖验收）

本次用一个 9 零件装配体把 30 项 verified 全跑一遍，修掉 9 个 skill 缺陷。

### O1. 旋转：轴必须沿草图 Y 方向（★★ 偏差 768% 的元凶）

```python
# ✗ 错：轮廓沿 X 延伸 + 中心线沿 X → 绕错轴，体积偏差 768%
poly = [(0,0),(0,R2),(L1,R2),(L1,R3),...]      # X 是轴线
skm.CreateCenterLine(0,-0.02,0, 0, L*0.001, 0)  # 水平中心线

# ✓ 对：轮廓「X=半径、Y=轴线」，中心线沿 Y
poly = [(0,0),(R2,0),(R2,L1+L2),(R3,L1+L2),(R3,L), (0,L),(0,0)]
skm.CreateCenterLine(0.0, -0.02, 0.0, 0.0, (L+20)*0.001, 0.0)   # 全 6 参单位是米
```
判据：bbox 的 X/Z 应等于 ±Rmax，Y 等于轴长。若 X/Z 变成 ±L，就是轴画错了。

### O2. 齿轮：孔必须画在同一草图

- ✗ 先拉伸齿廓实体，再在顶面开草图切中心孔 → `cut` 返回 None
  （齿廓 2761 点样条导致面拓扑异常，切除找不到有效面）
- ✓ 齿廓 + 中心圆画在**同一草图**，一次拉伸 → solid=1 且带孔
  实测：56064 − π·10²·20 = 49781，精确吻合

### O3. 整圈齿廓：gearmath 只给单齿廓

`gearmath.flank()` 返回**单侧半齿廓**（55 点，角度 −7.19°..−1.58°）。
要整圈必须自己拼：左半 + 镜像右半 + 齿根圆弧连接 + 旋转 z 次。
已封装为 `scripts/gearring.py`：
```python
from gearring import full_ring, check_ring
ring = full_ring(p, g, list(half.pts))   # 2761 点，闭合
check_ring(ring, g)  # r_ok=True 表示 r_min==rf、r_max==ra
```

### O4. 装配体 bbox / 组件 / 出图（三个接口归属坑）

| 现象 | 根因 | 修复 |
|---|---|---|
| `bbox6(asm)` TypeError 参数过多 | `IAssemblyDoc.GetBox` 只接受 1~2 参 | 改 `GetBox(0)` + 0 参回退 |
| `comps(asm)` 报 `GetComponents` 不存在 | 传的是 IModelDoc2 | 先 `wrap(asm,"IAssemblyDoc")` |
| 装配体 PNG 模型极小、大片留白 | `ViewZoomtofit2` 对装配体不理想 | **新增 `save_png(..., fit=True)`** 走 `zoom_to_model()` → `ViewZoomTo2` 框选 |
| 四视图文件大小完全相同 | 误判 | **不比大小，比 md5 哈希**；实测四视图哈希都不同 |

### O5. 曲面与面类型（两个属性/归属坑）

| 现象 | 根因 | 修复 |
|---|---|---|
| `IsCylinder()` 报 `'bool' object is not callable` | `ISurface.IsCylinder` 在早绑定下是**属性** | 用 `getattr(s,"IsCylinder",False)`；已封装 `face_cylinder()` |
| `surface_thicken` 报 IModelDoc2 无 GetModeler | `GetModeler` 在 **ISldWorks** 上 | `V.surface_thicken(..., sw=sw)` |
| `ThickenSheet` 一律返回 None | 平面/拉伸曲面在本机都加厚失败 | 标 SKIP；不阻塞其它能力 |

### O6. 组件上色（9 元素 + VARIANT）

```python
V.set_component_color(comp, (0.92, 0.72, 0.30))   # 3 参 + 9 元素 + VARIANT
```
- `SetMaterialPropertyValues2` 在 **IComponent2** 上，**3 参**
- 数组必须 9 元素 + `VARIANT(VT_ARRAY|VT_R8)`，裸 list 报类型不匹配
- 返回 None 是正常的（void），不要用返回值判成败
- 颜色别用暗值（0.5 以下），SW 里会显示接近黑色；用 0.6~0.95

## P. 装配布局与出图缩放（2026-11-19 复检新增）

### P1. `V.place` 设的是组件原点，不是 bbox 中心

```python
V.place(sw, comp, V.rot_z(0), (x, y, z))   # (x,y,z) 被当作组件的【平移量】
```
- 组件自身原点若不在几何中心（焊件、非对称件常见），设 `(-340,100,-260)`
  后 bbox 中心实际落在 `(-190,200,-209)` —— **不是同一个点**。
- **迭代逼近不收敛**：反复按 `target - center` 修正，仍会偏移，因为每次设的都是原点。
- **实用做法**：按零件实际 bbox 尺寸手工排网格，允许中心有偏移，
  但保证 **bbox 互不相交**（用 `V.snapshot()` 检查重叠对数=0 即可）。
- `V.snapshot()` 内部有 GetBox 的 3 级回退，能读组件 bbox；
  直接调 `comp.GetBox(0)` 在早绑定下报「类型不匹配」。

### P2. 装配体出图缩放：`ViewZoomtofit2 + ViewZoomout` 最稳

试过的四种方式：

| 方式 | 结果 |
|---|---|
| `save_png(..., fit=True, margin=0.08)` | **过紧**，边缘零件被裁掉 |
| `ViewZoomTo2(bbox 外扩 25%)` | 按包围球算，宽高比不匹配仍裁切 |
| `ViewZoomtofit2()` + ~~`ViewZoomin()`~~ | **放大过头**，边缘零件仍被裁（2026-11-20 纠正） |
| **`ViewZoomtofit2()` + `ViewZoomout()`** | ✓ 完整显示且留边（退一步才是对的） |

★★ 2026-11-20 修正：原结论写 `ViewZoomin()` 是**反的**。
  `ViewZoomin` 是"放大"，装配体 fit 之后已经贴边，再放大必裁；
  要用 **`ViewZoomout`** 退一步留边。
  e2e 套件实测：`Zoomout` 版四视图 36K/9K/17.6K/10K 全部完整，
  `Zoomin` 版 iso 图右侧零件被切掉一半。

★ `margin` 参数在装配体上不可靠，**出图前用 Zoomtofit+Zoomout 手动调**。
★ 四视图逐个 `ShowNamedView2` → `ViewZoomtofit2` → `ViewZoomout` → `SaveAs3`。

### P3. 焊件被"端部切齐"截断

- 批次1 为验证 `cut_through` 在焊件上用大矩形**双向贯穿**切除，
  结果把型材拦腰切断 → 体积从 908360 掉到 15240，`bodies` 变成 2 段。
- ★ 焊件是**多实体**结构，端部切齐要用**小范围单向切除**，
  或直接不切（型材自带端面）。
- ★ 验证 `cut_through` 请用实体零件，不要拿焊件当试验品。
- ★ 焊件必须**单次** `structural_weldment` 建；分两次建第二次必返回 None。

### P4. `cut_checked` 原来不能控制方向

盲孔切在底面而非顶面时，旧版 `cut_checked` 的 `Flip` 参数硬编码 False。
现已加 `reverse` 参数：
```python
V.cut_checked(m, sk, depth_mm=11, reverse=True)   # 反向切除
```
★ 但 `reverse=True` 在多圆草图里只对第一个轮廓生效，混合方向仍会出现。
**最稳做法**：草图直接画在目标端面上（但那需要面拓扑正常，样条齿轮不适用）。

### P5. 装配配合实战（2026-11-19 补全 9 个配合）

| 现象 | 根因 | 修复 |
|---|---|---|
| **`count_mates(asm)` 报 `FirstFeature` 不存在** | `FirstFeature` 在 **IModelDoc2**，不在 IAssemblyDoc | 已修：内部先 `wrap(m,"IModelDoc2")` |
| 曲面件配合全失败 | 曲面体 `GetBody()` 返回 **None**，没有实体面可选 | 改用**组件基准面**：`comp.FeatureByName("Top Plane")` + 装配体基准面 |
| 配合后零件互相穿插 | 同心只锁轴对齐，不锁轴向距离 | 加**距离配合**（`swMateType_e=5`）拉开 |
| 手动 `place` 后位置被拉回 | 配合会强制约束，属正常行为 | 想自由摆放就别加配合；两者互斥 |

**配合类型枚举**（`swMateType_e`）：
```
0=COINCIDENT  1=CONCENTRIC  3=PARALLEL  4=TANGENT  5=DISTANCE  6=ANGLE  10=GEAR
```
**对齐枚举**（`swMateAlign_e`）：`0=ALIGNED 1=ANTI_ALIGNED 2=CLOSEST`

**可用的配合建立模板**：
```python
before = V.count_mates(asm)          # ★ 唯一可信判据
asm.ClearSelection2(True)
V._select_obj(V.wrap(face1, "IEntity"), append=False)
V._select_obj(V.wrap(face2, "IEntity"), append=True)
r = V.wrap(asm, "IAssemblyDoc").AddMate5(
    5,            # mate_type: 5=DISTANCE
    2,            # align: 2=CLOSEST
    False, 0.060, # flip, distance(m)
    0,0, 0,0,0,0,0, False, False, 0)
err = r[1]                          # errStatus: 1=NoError, 0=ErrorUnknown
ok = V.count_mates(asm) > before    # ★ 以增量为准，别信 err
```

**平面选取技巧**：按法向 + bbox 极值挑面
```python
n = V.com_member(face, "Normal")     # 法向是属性
ax = max(range(3), key=lambda i: abs(n[i]))   # 主法向轴
# 再按 GetBox() 在该轴的极值取最外侧平面
```

## Q. GitHub 结论的版本陷阱

| 现象 | 修复 |
|---|---|
| 照抄 GitHub fillet 4 参，本机 SW2022 失败 | GitHub 多为 SW2024/2026；本机 SW2022 是 7 参，**以本机实测为准** |
| wzyn skill 说 loft blocked 走 OCP | 那是 SW2026 结论；本机 SW2022 原生 `InsertProtrusionBlend2` 实测可用 |
| MultiSelect2 在别人的 skill 里能用，本机卡死 | 版本/语言差异；本机统一用对象级 Select2 逐张追加 |
| 拔模/螺旋照抄 GitHub 失败 | wzyn 无独立 draft 封装；helix 的 `InsertHelix` 返回 void 必须回读特征树 |

---

## R. 关键路径

```
类型库:  %TEMP%\gen_py\3.12\83A33D31-...x0x30x0.py
枚举:    ...\4687F359-...x0x30x0.py   (swMateType_e / swAddMateError_e / swDisplayMode_e)
模板:    C:\ProgramData\SolidWorks\SOLIDWORKS 2022\templates\Part.prtdot | AsmEmpty.asmdot
封装库:  scripts/swlib_v2.py
```

**查签名**：`grep "def 方法名" 类型库文件`；接口归属必须先查再写，不靠记忆。

---

## S. 装配 / 扫描 / 工程图（2026-11-20 同步带模组实战，11 条新坑）

### S1 ★ 切除方向：reverse 不能传给 Flip

**现象**：`cut_checked(m, sk, 6.0, reverse=True)` 之后，P5 滑台板 4 个沉孔少切
73319 mm³ —— 正好等于「整块 − 4 个圆柱」，即**切掉了轮廓外侧**。

**根因**：`FeatureCut4` 第 2 参 `Flip` 是【保留轮廓 / 切外侧】(flip side to cut)，
不是反向。方向在第 3 参 `Direction`。

| 参数 | 含义 |
|---|---|
| `Flip`（第 2 参） | True = 保留轮廓切外侧 |
| `Direction`（第 3 参） | True = 沿草图正法向，False = 负法向 |

**修法**（已改进 swlib_v2）：
```python
f = fm.FeatureCut4(sd, False, not reverse, t1, t2, d1, d2, ...)
#                      ^Flip=False      ^Direction
```
**注意**：`Dir=False` 在负法向一侧**没有材料**时返回 None，这不是参数错误。
板向 +Y 拉伸、草图在 y=0 时，负法向无材料 → 只能 `Dir=True`。
`StartOffset` 参数在本机实测**完全无效**（切 12mm 和切 6mm 结果一样），别指望它调盲孔起点。

### S2 ★ fillet / chamfer 多条边：append 必须逐次递增

**现象**：P2 端盖 4 条外框边倒 C1，期望切 199.5，实际只切 50.0
（= 100 × 0.5，正好 **1 条边**）。圆角看起来"成功"，实际只倒了一条。

**根因**：循环里一律 `Select2(False, 0)`，第一个参数是 append，
传 False 会每次**替换**选择集，最终只剩最后一条边。

**修法**（已改进 swlib.py，新增 `_select_edges`）：
```python
for i, e in enumerate(edges):
    wrap(e, "IEntity").Select2(i > 0, 0)   # 首条 False 清空，其余 True 追加
```

### S3 ★ CreateArc2 参数单位是【米】

**现象**：跑道形路径画完，端点读数是 `(480000, -32000)` 而不是 `(480, -32)`，
草图看着闭合、拉伸和扫描全失败。

**根因**：`V.L.line` 内部已乘 `MM=0.001`，但直接调 `m.CreateArc2` 不会。
`CreateArc2` 收米，`swlib.line` 收毫米。

**修法**：
```python
m.CreateArc2(C * MM, 0.0, 0.0,            # 圆心
             C * MM, -R2 * MM, 0.0,      # 起点
             C * MM,  R2 * MM, 0.0, 1)   # 终点，1=逆时针
```

### S4 ★ 扫描失败的头号原因：轮廓圆心没落在路径起点上

**现象**：跑道形闭环路径（1111mm）+ Right Plane 上 R1.5 圆轮廓，扫描恒返回 None。

**排查矩阵**（同一路径，只改轮廓位置）：

| 轮廓圆心 | 结果 |
|---|---|
| (0, −16) = 路径起点 | **OK** vol=7848.4，dev −0.09% |
| (0, 0) | None |
| Top Plane (0,0) | None |

**铁律**：轮廓圆心必须**精确重合**于路径起点坐标，不是"靠近"。
另外轮廓平面必须垂直于路径起点处的**切线**方向。
闭环路径可以扫（官方文档说 twist 须整圈倍数，本机实测 twist=0 亦通过）。

### S5 ★ IFace2.GetBox() 返回零件局部坐标

**现象**：装配体里挑"基座顶面 y=50"，用世界坐标筛，一个面都挑不到。

**根因**：`IFace2.GetBox()` 和 `ISurface.PlaneParams` 的法向都是**零件局部坐标**，
不是装配世界坐标。P6 导轨世界 x = −200..300，但面 box 显示 −250..250。

**修法**：挑面用零件自身尺寸给值；要世界坐标得叠加 `IComponent2.Transform2`。

### S6 ★ V.place 设的是组件原点，不是 bbox 中心

**现象**：按目标位置摆件，非对称零件（如焊件框、电机板）整体偏移。

**修法**：迭代把 bbox 最小角移到目标点，3~5 次收敛到 0.05mm：
```python
def place_to(comp, R, target_min, iters=5):
    V.place(sw, comp, R, (0, 0, 0))
    t = [0.0, 0.0, 0.0]
    for _ in range(iters):
        b = [x * 1000 for x in comp.GetBox(0, False)]
        d = [target_min[i] - b[i] for i in range(3)]
        if max(abs(x) for x in d) < 0.05:
            break
        t = [t[i] + d[i] for i in range(3)]
        V.place(sw, comp, R, t)
```

### S7 ★ 焊件切割清单要存盘重开才出现

**现象**：焊件建好，`feature_tree` 里 `WeldmentFeature` 有了，但 `CutListFolder` 为 0，
`InsertWeldmentCutList2(None)` 也返回 None。

**修法**：存盘 → 关闭 → 重开，`CutListFolder` 才出现在特征树（实测 2 项）。
`InsertWeldmentCutList2` 是插表格用的，不是生成切割清单的。

### S8 ★ 型材库默认配置是 6 英寸，必须用 config 指定小规格

**现象**：700×300 焊件框体积 4,879,147 mm³，渲染时把整个模型都盖住了。

**根因**：`find_weldment_profiles()` 只给 .sldlfp 文件路径，默认配置是库里最大规格
（152mm 角钢）。该库实际有 91 个配置。

**修法**：
```python
V.structural_weldment(m, sk, prof, config="Al LS ANGLE SQR END 1 x 0.75 x 0.125")
# 25.4 x 19.05 x 3.18 mm，体积降到 260,849
```
查配置名：`open_doc(prof)` → `GetConfigurationNames()`。

### S9 ★ 工程图：中文视图名 + IDrawingDoc 宿主

**现象**：`CreateDrawViewFromModelView3` 用 `*Isometric` / `*Front` 一律返回 False，
`*等轴测` / `*前视` 返回 True。

**三条铁律**：
1. 本机 SW 是**中文界面**，视图名必须中文：`*等轴测` `*前视` `*上视`
2. 方法在 **IDrawingDoc** 上，不在 IModelDoc2（`getattr` 直接 AttributeError）
3. 装配体必须先在会话里打开并激活

**验证视图真插进去了**：读返回值 `V.com_member(V.wrap(r,"IView"),"GetName2")`
→ "工程图视图1"；SLDDRW 从 25 KB 涨到 340 KB 以上。
**别用 `GetFirstView`/`GetNextView` 数视图**，本机第二步就抛异常。

### S10 ★ 干涉检查必须调 IAssemblyDoc

**现象**：`V.check_interference(asm)` 返回 `('ERROR', '类型不匹配')`，
误判成"有干涉"。

**根因**：`ToolsCheckInterference2` 在 **IAssemblyDoc** 上，
旧版 `swlib_v2.check_interference` 用 IModelDoc2 调必抛 −2147352571。

**修法（已落地，2026-11-20 修完）**：
```python
ok, raw = V.interference_ok(asm)     # (True, (None, None)) —— 推荐
V.check_interference(asm)            # 底层版，内部已强制 wrap IAssemblyDoc
```
★ 函数内部现在先 `wrap(asm, "IAssemblyDoc")` 再调，传 IModelDoc2 进来也不会抛。
★ 但**别自己直接调** `asm.ToolsCheckInterference2(...)` —— 走封装。

### S11 零厚度曲面体在装配体不渲染

**现象**：P11 护罩（0 实体 2 曲面）在零件里能出图，装配体里完全看不见，
`GetBody()` 返回 False。

**根因**：SW 装配体默认不渲染曲面体。

**修法**：`sw.SetUserPreferenceToggle(155, True)` 和 `(209, True)` 开曲面显示；
若仍不显示，就在总装里隐藏该组件，单独出零件图证明曲面能力，并在报告里注明。

### S12 ★ 装配必须一次成型 —— 反复加/删配合会让视口彻底锁死

**现象**（最诡异的一条）：
`belt_actuator.SLDASM` 经过几轮"加配合 → 删配合 → 求解器拉动"之后，
`ShowNamedView2` / `Orientation3` / `SaveAs3` / `SaveBMP` **全部失效**：
- 四视图 md5 完全相同，图片大小恒为 129823 B
- 改用 `SaveBMP` 得到 2.6 MB BMP，但四张内容一样
- 改用 `Orientation3` 显式设矩阵，仍然一样
- `ViewZoomtofit2` 后图像被裁切、视角不对

**对照实验**（决定性证据）：
新建一个装配体，只插 2 个零件，同一套 `ShowNamedView2 + ViewZoomtofit2 +
GraphicsRedraw2 + SaveAs3` 立刻正常 —— 四视图 95K / 5.5K / 15.7K / 7.3K，
md5 互异。**API 没问题，是那个 .SLDASM 文件坏了。**

**根因**：反复删除配合、求解器多次重算，文档内部状态损坏，视口不再响应
视图指令。存盘重开也救不回来。

**修法 —— 装配一次成型**（`b6_all.py`）：
```
新建装配体 → 逐件插入并用 bbox 迭代摆位 → 【全部固定】→ 上色
→ 加 10 组配合（固定状态下漂移恒 0）→ 隐藏曲面件 → 出四视图 → 存盘
```
全部在**同一个会话、同一个函数**里完成，中途不存盘、不重开、不删配合。

**配套铁律**：
1. **全部组件先 Fix 再加配合**。不固定时，一个平面重合配合会让零件在其余
   5 个自由度上乱跑 —— 实测 `p4_pulley` 从 Y −33.9..33.9 漂到 12.7..101.3，
   总漂移 135 mm，整个装配散架。全部固定后漂移恒 0.00 mm。
2. **配合的距离值必须等于摆放时的真实间隙**。摆放间隙 12.5 却传 10，
   求解器会把零件拉走。先量 bbox 再定距离。
3. **每条配合后比对所有组件 bbox**，漂移 >1mm 就判该配合不一致：
```python
def max_drift(a, b):
    return max(max(abs(a[k][i] - b[k][i]) for i in range(6))
               for k in a if k in b)
```

**顺带纠正两条旧结论**：
- `ShowNamedView2` 在本机对**健康文档**完全正常，返回 None 是 void 返回值的正常表现
- `SaveAs3` 对装配体出 PNG 也没问题（127K / 9K / 35K / 16K 四张各不相同）

### S13 ★ mirror / circular_pattern 的 mark 与轴（两个都写反过）

**mirror_checked 旧版 mark 体系是反的**：

| 版本 | 被镜像特征 | 基准面 | 结果 |
|---|---|---|---|
| 旧（错） | mark=4 | mark=1 | 恒返回 None |
| 新（对） | **mark=1** | **mark=2** | Δ = −4000.00 精确 |

六种组合实测，只有 `特征 mark=1 + 面 mark=2` 能成。已修 `swlib_v2.mirror_checked`。

**circular_pattern 的轴必须垂直于「孔心↔中心」连线**：

孔开在 (X=25, Y=0)，圆柱轴沿 Z。三个轴 × count=6 实测：

| 轴 | 交线 | 新增孔数 | 判定 |
|---|---|---|---|
| X | Top × Right | **+5.00** | ✓ 正确（count−1） |
| Z | Front × Top | +1.34 | ✗ 孔在轴上，转不出新孔 |
| Y | Front × Right | 返回 None | ✗ |

★ 母特征必须传【切除特征名】——特征树里类型名是 **`ICE`**，不是 `Cut`/`Extrusion`。
  传草图名必返回 None。

### S14 ★ weldment_cut_list 是"读"不是"建"

**现象**：旧版调 `InsertWeldmentCutList2(None)` 必返回 None。

**根因**：那个方法是【插入切割清单表格】用的，不是生成切割清单。
切割清单是 SW 建焊件时自动生成的 `CutListFolder`。

**修法**（已落地）：
```python
V.weldment_cut_list(m)        # 返回 ['切割清单项目1', ...]，读特征树
V.weldment_cut_list_table(m)  # 插表格（PILOT，位置不可控）
```

**但 CutListFolder 的生成条件不稳定**（PILOT 维持）：

| 案例 | 尺寸 | bodies | CutListFolder |
|---|---|---|---|
| belt_actuator P14 | 700×300，角钢总长 2000mm | 4 | **2 项** |
| capcheck 小框 | 200×120，总长 640mm | 4 | **0 项** |

同样 4 实体、同配置，只有尺寸不同。结论：与型材总长/切分方式有关，
不是纯 API 行为。**别把它当必然结果**。

### S15 hole_wizard 在本机确实不可用（4 轮实测）

按官方 VBA 示例复刻，试遍组合全部返回 None：

| 变量 | 试过的值 |
|---|---|
| StandardIndex | 0~5 |
| FastenerTypeIndex | 0~3 |
| SSize | `""` `"10"` `"0.375"` `"M10"` `"M2"` `"#97"` |
| hole_type | 2(Hole) 1(CounterSink) |
| end_type | 0(Blind) 1(ThroughAll) |
| 选择方式 | 草图点 / 面点 |

**结论**：维持 PILOT。但封装**会抛明确 RuntimeError**，不是静默失败 —— 这点已保证。
要打孔请用普通贯穿切除（`cut_checked`），已验证 0.000% 精确。
