"""pytest 公共夹具：构造一个小规模但结构完整的内存面板。

不写盘、不依赖已训练模型，确保 `pytest` 在干净环境也能通过。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.gen_demo_data import (  # noqa: E402
    _audit_and_market,
    _company_master,
    _financial_items,
    _governance,
    _label_table,
    _legal_events,
    _macro_table,
    _risk_path,
    _text_features,
)
from etl.feature_engineering import build_panel  # noqa: E402


@pytest.fixture(scope="session")
def raw_tables() -> dict:
    rng = np.random.default_rng(7)
    master = _company_master(24, rng)
    risk = _risk_path(master, rng)
    financial = _financial_items(risk, master, rng).merge(
        master[["stock_code", "company_name", "industry"]], on="stock_code", how="left"
    )
    return {
        "financial": financial,
        "governance": _governance(risk, rng),
        "sentiment": _text_features(risk, rng),
        "market": _audit_and_market(risk, rng),
        "legal": _legal_events(master, rng),
        "labels": _label_table(risk, rng),
        "macro": _macro_table(),
    }


@pytest.fixture(scope="session")
def panel(raw_tables: dict):
    return build_panel(**raw_tables)
