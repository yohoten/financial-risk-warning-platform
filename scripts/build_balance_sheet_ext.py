"""从 FS_Combas 解码「留存收益」补充表（盈余公积 + 未分配利润）。

用于补齐 Altman Z/Z'' 的 X2（留存收益/总资产），对应缺口 G-13。

科目代码（2026-11-17 以贵州茅台/神州高铁恒等式实测确认）：
- A003103000 = 盈余公积（非字段说明文档所称"库存股"）
- A003105000 = 未分配利润

输出：``data/raw/candidates/balance_sheet_ext.csv``（金额单位：亿元）。
"""

from __future__ import annotations

import pandas as pd

from config import settings
from etl.io_utils import get_logger, write_table

logger = get_logger("balance-ext")

CODES = {"A003103000": "surplus_reserve", "A003105000": "undistributed_profit"}
YEAR_MIN, YEAR_MAX = 2013, 2026
KEY = ["stock_code", "year"]


def build(write: bool = True) -> pd.DataFrame:
    path = settings.RAW_DIR / "FS_Combas.csv"
    header = pd.read_csv(path, nrows=0, encoding="utf-8-sig").columns
    usecols = [c for c in ["Stkcd", "Accper", "Typrep", *CODES] if c in header]

    frames = []
    for chunk in pd.read_csv(path, usecols=usecols, dtype=str, encoding="utf-8-sig",
                             chunksize=200_000, low_memory=False):
        chunk["Accper"] = chunk["Accper"].astype(str).str.strip()
        year = chunk["Accper"].str[:4]
        mask = (
            chunk["Typrep"].astype(str).str.upper().eq("A")
            & chunk["Accper"].str.endswith("-12-31")
            & year.str.isdigit() & year.astype(int).between(YEAR_MIN, YEAR_MAX)
        )
        sub = chunk.loc[mask].copy()
        if sub.empty:
            continue
        sub["year"] = year[mask].astype(int)
        frames.append(sub)

    df = pd.concat(frames, ignore_index=True)
    df["stock_code"] = df["Stkcd"].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    df = df.rename(columns=CODES)
    for col in CODES.values():
        df[col] = pd.to_numeric(df[col], errors="coerce") * 1e-8  # 元 → 亿元

    df = (df.sort_values([*KEY])
            .drop_duplicates(KEY, keep="last"))
    out = df[[*KEY, "surplus_reserve", "undistributed_profit"]].reset_index(drop=True)
    out = out[out[["surplus_reserve", "undistributed_profit"]].notna().any(axis=1)]
    out["retained_earnings"] = (out["surplus_reserve"].fillna(0)
                                + out["undistributed_profit"].fillna(0))

    logger.info("留存收益补充表：%d 行 × %d 列，%d 家公司，年份 %d-%d；未分配利润非空率 %.1f%%",
                len(out), out.shape[1], out["stock_code"].nunique(),
                out["year"].min(), out["year"].max(),
                out["undistributed_profit"].notna().mean() * 100)
    if write:
        target = settings.RAW_DIR / "candidates" / "balance_sheet_ext.csv"
        write_table(out, target)
        logger.info("已写出 %s", settings.rel(target))
    return out


if __name__ == "__main__":
    build(write=True)
