"""Build the active legal-event contract from CSMAR raw exports.

Definition (frozen for this project)
------------------------------------
litigation_count
    Number of distinct ``EventID`` whose **first observed announcement**
    (minimum ``DeclareDate`` across all progress/annual-report rows) falls in
    the company-year.  Later annual-report or progress announcements for the
    same event are not counted again.

penalty_count
    Number of distinct ``ViolationID`` with ``IsViolated=Y`` whose **final
    disposal date** (``DisposalDate``) falls in the company-year.  This is the
    regulatory outcome date, not the first media report date.

The output is a full company-year grid for A-share C manufacturing firms, so
``legal_available=1`` means "the source grid covers this key"; a zero count
means "covered and no event observed", not missing data.

Usage:
    python -m scripts.build_legal_features
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from config import settings
from etl.csmar_import import A_SHARE_PREFIXES

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INCOMING = ROOT / "data" / "incoming" / "csmar"
KEY = ["stock_code", "year"]
YEAR_MIN, YEAR_MAX = 2013, 2026
CNY_CODES = {"CNY", "RMB", "人民币", "人民币元", ""}


def _normalize_code(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.extract(r"(\d{1,6})", expand=False)
        .str.zfill(6)
    )


def _backup(path: Path) -> None:
    if path.exists():
        backup = path.with_suffix(path.suffix + f".bak_{datetime.now():%Y%m%d_%H%M%S}")
        shutil.copy2(path, backup)
        print(f"backup: {backup}")


def _financial_grid() -> pd.DataFrame:
    """A-share C-manufacturing company-year grid from the active financial table."""
    fin = pd.read_csv(
        settings.RAW_FINANCIAL,
        dtype={"stock_code": str},
        usecols=["stock_code", "year", "industry"],
        encoding="utf-8-sig",
    )
    fin["stock_code"] = _normalize_code(fin["stock_code"])
    fin["year"] = pd.to_numeric(fin["year"], errors="coerce")
    fin = fin.dropna(subset=KEY).copy()
    fin["year"] = fin["year"].astype(int)
    fin = fin[
        fin["stock_code"].str[:3].isin(A_SHARE_PREFIXES)
        & fin["industry"].astype(str).str.upper().str.startswith(settings.MANUFACTURING_PREFIX)
        & fin["year"].between(YEAR_MIN, YEAR_MAX)
    ]
    return fin[KEY].drop_duplicates().sort_values(KEY).reset_index(drop=True)


def _read_lawsuits() -> pd.DataFrame:
    """Parse ``LAW_lawsuit.csv`` by fixed leading columns.

    The export contains unescaped commas in ``EventContent``; pandas' C parser
    cannot read it reliably.  The first five columns are stable:
    Symbol, ShortName, EventID, DeclareType, DeclareDate.
    """
    path = RAW / "LAW_lawsuit.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing {path}")

    records: list[tuple[str, str, str, str, str]] = []
    bad = 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)
        for fields in reader:
            if len(fields) < 5:
                bad += 1
                continue
            code, event_id, date = fields[0].strip(), fields[2].strip(), fields[4].strip()
            if not event_id or event_id.lower() == "nan":
                continue
            amount = fields[17].strip() if len(fields) > 19 else ""
            currency = fields[19].strip().upper() if len(fields) > 19 else ""
            records.append((code, event_id, date, amount, currency))

    df = pd.DataFrame(records, columns=["stock_code", "event_id", "declare_date", "amount", "currency"])
    df["stock_code"] = _normalize_code(df["stock_code"])
    df["declare_date"] = pd.to_datetime(df["declare_date"], errors="coerce")
    df = df.dropna(subset=["stock_code", "event_id", "declare_date"])
    df = df[df["stock_code"].str[:3].isin(A_SHARE_PREFIXES)]
    df["amount"] = pd.to_numeric(
        df["amount"].str.replace(",", "", regex=False).replace({"": np.nan, "--": np.nan}),
        errors="coerce",
    )
    df = df.sort_values(["stock_code", "event_id", "declare_date"], kind="mergesort")
    first = df.drop_duplicates(["stock_code", "event_id"], keep="first").copy()
    first["year"] = first["declare_date"].dt.year.astype(int)
    first["is_cny"] = first["currency"].isin(CNY_CODES)
    print(f" LAW_lawsuit: {len(df):,} rows -> {len(first):,} first-announcement events (bad rows={bad})")
    return first


def _read_penalties() -> pd.DataFrame:
    path = INCOMING / "VIO_penalty_2013_2026.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing {path}")
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    df["stock_code"] = _normalize_code(df["stock_code"])
    df["year"] = pd.to_numeric(df["disposal_date"].astype(str).str[:4], errors="coerce")
    df = df[
        df["is_violated"].astype(str).str.strip().str.upper().eq("Y")
        & df["year"].between(YEAR_MIN, YEAR_MAX)
    ].copy()
    df["year"] = df["year"].astype(int)
    df["sum_penalty"] = pd.to_numeric(
        df["sum_penalty"].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    ).fillna(0.0)
    df = df.drop_duplicates(["stock_code", "year", "violation_id"])
    print(f" VIO_penalty: {len(df):,} unique violation events")
    return df


def build() -> pd.DataFrame:
    grid = _financial_grid()
    lawsuits = _read_lawsuits()
    penalties = _read_penalties()

    lawsuits = lawsuits[lawsuits["year"].between(YEAR_MIN, YEAR_MAX)]
    law_agg = (
        lawsuits.groupby(KEY)
        .agg(
            litigation_count=("event_id", "nunique"),
            lawsuit_amount_cny=("amount", lambda s: float(s[lawsuits.loc[s.index, "is_cny"]].sum())),
            non_cny_count=("is_cny", lambda s: int((~s.astype(bool)).sum())),
        )
        .reset_index()
    )
    pen_agg = (
        penalties.groupby(KEY)
        .agg(penalty_count=("violation_id", "nunique"), penalty_amount_sum=("sum_penalty", "sum"))
        .reset_index()
    )

    out = grid.merge(law_agg, on=KEY, how="left").merge(pen_agg, on=KEY, how="left")
    for col in ("litigation_count", "penalty_count", "non_cny_count", "lawsuit_amount_cny", "penalty_amount_sum"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in ("litigation_count", "penalty_count", "non_cny_count"):
        out[col] = out[col].fillna(0).astype(int)
    out["legal_event_count"] = out["litigation_count"] + out["penalty_count"]
    out["has_lawsuit"] = out["litigation_count"].gt(0).astype(int)
    out["has_penalty"] = out["penalty_count"].gt(0).astype(int)
    out["legal_available"] = 1
    out["litigation_definition"] = "first_announcement_year_unique_EventID"
    out["penalty_definition"] = "final_disposal_year_unique_ViolationID"
    out["legal_source"] = np.where(
        out["legal_event_count"].gt(0),
        "CSMAR.LA_DETAIL_first_announcement+STK_Violation_Main.disposal",
        "none_observed",
    )
    out = out.sort_values(KEY).reset_index(drop=True)
    out = out[
        [
            *KEY,
            "litigation_count",
            "lawsuit_amount_cny",
            "non_cny_count",
            "penalty_count",
            "penalty_amount_sum",
            "legal_event_count",
            "has_lawsuit",
            "has_penalty",
            "legal_available",
            "litigation_definition",
            "penalty_definition",
            "legal_source",
        ]
    ]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="重建 C 制造业公司-年司法/处罚事件表")
    parser.add_argument("--write", action="store_true", help="写入 data/raw/legal_events.csv")
    args = parser.parse_args()

    settings.ensure_dirs()
    out = build()
    print(f"legal grid: {len(out):,} rows, {out['stock_code'].nunique():,} companies")
    print(out.groupby("year")[["litigation_count", "penalty_count"]].sum().to_string())
    print(
        "event rows:",
        int(out["legal_event_count"].sum()),
        "| lawsuit:", int(out["litigation_count"].sum()),
        "| penalty:", int(out["penalty_count"].sum()),
    )
    if args.write:
        path = settings.RAW_LEGAL
        _backup(path)
        out.to_csv(path, index=False, encoding="utf-8-sig")
        summary = {
            "path": str(path),
            "rows": int(len(out)),
            "companies": int(out["stock_code"].nunique()),
            "years": [int(out["year"].min()), int(out["year"].max())],
            "litigation_sum": int(out["litigation_count"].sum()),
            "penalty_sum": int(out["penalty_count"].sum()),
            "litigation_definition": "first_announcement_year_unique_EventID",
            "penalty_definition": "final_disposal_year_unique_ViolationID",
            "industry_prefix": settings.MANUFACTURING_PREFIX,
        }
        profile = path.with_suffix(path.suffix + ".profile.json")
        profile.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote: {path}")
        print(f"wrote: {profile}")


if __name__ == "__main__":
    main()
