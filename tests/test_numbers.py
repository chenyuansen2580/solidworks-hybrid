# -*- coding: utf-8 -*-
"""test_numbers.py — 数字守卫：文档声明的数字必须与实际一致。

Guard 目的：防止 README / SKILL.md 里写死的数字（探测项数、约束条数、
文件行数）随代码演进后变成假声明。

规则：
  * 探测项数 = capability_matrix.py 里注册的 rec() id 数
  * 硬约束条数 = hybrid-contract.md 里 `#### A<n>.` + `#### B<n>.` 的条目数
  * 行数类声明（"NNN 行"）一律禁止出现在文档里 —— 行数会漂，不该写死
"""
import io
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_ROOT = os.path.dirname(HERE)


def _read(*parts):
    p = os.path.join(PKG_ROOT, *parts)
    with io.open(p, encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------- 实际值
def _actual_probe_ids():
    txt = _read("templates", "capability_matrix.py")
    ids = {m for m in re.findall(r'"((?:PRE-\d+|M\d+))"', txt)
           if re.fullmatch(r"(PRE-\d+|M\d+)", m)}
    return ids


def _actual_constraints():
    txt = _read("references", "hybrid-contract.md")
    a = re.findall(r"^#### (A\d)\.", txt, re.M)
    b = re.findall(r"^#### (B\d)\.", txt, re.M)
    return a, b


# --------------------------------------------------------------- 守卫
def test_contract_has_13_constraints():
    """契约必须有 A1-A6 + B1-B7 = 13 条，编号连续无断档。"""
    a, b = _actual_constraints()
    assert a == ["A%d" % i for i in range(1, 7)], "A 组应为 A1..A6，实际 %s" % a
    assert b == ["B%d" % i for i in range(1, 8)], "B 组应为 B1..B7，实际 %s" % b
    assert len(a) + len(b) == 13


def test_readme_constraint_count_matches():
    """README 若声明「N 条硬约束」，N 必须等于实际条数。"""
    rd = _read("README.md")
    a, b = _actual_constraints()
    actual = len(a) + len(b)

    declared = {int(m.group(1)) for m in re.finditer(r"(\d+)\s*条硬约束", rd)}
    assert declared, "README 应声明硬约束条数"
    assert declared == {actual}, (
        "README 声明 %s 条，实际 %d 条" % (sorted(declared), actual))


def test_readme_probe_count_matches():
    """README 若声明「N 项探测/能力」，N 必须等于实际注册 id 数。"""
    rd = _read("README.md")
    actual = len(_actual_probe_ids())

    declared = set()
    for pat in (r"(\d+)\s*项探测", r"(\d+)\s*项能力"):
        declared |= {int(m.group(1)) for m in re.finditer(pat, rd)}
    assert declared, "README 应声明探测项数"
    assert declared == {actual}, (
        "README 声明 %s 项，实际 %d 项" % (sorted(declared), actual))


def test_skill_md_probe_count_matches():
    """SKILL.md 若声明探测项数，同样必须一致。"""
    sk = _read("SKILL.md")
    actual = len(_actual_probe_ids())
    declared = set()
    for pat in (r"(\d+)\s*项探测", r"(\d+)\s*项能力"):
        declared |= {int(m.group(1)) for m in re.finditer(pat, sk)}
    if declared:
        assert declared == {actual}, (
            "SKILL.md 声明 %s 项，实际 %d 项" % (sorted(declared), actual))


def test_no_hardcoded_line_counts():
    """文档里禁止写死「NNN 行」——行数会漂，属于不可维护的假声明。"""
    offenders = []
    for name in ("README.md", "SKILL.md"):
        txt = _read(name)
        for m in re.finditer(r"(\d+)\s*行", txt):
            offenders.append((name, m.group(0)))
    assert not offenders, "发现写死的行数声明: %s" % offenders


def test_no_machine_specific_paths():
    """发布版禁止出现个人机器路径。"""
    bad = []
    for root, dirs, files in os.walk(PKG_ROOT):
        if ".git" in root or "tests" in root:
            continue
        for f in files:
            if not f.endswith((".py", ".md")):
                continue
            p = os.path.join(root, f)
            with io.open(p, encoding="utf-8", errors="replace") as fh:
                txt = fh.read()
            for pat in (r"D:\\yysls", r"C:\\Users\\pc", r"/Users/[a-z]+/"):
                if re.search(pat, txt):
                    bad.append((os.path.relpath(p, PKG_ROOT), pat))
    assert not bad, "发现硬编码机器路径: %s" % bad


def test_probe_ids_unique():
    """探测 id 不得重复，否则统计会虚高。"""
    txt = _read("templates", "capability_matrix.py")
    ids = re.findall(r'rec\("((?:PRE-\d+|M\d+))"', txt)
    dup = {i for i in ids if ids.count(i) > 1}
    assert not dup, "探测 id 重复登记: %s" % dup
