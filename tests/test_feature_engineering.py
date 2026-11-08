"""特征工程测试：口径正确性 + 数据质量约束。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config.feature_registry import FEATURE_KEYS, TARGET_COLUMN


def test_panel_contains_all_features(panel):
    missing = [k for k in FEATURE_KEYS if k not in panel.columns]
    assert not missing, f"特征缺失：{missing}"


def test_panel_has_no_infinite_values(panel):
    numeric = panel[FEATURE_KEYS]
    assert not np.isinf(numeric.to_numpy()).any(), "特征中存在 inf，需检查安全除法"


def test_panel_has_no_missing_features(panel):
    assert panel[FEATURE_KEYS].isna().sum().sum() == 0


def test_primary_key_is_unique(panel):
    assert not panel.duplicated(["stock_code", "year"]).any()


def test_label_is_binary(panel):
    assert set(panel[TARGET_COLUMN].unique()) <= {0, 1}


def test_year_window_respects_label_horizon(panel):
    from config.settings import PANEL_YEARS

    assert panel["year"].between(min(PANEL_YEARS), max(PANEL_YEARS)).all()


def test_ratio_features_are_plausible(panel):
    # 资产负债率在 (0,1.5] 区间；流动比率为正
    assert panel["debt_to_asset"].between(0, 1.5).mean() > 0.95
    assert (panel["current_ratio"] > 0).mean() > 0.95


def test_roe_change_uses_same_company(panel):
    one = panel[panel["stock_code"] == panel["stock_code"].iloc[0]].sort_values("year")
    if len(one) >= 2:
        expected = one["roe"].diff().iloc[1]
        assert one["roe_change"].iloc[1] == expected or pd.isna(expected)


def test_growth_features_are_percentages(panel):
    growth = panel["revenue_growth"].dropna()
    assert growth.abs().median() < 3, "成长率量级异常，可能未做单位统一"


def test_fcf_negative_years_is_non_negative_integer(panel):
    values = panel["fcf_negative_years"].dropna()
    assert (values >= 0).all()
    assert np.allclose(values, values.round())
