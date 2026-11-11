"""模型评估指标：AUC / KS / F1 / Brier / ECE + 阈值选择 + 分群评估。

指标口径固定为"预警场景"语义：正样本=将被 ST 的高风险企业，
因此召回率（抓到多少高风险企业）比精确率更受关注。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.calibration import calibration_curve

from config import settings
from etl.stats_utils import ks_statistic


def expected_calibration_error(y_true: np.ndarray, y_prob: np.ndarray, bins: int = 10) -> float:
    """ECE：分箱内 |预测概率-实际频率| 的加权平均，衡量概率可信度。"""
    edges = np.quantile(y_prob, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    idx = np.digitize(y_prob, edges[1:-1])
    ece = 0.0
    for b in range(bins):
        mask = idx == b
        if mask.sum() == 0:
            continue
        ece += mask.mean() * abs(y_prob[mask].mean() - y_true[mask].mean())
    return float(ece)


def best_threshold(y_true: np.ndarray, y_prob: np.ndarray, method: str = "youden") -> float:
    """确定分类阈值：默认 Youden's J，另有 f1 可选。"""
    fpr, tpr, thresholds = roc_curve(y_true, y_prob)
    if method == "f1":
        scores = [f1_score(y_true, (y_prob >= t).astype(int), zero_division=0) for t in thresholds]
        return float(thresholds[int(np.argmax(scores))])
    j = tpr - fpr
    return float(thresholds[int(np.argmax(j))])


def evaluate_model(
    y_true: pd.Series | np.ndarray,
    y_prob: np.ndarray,
    threshold: float | None = None,
    name: str = "model",
) -> dict:
    """计算全套指标，返回可直接序列化为 JSON 的字典。"""
    y_true = np.asarray(y_true).astype(int)
    y_prob = np.asarray(y_prob, dtype=float)
    thr = best_threshold(y_true, y_prob) if threshold is None else float(threshold)
    y_pred = (y_prob >= thr).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()

    return {
        "model": name,
        "n_samples": int(len(y_true)),
        "positive_rate": round(float(y_true.mean()), 4),
        "auc": round(float(roc_auc_score(y_true, y_prob)), 4),
        "pr_auc": round(float(average_precision_score(y_true, y_prob)), 4),
        "ks": round(ks_statistic(y_true, y_prob), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "brier": round(float(brier_score_loss(y_true, y_prob)), 4),
        "ece": round(expected_calibration_error(y_true, y_prob), 4),
        "threshold": round(thr, 4),
        "tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn),
    }


def calibration_dataframe(y_true: pd.Series | np.ndarray, y_prob: np.ndarray, bins: int = 10) -> pd.DataFrame:
    """校准曲线数据点，供前端 Plotly 绘制。"""
    frac_pos, mean_pred = calibration_curve(y_true, y_prob, n_bins=bins, strategy="quantile")
    return pd.DataFrame({"预测概率": mean_pred, "实际违约率": frac_pos})


def group_metrics(
    df: pd.DataFrame,
    y_prob: np.ndarray,
    group_col: str = "industry",
    threshold: float | None = None,
) -> pd.DataFrame:
    """分群评估：检查模型在不同行业/年份上的表现是否一致。"""
    data = df.copy()
    data["_prob"] = y_prob
    rows = []
    for key, part in data.groupby(group_col):
        if len(part) < 20 or part["is_st"].nunique() < 2:
            continue
        m = evaluate_model(part["is_st"], part["_prob"].to_numpy(), threshold=threshold, name=str(key))
        m[group_col] = key
        rows.append(m)
    cols = [group_col, "n_samples", "positive_rate", "auc", "ks", "f1", "brier"]
    return pd.DataFrame(rows)[cols].sort_values("auc") if rows else pd.DataFrame(columns=cols)


@lru_cache(maxsize=8)
def _read_meta_thresholds(path: str, mtime_ns: int) -> dict:
    """读取并缓存模型元信息中的阈值块（按文件路径 + mtime 失效）。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    block = payload.get("threshold") or {}
    legacy = payload.get("risk_thresholds") or {}

    high = float(block.get("high", legacy.get("high", settings.RISK_THRESHOLDS["high"])))
    medium = float(block.get("medium", legacy.get("medium", settings.RISK_THRESHOLDS["medium"])))
    if medium >= high:  # 元信息异常时退回观察带比例，避免分级倒挂
        medium = round(high * settings.RISK_MEDIUM_RATIO, 4)

    if block:
        source = "model_meta"
    elif legacy:
        source = "model_meta(legacy)"
    else:
        source = "settings"
    return {
        "high": high,
        "medium": medium,
        "value": float(block.get("value", high)),
        "method": block.get("method", "settings"),
        "selected_on": block.get("selected_on", "-"),
        "source": source,
    }


def load_thresholds() -> dict:
    """风险分级阈值唯一入口：模型元信息优先，缺失时退回 settings 兜底值。"""
    path = Path(settings.MODEL_META)
    if path.exists():
        return _read_meta_thresholds(str(path), path.stat().st_mtime_ns)
    return {
        "high": float(settings.RISK_THRESHOLDS["high"]),
        "medium": float(settings.RISK_THRESHOLDS["medium"]),
        "value": float(settings.RISK_THRESHOLDS["high"]),
        "method": "settings_default",
        "selected_on": "-",
        "source": "settings",
    }


def score_to_level(prob: float, thresholds: dict | None = None) -> str:
    """风险概率 → 风险等级（高/中/低）。

    默认阈值来自 model_meta.json（训练时在验证集冻结），保证评估、监控、
    前端批量预警与 PDF 报告使用同一套口径。
    """
    thresholds = thresholds or load_thresholds()
    if prob >= thresholds["high"]:
        return "高风险"
    if prob >= thresholds["medium"]:
        return "中风险"
    return "低风险"
