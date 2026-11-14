"""Promote the CSMAR TRD_Dly company-year market table to the active contract.

Unit contract
-------------
annual_turnover : decimal turns per year (sum of daily shares traded / free-float
                  shares); NOT percent.  The old active table stored percent
                  values (100x), so it is replaced rather than mixed.
stock_volatility: annualised standard deviation of daily returns, decimal.

The audit-opinion columns are kept from the old active table; the market
columns are replaced by the candidate TRD table.  ``market_available`` marks
whether a TRD company-year record exists.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import settings

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
LEGACY_MARKET = RAW / "market_features.csv"  # audit-only legacy table; never write it
OUT = RAW / "market_features_trd.csv"
CAND = RAW / "candidates" / "TRD_Dly_company_year_2013_2026.csv"
AUDIT_COLS = ["audit_opinion", "big4_audit", "audit_fee"]


def _normalize_code(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.extract(r"(\d{1,6})", expand=False)
        .str.zfill(6)
    )


def build() -> pd.DataFrame:
    active = pd.read_csv(LEGACY_MARKET, dtype={"stock_code": str}, encoding="utf-8-sig")
    active["stock_code"] = _normalize_code(active["stock_code"])
    active["year"] = pd.to_numeric(active["year"], errors="coerce")
    audit = (
        active.dropna(subset=["stock_code", "year"])
        .assign(year=lambda d: d["year"].astype(int))
        [["stock_code", "year", *[c for c in AUDIT_COLS if c in active.columns]]]
        .drop_duplicates(["stock_code", "year"])
    )

    trd = pd.read_csv(CAND, dtype={"Stkcd": str}, encoding="utf-8-sig")
    trd["stock_code"] = _normalize_code(trd["Stkcd"])
    trd["year"] = pd.to_numeric(trd["year"], errors="coerce")
    trd = trd.dropna(subset=["stock_code", "year"]).copy()
    trd["year"] = trd["year"].astype(int)
    trd = trd[
        [
            "stock_code", "year", "trading_days", "annual_turnover", "stock_volatility",
            "turnover_coverage", "return_coverage",
        ]
    ].drop_duplicates(["stock_code", "year"])

    out = audit.merge(trd, on=["stock_code", "year"], how="outer", indicator=True)
    out["market_available"] = out["_merge"].ne("left_only").astype(int)
    out = out.drop(columns=["_merge"])
    out["market_source"] = "CSMAR.TRD_Dly.company_year"
    out["turnover_unit"] = "decimal_turns_per_year"
    out = out.sort_values(["stock_code", "year"]).reset_index(drop=True)

    print(f"active audit rows: {len(audit):,}; TRD rows: {len(trd):,}; union: {len(out):,}")
    print(f"market_available: {out['market_available'].sum():,} ({out['market_available'].mean():.2%})")
    print(out[["annual_turnover", "stock_volatility"]].describe(percentiles=[0.01, 0.5, 0.99]).to_string())
    return out


def main() -> None:
    settings.ensure_dirs()
    out = build()
    path = OUT
    if path.exists():
        backup = path.with_suffix(path.suffix + f".bak_{datetime.now():%Y%m%d_%H%M%S}")
        shutil.copy2(path, backup)
        print(f"backup: {backup}")
    out.to_csv(path, index=False, encoding="utf-8-sig")
    summary = {
        "path": str(path),
        "rows": int(len(out)),
        "companies": int(out["stock_code"].nunique()),
        "years": [int(out["year"].min()), int(out["year"].max())],
        "market_available_rate": float(out["market_available"].mean()),
        "annual_turnover_unit": "decimal_turns_per_year",
        "annual_turnover_median": float(out["annual_turnover"].median()),
        "annual_turnover_p99": float(out["annual_turnover"].quantile(0.99)),
        "stock_volatility_median": float(out["stock_volatility"].median()),
        "source": "CSMAR.TRD_Dly (2013-2026) + prior audit columns",
    }
    profile = path.with_suffix(path.suffix + ".profile.json")
    profile.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote: {path}")
    print(f"wrote: {profile}")


if __name__ == "__main__":
    main()
