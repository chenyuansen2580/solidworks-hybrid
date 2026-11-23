# Hybrid 契约：旧 skill 建模 + 新 skill 装配验真

## 1. 为什么这样分工

旧 `solidworks-modeling`：

- 针对本机 SW2022 实测；
- `swlib_v2` 封装 123 个函数；
- 建模的坑（草图选择、拉伸、切除、旋转、倒角、圆角、属性、材料、配置、存盘重建）已经固化；
- 体积/bbox/特征树三重断言很简单；
- 缺点是装配验真层弱：`count_mates` / `max_drift` / 旧干涉判据容易假成功。

新 `solidworks-automation`：

- 面向多入口、多后端；
- 装配层有组件解析、装配上下文实体映射、AddMate5 错误码、配合特征树、自由度、干涉三态；
- 缺点是本机 SW2022 没有官方声明支持，建模 API 在本机踩坑多，速度慢。

所以：

```text
建模 = 旧 skill
装配/验真 = 新 skill
```

---

## 2. 建模阶段固定调用

```python
import sys
OLD_SCRIPTS = H.OLD_SCRIPTS     # 由 hybrid_common 自动发现
sys.path.insert(0, OLD_SCRIPTS)

import pythoncom
pythoncom.CoInitialize()
import swlib_v2 as V

# V.L 是 swlib 模块别名（swlib_v2.py line 44: import swlib as L）
# 所以 V.L.new_sketch / V.L.rect / V.L.line 是正确入口。
sw = V.connect(version=2022, verbose=False, warn_multi=False)
```

### 建模标准代码骨架

```python
m = V.new_part(sw)
with V.addtoDB(m) as skm:
    V.L.new_sketch(m, "Front Plane")
    V.circle(skm, 0, 0, r)
    sk = V.last_sketch_name(m)
    skm.InsertSketch(True)
V.extrude_checked(m, sk, depth)
V.volume_check(m, theory_volume)
V.verify(m, volume=theory_volume, bbox=theory_bbox, bodies=1)
V.set_material(m, material)
V.set_custom_props(m, props)
V.add_configuration(m, "RF120")
V.save_checked(m, path, rebuild=True)
V.close_doc(sw, m, force=True)
```

### 建模禁止项

- 不用 `sw_part.sketch/extrude_boss` 建零件；
- 不用 `sw_hole_features.create_through_hole` 建孔；
- 不用 `sw_gear` 在 SW2022 上建齿轮。

---

## 3. 装配阶段固定调用

```python
import os
import sys
NEW_SCRIPTS = H.NEW_SCRIPTS     # 由 hybrid_common 自动发现
sys.path.insert(0, NEW_SCRIPTS)
os.environ["SW_ATTACH_EXISTING_DISPATCH"] = "1"

import pythoncom
pythoncom.CoInitialize()

import sw_connect
import sw_assembly
import sw_measure

sw, _ = sw_connect.connect_solidworks(version=2022)
```

### 装配模板

```python
EMPTY_ASM = r"C:\ProgramData\SolidWorks\SOLIDWORKS 2022\templates\AsmEmpty.ASMDOT"
asm = sw_connect.new_document(sw, "assembly", template_path=EMPTY_ASM)
```

禁止使用 `Assembly.asmdot`，它带 4 个模板组件且可能弹框挂住 COM。

### 插入组件

```python
c = sw_assembly.add_component(asm, part_path, x=0, y=0, z=0, sw=sw)
sv_assembly.resolve_component(c)
```

### 选圆柱面并建配合

```python
face = sw_assembly.find_largest_cylinder_face(c, min_radius, max_radius)
sw_assembly.select_entities_for_mate(asm, face_a, face_b, mark=1)
mate = sw_assembly.add_mate5_checked(asm, sw_assembly.SW_MATE_CONCENTRIC)
```

### 回读配合

```python
rows = sw_assembly.collect_mate_feature_summary(asm)
mates = [r for r in rows if r.get("depth", 0) >= 1]
```

### 干涉

