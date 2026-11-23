# -*- coding: utf-8 -*-
"""hybrid_common.py —— solidworks-hybrid 共用工具。

职责：
  * **自动发现**两个底座 skill 的路径（不写死用户目录）
  * 统一路径与环境变量
  * 建模阶段切到旧 skill 的 scripts
  * 装配阶段切到新 skill 的 scripts
  * 提供 UTF-8 输出、YAML/JSON、断言记录

路径发现顺序（逐个尝试，第一个命中即用）：
  1. 环境变量覆盖：DSH_SW_MODELING / DSH_SW_AUTOMATION / DSH_SW_HYBRID
  2. 本文件所在包的上一级（把本 skill 装成 sibling 目录时）
  3. DSH skills 根目录：%USERPROFILE%\\.dsh\\skills\\<name>
  4. 常见位置：~/.config/dsh/skills, ~/dsh/skills, /opt/dsh/skills

注意：**不要同时把两个 scripts 目录永久追加到 sys.path**。
提供 with 上下文，按阶段临时切换，避免同名模块互相覆盖。
"""
from __future__ import annotations

import io
import json
import os
import sys

MM = 0.001

# 两个底座 skill 的目录名（可被环境变量覆盖）
MODELING_DIRNAME = "solidworks-modeling"
AUTOMATION_DIRNAME = "solidworks-automation"
HYBRID_DIRNAME = "solidworks-hybrid"

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE_ROOT = os.path.dirname(HERE)          # .../solidworks-hybrid


def _candidates(dirname):
    """列出某个 skill 目录的所有候选位置。"""
    env_key = {
        MODELING_DIRNAME: "DSH_SW_MODELING",
        AUTOMATION_DIRNAME: "DSH_SW_AUTOMATION",
        HYBRID_DIRNAME: "DSH_SW_HYBRID",
    }.get(dirname)
    out = []
    if env_key:
        v = os.environ.get(env_key)
        if v:
            out.append(v)
    # sibling：本 skill 的上一级目录里找同名目录
    out.append(os.path.join(os.path.dirname(PACKAGE_ROOT), dirname))
    # 自身（hybrid 自己）
    if dirname == HYBRID_DIRNAME:
        out.append(PACKAGE_ROOT)
    # DSH 默认 skills 根
    home = os.path.expanduser("~")
    for root in (os.path.join(home, ".dsh", "skills"),
                 os.path.join(home, ".config", "dsh", "skills"),
                 os.path.join(home, "dsh", "skills"),
                 "/opt/dsh/skills"):
        out.append(os.path.join(root, dirname))
    # 去重保序
    seen, uniq = set(), []
    for p in out:
        ap = os.path.abspath(os.path.expandvars(p))
        if ap not in seen:
            seen.add(ap)
            uniq.append(ap)
    return uniq


def _resolve(dirname, script):
    """在候选中找含指定脚本文件的 skill 目录；找不到返回 None。"""
    for base in _candidates(dirname):
        if os.path.isfile(os.path.join(base, "scripts", script)):
            return base
    return None


def discover(verbose=False):
    """发现三个 skill 的根目录。返回 dict；缺失项为 None + 原因。"""
    found = {
        MODELING_DIRNAME: _resolve(MODELING_DIRNAME, "swlib_v2.py"),
        AUTOMATION_DIRNAME: _resolve(AUTOMATION_DIRNAME, "sw_assembly.py"),
        HYBRID_DIRNAME: PACKAGE_ROOT,
    }
    if verbose:
        for k, v in found.items():
            print("  [discover] %-24s %s" % (k, v or "NOT FOUND"))
    return found


_found = discover()
OLD_SKILL = _found[MODELING_DIRNAME]
NEW_SKILL = _found[AUTOMATION_DIRNAME]
OLD_SCRIPTS = os.path.join(OLD_SKILL, "scripts") if OLD_SKILL else None
NEW_SCRIPTS = os.path.join(NEW_SKILL, "scripts") if NEW_SKILL else None


