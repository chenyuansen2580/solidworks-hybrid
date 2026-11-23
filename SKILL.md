---
name: solidworks-hybrid
description: "SolidWorks 2022 建模/装配融合技能。建模阶段复用 solidworks-modeling 的 swlib_v2 快速精确建模；装配与验真阶段复用 solidworks-automation 的组件解析、配合错误码、自由度和干涉三态。适合需要既快又能证明装配正确的本地 CAD 任务。"
metadata:
  os: ["win32"]
  requires:
    anyBins: ["python", "py"]
  parent_skills:
    - solidworks-modeling
    - solidworks-automation
  verified_on:
    solidworks: "2022 SP5 / 30.5.0"
    python: "3.12.4"
  scope_default:
    modeling: true
    assembly: true
    drawing: false
    review: false
---

# SolidWorks Hybrid（建模快 + 装配真）

## 何时使用

用户要求在本机 SolidWorks 2022 上建模、装配、验证零件或简单机构，并且：

- 需要零件体积/bbox/特征树快速精确验收；
- 需要装配体、配合、干涉、组件位姿验证；
- 默认不出图、不截图、不做 PDF/SLDDRW；
- 希望避免在两个 skill 之间混用 API 导致返工。

---

## 核心分工（必须遵守）

| 阶段 | 只用哪个底座 | 为什么 |
|---|---|---|
| 零件建模 | `solidworks-modeling`（旧 skill） | SW2022 原生验证，建模封装稳定，体积/bbox/特征树断言快 |
| 装配与验真 | `solidworks-automation`（新 skill） | 组件解析、装配上下文实体、AddMate5 错误码、DOF、干涉三态更完整 |

禁止在同一阶段混用两个底座的 API。

- 建模阶段禁止调用 `sw_part` / `sw_hole_features` 建零件。
- 装配阶段禁止用旧 `place_to/fix_all` 把“配合记录”当成“配合求解”。

---

## 路径（自动发现，不写死）

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates"))
import hybrid_common as H
H.setup()                       # 校验底座存在 + 设 SW_ATTACH_EXISTING_DISPATCH

OLD_SCRIPTS = H.OLD_SCRIPTS     # 自动发现 solidworks-modeling/scripts
NEW_SCRIPTS = H.NEW_SCRIPTS     # 自动发现 solidworks-automation/scripts
EMPTY_ASM   = H.EMPTY_ASM       # 自动定位 AsmEmpty.ASMDOT
```

**路径发现顺序**（第一个命中即用）：

| 顺序 | 位置 |
|---|---|
| 1 | 环境变量 `DSH_SW_MODELING` / `DSH_SW_AUTOMATION` / `DSH_SW_ASM_TEMPLATE` |
| 2 | 本 skill 的 sibling 目录（`../solidworks-modeling` 等） |
| 3 | `~/.dsh/skills/<name>` |
| 4 | `~/.config/dsh/skills/`、`~/dsh/skills`、`/opt/dsh/skills` |

自检一行：

```powershell
python templates\hybrid_common.py
```

输出应列出三个底座路径 + `AsmEmpty.ASMDOT` 定位结果 + `setup: OK`。

连接 SolidWorks 前设置：

```powershell
$env:SW_ATTACH_EXISTING_DISPATCH = "1"
```

本机 ROT 未注册；这是 `solidworks-automation` 已有的安全开关。

---


## 0. 开始前：先跑能力矩阵（1 次顶 21 个探针）

**不要用一堆 `probe_*.py` 逐个试 API。** 一次会话跑完：

```powershell
$env:SW_ATTACH_EXISTING_DISPATCH = "1"
python templates\capability_matrix.py
```

输出 `%TEMP%\dsh_sw_matrix\capability_matrix.json`，21 项探测 + 2 项前置健康检查。

**本机 SW2022 基线（2026-11-23 实测，`pass_with_limitations`）：**

| 项 | 结果 |
|---|---|
| 21 项 | pass |
| 1 项 | fail（M04 revolve，有等价替代） |
| 0 项 | blocked |

判定语义：

| verdict | 含义 | 影响 overall |
|---|---|---|
| `pass` | 能力可用且行为符合解析预期 | — |
| `fail` | **能力本身不可用**（SW 版本限制），但已有等价替代 | 记入 `known_limitations` |
| `blocked` | 无法判定（环境/悬空引用/前置条件） | overall → `review`，必须人工看 |

> **唯一已知能力缺失**：`revolve_checked` + `CreateCenterLine` 在 SW2022 抛
> `-2147352571 类型不匹配`。等价替代：多段同轴 `extrude` 叠台阶回转体（已验证体积逐位吻合）。

### 写探测脚本的两条铁律（本轮踩出来的）

1. **破坏性探测必须用独立临时文档。**
   `revolve` 抛错后该文档 `volume=0` / bbox 全零；若复用母件文档，
   后续 `save` 会静默存出 **0 字节文件**，装配插入随后全崩。
2. **探活不能顺手 `CloseAllDocuments`。**
   它会把别的探测正在用的文档一起关掉，之后拿到悬空引用
   （`-2147417848 被调用的对象已与其客户端断开连接`）。
   基线探活放在**最前面**，之后不要再全局清文档。

---

## 0.0 先算复用，再动手（省 40% 时间）

**不要一上来就按零件清单逐个建。** 先分组，只建母件。

```python
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates"))
from hybrid_reuse import plan_families, family_report

