# -*- coding: utf-8 -*-
"""check_numbers.py — 数字守卫（不依赖 pytest，可在纯 Linux 跑）。

★ 全库唯一口径：探测总数 23 = 能力探针 20 + 前置健康检查 3。

检查项：
  1. 契约约束 13 条（A1–A6 + B1–B7），编号连续
  2. 探测 id：源码 23 个、无重复、M01–M20 连续、PRE-00..02 齐全；
     且与 templates/matrix_manifest.py 镜像一致
  3. 文档里的「N 项探测 / N 项能力 / N 个探针」主数字必须等于 23
     「N 项前置 / N 项健康检查」必须等于 3
  4. SKILL.md 基线表 pass/fail/blocked 三行之和必须等于 23，
     且 fail 的具体 id 必须写明
  5. 禁止写死行数声明（"NNN 行"）
  6. 禁止硬编码机器路径

退出码：0 = 全通过；1 = 有不一致。
"""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- 采集
def collect():
    cm = read("templates", "capability_matrix.py")
    ct = read("references", "hybrid-contract.md")
    sk = read("SKILL.md")
    rd = read("README.md")

    ids = sorted({m for m in re.findall(r'"((?:PRE-\d+|M\d+))"', cm)
                  if re.fullmatch(r"(PRE-\d+|M\d+)", m)})
    m_ids = sorted(int(i[1:]) for i in ids if i.startswith("M"))
    pre_ids = sorted(i for i in ids if i.startswith("PRE"))

    a = re.findall(r"^#### (A\d)\.", ct, re.M)
    b = re.findall(r"^#### (B\d)\.", ct, re.M)

    # 镜像
    try:
        import importlib
        sys.path.insert(0, os.path.join(ROOT, "templates"))
        M = importlib.import_module("matrix_manifest")
        manifest_ids = sorted(M.ALL_IDS)
        manifest_total = M.TOTAL
        manifest_baseline = dict(M.BASELINE)
        manifest_fail_ids = list(M.BASELINE_FAIL_IDS)
    except Exception as e:
        manifest_ids = None
        manifest_total = None
        manifest_baseline = None
        manifest_fail_ids = None
        print("  [warn] 未能加载 matrix_manifest: %s" % str(e)[:100])

    return dict(cm=cm, ct=ct, sk=sk, rd=rd, ids=ids, m_ids=m_ids,
                pre_ids=pre_ids, a=a, b=b,
                manifest_ids=manifest_ids, manifest_total=manifest_total,
                manifest_baseline=manifest_baseline,
                manifest_fail_ids=manifest_fail_ids)


