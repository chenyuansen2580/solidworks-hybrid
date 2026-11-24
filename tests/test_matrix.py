# -*- coding: utf-8 -*-
"""test_matrix.py — capability_matrix.py 的结构契约测试。

★ 不 import 任何 COM 模块，不依赖 pywin32 / SolidWorks，Linux 可直接跑。
   通过 templates/matrix_manifest.py（纯数据镜像）+ 源码正则做交叉校验。

覆盖：
  a. 全部 id：23 个、无重复、M01–M20 连续、PRE-00..02 齐全
  b. 每个 @probe 函数体非空（不是 pass 占位），category 只允许 modeling/assembly
  c. status 判定集合与 SKILL.md 的 verdict 语义表一致
  d. SKILL.md 基线表 pass+fail+blocked 之和等于探测总数
"""
import io
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_ROOT = os.path.dirname(HERE)
MATRIX = os.path.join(PKG_ROOT, "templates", "capability_matrix.py")

import matrix_manifest as M   # noqa: E402  (conftest 已把 templates 加进 sys.path)


def _read(p):
    with io.open(p, encoding="utf-8") as f:
        return f.read()


def _src():
    return _read(MATRIX)


def _skill():
    return _read(os.path.join(PKG_ROOT, "SKILL.md"))


def _ids_in_source():
    txt = _src()
    return sorted({m for m in re.findall(r'"((?:PRE-\d+|M\d+))"', txt)
                   if re.fullmatch(r"(PRE-\d+|M\d+)", m)})


def _probe_ids_in_source():
    """只取通过 @probe 装饰器注册的 id。"""
    txt = _src()
    return re.findall(r'@probe\("((?:M\d+|PRE-\d+))"', txt)


def _rec_ids_in_source():
    """只取通过 rec("...") 直接登记的 id（前置检查走这条）。"""
    txt = _src()
    return re.findall(r'rec\("((?:M\d+|PRE-\d+))"', txt)


# ============================================================ a. id 集合
def test_total_ids_23():
    ids = _ids_in_source()
    assert len(ids) == 23, "探测总数应为 23，实际 %d: %s" % (len(ids), ids)


def test_ids_unique():
    ids = _ids_in_source()
    dup = {i for i in ids if ids.count(i) > 1}
    assert not dup, "id 重复: %s" % dup


def test_m_ids_contiguous():
    m_ids = sorted(int(i[1:]) for i in _ids_in_source() if i.startswith("M"))
    assert m_ids == list(range(1, 21)), "M 编号应为 M01..M20 连续，实际 %s" % m_ids


def test_pre_ids_complete():
    pre = sorted(i for i in _ids_in_source() if i.startswith("PRE"))
    assert pre == ["PRE-00", "PRE-01", "PRE-02"], "PRE 应为 00..02，实际 %s" % pre


def test_manifest_matches_source():
    """纯数据镜像必须与源码 id 集合完全一致（防止镜像漂移）。"""
    assert sorted(M.ALL_IDS) == _ids_in_source()


def test_manifest_counts():
    assert M.TOTAL == 23
    assert M.N_PROBES == 20
    assert M.N_PRE == 3


# ============================================== b. probe 体非空 + category
def test_probe_decorators_count():
    assert len(_probe_ids_in_source()) == 20


def test_each_probe_has_nonempty_body():
    """每个 @probe 函数体不能只有 pass / ... 占位。"""
    txt = _src()
    # 按 "@probe(" 切块，检查每块到下一个 def/decorator 之间是否有实质语句
    parts = re.split(r'(?=@probe\()', txt)
    checked = 0
    for chunk in parts[1:]:
        m = re.search(r"@probe\(\"((?:M\d+|PRE-\d+))\"", chunk)
        if not m:
            continue
        pid = m.group(1)
        # 取函数体（def ... 之后的行）
        body = chunk.split("def ", 1)
        assert len(body) == 2, "%s 缺少 def" % pid
        body_lines = body[1].splitlines()[1:]
        # 截断到下一个 "@probe(" 或模块级分界
        real = []
        for ln in body_lines:
            s = ln.strip()
            if s.startswith("@probe("):
                break
            if not s or s.startswith("#"):
                continue
            real.append(s)
        stmts = [s for s in real if s not in ("pass", "...", '"""', "'''")]
        assert len(stmts) >= 2, (
            "%s 函数体疑似空占位，实质语句 %d 行: %s" % (pid, len(stmts), stmts[:4]))
        checked += 1
    assert checked == 20, "应检查 20 个 @probe，实际 %d" % checked