fams = plan_families(theory["parts"])   # theory.json 生成后立刻调用，不碰 SW
rep  = family_report(fams)
print(rep["total_instances"], "实例 /", rep["unique_shapes"], "唯一形状 /",
      "可省", rep["reusable_copies"], "件 (%.1f%%)" % rep["saving_pct"])
```

实测（ballscrew_slide_v1）：

| 指标 | 逐件建 | 按母件复用 |
|---|---|---|
| 零件实例 | 35 | 35 |
| 实际建模 | 35 | **20** |
| 特征数 | 973 | 550（省 43%） |
| SLDPRT 字节 | 4.5 MB | 2.5 MB（省 44%） |

典型重复组：滑块 ×4、等高垫块 ×4、端盖 ×4、压板 ×4、导轨 ×2、限位块 ×2、开关 ×2。

**两种复用方式，按场景选：**

| 方式 | 做法 | 状态 |
|---|---|---|
| **同零件多实例**（首选） | 只存 1 个 SLDPRT，装配里插 N 次，靠 `set_component_transform` 平移 | ✅ **本机 6/6 实测通过** |
| 派生零件（SaveAs + 平移草图） | 得到独立文件 | ⚠ 未验证，不建议 |

```python
from hybrid_reuse import plan_instances, instance_report

rows = plan_instances(theory["parts"])   # [{part, master, offset_mm, is_master}]
rep  = instance_report(rows)
print("要建", rep["to_build"], "件，装配", rep["instances"], "个实例，省", rep["saved_parts"], "件")
```

**多实例实测证据**（`templates/verify_reuse.py` → `trace_reuse.json`）：

| 验证 | 结果 |
|---|---|
| R1 同一 SLDPRT 插 4 次，实例名互异 | pass（`master_block-1..4`） |
| R2 平移后 bbox 与「母件+偏移」比对 | pass，**max dev = 0.000000 mm** |
| R3 4 个分开实例的干涉 | pass，count=0（**复用不产生假干涉**） |
| R4 负向对照：故意重叠 20 mm | **warn, count=1, max_volume=3717.26 mm³**（判定照常生效） |
| R5 实例 bbox 尺寸等于母件 | pass（无变体） |
| R6 复用实例上建 MateConcentric | pass，写入特征树 |

> ⚠ **不要为了"零件 bbox 等于装配 bbox"的验收便利而放弃复用** ——
> 那正是本次浪费 43% 特征的根因。正确做法：零件建**局部坐标**，
> 每个实例单独记 `bbox_in_asm`，与「母件 bbox + 平移量」比对，同样严格。

> ⚠ **建模与装配必须复用同一个 SW 实例。** 两次 `connect()` 可能附着到不同实例，
> 症状是「建模正常、装配 `AddComponent5` 恒返回 None」。所以：
> 在**脚本顶部、任何 import 之前**设 `os.environ["SW_ATTACH_EXISTING_DISPATCH"]="1"`，
> 且全流程只 `connect()` 一次，把 `sw` 传给建模和装配两段。

---

## 0.1 装配必须可断点续建

**装配禁止写成原子块。** 一歪一件就整轮重来，代价是 N 次全量插入。

```python
from hybrid_reuse import AssemblySession

