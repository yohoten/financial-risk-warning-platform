"""特征工程：从原始报表科目构建 70+ 维特征面板。

特征口径全部以 `config/feature_registry.py` 为准，本模块只负责"算出来"，
不做筛选（筛选在 feature_selection.py），不做建模（在 models/train.py）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import settings
from config.feature_registry import FEATURE_KEYS, ID_COLUMNS, TARGET_COLUMN, group_of
from etl.clean_financial import clean_panel
from etl.clean_text import clean_sentiment
from etl.io_utils import get_logger, read_table, write_table

logger = get_logger("features")

KEY = ["stock_code", "year"]
EPS = 1e-9


def _div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """安全除法：分母为 0 或缺失时返回 NaN，避免 inf 污染特征。"""
    denom = denominator.replace(0, np.nan)
    return (numerator / denom).replace([np.inf, -np.inf], np.nan)


# ---------------------------------------------------------------------------
# 各维度特征
# ---------------------------------------------------------------------------
def _solvency(d: pd.DataFrame) -> pd.DataFrame:
    ebitda = d["ebit"] + d["depreciation"]
    d["current_ratio"] = _div(d["current_assets"], d["current_lia"])
    d["quick_ratio"] = _div(d["current_assets"] - d["inventory"], d["current_lia"])
    d["cash_ratio"] = _div(d["cash"], d["current_lia"])
    d["debt_to_asset"] = _div(d["total_liabilities"], d["total_assets"])
    d["equity_multiplier"] = _div(d["total_liabilities"], d["equity"])
    d["interest_coverage"] = _div(d["ebit"], d["interest_expense"])
    d["lt_debt_to_ebitda"] = _div(d["lt_debt"], ebitda)
    d["short_debt_ratio"] = _div(d["short_borrow"], d["total_liabilities"])
    d["interest_debt_ratio"] = _div(d["interest_debt"], d["total_assets"])
    d["ocf_to_debt"] = _div(d["ocf"], d["total_liabilities"])
    return d


def _profitability(d: pd.DataFrame) -> pd.DataFrame:
    ebitda = d["ebit"] + d["depreciation"]
    d["roa"] = _div(d["net_profit"], d["total_assets"])
    d["roe"] = _div(d["net_profit"], d["equity"])
    d["gross_margin"] = _div(d["revenue"] - d["cost"], d["revenue"])
    d["net_margin"] = _div(d["net_profit"], d["revenue"])
    d["ebitda_margin"] = _div(ebitda, d["revenue"])
    d["cost_profit_ratio"] = _div(d["ebit"], d["cost"] + d["opex"])
    d["operating_margin"] = _div(d["ebit"], d["revenue"])
    d["deducted_profit_ratio"] = _div(d["deducted_profit"], d["net_profit"].abs())
    d["eps"] = _div(d["net_profit"], d["total_shares"])
    d["roe_change"] = d.groupby("stock_code")["roe"].diff()
    return d


def _operation(d: pd.DataFrame) -> pd.DataFrame:
    d["ar_turnover"] = _div(d["revenue"], d["receivables"])
    d["inventory_turnover"] = _div(d["cost"], d["inventory"])
    d["asset_turnover"] = _div(d["revenue"], d["total_assets"])
    d["fixed_asset_turnover"] = _div(d["revenue"], d["fixed_assets"])
    d["working_capital_turnover"] = _div(d["revenue"], d["current_assets"] - d["current_lia"])
    dso = _div(pd.Series(365.0, index=d.index), d["ar_turnover"])
    dio = _div(pd.Series(365.0, index=d.index), d["inventory_turnover"])
    dpo = _div(pd.Series(365.0, index=d.index), _div(d["cost"], d["payable"]))
    d["cash_conversion_cycle"] = dso + dio - dpo
    d["payable_days"] = dpo
    d["ar_to_revenue"] = _div(d["receivables"], d["revenue"])
    d["inventory_to_assets"] = _div(d["inventory"], d["total_assets"])
    d["ocf_to_revenue"] = _div(d["ocf"], d["revenue"])
    return d


def _growth(d: pd.DataFrame) -> pd.DataFrame:
    g = d.groupby("stock_code", group_keys=False)
    d["revenue_growth"] = g["revenue"].pct_change(fill_method=None)
    d["profit_growth"] = _div(
        d["net_profit"] - g["net_profit"].shift(1), g["net_profit"].shift(1).abs()
    )
    d["asset_growth"] = g["total_assets"].pct_change(fill_method=None)
    d["equity_growth"] = g["equity"].pct_change(fill_method=None)
    d["ocf_growth"] = g["ocf"].pct_change(fill_method=None)
    d["rd_growth"] = g["rd_expense"].pct_change(fill_method=None)
    d["capex_to_depreciation"] = _div(d["capex"], d["depreciation"])

    # 3 年复合增速：(本期/3年前)^(1/3)-1
    base = g["revenue"].shift(3)
    with np.errstate(invalid="ignore"):
        d["revenue_cagr_3y"] = np.where(
            (base > 0) & (d["revenue"] > 0), np.power(d["revenue"] / base, 1 / 3) - 1, np.nan
        )
    return d


def _cashflow(d: pd.DataFrame) -> pd.DataFrame:
    fcf = d["ocf"] - d["capex"]
    d["ocf_to_net_profit"] = _div(d["ocf"], d["net_profit"].abs())
    d["fcf_to_assets"] = _div(fcf, d["total_assets"])
    d["icf_to_assets"] = _div(d["icf"], d["total_assets"])
    d["financing_to_assets"] = _div(d["fcf_financing"], d["total_assets"])
    d["cash_to_assets"] = _div(d["cash"], d["total_assets"])

    mean3 = d.groupby("stock_code")["ocf"].transform(
        lambda s: s.rolling(3, min_periods=2).mean()
    )
    std3 = d.groupby("stock_code")["ocf"].transform(
        lambda s: s.rolling(3, min_periods=2).std()
    )
    d["ocf_volatility"] = _div(std3, mean3.abs())

    # 自由现金流连续为负年数
    is_neg = (fcf < 0).astype(int)
    run_id = (is_neg == 0).groupby(d["stock_code"]).cumsum()
    d["fcf_negative_years"] = is_neg.groupby([d["stock_code"], run_id]).cumsum()
    return d


def _governance_derived(d: pd.DataFrame) -> pd.DataFrame:
    """治理类衍生指标（依赖治理主表，须在 merge 之后调用）。"""
    if {"top2_5_holding", "top1_holding"}.issubset(d.columns):
        d["equity_balance"] = _div(d["top2_5_holding"], d["top1_holding"])
    if {"independent_directors", "board_size"}.issubset(d.columns):
        d["independent_ratio"] = _div(d["independent_directors"], d["board_size"])
    return d


def _audit_derived(d: pd.DataFrame) -> pd.DataFrame:
    d["audit_fee_ratio"] = _div(d["audit_fee"], d["total_assets"])
    return d


def _macro_gaps(d: pd.DataFrame) -> pd.DataFrame:
    """行业基准偏离度：同一行业-年度内的中位数作为基准。"""
    for src, gap in (("roa", "industry_roa_gap"), ("debt_to_asset", "industry_debt_gap")):
        median = d.groupby(["industry", "year"])[src].transform("median")
        d[gap] = d[src] - median
    return d


# ---------------------------------------------------------------------------
# 面板构建
# ---------------------------------------------------------------------------
def compute_features(financial: pd.DataFrame) -> pd.DataFrame:
    """按维度串联计算全部财务衍生特征。"""
    d = financial.sort_values(KEY).copy()
    d = _solvency(d)
    d = _profitability(d)
    d = _operation(d)
    d = _growth(d)
    d = _cashflow(d)
    d = _audit_derived(d)
    d = _macro_gaps(d)
    d = d.replace([np.inf, -np.inf], np.nan)
    return d


def sync_label(features: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """把 T 年标签回挂到 T-horizon 年的特征上（避免前视偏差）。

    例：2022 年的特征行，标签取自 2024 年是否被 ST。
    """
    lagged = labels.copy()
    lagged["year"] = lagged["year"] - settings.LABEL_HORIZON
    lagged = lagged.rename(columns={TARGET_COLUMN: f"{TARGET_COLUMN}_t{settings.LABEL_HORIZON}"})
    out = features.merge(lagged, on=KEY, how="left")
    out = out.rename(columns={f"{TARGET_COLUMN}_t{settings.LABEL_HORIZON}": TARGET_COLUMN})
    return out


def _normalize_keys(df: pd.DataFrame) -> pd.DataFrame:
    """统一主键类型：stock_code 补零为 6 位字符串，year 转整型。

    CSV 往返会把 "002000" 读成整数 2000，若不统一，多表合并会静默丢样本。
    """
    out = df.copy()
    if "stock_code" in out.columns:
        out["stock_code"] = out["stock_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    if "year" in out.columns:
        out["year"] = pd.to_numeric(out["year"], errors="coerce").astype(int)
    return out


def build_panel(
    financial: pd.DataFrame | None = None,
    governance: pd.DataFrame | None = None,
    sentiment: pd.DataFrame | None = None,
    market: pd.DataFrame | None = None,
    legal: pd.DataFrame | None = None,
    labels: pd.DataFrame | None = None,
    macro: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """构建特征面板：清洗 → 衍生 → 宽表合并 → 标签对齐 → 年份筛选。"""
    settings.ensure_dirs()
    financial = financial if financial is not None else read_table(settings.RAW_FINANCIAL)
    governance = governance if governance is not None else read_table(settings.RAW_GOVERNANCE)
    sentiment = sentiment if sentiment is not None else read_table(settings.RAW_TEXT_SENTIMENT)
    market = market if market is not None else read_table(settings.RAW_MARKET)
    legal = legal if legal is not None else read_table(settings.RAW_LEGAL)
    labels = labels if labels is not None else read_table(settings.RAW_LABELS)
    macro = macro if macro is not None else read_table(settings.RAW_MACRO)

    financial, governance = _normalize_keys(financial), _normalize_keys(governance)
    sentiment, market = _normalize_keys(sentiment), _normalize_keys(market)
    legal, labels = _normalize_keys(legal), _normalize_keys(labels)
    macro = _normalize_keys(macro)

    numeric_cols = [
        c for c in financial.columns
        if c not in {"stock_code", "company_name", "industry"} and pd.api.types.is_numeric_dtype(financial[c])
    ]
    financial = clean_panel(financial, numeric_cols)
    panel = compute_features(financial)

    panel = panel.merge(governance, on=KEY, how="left", suffixes=("", "_gov"))
    panel = _governance_derived(panel)
    panel = panel.merge(clean_sentiment(sentiment), on=KEY, how="left")
    panel = panel.merge(market, on=KEY, how="left", suffixes=("", "_mkt"))
    panel = panel.merge(legal, on=KEY, how="left")
    panel = panel.merge(macro, on="year", how="left")
    panel = sync_label(panel, labels)

    # 只保留建模窗口内的样本，且标签可得
    keep_years = settings.PANEL_YEARS
    panel = panel[panel["year"].isin(keep_years)]
    panel = panel[panel[TARGET_COLUMN].notna()].copy()
    panel[TARGET_COLUMN] = panel[TARGET_COLUMN].astype(int)

    # 特征缺失兜底：行业-年度中位数，剩余置 0
    missing_cols = [c for c in FEATURE_KEYS if c in panel.columns]
    panel[missing_cols] = panel[missing_cols].replace([np.inf, -np.inf], np.nan)
    panel[missing_cols] = panel[missing_cols].fillna(
        panel.groupby(["industry", "year"])[missing_cols].transform("median")
    )
    panel[missing_cols] = panel[missing_cols].fillna(0.0)

    unknown = [k for k in FEATURE_KEYS if k not in panel.columns]
    if unknown:
        logger.warning("以下特征在数据中缺失，已补 0：%s", unknown)
        for col in unknown:
            panel[col] = 0.0

    ordered = ID_COLUMNS + [TARGET_COLUMN] + FEATURE_KEYS
    extras = [c for c in ["total_assets", "revenue", "net_profit", "ocf"] if c in panel.columns]
    panel = panel[ordered + extras].sort_values(KEY).reset_index(drop=True)

    logger.info(
        "特征面板构建完成：%d 行 × %d 维特征，正样本率 %.2f%%，时间跨度 %d-%d",
        len(panel), len(FEATURE_KEYS), panel[TARGET_COLUMN].mean() * 100,
        int(panel["year"].min()), int(panel["year"].max()),
    )
    groups = pd.Series(group_of(FEATURE_KEYS)).value_counts().to_dict()
    logger.info("维度分布：%s", groups)
    return panel


def main() -> None:
    panel = build_panel()
    write_table(panel, settings.FEATURE_PANEL)
    logger.info("已写出：%s", settings.rel(settings.FEATURE_PANEL))


if __name__ == "__main__":
    main()
