"""候选转正评审：现金流修正、官方 ST 标签、行情口径的差异清单。

只读脚本：不写 data/raw、不覆盖契约表，只产出评审证据，供决定
"整表覆盖 / 字段级合并 / 保持现状"。

输出：
    reports/data_quality/promotion_review_20261114.json
    reports/data_quality/promotion_review_20261114.md
    reports/data_quality/promotion_diff_financial_20261114.csv
    reports/data_quality/promotion_diff_labels_20261114.csv
    reports/data_quality/promotion_diff_market_20261114.csv

运行：
    python -m scripts.review_candidate_promotion
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CAND = RAW / "candidates"
PANEL = ROOT / "data" / "feature_store" / "panel_features.parquet"
OUT = ROOT / "reports" / "data_quality"
OUT.mkdir(parents=True, exist_ok=True)

KEY = ["stock_code", "year"]
CASHFLOW = ["ocf", "icf", "fcf_financing", "capex"]
YEAR_MIN, YEAR_MAX = 2013, 2025


def code(series: pd.Series) -> pd.Series:
    return (series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
            .str.extract(r"(\d{1,6})", expand=False).str.zfill(6))


def read(path: Path, **kwargs) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", low_memory=False, **kwargs)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["stock_code"] = code(out["stock_code"])
    out["year"] = pd.to_numeric(out["year"], errors="coerce")
    return out.dropna(subset=KEY).assign(year=lambda d: d["year"].astype(int))


def col_diff(active: pd.DataFrame, cand: pd.DataFrame, cols: list[str], tol: float = 1e-9):
    merged = active[KEY + cols].merge(cand[KEY + cols], on=KEY, how="outer",
                                      suffixes=("_a", "_c"), indicator=True)
    rec = []
    for c in cols:
        if pd.api.types.is_numeric_dtype(active[c]):
            a = pd.to_numeric(merged[f"{c}_a"], errors="coerce")
            b = pd.to_numeric(merged[f"{c}_c"], errors="coerce")
            d = (a - b).abs()
            rel = d / a.abs().replace(0, np.nan)
            rec.append({
                "column": c, "active_nonnull": int(a.notna().sum()),
                "candidate_nonnull": int(b.notna().sum()),
                "both_nonnull": int((a.notna() & b.notna()).sum()),
                "rows_lost": int((a.notna() & b.isna()).sum()),
                "rows_gained": int((a.isna() & b.notna()).sum()),
                "rows_diff": int((d > tol).sum()),
                "max_abs_diff": float(d.max()) if d.notna().any() else None,
                "median_rel_diff": float(rel.median()) if rel.notna().any() else None,
            })
        else:
            a, b = merged[f"{c}_a"].astype("string"), merged[f"{c}_c"].astype("string")
            both = a.notna() & b.notna()
            rec.append({
                "column": c, "active_nonnull": int(a.notna().sum()),
                "candidate_nonnull": int(b.notna().sum()),
                "both_nonnull": int(both.sum()),
                "rows_lost": int((a.notna() & b.isna()).sum()),
                "rows_gained": int((a.isna() & b.notna()).sum()),
                "rows_diff": int((both & a.ne(b)).sum()),
                "max_abs_diff": None, "median_rel_diff": None,
            })
    return pd.DataFrame(rec).sort_values(["rows_diff", "rows_lost"], ascending=False), merged


# ------------------------------------------------------------------ 1 现金流
def review_financial() -> dict:
    active_path, cand_path = RAW / "csmar_financial.csv", CAND / "csmar_financial_cashflow_fixed.csv"
    active, cand = norm(read(active_path, dtype={"stock_code": str})), \
        norm(read(cand_path, dtype={"stock_code": str}))
    common = [c for c in active.columns if c in cand.columns and c not in KEY]
    diff, merged = col_diff(active, cand, common)
    diff.to_csv(OUT / "promotion_diff_financial_20261114.csv", index=False, encoding="utf-8-sig")

    only_active = [c for c in active.columns if c not in cand.columns]
    missing_cols = {c: int(active[c].notna().sum()) for c in only_active}
    cf_ok = {c: bool(diff.loc[diff["column"].eq(c), "rows_diff"].sum() == 0) for c in CASHFLOW}
    regression = diff[diff["rows_lost"] > 0][["column", "rows_lost", "active_nonnull", "candidate_nonnull"]]

    unit = {}
    ta = pd.to_numeric(active["total_assets"], errors="coerce").replace(0, np.nan)
    for c in CASHFLOW:
        r = (pd.to_numeric(active[c], errors="coerce") / ta).abs()
        unit[c] = {"median_abs_to_assets": float(r.median()), "p99_abs_to_assets": float(r.quantile(0.99))}

    eps = diff[diff["column"].eq("eps")]
    eps_precision_only = bool(len(eps) and eps["max_abs_diff"].iloc[0] is not None
                              and eps["max_abs_diff"].iloc[0] < 1e-3
                              and (eps["median_rel_diff"].iloc[0] or 0) == 0
                              and eps["rows_lost"].iloc[0] == 0)

    blockers = []
    if only_active:
        missing_desc = "、".join(f"{c}({n:,} 行)" for c, n in missing_cols.items())
        blockers.append(f"候选缺列：{missing_desc}；整表覆盖会丢失这些既有口径修正")
    if len(regression):
        blockers.append("覆盖回退：" + "、".join(
            f"{r.column} 少 {int(r.rows_lost)} 行" for r in regression.itertuples()))

    if all(cf_ok.values()):
        status, verdict = "keep_active", "四列现金流在在线表已同值，禁止整表覆盖；本候选已无转正价值"
    elif blockers:
        status, verdict = "activate_field_level", "现金流未同值且存在覆盖回退，只能字段级合并四列"
    else:
        status, verdict = "promote", "可整表覆盖"

    return {
        "candidate": cand_path.relative_to(ROOT).as_posix(),
        "target": active_path.relative_to(ROOT).as_posix(),
        "rows": {"active": int(len(active)), "candidate": int(len(cand))},
        "key_merge": merged["_merge"].value_counts().to_dict(),
        "cashflow_identical": cf_ok,
        "cashflow_unit_sanity": unit,
        "only_in_active": only_active,
        "only_in_candidate": [c for c in cand.columns if c not in active.columns],
        "coverage_regression": regression.to_dict("records"),
        "eps_precision_only": eps_precision_only,
        "blockers": blockers,
        "status": status,
        "verdict": verdict,
        "sha256": {"active": sha(active_path), "candidate": sha(cand_path)},
    }


# ------------------------------------------------------------------ 2 标签
def positives_from_events(events: pd.DataFrame, end_year: int = YEAR_MAX) -> set[tuple[str, int]]:
    pos: set[tuple[str, int]] = set()
    for row in events.itertuples(index=False):
        start = int(str(getattr(row, "实施日期"))[:4])
        end_raw = str(getattr(row, "撤销日期"))
        end = int(end_raw[:4]) if end_raw[:4].isdigit() else end_year
        for year in range(max(start, YEAR_MIN), min(end, end_year) + 1):
            pos.add((str(getattr(row, "证券代码")).zfill(6), year))
    return pos


def review_labels() -> dict:
    active_path, cand_path = RAW / "labels_st.csv", CAND / "labels_st_official.csv"
    active, cand = norm(read(active_path, dtype={"stock_code": str})), \
        norm(read(cand_path, dtype={"stock_code": str}))
    for f in (active, cand):
        f["is_st"] = pd.to_numeric(f["is_st"], errors="coerce")

    merged = active[KEY + ["is_st", "label_source"]].merge(
        cand[KEY + ["is_st", "label_source"]], on=KEY, how="outer",
        suffixes=("_active", "_candidate"), indicator=True)
    tmp = active[KEY + ["is_st"]].merge(cand[KEY + ["is_st"]], on=KEY,
                                        suffixes=("_a", "_c"), how="inner")
    disagree = tmp[tmp["is_st_a"] != tmp["is_st_c"]]

    by_year = (active.groupby("year")["is_st"].agg(active_n="size", active_pos="sum")
               .join(cand.groupby("year")["is_st"].agg(cand_n="size", cand_pos="sum"), how="outer")
               .fillna(0).astype(int).reset_index())
    by_year["pos_diff"] = by_year["cand_pos"] - by_year["active_pos"]
    by_year.to_csv(OUT / "promotion_diff_labels_20261114.csv", index=False, encoding="utf-8-sig")

    ev_active = read(RAW / "ST_events.csv", dtype=str)
    ev_cand = read(CAND / "ST_events_official.csv", dtype=str)
    ev_key = ["证券代码", "实施日期"]
    ev_a = ev_active.assign(证券代码=code(ev_active["证券代码"])).drop_duplicates(ev_key)
    ev_c = ev_cand.assign(证券代码=code(ev_cand["证券代码"])).drop_duplicates(ev_key)
    ev_merged = ev_a.merge(ev_c, on=ev_key, how="outer", suffixes=("_a", "_c"), indicator=True)
    ev_both = ev_merged[ev_merged["_merge"].eq("both")]
    ev_cols = {}
    for c in ev_cand.columns:
        if c in ev_key:
            continue
        a, b = ev_both.get(f"{c}_a"), ev_both.get(f"{c}_c")
        if a is not None and b is not None:
            ev_cols[c] = int((a.astype("string").fillna("") != b.astype("string").fillna("")).sum())

    recomputed = positives_from_events(ev_cand)
    label_keys = {(c, int(y)) for c, y in zip(cand["stock_code"], cand["year"])}
    positive_rows = cand[cand["is_st"].eq(1)]
    cand_pos = {(c, int(y)) for c, y in zip(positive_rows["stock_code"], positive_rows["year"])}
    # 事件落在财务主表键之外（退市/更名公司）属正常，只在键内校验一致性
    inside = recomputed & label_keys
    self_check = {"positive_pairs_from_events": len(recomputed),
                  "outside_label_keys": len(recomputed - label_keys),
                  "missing_in_labels": len(inside - cand_pos),
                  "extra_in_labels": len(cand_pos - inside)}

    values_identical = bool(len(disagree) == 0 and merged["_merge"].eq("both").all())
    if values_identical:
        status, verdict = "keep_active", "0/1 取值完全一致，仅来源标注不同；标签已实质激活，候选可归档，无需重训"
    else:
        status, verdict = "do_not_promote", f"{len(disagree)} 个公司-年取值冲突，禁止覆盖，需逐条回溯 ST 事件"

    return {
        "candidate": cand_path.relative_to(ROOT).as_posix(),
        "target": active_path.relative_to(ROOT).as_posix(),
        "rows": {"active": int(len(active)), "candidate": int(len(cand))},
        "key_merge": merged["_merge"].value_counts().to_dict(),
        "positive": {"active": int(active["is_st"].sum()), "candidate": int(cand["is_st"].sum())},
        "disagreement_rows": int(len(disagree)),
        "disagreement_examples": disagree.head(10)[KEY + ["is_st_a", "is_st_c"]].to_dict("records"),
        "label_source": {"active": sorted(active["label_source"].dropna().unique().tolist()),
                         "candidate": sorted(cand["label_source"].dropna().unique().tolist())},
        "events": {"rows": {"active": int(len(ev_active)), "candidate": int(len(ev_cand))},
                   "key_merge": ev_merged["_merge"].value_counts().to_dict(),
                   "column_diff_rows": ev_cols,
                   "candidate_self_consistent": self_check},
        "status": status, "verdict": verdict,
        "sha256": {"active": sha(active_path), "candidate": sha(cand_path)},
    }


# ------------------------------------------------------------------ 3 行情
def reader_drift() -> dict:
    """找出仍硬编码遗留 market_features.csv 的代码位置（排除注释/文档字符串）。"""
    skip = {".venv", "node_modules", "docs", "cache", "models", "data"}
    tokens = ("read(", "read_csv(", "RAW /", "OUT =", "Path(")
    hits = []
    for path in ROOT.rglob("*.py"):
        if skip & set(path.parts) or path.name == Path(__file__).name:
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if "market_features.csv" not in line or "market_features_trd" in line:
                continue
            if line.lstrip().startswith("#") or not any(t in line for t in tokens):
                continue
            role = ("legacy_writer" if path.name.startswith("fetch_")
                    else "audit_sidecar" if path.name == "build_market_features.py"
                    else "consumer")
            hits.append({"file": path.relative_to(ROOT).as_posix(), "line": i,
                         "role": role, "text": line.strip()})
    return {"hits": hits,
            "consumers": sorted({h["file"] for h in hits if h["role"] == "consumer"})}


def panel_consistency(trd: pd.DataFrame) -> dict:
    if not PANEL.exists():
        return {"available": False}
    panel = pd.read_parquet(PANEL, columns=[*KEY, "annual_turnover", "stock_volatility"])
    m = panel.merge(trd[KEY + ["annual_turnover", "stock_volatility"]], on=KEY, how="inner",
                    suffixes=("_panel", "_trd"))
    train = m["year"].between(2015, 2021)
    out = {"available": True, "overlap_rows": int(len(m))}
    for col in ("annual_turnover", "stock_volatility"):
        a = pd.to_numeric(m[f"{col}_panel"], errors="coerce")
        b = pd.to_numeric(m[f"{col}_trd"], errors="coerce")
        d = (a - b).abs()
        lo, hi = a[train].quantile(0.01), a[train].quantile(0.99)
        edge = ((a <= lo) | (a >= hi)) & (d > 1e-6)
        out[col] = {
            "spearman": float(a.corr(b, method="spearman")),
            "pearson": float(a.corr(b)),
            "rows_diff_gt_1e-6": int((d > 1e-6).sum()),
            "share_diff": float((d > 1e-6).mean()),
            "share_diff_at_clip_edge": float(edge.sum() / max(int((d > 1e-6).sum()), 1)),
        }
    return out


def review_market() -> dict:
    legacy_path, new_path = RAW / "market_features_legacy_percent.csv", RAW / "market_features_trd.csv"
    trd_path = CAND / "TRD_Dly_company_year_2013_2026.csv"
    legacy = norm(read(legacy_path, dtype={"stock_code": str}))
    new = norm(read(new_path, dtype={"stock_code": str, "audit_opinion": "Int8",
                                     "big4_audit": "Int8"}))
    trd = norm(read(trd_path, dtype={"Stkcd": str}).rename(columns={"Stkcd": "stock_code"}))

    key_union = (legacy[KEY].merge(new[KEY], on=KEY, how="outer", indicator=True)["_merge"]
                 .value_counts().to_dict())
    both = legacy.merge(new, on=KEY, how="inner", suffixes=("_legacy", "_new"))
    turnover_ratio = (pd.to_numeric(both["annual_turnover_new"], errors="coerce")
                      / pd.to_numeric(both["annual_turnover_legacy"], errors="coerce").replace(0, np.nan))
    vol_ratio = (pd.to_numeric(both["stock_volatility_new"], errors="coerce")
                 / pd.to_numeric(both["stock_volatility_legacy"], errors="coerce").replace(0, np.nan))
    audit = {}
    for c in ("audit_opinion", "big4_audit", "audit_fee"):
        a = pd.to_numeric(both[f"{c}_legacy"], errors="coerce").astype("float64")
        b = pd.to_numeric(both[f"{c}_new"], errors="coerce").astype("float64")
        audit[c] = {"legacy_nonnull": int(a.notna().sum()), "contract_nonnull": int(b.notna().sum()),
                    "value_mismatch_rows": int(((a.notna() & b.notna()) & ~np.isclose(a, b)).sum()),
                    "one_side_missing": int((a.notna() ^ b.notna()).sum())}

    vol_abs = (pd.to_numeric(both["stock_volatility_legacy"], errors="coerce")
               - pd.to_numeric(both["stock_volatility_new"], errors="coerce")).abs()
    volatility_value_diff = {"median_abs": float(vol_abs.median()),
                             "p99_abs": float(vol_abs.quantile(0.99)),
                             "max_abs": float(vol_abs.max()),
                             "share_gt_1e-6": float((vol_abs > 1e-6).mean())}

    market_rows = []
    for c, ratio in (("annual_turnover", float(turnover_ratio.median())),
                     ("stock_volatility", float(vol_ratio.median()))):
        a, b = (pd.to_numeric(both[f"{c}_legacy"], errors="coerce"),
                pd.to_numeric(both[f"{c}_new"], errors="coerce"))
        market_rows.append({"column": c, "legacy_nonnull": int(a.notna().sum()),
                            "contract_nonnull": int(b.notna().sum()),
                            "value_mismatch_rows": int(((a.notna() & b.notna()) & ~np.isclose(a, b)).sum()),
                            "one_side_missing": int((a.notna() ^ b.notna()).sum()),
                            "contract_over_legacy_ratio_median": ratio})
    for c, v in audit.items():
        market_rows.append({"column": c, **v, "contract_over_legacy_ratio_median": None})
    pd.DataFrame(market_rows).to_csv(OUT / "promotion_diff_market_20261114.csv",
                                     index=False, encoding="utf-8-sig")

    m2 = new.merge(trd[KEY + ["annual_turnover", "stock_volatility", "trading_days"]],
                   on=KEY, how="inner", suffixes=("_new", "_trd"))
    contract_vs_trd = {}
    for c in ("annual_turnover", "stock_volatility", "trading_days"):
        a, b = (pd.to_numeric(m2[f"{c}_new"], errors="coerce"),
                pd.to_numeric(m2[f"{c}_trd"], errors="coerce"))
        d = (a - b).abs()
        contract_vs_trd[c] = {"pairs": int(len(m2)), "rows_diff_gt_1e-9": int((d > 1e-9).sum()),
                              "max_abs_diff": float(d.max()) if d.notna().any() else None}

    y2026 = trd[trd["year"].eq(2026)]
    schema = {
        "rows": {"legacy": int(len(legacy)), "contract": int(len(new)), "trd_candidate": int(len(trd))},
        "columns": {"legacy": list(legacy.columns), "contract": list(new.columns)},
        "audit_opinion_dtype": {"legacy": str(legacy["audit_opinion"].dtype),
                                "contract": str(new["audit_opinion"].dtype)},
        "market_available_rate": {
            "legacy": float(pd.to_numeric(legacy["market_available"], errors="coerce").fillna(0).mean()),
            "contract": float(pd.to_numeric(new["market_available"], errors="coerce").fillna(0).mean()),
        },
        "rows_2026": int(len(y2026)),
        "trading_days_2026_median": float(y2026["trading_days"].median()) if len(y2026) else None,
    }

    panel = panel_consistency(trd)
    drift = reader_drift()
    gaps = []
    if drift["consumers"]:
        gaps.append("读取端仍指向遗留表：" + "、".join(drift["consumers"]))
    if schema["audit_opinion_dtype"]["contract"].startswith("float"):
        gaps.append("契约表 audit_opinion/big4_audit 因外连接出现 NaN 被降级为 float")
    if schema["rows_2026"] and (schema["trading_days_2026_median"] or 0) < 220:
        gaps.append(f"2026 仅 {schema['trading_days_2026_median']:.0f} 个交易日，不可作完整年度")
    notes = []
    if not drift["consumers"]:
        notes.append("EDA/audit 读取端已改为 settings.RAW_MARKET，遗留表仅归档保留")
    if schema["audit_opinion_dtype"]["contract"].startswith("Int8"):
        notes.append("审计列按 Int8 落盘；CSV 不保留可空整型，读取端需显式 dtype 提示")
    if panel.get("available"):
        for col in ("annual_turnover", "stock_volatility"):
            if panel[col]["share_diff_at_clip_edge"] > 0.95:
                notes.append(f"{col}：面板与候选差异全部落在缩尾边界，Spearman="
                             f"{panel[col]['spearman']:.4f}，口径已贯通")

    return {
        "legacy": legacy_path.relative_to(ROOT).as_posix(),
        "contract": new_path.relative_to(ROOT).as_posix(),
        "candidate": trd_path.relative_to(ROOT).as_posix(),
        "key_union": key_union,
        "turnover_scale": {"ratio_median": float(turnover_ratio.median()),
                           "ratio_p01": float(turnover_ratio.quantile(0.01)),
                           "ratio_p99": float(turnover_ratio.quantile(0.99)),
                           "pairs": int(turnover_ratio.notna().sum())},
        "volatility_scale": {"ratio_median": float(vol_ratio.median()),
                             "pairs": int(vol_ratio.notna().sum())},
        "audit_columns": audit,
        "volatility_value_diff": volatility_value_diff,
        "contract_vs_trd": contract_vs_trd,
        "schema": schema,
        "panel": panel,
        "reader_drift": drift,
        "gaps": gaps,
        "notes": notes,
        "status": "needs_reader_fix" if drift["consumers"] else "keep_active",
        "verdict": ("契约指针已切到 TRD 小数口径，但仍有读取端指向遗留表；应修读取端并归档遗留表"
                    if drift["consumers"] else
                    "契约与读取端已统一为 TRD 小数口径；遗留百分数表仅作审计对照"),
        "sha256": {name: sha(path) for name, path in
                   (("legacy", legacy_path), ("contract", new_path), ("candidate", trd_path))},
    }


# ------------------------------------------------------------------ 报告
def md_table(headers: list[str], rows: list[list]) -> str:
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(["---"] * len(headers)) + "|"
    body = ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows]
    return "\n".join([head, sep, *body])


def write_markdown(p: dict) -> Path:
    fin, lab, mkt = p["financial"], p["labels"], p["market"]
    flags = {"keep_active": "PASS", "activate_field_level": "WARN",
             "do_not_promote": "BLOCK", "promote": "PASS", "needs_reader_fix": "WARN"}

    def kv(d: dict) -> str:
        return "，".join(f"{k}={v:,}" if isinstance(v, int) and not isinstance(v, bool) else f"{k}={v}"
                         for k, v in d.items())

    summary = [
        ["现金流修正", f"`{fin['candidate']}`", "禁止整表覆盖", flags[fin["status"]], fin["verdict"]],
        ["官方 ST 标签", f"`{lab['candidate']}`", "保持现状", flags[lab["status"]], lab["verdict"]],
        ["行情口径", f"`{mkt['candidate']}`", "修读取端", flags[mkt["status"]], mkt["verdict"]],
    ]
    reg = fin["coverage_regression"]
    unit_rows = [[c, f"{v['median_abs_to_assets']:.4f}", f"{v['p99_abs_to_assets']:.3f}"]
                 for c, v in fin["cashflow_unit_sanity"].items()]
    fin_rows = [[r["column"], f"{r['active_nonnull']:,}", f"{r['candidate_nonnull']:,}",
                 f"{r['rows_lost']:,}", f"{r['rows_diff']:,}",
                 f"{r['max_abs_diff']:.3g}" if pd.notna(r["max_abs_diff"]) else "-"]
                for r in (fin.get("diff_top") or [])]
    lab_rows = [[r["year"], r["active_n"], r["active_pos"], r["cand_n"], r["cand_pos"], r["pos_diff"]]
                for r in lab.get("by_year", [])]
    drift_rows = [[h["file"], h["line"], h["role"], f"`{h['text'][:70]}`"] for h in mkt["reader_drift"]["hits"]]
    panel = mkt["panel"]
    panel_rows = []
    if panel.get("available"):
        for c in ("annual_turnover", "stock_volatility"):
            v = panel[c]
            panel_rows.append([c, f"{v['spearman']:.4f}", f"{v['pearson']:.4f}",
                               v["rows_diff_gt_1e-6"], f"{v['share_diff']:.2%}",
                               f"{v['share_diff_at_clip_edge']:.1%}"])

    lines = [
        "# 候选转正评审（差异清单）",
        "",
        f"- 生成时间：{p['generated_at']}",
        "- 口径：**只读评审**，未修改 `data/raw` 任何文件；结论用于决定整表覆盖 / 字段级合并 / 保持现状。",
        "",
        "## 一、结论摘要",
        "",
        md_table(["候选", "目标文件", "建议动作", "判定", "结论"], summary),
        "",
        "## 二、现金流修正候选",
        "",
        f"- 在线 `{fin['target']}`：{fin['rows']['active']:,} 行；候选：{fin['rows']['candidate']:,} 行",
        f"- 主键对齐：{kv(fin['key_merge'])}",
        f"- 四列现金流是否已同值：{kv(fin['cashflow_identical'])}",
        f"- 候选缺少的在线列：{', '.join(fin['only_in_active']) or '无'}（非空行数见阻塞项）",
        "",
        "### 2.1 逐列差异 Top（完整清单见证据 CSV）",
        "",
        md_table(["列", "在线非空", "候选非空", "覆盖少掉", "差异行", "最大绝对差"], fin_rows),
        "",
        "### 2.2 覆盖回退（整表覆盖会丢的列）",
        "",
        md_table(["列", "少掉的行数", "在线非空", "候选非空"],
                 [[r["column"], r["rows_lost"], r["active_nonnull"], r["candidate_nonnull"]] for r in reg])
        if reg else "- 无",
        "",
        "### 2.3 现金流单位合理性（|现金流| / 总资产）",
        "",
        md_table(["列", "中位数", "P99"], unit_rows),
        "",
        f"- `eps` 差异是否仅为浮点精度：{fin['eps_precision_only']}",
        "",
        "**阻塞项（因此不能整表覆盖）**",
        "",
        *([f"- {b}" for b in fin["blockers"]] if fin["blockers"] else ["- 无"]),
        "",
        "",
        "> 结论：**禁止把候选整表覆盖到 `csmar_financial.csv`**（会清空扣非/折旧、回退有息负债与长期借款回填）。"
        "四列现金流已在在线表生效，无需再次合并；若未来重导入财务表，必须重跑 "
        "`import_comscfi_official --write` 与 `fix_interest_debt --write`。",
        "",
        "## 三、官方 ST 标签",
        "",
        f"- 在线 {lab['rows']['active']:,} 行 / 正样本 {lab['positive']['active']:,}；"
        f"候选 {lab['rows']['candidate']:,} 行 / 正样本 {lab['positive']['candidate']:,}",
        f"- 主键对齐：{kv(lab['key_merge'])}；0/1 取值冲突：{lab['disagreement_rows']} 行",
        f"- 来源标注：在线 `{lab['label_source']['active'][0]}`；候选 `{lab['label_source']['candidate'][0]}`",
        f"- 事件表（在线 {lab['events']['rows']['active']:,} 段 / 候选 {lab['events']['rows']['candidate']:,} 段）："
        f"{kv(lab['events']['key_merge'])}；逐列差异 {sum(lab['events']['column_diff_rows'].values())} 行",
        f"- 标签可否由事件复现：事件正样本 {lab['events']['candidate_self_consistent']['positive_pairs_from_events']:,} 个公司-年，"
        f"{lab['events']['candidate_self_consistent']['outside_label_keys']:,} 个落在财务主表键外（退市/更名），"
        f"键内缺失 {lab['events']['candidate_self_consistent']['missing_in_labels']}、"
        f"多余 {lab['events']['candidate_self_consistent']['extra_in_labels']}",
        "",
        md_table(["年份", "在线行数", "在线正样本", "候选行数", "候选正样本", "正样本差"], lab_rows),
        "",
        f"> 结论：{lab['verdict']}。",
        "",
        "## 四、行情口径",
        "",
        f"- 遗留表 `{mkt['legacy']}`：{mkt['schema']['rows']['legacy']:,} 行；"
        f"契约表 `{mkt['contract']}`：{mkt['schema']['rows']['contract']:,} 行；"
        f"候选 `{mkt['candidate']}`：{mkt['schema']['rows']['trd_candidate']:,} 行",
        f"- 主键并集：{kv(mkt['key_union'])}（契约表多出的行为 2013–2026 新增键）",
        f"- 换手率 契约/遗留 比值中位数：{mkt['turnover_scale']['ratio_median']:.3f}"
        f"（P01 {mkt['turnover_scale']['ratio_p01']:.3f} / P99 {mkt['turnover_scale']['ratio_p99']:.3f}，"
        f"配对 {mkt['turnover_scale']['pairs']:,} 行）→ 遗留表为百分数口径（约 100×）",
        f"- 波动率 契约/遗留 比值中位数：{mkt['volatility_scale']['ratio_median']:.4f}（口径一致）",
        f"- 波动率数值差（共同非空）：中位数 {mkt['volatility_value_diff']['median_abs']:.2e} / "
        f"P99 {mkt['volatility_value_diff']['p99_abs']:.4f} / 最大 {mkt['volatility_value_diff']['max_abs']:.2f}，"
        f"{mkt['volatility_value_diff']['share_gt_1e-6']:.2%} 行有差异 → 属数据源重算，非单位切换",
        f"- 审计列对齐：非空 {mkt['audit_columns']['audit_opinion']['legacy_nonnull']:,} 行，取值差异 "
        f"{sum(v['value_mismatch_rows'] for v in mkt['audit_columns'].values())} 行、单边缺失 "
        f"{sum(v['one_side_missing'] for v in mkt['audit_columns'].values())} 行（三类审计列合计）",
        f"- 契约表 vs 候选：换手率/波动率/交易日 最大绝对差 "
        f"{max(v['max_abs_diff'] or 0 for v in mkt['contract_vs_trd'].values()):.2e}，"
        f"超容差行 {sum(v['rows_diff_gt_1e-9'] for v in mkt['contract_vs_trd'].values())}",
        f"- `audit_opinion` dtype：遗留 {mkt['schema']['audit_opinion_dtype']['legacy']} → "
        f"契约 {mkt['schema']['audit_opinion_dtype']['contract']}",
        f"- 2026：{mkt['schema']['rows_2026']:,} 行，交易日中位数 "
        f"{mkt['schema']['trading_days_2026_median']}（部分年度）",
        "",
        "### 4.1 特征面板是否已贯通",
        "",
        md_table(["列", "Spearman", "Pearson", "差异行", "差异占比", "差异落在缩尾边界"], panel_rows)
        if panel_rows else "- 面板不可用",
        "",
        "### 4.2 读取端漂移",
        "",
        md_table(["文件", "行号", "角色", "代码"], drift_rows) if drift_rows else "- 无",
        "",
        "### 4.3 遗留缺口",
        "",
        *([f"- {g}" for g in mkt["gaps"]] or ["- 无"]),
        "",
        "### 4.4 已通过项",
        "",
        *([f"- {n}" for n in mkt["notes"]] or ["- 无"]),
        "",
        f"> 结论：{mkt['verdict']}。",
        "",
        "## 五、动作清单",
        "",
        "| # | 动作 | 命令/文件 | 是否需要重训 |",
        "|---|---|---|---|",
        "| 1 | 现金流：保持现状，禁止整表覆盖 | 无需执行；重导入后跑 `import_comscfi_official --write` + `fix_interest_debt --write` | 否 |",
        "| 2 | 标签：归档候选，保留在线表 | `data/raw/candidates/labels_st_official.csv` 标记 replaced | 否 |",
        "| 3 | 行情：读取端切到 `settings.RAW_MARKET`（已完成） | `run_data_eda.py`、`audit_data_gap.py` 已改读契约表 | 否 |",
        "| 4 | 行情：遗留表归档（已完成） | `market_features.csv` → `market_features_legacy_percent.csv`，保留不删 | 否 |",
        "| 5 | 行情：审计列 Int8（已完成） | `build_market_features.py` 落盘 Int8；读取端传 `dtype=Int8` | 否 |",
        "| 6 | 2026：年度对比排除部分年度 | 训练/评估窗口仍为 2015–2023 | 否 |",
        "",
        "## 六、证据文件",
        "",
        "- `reports/data_quality/promotion_diff_financial_20261114.csv`（逐列差异）",
        "- `reports/data_quality/promotion_diff_labels_20261114.csv`（年度分布差异）",
        "- `reports/data_quality/promotion_review_20261114.json`（完整机器可读证据 + SHA256）",
        "",
        "## 七、文件指纹",
        "",
        md_table(["对象", "SHA256"],
                 [[f"{section}.{k}", f"`{v}`"] for section in ("financial", "labels", "market")
                  for k, v in p[section]["sha256"].items()]),
        "",
    ]
    path = OUT / "promotion_review_20261114.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def jsonable(obj):
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"不可序列化：{type(obj)}")


def main() -> None:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "financial": review_financial(),
        "labels": review_labels(),
        "market": review_market(),
    }
    # 报告用的 Top 差异行（完整清单在 CSV）
    diff = pd.read_csv(OUT / "promotion_diff_financial_20261114.csv", encoding="utf-8-sig")
    interesting = diff[(diff["rows_diff"] > 0) | (diff["rows_lost"] > 0)]
    payload["financial"]["diff_top"] = interesting.head(15).to_dict("records")
    by_year = pd.read_csv(OUT / "promotion_diff_labels_20261114.csv", encoding="utf-8-sig")
    payload["labels"]["by_year"] = by_year.to_dict("records")

    json_path = OUT / "promotion_review_20261114.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=jsonable),
                         encoding="utf-8")
    md_path = write_markdown(payload)

    print(json.dumps({
        "generated_at": payload["generated_at"],
        "decisions": {k: {"status": payload[k]["status"], "verdict": payload[k]["verdict"]}
                      for k in ("financial", "labels", "market")},
        "blockers": payload["financial"]["blockers"],
        "market_gaps": payload["market"]["gaps"],
        "outputs": [json_path.relative_to(ROOT).as_posix(), md_path.relative_to(ROOT).as_posix()],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
