# Changelog

本文件记录 solidworks-hybrid 的版本变更。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

（暂无）

## [0.1.0] - 2026-11-24

首个可用版本。核心内容来自一次真实任务实测：滚珠丝杠驱动双导轨直线滑台
（35 零件 / 36 配合），所有硬约束都有对应 trace 证据，不是推测。

### Added

- **建模阶段硬约束 A1–A6**（`references/hybrid-contract.md`）
  - A1 材料名无效会**静默不生效**，必须先枚举 `.sldmat`（UTF-16）拿实名
  - A2 不能给已存在的 `Default` 再加同名配置
  - A3 草图平面 → 世界坐标映射表（Front→+Z / Right 草图 `x = -z_world`）
  - A4 只有覆盖全长才双向贯穿，否则必须偏移面定向盲切（否则盲孔变通孔）
  - A5 阶梯盲孔用双同心圆一次拉伸成环（实心+内孔切除会返回 None）
  - A6 `revolve_checked` 在 SW2022 抛 `-2147352571`，改用多段同轴 extrude

- **装配阶段硬约束 B1–B7**
  - B1 插入前 `OpenDoc6`+`ActivateDoc3`，插入后立即 `CloseDoc`
  - B2 插入后必须 `set_component_transform(identity)` 归位
  - B3 `AddMate5` 的 `error_status` 必须传裸 `int`
  - B4 `GetSurface`/`IsCylinder`/`CylinderParams`/`GetArea` 在本机是**属性**
  - B5 `PlaneParams` 是 `[法向, 过点]` 且法向被规范化 → 只按过点坐标筛面
  - B6 先全组件固定再加配合（否则平面配合拉走零件、产生假干涉）
  - B7 全流程只 `connect()` 一次，环境变量须在任何 import 之前设

- **复用分析** `templates/hybrid_reuse.py`
  - `plan_families` / `plan_instances`：按与位置无关的形状签名分组
  - 实测收益：35 件里识别出 15 件纯平移副本（43% 特征、44% 文件字节）
  - `AssemblySession`：装配断点续建，原子落盘，重试上限

- **解析干涉预检** `templates/precheck_interference.py`
  - 纯 Python、0.1 秒、不碰 SolidWorks，建模前即可发现设计级冲突
  - 实测：595 对里 13 对 bbox 相交，全部命中已知接触白名单

- **能力矩阵** `templates/capability_matrix.py`
  - 23 项探测 = 能力探针 20（M01–M20）+ 前置健康检查 3（PRE-00..02）
  - 一次会话跑完，替代散落的 21 个临时 probe 脚本

- **示例** `examples/theory.json`：4 零件（3 个纯平移副本）→ 只需建 2 件

- **测试** `tests/`：52 个用例，全部不依赖 SolidWorks / pywin32，Linux 可跑
  - `test_shapes.py` 签名平移不变性 / 尺度敏感 / 镜像不误判 / 分组 / 平移差
  - `test_resume.py` 落盘 / 断点续建往返 / 重试上限 / 原子写
  - `test_precheck.py` 正负对照 / 阈值边界 / 白名单 / 贴合不误判
  - `test_numbers.py` + `test_matrix.py` 数字守卫与矩阵契约

- **CI** `.github/workflows/ci.yml`
  - ubuntu-latest × Python 3.10/3.11/3.12
  - 显式断言环境无 CAD 依赖；跑 pytest、自检、数字守卫
  - 独立 portability job：不装任何依赖，验证核心模块只用 stdlib

- **打包** `pyproject.toml`
  - `requires-python >= 3.10`；`pywin32` 挂 `sys_platform == 'win32'`
  - `[tool.setuptools]` 显式 `packages = []` / `py-modules = []`，
    避免 flat-layout 自动发现把 `templates/`、`references/` 当成顶层包

### Known limitations

- `revolve_checked` + `CreateCenterLine` 在 SW2022 不可用（M04 fail），
  已有等价替代（多段同轴 extrude）
- **多进程并行不可行**：SW2022 单机不能共存多个 COM 实例，
  2 worker 实测加速比 0.168（比串行慢 6 倍）。见 `verify_parallel.py`
- `derive_by_saveas` 未实现且不建议使用，请用同零件多实例
- 静态装配全固定后，配合对几何**无约束作用**，仅作工程语义记录
- 建模阶段 100% 依赖未公开的 `solidworks-modeling` 底座；
  装配依赖第三方 `wzyn20051216/solidworks-automation-skill`

### Notes

- 真机结论（体积偏差 0.000004%、干涉 0、轴心距 0.000000 mm）
  **仅对本机 SolidWorks 2022 SP5 / 30.5.0 有效**
- CI 绿灯只代表纯逻辑与文档一致，**不代表远端 CAD 验证通过**

[Unreleased]: https://github.com/chenyuansen2580/solidworks-hybrid/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/chenyuansen2580/solidworks-hybrid/releases/tag/v0.1.0
