"""风控统计函数测试：IV / PSI / VIF / KS。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from etl.stats_utils import (
    calculate_iv,
    calculate_psi,
    calculate_vif,
    drop_high_corr,
    ks_statistic,
    psi_table,
    quantile_bins,
)


@pytest.fixture()
def sample():
    rng = np.random.default_rng(0)
    n = 800
    good = pd.Series(rng.normal(0.6, 0.15, n))
    bad = pd.Series(rng.normal(0.35, 0.15, n))
    feature = pd.concat([good, bad], ignore_index=True)
    target = pd.Series([0] * n + [1] * n)
    return feature, target


def test_psi_identical_distribution_is_near_zero(sample):
    feature, _ = sample
    assert calculate_psi(feature, feature) < 0.01


def test_psi_detects_shift(sample):
    feature, _ = sample
    shifted = feature + 1.5
    assert calculate_psi(feature, shifted) > 0.25


def test_iv_of_predictive_feature_is_meaningful(sample):
    feature, target = sample
    table = calculate_iv(feature.to_frame("x"), target)
    assert table.iloc[0]["iv"] > 0.1
    assert table.iloc[0]["level"] in {"中等", "强"}


def test_iv_of_noise_is_near_zero():
    rng = np.random.default_rng(1)
    x = pd.DataFrame({"noise": rng.normal(size=4000)})
    y = pd.Series(rng.integers(0, 2, 4000))
    assert calculate_iv(x, y).iloc[0]["iv"] < 0.03


def test_quantile_bins_binary_yields_two_bins():
    """二值特征不得退化为单箱（否则 IV/PSI 恒为 0）。"""
    s = pd.Series([0, 1, 0, 1, 0, 1])
    bp = quantile_bins(s, buckets=10)
    assert len(bp) == 3
    assert bp[1] == 0.5


def test_binary_feature_iv_is_not_zero():
    """二值强预测特征经分箱后 IV 应显著大于 0（回归：审计意见被误删）。"""
    rng = np.random.default_rng(5)
    n = 2000
    feature = pd.Series(np.concatenate([np.zeros(n), np.ones(n)]))
    target = pd.Series(np.concatenate([rng.binomial(1, 0.02, n), rng.binomial(1, 0.40, n)]))
    table = calculate_iv(feature.to_frame("binary"), target)
    assert table.iloc[0]["iv"] > 0.1


def test_vif_of_independent_features_is_low():
    rng = np.random.default_rng(2)
    X = pd.DataFrame(rng.normal(size=(500, 4)), columns=list("abcd"))
    assert calculate_vif(X).max() < 3.0


def test_vif_flags_collinearity():
    rng = np.random.default_rng(3)
    base = rng.normal(size=500)
    X = pd.DataFrame({"a": base, "b": base * 2 + rng.normal(0, 0.01, 500), "c": rng.normal(size=500)})
    assert calculate_vif(X).max() > 10


def test_drop_high_corr_keeps_higher_iv():
    rng = np.random.default_rng(4)
    base = rng.normal(size=400)
    X = pd.DataFrame({"strong": base, "duplicate": base + rng.normal(0, 0.001, 400)})
    dropped = drop_high_corr(X, pd.Series({"strong": 0.4, "duplicate": 0.1}), threshold=0.85)
    assert dropped == ["duplicate"]


def test_ks_perfect_separation():
    y = pd.Series([0, 0, 0, 1, 1, 1])
    score = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
    assert ks_statistic(y, score) == pytest.approx(1.0)


def test_psi_table_marks_status(sample):
    feature, _ = sample
    table = psi_table(feature.to_frame("x"), (feature + 2).to_frame("x"))
    assert table.iloc[0]["status"] == "漂移"
