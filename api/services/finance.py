"""财务分析服务（移植自旧项目 server/app/services/finance.py）。

能力：概览 KPI、趋势、杜邦分解、Altman Z/Z''、Piotroski F、Beneish M、同业对标、异常勾稽。
数据源：``data/cleaned/panel_clean.parquet``（金额单位：亿元）。
原则：缺失即不参与、口径可追溯、模型输入逐项披露 exact/approx/missing。
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd

from config import settings
from etl.io_utils import read_table

DIM_LABELS = {
    "scale": "规模",
    "profit": "盈利能力",
    "solvency": "偿债与杠杆",
    "operation": "营运效率",
    "cashflow": "现金流质量",
    "growth": "成长性",
}

# key -> (标签, 单位, 分组, 是否越大越好)
METRIC_META: dict[str, tuple[str, str, str, bool]] = {
    "revenue": ("营业总收入", "亿元", "scale", True),
    "net_profit": ("归母净利润", "亿元", "scale", True),
    "net_profit_total": ("净利润（含少数股东）", "亿元", "scale", True),
    "gross_margin": ("毛利率", "%", "profit", True),
    "net_margin": ("销售净利率", "%", "profit", True),
    "roe": ("净资产收益率 ROE", "%", "profit", True),
    "roa": ("总资产报酬率 ROA", "%", "profit", True),
    "operating_margin": ("营业利润率", "%", "profit", True),
    "debt_ratio": ("资产负债率", "%", "solvency", False),
    "current_ratio": ("流动比率", "倍", "solvency", True),
    "quick_ratio": ("速动比率", "倍", "solvency", True),
    "equity_multiplier": ("权益乘数", "倍", "solvency", False),
    "asset_turnover": ("总资产周转率", "次", "operation", True),
    "ar_days": ("应收账款周转天数", "天", "operation", False),
    "inventory_days": ("存货周转天数", "天", "operation", False),
    "ocf": ("经营活动现金流净额", "亿元", "cashflow", True),
    "ocf_to_profit": ("现金含量（经营现金流/净利润）", "倍", "cashflow", True),
    "ocf_to_revenue": ("经营现金流/营业收入", "倍", "cashflow", True),
    "revenue_growth": ("营业总收入增速", "%", "growth", True),
    "profit_growth": ("归母净利润增速", "%", "growth", True),
    "goodwill_ratio": ("商誉/净资产", "%", "solvency", False),
    "deducted_ratio": ("扣非净利润/净利润", "倍", "profit", True),
    "deducted_profit": ("扣非净利润", "亿元", "profit", True),
}


def _f(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _div(a, b) -> float | None:
    a, b = _f(a), _f(b)
    if a is None or b in (None, 0):
        return None
    return a / b


def _pct(a, b) -> float | None:
    r = _div(a, b)
    return None if r is None else round(r * 100, 4)


def _r(v, nd=4) -> float | None:
    return None if v is None else round(v, nd)


@lru_cache(maxsize=1)
def _panel() -> pd.DataFrame:
    df = read_table(settings.CLEANED_PANEL).copy()
    if "stock_code" in df.columns:
        df["stock_code"] = df["stock_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    if "year" in df.columns:
        df["year"] = df["year"].astype(int)
    return df


def _industry_label(code: str) -> str:
    return settings.INDUSTRIES.get(str(code).strip(), str(code).strip()) if code else ""


def _period_from_row(m: pd.Series) -> dict:
    revenue = _f(m.get("revenue"))
    net_profit_total = _f(m.get("net_profit"))
    net_profit = _f(m.get("net_profit_parent"))
    if net_profit is None:
        net_profit = net_profit_total
    total_assets = _f(m.get("total_assets"))
    total_liabilities = _f(m.get("total_liabilities"))
    equity = _f(m.get("equity"))
    current_assets = _f(m.get("current_assets"))
    current_liabilities = _f(m.get("current_lia"))
    accounts_receivable = _f(m.get("receivables"))
    inventory = _f(m.get("inventory"))
    fixed_assets = _f(m.get("fixed_assets"))
    cost = _f(m.get("cost"))
    ebit = _f(m.get("ebit"))
    finance_expense = _f(m.get("fin_exp"))
    selling_expense = _f(m.get("sell_exp"))
    admin_expense = _f(m.get("admin_exp"))
    ocf = _f(m.get("ocf"))
    capex = _f(m.get("capex"))
    deducted_profit = _f(m.get("deducted_profit"))
    depreciation = _f(m.get("depreciation"))

    p: dict = {
        "year": int(m["year"]),
        "report_type": "年报",
        "source": "CSMAR",
        "revenue": revenue,
        "net_profit": net_profit,
        "net_profit_total": net_profit_total,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "equity": equity,
        "ocf": ocf,
        "current_assets": current_assets,
        "current_liabilities": current_liabilities,
        "accounts_receivable": accounts_receivable,
        "inventory": inventory,
        "fixed_assets": fixed_assets,
        "fixed_assets_gross": None,       # 契约表未含固定资产原值
        "accum_depreciation": None,       # 契约表未含累计折旧
        "depreciation": depreciation,     # 当期折旧
        "goodwill": None,                 # 契约表未含商誉
        "surplus_reserve": None,          # 契约表未含盈余公积
        "undistributed_profit": None,     # 契约表未含未分配利润
        "operating_profit": _r(ebit - finance_expense, 2) if ebit is not None and finance_expense is not None else None,
        "finance_expense": finance_expense,
        "selling_expense": selling_expense,
        "admin_expense": admin_expense,
        "capex": capex,
        "deducted_profit": deducted_profit,
        "bvps": None,
    }

    derived: list[str] = []
    p["debt_ratio"] = _pct(total_liabilities, total_assets)
    p["gross_margin"] = _pct((revenue - cost) if revenue is not None and cost is not None else None, revenue)
    p["net_margin"] = _pct(net_profit, revenue)
    p["roe"] = _pct(net_profit, equity)
    p["roa"] = _pct(net_profit, total_assets)
    p["operating_margin"] = _pct(p["operating_profit"], revenue)
    p["current_ratio"] = _r(_div(current_assets, current_liabilities))
    p["quick_ratio"] = _r(_div((current_assets - inventory) if current_assets is not None and inventory is not None else None, current_liabilities))
    p["equity_multiplier"] = _r(_div(total_assets, equity))  # 杜邦口径：总资产/净资产
    p["asset_turnover"] = _r(_div(revenue, total_assets))
    p["ar_days"] = _r(_div(accounts_receivable, revenue) * 365) if accounts_receivable is not None and revenue else None
    p["inventory_days"] = _r(_div(inventory, cost) * 365) if inventory is not None and cost else None
    p["ocf_to_revenue"] = _r(_div(ocf, revenue))
    p["ocf_to_profit"] = _r(_div(ocf, net_profit))
    p["goodwill_ratio"] = None
    p["deducted_ratio"] = _r(_div(deducted_profit, net_profit)) if deducted_profit is not None and net_profit else None
    p["shares_wan"] = None
    for k in ("debt_ratio", "gross_margin", "net_margin", "roe", "roa", "operating_margin",
              "current_ratio", "quick_ratio", "equity_multiplier", "asset_turnover",
              "ar_days", "inventory_days", "ocf_to_revenue", "ocf_to_profit"):
        if p.get(k) is not None:
            derived.append(k)
    p["derived"] = derived
    return p


def load_periods(stock_code: str, years: int = 5) -> list[dict]:
    code = str(stock_code).strip().zfill(6)
    rows = _panel()[_panel()["stock_code"] == code].sort_values("year").tail(years)
    periods = [_period_from_row(r) for _, r in rows.iterrows()]
    for i, p in enumerate(periods):
        if i == 0:
            continue
        prev = periods[i - 1]
        if p["revenue_growth"] is None and p["revenue"] is not None and prev["revenue"]:
            p["revenue_growth"] = _pct(p["revenue"] - prev["revenue"], abs(prev["revenue"]))
        if p["profit_growth"] is None and p["net_profit"] is not None and prev["net_profit"]:
            p["profit_growth"] = _pct(p["net_profit"] - prev["net_profit"], abs(prev["net_profit"]))
    return periods


def _latest(periods: list[dict]) -> dict | None:
    return periods[-1] if periods else None


def _prev(periods: list[dict]) -> dict | None:
    return periods[-2] if len(periods) >= 2 else None


# ---------------------------------------------------------------------------
# 1. 概览 KPI
# ---------------------------------------------------------------------------

KPI_KEYS = [
    "revenue", "net_profit", "deducted_profit", "gross_margin", "net_margin", "roe", "roa",
    "debt_ratio", "ocf", "ocf_to_profit", "revenue_growth", "profit_growth",
    "current_ratio", "ar_days", "inventory_days", "goodwill_ratio",
]


def build_kpi(periods: list[dict]) -> list[dict]:
    cur, prev = _latest(periods), _prev(periods)
    out: list[dict] = []
    for key in KPI_KEYS:
        label, unit, group, higher_better = METRIC_META[key]
        v = _f(cur.get(key)) if cur else None
        pv = _f(prev.get(key)) if prev else None
        yoy = round((v - pv) / abs(pv) * 100, 2) if v is not None and pv is not None and pv != 0 else None
        trend = "flat"
        if v is not None and pv is not None and abs(v - pv) >= 1e-9:
            trend = "up" if ((v - pv) > 0) == higher_better else "down"
        out.append({
            "key": key, "label": label, "unit": unit, "group": group,
            "value": _r(v, 2), "prev": _r(pv, 2), "yoy": yoy, "trend": trend,
            "higher_better": higher_better, "available": v is not None,
            "year": cur["year"] if cur else None,
            "note": "" if v is not None else "该期无此指标（数据源未提供或未采集）",
        })
    return out


# ---------------------------------------------------------------------------
# 2. 趋势序列
# ---------------------------------------------------------------------------

def build_trends(periods: list[dict]) -> dict:
    groups: dict[str, dict] = {}
    for key, (label, unit, group, _hb) in METRIC_META.items():
        if key in ("net_profit_total", "goodwill_ratio", "deducted_ratio", "deducted_profit"):
            continue
        points = [{"year": p["year"], "value": _r(_f(p.get(key)), 2)} for p in periods]
        if not any(pt["value"] is not None for pt in points):
            continue
        groups.setdefault(group, {"label": DIM_LABELS.get(group, group), "series": []})
        groups[group]["series"].append({"key": key, "label": label, "unit": unit, "points": points})
    return groups


# ---------------------------------------------------------------------------
# 3. 杜邦分解
# ---------------------------------------------------------------------------

def build_dupont(periods: list[dict]) -> dict:
    rows: list[dict] = []
    for p in periods:
        rev, ta, eq, np_ = p["revenue"], p["total_assets"], p["equity"], p["net_profit"]
        margin, turnover, leverage = _div(np_, rev), _div(rev, ta), _div(ta, eq)
        roe = margin * turnover * leverage if None not in (margin, turnover, leverage) else None
        rows.append({
            "year": p["year"],
            "roe": _r(roe * 100 if roe is not None else _f(p.get("roe")), 2),
            "net_margin": _r(margin * 100 if margin is not None else _f(p.get("net_margin")), 2),
            "asset_turnover": _r(turnover, 4),
            "equity_multiplier": _r(leverage, 4),
            "complete": all(x is not None for x in (margin, turnover, leverage)),
        })
    attribution = None
    if len(rows) >= 2 and rows[-1]["complete"] and rows[-2]["complete"]:
        a, b = rows[-2], rows[-1]
        m0, t0, l0 = a["net_margin"] / 100, a["asset_turnover"], a["equity_multiplier"]
        m1, t1, l1 = b["net_margin"] / 100, b["asset_turnover"], b["equity_multiplier"]
        attribution = {
            "from_year": a["year"], "to_year": b["year"], "roe_delta": _r(b["roe"] - a["roe"], 2),
            "items": [
                {"key": "net_margin", "label": "销售净利率", "contrib": _r((m1 - m0) * t0 * l0 * 100, 2)},
                {"key": "asset_turnover", "label": "总资产周转率", "contrib": _r(m1 * (t1 - t0) * l0 * 100, 2)},
                {"key": "equity_multiplier", "label": "权益乘数（杠杆）", "contrib": _r(m1 * t1 * (l1 - l0) * 100, 2)},
            ],
            "note": "按三因素顺序分解，贡献之和 = ROE 变动（单位：百分点）",
        }
    return {"formula": "ROE = 销售净利率 × 总资产周转率 × 权益乘数", "rows": rows, "attribution": attribution}


# ---------------------------------------------------------------------------
# 4. 财务预警模型
# ---------------------------------------------------------------------------

def _comp(value, source: str, label: str = "") -> dict:
    return {"value": _r(value, 4), "source": source, "label": label}


def _z_verdict(score: float | None, safe: float, distress: float) -> str | None:
    if score is None:
        return None
    if score > safe:
        return "安全区"
    if score >= distress:
        return "灰色区"
    return "困境区"


def build_altman(p: dict, market_cap: float | None) -> dict:
    ca, cl = p.get("current_assets"), p.get("current_liabilities")
    ta, tl, eq = p.get("total_assets"), p.get("total_liabilities"), p.get("equity")
    rev = p.get("revenue")
    retained = None
    if p.get("surplus_reserve") is not None or p.get("undistributed_profit") is not None:
        retained = (p.get("surplus_reserve") or 0) + (p.get("undistributed_profit") or 0)
    ebit = None
    if p.get("operating_profit") is not None:
        ebit = p["operating_profit"] + (p.get("finance_expense") or 0)

    comps = {
        "X1": _comp(_div((ca - cl) if ca is not None and cl is not None else None, ta),
                    "exact" if (ca is not None and cl is not None and ta) else "missing", "营运资金 / 总资产"),
        "X2": _comp(_div(retained, ta), "exact" if (retained is not None and ta) else "missing", "留存收益 / 总资产"),
        "X3": _comp(_div(ebit, ta), "exact" if (ebit is not None and ta) else "missing", "EBIT / 总资产"),
        "X5": _comp(_div(rev, ta), "exact" if (rev is not None and ta) else "missing", "营业收入 / 总资产"),
    }

    z2_comps = dict(comps)
    z2_comps["X4"] = _comp(_div(eq, tl), "exact" if (eq is not None and tl) else "missing", "账面净资产 / 总负债")
    z2_missing = [k for k, v in z2_comps.items() if v["source"] == "missing"]
    z2 = None
    if not z2_missing:
        z2 = (6.56 * z2_comps["X1"]["value"] + 3.26 * z2_comps["X2"]["value"]
              + 6.72 * z2_comps["X3"]["value"] + 1.05 * z2_comps["X4"]["value"])

    z_comps = dict(comps)
    z = None
    if market_cap is not None:
        z_comps["X4"] = _comp(_div(market_cap, tl), "exact" if tl else "missing", "股权市值 / 总负债")
    else:
        z_comps["X4"] = _comp(None, "missing", "股权市值 / 总负债（未取到总市值）")
    z_missing = [k for k, v in z_comps.items() if v["source"] == "missing"]
    if not z_missing:
        z = (1.2 * z_comps["X1"]["value"] + 1.4 * z_comps["X2"]["value"]
             + 3.3 * z_comps["X3"]["value"] + 0.6 * z_comps["X4"]["value"]
             + 1.0 * z_comps["X5"]["value"])

    return {
        "key": "altman", "name": "Altman Z-Score 财务困境预警", "period": p["year"],
        "z": {
            "score": _r(z, 3), "verdict": _z_verdict(z, 2.99, 1.81), "available": z is not None,
            "basis": "股权市值 / 总负债（上市制造业口径）",
            "thresholds": "Z > 2.99 安全 · 1.81 ~ 2.99 灰色 · Z < 1.81 困境",
            "components": z_comps,
            "missing": [f"{k}（{z_comps[k]['label']}）" for k in z_missing],
            "note": "" if z is not None else "缺少市值或绝对值科目，无法计算 Z；可参考 Z''-Score",
        },
        "z2": {
            "score": _r(z2, 3), "verdict": _z_verdict(z2, 2.6, 1.1), "available": z2 is not None,
            "basis": "账面净资产 / 总负债（非制造业 / 新兴市场口径）",
            "thresholds": "Z'' > 2.6 安全 · 1.1 ~ 2.6 灰色 · Z'' < 1.1 困境",
            "components": z2_comps,
            "missing": [f"{k}（{z2_comps[k]['label']}）" for k in z2_missing],
            "note": "" if z2 is not None else "缺少绝对值科目，无法计算 Z''",
        },
    }
