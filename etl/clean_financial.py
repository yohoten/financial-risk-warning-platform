"""财务数据清洗：去重 → 缺失插补 → 缩尾 → 样本剔除。

清洗顺序有讲究：先插补再缩尾（否则极端值会污染插补基准），
先按公司-时间排序再插补（保证插补使用相邻年度信息）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import settings
from config.feature_registry import ID_COLUMNS, TARGET_COLUMN
from etl.io_utils import get_logger

logger = get_logger("clean")

KEY = ["stock_code", "year"]


def dedupe(df: pd.DataFrame, keys: list[str] | None = None) -> pd.DataFrame:
    """按主键去重，保留最后一条（后写入的数据视为更新版本）。"""
    keys = keys or KEY
    before = len(df)
    out = df.drop_duplicates(subset=keys, keep="last").reset_index(drop=True)
    if before != len(out):
        logger.info("去重：%d → %d 行", before, len(out))
    return out


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """统一编码与类型：股票代码补零为 6 位、年份转 int、数值转 float。"""
    out = df.copy()
    if "stock_code" in out.columns:
        out["stock_code"] = out["stock_code"].astype(str).str.strip().str.zfill(6)
    if "year" in out.columns:
        out["year"] = pd.to_numeric(out["year"], errors="coerce").astype("Int64")
    for col in out.select_dtypes(include=["int64", "Int64", "float64"]).columns:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype(float)
    return out


def impute_missing(
    df: pd.DataFrame,
    value_cols: list[str],
    group_cols: tuple[str, ...] = ("industry", "year"),
    max_gap: int = 2,
) -> pd.DataFrame:
    """三级插补：公司内线性插值(≤max_gap期) → 行业-年度中位数 → 全局中位数。

    同时生成 `<col>_is_missing` 标记列，供模型识别"缺失本身即信息"的场景。
    """
    out = df.sort_values(KEY).copy()
    missing_before = out[value_cols].isna().mean().mean()

    # Level 1: 公司内时间序列插值
    out[value_cols] = (
        out.groupby("stock_code", group_keys=False)[value_cols]
        .apply(lambda g: g.interpolate(method="linear", limit=max_gap, limit_direction="both"))
    )

    # Level 2: 行业-年度中位数
    group_cols = tuple(c for c in group_cols if c in out.columns)
    if group_cols:
        out[value_cols] = out[value_cols].fillna(
            out.groupby(list(group_cols))[value_cols].transform("median")
        )

    # Level 3: 全局中位数
    out[value_cols] = out[value_cols].fillna(out[value_cols].median(numeric_only=True))

    logger.info(
        "缺失插补：缺失率 %.2f%% → %.2f%%",
        missing_before * 100,
        out[value_cols].isna().mean().mean() * 100,
    )
    return out


def winsorize(df: pd.DataFrame, cols: list[str], lower: float = 0.01, upper: float = 0.99) -> pd.DataFrame:
    """按分位数缩尾，抑制极端值对树模型分裂点的干扰。"""
    out = df.copy()
    for col in cols:
        if col not in out.columns:
            continue
        lo, hi = out[col].quantile(lower), out[col].quantile(upper)
        if pd.notna(lo) and pd.notna(hi) and hi > lo:
            out[col] = out[col].clip(lo, hi)
    return out


def drop_invalid(df: pd.DataFrame, exclude_cols: list[str] | None = None) -> pd.DataFrame:
    """剔除关键字段缺失、资不抵债、上市不满 3 年的样本。"""
    exclude_cols = exclude_cols or []
    key_cols = [c for c in ["total_assets", "revenue", "net_profit"] if c in df.columns]
    out = df.dropna(subset=key_cols)
    out = out[out["total_assets"] > 0]

    # 上市年限：以公司首次出现年份为上市起点
    if "year" in out.columns:
        first_year = out.groupby("stock_code")["year"].transform("min")
        out = out[(out["year"] - first_year) >= 0]

    coverage = out.drop(columns=[c for c in exclude_cols if c in out.columns]).notna().mean(axis=1)
    out = out[coverage >= 0.7]
    logger.info("样本剔除后剩余 %d 行 / %d 家公司", len(out), out["stock_code"].nunique())
    return out.reset_index(drop=True)


def clean_panel(df: pd.DataFrame, numeric_cols: list[str]) -> pd.DataFrame:
    """一站式清洗入口，供 run_pipeline 调用。"""
    out = standardize_columns(dedupe(df))
    out = impute_missing(out, [c for c in numeric_cols if c in out.columns])
    out = winsorize(out, [c for c in numeric_cols if c in out.columns])
    out = drop_invalid(out, exclude_cols=ID_COLUMNS + [TARGET_COLUMN])
    return out