# ---------------------------------------------------------------- 主逻辑
def main():
    d = collect()
    fails = []

    print("=" * 72)
    print("数字守卫")
    print("=" * 72)

    # ---- 1. 约束
    print("\n[1] 契约约束")
    print("    A 组: %d %s" % (len(d["a"]), d["a"]))
    print("    B 组: %d %s" % (len(d["b"]), d["b"]))
    if d["a"] != ["A%d" % i for i in range(1, 7)]:
        fails.append("A 组应为 A1..A6，实际 %s" % d["a"])
    if d["b"] != ["B%d" % i for i in range(1, 8)]:
        fails.append("B 组应为 B1..B7，实际 %s" % d["b"])
    if len(d["a"]) + len(d["b"]) != 13:
        fails.append("约束应为 13 条，实际 %d" % (len(d["a"]) + len(d["b"])))

    # ---- 2. 探测 id
    print("\n[2] 探测 id")
    print("    源码全部 id: %d" % len(d["ids"]))
    print("    M 系列     : %d %s" % (len(d["m_ids"]),
                                     ("M%02d..M%02d" % (d["m_ids"][0], d["m_ids"][-1]))
                                     if d["m_ids"] else "-"))
    print("    PRE 系列   : %d %s" % (len(d["pre_ids"]), d["pre_ids"]))
    if len(d["ids"]) != 23:
        fails.append("探测总数应为 23，实际 %d: %s" % (len(d["ids"]), d["ids"]))
    if d["m_ids"] != list(range(1, 21)):
        fails.append("M 编号应为 M01..M20 连续，实际 %s" % d["m_ids"])
    if d["pre_ids"] != ["PRE-00", "PRE-01", "PRE-02"]:
        fails.append("PRE 应为 00..02，实际 %s" % d["pre_ids"])
    if d["manifest_ids"] is not None:
        print("    镜像 id    : %d" % len(d["manifest_ids"]))
        if d["manifest_ids"] != d["ids"]:
            only_src = set(d["ids"]) - set(d["manifest_ids"])
            only_mir = set(d["manifest_ids"]) - set(d["ids"])
            fails.append("镜像与源码 id 不一致: 仅源码 %s / 仅镜像 %s"
                         % (sorted(only_src), sorted(only_mir)))
        if d["manifest_total"] != 23:
            fails.append("manifest.TOTAL 应为 23，实际 %s" % d["manifest_total"])

    # ---- 3. 文档主数字
    print("\n[3] 文档声明的主数字")
    # 3a. 行内写法：「N 项探测 / N 项能力 / N 个探针」
    pats_main = [r"(\d+)\s*(?:项|个)\s*(?:探测|能力|探针)"]
    # 3b. 表格写法：「| **探测总数** | **23** |」「| 能力探针 | 20 |」
    pats_table = [
        (r"\|\s*\**探测总数\**\s*\|\s*\**(\d+)\**\s*\|", 23, "探测总数"),
        (r"\|\s*\**能力探针\**\s*\|\s*\**(\d+)\**\s*\|", 20, "能力探针"),
        (r"\|\s*\**前置健康检查\**\s*\|\s*\**(\d+)\**\s*\|", 3, "前置健康检查"),
    ]
    pats_pre = [r"(\d+)\s*项\s*(?:前置|健康检查)"]

    for name, txt in (("SKILL.md", d["sk"]), ("README.md", d["rd"])):
        for pat in pats_main:
            for m in re.finditer(pat, txt):
                n = int(m.group(1))
                ln = txt[:m.start()].count("\n") + 1
                flag = "OK" if n == 23 else "MISMATCH"
                print("    %-12s L%-4d %-28r -> %d %s"
                      % (name, ln, m.group(0), n, flag))
                if n != 23:
                    fails.append("%s:%d 声明 %r，主数字应为 23（实际 %d）"
                                 % (name, ln, m.group(0), n))
        for pat, want, label in pats_table:
            for m in re.finditer(pat, txt):
                n = int(m.group(1))
                ln = txt[:m.start()].count("\n") + 1
                flag = "OK" if n == want else "MISMATCH"
                print("    %-12s L%-4d %-28r -> %d (应 %d) %s"
                      % (name, ln, label, n, want, flag))
                if n != want:
                    fails.append("%s:%d 表格「%s」= %d，应为 %d"
                                 % (name, ln, label, n, want))
        for pat in pats_pre:
            for m in re.finditer(pat, txt):
                n = int(m.group(1))
                ln = txt[:m.start()].count("\n") + 1
                flag = "OK" if n == 3 else "MISMATCH"
                print("    %-12s L%-4d %-28r -> %d %s"
                      % (name, ln, m.group(0), n, flag))
                if n != 3:
                    fails.append("%s:%d 声明前置 %d 项，应为 3"
                                 % (name, ln, n))

    # ---- 4. 基线表
    print("\n[4] SKILL.md 基线表")
    got = {}
    for key in ("pass", "fail", "blocked"):
        m = re.search(r"^\|\s*%s[^|]*\|\s*\**(\d+)\**\s*\|" % key, d["sk"], re.M)
        if m:
            got[key] = int(m.group(1))
    print("    %s" % got)
    if set(got) != {"pass", "fail", "blocked"}:
        fails.append("基线表缺行，实际解析到 %s" % got)
    else:
        total = sum(got.values())
        print("    三行之和: %d  (应为 23)  %s"
              % (total, "OK" if total == 23 else "MISMATCH"))
        if total != 23:
            fails.append("基线表 %s 之和 %d != 23" % (got, total))
        if d["manifest_baseline"] is not None and got != d["manifest_baseline"]:
            fails.append("基线表 %s 与 manifest %s 不一致"
                         % (got, d["manifest_baseline"]))
    for pid in (d["manifest_fail_ids"] or ["M04"]):
        if pid not in d["sk"]:
            fails.append("基线 fail 项 %s 未在 SKILL.md 写明" % pid)
    print("    fail 项已写明: %s" % (d["manifest_fail_ids"] or ["M04"]))

    # ---- 5. 禁止写死行数
    print("\n[5] 禁止写死行数")
    lc = []
    for name, txt in (("SKILL.md", d["sk"]), ("README.md", d["rd"])):
        for m in re.finditer(r"(\d+)\s*行", txt):
            ln = txt[:m.start()].count("\n") + 1
            lc.append("%s:%d %r" % (name, ln, m.group(0)))
    if lc:
        print("    发现: %s" % lc)
        fails.append("文档含写死的行数声明: %s" % lc)
    else:
        print("    clean")

    # ---- 6. 硬编码路径
    print("\n[6] 禁止硬编码机器路径")
    bad = []
    for root, dirs, files in os.walk(ROOT):
        if ".git" in root or os.sep + "tests" in root:
            continue
        for f in files:
            if not f.endswith((".py", ".md", ".toml", ".yml")):
                continue
            p = os.path.join(root, f)
            txt = io.open(p, encoding="utf-8", errors="replace").read()
            for pat in ("D:" + "\\yysls", "C:" + "\\Users\\pc"):
                if pat in txt:
                    bad.append("%s <- %s" % (os.path.relpath(p, ROOT), pat))
    if bad:
        print("    发现: %s" % bad)
        fails.append("硬编码机器路径: %s" % bad)
    else:
        print("    clean")

    # ---- 汇总
    print("\n" + "=" * 72)
    if fails:
        for x in fails:
            print("FAIL:", x)
        print("=" * 72)
        print("RESULT: FAIL (%d 条)" % len(fails))
        return 1
    print("RESULT: OK  (探测 23 = 能力 20 + 前置 3；约束 13；基线 22+1+0=23)")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
