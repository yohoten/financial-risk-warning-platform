"""MD&A 词典基线与缺失语义回归测试。"""
from __future__ import annotations

import pandas as pd

from etl.clean_text import clean_sentiment
from scripts.build_text_features import score_text


def test_score_text_counts_and_sentences() -> None:
    result = score_text("公司盈利增长，经营稳健。未来将继续推进转型。诉讼风险下降，但仍有不确定性。")
    assert result["text_available"] == 1
    assert result["text_tokens"] > 0
    assert result["mdna_positive"] > 0
    assert result["mdna_negative"] > 0
    assert result["forward_looking_ratio"] > 0
    assert result["mdna_uncertainty"] > 0
    assert 0 <= result["sentiment_volatility"] <= 1


def test_score_text_empty_is_unavailable() -> None:
    result = score_text("")
    assert result["text_available"] == 0
    assert pd.isna(result["mdna_positive"])
    assert pd.isna(result["sentiment_volatility"])


def test_clean_text_preserves_missing_and_recomputes_polarity() -> None:
    df = pd.DataFrame({
        "stock_code": ["000001", "000002"], "year": [2022, 2022],
        "mdna_positive": [0.02, None], "mdna_negative": [0.01, None],
        "mdna_uncertainty": [0.002, None], "sentiment_polarity": [0.0, None],
        "sentiment_volatility": [0.2, None], "forward_looking_ratio": [0.01, None],
    })
    out = clean_sentiment(df)
    assert out.loc[0, "sentiment_polarity"] == 0.01
    assert pd.isna(out.loc[1, "sentiment_polarity"])
    assert pd.isna(out.loc[1, "mdna_negative"])
