"""文本情感特征清洗与规范化。

真实链路可使用词典基线或经版本冻结的 FinBERT 对年报 MD&A 打分后聚合；
本模块负责落库前的口径统一：裁剪到 [0,1]、重算极性，并保留缺失标记。
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
    # 只对有真实文本的行重算极性；缺文件不是「情感中性」，保留 NaN 给统一缺失处理。
    has_score = out[["mdna_positive", "mdna_negative"]].notna().all(axis=1)
    out.loc[has_score, "sentiment_polarity"] = (
        out.loc[has_score, "mdna_positive"] - out.loc[has_score, "mdna_negative"]
    ).clip(-1, 1)
    out["sentiment_volatility"] = out["sentiment_volatility"].clip(0, 1)
    out["forward_looking_ratio"] = out["forward_looking_ratio"].clip(0, 1)

    missing = out[TEXT_COLS].isna().all(axis=1).mean()
    if missing:
        logger.info("文本特征真实缺失占比 %.1f%%（保留缺失，不按中性处理）", missing * 100)
    extra = [c for c in ["text_available", "text_chars", "text_tokens", "text_sentences",
                         "sentiment_method", "lexicon_version"] if c in out.columns]
    return out[["stock_code", "year"] + TEXT_COLS + extra]
