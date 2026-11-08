"""演示数据生成器（无需 CSMAR 权限即可跑通全链路）。

设计目标
--------
1. **结构真实**：生成的是"原始报表科目"而非特征，特征必须由 ETL 计算得出，
   保证 ETL 逻辑被真实执行；
2. **因果关系真实**：用一个潜在风险因子 z 驱动财务科目退化，ST 标签由
   T-2 期的 z 决定，因此模型可学到稳定信号（演示 AUC 约 0.85-0.92）；
3. **可复现**：固定随机种子，同一条命令永远生成同一份数据。

用法
----
    python -m data.gen_demo_data --companies 240
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from config import settings
from config.feature_registry import FEATURES, ID_COLUMNS, TARGET_COLUMN
from etl.io_utils import get_logger, write_table

logger = get_logger("demo-data")

START_YEAR = 2013          # 提前 2 年，便于构造 3 年复合增速与滞后标签
END_YEAR = settings.TEST_YEAR + settings.LABEL_HORIZON  # 2026，供 2024 年样本取标签
ST_RATE = 0.085


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _company_master(n_companies: int, rng: np.random.Generator) -> pd.DataFrame:
    """构造公司主表：代码、简称、行业、规模、基础资质。"""
    industries = list(settings.INDUSTRIES.keys())
    codes = [f"{600000 + i:06d}" if i % 2 == 0 else f"{2000 + i:06d}" for i in range(n_companies)]
    quality = rng.normal(0, 0.55, n_companies)          # 基础经营质量（越低越差）
    size = rng.lognormal(mean=np.log(60), sigma=0.8, size=n_companies)  # 总资产（亿元）
    return pd.DataFrame(
        {
            "stock_code": codes,
            "company_name": [f"示例制造{i + 1:03d}" for i in range(n_companies)],
            "industry": rng.choice(industries, n_companies),
            "quality": quality,
            "base_size": size,
        }
    )


def _risk_path(master: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """潜在风险因子：AR(1) 过程，均值回复到公司自身资质水平。"""
    years = list(range(START_YEAR, END_YEAR + 1))
    rows = []
    for _, comp in master.iterrows():
        level = comp["quality"]
        z = rng.normal(level, 0.4)
        for year in years:
            z = 0.82 * z + 0.18 * level + rng.normal(0, 0.22)
            rows.append({"stock_code": comp["stock_code"], "year": year, "risk_z": z})
    return pd.DataFrame(rows)


def _financial_items(df: pd.DataFrame, master: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """由风险因子推导原始报表科目（单位：亿元）。"""
    n = len(df)
    risk = df["risk_z"].to_numpy()
    size = master.set_index("stock_code").loc[df["stock_code"], "base_size"].to_numpy()

    growth = 0.06 + 0.05 * rng.normal(size=n) - 0.03 * risk
    years_from_start = df["year"].to_numpy() - START_YEAR
    total_assets = size * np.power(1.08, years_from_start) * (1 + 0.05 * rng.normal(size=n))
    total_assets = np.clip(total_assets, 3, None)

    debt_to_asset = np.clip(0.42 + 0.16 * risk + 0.05 * rng.normal(size=n), 0.05, 0.96)
    total_liabilities = total_assets * debt_to_asset
    equity = total_assets - total_liabilities

    revenue = total_assets * np.clip(0.55 + 0.25 * rng.normal(size=n) + growth, 0.05, None)
    gross_margin = np.clip(0.30 - 0.09 * risk + 0.05 * rng.normal(size=n), -0.15, 0.75)
    cost = revenue * (1 - gross_margin)
    opex = revenue * np.clip(0.13 + 0.03 * rng.normal(size=n), 0.02, 0.35)
    ebit = revenue - cost - opex

    interest_debt = total_liabilities * np.clip(0.55 + 0.08 * rng.normal(size=n), 0.1, 0.95)
    interest_expense = interest_debt * 0.048 + 0.01 * total_assets
    net_profit = ebit - interest_expense
    net_profit = net_profit * (1 - 0.15 * (net_profit > 0))
    deducted_profit = net_profit * np.clip(0.85 + 0.15 * rng.normal(size=n), -0.4, 1.3)

    ocf = net_profit * np.clip(0.95 - 0.55 * risk + 0.25 * rng.normal(size=n), -1.5, 2.5)
    capex = np.clip(revenue * 0.07, 0.02, None) * (1 + 0.2 * rng.normal(size=n)).clip(0.3, 2.0)
    icf = -capex * (1 + 0.3 * rng.normal(size=n)).clip(0.3, 2.0)
    fcf_financing = -(ocf + icf) * 0.8 + total_assets * 0.02 * rng.normal(size=n)

    current_ratio = np.clip(2.4 - 1.0 * risk + 0.25 * rng.normal(size=n), 0.35, 6.5)
    current_lia = total_liabilities * np.clip(0.62 + 0.08 * rng.normal(size=n), 0.3, 0.95)
    current_assets = current_lia * current_ratio
    inventory = current_assets * np.clip(0.32 + 0.08 * rng.normal(size=n), 0.05, 0.7)
    cash = current_assets * np.clip(0.30 - 0.10 * risk + 0.06 * rng.normal(size=n), 0.02, 0.7)
    receivables = revenue * np.clip(0.15 + 0.06 * risk + 0.05 * rng.normal(size=n), 0.01, 0.6)
    payable = cost * np.clip(0.16 + 0.05 * rng.normal(size=n), 0.02, 0.5)
    fixed_assets = total_assets * np.clip(0.30 + 0.06 * rng.normal(size=n), 0.05, 0.6)

    short_borrow = total_liabilities * np.clip(0.35 + 0.07 * rng.normal(size=n), 0.05, 0.7)
    lt_debt = total_liabilities * np.clip(0.22 + 0.06 * rng.normal(size=n), 0.0, 0.6)
    total_shares = total_assets * 1.2 + 2 * rng.random(n)
    rd_expense = revenue * np.clip(0.032 + 0.012 * rng.normal(size=n) - 0.004 * risk, 0.0, 0.15)
    depreciation = total_assets * np.clip(0.042 + 0.008 * rng.normal(size=n), 0.01, 0.12)
    audit_fee = np.clip(0.010 + 0.003 * rng.normal(size=n) + 0.001 * total_assets, 0.003, None)

    df = df.assign(
        revenue=revenue, cost=cost, opex=opex, ebit=ebit, net_profit=net_profit,
        deducted_profit=deducted_profit, ocf=ocf, icf=icf, fcf_financing=fcf_financing,
        capex=capex, total_assets=total_assets, total_liabilities=total_liabilities,
        equity=equity, current_assets=current_assets, current_lia=current_lia,
        inventory=inventory, cash=cash, receivables=receivables, payable=payable,
        fixed_assets=fixed_assets, short_borrow=short_borrow, lt_debt=lt_debt,
        interest_debt=interest_debt, interest_expense=interest_expense,
        total_shares=total_shares, rd_expense=rd_expense,
        depreciation=depreciation, audit_fee=audit_fee,
    )

    # 注入真实数据的"脏"特征：约 2% 缺失、1% 极端异常值
    numeric_cols = [c for c in df.columns if df[c].dtype.kind == "f" and c not in {"risk_z"}]
    for col in numeric_cols:
        mask = rng.random(n) < 0.02
        df.loc[mask, col] = np.nan
    for col in ["revenue", "net_profit", "total_assets"]:
        idx = rng.random(n) < 0.005
        df.loc[idx, col] = df.loc[idx, col] * 25
    return df


def _label_table(risk: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """T 年 ST 标签由 T-2 期风险因子决定（避免前视偏差）。"""
    pivot = risk.pivot(index="stock_code", columns="year", values="risk_z")
    labels = []
    for year in pivot.columns:
        lag_year = year - settings.LABEL_HORIZON
        if lag_year not in pivot.columns:
            continue
        z = pivot[lag_year].to_numpy()
        prob = _sigmoid(2.6 * z - 2.35).clip(0.005, 0.9)
        is_st = (rng.random(len(z)) < prob).astype(int)
        labels.append(
            pd.DataFrame({"stock_code": pivot.index, "year": int(year), TARGET_COLUMN: is_st})
        )
    return pd.concat(labels, ignore_index=True)


def _text_features(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    n = len(df)
    risk = df["risk_z"].to_numpy()
    positive = np.clip(_sigmoid(0.9 - 1.1 * risk + 0.5 * rng.normal(size=n)), 0.01, 0.99)
    negative = np.clip(_sigmoid(-1.5 + 1.3 * risk + 0.5 * rng.normal(size=n)), 0.01, 0.99)
    uncertainty = np.clip(_sigmoid(-1.0 + 0.9 * risk + 0.4 * rng.normal(size=n)), 0.01, 0.99)
    volatility = np.clip(0.12 + 0.05 * np.abs(risk) + 0.03 * rng.random(n), 0.01, 0.9)
    forward = np.clip(0.18 + 0.08 * np.abs(risk) + 0.04 * rng.normal(size=n), 0.0, 0.8)
    return pd.DataFrame(
        {
            "stock_code": df["stock_code"],
            "year": df["year"],
            "mdna_positive": positive.round(4),
            "mdna_negative": negative.round(4),
            "mdna_uncertainty": uncertainty.round(4),
            "sentiment_polarity": (positive - negative).round(4),
            "sentiment_volatility": volatility.round(4),
            "forward_looking_ratio": forward.round(4),
        }
    )


def _governance(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    n = len(df)
    risk = df["risk_z"].to_numpy()
    board = rng.integers(5, 16, n).astype(float)
    independent = np.round(board * np.clip(0.36 + 0.04 * rng.normal(size=n), 0.24, 0.6))
    top1 = np.clip(0.34 - 0.04 * risk + 0.06 * rng.normal(size=n), 0.05, 0.85)
    others = np.clip(0.30 + 0.05 * rng.normal(size=n), 0.02, 0.6)
    return pd.DataFrame(
        {
            "stock_code": df["stock_code"],
            "year": df["year"],
            "top1_holding": top1.round(4),
            "top2_5_holding": others.round(4),
            "board_size": board,
            "independent_directors": independent,
            "management_holding": np.clip(0.08 - 0.02 * risk + 0.05 * rng.normal(size=n), 0.0, 0.7).round(4),
            "duality": (rng.random(n) < _sigmoid(0.4 + 0.5 * risk)).astype(int),
            "big4_audit": (rng.random(n) < _sigmoid(-0.4 - 0.5 * risk)).astype(int),
            "institutional_holding": np.clip(0.32 - 0.06 * risk + 0.09 * rng.normal(size=n), 0.0, 0.9).round(4),
        }
    )


def _audit_and_market(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    n = len(df)
    risk = df["risk_z"].to_numpy()
    opinion = (rng.random(n) < _sigmoid(-2.4 + 1.6 * risk)).astype(int)
    return pd.DataFrame(
        {
            "stock_code": df["stock_code"],
            "year": df["year"],
            "audit_opinion": opinion,
            "annual_turnover": np.clip(2.4 - 0.5 * risk + 0.8 * rng.normal(size=n), 0.1, 12).round(3),
            "stock_volatility": np.clip(0.32 + 0.10 * risk + 0.08 * rng.normal(size=n), 0.05, 1.5).round(4),
        }
    )


def _legal_events(master: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for _, comp in master.iterrows():
        for year in range(START_YEAR, END_YEAR + 1):
            lam = np.exp(0.6 + 0.35 * comp["quality"] * -1)
            rows.append(
                {
                    "stock_code": comp["stock_code"],
                    "year": year,
                    "litigation_count": int(rng.poisson(lam)),
                    "penalty_count": int(rng.poisson(lam * 0.4)),
                }
            )
    return pd.DataFrame(rows)


def _macro_table() -> pd.DataFrame:
    data = {
        2013: (7.8, 13.6, 2.6, -1.9, 18.2, 50.5),
        2014: (7.4, 12.2, 2.0, -1.9, 14.3, 50.1),
        2015: (7.0, 13.3, 1.4, -5.2, 12.4, 49.7),
        2016: (6.8, 11.3, 2.0, -1.4, 12.8, 51.4),
        2017: (6.9, 8.2, 1.6, 6.3, 12.0, 51.6),
        2018: (6.7, 8.1, 2.1, 3.5, 10.3, 49.4),
        2019: (6.0, 8.7, 2.9, -0.3, 10.7, 50.2),
        2020: (2.2, 10.1, 2.5, -1.8, 13.3, 51.9),
        2021: (8.4, 9.0, 0.9, 8.1, 10.3, 50.5),
        2022: (3.0, 11.8, 2.0, 4.1, 9.6, 49.1),
        2023: (5.2, 10.0, 0.2, -2.9, 9.5, 49.0),
        2024: (5.0, 7.3, 0.2, -2.2, 8.4, 50.1),
        2025: (4.8, 7.0, 0.4, -1.8, 8.2, 50.3),
        2026: (4.9, 7.2, 0.6, -1.5, 8.3, 50.4),
    }
    cols = ["gdp_growth", "m2_growth", "cpi_yoy", "ppi_yoy", "social_financing_growth", "pmi_manufacturing"]
    return pd.DataFrame(
        [{"year": y, **dict(zip(cols, v))} for y, v in data.items()]
    )


def generate(n_companies: int = 240, seed: int = settings.RANDOM_SEED) -> dict[str, Path]:
    """生成全部原始表，返回 {表名: 路径}。"""
    settings.ensure_dirs()
    rng = np.random.default_rng(seed)

    master = _company_master(n_companies, rng)
    risk = _risk_path(master, rng)
    financial = _financial_items(risk, master, rng)

    # 合并公司静态信息
    static = master[["stock_code", "company_name", "industry"]]
    financial = financial.merge(static, on="stock_code", how="left")
    financial = financial[["stock_code", "company_name", "industry", "year"] + [
        c for c in financial.columns if c not in {"stock_code", "company_name", "industry", "year"}
    ]].drop(columns=["risk_z"])

    labels = _label_table(risk, rng)
    text = _text_features(risk, rng)
    governance = _governance(risk, rng)
    market = _audit_and_market(risk, rng)
    legal = _legal_events(master, rng)
    macro = _macro_table()

    paths = {
        "financial": write_table(financial, settings.RAW_FINANCIAL),
        "governance": write_table(governance, settings.RAW_GOVERNANCE),
        "text": write_table(text, settings.RAW_TEXT_SENTIMENT),
        "legal": write_table(legal, settings.RAW_LEGAL),
        "market": write_table(market, settings.RAW_MARKET),
        "labels": write_table(labels, settings.RAW_LABELS),
        "macro": write_table(macro, settings.RAW_MACRO),
    }

    pos = labels[TARGET_COLUMN].mean()
    logger.info("演示数据生成完成：%d 家公司 × %d 年", n_companies, END_YEAR - START_YEAR + 1)
    logger.info("财务主表 %s 行，ST 样本占比 %.2f%%", len(financial), pos * 100)
    logger.info("特征注册表共 %d 维，覆盖 %d 个维度", len(FEATURES), len(set(f.group for f in FEATURES)))
    for name, path in paths.items():
        logger.info("  %-12s → %s", name, settings.rel(path))
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="生成演示用原始数据")
    parser.add_argument("--companies", type=int, default=240, help="公司数量（默认 240）")
    parser.add_argument("--seed", type=int, default=settings.RANDOM_SEED, help="随机种子")
    args = parser.parse_args()
    generate(args.companies, args.seed)


if __name__ == "__main__":
    main()
