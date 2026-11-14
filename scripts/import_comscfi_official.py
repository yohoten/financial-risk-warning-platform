# -*- coding: utf-8 -*-
"""用 CSMAR 现金流量表（间接法）官方口径替换折旧回填值（G-03）。

口径
----
- 仅取合并报表（Typrep=A）、年报（Accper=12-31）、2013–2025；
- 同一公司-年多次披露（差错更正）按 DeclareDate 取最新；
- 金额由「元」统一为「亿元」（/1e8），与契约层一致；
- 主字段 `depreciation` ← D000103000「固定资产折旧、油气资产折耗、生产性生物资产折旧」；
- `amort_intangible` / `amort_lt_prepaid` 只写入候选表，供后续扩展 EBITDA 口径，暂不改契约。

写回规则
--------
官方值优先（覆盖新浪回填值），官方缺失时保留旧值；`deducted_profit` 与行键必须保持不变，
写前自动备份为 ``.bak_YYYYmmdd_HHMMSS``。

用法
----
    python -m scripts.import_comscfi_official            # 只体检 + 写候选
    python -m scripts.import_comscfi_official --write    # 字段级写回契约表
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
from etl.io_utils import get_logger, write_table

logger = get_logger("comscfi")

CODES = {
    "D000103000": "depreciation",
    "D000104000": "amort_intangible",
    "D000105000": "amort_lt_prepaid",
}
YEAR_MIN, YEAR_MAX = 2013, 2025
KEY = ["stock_code", "year"]
CANDIDATE = settings.RAW_DIR / "candidates" / "depreciation_comscfi_annual.csv"
SINA = settings.RAW_DIR / "candidates" / "depreciation_sina_annual.csv"
STAGED = settings.STAGING_DIR / "raw" / "FS_Comscfi.csv"


def _source() -> Path:
    if STAGED.exists():
        return STAGED
    hits = sorted(settings.RAW_DOWNLOAD_DIR.glob("**/FS_Comscfi.csv"))
    if not hits:
        raise FileNotFoundError(
            f"未找到 FS_Comscfi.csv。请先执行：\n"
            f"  python -m scripts.sync_raw_download --only FS_Comscfi --write\n"
            f"（落地区：{settings.rel(settings.RAW_DOWNLOAD_DIR)}）"
        )
    return hits[0]


def load_official() -> pd.DataFrame:
    path = _source()
    header = pd.read_csv(path, nrows=0, encoding="utf-8-sig").columns
    usecols = [c for c in ["Stkcd", "Accper", "Typrep", "DeclareDate", *CODES] if c in header]
    missing = [c for c in CODES if c not in header]
    if missing:
        raise ValueError(f"FS_Comscfi 缺少字段：{missing}")

    frames = []
    for chunk in pd.read_csv(path, usecols=usecols, dtype=str, encoding="utf-8-sig",
                             chunksize=200_000, low_memory=False):
        accper = chunk["Accper"].astype(str).str.strip()
        year = accper.str[:4]
        mask = (
            chunk["Typrep"].astype(str).str.upper().eq("A")
            & accper.str.endswith("-12-31")
            & year.str.isdigit()
            & year.astype(int).between(YEAR_MIN, YEAR_MAX)
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
        errors="coerce",
    )
    for code, name in CODES.items():
        df[name] = pd.to_numeric(df[code], errors="coerce") / 1e8      # 元 → 亿元
    df = (df.sort_values([*KEY, "declare_date"])
            .drop_duplicates(KEY, keep="last")
            .reset_index(drop=True))
    logger.info("官方间接法：%d 个公司-年，%d 家，%d–%d", len(df),
                df["stock_code"].nunique(), df["year"].min(), df["year"].max())
    return df[[*KEY, *CODES.values()]]


def compare_with_sina(official: pd.DataFrame) -> dict:
    """与现有新浪回填值对齐，输出偏差统计（只读，不写盘）。"""
    if not SINA.exists():
        return {"status": "no_sina_candidate"}
    sina = pd.read_csv(SINA, dtype={"stock_code": str}, encoding="utf-8-sig")
    sina["stock_code"] = sina["stock_code"].str.zfill(6)
    both = official.merge(sina[[*KEY, "depreciation"]], on=KEY, how="inner",
                          suffixes=("_official", "_sina"))
    both = both[(both["year"] >= 2015) & (both["year"] <= 2023)]
    pair = both[["depreciation_official", "depreciation_sina"]].apply(
        pd.to_numeric, errors="coerce").dropna()
    if pair.empty:
        return {"status": "no_overlap"}
    rel = (pair["depreciation_official"] - pair["depreciation_sina"]).abs() / pair[
        "depreciation_sina"].abs().replace(0, np.nan)
    return {
        "overlap_rows": int(len(pair)),
        "pearson": round(float(pair.corr().iloc[0, 1]), 4),
        "median_abs_diff_yi": round(float((pair.iloc[:, 0] - pair.iloc[:, 1]).abs().median()), 4),
        "p95_abs_diff_yi": round(float((pair.iloc[:, 0] - pair.iloc[:, 1]).abs().quantile(0.95)), 4),
        "within_5pct": round(float((rel <= 0.05).mean()), 4),
    }


def _hash(series: pd.Series) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(series, index=True).values.tobytes()).hexdigest()


def merge_into_contract(official: pd.DataFrame) -> dict:
    path = Path(settings.RAW_FINANCIAL)
    backup = path.with_name(f"{path.name}.bak_{datetime.now():%Y%m%d_%H%M%S}")
    shutil.copy2(path, backup)

    cur = pd.read_csv(path, dtype={"stock_code": str}, encoding="utf-8-sig", low_memory=False)
    cur["stock_code"] = cur["stock_code"].str.zfill(6)
    keys_before = len(cur)
    hash_before = _hash(cur["deducted_profit"])

    mapped = cur[KEY].merge(official[[*KEY, "depreciation"]], on=KEY, how="left",
                            validate="one_to_one")
    old = pd.to_numeric(cur["depreciation"], errors="coerce")
    new = pd.to_numeric(mapped["depreciation"], errors="coerce")
    changed = int((old.notna() & new.notna() & ~np.isclose(old, new, rtol=1e-6, atol=1e-6)).sum())
    filled = int((old.isna() & new.notna()).sum())
    cur["depreciation"] = new.combine_first(old)

    assert len(cur) == keys_before, "写回后行数变化"
    assert not cur.duplicated(KEY).any(), "写回后出现重复公司-年"
    assert _hash(cur["deducted_profit"]) == hash_before, "扣非列被改动，停止写回"

    cur.to_csv(path, index=False, encoding="utf-8-sig")
    return {
        "backup": settings.rel(backup),
        "rows": keys_before,
        "replaced": changed,
        "filled": filled,
        "coverage_2015_2023": round(float(
            cur.loc[cur["year"].between(2015, 2023), "depreciation"].notna().mean()), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="FS_Comscfi 官方折旧替换（G-03）")
    parser.add_argument("--write", action="store_true", help="字段级写回 data/raw/csmar_financial.csv")
    args = parser.parse_args()

    official = load_official()
    window = official[official["year"].between(2015, 2023)]
    coverage = {c: round(float(window[c].notna().mean()), 4) for c in CODES.values()}
    logger.info("2015–2023 覆盖率：%s", coverage)

    diff = compare_with_sina(official)
    logger.info("与新浪回填对比：%s", diff)

    write_table(official, CANDIDATE)
    manifest = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": settings.rel(_source()),
        "source_field_map": {"depreciation": "D000103000",
                             "amort_intangible": "D000104000",
                             "amort_lt_prepaid": "D000105000"},
        "unit": "亿元（原始元 / 1e8）",
        "rows": int(len(official)),
        "coverage_2015_2023": coverage,
        "vs_sina": diff,
        "candidate": settings.rel(CANDIDATE),
    }
    (CANDIDATE.parent / "depreciation_comscfi_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.write:
        logger.info("候选已写出：%s（加 --write 写回契约表）", settings.rel(CANDIDATE))
        return

    result = merge_into_contract(official)
    manifest["merge"] = result
    (CANDIDATE.parent / "depreciation_comscfi_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("折旧已写回：替换 %d 行、新填 %d 行；2015–2023 覆盖 %.2f%%",
                result["replaced"], result["filled"], result["coverage_2015_2023"] * 100)


if __name__ == "__main__":
    main()
