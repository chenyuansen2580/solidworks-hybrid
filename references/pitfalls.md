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

### P2. 装配体出图缩放：`ViewZoomtofit2 + ViewZoomin` 最稳

试过的三种方式：

| 方式 | 结果 |
|---|---|
| `save_png(..., fit=True, margin=0.08)` | **过紧**，边缘零件被裁掉 |
| `ViewZoomTo2(bbox 外扩 25%)` | 按包围球算，宽高比不匹配仍裁切 |
| **`ViewZoomtofit2()` + `ViewZoomin()`** | ✓ 完整显示且留边 |

★ `margin` 参数在装配体上不可靠，**出图前用 Zoomtofit+Zoomin 手动调**。
★ 四视图逐个 `ShowNamedView2` → `ViewZoomtofit2` → `ViewZoomin` → `SaveAs3`。

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
