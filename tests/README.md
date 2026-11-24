# tests/

纯 Python 测试，**不依赖 SolidWorks、不依赖 pywin32**，可在 Linux 无 CAD 环境运行。

```bash
pip install -e ".[test]"
python -m pytest -q
```

> **安装前提**：`pyproject.toml` 里必须有
> `[tool.setuptools]` 下的 `packages = []` 与 `py-modules = []`。
> 缺了这两行，setuptools 会把 `templates/` 和 `references/` 当成两个顶层包，
> `pip install -e` 直接失败：
> `error: Multiple top-level packages discovered in a flat-layout`。
> 删之前先想清楚 —— CI 的 Install 步骤就靠它过。

## 覆盖范围

| 文件 | 内容 |
|---|---|
| `test_shapes.py` | `shape_signature` 平移不变性 / 尺度敏感 / 镜像不误判；`plan_families` 分组正确性；`plan_instances` 4 零件→2 母件；`translation_between` 正负例 |
| `test_resume.py` | `AssemblySession` 落盘、断点续建往返、重试上限、原子写、失败记录 |
| `test_precheck.py` | `precheck_interference` 正负对照：真重叠检出、贴合共面不误报、阈值边界、白名单、输出文件 |
| `test_numbers.py` | 数字守卫：契约 13 条、README/SKILL 声明的探测项数、禁止写死行数、禁止硬编码机器路径、探测 id 唯一 |

## 辅助脚本（CI 调用，也可单独跑）

```bash
python tests/check_environment.py           # 当前环境是否装了 CAD 依赖
python tests/check_environment.py --strict  # CI 用：必须无依赖
python tests/check_numbers.py               # 数字守卫（不依赖 pytest）
```

`check_environment.py` 的语义按平台区分：
- **Linux CI** + `--strict`：必须无 CAD 依赖，否则 FAIL
- **Windows 本机**：有 pywin32 是正常的（建模底座需要），返回 0

## 明确边界

**本目录的测试通过 ≠ CAD 功能在真机验证通过。**

这里只验证不依赖 CAD 的纯逻辑：形状签名、分组、断点续建、解析预检、
文档数字一致性。真正需要 SolidWorks 的部分（体积/bbox 断言、配合、
干涉）只能在装了 SolidWorks 2022 的 Windows 机器上跑，结论记录在各
`trace_*.json` 里，且**仅对本机 SW2022 SP5 (30.5.0) 有效**。

CI 绿灯请读作「纯逻辑与文档一致」，不要读作「远端 CAD 验证通过」。
