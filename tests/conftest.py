# -*- coding: utf-8 -*-
"""conftest.py — pytest 公共配置。

全部测试**不依赖 SolidWorks / pywin32**，可在 Linux 无 CAD 环境运行。
任何需要真机 SW 的验证都在 tests/README.md 里单独标注为「仅本机」。
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_ROOT = os.path.dirname(HERE)
TEMPLATES = os.path.join(PKG_ROOT, "templates")
EXAMPLES = os.path.join(PKG_ROOT, "examples")

if TEMPLATES not in sys.path:
    sys.path.insert(0, TEMPLATES)


@pytest.fixture(scope="session")
def pkg_root():
    return PKG_ROOT


@pytest.fixture(scope="session")
def example_theory():
    """仓库内 4 零件示例（3 个互为纯平移副本 + 1 根轴）。"""
    p = os.path.join(EXAMPLES, "theory.json")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def example_parts(example_theory):
    return example_theory["parts"]
