"""Build company-year market features from CSMAR TRD_Dly (日个股回报率).

The raw daily export is kept in data/incoming; this compact company-year table
is the candidate feature input.  The promoted contract is
data/raw/market_features_trd.csv (see scripts/build_market_features.py); the old
percent-scale table is archived as market_features_legacy_percent.csv.

Definitions
-----------
trading_days       number of observed trading days in the company-year
annual_return      product(1 + Dretwd) - 1
return_mean        mean(Dretwd)
stock_volatility   sample std(Dretwd) * sqrt(252)
annual_turnover    sum(Dnshrtrd / (Dsmvosd * 1000 / Clsprc)); daily share turnover
avg_market_cap     mean(Dsmvosd), thousand yuan (CSMAR native unit)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def build(inputs: list[Path], out_path: Path) -> dict:
    frames = []
    for path in inputs:
        df = pd.read_csv(
            path,
            usecols=["Stkcd", "Trddt", "Clsprc", "Dnshrtrd", "Dsmvosd", "Dretwd"],
            dtype={"Stkcd": "string"},
        )
        df["year"] = df["Trddt"].str.slice(0, 4).astype("int16")
        frames.append(df)
    daily = pd.concat(frames, ignore_index=True)

    daily["Dretwd"] = pd.to_numeric(daily["Dretwd"], errors="coerce")
    daily["Clsprc"] = pd.to_numeric(daily["Clsprc"], errors="coerce")
    daily["Dnshrtrd"] = pd.to_numeric(daily["Dnshrtrd"], errors="coerce")
    daily["Dsmvosd"] = pd.to_numeric(daily["Dsmvosd"], errors="coerce")

    # CSMAR Dsmvosd is reported in thousand yuan; Clsprc is yuan/share.
    shares = daily["Dsmvosd"] * 1000.0 / daily["Clsprc"].where(daily["Clsprc"] > 0)
    daily["turnover_daily"] = daily["Dnshrtrd"] / shares.where(shares > 0)
    daily["log1p_ret"] = np.log1p(daily["Dretwd"].where(daily["Dretwd"] > -1))

    grouped = daily.groupby(["Stkcd", "year"], sort=True)
    out = grouped.agg(
        trading_days=("Trddt", "nunique"),
        return_mean=("Dretwd", "mean"),
        return_std=("Dretwd", "std"),
        annual_turnover=("turnover_daily", "sum"),
        avg_market_cap=("Dsmvosd", "mean"),
        avg_close=("Clsprc", "mean"),
        valid_return_days=("Dretwd", "count"),
        valid_turnover_days=("turnover_daily", "count"),
    ).reset_index()
    annual_log = grouped["log1p_ret"].sum(min_count=1).rename("annual_log_return").reset_index()
    out = out.merge(annual_log, on=["Stkcd", "year"], how="left")
    out["annual_return"] = np.expm1(out["annual_log_return"])
    out["stock_volatility"] = out["return_std"] * np.sqrt(252.0)
    out["turnover_coverage"] = out["valid_turnover_days"] / out["trading_days"]
    out["return_coverage"] = out["valid_return_days"] / out["trading_days"]

    # Keep raw-scale values but document the distributions; no silent winsorising.
    out = out.sort_values(["Stkcd", "year"]).reset_index(drop=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")

    summary = {
        "out_path": str(out_path),
        "rows": int(len(out)),
        "companies": int(out["Stkcd"].nunique()),
        "years": [int(out["year"].min()), int(out["year"].max())],
        "columns": list(out.columns),
        "annual_turnover": {
            "non_null": int(out["annual_turnover"].notna().sum()),
            "median": float(out["annual_turnover"].median()),
            "p99": float(out["annual_turnover"].quantile(0.99)),
            "max": float(out["annual_turnover"].max()),
        },
        "stock_volatility": {
            "non_null": int(out["stock_volatility"].notna().sum()),
            "median": float(out["stock_volatility"].median()),
            "p99": float(out["stock_volatility"].quantile(0.99)),
            "max": float(out["stock_volatility"].max()),
        },
        "annual_return": {
            "non_null": int(out["annual_return"].notna().sum()),
            "median": float(out["annual_return"].median()),
            "p01": float(out["annual_return"].quantile(0.01)),
            "p99": float(out["annual_return"].quantile(0.99)),
        },
        "source_files": [str(p) for p in inputs],
    }
    profile = out_path.with_suffix(out_path.suffix + ".profile.json")
    profile.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", action="append", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.input, args.out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
