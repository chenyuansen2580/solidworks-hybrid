# -*- coding: utf-8 -*-
"""matrix_manifest.py — capability_matrix 的纯数据清单（零 COM 依赖）。

用途：让测试能在没有 pywin32 / 没有 SolidWorks 的 Linux 上验证矩阵契约。

★★ 唯一真相源仍是 `templates/capability_matrix.py`。
   本文件是它的**镜像**，供纯逻辑测试使用。
   tests/test_matrix.py 会交叉校验两者一致（id 集合、category、status 集合），
   一旦 capability_matrix.py 增删探针而本文件没同步，测试立刻变红。

数据结构：
  PROBES        = [(id, category, question), ...]   能力探针 M01–M20
  PRE_CHECKS    = [(id, category, question), ...]   前置健康检查 PRE-00..02
  VERDICT_SET   = 允许出现的 status 集合
  BASELINE      = 本机 SW2022 SP5 基线三行计数
"""

# --------------------------------------------------------------- 能力探针
# (id, category, question)  category 只允许 modeling / assembly
PROBES = [
    ("M01", "modeling", "Front/Top/Right 草图->世界映射是否如文档"),
    ("M02", "modeling", "定向盲切：方向语义与体积是否都符合解析值"),
    ("M03", "modeling", "双同心圆一次拉伸能否得到环（管）"),
    ("M04", "modeling", "revolve_checked + CreateCenterLine 在 SW2022 是否可用"),
    ("M05", "modeling", "无效材料名是否静默不生效；实名能否回读"),
    ("M06", "modeling", "能否重复添加已存在的 Default 配置"),
    ("M07", "assembly", "插入后 set_component_transform 归位 bbox 是否等于母件"),
    ("M08", "assembly", "同一 SLDPRT 多实例 + 平移是否得到独立实例"),
    ("M09", "assembly", "IFace2/ISurface 成员是属性还是方法"),
    ("M10", "assembly", "PlaneParams 布局与法向是否被规范化"),
    ("M11", "assembly", "CylinderParams 布局与轴线可读性"),
    ("M12", "assembly", "AddMate5 error_status 的正确传法"),
    ("M13", "assembly", "FixComponent 是否生效且 bbox 不变"),
    ("M14", "assembly", "配合特征树能否回读到 MateGroup 下真实 Mate"),
    ("M15", "assembly", "inspect_interference 三态是否可用"),
    ("M16", "assembly", "干涉能否检出真实重叠（负向对照）"),
    ("M17", "assembly", "inspect_component_dofs 返回的是不是自由度数"),
    ("M18", "assembly", "打开文档数累积是否让 AddComponent5 失败"),
    ("M19", "assembly", "save_checked(rebuild=True) 是否可存装配体"),
    ("M20", "assembly", "重新打开存盘装配体，组件数与干涉是否一致"),
]

# ------------------------------------------------------- 前置健康检查
PRE_CHECKS = [
    ("PRE-00", "session", "会话基线探活（建模前）"),
    ("PRE-01", "modeling", "母件存盘后文档健康（体积/bbox 非零）"),
    ("PRE-02", "assembly", "装配模板 AsmEmpty.ASMDOT 是否可定位"),
]

# ------------------------------------------------------------- 判定语义
# 与 SKILL.md「判定语义」表严格一致，不许出现表里没写的状态。
VERDICT_SET = ("pass", "fail", "blocked")

# 各 status 的语义（供测试与文档交叉校验）
VERDICT_MEANING = {
    "pass": "能力可用且行为符合解析预期",
    "fail": "能力本身不可用（SW 版本限制），但已有等价替代",
    "blocked": "无法判定（环境/悬空引用/前置条件）",
}

# overall 的取值（_finish() 会用到）
OVERALL_SET = ("pass", "pass_with_limitations", "review")

# ------------------------------------------------------- 本机基线（2026-11-23）
# SW2022 SP5 / 30.5.0 实测；三行相加必须等于 ALL_IDS 的数量。
BASELINE = {
    "pass": 22,
    "fail": 1,      # M04 revolve
    "blocked": 0,
}
BASELINE_FAIL_IDS = ["M04"]

# 派生
ALL_IDS = [p[0] for p in PROBES] + [p[0] for p in PRE_CHECKS]
TOTAL = len(ALL_IDS)
N_PROBES = len(PROBES)
N_PRE = len(PRE_CHECKS)


def summary():
    """一行摘要，便于测试/CI 打印。"""
    return ("探测总数 %d = 能力探针 %d + 前置健康检查 %d"
            % (TOTAL, N_PROBES, N_PRE))


def baseline_sum():
    return sum(BASELINE.values())


if __name__ == "__main__":
    print(summary())
    print("ALL_IDS =", ALL_IDS)
    print("BASELINE =", BASELINE, "-> sum =", baseline_sum())
    print("VERDICT_SET =", VERDICT_SET)
    assert baseline_sum() == TOTAL, (
        "基线三行之和 %d != 探测总数 %d" % (baseline_sum(), TOTAL))
    print("OK: manifest 自洽")
