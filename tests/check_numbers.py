# -*- coding: utf-8 -*-
"""check_numbers.py — CI 用：打印并校验数字守卫（不依赖 pytest）。

与 tests/test_numbers.py 同口径，但可在无 pytest 环境单独跑。
退出码 0 = 通过；1 = 不一致。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def main():
    cm = read("templates", "capability_matrix.py")
    ids = {m for m in re.findall(r'"((?:PRE-\d+|M\d+))"', cm)
           if re.fullmatch(r"(PRE-\d+|M\d+)", m)}

    ct = read("references", "hybrid-contract.md")
    a = re.findall(r"^#### (A\d)\.", ct, re.M)
    b = re.findall(r"^#### (B\d)\.", ct, re.M)

    print("probe ids    : %d  %s" % (len(ids), sorted(ids)))
    print("constraints  : %d  (A%d + B%d)" % (len(a) + len(b), len(a), len(b)))

    fails = []
    if a != ["A%d" % i for i in range(1, 7)]:
        fails.append("A 组应为 A1..A6，实际 %s" % a)
    if b != ["B%d" % i for i in range(1, 8)]:
        fails.append("B 组应为 B1..B7，实际 %s" % b)
    if len(a) + len(b) != 13:
        fails.append("约束应为 13 条，实际 %d" % (len(a) + len(b)))

    # 文档声明与实际的比对
    for name in ("README.md", "SKILL.md"):
        txt = read(name)
        declared = set()
        for pat in (r"(\d+)\s*项探测", r"(\d+)\s*项能力"):
            declared |= {int(m.group(1)) for m in re.finditer(pat, txt)}
        if declared and declared != {len(ids)}:
            fails.append("%s 声明探测 %s 项，实际 %d"
                         % (name, sorted(declared), len(ids)))
        if re.search(r"(\d+)\s*行", txt):
            fails.append("%s 含写死的行数声明" % name)

    # 硬编码路径
    for root, dirs, files in os.walk(ROOT):
        if ".git" in root or os.sep + "tests" in root:
            continue
        for f in files:
            if not f.endswith((".py", ".md")):
                continue
            p = os.path.join(root, f)
            t = io.open(p, encoding="utf-8", errors="replace").read()
            for pat in ("D:\\yysls", "C:\\Users\\pc"):
                if pat in t:
                    fails.append("%s 含硬编码路径 %s"
                                 % (os.path.relpath(p, ROOT), pat))

    print()
    if fails:
        for x in fails:
            print("FAIL:", x)
        return 1
    print("OK: number guard passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
