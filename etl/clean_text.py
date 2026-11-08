"""文本情感特征清洗与规范化。

真实链路由 FinBERT 对年报 MD&A 段落逐段打分后聚合，
本模块负责落库前的口径统一：裁剪到 [0,1]、重算极性、缺失补齐。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from etl.io_utils import get_logger

logger = get_logger("clean-text")

TEXT_COLS = [
    "mdna_positive",
    "mdna_negative",
    "mdna_uncertainty",
    "sentiment_polarity",
    "sentiment_volatility",
    "forward_looking_ratio",
]


def clean_sentiment(df: pd.DataFrame) -> pd.DataFrame:
    """规范化情感打分：区间裁剪 → 极性重算 → 缺失补齐。"""
    out = df.copy()
    for col in TEXT_COLS:
        if col not in out.columns:
            out[col] = np.nan

    score_cols = ["mdna_positive", "mdna_negative", "mdna_uncertainty"]
    out[score_cols] = out[score_cols].clip(0, 1)
    out["sentiment_polarity"] = (out["mdna_positive"] - out["mdna_negative"]).clip(-1, 1)
    out["sentiment_volatility"] = out["sentiment_volatility"].clip(0, 1)
    out["forward_looking_ratio"] = out["forward_looking_ratio"].clip(0, 1)

    # 无文本数据的样本：情感中性、波动为 0，避免"无披露"被误读为"极度悲观"
    out["sentiment_polarity"] = out["sentiment_polarity"].fillna(0.0)
    out[TEXT_COLS] = out[TEXT_COLS].fillna(0.0)

    missing = out[TEXT_COLS].eq(0).all(axis=1).mean()
    if missing:
        logger.info("文本特征缺失（按中性处理）占比 %.1f%%", missing * 100)
    return out[["stock_code", "year"] + TEXT_COLS]