sess = AssemblySession(os.path.join(ROOT, "assembly_state.json"), asm_path=ASM)
sess.load(resume=True)                    # 有断点就续

for name in sess.pending_components(all_names):   # 只做没完成的
    c = insert_component(...)                      # 见模板 B1+B2
    sess.mark_component(name, instance=inst)

for key in sess.pending_mates(all_mate_keys):
    try:
        ...; sess.mark_mate(key, axis_dist_mm=d)
    except Exception as e:
        sess.bump_attempt(key); sess.mark_failure("mate", key, e)
```

`state.json` 每步原子落盘（`os.replace`），崩了重跑只补缺口。
配合项还有 `attempts` 上限，避免死循环重试同一条。

---

## 标准流程

### 0. 先写计划

新建独立交付目录，写：

```text
design.yaml       唯一参数真相源
PLAN.md           参数表、零件清单、理论体积公式、验收矩阵、坐标契约
theory.json       必须在调用 SolidWorks 前生成
```

理论体积不得从 SolidWorks 反推。

theory.json 生成后**立刻**跑 `plan_families()` 出复用计划，再开始建模。

### 0.2 建模前先做解析预检（不碰 SW）

`theory.json` 里已有全部 bbox，两两相交可以纯解析算出来，**在建模前**就能发现
明显的设计冲突，比装配完再跑干涉早得多、便宜得多。

```python
# 595 对里只报"重叠体积 > 小件 5%"的候选，人工确认是否真干涉
# 正常工程接触（轴承配合、滑块夹轨、电机止口）也会命中，需按配合意图判读
```

### 1. 建模阶段（旧 skill）

```python
import sys
sys.path.insert(0, OLD_SCRIPTS)
import swlib_v2 as V
```

允许使用：

```text
V.connect / V.new_part / V.addtoDB / V.L
# V.L 是 swlib 模块别名（swlib_v2.py line 44: import swlib as L）
# 因此 V.L.new_sketch / V.L.rect / V.L.line 是正确入口
V.L.new_sketch / V.circle / V.L.rect / V.L.line
V.extrude_checked / V.cut_checked / V.revolve_checked
V.fillet_checked / V.chamfer_checked
V.volume_check / V.verify / V.feature_tree / V.body_counts
V.set_material / V.get_material
V.set_custom_props / V.get_custom_props
V.add_configuration
V.save_checked(m, path, rebuild=True)
V.close_doc
```

建模验收门槛：

- 每件 `bodies=1, surface=0`
- 体积偏差 < 0.5%，优先 < 0.05%
- bbox 逐项偏差 < 0.5 mm
- 特征树有真实建模特征
- 材料/属性/配置回读
- 存盘文件 > 0 字节

### 2. 装配阶段（新 skill）

```python
import sys
sys.path.insert(0, NEW_SCRIPTS)
import sw_connect
import sw_assembly
import sw_measure
```

允许使用：

```text
sw_connect.connect_solidworks(version=2022)
sw_connect.open_document / new_document
sw_assembly.add_component
sw_assembly.resolve_component
sw_assembly.get_component_model
sw_assembly.get_assembly_entity
sw_assembly.find_largest_cylinder_face
sw_assembly.select_entities_for_mate
sw_assembly.add_mate5_checked
sw_assembly.add_concentric_mate_by_cylinders
sw_assembly.collect_mate_feature_summary
sw_assembly.inspect_component_dofs
sw_assembly.make_transform / set_component_transform
sw_measure.inspect_interference
```

装配规则：

1. 装配体模板用 `AsmEmpty.ASMDOT`，不用 `Assembly.asmdot`。
2. 静态装配：摆位后固定，配合作为工程语义记录。
3. 运动装配：只固定基准件，保留旋转自由度（`lock_rotation=False`）。
4. 配合必须回读 `collect_mate_feature_summary`。
5. 同心配合必须验几何轴心距，不能只看 `count_mates`。
6. 干涉用 `sw_measure.inspect_interference`；`blocked` 不能写 pass。

### 2.1 装配阶段 6 条硬约束（SW2022 实测，缺一条就返工）

| # | 约束 | 不遵守的后果 |
|---|---|---|
| B1 | 插入前 `OpenDoc6` + `ActivateDoc3(title,False,0,0)`；插入后立即 `CloseDoc(零件名)` | 第 33 件起 `AddComponent5` 稳定返回 None |
| B2 | 插入后 `set_component_transform(c, identity)` 归位 | 组件以自身 bbox 中心定位，位置全错 |
| B3 | `AddMate5` 的 `error_status` 传**裸 int 0** | 抛 `int() argument must be ... not 'VARIANT'` |
| B4 | `GetSurface`/`IsCylinder`/`CylinderParams`/`GetArea`/`PlaneParams` **不加括号** | `-2147352573 找不到成员` |
| B5 | `PlaneParams = [法向, 过点]`，且法向被规范化成正轴 → **只按过点坐标筛面** | 按法向负号筛面恒找不到 |
| B6 | 先全组件 `FixComponent` 再加配合（静态装配） | 平面配合拉走零件，产出假干涉 |
| B7 | 全流程只 `connect()` **一次**；`os.environ["SW_ATTACH_EXISTING_DISPATCH"]="1"` 必须在**任何 import 之前**设 | 两次 connect 可能附着到不同 SW 实例 → 建模正常但装配 `AddComponent5` 恒返回 None |

另：`AddMate5` 在 **`IAssemblyDoc`**，`ClearSelection2` 在 `IModelDoc2`。

完整实证见 `references/hybrid-contract.md §6.1`；可直接抄的代码见
`templates/assembly_template.py`（已按上述 6 条校准）。

### 2.2 静态装配 vs 运动装配的取舍（重要）

**开工前必须先判定验收目标**，判定结果决定装配策略，不能事后挑省事的那个。

```python
# 在 PLAN.md 里显式写下来，作为验收契约的一部分
acceptance_goal = "position"   # 只要零件位置对
# acceptance_goal = "mechanism"  # 要证明机构/配合真的解得开
```

| 验收目标 | 装配策略 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| **`position`**（静态布置、夹具、支架、箱体） | 摆位 → **全组件 Fix** → 加配合作为语义记录 | 零件位置正确、无干涉、BOM 齐全 | 配合能否求解 |
| **`mechanism`**（铰链、丝杠传动、连杆、可动滑台） | 只固定 **base** → 其余自由 → 加配合 **`lock_rotation=False`** → 验轴心距/DOF → 干涉 | 配合真实成立、机构可动 | — |

**强制规则：**

1. `acceptance_goal == "mechanism"` 时，**禁止**全组件固定。
   全固定后配合对几何零约束，等于把验证降级成记录。
2. 只有在 `acceptance_goal == "position"` 时才允许全固定，
   且 `REPORT.json` 必须写明 `acceptance_goal: "position"` 与
   `mates_role: "semantic_record_not_solved"`，避免下游误读成「配合已验证」。
3. 判定不许为了「让 gate 好过」而下调。若 `mechanism` 求解失败，
   结论就是失败（或 BLOCKED），不是改成 `position` 重跑。

> 本次 ballscrew_slide_v1 的真实目标是 `position`（静态滑台），全固定是合理的；
> 但当时报告里没写这个判定，容易被误读成「36 条配合都解过」。
> 这是**表述缺陷**，已在 LESSONS.md 记录。

### 3. 验收

必须记录：

```text
每个零件：volume / bbox / bodies / feature tree / material / props / config / save bytes
装配：components / mates / axis distances / interference status+count+max volume
```

输出：

```text
REPORT.json   机器可读
FINAL.md      人读总结
trace.json    执行留痕（推荐）
```

默认不出图。

---

## 已知 2022 坑（必读）

详见 `references/hybrid-contract.md`。重点：

- 齿轮生成 `sw_gear` 在 SW2022 卡死，禁用。
- 新 skill 的 `create_through_hole` 已修为按版本自适应，但建模仍优先旧 skill。
- `Assembly.asmdot` 自带组件，禁用；用 `AsmEmpty.ASMDOT`。
- 锁定组件的配合只记录不求解。
- `IFace2.GetBox` / `EditRebuild3` / `GetNames` 在本机是属性，不一定是方法。
- `sw` 是动态对象，`ActivateDoc3` 等长参数方法需 QI 成接口。

### 建模侧 6 条（同样实测，见 contract §6.1 A 组）

| # | 坑 | 正确做法 |
|---|---|---|
| A1 | 材料名写错**静默不生效**（`ok=true` 但读回空） | 先从 `.sldmat` 枚举实名；本机 UTF-16 编码 |
| A2 | 新建零件已有 `Default`，再加同名配置抛错 | 先 `GetConfigurationNames()` 再追加新名 |
| A3 | 平面映射反直觉 | Front→+Z 拉伸；Right 草图 `x = -z_world` |
| A4 | `cut_checked` 双向贯穿会把盲孔切成通孔 | 只有覆盖全长才贯穿，否则偏移面定向盲切 |
| A5 | 「实心 + 内孔切除」在内孔不接触材料时返回 None | 用双同心圆一次拉伸成环形 |
| A6 | `revolve_checked` + `CreateCenterLine` 在本机抛类型不匹配 | 用多段同轴 `extrude` 叠台阶回转体 |

本机已验证材料实名：`6061 合金` / `6061-T6 (SS)` / `合金钢` / `普通碳钢` / `AISI 1020` / `ABS` / `ABS PC`。

---

## 效率纪律（血泪教训）

| 反模式 | 代价 | 正确做法 |
|---|---|---|
| 逐件建同形状零件 | 白建 43% 特征 / 44% 文件 | `plan_instances()` 先分组，只建母件 |
| 装配写成原子块 | 一歪就 N 次全量重来 | `AssemblySession` 断点续建 |
| 一个细节写一个 probe 脚本 | 21 个探针，9 个各自重建装配环境 | `capability_matrix.py` 一次跑完 22 项 |
| 断言 pre/post 各跑一遍全量 | 70 次断言（含 35 次冗余特征树） | post 只验体积/字节 |
| 等装配完才查干涉 | 6 处假干涉最后才发现 | `precheck_interference.py` 建模前跑 |
| 材料名试错 | 13 个候选全静默失败 | 先读 `.sldmat` 拿实名 |
| ~~全串行单 COM，重复件可并行~~ | **已实测：不可行** | 见下方并行结论 |

### 多进程并行：**本机不可行**（已实测，别再试）

`templates/verify_parallel.py`，2026-11-23，SW2022 / 32 GB 内存：

| 验证 | 结果 |
|---|---|
| P1 同时起 2 个 SW 实例 | **0/2 完成** |
| P2 并行结果一致性 | pass（能建出来的那件数据正确） |
| P3 加速比 | **0.168**（比串行慢 6 倍：8.29 → 49.4 s/件） |
| P4 根因 | 实例间互相踢连接，`-2147417848 客户端断开` |

**实证细节**：两个 worker 各自 `Dispatch` 独立实例，结果
`w0.json` 两件全失败、`w1.json` 第 0 件失败第 1 件成功。
即：**SW2022 单机不能并行共存多个 COM 实例**，后起的会把先起的连接踢掉。

结论：**老实串行**。想省时间只能靠「减少要建的东西」（复用母件），
不能靠「同时建」。

---

## 建模前解析预检（省钱的一步）

```bash
python templates/precheck_interference.py <theory.json> [--strict]
```

纯解析、不碰 SolidWorks、0.1 秒出结果。用零件的理论 bbox 两两求交，
按「重叠体积 / 较小件」分档：

- 命中 `DEFAULT_CONTACTS` 白名单 → 归为**已知设计接触**（正常）
- 未分类且 ratio > 5% → **可疑候选**，需人工按配合意图判读

实测（ballscrew_slide_v1）：595 对里 13 对 bbox 相交，**全部命中白名单**，
verdict = pass。这 13 对恰好等于后来真实干涉检查里"不报错"的那 13 对 ——
说明解析预检的判读规则与 SW 实测一致。

> ⚠ 它**不能替代** `sw_measure.inspect_interference`。bbox 相交 ≠ 体积干涉，
> 最终判据仍是装配后的干涉检查。

---

## 默认边界

```yaml
scope:
  modeling: true
  assembly: true
  drawing: false
  review: false
```

只有用户明确说出图、工程图、PDF、截图时，才允许启用出图/截图能力。

装配验收通过即停止。
