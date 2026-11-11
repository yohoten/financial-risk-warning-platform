"""评估指标测试：确保阈值选择与分级符合风控语义。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from models.metrics import best_threshold, evaluate_model, expected_calibration_error, score_to_level


def test_perfect_prediction_metrics():
    y = pd.Series([0, 0, 1, 1])
    prob = np.array([0.05, 0.1, 0.85, 0.95])
    m = evaluate_model(y, prob, name="perfect")
    assert m["auc"] == 1.0
    assert m["ks"] == 1.0
    assert m["f1"] == 1.0
    assert m["brier"] < 0.01


def test_random_prediction_auc_near_half():
    rng = np.random.default_rng(0)
    y = pd.Series(rng.integers(0, 2, 4000))
    prob = rng.random(4000)
    assert abs(evaluate_model(y, prob)["auc"] - 0.5) < 0.05


def test_threshold_within_probability_range():
    rng = np.random.default_rng(1)
    y = pd.Series(rng.integers(0, 2, 500))
    prob = rng.random(500)
    thr = best_threshold(y.to_numpy(), prob)
    assert 0 <= thr <= 1


def test_score_to_level_boundaries():
    thresholds = {"high": 0.5, "medium": 0.25}
    assert score_to_level(0.9, thresholds) == "高风险"
    assert score_to_level(0.5, thresholds) == "高风险"
    assert score_to_level(0.3, thresholds) == "中风险"
    assert score_to_level(0.1, thresholds) == "低风险"


def test_ece_zero_for_calibrated_perfect():
    y = np.array([0, 0, 1, 1])
    prob = np.array([0.0, 0.0, 1.0, 1.0])
    assert expected_calibration_error(y, prob) < 0.01


def test_confusion_counts_consistent():
    y = pd.Series([1, 1, 0, 0, 1])
    prob = np.array([0.9, 0.6, 0.2, 0.55, 0.1])
    m = evaluate_model(y, prob, threshold=0.5)
    assert m["tp"] + m["fp"] + m["tn"] + m["fn"] == len(y)
    assert m["tp"] == 2 and m["fn"] == 1 and m["fp"] == 1 and m["tn"] == 1
