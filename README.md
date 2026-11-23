# solidworks-hybrid

> **仓库名说明 / Repo name note**
> 本仓库原名 `solidworks-modeling`，现已演进为 **solidworks-hybrid**。
> 内容以 `solidworks-hybrid` skill 为准；旧的 `solidworks-modeling` 内容完整保存在
> 分支 [`backup-modeling-skill-20261123`](../../tree/backup-modeling-skill-20261123)。
>
> This repository was originally named `solidworks-modeling` and has evolved into
> **solidworks-hybrid**. The previous `solidworks-modeling` skill is preserved intact
> in the [`backup-modeling-skill-20261123`](../../tree/backup-modeling-skill-20261123) branch.

> SolidWorks 2022 建模 + 装配验真的**融合技能**。建模走 `swlib_v2` 快而准，
> 装配验真走 `sw_assembly` + `sw_measure` 真而稳。
>
> A hybrid skill for SolidWorks 2022: fast parametric modelling via `swlib_v2`,
> verifiable assembly checks via `sw_assembly` + `sw_measure`.

## 为什么需要它

单独用任何一个底座都会吃亏：

| 底座 | 强项 | 短板 |
|---|---|---|
| `solidworks-modeling` | 建模封装稳，体积/bbox/特征树断言快 | 装配验真层弱，旧干涉判据容易假成功 |
| `solidworks-automation` | 组件解析、配合错误码、DOF、干涉三态 | 本机 SW2022 建模踩坑多、慢 |

**分工**：零件建模只用前者，装配验真只用后者，禁止同一阶段混用。

## 它实际解决过什么

本仓库的 13 条硬约束与 3 个流程机制，全部来自一次真实任务
（滚珠丝杠驱动双导轨直线滑台，35 零件 / 36 配合）的实测，不是推测：

| 类别 | 数量 | 例子 |
|---|---|---|
| 建模侧硬约束 | 6 条（A1–A6） | 材料名无效**静默不生效**；`cut` 双向贯穿会把盲孔切成通孔 |
| 装配侧硬约束 | 7 条（B1–B7） | `AddMate5` 的 `error_status` 必须传裸 `int`；`PlaneParams` 是 `[法向, 过点]` 且法向被规范化 |
| 流程机制 | 3 个 | 母件复用、装配断点续建、建模前解析预检 |

实测收益：把 35 件里 **15 件纯平移副本（43% 特征）** 识别出来只建母件；
装配返工从 **5 次全量** 降到 0。

## 安装

```bash
git clone https://github.com/<you>/solidworks-hybrid.git \
  ~/.dsh/skills/solidworks-hybrid
```

同时需要两个底座 skill 在同级目录（或通过环境变量指向）：

```
~/.dsh/skills/
  solidworks-hybrid/      ← 本仓库
  solidworks-modeling/    ← 底座（建模）
  solidworks-automation/  ← 底座（装配）
```

自检：

```powershell
python templates\hybrid_common.py
```

应输出三个底座路径 + `AsmEmpty.ASMDOT` 定位结果 + `setup: OK`。

## 环境要求

- Windows 10/11 x64
- SolidWorks **2022**（SP5 / 30.5.0 实测；其他版本未验证，API 行为可能不同）
- Python 3.10+，含 `pywin32`、`pyyaml`
- `SW_ATTACH_EXISTING_DISPATCH=1`（本机 ROT 未注册时附着已有实例）

## 快速开始

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "templates"))
import hybrid_common as H
H.setup()

# 1) 建模前：先算复用（纯 Python，不碰 SolidWorks）
from hybrid_reuse import plan_instances, instance_report
rows = plan_instances(theory["parts"])
print(instance_report(rows))        # 要建几件 / 装配几个实例 / 省几件

# 2) 建模前：解析预检（0.1 秒，不碰 SolidWorks）
#    python templates/precheck_interference.py theory.json

# 3) 建模（旧底座）
with H.use_scripts("model"):
    import swlib_v2 as V

# 4) 装配（新底座），带断点续建
from hybrid_reuse import AssemblySession
sess = AssemblySession("assembly_state.json")
sess.load(resume=True)
```

## 目录

```
SKILL.md                      技能主文档（456 行）
references/hybrid-contract.md 完整契约 + 13 条硬约束实证
templates/
  hybrid_common.py            路径自动发现 + 环境校验
  hybrid_reuse.py             复用分组 + 装配断点续建
  capability_matrix.py        22 项能力探测，一次会话跑完
  precheck_interference.py    建模前解析预检
  assembly_template.py        装配模板（按 B1–B7 校准）
  model_part_template.py      建模模板
  verify_reuse.py             多实例复用验证（6/6 实测）
  verify_parallel.py          多进程并行验证（结论：不可行）
```

## 已实测的边界

| 结论 | 证据 |
|---|---|
| 多进程并行**不可行** | SW2022 单机不能共存多个 COM 实例，2 worker 加速比 0.168（慢 6 倍） |
| 多实例复用**可行** | 同一 SLDPRT 插 4 次，bbox dev **0.000000 mm**，负向对照能检出重叠 |
| `revolve_checked` **不可用** | `CreateCenterLine` + revolve 抛 `-2147352571`；用多段同轴 extrude 替代 |
| 静态装配全固定 = 配合仅记录 | 固定件不参与求解，配合对几何零约束 |

## 默认不出图

本技能默认 **不生成** PNG / PDF / SLDDRW / BMP / JPG / TIF，不做四视图、
不做工程图标注。只有在用户明确要求出图时才启用。

## 许可

MIT。两个底座 skill 亦为 MIT。
本技能**不包含**任何底座 skill 的代码，运行时按路径依赖它们。

非 Dassault Systèmes 官方项目，与 SolidWorks 厂商无关。
