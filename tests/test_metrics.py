"""评估指标测试：确保阈值选择与分级符合风控语义。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from models.metrics import (
    best_threshold,
    cost_optimal_threshold,
    evaluate_model,
    expected_calibration_error,
    score_to_level,
    top_k_metrics,
)


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


def test_cost_threshold_prefers_review_when_fn_expensive():
    y = np.array([0, 0, 0, 1, 1, 0, 0, 1])
    prob = np.array([0.1, 0.2, 0.3, 0.8, 0.9, 0.4, 0.05, 0.7])
    thr = cost_optimal_threshold(y, prob, cost_fn=10, cost_fp=1)
    assert 0.0 <= thr <= 1.0
    assert (prob >= thr).sum() <= len(y)


def test_cost_threshold_all_pass_when_false_positive_is_cheap():
    y = np.array([0, 0, 0, 0, 1])
    prob = np.array([0.2, 0.3, 0.4, 0.5, 0.1])
    thr = cost_optimal_threshold(y, prob, cost_fn=100, cost_fp=1)
    assert (prob >= thr).all()


def test_cost_threshold_all_reject_when_false_positive_is_expensive():
    y = np.array([1, 0, 0])
    prob = np.array([0.1, 0.9, 0.8])
    thr = cost_optimal_threshold(y, prob, cost_fn=1, cost_fp=100)
    assert (prob >= thr).sum() == 0


def test_top_k_metrics_capture_and_lift():
    y = np.array([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    prob = np.array([0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05])
    top = top_k_metrics(y, prob, fractions=(0.1,))
    assert top["top_10pct"]["n_reviewed"] == 1
    assert top["top_10pct"]["tp"] == 1
    assert top["top_10pct"]["recall"] == 0.5
    assert top["top_10pct"]["precision"] == 1.0
    assert top["top_10pct"]["lift"] == 5.0


def test_evaluate_model_reports_cost_and_topk():
    y = np.array([0, 0, 1, 1, 0, 0])
    prob = np.array([0.1, 0.2, 0.8, 0.7, 0.3, 0.05])
    m = evaluate_model(y, prob, threshold=0.5, cost_fn=10, cost_fp=1)
    assert m["cost"] == m["fn"] * 10 + m["fp"]
    assert "top_10pct" in m["top_k"]
    assert m["top_k"]["top_10pct"]["recall"] == 0.5
