# REVIEW — 外部意见处理记录

本文件记录历次外部 review 提出的意见、核实结果与处置。
**不是所有意见都被采纳** —— 有些经核实是错的，这里说明理由，避免重复讨论。

处置状态：`采纳` / `部分采纳` / `驳回（有据）` / `待定`

---

## 第 3 轮 — 2026-11-24（豆包，6 条）

### R3-1 可编辑安装失败 `采纳`

**意见**：干净 venv 里 `pip install -e ".[test]"` 报
`Multiple top-level packages discovered in a flat-layout: ['templates', 'references']`。

**核实**：属实，本机干净 venv 当场复现：
```
error: Multiple top-level packages discovered in a flat-layout: ['templates', 'references']
ERROR: Failed to build 'file:///<repo-root>'
```
这是 setuptools 的 flat-layout 自动发现行为，与平台无关。

**处置**：`pyproject.toml` 的 `[tool.setuptools]` 加 `packages = []` 与
`py-modules = []`。同步在 `ci.yml` 注释与 `tests/README.md` 写明「删掉 CI 就挂」。

**验证**：新干净 venv → `pip install -e ".[test]"` exit=0 → `pytest` 全绿。
CI 实测：`9fb7add` 三个 job 全卡在 Install（failure）；
`b10c06f` 起四个 job 全绿（success）。

---

### R3-2 pyproject URL 是 404 `驳回（有据）`

**意见**：`Homepage` / `Issues` 指向 `github.com/chenyuansen2580/solidworks-hybrid`，
但实际仓库是 `solidworks-modeling`，`/solidworks-hybrid` 不存在。

**核实**：**不成立**。仓库已在 GitHub 上改名为 `solidworks-hybrid`：
```
HEAD https://github.com/chenyuansen2580/solidworks-hybrid         -> 200
HEAD https://github.com/chenyuansen2580/solidworks-hybrid/issues  -> 200
API  full_name = chenyuansen2580/solidworks-hybrid
     chenyuansen2580/solidworks-modeling -> 重定向到 solidworks-hybrid
```

**处置**：不改 URL（本来就是对的）。仅在 `pyproject.toml` 加注释说明旧名会被重定向。

---

### R3-3 数字口径不一致、守卫漏检 `采纳（并额外发现 1 个 bug）`

**意见**：四处说法矛盾（SKILL.md:98 / :102 / :417，README.md:202），守卫没抓到。

**核实**：属实。实测构成 = 20 个 `@probe`（M01–M20）+ 3 个 `rec()` 前置
（PRE-00/01/02）= **23 个 id**。

**处置**：统一口径为「探测总数 23 = 能力探针 20 + 前置健康检查 3」。

| 位置 | 原 | 现 |
|---|---|---|
| SKILL.md:98 | 「23 项探测 + 2 项前置」（和=25） | 口径说明表，明列 23/20/3 |
| SKILL.md:104 | pass 21 / fail 1 / blocked 0（和=22） | pass **22** / fail 1 / blocked 0（和=23） |
| SKILL.md:417 | 「21 个探针…跑完 22 项」 | 「跑完全部 23 项（20 能力 + 3 前置）」 |
| README.md:202 | 「23 项能力探测」 | 「23 项探测（20 能力 + 3 前置）」 |

**额外发现（意见里没提）**：`PRE-02` 原本是**条件注册**（只在模板缺失时登记），
正常运行时只记 22 项 —— 静态源码数得对、运行时数不对。已改为无条件登记。

**守卫强化**：`check_numbers.py` 新增表格写法解析
（`| **探测总数** | **23** |`）、基线表三行求和、与 `matrix_manifest` 交叉校验。

**反向自测**（证明守卫真的会红）：
```
[A PASS] 原样                    want=0 got=0
[B PASS] SKILL 探测总数 23->22   want=1 got=1
[C PASS] 还原                    want=0 got=0
[D PASS] 基线 pass 22->21        want=1 got=1   (三行之和 22 != 23)
[E PASS] 还原                    want=0 got=0
[F PASS] README 23->22           want=1 got=1
```
第一轮自测曾暴露守卫漏洞：把表格里的 23 改成 22 时守卫**没红**，
因为原正则只匹配「N 项探测」行内写法、漏了表格写法。补上后 6/6 通过。

---

### R3-4 capability_matrix 零测试覆盖 `采纳`

**意见**：820 行、零测试，需补 4 条不依赖 SolidWorks 的契约测试。

**核实**：属实，`tests/` 下确实没有 `test_matrix.py`。

