"""概率校准测试：isotonic / Platt 回退 / 交叉拟合。"""

from __future__ import annotations

import numpy as np

from models.calibration import (
    IdentityCalibrator,
    cross_fitted_probabilities,
    fit_calibrator,
    load_calibrator,
    save_calibrator,
)


def _synthetic(n=600, seed=0, scale=1.0):
    rng = np.random.default_rng(seed)
    y = rng.binomial(1, 0.2, n)
    raw = np.clip(0.15 + 0.4 * y + rng.normal(0, 0.15 * scale, n), 0.001, 0.999)
    return y, raw


def test_isotonic_outputs_probabilities_and_is_monotonic():
    y, raw = _synthetic()
    calibrator = fit_calibrator(y, raw, method="isotonic")
    prob = calibrator.apply(np.linspace(0, 1, 100))
    assert calibrator.method == "isotonic"
    assert prob.min() >= 0 and prob.max() <= 1
    assert np.all(np.diff(prob) >= -1e-12)


def test_small_positive_set_falls_back_to_platt_probabilities():
    y, raw = _synthetic(n=200, seed=1)
    y[:] = 0
    y[:10] = 1
    calibrator = fit_calibrator(y, raw, method="isotonic")
    assert calibrator.method == "platt"
    prob = calibrator.apply(raw)
    assert prob.min() >= 0 and prob.max() <= 1
    # 必须是连续概率，而不是 LogisticRegression.predict 的 0/1 类别
    assert len(np.unique(prob)) > 2


def test_cross_fitted_probabilities_keep_shape_and_range():
    y, raw = _synthetic(n=800, seed=2)
    oof = cross_fitted_probabilities(y, raw, method="isotonic", n_splits=4)
    assert oof.shape == raw.shape
    assert oof.min() >= 0 and oof.max() <= 1


def test_identity_calibrator_is_safe_fallback():
    raw = np.array([0.01, 0.2, 0.8])
    assert np.allclose(IdentityCalibrator().apply(raw), raw)


def test_save_and_load_roundtrip(tmp_path):
    y, raw = _synthetic(n=300, seed=3)
    path = tmp_path / "calibrator.pkl"
    calibrator = fit_calibrator(y, raw, method="isotonic", fit_year=2022)
    save_calibrator(calibrator, path)
    loaded = load_calibrator(path)
    assert loaded.method == calibrator.method
    assert loaded.fit_year == 2022
    assert np.allclose(loaded.apply(raw[:20]), calibrator.apply(raw[:20]))