```python
rep = sw_measure.inspect_interference(asm)
if rep.get("status") == "blocked":
    raise RuntimeError("干涉检查不可验证，不能写 pass")
```

判定：

| rep.status | 含义 |
|---|---|
| `pass` | 无实体干涉 |
| `warn` | 有干涉体（需看 `max_volume_mm3`） |
| `blocked` | 无法验证，判 BLOCKED |

---

## 4. 装配策略选择

### 静态装配

例如夹具、支架、滑台、箱体布置：

```text
零件建模完成
→ 插入组件
→ 按 bbox/坐标摆位
→ 固定组件
→ 添加配合作为工程语义
→ 干涉验真
→ 存盘
```

允许先固定再加配合，因为配合不用于驱动位置，只作为工程约束表达。

### 运动装配

例如铰链、齿轮传动、可动机构：

```text
插入组件
→ 只固定基准件
→ 解析并映射实体
→ 添加配合（lock_rotation=False）
→ 回读配合特征
→ 验自由度
→ 验几何轴心距
→ 固定或保存
→ 干涉验真
```

固定件加配合不会参与求解。必须保持自由件可动。

---

## 5. 必验项

### 零件

| 项 | 判据 |
|---|---|
| volume | dev < 0.5%，优先 < 0.05% |
| bbox | 逐项 < 0.5 mm |
| bodies | 1 solid / 0 surface |
| feature tree | 有真实建模特征 |
| material | 回读一致 |
| props | 4 条以上回读 |
| config | 至少 Default + 自定义 |
| save | > 0 字节 |

### 装配

| 项 | 判据 |
|---|---|
| components | 达到设计数量 |
| mates | 达到设计数量 |
| 配合特征树 | MateGroup 下有真实 Mate 特征 |
| 轴心距 | 同心配合 < 0.05 mm |
| 干涉 | `inspect_interference` 非 blocked，实体干涉体积 < 阈值 |
| save | > 0 字节 |

---

## 6. SW2022 必避坑

| 坑 | 规避 |
|---|---|
| `GetMathUtility` / `ActivateDoc3` 类型不匹配 | QI 成 `ISldWorks` |
| `IComponent2.Transform2` | QI 成 `IComponent2` |
| `IFace2.GetBox` / `EditRebuild3` / `GetNames` | 本机可能是属性，用 `get_com_member` 或判断 callable |
| `Assembly.asmdot` | 禁用 |
| `sw_gear` | SW2022 卡死，禁用 |
| 齿轮啮合 | 用光轮/静态占位，不建真齿廓 |
| 固定件配合 | 不参与求解 |
| 旧干涉 verdict | clean 不可达，用新 `sw_measure` |
| 新孔特征方向 | 已做版本自适应，但建模仍优先旧 skill |

---

## 6.1 SW2022 实机实测约束（2026-11-23，ballscrew_slide_v1 全流程验证）

以下 9 条是**实测踩出来的**，不是推断。每条都有对应的实证 trace。
`skill 文档里没写 → 下次会话必然原样重踩`，所以必须固化在这里。

### A. 建模阶段

#### A1. 材料名：无效名**静默不生效**，必须先枚举库文件拿实名

`SetMaterialPropertyName2` 对不存在的材料名**不报错**，只是保持旧材料不动。
直接写 `"6061 Alloy"` / `"Alloy Steel"` 会「调用成功但读回空」，35 件全部返工。

**正确做法**：先从 `.sldmat` 枚举实名，再调 API，最后回读。

```python
# 枚举材料库（.sldmat 是 UTF-16，不是 UTF-8）
import re
SLDMAT = r"F:\SOLIDWORKS\lang\chinese-simplified\sldmaterials\solidworks materials.sldmat"
t = open(SLDMAT, "rb").read().decode("utf-16")
names = re.findall(r'<material name="([^"]+)"', t)      # 本机 259 条
```

本机已验证可用的实名：

| 用途 | 材料名 |
|---|---|
| 铝合金 | `6061 合金`（也可 `6061-T6 (SS)`） |
| 钢 | `合金钢` / `普通碳钢` / `AISI 1020` |
| 塑料 | `ABS` / `ABS PC` |

