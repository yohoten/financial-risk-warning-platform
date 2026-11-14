# -*- coding: utf-8 -*-
"""按 CSMAR 官方口径重建有息负债（G-04）。

口径
----
CSMAR 财务指标「有形资产带息债务比 F011501A」的分子定义为：

    带息债务 = 非流动负债合计 + 短期借款 + 一年内到期的非流动负债

本脚本采用同一口径：

    interest_debt = A002200000(非流动负债合计) + A002101000(短期借款)
                    + A002125000(一年内到期的非流动负债)

同时修复 `lt_debt`（长期借款 A002201000）的"未披露 ≠ 0"问题：
对报表存在但该科目为空的公司-年，用官方比率 F011301A（长期借款/总资产）× 总资产回填
（两者在重叠样本上相关系数 = 1.0000，属同一数据的两种表达）。

校验
----
- `lt_debt` 回填值 vs `F011301A × total_assets`：重叠样本相关系数应 ≈ 1；
- 新口径 `interest_debt / total_assets` vs `F011501A`：相关系数应 > 0.95。

写回
----
只更新 `lt_debt`、`interest_debt` 两列并新增 `interest_debt_imputed` 标记；
写前备份 `.bak_YYYYmmdd_HHMMSS`，扣非/折旧列哈希必须不变。

用法
----
    python -m scripts.fix_interest_debt            # 只体检
    python -m scripts.fix_interest_debt --write    # 写回契约表
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from config import settings
from etl.io_utils import get_logger

logger = get_logger("debt-fix")

KEY = ["stock_code", "year"]
YEAR_MIN, YEAR_MAX = 2013, 2025
BALANCE_CODES = {
    "A001000000": "total_assets",
    "A002000000": "total_liabilities",
    "A002101000": "short_borrow",
    "A002125000": "current_lt_debt",
    "A002201000": "lt_debt",
    "A002200000": "noncurrent_liab",
}
FI_CODES = {"F011301A": "lt_borrow_to_assets", "F011501A": "interest_debt_to_tangible_assets"}
REPORT = settings.REPORT_DIR / "data_quality" / "interest_debt_fix.json"


def _staged(name: str) -> Path:
    path = settings.STAGING_DIR / "raw" / name
    if path.exists():
        return path
    hits = sorted(settings.RAW_DOWNLOAD_DIR.glob(f"**/{name}"))
    if not hits:
        raise FileNotFoundError(
            f"未找到 {name}，请先 python -m scripts.sync_raw_download --only "
            f"{name.split('.')[0]} --write"
        )
    return hits[0]


def load_balance() -> pd.DataFrame:
    path = _staged("FS_Combas.csv")
    header = pd.read_csv(path, nrows=0, encoding="utf-8-sig").columns
    usecols = [c for c in ["Stkcd", "Accper", "Typrep", "DeclareDate", *BALANCE_CODES] if c in header]
    frames = []
    for chunk in pd.read_csv(path, usecols=usecols, dtype=str, encoding="utf-8-sig",
                             chunksize=200_000, low_memory=False):
        accper = chunk["Accper"].astype(str).str.strip()
        year = accper.str[:4]
        mask = (
            chunk["Typrep"].astype(str).str.upper().eq("A")
            & accper.str.endswith("-12-31")
            & year.str.isdigit() & year.astype(int).between(YEAR_MIN, YEAR_MAX)
        )
        sub = chunk.loc[mask].copy()
        if sub.empty:
            continue
        sub["year"] = year[mask].astype(int)
        frames.append(sub)
    df = pd.concat(frames, ignore_index=True)
    df["stock_code"] = df["Stkcd"].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    df["declare_date"] = pd.to_datetime(
        df.get("DeclareDate", pd.Series(index=df.index, dtype=str)).astype(str).str[:10],
        errors="coerce")
    for code, name in BALANCE_CODES.items():
        df[name] = pd.to_numeric(df[code], errors="coerce") / 1e8
    df = (df.sort_values([*KEY, "declare_date"]).drop_duplicates(KEY, keep="last")
            .reset_index(drop=True))
    logger.info("资产负债表：%d 个公司-年", len(df))
    return df[[*KEY, *BALANCE_CODES.values()]]


def load_fi_t1() -> pd.DataFrame:
    path = _staged("FI_T1.csv")
    header = pd.read_csv(path, nrows=0, encoding="utf-8-sig").columns
    usecols = [c for c in ["Stkcd", "Accper", "Typrep", *FI_CODES] if c in header]
    df = pd.read_csv(path, usecols=usecols, dtype={"Stkcd": str, "Accper": str},
                     encoding="utf-8-sig")
    df = df[(df["Typrep"].astype(str).str.upper() == "A")
            & df["Accper"].str.endswith("-12-31")]
    df = df.assign(year=df["Accper"].str[:4].astype(int))
    df = df[df["year"].between(YEAR_MIN, YEAR_MAX)]
    df["stock_code"] = df["Stkcd"].str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    for code, name in FI_CODES.items():
        df[name] = pd.to_numeric(df[code], errors="coerce")
    df = df.sort_values(KEY).drop_duplicates(KEY, keep="last")
    logger.info("偿债能力表：%d 个公司-年", len(df))
    return df[[*KEY, *FI_CODES.values()]]


def build(bs: pd.DataFrame, fi: pd.DataFrame) -> pd.DataFrame:
    d = bs.merge(fi, on=KEY, how="left")
    has_bs = d["total_liabilities"].notna()

    # lt_debt：未披露但确有长期借款的，用官方比率 × 总资产回填
    implied_lt = d["lt_borrow_to_assets"] * d["total_assets"]
    fill_lt = d["lt_debt"].isna() & has_bs & implied_lt.notna()
    d["lt_debt_filled"] = d["lt_debt"].where(~fill_lt, implied_lt)

    # 有息负债：CSMAR 带息债务口径
    parts = d[["noncurrent_liab", "short_borrow", "current_lt_debt"]]
    d["interest_debt_new"] = parts.sum(axis=1, min_count=1)
    d["interest_debt_imputed"] = 0
    # 非流动负债合计缺失但官方比率可用的，用比率 × 总资产兜底
    fallback = d["interest_debt_new"].isna() & has_bs & d["interest_debt_to_tangible_assets"].notna()
    d.loc[fallback, "interest_debt_new"] = (
        d.loc[fallback, "interest_debt_to_tangible_assets"] * d.loc[fallback, "total_assets"])
    d.loc[fallback, "interest_debt_imputed"] = 1

    d["interest_debt_filled"] = d["interest_debt_new"]
    return d[[*KEY, "total_assets", "lt_debt", "lt_debt_filled", "interest_debt_filled",
              "interest_debt_imputed", "lt_borrow_to_assets",
              "interest_debt_to_tangible_assets"]]


def diagnose(built: pd.DataFrame, window=(2015, 2023)) -> dict:
    w = built[built["year"].between(*window)]
    old_lt = float(w["lt_debt"].notna().mean())
    new_lt = float(w["lt_debt_filled"].notna().mean())
    old_id = float(w["interest_debt"].notna().mean())
    new_id = float(w["interest_debt_filled"].notna().mean())
    both = w.dropna(subset=["lt_borrow_to_assets", "lt_debt_filled"])
    corr_lt = float((both["lt_debt_filled"]).corr(
        both["lt_borrow_to_assets"] * both["total_assets"])) if len(both) > 10 else np.nan
    both2 = w.dropna(subset=["interest_debt_to_tangible_assets", "interest_debt_filled"])
    ratio = (both2["interest_debt_filled"] / both2["total_assets"])
    corr_id = float(ratio.corr(both2["interest_debt_to_tangible_assets"])) if len(both2) > 10 else np.nan
    return {
        "rows_2015_2023": int(len(w)),
        "lt_debt_coverage_before": round(old_lt, 4),
        "lt_debt_coverage_after": round(new_lt, 4),
        "lt_debt_imputed_rows": int(w["lt_debt"].isna().sum() - w["lt_debt_filled"].isna().sum()),
        "interest_debt_coverage_before": round(old_id, 4),
        "interest_debt_coverage_after": round(new_id, 4),
        "interest_debt_ratio_median_before": round(float((w["interest_debt"] / w["total_assets"]).median()), 4),
        "interest_debt_ratio_median_after": round(float((w["interest_debt_filled"] / w["total_assets"]).median()), 4),
        "corr_lt_debt_vs_official": round(corr_lt, 4),
        "corr_interest_ratio_vs_F011501A": round(corr_id, 4),
        "imputed_by_ratio_rows": int(w["interest_debt_imputed"].sum()),
    }


def _hash(series: pd.Series) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(series, index=True).values.tobytes()).hexdigest()


def merge_into_contract(built: pd.DataFrame) -> dict:
    path = Path(settings.RAW_FINANCIAL)
    backup = path.with_name(f"{path.name}.bak_{datetime.now():%Y%m%d_%H%M%S}")
    shutil.copy2(path, backup)

    cur = pd.read_csv(path, dtype={"stock_code": str}, encoding="utf-8-sig", low_memory=False)
    cur["stock_code"] = cur["stock_code"].str.zfill(6)
    hashes = {c: _hash(cur[c]) for c in ("deducted_profit", "depreciation")}
    n_before = len(cur)

    mapped = cur[KEY].merge(
        built[[*KEY, "lt_debt_filled", "interest_debt_filled", "interest_debt_imputed"]],
        on=KEY, how="left", validate="one_to_one")
    old_lt = pd.to_numeric(cur["lt_debt"], errors="coerce")
    old_id = pd.to_numeric(cur["interest_debt"], errors="coerce")
    new_lt = pd.to_numeric(mapped["lt_debt_filled"], errors="coerce")
    new_id = pd.to_numeric(mapped["interest_debt_filled"], errors="coerce")

    cur["lt_debt"] = new_lt.combine_first(old_lt)
    cur["interest_debt"] = new_id.combine_first(old_id)
    cur["interest_debt_imputed"] = mapped["interest_debt_imputed"].fillna(0).astype("int8")

    assert len(cur) == n_before and not cur.duplicated(KEY).any(), "写回后行数/主键异常"
    for col, h in hashes.items():
        assert _hash(cur[col]) == h, f"{col} 被改动，停止写回"

    cur.to_csv(path, index=False, encoding="utf-8-sig")
    return {
        "backup": settings.rel(backup),
        "lt_debt_changed": int((~np.isclose(old_lt, cur["lt_debt"], equal_nan=True)).sum()),
        "interest_debt_changed": int((~np.isclose(old_id, cur["interest_debt"], equal_nan=True)).sum()),
        "rows": n_before,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="CSMAR 官方有息负债口径重建（G-04）")
    parser.add_argument("--write", action="store_true", help="字段级写回 csmar_financial.csv")
    args = parser.parse_args()

    bs, fi = load_balance(), load_fi_t1()
    built = build(bs, fi)
    old = pd.read_csv(settings.RAW_FINANCIAL, usecols=[*KEY, "interest_debt"],
                      dtype={"stock_code": str}, encoding="utf-8-sig")
    old["stock_code"] = old["stock_code"].str.zfill(6)
    built = built.merge(old, on=KEY, how="left", suffixes=("", "_before"))
    diag = diagnose(built)
    for k, v in diag.items():
        logger.info("%-38s %s", k, v)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "diagnose": diag}
    if args.write:
        payload["merge"] = merge_into_contract(built)
        logger.info("已写回：%s", payload["merge"])
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("诊断报告：%s", settings.rel(REPORT))


if __name__ == "__main__":
    main()