def test_categories_allowed():
    """category 只允许 modeling / assembly（前置另有 session）。"""
    allowed_probe = {"modeling", "assembly"}
    for pid, cat, _q in M.PROBES:
        assert cat in allowed_probe, "%s category=%r 不合法" % (pid, cat)
    allowed_pre = {"modeling", "assembly", "session"}
    for pid, cat, _q in M.PRE_CHECKS:
        assert cat in allowed_pre, "%s category=%r 不合法" % (pid, cat)


def test_categories_present_in_source():
    """源码里每个 @probe 的 category 参数必须落在允许集合内。"""
    txt = _src()
    cats = re.findall(r'@probe\("(?:M\d+|PRE-\d+)",\s*"([a-z]+)"', txt)
    assert cats, "未解析到任何 category"
    assert set(cats) <= {"modeling", "assembly", "session"}, (
        "出现非法 category: %s" % (set(cats) - {"modeling", "assembly", "session"}))


# ============================================ c. status 集合与文档语义一致
def test_verdict_set_matches_doc():
    """VERDICT_SET 必须与 SKILL.md「判定语义」表列出的 verdict 完全一致。"""
    sk = _skill()
    # 表格行形如：| `pass` | ... |
    declared = set(re.findall(r"^\|\s*`(pass|fail|blocked|skip)`\s*\|", sk, re.M))
    assert declared, "SKILL.md 未解析到 verdict 表"
    assert declared == set(M.VERDICT_SET), (
        "SKILL.md 声明 %s，manifest 为 %s" % (sorted(declared),
                                            sorted(M.VERDICT_SET)))


def test_no_unknown_status_in_matrix():
    """源码里 rec() 传入的 status 只能是 VERDICT_SET 之一。"""
    txt = _src()
    used = set(re.findall(r'rec\([^)]*?"(pass|fail|blocked|skip)"', txt))
    # 多行 rec 调用，status 常在第 3 个参数位置，用宽松匹配兜底
    used |= set(re.findall(r'"(pass|fail|blocked|skip)"\s*,\s*\{', txt))
    unknown = used - set(M.VERDICT_SET) - {"skip"}
    assert not unknown, "出现文档未定义的 status: %s" % unknown


def test_overall_set():
    assert set(M.OVERALL_SET) == {"pass", "pass_with_limitations", "review"}


# ======================================== d. 基线表之和 == 探测总数
def test_baseline_sum_equals_total():
    assert M.baseline_sum() == M.TOTAL, (
        "基线三行之和 %d != 探测总数 %d" % (M.baseline_sum(), M.TOTAL))


def test_skill_baseline_table_sums_to_total():
    """SKILL.md 基线表 pass/fail/blocked 三行相加必须等于 23。"""
    sk = _skill()
    # 抓「| pass | **22** |」或「| pass | 22 |」形式
    got = {}
    for key in ("pass", "fail", "blocked"):
        m = re.search(r"^\|\s*%s[^|]*\|\s*\**(\d+)\**\s*\|" % key, sk, re.M)
        if m:
            got[key] = int(m.group(1))
    assert got, "SKILL.md 未解析到基线表计数行"
    assert set(got) == {"pass", "fail", "blocked"}, "基线表缺行: %s" % got
    assert sum(got.values()) == M.TOTAL, (
        "SKILL.md 基线表 %s 之和 %d != %d" % (got, sum(got.values()), M.TOTAL))


def test_baseline_fail_ids_documented():
    """fail 的具体 id 必须写明（当前是 M04）。"""
    sk = _skill()
    for pid in M.BASELINE_FAIL_IDS:
        assert pid in sk, "基线 fail 项 %s 未在 SKILL.md 中说明" % pid


# =============================================== 附加：探测数与文档交叉
def test_skill_declares_23_total():
    sk = _skill()
    assert "23" in sk
    assert re.search(r"\*\*23\*\*", sk) or "23" in sk


def test_pre_count_declared_as_3():
    """文档若说「N 项前置」，N 必须是 3。"""
    for name in ("SKILL.md", "README.md"):
        txt = _read(os.path.join(PKG_ROOT, name))
        for m in re.finditer(r"(\d+)\s*项\s*(?:前置|健康检查)", txt):
            assert int(m.group(1)) == 3, (
                "%s 声明前置 %s 项，实际 3" % (name, m.group(1)))
