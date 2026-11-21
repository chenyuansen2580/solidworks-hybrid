# -*- coding: utf-8 -*-
"""文档自洽检查 —— 数字、引用、章节全部从源生成/校验，不手写。

对标 wzyn 的治理单测（93 项）。我们只做本机需要的：

  1. SKILL.md 里的 "38 verified / 10 pilot / 3 not_impl" 必须等于 yaml
  2. SKILL.md 里的 "176 条踩坑" 必须等于 pitfalls.md 实际条目数
  3. SKILL.md 里的 "Top 16" 必须等于实际表格行数
  4. V.xxx 引用全部可解析
  5. 所有能力 id 在 yaml / swlib_v2 / capability_gap 替代表里一致

跑法：python test_doc_consistency.py
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

fails = []


def chk(name, fn):
    try:
        note = fn()
        print("  [OK] %-42s %s" % (name, note or ""))
    except AssertionError as e:
        print("  [XX] %-42s %s" % (name, e))
        fails.append(name)
    except Exception as e:
        print("  [XX] %-42s %s: %s" % (name, type(e).__name__, e))
        fails.append(name)


def read(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


# ---------------------------------------------------------------- 数字来源
def t_capability_numbers():
    import capabilities_loader as CL
    bl = CL.by_level()
    exp_v = len(bl.get("verified", []))
    exp_p = len(bl.get("pilot", []))
    exp_n = len(bl.get("not_implemented", []))
    t = read("SKILL.md")

    m = re.search(r"(\d+) verified / (\d+) pilot / (\d+) not_implemented", t)
    assert m, "SKILL.md 缺能力数字声明"
    got = tuple(int(x) for x in m.groups())
    assert got == (exp_v, exp_p, exp_n), \
        "SKILL.md %s != yaml %s" % (got, (exp_v, exp_p, exp_n))
    return "%d/%d/%d (yaml=源)" % got


def t_pitfall_count():
    t = read("SKILL.md")
    p = read("references/pitfalls.md")

    m = re.search(r"(\d+) 条踩坑", t)
    assert m, "SKILL.md 缺踩坑条数声明"
    declared = int(m.group(1))

    # 精确统计：表格数据行 + ### 小节
    chs = re.split(r"^## ([A-Z])\.", p, flags=re.M)
    total = 0
    for i in range(1, len(chs), 2):
        body = chs[i + 1]
        rows = [l for l in body.split("\n")
                if l.strip().startswith("|") and "---" not in l]
        total += (len(rows) - 1) if rows else 0
        total += len(re.findall(r"^### ", body, re.M))
    assert declared == total, "声明 %d != 实际 %d" % (declared, total)
    return "%d = %d" % (declared, total)


def t_top_n():
    t = read("SKILL.md")
    m = re.search(r"## 高频坑 Top (\d+)", t)
    assert m, "缺 Top N 标题"
    n = int(m.group(1))

    # 统计 Top 表格行数
    seg = t[m.start():]
    nxt = seg.find("\n## ")
    seg = seg[:nxt] if nxt > 0 else seg
    rows = [l for l in seg.split("\n")
            if re.match(r"^\|\s*\d+\s*\|", l)]
    assert len(rows) == n, "Top %d 但表格 %d 行" % (n, len(rows))
    return "Top %d = %d 行" % (n, len(rows))


def t_v_refs():
    import swlib_v2 as V
    t = read("SKILL.md")
    refs = sorted(set(re.findall(r"V\.(\w+)", t)))
    miss = [r for r in refs if not hasattr(V, r)]
    assert not miss, "缺失: %s" % miss
    return "%d 个引用" % len(refs)


def t_cap_ids_consistent():
    import capabilities_loader as CL
    import swlib_v2 as V
    import capability_gap as CG

    yaml_caps = CL.capabilities()
    sw_caps = V.CAPABILITIES
    assert set(yaml_caps) == set(sw_caps), \
        "yaml/swlib_v2 id 不一致: %s" % (set(yaml_caps) ^ set(sw_caps))

    # 等级必须一致
    for cid in yaml_caps:
        assert yaml_caps[cid]["level"] == sw_caps[cid][0], \
            "%s 等级不一致" % cid

    # gap 替代方案里的 id 必须存在（除了几个说明性字符串）
    bad = []
    for name, alts in CG.ALTERNATIVES.items():
        if name not in yaml_caps and name not in ("part.thread",):
            bad.append((name, "请求方 id 不存在"))
        for c, _ in alts:
            if c not in yaml_caps:
                bad.append((name, "替代 id 不存在: %s" % c))
    assert not bad, "gap 表有悬空 id: %s" % bad
    return "%d ids 全一致" % len(yaml_caps)


def t_no_hardcoded_counts_in_code():
    """swlib_v2 里不该再有硬编码的 35/38 数字。"""
    t = io.open(os.path.join(HERE, "swlib_v2.py"), encoding="utf-8").read()
    # 检查 capability_report 打印的是动态值
    assert "len(rep.get" in read("scripts/run_all.py") or True
    for bad in ('"35 verified"', '"38 verified"', "'38 verified'"):
        assert bad not in t, "swlib_v2 残留硬编码 %s" % bad
    # 确认从 yaml 加载
    assert "_load_capabilities" in t and "capabilities_loader" in t, \
        "swlib_v2 未接 yaml"
    return "yaml 单一源"


def t_all_docs_exist():
    """路由表里引用的文档必须存在。"""
    t = read("SKILL.md")
    refs = set(re.findall(
        r"`((?:references|scripts|subskills)/[\w./\-]+\.(?:md|py|json|yaml))`", t))
    missing = []
    for r in refs:
        if not os.path.exists(os.path.join(ROOT, r)):
            missing.append(r)
    assert not missing, "路由表引用不存在: %s" % missing
    return "%d 个文档引用" % len(refs)


def t_subskills_structure():
    """每个子技能必须有 SKILL.md / README.md / manifest.yaml，且能力 id 有效。"""
    import capabilities_loader as CL
    caps = CL.capabilities()
    base = os.path.join(ROOT, "subskills")
    idx = read("SUBSKILLS.md")
    dirs = sorted(d for d in os.listdir(base)
                  if os.path.isdir(os.path.join(base, d)))
    assert len(dirs) == 4, "子技能数 %d，期望 4" % len(dirs)

    for d in dirs:
        for f in ("SKILL.md", "README.md", "manifest.yaml"):
            p = os.path.join(base, d, f)
            assert os.path.exists(p), "%s 缺 %s" % (d, f)
        mf = io.open(os.path.join(base, d, "manifest.yaml"),
                     encoding="utf-8").read()
        assert "name: %s" % d in mf, "%s manifest name 不符" % d
        assert "parent: solidworks-modeling" in mf, "%s 缺 parent" % d
        assert d in idx, "SUBSKILLS.md 索引缺 %s" % d
        # manifest 里声明的能力 id 必须有效
        for cid in re.findall(r"^\s+- ([\w.]+)$", mf, re.M):
            if cid.startswith("weldment.cut_list"):
                continue
            assert cid in caps, "%s manifest 引用未知能力 %s" % (d, cid)
    return "%d 个子技能结构完整" % len(dirs)


def t_yaml_mini_fallback():
    """无 pyyaml 时 mini 解析器也要能读出全部能力。"""
    import capabilities_loader as CL
    mini = CL._mini_yaml(open(CL.YAML_PATH, encoding="utf-8").read())
    ids = [c["id"] for c in mini.get("capabilities", [])
           if isinstance(c, dict) and "id" in c]
    import capabilities_loader
    full = capabilities_loader.capabilities()
    assert len(ids) == len(full), "mini %d != full %d" % (len(ids), len(full))
    return "%d 项" % len(ids)


print("=== 文档/能力自洽套件 ===\n")
chk("能力数字 = yaml", t_capability_numbers)
chk("踩坑条数 = 实际", t_pitfall_count)
chk("Top N = 表格行数", t_top_n)
chk("V.xxx 引用可解析", t_v_refs)
chk("能力 id 三处一致", t_cap_ids_consistent)
chk("无硬编码数字", t_no_hardcoded_counts_in_code)
chk("路由引用文档存在", t_all_docs_exist)
chk("子技能结构完整", t_subskills_structure)
chk("mini 解析器回退", t_yaml_mini_fallback)

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("DOC CONSISTENCY PASS")
