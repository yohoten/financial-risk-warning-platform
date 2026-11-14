"""数据探索（EDA）：标签、财务分布、治理、司法、行业与候选特征关联。

输出：
    reports/eda/*.csv
    reports/eda/eda_summary.json
    reports/figures/eda_*.png

运行：
    python -m scripts.run_data_eda
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CAND = RAW / "candidates"
EXT = ROOT / "data" / "external"
OUT = ROOT / "reports" / "eda"
FIG = ROOT / "reports" / "figures"
OUT.mkdir(parents=True, exist_ok=True)
FIG.mkdir(parents=True, exist_ok=True)

KEY = ["stock_code", "year"]
A_SHARE_PREFIXES = {"000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688", "689"}
GROUP_CN = {
    "solvency": "偿债",
    "profitability": "盈利",
    "operation": "营运",
    "growth": "成长",
    "cashflow": "现金流",
    "text": "文本",
    "governance": "治理",
    "audit_market_legal": "审计/市场/司法",
    "macro_industry": "宏观/行业",
}
COLORS = {
    "blue": "#2F5597",
    "light_blue": "#8FAADC",
    "orange": "#C55A11",
    "red": "#C00000",
    "green": "#548235",
    "gray": "#7F7F7F",
    "light_gray": "#D9D9D9",
}

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "figure.dpi": 120,
    "savefig.dpi": 220,
    "axes.titlesize": 12,
    "axes.labelsize": 10,
    "legend.fontsize": 9,
})


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


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return float("nan"), float("nan")
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def add_ci(df: pd.DataFrame, k: str, n: str, prefix: str = "ci") -> pd.DataFrame:
    intervals = [wilson(int(a), int(b)) for a, b in zip(df[k], df[n])]
    df[f"{prefix}_low"] = [x[0] for x in intervals]
    df[f"{prefix}_high"] = [x[1] for x in intervals]
    return df


def winsorize(s: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    lo, hi = x.quantile(lower), x.quantile(upper)
    return x.clip(lo, hi)


def plot_box(ax, df: pd.DataFrame, col: str, title: str) -> None:
    x = pd.to_numeric(df[col], errors="coerce")
    x = x.clip(x.quantile(0.01), x.quantile(0.99))
    groups = [x[df["is_st"].eq(0)].dropna(), x[df["is_st"].eq(1)].dropna()]
    bp = ax.boxplot(groups, tick_labels=["非 ST", "ST"], patch_artist=True, showfliers=False,
                    widths=0.55, medianprops={"color": "white", "linewidth": 1.3})
    for patch, color in zip(bp["boxes"], [COLORS["light_blue"], COLORS["orange"]]):
        patch.set_facecolor(color)
        patch.set_alpha(0.9)
    for i, g in enumerate(groups):
        if len(g):
            ax.text(i + 1, g.median(), f"{g.median():.3f}", ha="center", va="bottom",
                    fontsize=8, color="#333333")
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.25)
    ax.text(0.02, 0.98, f"n={len(groups[0]):,} / {len(groups[1]):,}", transform=ax.transAxes,
            va="top", fontsize=8, color=COLORS["gray"])


def load_data() -> dict:
    fin = read(RAW / "csmar_financial.csv", dtype={"stock_code": str})
    fin["stock_code"] = code(fin["stock_code"])
    fin["year"] = pd.to_numeric(fin["year"], errors="coerce")
    fin = fin.dropna(subset=KEY).copy()
    fin["year"] = fin["year"].astype(int)
    fin = fin[fin["stock_code"].str[:3].isin(A_SHARE_PREFIXES)].copy()

    # 现金流双缩放修正：在线 raw 仍是旧值，EDA 用候选修正值替换四个现金流列。
    cashflow_source = "active_raw_double_scaled"
    fixed_path = CAND / "csmar_financial_cashflow_fixed.csv"
    if fixed_path.exists():
        fixed = read(fixed_path, dtype={"stock_code": str},
                     usecols=[*KEY, "ocf", "icf", "fcf_financing", "capex"])
        fixed["stock_code"] = code(fixed["stock_code"])
        fixed["year"] = pd.to_numeric(fixed["year"], errors="coerce").astype(int)
        fin = fin.drop(columns=["ocf", "icf", "fcf_financing", "capex"]).merge(
            fixed, on=KEY, how="left", validate="one_to_one"
        )
        cashflow_source = "candidate_cashflow_fixed"

    official = read(CAND / "labels_st_official.csv", dtype={"stock_code": str})
    proxy = read(RAW / "labels_st.csv", dtype={"stock_code": str})
    for frame in (official, proxy):
        frame["stock_code"] = code(frame["stock_code"])
        frame["year"] = pd.to_numeric(frame["year"], errors="coerce")
        frame["is_st"] = pd.to_numeric(frame["is_st"], errors="coerce")
        frame.dropna(subset=[*KEY, "is_st"], inplace=True)
        frame["year"] = frame["year"].astype(int)

    gov = read(CAND / "governance_ext.csv", dtype={"stock_code": str})
    gov["stock_code"] = code(gov["stock_code"])
    gov["year"] = pd.to_numeric(gov["year"], errors="coerce")
    gov = gov.dropna(subset=KEY).copy()
    gov["year"] = gov["year"].astype(int)
    for c in ["duality", "board_size_cg", "independent_ratio_cg", "management_holding_cg",
              "supervisor_size", "executives_number", "control_proportion"]:
        gov[c] = pd.to_numeric(gov[c], errors="coerce")

    legal = read(CAND / "legal_events.csv", dtype={"stock_code": str})
    legal["stock_code"] = code(legal["stock_code"])
    legal["year"] = pd.to_numeric(legal["year"], errors="coerce")
    legal = legal.dropna(subset=KEY).copy()
    legal["year"] = legal["year"].astype(int)
    for c in ["litigation_count", "penalty_count", "lawsuit_amount_cny", "penalty_amount_sum",
              "non_cny_count", "legal_event_count", "has_lawsuit", "has_penalty"]:
        legal[c] = pd.to_numeric(legal[c], errors="coerce")

    market = read(RAW / "market_features.csv", dtype={"stock_code": str})
    market["stock_code"] = code(market["stock_code"])
    market["year"] = pd.to_numeric(market["year"], errors="coerce")
    market = market.dropna(subset=KEY).copy()
    market["year"] = market["year"].astype(int)

    trd = read(CAND / "TRD_Dly_company_year_2013_2026.csv", dtype={"Stkcd": str})
    trd["stock_code"] = code(trd["Stkcd"])
    trd["year"] = pd.to_numeric(trd["year"], errors="coerce")
    trd = trd.dropna(subset=KEY).copy()
    trd["year"] = trd["year"].astype(int)
    for c in ["trading_days", "annual_turnover", "stock_volatility", "annual_return"]:
        trd[c] = pd.to_numeric(trd[c], errors="coerce")
    trd = trd.rename(columns={"annual_return": "trd_annual_return"})

    readiness = read(ROOT / "reports" / "data_quality" / "feature_readiness_20261114.csv")
    return {"fin": fin, "official": official, "proxy": proxy, "gov": gov,
            "legal": legal, "market": market, "trd": trd, "readiness": readiness,
            "cashflow_source": cashflow_source}


def build_base(data: dict) -> pd.DataFrame:
    base = data["fin"].merge(data["official"], on=KEY, how="left", suffixes=("", "_label"))
    base = base.merge(data["market"][[*KEY, "audit_opinion"]], on=KEY, how="left")
    base = base.merge(data["gov"][[*KEY, "duality", "board_size_cg", "independent_ratio_cg"]],
                      on=KEY, how="left")
    base = base.merge(data["legal"][[*KEY, "litigation_count", "penalty_count", "has_lawsuit",
                                    "has_penalty", "lawsuit_amount_cny", "non_cny_count"]],
                      on=KEY, how="left")
    base = base.merge(data["trd"][[*KEY, "annual_turnover", "stock_volatility",
                                     "trading_days", "trd_annual_return"]],
                      on=KEY, how="left")
    for c in ["litigation_count", "penalty_count", "has_lawsuit", "has_penalty"]:
        base[c] = base[c].fillna(0)
    base["debt_to_asset"] = base["total_liabilities"] / base["total_assets"]
    base["roa"] = base["net_profit"] / base["total_assets"]
    base["current_ratio"] = base["current_assets"] / base["current_lia"]
    base["ocf_to_assets"] = base["ocf"] / base["total_assets"]
    base["net_margin"] = base["net_profit"] / base["revenue"]
    base["asset_turnover"] = base["revenue"] / base["total_assets"]
    return base


def label_tables(data: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    fin = data["fin"]
    rows = []
    for year, part in fin.groupby("year"):
        rows.append({
            "year": int(year),
            "financial_company_years": int(len(part)),
            "financial_companies": int(part["stock_code"].nunique()),
        })
    tab = pd.DataFrame(rows)

    for name, frame in [("proxy", data["proxy"]), ("official", data["official"])]:
        g = frame.groupby("year").agg(n=("is_st", "size"), positive=("is_st", "sum")).reset_index()
        g = g.rename(columns={"n": f"{name}_rows", "positive": f"{name}_positive"})
        g[f"{name}_rate"] = g[f"{name}_positive"] / g[f"{name}_rows"]
        tab = tab.merge(g[["year", f"{name}_rows", f"{name}_positive", f"{name}_rate"]],
                        on="year", how="left")

        f = frame.sort_values(["stock_code", "year"]).copy()
        f["prev_year"] = f.groupby("stock_code")["year"].shift(1)
        f["prev_st"] = f.groupby("stock_code")["is_st"].shift(1)
        f["first_st"] = (f["is_st"].eq(1) & f["prev_year"].eq(f["year"] - 1) & f["prev_st"].eq(0))
        first = f.groupby("year")["first_st"].sum().rename(f"first_st_{name}")
        tab = tab.merge(first, left_on="year", right_index=True, how="left")
        tab[f"first_st_{name}"] = tab[f"first_st_{name}"].fillna(0).astype(int)
    tab = tab.fillna({"proxy_positive": 0, "official_positive": 0})
    for c in ["proxy_positive", "official_positive"]:
        tab[c] = tab[c].astype(int)
    return tab


def financial_table(base: pd.DataFrame) -> pd.DataFrame:
    cols = {
        "debt_to_asset": "资产负债率",
        "roa": "总资产收益率 ROA",
        "current_ratio": "流动比率",
        "ocf_to_assets": "经营现金流/总资产",
        "net_margin": "销售净利率",
        "asset_turnover": "总资产周转率",
    }
    rows = []
    for col, cn in cols.items():
        x = pd.to_numeric(base[col], errors="coerce")
        lo, hi = x.quantile(0.01), x.quantile(0.99)
        x = x.clip(lo, hi)
        s0, s1 = x[base["is_st"].eq(0)].dropna(), x[base["is_st"].eq(1)].dropna()
        smd = (s1.mean() - s0.mean()) / np.sqrt((s1.var() + s0.var()) / 2) if len(s1) and len(s0) else np.nan
        rows.append({
            "variable": col, "cn": cn,
            "n_non_st": int(len(s0)), "n_st": int(len(s1)),
            "mean_non_st": float(s0.mean()), "median_non_st": float(s0.median()),
            "mean_st": float(s1.mean()), "median_st": float(s1.median()),
            "missing_rate": float(base[col].isna().mean()),
            "smd_st_minus_non": float(smd),
        })
    return pd.DataFrame(rows)


def governance_table(data: dict) -> pd.DataFrame:
    gov = data["gov"]
    rows = []
    for year, part in gov.groupby("year"):
        nonnull = part["duality"].dropna()
        k, n = int(nonnull.sum()), int(len(nonnull))
        lo, hi = wilson(k, n)
        rows.append({
            "year": int(year), "rows": int(len(part)),
            "duality_n": n, "duality_positive": k, "duality_rate": k / n if n else np.nan,
            "duality_ci_low": lo, "duality_ci_high": hi,
            "board_size_mean": float(part["board_size_cg"].mean()),
            "independent_ratio_mean": float(part["independent_ratio_cg"].mean()),
            "management_holding_mean": float(part["management_holding_cg"].mean()),
            "control_proportion_mean": float(part["control_proportion"].mean()),
        })
    return pd.DataFrame(rows)


def legal_table(data: dict) -> pd.DataFrame:
    legal = data["legal"]
    rows = []
    for year, part in legal.groupby("year"):
        n = len(part)
        k_law, k_pen = int(part["has_lawsuit"].sum()), int(part["has_penalty"].sum())
        ci_law, ci_pen = wilson(k_law, n), wilson(k_pen, n)
        rows.append({
            "year": int(year), "rows": n,
            "lawsuit_company_years": k_law, "lawsuit_prevalence": k_law / n,
            "lawsuit_ci_low": ci_law[0], "lawsuit_ci_high": ci_law[1],
            "penalty_company_years": k_pen, "penalty_prevalence": k_pen / n,
            "penalty_ci_low": ci_pen[0], "penalty_ci_high": ci_pen[1],
            "lawsuits": int(part["litigation_count"].sum()),
            "penalties": int(part["penalty_count"].sum()),
            "lawsuit_amount_cny_bn": float(part["lawsuit_amount_cny"].sum() / 1e9),
            "non_cny_events": int(part["non_cny_count"].sum()),
            "coverage_note": "full A-share key grid" if year < 2026 else "observed 2026 event keys only; not comparable",
        })
    return pd.DataFrame(rows)


def association_table(base: pd.DataFrame) -> pd.DataFrame:
    fut = pd.DataFrame({
        "stock_code": base["stock_code"],
        "year": base["year"] - 2,
        "is_st_t2": base["is_st"],
    })
    t2 = base.merge(fut, on=KEY, how="left", suffixes=("", "_future"))
    rows = []
    for horizon, frame, target in [
        ("same_year", base, "is_st"),
        ("t_plus_2", t2, "is_st_t2"),
    ]:
        for feature in ["has_lawsuit", "has_penalty", "duality"]:
            d = frame.dropna(subset=[feature, target]).copy()
            d[feature] = pd.to_numeric(d[feature], errors="coerce")
            for value, part in d.groupby(feature):
                k, n = int(part[target].sum()), int(len(part))
                lo, hi = wilson(k, n)
                rows.append({
                    "horizon": horizon, "feature": feature, "value": int(value),
                    "n": n, "st_positive": k, "st_rate": k / n,
                    "ci_low": lo, "ci_high": hi,
                })
    return pd.DataFrame(rows)


def market_table(base: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, flag in [("non_st", 0), ("st", 1)]:
        part = base[base["is_st"].eq(flag) & base["year"].le(2025)]
        rows.append({
            "group": label,
            "n": int(len(part)),
            "turnover_n": int(part["annual_turnover"].notna().sum()),
            "turnover_median": float(part["annual_turnover"].median()),
            "turnover_p90": float(part["annual_turnover"].quantile(0.90)),
            "volatility_n": int(part["stock_volatility"].notna().sum()),
            "volatility_median": float(part["stock_volatility"].median()),
            "volatility_p90": float(part["stock_volatility"].quantile(0.90)),
            "trd_return_median": float(part["trd_annual_return"].median()),
        })
    return pd.DataFrame(rows)


def industry_table(base: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for industry, part in base.groupby("industry"):
        k, n = int(part["is_st"].sum()), int(len(part))
        lo, hi = wilson(k, n)
        rows.append({
            "industry": industry, "rows": n, "companies": int(part["stock_code"].nunique()),
            "st_positive": k, "st_rate": k / n,
            "ci_low": lo, "ci_high": hi,
        })
    tab = pd.DataFrame(rows).sort_values("rows", ascending=False).reset_index(drop=True)
    return tab


def load_industry_names() -> dict[str, str]:
    path = RAW / "basic_info.csv"
    try:
        info = pd.read_csv(path, encoding="utf-8-sig", dtype=str,
                           usecols=["IndustryCodeC", "IndustryNameC"], low_memory=False)
        info = info.dropna(subset=["IndustryCodeC", "IndustryNameC"]).drop_duplicates("IndustryCodeC")
        return dict(zip(info["IndustryCodeC"].str.strip(), info["IndustryNameC"].str.strip()))
    except Exception:
        return {}


def plot_label_trend(tab: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), constrained_layout=True)
    ax = axes[0]
    x = tab["year"]
    ax.bar(x - 0.2, tab["official_positive"], width=0.4, color=COLORS["blue"], label="ST 状态正样本")
    ax.bar(x + 0.2, tab["first_st_official"], width=0.4, color=COLORS["orange"], label="首次 ST")
    ax.set_title("官方 ST 标签：状态正样本与首次 ST")
    ax.set_xlabel("年份")
    ax.set_ylabel("公司-年数")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    ax2 = ax.twinx()
    ax2.plot(x, tab["financial_company_years"], color=COLORS["gray"], marker="o", ms=3, lw=1.2,
             label="财务公司-年（右轴）")
    ax2.set_ylabel("财务公司-年数", color=COLORS["gray"])
    ax2.tick_params(axis="y", colors=COLORS["gray"])
    ax2.legend(loc="upper left", frameon=False)

    ax = axes[1]
    ax.plot(x, tab["official_rate"], color=COLORS["red"], marker="o", lw=2, label="官方：ST 状态率")
    ax.plot(x, tab["proxy_rate"], color=COLORS["gray"], marker="s", lw=1.5, ls="--", label="代理：ST 状态率")
    ax.plot(x, tab["first_st_official"] / tab["financial_company_years"], color=COLORS["orange"],
            marker="^", lw=1.2, ls=":", label="官方：首次 ST 率")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_title("ST 正样本率：官方 vs 代理")
    ax.set_xlabel("年份")
    ax.set_ylabel("占财务公司-年比例")
    ax.grid(alpha=0.25)
    ax.legend(frameon=False)
    fig.savefig(FIG / "eda_01_label_trend.png", bbox_inches="tight")
    plt.close(fig)


def plot_feature_availability(readiness: pd.DataFrame) -> None:
    group = readiness.groupby("group").agg(features=("feature", "size"), all_zero=("all_zero", "sum")).reset_index()
    group["available"] = group["features"] - group["all_zero"]
    group["group_cn"] = group["group"].map(GROUP_CN).fillna(group["group"])
    group = group.sort_values("features", ascending=True)
    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    ax.barh(group["group_cn"], group["available"], color=COLORS["blue"], label="非零/有变异")
    ax.barh(group["group_cn"], group["all_zero"], left=group["available"], color=COLORS["light_gray"],
            label="全零常量")
    for i, row in group.reset_index(drop=True).iterrows():
        ax.text(row["features"] + 0.15, i, f"{int(row['available'])}/{int(row['features'])}",
                va="center", fontsize=9, color=COLORS["gray"])
    ax.set_xlabel("特征数")
    ax.set_title("73 维候选特征的实际可用性（当前特征面板）")
    ax.set_xlim(0, 12)
    ax.grid(axis="x", alpha=0.25)
    ax.legend(frameon=False, loc="lower right")
    fig.savefig(FIG / "eda_02_feature_availability.png", bbox_inches="tight")
    plt.close(fig)


def plot_financial(base: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(13, 7.5), constrained_layout=True)
    specs = [
        ("debt_to_asset", "资产负债率"),
        ("roa", "总资产收益率 ROA"),
        ("current_ratio", "流动比率"),
        ("ocf_to_assets", "经营现金流/总资产（已修正）"),
        ("net_margin", "销售净利率"),
        ("asset_turnover", "总资产周转率"),
    ]
    for ax, (col, title) in zip(axes.ravel(), specs):
        plot_box(ax, base, col, title)
    fig.suptitle("财务特征分布：ST vs 非 ST（2013–2025，1%/99% 缩尾）", fontsize=13)
    fig.savefig(FIG / "eda_03_financial_distributions.png", bbox_inches="tight")
    plt.close(fig)


def plot_governance_legal(gov_tab: pd.DataFrame, legal_tab: pd.DataFrame) -> None:
    legal_plot = legal_tab[legal_tab["year"] <= 2025].copy()
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), constrained_layout=True)

    ax = axes[0, 0]
    ax.plot(gov_tab["year"], gov_tab["duality_rate"], color=COLORS["blue"], marker="o", lw=2)
    ax.fill_between(gov_tab["year"], gov_tab["duality_ci_low"], gov_tab["duality_ci_high"],
                    color=COLORS["blue"], alpha=0.15)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_title("两职合一比例（95% CI）")
    ax.set_xlabel("年份")
    ax.grid(alpha=0.25)

    ax = axes[0, 1]
    ax.plot(gov_tab["year"], gov_tab["board_size_mean"], color=COLORS["green"], marker="o", label="董事会人数")
    ax.set_ylabel("董事会人数均值", color=COLORS["green"])
    ax.tick_params(axis="y", colors=COLORS["green"])
    ax.set_title("董事会规模与独立董事比例")
    ax.set_xlabel("年份")
    ax.grid(alpha=0.25)
    ax2 = ax.twinx()
    ax2.plot(gov_tab["year"], gov_tab["independent_ratio_mean"], color=COLORS["orange"],
             marker="s", ls="--", label="独立董事比例")
    ax2.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax2.set_ylabel("独立董事比例均值", color=COLORS["orange"])
    ax2.tick_params(axis="y", colors=COLORS["orange"])
    lines = ax.get_lines() + ax2.get_lines()
    ax.legend(lines, [l.get_label() for l in lines], frameon=False, loc="lower right")

    ax = axes[1, 0]
    ax.plot(legal_plot["year"], legal_plot["lawsuit_prevalence"], color=COLORS["red"], marker="o", lw=2)
    ax.fill_between(legal_plot["year"], legal_plot["lawsuit_ci_low"], legal_plot["lawsuit_ci_high"],
                    color=COLORS["red"], alpha=0.15)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_title("涉诉公司-年占比（公告口径）")
    ax.set_xlabel("年份")
    ax.grid(alpha=0.25)

    ax = axes[1, 1]
    ax.plot(legal_plot["year"], legal_plot["penalty_prevalence"], color=COLORS["orange"], marker="s", lw=2)
    ax.fill_between(legal_plot["year"], legal_plot["penalty_ci_low"], legal_plot["penalty_ci_high"],
                    color=COLORS["orange"], alpha=0.15)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_title("受处罚公司-年占比（公告口径）")
    ax.set_xlabel("年份")
    ax.grid(alpha=0.25)

    fig.suptitle("治理与司法指标的年度趋势（2026 年仅有事件键，未画）", fontsize=13)
    fig.savefig(FIG / "eda_04_governance_legal_trends.png", bbox_inches="tight")
    plt.close(fig)


def plot_association(assoc: pd.DataFrame) -> None:
    labels = {
        "has_lawsuit": "涉诉", "has_penalty": "处罚", "duality": "两职合一",
    }
    fig, ax = plt.subplots(figsize=(10, 5), constrained_layout=True)
    x = np.arange(6)
    width = 0.36
    rows = [
        ("same_year", "has_lawsuit", 0), ("same_year", "has_lawsuit", 1),
        ("same_year", "has_penalty", 0), ("same_year", "has_penalty", 1),
        ("same_year", "duality", 0), ("same_year", "duality", 1),
    ]
    for offset, horizon, color, name in [
        (-width / 2, "same_year", COLORS["blue"], "同年"),
        (width / 2, "t_plus_2", COLORS["orange"], "T+2"),
    ]:
        vals, errs, ns = [], [], []
        for h, feature, value in rows:
            r = assoc[(assoc["horizon"] == horizon) & (assoc["feature"] == feature) & (assoc["value"] == value)]
            if len(r):
                r = r.iloc[0]
                vals.append(r["st_rate"])
                errs.append([r["st_rate"] - r["ci_low"], r["ci_high"] - r["st_rate"]])
                ns.append(int(r["n"]))
            else:
                vals.append(np.nan)
                errs.append([0, 0])
                ns.append(0)
        ax.bar(x + offset, vals, width, color=color, label=name, yerr=np.array(errs).T,
               capsize=2, error_kw={"lw": 0.8, "ecolor": "#555555"})
        for xi, v, n in zip(x + offset, vals, ns):
            if not np.isnan(v):
                ax.text(xi, v + 0.004, f"{v:.1%}\nn={n:,}", ha="center", va="bottom", fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels([
        "无涉诉", "有涉诉", "无处罚", "有处罚", "非两职合一", "两职合一",
    ])
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_ylabel("ST 比例")
    ax.set_title("候选特征与 ST 的描述性关联（含 95% CI，非因果）")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    fig.savefig(FIG / "eda_05_candidate_association.png", bbox_inches="tight")
    plt.close(fig)


def plot_market(base: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), constrained_layout=True)
    specs = [
        ("annual_turnover", "年换手率（对数轴）", True),
        ("stock_volatility", "年化波动率", False),
    ]
    for ax, (col, title, log_scale) in zip(axes, specs):
        x = pd.to_numeric(base[col], errors="coerce")
        x = x.clip(x.quantile(0.01), x.quantile(0.99))
        groups = [x[base["is_st"].eq(0)].dropna(), x[base["is_st"].eq(1)].dropna()]
        bp = ax.boxplot(groups, tick_labels=["非 ST", "ST"], patch_artist=True, showfliers=False,
                        widths=0.55, medianprops={"color": "white", "linewidth": 1.3})
        for patch, color in zip(bp["boxes"], [COLORS["light_blue"], COLORS["orange"]]):
            patch.set_facecolor(color)
            patch.set_alpha(0.9)
        for i, g in enumerate(groups):
            if len(g):
                ax.text(i + 1, g.median(), f"{g.median():.3f}", ha="center", va="bottom",
                        fontsize=8, color="#333333")
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.25)
        if log_scale:
            ax.set_yscale("log")
        ax.text(0.02, 0.98, f"n={len(groups[0]):,} / {len(groups[1]):,}", transform=ax.transAxes,
                va="top", fontsize=8, color=COLORS["gray"])
    fig.suptitle("日行情聚合特征：ST vs 非 ST（2013–2025，1%/99% 缩尾）", fontsize=13)
    fig.savefig(FIG / "eda_07_market_features.png", bbox_inches="tight")
    plt.close(fig)


def plot_industry(ind_tab: pd.DataFrame, names: dict[str, str]) -> None:
    top = ind_tab.head(15).copy()
    top["label"] = top["industry"].map(lambda x: f"{x} {names.get(x, '')}".strip())
    top = top.sort_values("st_rate", ascending=True)
    fig, ax = plt.subplots(figsize=(10, 6), constrained_layout=True)
    ax.barh(top["label"], top["st_rate"], color=COLORS["blue"], alpha=0.9,
            xerr=[top["st_rate"] - top["ci_low"], top["ci_high"] - top["st_rate"]],
            capsize=2, error_kw={"lw": 0.8, "ecolor": "#555555"})
    overall = ind_tab["st_positive"].sum() / ind_tab["rows"].sum()
    ax.axvline(overall, color=COLORS["red"], ls="--", lw=1.2, label=f"总体 {overall:.2%}")
    ax.xaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_xlabel("ST 比例")
    ax.set_title("行业 ST 比例（按公司-年数前 15 个行业，95% CI）")
    ax.grid(axis="x", alpha=0.25)
    ax.legend(frameon=False, loc="lower right")
    fig.savefig(FIG / "eda_06_industry_st.png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    data = load_data()
    base = build_base(data)
    label_tab = label_tables(data)
    fin_tab = financial_table(base)
    gov_tab = governance_table(data)
    legal_tab = legal_table(data)
    assoc = association_table(base)
    mkt_tab = market_table(base)
    ind_tab = industry_table(base)
    names = load_industry_names()
    ind_tab["industry_name"] = ind_tab["industry"].map(names).fillna("")

    write(label_tab, "eda_label_year.csv")
    write(fin_tab, "eda_financial_by_st.csv")
    write(gov_tab, "eda_governance_year.csv")
    write(legal_tab, "eda_legal_year.csv")
    write(assoc, "eda_candidate_association.csv")
    write(mkt_tab, "eda_market_by_st.csv")
    write(ind_tab, "eda_industry_st.csv")

    plot_label_trend(label_tab)
    plot_feature_availability(data["readiness"])
    plot_financial(base)
    plot_governance_legal(gov_tab, legal_tab)
    plot_association(assoc)
    plot_market(base)
    plot_industry(ind_tab, names)

    summary = {
        "sample": {
            "financial_rows": int(len(base)),
            "companies": int(base["stock_code"].nunique()),
            "year_min": int(base["year"].min()),
            "year_max": int(base["year"].max()),
            "st_positive": int(base["is_st"].sum()),
            "st_rate": float(base["is_st"].mean()),
        },
        "label": {
            "proxy_positive": int(data["proxy"]["is_st"].sum()),
            "official_positive": int(data["official"]["is_st"].sum()),
            "proxy_rate": float(data["proxy"]["is_st"].mean()),
            "official_rate": float(data["official"]["is_st"].mean()),
        },
        "feature_availability": {
            "features": int(len(data["readiness"])),
            "all_zero": int(data["readiness"]["all_zero"].sum()),
            "all_zero_features": data["readiness"].loc[data["readiness"]["all_zero"], "feature"].tolist(),
        },
        "market_features": {
            "candidate_rows": int(len(data["trd"])),
            "candidate_companies": int(data["trd"]["stock_code"].nunique()),
            "matched_rows_2013_2025": int(base["annual_turnover"].notna().sum()),
            "turnover_coverage_2013_2025": float(base["annual_turnover"].notna().mean()),
            "volatility_coverage_2013_2025": float(base["stock_volatility"].notna().mean()),
            "by_st": mkt_tab.to_dict("records"),
            "note": "TRD_Dly 候选已可用，但尚未写入 feature_store/panel_features.csv，也未重训模型；2026 为部分年度。",
        },
        "cashflow_source": data["cashflow_source"],
        "figures": sorted(p.name for p in FIG.glob("eda_*.png")),
        "caveats": [
            "EDA 的 ST 关联为描述性，不构成因果证据；司法事件可能与 ST 互为因果。",
            "2026 年司法表只有已观测事件键，不能计算全市场发生率。",
            "在线 labels_st.csv 已与官方 ST 标签一致（48,290 行、1,897 正）；2026 标签仍缺失。",
            "2024 锁箱是特征年 2024，需要 2026 标签；当前无 2026 公司-年键，不能评估。",
            "EDA 使用候选现金流修正值；在线 csmar_financial.csv 已处于同一量级，但模型产物尚未重跑。",
            "TRD_Dly 公司-年行情为候选输入，尚未合并进特征面板；在线 market_features 仍为百分数口径（约100×），本图使用小数口径候选；2026 年仅至 9-30，未纳入年度对比图。",
        ],
    }
    (OUT / "eda_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