def find_asmdot():
    """定位 AsmEmpty.ASMDOT（装配模板）。

    不能用 Assembly.asmdot（自带 4 个模板组件，可能弹框挂住 COM）。

    查找顺序：
      1. 环境变量 DSH_SW_ASM_TEMPLATE
      2. 注册表/常见安装根下的 templates 目录
      3. 退化为 None，由调用方给出明确报错
    """
    direct = os.environ.get("DSH_SW_ASM_TEMPLATE")
    if direct and os.path.isfile(direct):
        return direct

    roots = []
    for envk in ("PROGRAMDATA",):
        v = os.environ.get(envk)
        if v:
            roots.append(v)
    roots += [r"C:\ProgramData", r"C:\Users\Public\Documents"]

    years = ["2026", "2025", "2024", "2023", "2022", "2021", "2020"]
    for root in roots:
        swroot = os.path.join(root, "SOLIDWORKS")
        for y in years:
            tmpl = os.path.join(swroot, "SOLIDWORKS " + y, "templates")
            for name in ("AsmEmpty.ASMDOT", "AsmEmpty.asmdot"):
                p = os.path.join(tmpl, name)
                if os.path.isfile(p):
                    return p
    return None


EMPTY_ASM = find_asmdot()


def setup(verbose=False):
    """基础环境：UTF-8 输出 + 允许附着已有 SW 实例 + 校验底座存在。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    os.environ.setdefault("SW_ATTACH_EXISTING_DISPATCH", "1")

    missing = []
    if not OLD_SCRIPTS:
        missing.append("%s (swlib_v2.py) — 设 DSH_SW_MODELING 环境变量"
                       % MODELING_DIRNAME)
    if not NEW_SCRIPTS:
        missing.append("%s (sw_assembly.py) — 设 DSH_SW_AUTOMATION 环境变量"
                       % AUTOMATION_DIRNAME)
    if missing:
        raise RuntimeError(
            "缺少底座 skill，无法继续：\n  - " + "\n  - ".join(missing) +
            "\n请先安装 solidworks-modeling / solidworks-automation，"
            "或用对应环境变量指向其目录。")
    if not EMPTY_ASM and verbose:
        print("  [warn] 未找到 AsmEmpty.ASMDOT；装配阶段请显式传 template_path，"
              "或设 DSH_SW_ASM_TEMPLATE")
    return True


class use_scripts:
    """临时把某个底座的 scripts 放到 sys.path[0]。

    用法：
        with use_scripts("model"):
            import swlib_v2 as V

        with use_scripts("assembly"):
            import sw_connect, sw_assembly, sw_measure
    """

    def __init__(self, phase):
        phase = str(phase).lower()
        if phase in ("model", "modeling", "old", "build"):
            self.path = OLD_SCRIPTS
        elif phase in ("assembly", "asm", "verify", "new"):
            self.path = NEW_SCRIPTS
        else:
            raise ValueError("未知阶段 %r" % phase)
        if not self.path:
            raise RuntimeError("阶段 %r 对应的底座 skill 未找到" % phase)
        self.removed = []

    def __enter__(self):
        for p in (OLD_SCRIPTS, NEW_SCRIPTS):
            if not p:
                continue
            while p in sys.path:
                sys.path.remove(p)
                self.removed.append(p)
        sys.path.insert(0, self.path)

        names = [n for n in list(sys.modules)
                 if n in ("sw_connect", "sw_assembly", "sw_measure",
                          "sw_part", "sw_hole_features", "swlib", "swlib_v2")]
        for n in names:
            del sys.modules[n]
        return self.path

    def __exit__(self, *exc):
        while self.path in sys.path:
            sys.path.remove(self.path)
        return False


def load_yaml(path):
    import yaml
    with io.open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_json(path, obj):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return path


def load_json(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


class Checks:
    """轻量断言记录：同时打印并收集。"""

    def __init__(self, title=""):
        self.title = title
        self.rows = []

    def check(self, cid, ok, detail=""):
        ok = bool(ok)
        self.rows.append({"id": cid, "ok": ok, "detail": str(detail)[:300]})
        print("  [%s] %-42s %s" % ("OK" if ok else "XX", cid, str(detail)[:160]))
        return ok

    @property
    def failed(self):
        return [r for r in self.rows if not r["ok"]]

    def verdict(self):
        return "PASS" if not self.failed else "FAIL"

    def save(self, path):
        return save_json(path, {"title": self.title, "verdict": self.verdict(),
                                "checks": self.rows})


if __name__ == "__main__":
    print("== solidworks-hybrid 路径自检 ==")
    found = discover(verbose=True)
    print("  AsmEmpty.ASMDOT:", EMPTY_ASM or "NOT FOUND")
    try:
        setup(verbose=True)
        print("  setup: OK")
    except Exception as e:
        print("  setup: FAIL ->", e)
        sys.exit(1)