**处置**：
- 新增 `templates/matrix_manifest.py` 作为纯数据镜像（零 COM 依赖）
- 新增 `tests/test_matrix.py` 18 条：
  - a. id 23 个、无重复、M01–M20 连续、PRE-00..02 齐全、与镜像一致
  - b. 每个 `@probe` 函数体非空（逐块检查实质语句 ≥2 行）、category 合法
  - c. status 集合与 SKILL.md verdict 表**严格相等**
  - d. 基线表三行之和 == 探测总数，且 fail 项 id 必须写明

**验证**：pytest 从 34 涨到 **52**（要求 ≥38），Linux CI 全绿。

---

### R3-5 两处注释残留 `采纳`

**核实**：属实。
- `verify_reuse.py:17` docstring 写死了某台机器上的绝对输出路径（`<盘符>:\<项目目录>\trace_reuse.json`）
- `derive_by_saveas` docstring 首行没有「禁止调用」警示

**处置**：
- 前者改为 `<WORKDIR>/trace_reuse.json` + 解析顺序说明
- 后者首行加 `⚠ 此路径未验证，禁止调用，请改用同零件多实例。`

---

### R3-6 README 首屏定位不清 `采纳`

**核实**：属实。首屏看起来像开箱即用，但建模 100% 依赖未公开底座。

**处置**：标题下新增「⚠ 先看这里：这个仓库能直接跑什么」，明确：
- 可直接运行：`hybrid_reuse.py`、`precheck_interference.py`（纯 Python）
- 建模需自备 `solidworks-modeling`；装配需 clone `wzyn20051216/solidworks-automation-skill`
- 附缺底座时的 `RuntimeError` 样例，并注明「这是预期行为，不是 bug」

---

## 第 2 轮 — 2026-11-23（豆包，5 条）

| # | 意见 | 核实 | 处置 |
|---|---|---|---|
| R2-1 | `hybrid_reuse.py:309` 读死某个固定盘符路径；`verify_reuse.py:27-28` 同样 | 属实，行号精确 | 采纳：改为 `argv → DSH_SW_THEORY → DSH_SW_WORKDIR → examples/ → 内置示例` |
| R2-2 | README 的 `plan_instances(theory["parts"])` 传 list 会 AttributeError | **部分不成立**：`theory["parts"]` 是 dict，传 dict 恰好正确；真正问题是 README 从未定义 `theory` 变量，照抄会 `NameError` | 部分采纳：README 改为完整可跑代码 + 注明必须是 dict |
| R2-3 | 22 项探测 vs 实际 20；13 条约束 vs 正文 12；SKILL 456 行 vs 476 | 方向属实（精确值 23/12/477） | 采纳：见 R3-3 |
| R2-4 | 缺 tests/ | 属实 | 采纳：建 34 条 → 后续扩到 52 |
| R2-5 | 缺 CI 和 pyproject.toml | 属实 | 采纳：见下 |

R2 落地后新增：
- `.github/workflows/ci.yml`（ubuntu × py3.10–3.12）
- `pyproject.toml`（pywin32 挂 `sys_platform == 'win32'`）
- `tests/`（34 条起步）
- `examples/theory.json`（4 零件 / 3 副本）
- 契约补上 **B7**（全流程只 `connect()` 一次），从 12 条变 13 条

---

## 第 1 轮 — 2026-11-23（用户直接反馈，2 条）

| # | 意见 | 处置 |
|---|---|---|
| R1-1 | 相同模型重复建，浪费时间 | 采纳：`plan_instances` 按形状签名分组。实测 35 件 → 20 唯一形状，省 15 件 / 423 特征 / 1.97 MB |
| R1-2 | 装配一点错就全部重装 | 采纳：`AssemblySession` 原子落盘断点续建。实测返工从 5 次全量降到 0 |

R1 还带出 9 条 SW2022 硬约束（A1–A6、B1–B3）与 3 条后续（B4–B7）。

---

## 统计

| 轮次 | 条数 | 采纳 | 部分采纳 | 驳回（有据） |
|---|---|---|---|---|
| R1 | 2 | 2 | 0 | 0 |
| R2 | 5 | 4 | 1 | 0 |
| R3 | 6 | 5 | 0 | 1 |
| **合计** | **13** | **11** | **1** | **1** |

## 结论

外部意见命中率很高（13 条里 12 条有实质价值），但**不能照单全收**：
R3-2 关于 pyproject URL 的判断是错的（仓库早已改名），
R2-2 关于「传 list」的方向对、细节反。

处置原则：
1. 先复现再动手，不凭描述改代码
2. 判断错误的意见要留下证据与理由，避免下一轮重复讨论
3. 自己发现的问题（如 PRE-02 条件注册）也要一并修，不等外部提
