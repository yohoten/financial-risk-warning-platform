"""数据查缺审计：表清点、年份覆盖、主键、标签口径、特征可用性。

输出（全部可复现）：
    reports/data_quality/data_gap_audit_20261114.json
    reports/data_quality/tables_inventory_20261114.csv
    reports/data_quality/year_coverage_20261114.csv
    reports/data_quality/feature_readiness_20261114.csv
    reports/data_quality/financial_field_coverage_20261114.csv
    reports/data_quality/governance_year_coverage_20261114.csv
    reports/data_quality/legal_year_coverage_20261114.csv

运行：
    python -m scripts.audit_data_gap
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import feature_registry as fr
from config import settings

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CAND = RAW / "candidates"
INCOMING = ROOT / "data" / "incoming" / "csmar"
EXT = ROOT / "data" / "external"
OUT = ROOT / "reports" / "data_quality"
OUT.mkdir(parents=True, exist_ok=True)

KEY = ["stock_code", "year"]
A_SHARE_PREFIXES = {"000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688", "689"}


def code(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.extract(r"(\d{1,6})", expand=False)
        .str.zfill(6)
    )


def read(path: Path, **kwargs) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", low_memory=False, **kwargs)


def write(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT / name, index=False, encoding="utf-8-sig")


def inventory_entry(name: str, path: Path, df: pd.DataFrame, key=KEY, note: str = "") -> dict:
    entry = {
        "table": name,
        "path": path.relative_to(ROOT).as_posix(),
        "rows": int(len(df)),
        "columns": int(df.shape[1]),
        "note": note,
    }
    if "stock_code" in df.columns:
        c = code(df["stock_code"])
        entry["companies"] = int(c.nunique())
        entry["invalid_code_rows"] = int((~c.str.fullmatch(r"\d{6}")).sum())
        entry["a_share_rows"] = int(c.str[:3].isin(A_SHARE_PREFIXES).sum())
    if "year" in df.columns:
        y = pd.to_numeric(df["year"], errors="coerce")
        entry["year_min"] = int(y.min()) if y.notna().any() else None
        entry["year_max"] = int(y.max()) if y.notna().any() else None
        entry["invalid_year_rows"] = int(y.isna().sum())
    if all(k in df.columns for k in key):
        entry["duplicate_keys"] = int(df.duplicated(list(key)).sum())
    return entry


def main() -> None:
    fin = read(RAW / "csmar_financial.csv", dtype={"stock_code": str})
    fin["stock_code"] = code(fin["stock_code"])
    fin["year"] = pd.to_numeric(fin["year"], errors="coerce")
    fin = fin.dropna(subset=KEY).copy()
    fin["year"] = fin["year"].astype(int)
    fin_keys = fin[KEY].drop_duplicates()
    fin_a_keys = fin_keys[fin_keys["stock_code"].str[:3].isin(A_SHARE_PREFIXES)]

    gov = read(RAW / "csmar_governance.csv", dtype={"stock_code": str})
    gov["stock_code"] = code(gov["stock_code"])
    gov["year"] = pd.to_numeric(gov["year"], errors="coerce")
    gov = gov.dropna(subset=KEY).copy()
    gov["year"] = gov["year"].astype(int)

    # 行情契约表（TRD 小数口径）；审计列为可空整型，读回不应退化为 float。
    market_path = RAW / settings.RAW_MARKET.name
    market = read(market_path, dtype={"stock_code": str, "audit_opinion": "Int8", "big4_audit": "Int8"})
    market["stock_code"] = code(market["stock_code"])
    market["year"] = pd.to_numeric(market["year"], errors="coerce")
    market = market.dropna(subset=KEY).copy()
    market["year"] = market["year"].astype(int)

    # 遗留百分数表已归档，仅用于单位对照，不再作为契约读取。
    legacy_market_path = RAW / "market_features_legacy_percent.csv"
    legacy_market = None
    if legacy_market_path.exists():
        legacy_market = read(legacy_market_path, dtype={"stock_code": str})
        legacy_market["stock_code"] = code(legacy_market["stock_code"])
        legacy_market["year"] = pd.to_numeric(legacy_market["year"], errors="coerce")
        legacy_market = legacy_market.dropna(subset=KEY).copy()
        legacy_market["year"] = legacy_market["year"].astype(int)

    # 日行情聚合候选：与契约表同源，用于覆盖率与 2026 部分年度检查。
    trd = read(CAND / "TRD_Dly_company_year_2013_2026.csv", dtype={"Stkcd": str})
    trd["stock_code"] = code(trd["Stkcd"])
    trd["year"] = pd.to_numeric(trd["year"], errors="coerce")
    trd = trd.dropna(subset=KEY).copy()
    trd["year"] = trd["year"].astype(int)
    for col in ["trading_days", "annual_turnover", "stock_volatility", "annual_return"]:
        trd[col] = pd.to_numeric(trd[col], errors="coerce")

    labels_proxy = read(RAW / "labels_st.csv", dtype={"stock_code": str})
    labels_official = read(CAND / "labels_st_official.csv", dtype={"stock_code": str})
    for frame in (labels_proxy, labels_official):
        frame["stock_code"] = code(frame["stock_code"])
        frame["year"] = pd.to_numeric(frame["year"], errors="coerce")
        frame["is_st"] = pd.to_numeric(frame["is_st"], errors="coerce")
    labels_proxy = labels_proxy.dropna(subset=[*KEY, "is_st"]).copy()
    labels_official = labels_official.dropna(subset=[*KEY, "is_st"]).copy()
    labels_proxy["year"] = labels_proxy["year"].astype(int)
    labels_official["year"] = labels_official["year"].astype(int)

    gov_ext = read(CAND / "governance_ext.csv", dtype={"stock_code": str})
    gov_ext["stock_code"] = code(gov_ext["stock_code"])
    gov_ext["year"] = pd.to_numeric(gov_ext["year"], errors="coerce")
    gov_ext = gov_ext.dropna(subset=KEY).copy()
    gov_ext["year"] = gov_ext["year"].astype(int)

    legal = read(CAND / "legal_events.csv", dtype={"stock_code": str})
    legal["stock_code"] = code(legal["stock_code"])
    legal["year"] = pd.to_numeric(legal["year"], errors="coerce")
    legal = legal.dropna(subset=KEY).copy()
    legal["year"] = legal["year"].astype(int)
    for col in ["litigation_count", "penalty_count", "lawsuit_amount_cny",
                "penalty_amount_sum", "non_cny_count", "legal_event_count"]:
        legal[col] = pd.to_numeric(legal[col], errors="coerce")

    # ---------------------------------------------------------------- 表清点
    tables = [
        inventory_entry("财务主表", RAW / "csmar_financial.csv", fin, note="A 股公司-年，金额亿元"),
        inventory_entry("治理主表", RAW / "csmar_governance.csv", gov,
                        note=f"当前在线契约；duality 非空 {int(gov['duality'].notna().sum()):,}/{len(gov):,}" if "duality" in gov else "当前在线契约"),
        inventory_entry("审计/市场表（契约）", market_path, market,
                        note="审计意见/费用 + TRD 小数换手率；审计列为 Int8"),
        *([inventory_entry("行情遗留表（归档）", legacy_market_path, legacy_market,
                           note="百分数口径（约100×），仅作单位对照，不再读取")] if legacy_market is not None else []),
        inventory_entry("日行情公司-年（候选）", CAND / "TRD_Dly_company_year_2013_2026.csv", trd,
                        note="2013–2026 日行情聚合，与契约表同源"),
        inventory_entry("ST 在线标签", RAW / "labels_st.csv", labels_proxy, note="当前在线标签；本轮已与官方候选一致"),
        inventory_entry("ST 官方标签（候选）", CAND / "labels_st_official.csv", labels_official, note="未替换在线标签"),
        inventory_entry("治理增量（候选）", CAND / "governance_ext.csv", gov_ext, note="两职合一/董事会/管理层"),
        inventory_entry("诉讼处罚（候选）", CAND / "legal_events.csv", legal, note="公司-年，无事件补 0"),
    ]
    write(pd.DataFrame(tables), "tables_inventory_20261114.csv")

    # ------------------------------------------------------------ 年度覆盖
    cov = fin.groupby("year").size().rename("financial_rows").to_frame()
    cov["financial_companies"] = fin.groupby("year")["stock_code"].nunique()
    for name, frame in [("proxy", labels_proxy), ("official", labels_official)]:
        g = frame.groupby("year")["is_st"].agg(["size", "sum"])
        g.columns = [f"labels_{name}", f"st_{name}"]
        cov = cov.join(g, how="outer")
    for col in ["labels_proxy", "st_proxy", "labels_official", "st_official"]:
        cov[col] = cov[col].fillna(0).astype(int)
    cov["st_rate_proxy"] = cov["st_proxy"] / cov["labels_proxy"].replace(0, pd.NA)
    cov["st_rate_official"] = cov["st_official"] / cov["labels_official"].replace(0, pd.NA)
    cov = cov.reset_index()

    # 首次 ST：上一年同公司存在且为 0
    for name, frame in [("proxy", labels_proxy), ("official", labels_official)]:
        f = frame.sort_values(["stock_code", "year"]).copy()
        f["prev_year"] = f.groupby("stock_code")["year"].shift(1)
        f["prev_st"] = f.groupby("stock_code")["is_st"].shift(1)
        f["first"] = (
            f["is_st"].eq(1)
            & f["prev_year"].eq(f["year"] - 1)
            & f["prev_st"].eq(0)
        )
        first = f.groupby("year")["first"].sum().rename(f"first_st_{name}")
        cov = cov.merge(first, left_on="year", right_index=True, how="left")
        cov[f"first_st_{name}"] = cov[f"first_st_{name}"].fillna(0).astype(int)
    write(cov, "year_coverage_20261114.csv")

    # 标签一致性
    lab = labels_official.merge(
        labels_proxy, on=KEY, how="outer", suffixes=("_official", "_proxy"), indicator=True
    )
    both = lab[lab["_merge"].eq("both")]
    agreement = {
        "overlap_company_years": int(len(both)),
        "agreement_rows": int((both["is_st_official"] == both["is_st_proxy"]).sum()),
        "agreement_rate": float((both["is_st_official"] == both["is_st_proxy"]).mean()),
        "official_only_positive": int(((both["is_st_official"] == 1) & (both["is_st_proxy"] == 0)).sum()),
        "proxy_only_positive": int(((both["is_st_official"] == 0) & (both["is_st_proxy"] == 1)).sum()),
        "official_only_keys": int(lab["_merge"].eq("left_only").sum()),
        "proxy_only_keys": int(lab["_merge"].eq("right_only").sum()),
    }

    # ------------------------------------------------------------ 财务字段
    fin_cov = []
    for col in fin.columns:
        s = fin[col]
        fin_cov.append({
            "field": col,
            "non_null_rate": float(s.notna().mean()),
            "nonzero_rate": float((pd.to_numeric(s, errors="coerce").fillna(0) != 0).mean())
            if pd.api.types.is_numeric_dtype(s) else None,
            "n_unique": int(s.nunique(dropna=True)),
        })
    fin_cov = pd.DataFrame(fin_cov).sort_values("non_null_rate")
    write(fin_cov, "financial_field_coverage_20261114.csv")

    # ------------------------------------------------------------ 治理覆盖
    g = gov_ext.groupby("year").agg(
        rows=("stock_code", "size"),
        companies=("stock_code", "nunique"),
        duality_nonnull=("duality", "count"),
        duality_rate=("duality", "mean"),
        board_size_nonnull=("board_size_cg", "count"),
        independent_nonnull=("independent_ratio_cg", "count"),
        management_nonnull=("management_holding_cg", "count"),
        control_nonnull=("control_proportion", "count"),
    ).reset_index()
    g["duality_coverage"] = g["duality_nonnull"] / g["rows"]
    write(g, "governance_year_coverage_20261114.csv")

    gov_active = {
        "rows": int(len(gov)),
        "duality_nonnull": int(gov["duality"].notna().sum()) if "duality" in gov else 0,
        "board_size_nonnull_rate": float(gov["board_size"].notna().mean()) if "board_size" in gov else None,
        "independent_nonnull_rate": float(gov["independent_directors"].notna().mean()) if "independent_directors" in gov else None,
        "top1_nonnull_rate": float(gov["top1_holding"].notna().mean()) if "top1_holding" in gov else None,
        "management_nonnull_rate": float(gov["management_holding"].notna().mean()) if "management_holding" in gov else None,
    }

    # ------------------------------------------------------------ 司法覆盖
    lg = legal.groupby("year").agg(
        rows=("stock_code", "size"),
        companies=("stock_code", "nunique"),
        lawsuit_company_years=("has_lawsuit", "sum"),
        penalty_company_years=("has_penalty", "sum"),
        lawsuits=("litigation_count", "sum"),
        penalties=("penalty_count", "sum"),
        lawsuit_amount_cny=("lawsuit_amount_cny", "sum"),
        non_cny_count=("non_cny_count", "sum"),
    ).reset_index()
    lg["lawsuit_prevalence"] = lg["lawsuit_company_years"] / lg["rows"]
    lg["penalty_prevalence"] = lg["penalty_company_years"] / lg["rows"]
    write(lg, "legal_year_coverage_20261114.csv")

    # ------------------------------------------------ 候选特征与标签关联
    def st_rate_table(base: pd.DataFrame, feature: str, target: str = "is_st") -> list[dict]:
        d = base.dropna(subset=[feature, target]).copy()
        d["bin"] = pd.to_numeric(d[feature], errors="coerce")
        d = d.dropna(subset=["bin"])
        d["bin"] = d["bin"].astype(int).clip(lower=0, upper=1) if d["bin"].nunique() <= 2 else d["bin"]
        out = []
        for value, part in d.groupby("bin"):
            out.append({
                "feature": feature,
                "value": int(value) if float(value).is_integer() else float(value),
                "n": int(len(part)),
                "st_positive": int(part[target].sum()),
                "st_rate": float(part[target].mean()),
            })
        return out

    # 同年关联
    base_same = (
        legal.merge(labels_official, on=KEY, how="left")
        .merge(gov_ext[["stock_code", "year", "duality"]], on=KEY, how="left")
    )
    assoc = []
    for feature in ["has_lawsuit", "has_penalty", "duality"]:
        assoc += [{"horizon": "same_year", **r} for r in st_rate_table(base_same, feature)]

    # T+2 关联：特征年 T，标签年 T+2
    fut = labels_official.copy()
    fut["year"] = fut["year"] - 2
    fut = fut.rename(columns={"is_st": "is_st_t2"})
    base_t2 = (
        legal.merge(fut[["stock_code", "year", "is_st_t2"]], on=KEY, how="left")
        .merge(gov_ext[["stock_code", "year", "duality"]], on=KEY, how="left")
    )
    for feature in ["has_lawsuit", "has_penalty", "duality"]:
        assoc += [{"horizon": "t_plus_2", **r} for r in st_rate_table(base_t2, feature, "is_st_t2")]
    assoc_df = pd.DataFrame(assoc)
    write(assoc_df, "candidate_feature_association_20261114.csv")

    # ------------------------------------------------------------ 特征面板
    # 优先 parquet（流水线唯一产物）；CSV 可能来自旧版本，仅作兜底
    panel_pq = ROOT / "data" / "feature_store" / "panel_features.parquet"
    panel_path = ROOT / "data" / "feature_store" / "panel_features.csv"
    selected = json.loads((ROOT / "data" / "feature_store" / "selected_features.json").read_text(encoding="utf-8"))
    selected_set = set(selected.get("features", []))
    if panel_pq.exists():
        panel = pd.read_parquet(panel_pq)
    elif panel_path.exists():
        panel = read(panel_path, dtype={"stock_code": str})
    else:
        panel = pd.DataFrame()
    ids = ["stock_code", "year", "company_name", "industry", "is_st", "total_assets", "revenue", "net_profit", "ocf"]
    feature_cols = [c for c in panel.columns if c not in ids] if not panel.empty else fr.FEATURE_KEYS
    rows = []
    for col in feature_cols:
        s = panel[col] if col in panel else pd.Series(dtype=float)
        rows.append({
            "feature": col,
            "group": fr.FEATURE_MAP[col].group if col in fr.FEATURE_MAP else "unknown",
            "selected": col in selected_set,
            "non_null_rate": float(s.notna().mean()) if len(s) else 0.0,
            "nonzero_rate": float((s.fillna(0) != 0).mean()) if len(s) else 0.0,
            "std": float(pd.to_numeric(s, errors="coerce").std()) if len(s) else 0.0,
            "all_zero": bool(len(s) > 0 and (pd.to_numeric(s, errors="coerce").fillna(0) == 0).all()),
        })
    readiness = pd.DataFrame(rows)
    write(readiness, "feature_readiness_20261114.csv")

    group_summary = (
        readiness.groupby("group")
        .agg(features=("feature", "size"), all_zero=("all_zero", "sum"), selected=("selected", "sum"))
        .reset_index()
        .to_dict("records")
    )
    all_zero = readiness[readiness["all_zero"]]["feature"].tolist()

    # ------------------------------------------------------------ 宏观/文本/行情
    macro = read(EXT / "macro_industry.csv")
    macro_cov = {
        "rows": int(len(macro)),
        "year_min": int(macro["year"].min()),
        "year_max": int(macro["year"].max()),
        "non_null_rate": {c: float(macro[c].notna().mean()) for c in macro.columns if c != "year"},
    }
    text_path = RAW / "text_sentiment.csv"
    text_status = {
        "exists": text_path.exists(),
        "rows": int(len(read(text_path))) if text_path.exists() else 0,
        "status": "missing_no_permission" if not text_path.exists() else "available",
    }
    trd_fin_keys = trd[trd["year"].between(2013, 2025)].merge(fin_a_keys, on=KEY, how="inner")
    trd_2026 = trd[trd["year"].eq(2026)]
    contract_turnover_median = float(pd.to_numeric(market["annual_turnover"], errors="coerce").median()) if "annual_turnover" in market else None
    legacy_turnover_median = float(pd.to_numeric(legacy_market["annual_turnover"], errors="coerce").median()) if legacy_market is not None else None
    market_cov = {
        "path": market_path.relative_to(ROOT).as_posix(),
        "rows": int(len(market)),
        "annual_turnover_nonnull": float(market["annual_turnover"].notna().mean()) if "annual_turnover" in market else 0.0,
        "stock_volatility_nonnull": float(market["stock_volatility"].notna().mean()) if "stock_volatility" in market else 0.0,
        "audit_opinion_nonnull": float(market["audit_opinion"].notna().mean()) if "audit_opinion" in market else 0.0,
        "audit_opinion_nonzero": float((pd.to_numeric(market["audit_opinion"], errors="coerce").fillna(0) != 0).mean()) if "audit_opinion" in market else 0.0,
        "audit_opinion_dtype": str(market["audit_opinion"].dtype) if "audit_opinion" in market else None,
        "contract_turnover_median": contract_turnover_median,
        "legacy_turnover_median": legacy_turnover_median,
        "legacy_to_contract_ratio": float(contract_turnover_median / legacy_turnover_median)
        if contract_turnover_median and legacy_turnover_median else None,
        "unit_note": "契约表为 decimal turns/year；遗留表已归档为百分数口径（约100×）",
        "candidate": {
            "rows": int(len(trd)),
            "companies": int(trd["stock_code"].nunique()),
            "year_min": int(trd["year"].min()),
            "year_max": int(trd["year"].max()),
            "annual_turnover_nonnull": float(trd["annual_turnover"].notna().mean()),
            "stock_volatility_nonnull": float(trd["stock_volatility"].notna().mean()),
            "financial_key_coverage_2013_2025": float(len(trd_fin_keys) / len(fin_a_keys)),
            "rows_2026": int(len(trd_2026)),
            "trading_days_2026_median": float(trd_2026["trading_days"].median()) if len(trd_2026) else None,
            "note": "2026 仅至 9-30，部分年度；面板已按契约小数口径构建（缩尾后差异仅出现在边界）",
        },
    }

    # ------------------------------------------------------------ 锁箱约束
    lockbox = {
        "lockbox_feature_year": 2024,
        "financial_keys_2024": int(fin["year"].eq(2024).sum()),
        "official_labels_2024": int(labels_official["year"].eq(2024).sum()),
        "official_positive_2024": int(labels_official.loc[labels_official["year"].eq(2024), "is_st"].sum()),
        "official_labels_2026": int(labels_official["year"].eq(2026).sum()),
        "feature_panel_max_year": int(panel["year"].max()) if not panel.empty else None,
        "blocked_reason": "2024 特征年需要 2026 标签；财务主表与官方标签均止于 2025 公司-年键",
    }

    # ------------------------------------------------------------ 现金流修正
    cashflow_fix = None
    cf_path = OUT / "cashflow_fix_20261114.json"
    if cf_path.exists():
        cashflow_fix = json.loads(cf_path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------ 汇总
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tables": tables,
        "labels": {
            "proxy_rows": int(len(labels_proxy)),
            "proxy_positive": int(labels_proxy["is_st"].sum()),
            "proxy_rate": float(labels_proxy["is_st"].mean()),
            "official_rows": int(len(labels_official)),
            "official_positive": int(labels_official["is_st"].sum()),
            "official_rate": float(labels_official["is_st"].mean()),
            "agreement": agreement,
        },
        "financial": {
            "rows": int(len(fin)),
            "companies": int(fin["stock_code"].nunique()),
            "year_min": int(fin["year"].min()),
            "year_max": int(fin["year"].max()),
            "columns": int(fin.shape[1]),
            "industry_missing": int(fin["industry"].isna().sum()) if "industry" in fin else None,
            "industry_unique": int(fin["industry"].nunique()) if "industry" in fin else None,
        },
        "governance_active": gov_active,
        "governance_candidate": {
            "rows": int(len(gov_ext)),
            "companies": int(gov_ext["stock_code"].nunique()),
            "duality_nonnull": int(gov_ext["duality"].notna().sum()),
            "duality_rate": float(gov_ext["duality"].mean()),
            "duality_coverage": float(gov_ext["duality"].notna().mean()),
        },
        "legal_candidate": {
            "rows": int(len(legal)),
            "companies": int(legal["stock_code"].nunique()),
            "lawsuits": int(legal["litigation_count"].sum()),
            "penalties": int(legal["penalty_count"].sum()),
            "lawsuit_company_years": int(legal["has_lawsuit"].sum()),
            "penalty_company_years": int(legal["has_penalty"].sum()),
            "both_company_years": int(((legal["has_lawsuit"] == 1) & (legal["has_penalty"] == 1)).sum()),
            "coverage_of_a_share_financial_keys_2013_2025": float(
                legal[legal["year"].between(2013, 2025)].merge(fin_a_keys, on=KEY, how="inner").shape[0]
                / len(fin_a_keys)
            ),
            "coverage_of_all_financial_keys_2013_2025": float(
                legal[legal["year"].between(2013, 2025)].merge(fin_keys, on=KEY, how="inner").shape[0]
                / len(fin_keys)
            ),
        },
        "feature_panel": {
            "rows": int(len(panel)),
            "year_min": int(panel["year"].min()) if not panel.empty else None,
            "year_max": int(panel["year"].max()) if not panel.empty else None,
            "positive": int(panel["is_st"].sum()) if not panel.empty else None,
            "positive_rate": float(panel["is_st"].mean()) if not panel.empty else None,
            "features": int(len(feature_cols)),
            "selected": int(len(selected_set)),
            "all_zero_count": int(len(all_zero)),
            "all_zero_features": all_zero,
            "group_summary": group_summary,
        },
        "macro": macro_cov,
        "text": text_status,
        "market": market_cov,
        "lockbox": lockbox,
        "cashflow_fix": cashflow_fix,
        "association": assoc,
    }
    (OUT / "data_gap_audit_20261114.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "financial": result["financial"],
        "labels": result["labels"],
        "governance_candidate": result["governance_candidate"],
        "legal_candidate": result["legal_candidate"],
        "feature_panel": result["feature_panel"],
        "lockbox": result["lockbox"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
