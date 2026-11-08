"""风控统计工具函数：IV / PSI / VIF / KS / 分箱。

这些函数在特征筛选（etl）和模型监控（models）中复用，
集中实现可保证"训练期筛选口径"与"上线后监控口径"完全一致。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-6


# ---------------------------------------------------------------------------
# 分箱
# ---------------------------------------------------------------------------
def quantile_bins(expected: pd.Series, buckets: int = 10) -> np.ndarray:
    """基于参考样本的分位点切分，返回单调递增的边界数组。"""
    values = expected.dropna().to_numpy()
    breakpoints = np.unique(np.quantile(values, np.linspace(0, 1, buckets + 1)))
    if len(breakpoints) < 2:  # 常量特征
        breakpoints = np.array([values.min() - EPS, values.max() + EPS])
    breakpoints[0], breakpoints[-1] = -np.inf, np.inf
    return breakpoints


def _bin_pct(values: pd.Series, breakpoints: np.ndarray) -> np.ndarray:
    counts, _ = np.histogram(values.dropna().to_numpy(), bins=breakpoints)
    total = counts.sum()
    return counts / total if total else np.zeros(len(counts))


# ---------------------------------------------------------------------------
# PSI
# ---------------------------------------------------------------------------
def calculate_psi(expected: pd.Series, actual: pd.Series, buckets: int = 10) -> float:
    """群体稳定性指数。

    PSI < 0.1 稳定；0.1~0.25 轻度漂移需关注；> 0.25 显著漂移需重训练。
    """
    breakpoints = quantile_bins(expected, buckets)
    expected_pct = _bin_pct(expected, breakpoints)
    actual_pct = _bin_pct(actual, breakpoints)
    return float(np.sum((actual_pct - expected_pct) * np.log((actual_pct + EPS) / (expected_pct + EPS))))


def psi_table(expected: pd.DataFrame, actual: pd.DataFrame, buckets: int = 10) -> pd.DataFrame:
    """逐特征计算 PSI，返回按漂移程度降序的明细表。"""
    rows = []
    for col in expected.columns:
        if col not in actual.columns:
            continue
        psi = calculate_psi(expected[col], actual[col], buckets)
        status = "稳定" if psi < 0.10 else ("关注" if psi < 0.25 else "漂移")
        rows.append({"feature": col, "psi": round(psi, 4), "status": status})
    return pd.DataFrame(rows).sort_values("psi", ascending=False, ignore_index=True)


# ---------------------------------------------------------------------------
# IV
# ---------------------------------------------------------------------------
def _woe_iv(feature: pd.Series, target: pd.Series, buckets: int = 10) -> tuple[float, float]:
    """基于分位分箱计算单个特征的 IV 与最大 WOE 跨度。"""
    breakpoints = quantile_bins(feature, buckets)
    binned = pd.cut(feature, bins=breakpoints, include_lowest=True, duplicates="drop")
    grouped = pd.DataFrame({"bin": binned, "y": target}).groupby("bin", observed=False)["y"]
    stats = grouped.agg(["count", "sum"])
    stats.columns = ["total", "bad"]
    stats["good"] = stats["total"] - stats["bad"]
    total_bad, total_good = max(stats["bad"].sum(), 1), max(stats["good"].sum(), 1)
    bad_rate = (stats["bad"] / total_bad).clip(lower=EPS)
    good_rate = (stats["good"] / total_good).clip(lower=EPS)
    woe = np.log(bad_rate / good_rate)
    iv = float(((bad_rate - good_rate) * woe).sum())
    return iv, float((woe.max() - woe.min()) if len(woe) else 0.0)


def calculate_iv(features: pd.DataFrame, target: pd.Series, buckets: int = 10) -> pd.DataFrame:
    """批量计算 IV，返回 feature / iv / 预测力等级。"""
    rows = []
    for col in features.columns:
        try:
            iv, woe_range = _woe_iv(features[col], target, buckets)
        except Exception:  # 常量列、全缺失列
            iv, woe_range = 0.0, 0.0
        level = "无预测力" if iv < 0.02 else "弱" if iv < 0.1 else "中等" if iv < 0.3 else "强"
        rows.append({"feature": col, "iv": round(iv, 4), "woe_range": round(woe_range, 3), "level": level})
    return pd.DataFrame(rows).sort_values("iv", ascending=False, ignore_index=True)


# ---------------------------------------------------------------------------
# 共线性
# ---------------------------------------------------------------------------
def calculate_vif(features: pd.DataFrame) -> pd.Series:
    """方差膨胀因子；单特征或奇异矩阵时返回全 1。"""
    X = features.replace([np.inf, -np.inf], np.nan).fillna(features.median(numeric_only=True))
    if X.shape[1] < 2:
        return pd.Series(1.0, index=X.columns)
    corr = np.corrcoef(X.to_numpy(dtype=float), rowvar=False)
    try:
        inv = np.linalg.inv(corr)
    except np.linalg.LinAlgError:
        inv = np.linalg.pinv(corr)
    vif = np.diag(inv)
    return pd.Series(vif, index=X.columns)


def drop_high_corr(features: pd.DataFrame, iv_scores: pd.Series, threshold: float = 0.85) -> list[str]:
    """相关性去冗余：对 |r|>threshold 的特征对，保留 IV 更高者。"""
    corr = features.corr().abs()
    upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    to_drop: set[str] = set()
    for col in upper.columns:
        partners = upper.index[upper[col] > threshold].tolist()
        for partner in partners:
            if partner in to_drop or col in to_drop:
                continue
            weaker = partner if iv_scores.get(partner, 0) < iv_scores.get(col, 0) else col
            to_drop.add(weaker)
    return sorted(to_drop)


# ---------------------------------------------------------------------------
# KS
# ---------------------------------------------------------------------------
def ks_statistic(y_true: pd.Series, y_score: np.ndarray) -> float:
    """KS = max(TPR - FPR)，金融风控行业标准区分度指标。"""
    y_true = np.asarray(y_true)
    df = pd.DataFrame({"y": y_true, "s": np.asarray(y_score)}).sort_values("s", ascending=False)
    pos = max((df["y"] == 1).sum(), 1)
    neg = max((df["y"] == 0).sum(), 1)
    tpr = (df["y"] == 1).cumsum() / pos
    fpr = (df["y"] == 0).cumsum() / neg
    return float(np.max(np.abs(tpr - fpr)))
