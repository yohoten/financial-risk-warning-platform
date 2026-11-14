# -*- coding: utf-8 -*-
"""TRD_Year（年个股回报率）→ 年度市场特征候选（仅用于消融，不进入生产注册表）。

产出 `data/raw/candidates/market_annual.csv`：

| 字段 | 口径 |
|---|---|
| annual_return | Yretwd（考虑现金红利再投资的年个股回报率，小数） |
| annual_return_ex_div | Yretnd（不考虑现金红利再投资） |
| ln_mktcap | ln(Ysmvttl × 1000)，总市值（千元 → 元） |
| trading_days | Ndaytrd（年交易天数） |

只保留 A 股市场（1=上证A、4=深证A、16=创业板、32=科创板、64=北证A），
按 (stock_code, year) 去重。**不写入契约层、不加入 feature_registry**，
由 `scripts.ablation_study` 作为独立特征块评估边际增量。

用法：
    python -m scripts.build_annual_market_features            # 预演
    python -m scripts.build_annual_market_features --write    # 写候选
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from config import settings
from etl.io_utils import get_logger, write_table

logger = get_logger("market-annual")

KEY = ["stock_code", "year"]
YEAR_MIN, YEAR_MAX = 2013, 2025
A_SHARE_MARKETS = {1, 4, 16, 32, 64}
OUTPUT = settings.RAW_DIR / "candidates" / "market_annual.csv"


def _source() -> Path:
    staged = settings.STAGING_DIR / "raw" / "TRD_Year.csv"
    if staged.exists():
        return staged
    hits = sorted(settings.RAW_DOWNLOAD_DIR.glob("**/TRD_Year.csv"))
    if not hits:
        raise FileNotFoundError(
            "未找到 TRD_Year.csv，请先 python -m scripts.sync_raw_download "
            "--only TRD_Year --write")
    return hits[0]


def load() -> pd.DataFrame:
    path = _source()
    df = pd.read_csv(path, dtype={"Stkcd": str}, encoding="utf-8-sig")
    df = df.rename(columns={"Stkcd": "stock_code", "Trdynt": "year"})
    df["stock_code"] = df["stock_code"].str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df[df["year"].between(YEAR_MIN, YEAR_MAX)]
    if "Yarkettype" in df.columns:
        market = pd.to_numeric(df["Yarkettype"], errors="coerce")
        df = df[market.isin(A_SHARE_MARKETS) | market.isna()]
    df["year"] = df["year"].astype(int)

    out = pd.DataFrame({
        "stock_code": df["stock_code"],
        "year": df["year"],
        "annual_return": pd.to_numeric(df.get("Yretwd"), errors="coerce"),
        "annual_return_ex_div": pd.to_numeric(df.get("Yretnd"), errors="coerce"),
        "trading_days": pd.to_numeric(df.get("Ndaytrd"), errors="coerce"),
    })
    mv = pd.to_numeric(df.get("Ysmvttl"), errors="coerce") * 1000     # 千元 → 元
    out["ln_mktcap"] = np.log(mv.where(mv > 0))
    out = (out.dropna(subset=KEY).sort_values(KEY).drop_duplicates(KEY, keep="last")
              .reset_index(drop=True))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="TRD_Year → 年度市场候选特征")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    df = load()
    window = df[df["year"].between(2015, 2023)]
    stats = {
        "rows": int(len(df)),
        "companies": int(df["stock_code"].nunique()),
        "year_min": int(df["year"].min()),
        "year_max": int(df["year"].max()),
        "rows_2015_2023": int(len(window)),
        "coverage_2015_2023": {
            c: round(float(window[c].notna().mean()), 4)
            for c in ("annual_return", "annual_return_ex_div", "ln_mktcap", "trading_days")
        },
        "annual_return_median": round(float(window["annual_return"].median()), 4),
        "source": settings.rel(_source()),
    }
    logger.info("年度行情：%d 行 / %d 家 / %d–%d；2015–2023 覆盖 %s",
                stats["rows"], stats["companies"], stats["year_min"], stats["year_max"],
                stats["coverage_2015_2023"])

    if args.write:
        path = write_table(df, OUTPUT)
        stats["output"] = settings.rel(path)
        (OUTPUT.parent / "market_annual_manifest.json").write_text(
            json.dumps({"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **stats},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("已写出：%s", settings.rel(path))
    else:
        logger.info("预演完成（加 --write 写出 %s）", settings.rel(OUTPUT))


if __name__ == "__main__":
    main()
