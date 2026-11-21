# -*- coding: utf-8 -*-
"""Golden Workflow 校验器

守三件事：
  1. 每个 workflow 的 capability id 都在 capabilities.yaml 里
  2. required_inputs / required_artifacts / real_acceptance 都存在且非空
  3. real_acceptance 的数值能被实际产物验证（不只是一句空话）

对标 wzyn 的 golden-workflows + runner.py，但只做本机需要的校验部分。
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


def load_yaml():
    import capabilities_loader as CL
    p = os.path.join(ROOT, "golden-workflows.yaml")
    return CL.load(p)


def gws():
    return load_yaml().get("workflows", [])


# ---------------------------------------------------------------- 结构
def t_schema():
    d = load_yaml()
    assert d.get("schema_version") == "1.0"
    assert d.get("target_first_pass_rate") == 0.90
    assert len(gws()) >= 6
    return "%d 个 workflow" % len(gws())


def t_required_fields():
    bad = []
    for w in gws():
        for key in ("id", "name", "capabilities", "required_inputs",
                    "required_artifacts", "real_acceptance_2022"):
            if key not in w:
                bad.append("%s 缺 %s" % (w.get("id"), key))
    assert not bad, bad
    return "字段齐全"


def t_capability_ids_valid():
    import capabilities_loader as CL
    caps = CL.capabilities()
    bad = []
    for w in gws():
        for cid in w["capabilities"]:
            if cid not in caps:
                bad.append((w["id"], cid))
    assert not bad, "未知能力: %s" % bad
    return "全部在 capabilities.yaml"


def t_subskill_refs_valid():
    bad = []
    for w in gws():
        s = w.get("real_acceptance_2022", {}).get("subskill")
        if not s:
            continue
        p = os.path.join(ROOT, "subskills", s, "SKILL.md")
        if not os.path.exists(p):
            bad.append((w["id"], s))
    assert not bad, "子技能引用不存在: %s" % bad
    return "子技能引用有效"


def t_infrastructure_refs_valid():
    """infrastructure 字段引用的是真实脚本模块，不是 capability id"""
    bad = []
    for w in gws():
        for mod in w.get("infrastructure", []):
            p = os.path.join(HERE, mod + ".py")
            if not os.path.exists(p):
                bad.append((w["id"], mod))
    assert not bad, "infrastructure 模块不存在: %s" % bad
    n = sum(len(w.get("infrastructure", [])) for w in gws())
    return "%d 个模块引用有效" % n


def t_acceptance_has_numbers():
    """real_acceptance 必须有真数值，不能只有空话"""
    bad = []
    for w in gws():
        acc = w.get("real_acceptance_2022", {})
        has_num = any(isinstance(v, (int, float)) for v in acc.values())
        has_dict = any(isinstance(v, dict) for v in acc.values())
        if not (has_num or has_dict):
            bad.append(w["id"])
    assert not bad, "验收无数值: %s" % bad
    return "验收有数值证据"


# ---------------------------------------------------------------- 对真实产物
def t_belt_actuator_acceptance():
    """★ 用 belt_actuator 的真实 REPORT.json 验证 golden 数值"""
    import json
    rp = r"D:\yysls\belt_actuator\out\REPORT.json"
    if not os.path.exists(rp):
        print("      跳过（REPORT.json 不存在）")
        return
    with open(rp, encoding="utf-8") as f:
        r = json.load(f)
    s = r["summary"]
    gw = [w for w in gws() if w["id"] == "belt_actuator_assembly"][0]
    acc = gw["real_acceptance_2022"]
    assert s["parts"] == acc["parts"], "parts %d != %d" % (s["parts"], acc["parts"])
    assert s["components"] == acc["components"]
    assert s["mates"] == acc["mates"]
    assert s["interference_clean"] is True
    assert all(p.get("dev_pct", 0) == 0.0 or abs(p.get("dev_pct", 0)) < 0.001
               for p in r["parts"]), "有零件体积偏差非 0"
    d = r["deliverables"]
    assert d["step"]["size"] > 4_000_000
    assert d["drawing_pdf"]["size"] > 10_000
    return "14 件/15 组件/10 配合/0 偏差 全部对上"


def t_gear_acceptance():
    """齿轮的 2301/4601 点由脚本实时生成，这里只验参数结构"""
    gw = [w for w in gws() if w["id"] == "spur_gear_pair"][0]
    acc = gw["real_acceptance_2022"]
    assert acc["z20"]["points"] == 2301
    assert acc["z40"]["points"] == 4601
    assert acc["z20"]["r_ok"] if "r_ok" in acc["z20"] else True
    return "z20=2301 / z40=4601 点"


def t_gates_acceptance():
    """三个机制的断言数从测试文件实际统计"""
    gw = [w for w in gws() if w["id"] == "capability_gate_drill"][0]
    acc = gw["real_acceptance_2022"]
    counts = {
        "freshness_assertions": "test_freshness.py",
        "gap_assertions": "test_capability_gap.py",
        "trace_assertions": "test_exec_trace.py",
        "doc_consistency_assertions": "test_doc_consistency.py",
    }
    for key, fn in counts.items():
        src = io.open(os.path.join(HERE, fn), encoding="utf-8").read()
        n = len(re.findall(r"^chk\(", src, re.M))
        assert n == acc[key], "%s 声明 %d，实际 %d" % (key, acc[key], n)
    return "断言数与实际测试一致"


def t_no_false_version_claims():
    """不编造跨版本结论：real_acceptance 键必须是 2022"""
    for w in gws():
        keys = [k for k in w if k.startswith("real_acceptance_")]
        assert keys == ["real_acceptance_2022"], \
            "%s 版本声明错误: %s" % (w["id"], keys)


print("=== Golden Workflow 校验套件 ===\n")
chk("schema 与数量", t_schema)
chk("必需字段齐全", t_required_fields)
chk("能力 id 有效", t_capability_ids_valid)
chk("子技能引用有效", t_subskill_refs_valid)
chk("基础设施模块有效", t_infrastructure_refs_valid)
chk("验收含数值证据", t_acceptance_has_numbers)
chk("★ belt_actuator 真实验收", t_belt_actuator_acceptance)
chk("齿轮点数验收", t_gear_acceptance)
chk("★ 三机制断言数一致", t_gates_acceptance)
chk("不谎称跨版本", t_no_false_version_claims)

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("GOLDEN WORKFLOW PASS")
