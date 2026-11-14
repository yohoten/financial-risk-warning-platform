"""从已整理的 MD&A TXT 构建 6 维文本特征（词典基线）。

口径
----
- 正面/负面/不确定性/前瞻性 = 对应词数 / 全文有效词数；
- 情感极性由 `etl.clean_text` 统一为 正面得分 - 负面得分；
- 情感波动率 = 句子级 (正-负)/(正+负) 的标准差，中性句记 0；
- 缺文件/空文本保留 NaN 并写 text_available=0，不能把「未获取」当作中性文本。

这是 lexicon_cn_v1 基线，不是 FinBERT。词典版本、输入文件和输出画像一并落盘。

用法：
    python -m scripts.build_text_features --limit 200 --out data/raw/candidates/text_sentiment_smoke.csv
    python -m scripts.build_text_features --workers 6 --write
"""
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import jieba
import numpy as np
import pandas as pd

from config import settings
from config.text_lexicons import FORWARD_LOOKING, LEXICON_VERSION, NEGATIVE, POSITIVE, UNCERTAINTY
from etl.io_utils import get_logger, write_table

logger = get_logger("text-features")

def _resolve_default_source() -> Path:
    """文本树优先取落地区；兼容历史上 ``CSMAR_download/pakage`` 的旧路径。"""
    candidates = [
        settings.RAW_DOWNLOAD_DIR / "年报MDA管理层讨论与分析文本txt整理2001-2024年",
        settings.PROJECT_ROOT / "CSMAR_download" / "pakage"
        / "年报MDA管理层讨论与分析文本txt整理2001-2024年",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


DEFAULT_SOURCE = _resolve_default_source()
DEFAULT_OUTPUT = settings.RAW_TEXT_SENTIMENT
SENTENCE_SPLIT = re.compile(r"[。！？!?；;\n]+")
VALID_TOKEN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")

for word in POSITIVE | NEGATIVE | UNCERTAINTY | FORWARD_LOOKING:
    jieba.add_word(word)


def score_text(text: str) -> dict:
    """对单份 MD&A 文本打分；空文本返回零句数与 NaN 比率。"""
    sentence_polarity = []
    totals = {"tokens": 0, "positive": 0, "negative": 0, "uncertainty": 0, "forward": 0}
    for sentence in SENTENCE_SPLIT.split(text):
        tokens = [w for w in jieba.lcut(sentence, cut_all=False) if VALID_TOKEN.search(w)]
        if not tokens:
            continue
        pos = sum(w in POSITIVE for w in tokens)
        neg = sum(w in NEGATIVE for w in tokens)
        totals["tokens"] += len(tokens)
        totals["positive"] += pos
        totals["negative"] += neg
        totals["uncertainty"] += sum(w in UNCERTAINTY for w in tokens)
        totals["forward"] += sum(w in FORWARD_LOOKING for w in tokens)
        sentence_polarity.append((pos - neg) / (pos + neg) if pos + neg else 0.0)
    n = totals["tokens"]
    return {
        "mdna_positive": totals["positive"] / n if n else np.nan,
        "mdna_negative": totals["negative"] / n if n else np.nan,
        "mdna_uncertainty": totals["uncertainty"] / n if n else np.nan,
        "sentiment_polarity": (totals["positive"] - totals["negative"]) / n if n else np.nan,
        "sentiment_volatility": float(np.std(sentence_polarity)) if sentence_polarity else np.nan,
        "forward_looking_ratio": totals["forward"] / n if n else np.nan,
        "text_chars": len(text),
        "text_tokens": n,
        "text_sentences": len(sentence_polarity),
        "text_available": int(n > 0),
    }


def score_file(path: Path) -> dict:
    code, date = path.stem.split("_", 1)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="gb18030")
    return {"stock_code": code, "year": int(date[:4]), **score_text(text)}


def _score_file_star(path_str: str) -> dict:
    return score_file(Path(path_str))


def build(source: Path, output: Path, limit: int = 0, workers: int = 1,
          write: bool = False) -> pd.DataFrame:
    files = sorted(source.glob("*.txt"))
    if limit:
        files = files[:limit]
    if not files:
        raise FileNotFoundError(f"未找到 MD&A TXT：{source}")
    paths = [str(p) for p in files]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            records = list(pool.map(_score_file_star, paths, chunksize=32))
    else:
        records = [score_file(p) for p in files]
    out = pd.DataFrame(records)
    out["stock_code"] = out["stock_code"].astype(str).str.zfill(6)
    out["sentiment_method"] = "dictionary_baseline_not_finbert"
    out["lexicon_version"] = LEXICON_VERSION
    out["text_source"] = "第三方整理年报MD&A_TXT_2001_2024"

    # 显式保留当前面板缺失键，避免将「无文件」误读为「中性情感」。
    if settings.FEATURE_PANEL.exists():
        panel = pd.read_parquet(settings.FEATURE_PANEL, columns=["stock_code", "year"])
        panel["year"] = panel["year"].astype(int)
        missing = panel.merge(out[["stock_code", "year"]], on=["stock_code", "year"],
                              how="left", indicator=True)
        missing = missing[missing["_merge"].eq("left_only")].drop(columns="_merge")
        if len(missing):
            absent = missing.copy()
            absent["text_available"] = 0
            out = pd.concat([out, absent], ignore_index=True, sort=False)
    out = out.sort_values(["stock_code", "year"]).reset_index(drop=True)

    profile = {
        "source": str(source), "output": str(output), "txt_files_scored": len(files),
        "rows": len(out), "companies": int(out["stock_code"].nunique()),
        "years": [int(out["year"].min()), int(out["year"].max())],
        "available_rows": int(out["text_available"].eq(1).sum()),
        "unavailable_rows": int(out["text_available"].eq(0).sum()),
        "method": "dictionary_baseline_not_finbert", "lexicon_version": LEXICON_VERSION,
        "feature_nonzero_rate": {
            c: float(out[c].fillna(0).ne(0).mean())
            for c in ["mdna_positive", "mdna_negative", "mdna_uncertainty",
                      "sentiment_volatility", "forward_looking_ratio"]
        },
    }
    if write:
        write_table(out, output)
        profile_path = output.with_suffix(output.suffix + ".profile.json")
        profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("文本特征已写出：%s（%d 行）", settings.rel(output), len(out))
    logger.info("打分完成：%s", profile)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="MD&A TXT → 6 维文本词典基线")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0, help="仅前 N 份，用于冒烟")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    build(args.source, args.out, args.limit, args.workers, args.write)


if __name__ == "__main__":
    main()
