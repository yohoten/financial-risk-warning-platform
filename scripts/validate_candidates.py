"""校验 data/raw/candidates 的候选表；不修改任何数据。

运行：
    python -m scripts.validate_candidates
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CAND = ROOT / "data" / "raw" / "candidates"
RAW = ROOT / "data" / "raw"
OUT = ROOT / "reports" / "data_quality"
KEY = ["stock_code", "year"]


def code(series: pd.Series) -> pd.Series:
    return (
        series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
        .str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    )


def check_key(df: pd.DataFrame, key: list[str], name: str) -> dict:
    nulls = int(df[key].isna().any(axis=1).sum())
    dup = int(df.duplicated(key).sum())
    return {"table": name, "key": key, "rows": int(len(df)), "key_nulls": nulls, "duplicate_keys": dup,
            "passed": nulls == 0 and dup == 0}


def main() -> None:
    checks = []

    # 官方 ST 事件
    st = pd.read_csv(CAND / "ST_events_official.csv", encoding="utf-8-sig", dtype=str)
    c0, c2, c4 = st.columns[0], st.columns[2], st.columns[4]
    start = pd.to_datetime(st[c2], errors="coerce")
    end = pd.to_datetime(st[c4], errors="coerce")
    checks.append({
        "table": "ST_events_official.csv", "rows": int(len(st)),
        "companies": int(code(st[c0]).nunique()),
        "invalid_codes": int((~code(st[c0]).str.fullmatch(r"\d{6}")).sum()),
        "invalid_start_dates": int(start.isna().sum()),
        "end_before_start": int(((end.notna()) & (start.notna()) & (end < start)).sum()),
        "passed": bool(code(st[c0]).str.fullmatch(r"\d{6}").all() and start.notna().all()
                       and not ((end.notna()) & (start.notna()) & (end < start)).any()),
    })

    # 官方标签
    lab = pd.read_csv(CAND / "labels_st_official.csv", encoding="utf-8-sig",
                      dtype={"stock_code": str, "year": str})
    lab["stock_code"] = code(lab["stock_code"])
    lab["year"] = pd.to_numeric(lab["year"], errors="coerce")
    lab["is_st"] = pd.to_numeric(lab["is_st"], errors="coerce")
    checks.append({
        **check_key(lab, KEY, "labels_st_official.csv"),
        "years": [int(lab["year"].min()), int(lab["year"].max())],
        "positive": int(lab["is_st"].sum()),
        "invalid_binary": int((~lab["is_st"].isin([0, 1])).sum()),
        "invalid_years": int(lab["year"].isna().sum()),
    })

    # 两职合一紧凑表
    dual = pd.read_csv(CAND / "CG_duality_2013_2025.csv", encoding="utf-8-sig", dtype=str)
    dual["Symbol"] = code(dual["Symbol"])
    dual["Enddate"] = dual["Enddate"].astype(str)
    dual["duality"] = pd.to_numeric(dual["ConcurrentPosition"], errors="coerce")
    checks.append({
        "table": "CG_duality_2013_2025.csv", "rows": int(len(dual)),
        "companies": int(dual["Symbol"].nunique()),
        "duplicate_symbol_enddate": int(dual.duplicated(["Symbol", "Enddate"]).sum()),
        "invalid_duality": int((~dual["duality"].isin([0, 1]) & dual["duality"].notna()).sum()),
        "duality_missing": int(dual["duality"].isna().sum()),
        "years": [int(dual["Enddate"].str[:4].min()), int(dual["Enddate"].str[:4].max())],
        "passed": True,
    })

    # 治理增量契约
    gov = pd.read_csv(CAND / "governance_ext.csv", encoding="utf-8-sig", dtype=str)
    gov["stock_code"] = code(gov["stock_code"])
    gov["year"] = pd.to_numeric(gov["year"], errors="coerce")
    for c in ["duality", "board_size_cg", "independent_ratio_cg", "management_holding_cg",
              "supervisor_size", "executives_number", "ownership_nature", "control_proportion"]:
        gov[c] = pd.to_numeric(gov[c], errors="coerce")
    checks.append({
        **check_key(gov, KEY, "governance_ext.csv"),
        "duality_missing": int(gov["duality"].isna().sum()),
        "invalid_duality": int((~gov["duality"].isin([0, 1]) & gov["duality"].notna()).sum()),
        "independent_ratio_out_of_range": int((~gov["independent_ratio_cg"].between(0, 1) &
                                               gov["independent_ratio_cg"].notna()).sum()),
        "management_holding_out_of_range": int((~gov["management_holding_cg"].between(0, 1) &
                                                gov["management_holding_cg"].notna()).sum()),
        "board_size_out_of_range": int((~gov["board_size_cg"].between(1, 30) &
                                        gov["board_size_cg"].notna()).sum()),
    })

    # 诉讼处罚契约
    legal = pd.read_csv(CAND / "legal_events.csv", encoding="utf-8-sig", dtype=str)
    legal["stock_code"] = code(legal["stock_code"])
    legal["year"] = pd.to_numeric(legal["year"], errors="coerce")
    for c in ["litigation_count", "penalty_count", "non_cny_count", "legal_event_count",
              "has_lawsuit", "has_penalty"]:
        legal[c] = pd.to_numeric(legal[c], errors="coerce")
    legal_check = {
        **check_key(legal, KEY, "legal_events.csv"),
        "years": [int(legal["year"].min()), int(legal["year"].max())],
        "lawsuits": int(legal["litigation_count"].sum()),
        "penalties": int(legal["penalty_count"].sum()),
        "negative_counts": int(((legal[["litigation_count", "penalty_count", "non_cny_count"]] < 0).any(axis=1)).sum()),
        "invalid_flags": int((~legal[["has_lawsuit", "has_penalty"]].isin([0, 1])).any(axis=1).sum()),
        "rows_2026": int(legal["year"].eq(2026).sum()),
    }
    checks.append(legal_check)

    # 修正现金流候选表
    fixed = pd.read_csv(CAND / "csmar_financial_cashflow_fixed.csv", encoding="utf-8-sig",
                        dtype={"stock_code": str})
    fixed["stock_code"] = code(fixed["stock_code"])
    fixed["year"] = pd.to_numeric(fixed["year"], errors="coerce")
    cf = ["ocf", "icf", "fcf_financing", "capex"]
    checks.append({
        **check_key(fixed, KEY, "csmar_financial_cashflow_fixed.csv"),
        "cashflow_median": {c: float(pd.to_numeric(fixed[c], errors="coerce").median()) for c in cf},
        "cashflow_missing_rate": {c: float(fixed[c].isna().mean()) for c in cf},
        "extreme_abs_gt_1e6": int((fixed[cf].abs() > 1e6).any(axis=1).sum()),
    })

    # 日行情公司-年候选：2013–2026 全字段重导后的聚合表
    trd = pd.read_csv(CAND / "TRD_Dly_company_year_2013_2026.csv", encoding="utf-8-sig",
                      dtype={"Stkcd": str})
    trd["stock_code"] = code(trd["Stkcd"])
    trd["year"] = pd.to_numeric(trd["year"], errors="coerce")
    for c in ["trading_days", "annual_turnover", "stock_volatility", "annual_return"]:
        trd[c] = pd.to_numeric(trd[c], errors="coerce")
    trd_2026 = trd[trd["year"].eq(2026)]
    trd_check = {
        **check_key(trd, KEY, "TRD_Dly_company_year_2013_2026.csv"),
        "companies": int(trd["stock_code"].nunique()),
        "years": [int(trd["year"].min()), int(trd["year"].max())],
        "annual_turnover_missing": int(trd["annual_turnover"].isna().sum()),
        "stock_volatility_missing": int(trd["stock_volatility"].isna().sum()),
        "annual_turnover_median": float(trd["annual_turnover"].median()),
        "stock_volatility_median": float(trd["stock_volatility"].median()),
        "rows_2026": int(len(trd_2026)),
        "trading_days_2026_median": float(trd_2026["trading_days"].median()) if len(trd_2026) else None,
    }
    trd_check["passed"] = bool(
        trd_check["passed"]
        and trd_check["years"] == [2013, 2026]
        and trd_check["annual_turnover_missing"] == 0
        and 0 < trd_check["annual_turnover_median"] < 100
        and trd_check["trading_days_2026_median"] is not None
        and trd_check["trading_days_2026_median"] < 250
    )
    checks.append(trd_check)

    # 2013–2025 A 股键覆盖：与在线财务表对齐
    fin = pd.read_csv(RAW / "csmar_financial.csv", encoding="utf-8-sig",
                      dtype={"stock_code": str}, usecols=["stock_code", "year"])
    fin["stock_code"] = code(fin["stock_code"])
    fin["year"] = pd.to_numeric(fin["year"], errors="coerce")
    a_prefixes = {"000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688", "689"}
    fin = fin[fin["stock_code"].str[:3].isin(a_prefixes) & fin["year"].between(2013, 2025)]
    legal_keys = legal[legal["year"].between(2013, 2025)][KEY].drop_duplicates()
    fin_keys = fin[KEY].drop_duplicates()
    missing = fin_keys.merge(legal_keys, on=KEY, how="left", indicator=True)
    legal_check["legal_missing_financial_keys"] = int(missing["_merge"].eq("left_only").sum())
    legal_check["passed"] = bool(legal_check["passed"] and legal_check["legal_missing_financial_keys"] == 0)

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "candidate_dir": CAND.relative_to(ROOT).as_posix(),
        "checks": checks,
        "all_passed": all(c.get("passed", True) and c.get("key_nulls", 0) == 0 and c.get("duplicate_keys", 0) == 0
                          for c in checks),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "candidate_validation_20261114.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
