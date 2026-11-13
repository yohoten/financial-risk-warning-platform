"""推理服务：批量/单企业打分，供 Streamlit 与 CSV 导出复用。

对外只暴露三个函数：`predict_frame`（任意特征表）、`predict_codes`（按股票代码）、
`load_predictions`（读取缓存的最新评分结果）。
"""

from __future__ import annotations

import json
from functools import lru_cache

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from config import settings
from config.feature_registry import TARGET_COLUMN
from etl.io_utils import get_logger, read_table, resolve, write_table
from models.calibration import load_calibrator
from models.metrics import score_to_level

logger = get_logger("predict")


@lru_cache(maxsize=1)
def load_model() -> XGBClassifier:
    """加载主模型（进程内只加载一次）。"""
    if not settings.MODEL_PATH.exists():
        raise FileNotFoundError(
            f"未找到模型文件 {settings.rel(settings.MODEL_PATH)}，请先运行 python -m models.train"
        )
    model = XGBClassifier()
    model.load_model(str(settings.MODEL_PATH))
    return model


@lru_cache(maxsize=1)
def load_meta() -> dict:
    if not settings.MODEL_META.exists():
        return {"features": [], "created_at": "unknown"}
    return json.loads(settings.MODEL_META.read_text(encoding="utf-8"))


def predict_frame(df: pd.DataFrame, features: list[str] | None = None) -> pd.DataFrame:
    """对特征表打分，返回带概率、等级、百分位的 DataFrame。"""
    features = features or load_meta().get("features") or [c for c in df.columns if c not in {"stock_code", "year", "company_name", "industry", TARGET_COLUMN}]
    missing = [f for f in features if f not in df.columns]
    if missing:
        raise ValueError(f"特征缺失 {len(missing)} 维，例如 {missing[:5]}")

    model = load_model()
    out = _normalize_code_column(df)
    raw_prob = model.predict_proba(out[features].astype(float))[:, 1]
    out["st_prob_raw"] = raw_prob
    out["st_prob"] = load_calibrator().apply(raw_prob)
    out["risk_level"] = out["st_prob"].map(score_to_level)
    out["risk_percentile"] = out["st_prob"].rank(pct=True).round(4)
    return out


def predict_codes(codes: list[str], year: int | None = None) -> pd.DataFrame:
    """按股票代码打分；year 缺省时取每家公司最新可得年份。"""
    panel = load_panel_for_inference()
    codes = [str(c).strip().zfill(6) for c in codes if str(c).strip()]
    subset = panel[panel["stock_code"].isin(codes)]
    if subset.empty:
        raise ValueError("输入的股票代码在数据集中不存在，请检查代码是否正确")
    if year is not None:
        subset = subset[subset["year"] == year]
    else:
        subset = subset.sort_values("year").groupby("stock_code", as_index=False).tail(1)
    return predict_frame(subset).sort_values("st_prob", ascending=False)


def load_panel_for_inference() -> pd.DataFrame:
    """推理用面板：优先缓存，其次 feature_store。"""
    if resolve(settings.PREDICTION_PATH):
        cached = read_table(settings.PREDICTION_PATH)
        if {"stock_code", "st_prob"}.issubset(cached.columns):
            return cached
    panel = read_table(settings.FEATURE_MATRIX) if resolve(settings.FEATURE_MATRIX) else read_table(settings.FEATURE_PANEL)
    return panel


def refresh_predictions() -> pd.DataFrame:
    """对全量面板重新打分并写入缓存（供看板/批量预警使用）。"""
    panel = read_table(settings.FEATURE_MATRIX) if resolve(settings.FEATURE_MATRIX) else read_table(settings.FEATURE_PANEL)
    scored = predict_frame(panel)
    write_table(scored, settings.PREDICTION_PATH)
    logger.info("已刷新全量评分缓存：%d 行 → %s", len(scored), settings.rel(settings.PREDICTION_PATH))
    return scored


def _normalize_code_column(df: pd.DataFrame) -> pd.DataFrame:
    """股票代码统一为 6 位字符串：CSV 往返会丢失前导零，导致按代码查询为空。"""
    if "stock_code" not in df.columns:
        return df
    out = df.copy()
    out["stock_code"] = out["stock_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    return out


def load_predictions() -> pd.DataFrame:
    """读取评分缓存；不存在则即时计算。"""
    if resolve(settings.PREDICTION_PATH):
        return _normalize_code_column(read_table(settings.PREDICTION_PATH))
    return refresh_predictions()


def company_profile(stock_code: str, year: int | None = None) -> dict:
    """单企业诊断所需的全部素材：基本信息、评分、同行业排名、历史轨迹。"""
    scored = load_predictions()
    company = scored[scored["stock_code"] == stock_code]
    if company.empty:
        raise ValueError(f"未找到股票代码 {stock_code}")
    latest = company.sort_values("year").iloc[-1] if year is None else company[company["year"] == year].iloc[-1]

    peers = scored[(scored["year"] == latest["year"]) & (scored["industry"] == latest["industry"])]
    rank = int((peers["st_prob"] > latest["st_prob"]).sum() + 1)

    return {
        "stock_code": stock_code,
        "company_name": latest.get("company_name", stock_code),
        "industry": latest.get("industry", "未知"),
        "year": int(latest["year"]),
        "st_prob": float(latest["st_prob"]),
        "risk_level": latest["risk_level"],
        "risk_percentile": float(latest["risk_percentile"]),
        "peer_count": int(len(peers)),
        "peer_rank": rank,
        "peer_avg_prob": float(peers["st_prob"].mean()) if len(peers) else np.nan,
        "history": company.sort_values("year")[["year", "st_prob", "risk_level"]].reset_index(drop=True),
        "features": latest,
    }