```python
V.set_material(m, "6061 合金")
assert V.get_material(m) == "6061 合金", "材料回读不一致 -> 名字错了"
```

#### A2. `add_configuration` 不能加已存在的 `Default`

新建零件已有 `Default` 配置，`AddConfiguration3("Default", ...)` 返回 `None` 抛错。
要先 `m.GetConfigurationNames()` 查，只追加**新名字**。

```python
existing = list(m.GetConfigurationNames() or [])
if "AUDIT_CONFIG" not in existing:
    V.add_configuration(m, "AUDIT_CONFIG")
```

#### A3. 草图平面 → 世界坐标（本机实测映射表）

| 基准面 | 草图 x | 草图 y | 拉伸方向 | 法向 |
|---|---|---|---|---|
| Front | X | Y | **+Z** | +Z |
| Top | X | **−Z** | **+Y** | +Y |
| Right | **−Z** | Y | **+X** | +X |

结论（建全局坐标零件时的最佳组合）：

- **Z 向长方体 / Z 向圆** → Front Plane，`extrude(start_mm=z0)`
- **X 轴向圆柱** → Right Plane 画圆（草图 `x = -z_world, y = y_world`），`extrude(start_mm=x0)`
- `start_mm` **可以是负数**，实测正确（`start_mm=-40` → bbox z 从 −40 起）

#### A4. 只有"真正覆盖全长"才用贯穿切除，否则必须定向盲切

`cut_checked(m, sk)` 双向贯穿会把**盲孔也切成通孔**（滑块 M3 盲孔少切 2.2% 体积即此因）。

```python
covers_all = (t0 <= lo + 1e-6) and (t1 >= hi - 1e-6)   # lo/hi = 零件该轴全长
if covers_all:
    V.cut_checked(m, sk)                               # 双向贯穿
else:
    pn = V.offset_plane_named(m, "Front Plane", t1)    # 从远端面
    ...                                                # 画圆
    V.cut_checked(m, sk, depth_mm=t1 - t0, reverse=False)  # 定向盲切
```

实测：定向盲切体积与解析值**逐位吻合**（`removed == π r² Δ`）。

#### A5. 环形（管）用双同心圆一次拉伸，不要"先实心再挖孔"

联轴器阶梯盲孔（Ø8.4 / Ø12.4 两段）如果建成「实心圆柱 + 内孔切除」，
内孔草图落在材料内部时 `cut` **返回 None**。

正确：把两段画成**双同心圆 → 拉伸**，得到管；两段用不同内径分别拉伸即阶梯孔。

```python
with V.addtoDB(m) as skm:
    V.L.new_sketch(m, "Right Plane")
    V.circle(skm, -cz, cy, r_out)
    V.circle(skm, -cz, cy, r_in)      # 内圆 -> 拉伸得到环形
    sk = V.last_sketch_name(m); skm.InsertSketch(True)
V.extrude_checked(m, sk, length, start_mm=x0)
```

#### A6. `revolve_checked` 在 SW2022 不稳定

`CreateCenterLine` + `revolve_checked` 在本机抛
`-2147352571 类型不匹配`。**用多段同轴 `extrude` 叠出台阶回转体**，
几何等价、体积逐位吻合、且能保证 `bodies=1`。

### B. 装配阶段

#### B1. `AddComponent5` 需要「先开零件 → 再激活装配体」，且**必须释放窗口**

```python
sw.OpenDoc6(path, 1, 0, "", 0, 0)
sw.ActivateDoc3(asm_title, False, 0, 0)          # 注意：裸 int 0，不要 VARIANT
c = ad.AddComponent5(path, 0, "", False, "", 0.0, 0.0, 0.0)
```

**关键**：会话内打开文档数会累积，到第 33 件左右 `AddComponent5` 开始**稳定返回 None**。
每插完一件立即 `sw.CloseDoc(part_name + ".SLDPRT")` 释放窗口（装配体仍持组件引用，
几何不受影响）。实测可一直插到 35 件。

