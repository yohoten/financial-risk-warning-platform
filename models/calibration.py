"""概率校准：验证集拟合、测试集只应用。

中期采用等渗回归（isotonic）作为默认校准器；当验证集正样本过少或等渗失败时
自动回退到 Platt（logistic）校准。校准器与主模型分开保存，推理、评估、监控
统一通过 `apply` 变换，避免“训练时校准、上线时未校准”的口径错位。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import joblib
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from config import settings
from etl.io_utils import get_logger

logger = get_logger("calibration")


@dataclass
class ProbabilityCalibrator:
    """只依赖概率的一维校准器。"""

    method: str
    model: Any
    fit_year: int | None = None
    n_fit: int = 0
    positive_fit: int = 0
    fallback_reason: str | None = None

    def apply(self, prob: np.ndarray | list[float]) -> np.ndarray:
        p = np.clip(np.asarray(prob, dtype=float).reshape(-1), 0.0, 1.0)
        if self.method == "identity":
            return p
        if self.method == "platt":
            out = self.model.predict_proba(p.reshape(-1, 1))[:, 1]
        else:
            out = self.model.predict(p)
        return np.clip(np.asarray(out, dtype=float).reshape(-1), 0.0, 1.0)

    def describe(self) -> dict:
        return {
            "method": self.method,
            "fit_year": self.fit_year,
            "n_fit": self.n_fit,
            "positive_fit": self.positive_fit,
            "fallback_reason": self.fallback_reason,
        }


class IdentityCalibrator(ProbabilityCalibrator):
    """无校准器时的安全兜底：保持原概率，不改变排序。"""

    def __init__(self) -> None:
        super().__init__(method="identity", model=None, fallback_reason="calibrator_missing")


def fit_calibrator(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    method: str | None = None,
    fit_year: int | None = None,
) -> ProbabilityCalibrator:
    """在验证集上拟合校准器；不接触测试集。"""
    y = np.asarray(y_true).astype(int).reshape(-1)
    p = np.clip(np.asarray(y_prob, dtype=float).reshape(-1), 0.0, 1.0)
    if len(y) != len(p):
        raise ValueError("y_true 与 y_prob 长度不一致")
    if len(np.unique(y)) < 2:
        raise ValueError("校准需要同时包含正负样本")

    selected = (method or settings.CALIBRATION_METHOD).lower()
    positives = int(y.sum())
    fallback = None
    if selected == "isotonic" and positives < 20:
        selected = "platt"
        fallback = f"positive_fit={positives}<20，等渗回退 Platt"

    try:
        if selected == "isotonic":
            model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            model.fit(p, y)
        elif selected == "platt":
            model = LogisticRegression(solver="lbfgs", max_iter=1000)
            model.fit(p.reshape(-1, 1), y)
        else:
            raise ValueError(f"未知校准方法：{selected}")
    except Exception as exc:
        logger.warning("校准器拟合失败（%s），回退 Platt：%s", selected, exc)
        selected = "platt"
        fallback = f"{type(exc).__name__}: {exc}"
        model = LogisticRegression(solver="lbfgs", max_iter=1000)
        model.fit(p.reshape(-1, 1), y)

    return ProbabilityCalibrator(
        method=selected,
        model=model,
        fit_year=fit_year,
        n_fit=int(len(y)),
        positive_fit=positives,
        fallback_reason=fallback,
    )


def save_calibrator(calibrator: ProbabilityCalibrator, path=None) -> None:
    target = path or settings.CALIBRATOR_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(calibrator, target)
    logger.info("校准器已保存：%s（%s，验证集 %d 行）", settings.rel(target), calibrator.method, calibrator.n_fit)


def load_calibrator(path=None) -> ProbabilityCalibrator:
    """加载校准器；文件缺失/版本不兼容时返回恒等校准，保证推理不中断。"""
    target = path or settings.CALIBRATOR_PATH
    if not target.exists():
        return IdentityCalibrator()
    try:
        calibrator = joblib.load(target)
        if not isinstance(calibrator, ProbabilityCalibrator):
            raise TypeError(f"unexpected calibrator type: {type(calibrator)}")
        return calibrator
    except Exception as exc:
        logger.warning("校准器加载失败（%s），本次使用恒等校准", exc)
        return IdentityCalibrator()


def calibrate_probabilities(prob: np.ndarray | list[float], calibrator=None) -> np.ndarray:
    """便捷函数：应用校准器；缺省时自动加载。"""
    return (calibrator or load_calibrator()).apply(prob)


def cross_fitted_probabilities(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    method: str | None = None,
    n_splits: int = 5,
    random_state: int = 42,
) -> np.ndarray:
    """验证集内部的交叉拟合概率，用于诚实地报告校准指标。

    直接在验证集上拟合再评估，ECE 会被人为压到 0；这里用 StratifiedKFold
    做 out-of-fold 校准，仅用于“验证集报告/阈值选择”。部署校准器仍在全验证集
    重拟合，测试集只应用。
    """
    from sklearn.model_selection import StratifiedKFold

    y = np.asarray(y_true).astype(int).reshape(-1)
    p = np.clip(np.asarray(y_prob, dtype=float).reshape(-1), 0.0, 1.0)
    if len(y) != len(p):
        raise ValueError("y_true 与 y_prob 长度不一致")
    if len(np.unique(y)) < 2:
        return p
    max_splits = min(int(y.sum()), int((1 - y).sum()))
    n_splits = max(2, min(int(n_splits), max_splits))
    if max_splits < 2:
        return fit_calibrator(y, p, method=method).apply(p)

    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=random_state)
    oof = np.full(len(y), np.nan, dtype=float)
    for train_idx, test_idx in skf.split(p.reshape(-1, 1), y):
        try:
            fold_calibrator = fit_calibrator(y[train_idx], p[train_idx], method=method)
            oof[test_idx] = fold_calibrator.apply(p[test_idx])
        except Exception as exc:
            logger.warning("交叉拟合校准失败，该折保留原概率：%s", exc)
            oof[test_idx] = p[test_idx]
    if np.isnan(oof).any():
        oof = np.where(np.isnan(oof), p, oof)
    return np.clip(oof, 0.0, 1.0)
