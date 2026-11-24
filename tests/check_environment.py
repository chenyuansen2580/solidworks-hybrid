# -*- coding: utf-8 -*-
"""check_environment.py — 确认「当前环境是否装了 CAD 依赖」。

用途有两个，语义相反，所以要看平台：

* **Linux CI**：必须没有 CAD 依赖。装了 -> 说明依赖声明有问题 -> FAIL。
* **Windows 本机**：本来就有 pywin32（建模/装配底座需要）。有依赖是正常的，
  但仍应提示「真机验证需另跑，与 CI 无关」。

因此退出码：
  Linux   且 无依赖            -> 0（期望状态）
  Linux   且 有依赖            -> 1（CI 配置错误）
  Windows 且 有 win32com       -> 0（本机正常）
  Windows 且 无 win32com       -> 0（不阻塞，仅提示无法做真机验证）

加 --strict 则强制「必须无依赖」，供 CI 显式断言。
"""
import importlib.util as u
import sys

CAD_MODULES = ("win32com", "pythoncom", "swlib_v2", "sw_assembly", "sw_measure")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    strict = "--strict" in argv
    is_windows = sys.platform.startswith("win")

    present = [m for m in CAD_MODULES if u.find_spec(m)]
    print("platform      : %s" % sys.platform)
    print("CAD modules   : %s" % (", ".join(present) if present else "none"))

    if strict:
        if present:
            print("FAIL: --strict 要求无 CAD 依赖，却发现 %s" % present)
            return 1
        print("OK: no CAD dependency (strict)")
        return 0

    if is_windows:
        if present:
            print("OK: Windows 本机已装 CAD 依赖，可做真机验证（与 CI 无关）")
        else:
            print("NOTE: Windows 本机未装 CAD 依赖，无法做真机验证")
        return 0

    # Linux / macOS：CI 场景
    if present:
        print("FAIL: 非 Windows 环境不应安装 CAD 依赖，却发现 %s" % present)
        return 1
    print("OK: no CAD dependency on non-Windows (CI expectation)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