#### B2. 插入后组件以**自身 bbox 中心**定位，必须显式归位

`AddComponent5(..., 0,0,0)` 不是"放到原点"。
拿到的组件 bbox 是**以自身中心为原点**的局部框；如果零件建在全局坐标，
必须补一次单位变换，位置才回到建模坐标。

```python
ident = sw_assembly.make_transform(sw, 0, 0, 0, 0, "Z")
sw_assembly.set_component_transform(c, ident, rebuild=False)
# 实测：归位后 component bbox == 零件理论 bbox，dev = 0.0 mm
```

#### B3. `AddMate5` 的 `error_status` 在 SW2022 必须传**裸 int**

`sw_assembly.add_mate5_checked` 内部传 `VARIANT(VT_BYREF|VT_I4)`，在本机抛
`int() argument must be a string, a bytes-like object or a real number, not 'VARIANT'`。
四种写法实测只有一种通过：

| 写法 | 结果 |
|---|---|
| `L.byref_int(0)` | 抛 VARIANT 错 |
| `VARIANT(VT_BYREF\|VT_I4, 0)` | 抛 VARIANT 错 |
| **裸 `0`** | **通过，写出真实 Mate 特征** |
| `V.com_member(...)` | 抛 VARIANT 错 |

```python
m = ad.AddMate5(int(mate_type), int(align), bool(flip),
                0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                False, bool(lock_rotation), 0,
                0)          # ← 裸 int
```

同时注意接口归属：`AddMate5` 在 **`IAssemblyDoc`**；`ClearSelection2` 在 `IModelDoc2`。

#### B4. `ISurface` / `IFace2` 成员在本机是**属性**，调用即报错

`GetSurface` / `IsCylinder` / `CylinderParams` / `GetArea` / `IsPlane` / `PlaneParams`
在本机都是属性，加括号调用会报 `-2147352573 找不到成员`。

```python
s = f.GetSurface                # 不加括号
if s.IsCylinder:                # 不加括号
    p = list(s.CylinderParams)  # 不加括号
    r = float(f.GetArea)        # 不加括号
```

#### B5. `PlaneParams` 布局是 `[法向, 过点]`，且法向被规范化

```python
pp = [float(x) for x in s.PlaneParams]
nx, ny, nz, px, py, pz = pp      # ← 法向在前！与多数文档相反
```

**而且** SolidWorks 会把法向统一规范化成正轴向——同一实体的底面也返回 `+Z`。
所以**不能按法向符号筛面**，只能按"平面过点坐标"筛：

```python
if abs(abs(n[k]) - 1.0) > 1e-3: continue      # 只要平行于目标轴
if abs(p[k]*1000.0 - coord_mm) > 0.05: continue   # 按过点坐标筛
```
（`CylinderParams` 布局是 `[px,py,pz, ax,ay,az, r]`，位置在前、方向在后，与 `PlaneParams` 相反。）

#### B6. 平面重合配合会**拉走**未固定组件 → 必须先全固定再加配合

只固定基准件、其余自由，加一条平面重合配合后，自由件会在剩余 5 个自由度上跑掉，
并在装配完成时产出**假干涉**（本次实测 6 处，最大 10 657 mm³）。

```python
# 正确顺序：插入 → 全部 Fix → 再加配合
for c in comps:
    doc.ClearSelection2(True); c.Select2(False, 0)
    ia.FixComponent(); doc.ClearSelection2(True)
```

固定后 bbox 仍逐项 `dev = 0.0 mm`，配合照常写入特征树。
**静态装配可以这样**；运动装配不能（见 §4）。

---

## 7. 默认停止点

```yaml
modeling: true
assembly: true
drawing: false
review: false
```

装配验收通过后停止。

不生成：

```text
PNG / PDF / SLDDRW / BMP / JPG / TIF
四视图 / md5 / 像素统计
drawing/ / preview/
```

不调用：

```text
drawing_delivery
review.run_review
```
