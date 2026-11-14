"""整理浏览器导出的两职合一、诉讼仲裁与法律风险公司-年表。

保留 CSMAR 原始字段名；仅做日期过滤、事件去重和公司-年聚合。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DUALITY_COLS = [
    "Symbol", "ShortName", "Enddate", "ConcurrentPosition", "Boardsize",
    "IndDirectorRatio", "Mngmhldn", "SupervisorSize", "ExecutivesNumber",
    "PropertyRightsNature", "ContrshrProportion",
]

LAW_COLS = [
    "Symbol", "ShortName", "EventID", "DeclareType", "DeclareDate",
    "EventSignDate", "LATypes", "Plaintiff", "PlaintiffToCo", "Defendant",
    "DefendantToCo", "CaseReason", "LAValue", "LACosts", "Currency",
    "TrlInstus", "LAStatus", "ExecutnStus", "ProfitImpact",
]


def prepare_duality(src: Path, dst: Path) -> pd.DataFrame:
    df = pd.read_csv(src, encoding="utf-8-sig", dtype=str, usecols=DUALITY_COLS)
    df["Enddate"] = df["Enddate"].fillna("").str.strip()
    df = df[df["Enddate"].str.match(DATE_RE)]
    df = df[df["Enddate"].str[:4].astype(int).between(2013, 2025)]
    df = df.drop_duplicates(["Symbol", "Enddate"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dst, index=False, encoding="utf-8-sig")
    return df


def prepare_lawsuit(src: Path, events_dst: Path, counts_dst: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(src, encoding="utf-8-sig", dtype=str, usecols=LAW_COLS, low_memory=False)
    df["DeclareDate"] = df["DeclareDate"].fillna("").str.strip()
    df = df[df["DeclareDate"].str.match(DATE_RE)]
    df = df[df["EventID"].notna() & df["EventID"].str.strip().ne("")]
    df = df[df["DeclareDate"].str[:4].astype(int).between(2013, 2026)]
    # 同一事件可能多次公告：保留最后一次公告，避免重复计数。
    df = df.sort_values(["EventID", "DeclareDate"]).drop_duplicates("EventID", keep="last")
    events_dst.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(events_dst, index=False, encoding="utf-8-sig")

    work = df.copy()
    work["year"] = work["DeclareDate"].str[:4].astype(int)
    work["amount_num"] = pd.to_numeric(
        work["LAValue"].fillna("").str.replace(",", "", regex=False), errors="coerce"
    )
    work["is_cny"] = work["Currency"].fillna("").str.upper().eq("CNY")
    work["amount_cny"] = work["amount_num"].where(work["is_cny"])
    work["non_cny_flag"] = (~work["is_cny"]).astype(int)
    grouped = work.groupby(["Symbol", "year"], as_index=False).agg(
        litigation_count=("EventID", "nunique"),
        lawsuit_amount_cny=("amount_cny", "sum"),
        non_cny_count=("non_cny_flag", "sum"),
    )
    counts_dst.parent.mkdir(parents=True, exist_ok=True)
    grouped.to_csv(counts_dst, index=False, encoding="utf-8-sig")
    return df, grouped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duality", required=True)
    parser.add_argument("--lawsuit", required=True)
    parser.add_argument("--outdir", required=True)
    args = parser.parse_args()
    out = Path(args.outdir)
    d = prepare_duality(Path(args.duality), out / "CG_duality_2013_2025.csv")
    e, c = prepare_lawsuit(
        Path(args.lawsuit), out / "LAW_lawsuit_2013_2026.csv",
        out / "LAW_lawsuit_counts_2013_2026.csv",
    )
    print(f"duality: {d.shape}, companies={d.Symbol.nunique()}")
    print(f"lawsuit events: {e.shape}, companies={e.Symbol.nunique()}")
    print(f"lawsuit counts: {c.shape}, events={int(c.litigation_count.sum())}")


if __name__ == "__main__":
    main()
