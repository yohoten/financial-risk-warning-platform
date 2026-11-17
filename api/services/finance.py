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
    # 合并留存收益补充表（盈余公积 + 未分配利润），补齐 Altman X2（G-13）
    ext_path = settings.RAW_DIR / "candidates" / "balance_sheet_ext.csv"
    if ext_path.exists():
        try:
            ext = pd.read_csv(ext_path, dtype={"stock_code": str}, encoding="utf-8-sig")
            ext["stock_code"] = ext["stock_code"].astype(str).str.zfill(6)
            ext["year"] = ext["year"].astype(int)
            cols = [c for c in ("surplus_reserve", "undistributed_profit") if c in ext.columns]
            df = df.merge(ext[["stock_code", "year", *cols]], on=["stock_code", "year"], how="left")
        except Exception:  # noqa: BLE001 —— 补充表异常不影响主分析
            pass
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
        "surplus_reserve": _f(m.get("surplus_reserve")),          # 盈余公积（补充表）
        "undistributed_profit": _f(m.get("undistributed_profit")),  # 未分配利润（补充表）
        "operating_profit": _r(ebit - finance_expense, 2) if ebit is not None and finance_expense is not None else None,
        "finance_expense": finance_expense,
        "selling_expense": selling_expense,
        "admin_expense": admin_expense,
        "capex": capex,
        "deducted_profit": deducted_profit,
        "bvps": None,
    }
    p["revenue_growth"] = None
    p["profit_growth"] = None

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


def build_piotroski(periods: list[dict]) -> dict:
    if len(periods) < 2:
        return {"key": "piotroski", "name": "Piotroski F-Score", "available": False,
                "reason": "需要连续两年财报", "signals": [], "score": None, "max_score": 9}
    cur, prev = periods[-1], periods[-2]

    def roa(p):
        return _div(p.get("net_profit"), p.get("total_assets"))

    def cfo_ta(p):
        return _div(p.get("ocf"), p.get("total_assets"))

    signals: list[dict] = []

    def add(name: str, ok, detail: str, group: str) -> None:
        signals.append({"name": name, "group": group, "pass": None if ok is None else bool(ok), "detail": detail})

    r_cur, r_prev = roa(cur), roa(prev)
    add("ROA 为正", None if r_cur is None else r_cur > 0,
        f"ROA = {_r(r_cur * 100, 2)}%" if r_cur is not None else "缺净利润/总资产", "盈利")
    add("经营现金流为正", None if cur.get("ocf") is None else cur["ocf"] > 0,
        f"经营现金流 = {_r(cur.get('ocf'), 2)} 亿元" if cur.get("ocf") is not None else "缺经营现金流", "盈利")
    add("ROA 同比改善", None if (r_cur is None or r_prev is None) else r_cur > r_prev,
        f"{_r(r_prev * 100, 2)}% → {_r(r_cur * 100, 2)}%" if (r_cur is not None and r_prev is not None) else "缺两年 ROA", "盈利")
    c_cur = cfo_ta(cur)
    add("经营现金流优于 ROA（应计质量）", None if (c_cur is None or r_cur is None) else c_cur > r_cur,
        f"CFO/TA = {_r(c_cur * 100, 2)}% vs ROA = {_r(r_cur * 100, 2)}%" if (c_cur is not None and r_cur is not None) else "缺经营现金流/总资产", "盈利")

    d_cur, d_prev = _f(cur.get("debt_ratio")), _f(prev.get("debt_ratio"))
    add("杠杆率下降", None if (d_cur is None or d_prev is None) else d_cur < d_prev,
        f"资产负债率 {d_prev}% → {d_cur}%" if (d_cur is not None and d_prev is not None) else "缺资产负债率", "偿债")
    cr_cur, cr_prev = _f(cur.get("current_ratio")), _f(prev.get("current_ratio"))
    add("流动比率上升", None if (cr_cur is None or cr_prev is None) else cr_cur > cr_prev,
        f"流动比率 {cr_prev} → {cr_cur}" if (cr_cur is not None and cr_prev is not None) else "缺流动比率", "偿债")
    s_cur, s_prev = _f(cur.get("shares_wan")), _f(prev.get("shares_wan"))
    add("未增发股本", None if (s_cur is None or s_prev is None) else s_cur <= s_prev * 1.01,
        f"股本 {_r(s_prev, 0)} → {_r(s_cur, 0)} 万股" if (s_cur is not None and s_prev is not None) else "缺每股净资产/净资产，无法推算股本", "偿债")
    g_cur, g_prev = _f(cur.get("gross_margin")), _f(prev.get("gross_margin"))
    add("毛利率上升", None if (g_cur is None or g_prev is None) else g_cur > g_prev,
        f"毛利率 {g_prev}% → {g_cur}%" if (g_cur is not None and g_prev is not None) else "缺毛利率", "效率")
    t_cur, t_prev = _f(cur.get("asset_turnover")), _f(prev.get("asset_turnover"))
    add("总资产周转率上升", None if (t_cur is None or t_prev is None) else t_cur > t_prev,
        f"周转率 {t_prev} → {t_cur}" if (t_cur is not None and t_prev is not None) else "缺总资产周转率", "效率")

    scored = [s for s in signals if s["pass"] is not None]
    score = sum(1 for s in scored if s["pass"]) if scored else None
    max_score = len(scored)
    verdict = None
    if score is not None and max_score == 9:
        verdict = "基本面强（≥7）" if score >= 7 else ("基本面中等（4~6）" if score >= 4 else "基本面弱（≤3）")
    note = "" if max_score == 9 else f"9 项中 {9 - max_score} 项因数据缺失未评分，得分为可评分项之和"
    if r_cur is not None and r_cur < 0.02:
        note = (note + "；" if note else "") + f"注意：F-Score 衡量同比改善方向，当前 ROA 仅 {_r(r_cur * 100, 2)}%，绝对盈利水平仍很低"
    return {
        "key": "piotroski", "name": "Piotroski F-Score", "period": cur["year"],
        "available": score is not None, "score": score, "max_score": max_score,
        "full_score": 9, "verdict": verdict, "complete": max_score == 9,
        "signals": signals, "note": note,
    }


def build_beneish(periods: list[dict]) -> dict:
    if len(periods) < 2:
        return {"key": "beneish", "name": "Beneish M-Score", "available": False,
                "reason": "需要连续两年财报", "indices": [], "score": None}
    cur, prev = periods[-1], periods[-2]
    idx: list[dict] = []

    def add(key: str, label: str, value, source: str, detail: str) -> None:
        idx.append({"key": key, "label": label, "value": _r(value, 4), "source": source, "detail": detail})

    if cur.get("accounts_receivable") and cur.get("revenue") and prev.get("accounts_receivable") and prev.get("revenue"):
        add("DSRI", "应收账款指数", _div(cur["accounts_receivable"] / cur["revenue"], prev["accounts_receivable"] / prev["revenue"]),
            "exact", "应收账款/营业收入 的同比变化")
    else:
        add("DSRI", "应收账款指数", None, "missing", "缺应收账款或营业收入")

    gm_c, gm_p = _f(cur.get("gross_margin")), _f(prev.get("gross_margin"))
    if gm_c and gm_p:
        add("GMI", "毛利率指数", gm_p / gm_c, "exact", f"毛利率 {gm_p}% → {gm_c}%")
    else:
        add("GMI", "毛利率指数", None, "missing", "缺毛利率")

    if cur.get("current_assets") and cur.get("fixed_assets") and cur.get("total_assets") \
            and prev.get("current_assets") and prev.get("fixed_assets") and prev.get("total_assets"):
        r_c = 1 - (cur["current_assets"] + cur["fixed_assets"]) / cur["total_assets"]
        r_p = 1 - (prev["current_assets"] + prev["fixed_assets"]) / prev["total_assets"]
        add("AQI", "资产质量指数", _div(r_c, r_p), "exact", "非流动硬资产占比的同比变化")
    else:
        add("AQI", "资产质量指数", None, "missing", "缺流动资产/固定资产/总资产")

    if cur.get("revenue") and prev.get("revenue"):
        add("SGI", "销售增长指数", _div(cur["revenue"], prev["revenue"]), "exact",
            f"营业收入 {prev['revenue']} → {cur['revenue']} 亿元")
    else:
        add("SGI", "销售增长指数", None, "missing", "缺营业收入")

    dep_c, dep_p = _f(cur.get("depreciation")), _f(prev.get("depreciation"))
    fa_c, fa_p = cur.get("fixed_assets"), prev.get("fixed_assets")
    if dep_c is not None and dep_p is not None and fa_c and fa_p:
        add("DEPI", "折旧率指数", _div(dep_p / fa_p, dep_c / fa_c), "approx",
            "折旧率≈当期折旧/固定资产净额（契约表缺累计折旧与固定资产原值）")
    else:
        add("DEPI", "折旧率指数", None, "missing", "缺折旧/固定资产")

    sga_c = (cur.get("selling_expense") or 0) + (cur.get("admin_expense") or 0) \
        if cur.get("selling_expense") is not None or cur.get("admin_expense") is not None else None
    sga_p = (prev.get("selling_expense") or 0) + (prev.get("admin_expense") or 0) \
        if prev.get("selling_expense") is not None or prev.get("admin_expense") is not None else None
    if sga_c is not None and sga_p is not None and cur.get("revenue") and prev.get("revenue"):
        add("SGAI", "销售管理费用指数", _div(sga_c / cur["revenue"], sga_p / prev["revenue"]),
            "exact", "（销售+管理）费用率的同比变化")
    else:
        add("SGAI", "销售管理费用指数", None, "missing", "缺销售/管理费用")

    lv_c, lv_p = _div(cur.get("total_liabilities"), cur.get("total_assets")), _div(prev.get("total_liabilities"), prev.get("total_assets"))
    if lv_c is not None and lv_p is not None:
        add("LVGI", "杠杆指数", _div(lv_c, lv_p), "exact", "资产负债率的同比变化")
    else:
        add("LVGI", "杠杆指数", None, "missing", "缺总负债/总资产")

    if cur.get("net_profit") is not None and cur.get("ocf") is not None and cur.get("total_assets"):
        add("TATA", "总应计项目", _div(cur["net_profit"] - cur["ocf"], cur["total_assets"]),
            "exact", "（净利润 − 经营现金流）/ 总资产")
    else:
        add("TATA", "总应计项目", None, "missing", "缺净利润/经营现金流/总资产")

    values = {i["key"]: i["value"] for i in idx}
    missing = [i["label"] for i in idx if i["value"] is None]
    score = None
    if not missing:
        score = (-4.84 + 0.920 * values["DSRI"] + 0.528 * values["GMI"] + 0.404 * values["AQI"]
                 + 0.892 * values["SGI"] + 0.115 * values["DEPI"] - 0.172 * values["SGAI"]
                 + 4.679 * values["TATA"] - 0.327 * values["LVGI"])
    verdict = "存在盈余操纵嫌疑" if score is not None and score > -1.78 else ("未见明显操纵迹象" if score is not None else None)
    approx = [i["label"] for i in idx if i["source"] == "approx"]
    return {
        "key": "beneish", "name": "Beneish M-Score 盈余操纵识别", "period": cur["year"],
        "available": score is not None, "score": _r(score, 3),
        "thresholds": "M > -1.78 提示盈余操纵嫌疑（Beneish 1999 阈值）",
        "verdict": verdict, "indices": idx, "missing": missing, "approx": approx,
        "note": ("含近似项：" + "、".join(approx) + "；结论请结合审计意见判断") if approx else "",
    }


# ---------------------------------------------------------------------------
# 5. 同业对标
# ---------------------------------------------------------------------------

PEER_METRICS = ["revenue", "revenue_growth", "gross_margin", "net_margin", "roe",
                "debt_ratio", "asset_turnover", "current_ratio", "ocf_to_profit"]


def _percentile(values: list[float], v: float, higher_better: bool) -> float | None:
    if not values or v is None:
        return None
    below = sum(1 for x in values if x < v)
    equal = sum(1 for x in values if x == v)
    pct = (below + 0.5 * equal) / len(values) * 100
    return round(pct if higher_better else 100 - pct, 1)


def build_peers(stock_code: str, years: int = 5, limit: int = 6) -> dict:
    panel = _panel()
    code = str(stock_code).strip().zfill(6)
    target = panel[panel["stock_code"] == code]
    if target.empty:
        return {"industry": "", "rows": [], "metrics": [], "note": "未找到该企业"}
    industry = target.iloc[-1]["industry"]
    peers = panel[panel["industry"] == industry]["stock_code"].drop_duplicates().tolist()
    peers = [c for c in peers if c != code][:limit]

    rows: list[dict] = []
    for c in [code, *peers]:
        ps = load_periods(c, years)
        cur = _latest(ps)
        if cur is None:
            continue
        name = panel[panel["stock_code"] == c]["company_name"].iloc[-1]
        rows.append({
            "stock_code": c, "name": name, "industry": _industry_label(industry),
            "is_self": c == code, "year": cur["year"],
            "metrics": {k: _r(_f(cur.get(k)), 2) for k in PEER_METRICS},
        })

    for key in PEER_METRICS:
        label, unit, _g, higher_better = METRIC_META[key]
        vals = [r["metrics"][key] for r in rows if r["metrics"].get(key) is not None]
        for r in rows:
            v = r["metrics"].get(key)
            r.setdefault("percentiles", {})[key] = _percentile(vals, v, higher_better) if v is not None else None

    return {
        "industry": _industry_label(industry),
        "rows": rows,
        "metrics": [{"key": k, "label": METRIC_META[k][0], "unit": METRIC_META[k][1],
                     "higher_better": METRIC_META[k][3]} for k in PEER_METRICS],
        "note": f"同行业可比企业 {len(peers)} 家（分位数含本企业）",
    }


def _peer_median(peer: dict | None) -> dict:
    if not peer:
        return {}
    out: dict = {}
    for key in PEER_METRICS:
        vals = sorted(r["metrics"][key] for r in peer.get("rows", []) if r["metrics"].get(key) is not None)
        if vals:
            n = len(vals)
            out[key] = round(vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2, 2)
    return out


# ---------------------------------------------------------------------------
# 6. 异常勾稽
# ---------------------------------------------------------------------------

def build_anomalies(periods: list[dict], peer_median: dict | None = None) -> list[dict]:
    out: list[dict] = []
    cur = _latest(periods)
    prev = _prev(periods)
    if cur is None:
        return out

    def add(code: str, level: str, title: str, detail: str, evidence: dict) -> None:
        out.append({"code": code, "level": level, "title": title, "detail": detail, "evidence": evidence})

    if cur.get("net_profit") is not None and cur.get("ocf") is not None and cur["net_profit"] > 0 and cur["ocf"] < 0:
        add("OCF_NEGATIVE", "high", "净利润为正但经营现金流为负",
            f"{cur['year']} 年归母净利润 {_r(cur['net_profit'], 2)} 亿元，经营活动现金流 {_r(cur['ocf'], 2)} 亿元，利润未转化为现金。",
            {"year": cur["year"], "net_profit": cur["net_profit"], "ocf": cur["ocf"]})

    ocfp = _f(cur.get("ocf_to_profit"))
    if ocfp is not None and 0 <= ocfp < 0.5 and (cur.get("net_profit") or 0) > 0:
        add("LOW_CASH_CONTENT", "medium", "现金含量偏低",
            f"经营现金流/净利润 = {ocfp}（低于 0.5），盈利质量偏弱。",
            {"year": cur["year"], "ocf_to_profit": ocfp})

    if prev and cur.get("accounts_receivable") and prev.get("accounts_receivable") and cur.get("revenue") and prev.get("revenue"):
        rev_g = _pct(cur["revenue"] - prev["revenue"], abs(prev["revenue"]))
        ar_g = _pct(cur["accounts_receivable"] - prev["accounts_receivable"], abs(prev["accounts_receivable"]))
        if rev_g is not None and ar_g is not None and rev_g > 20 and ar_g > rev_g + 20:
            add("AR_DIVERGENCE", "high", "应收账款增速显著高于营收",
                f"营收同比 {_r(rev_g, 1)}%，应收账款同比 {_r(ar_g, 1)}%，收入含金量需核实。",
                {"year": cur["year"], "revenue_growth": rev_g, "ar_growth": ar_g})

    gm = _f(cur.get("gross_margin"))
    if gm is not None and peer_median and peer_median.get("gross_margin") is not None and gm - peer_median["gross_margin"] > 20:
        add("MARGIN_ABOVE_PEERS", "medium", "毛利率显著高于同业中位数",
            f"毛利率 {gm}%，同业中位数 {peer_median['gross_margin']}%，差异超过 20 个百分点，需核实成本口径与关联交易。",
            {"year": cur["year"], "gross_margin": gm, "peer_median": peer_median["gross_margin"]})

    if prev:
        d1, d0 = _f(cur.get("debt_ratio")), _f(prev.get("debt_ratio"))
        if d1 is not None and d0 is not None and d1 - d0 >= 10:
            add("DEBT_JUMP", "high", "资产负债率一年内大幅上升",
                f"资产负债率 {d0}% → {d1}%，上升 {_r(d1 - d0, 1)} 个百分点，偿债压力快速累积。",
                {"from_year": prev["year"], "to_year": cur["year"], "from": d0, "to": d1})

    if len(periods) >= 3:
        a, b, c = periods[-3], periods[-2], periods[-1]
        i0, i1, i2 = _f(a.get("inventory_days")), _f(b.get("inventory_days")), _f(c.get("inventory_days"))
        if None not in (i0, i1, i2) and i1 > i0 and i2 > i1 and i0 > 0 and (i2 - i0) / i0 > 0.3:
            add("INVENTORY_WORSEN", "medium", "存货周转天数连续两期恶化",
                f"存货周转天数 {i0} → {i1} → {i2} 天，存在积压或跌价风险。",
                {"years": [a["year"], b["year"], c["year"]], "inventory_days": [i0, i1, i2]})

    gr = _f(cur.get("goodwill_ratio"))
    if gr is not None and gr > 30:
        add("GOODWILL_HEAVY", "high", "商誉占净资产比例过高",
            f"商誉/净资产 = {_r(gr, 1)}%，超过 30%，存在减值冲击净资产的风险。",
            {"year": cur["year"], "goodwill_ratio": gr})

    dr = _f(cur.get("deducted_ratio"))
    if dr is not None and dr < 0.5:
        dp = cur.get("deducted_profit")
        detail = (f"扣非净利润为负（{_r(dp, 2)} 亿元），而净利润为正（{_r(cur.get('net_profit'), 2)} 亿元），盈利依赖非经常性损益。"
                  if dr < 0 else f"扣非净利润/净利润 = {_r(dr, 2)}，利润较大程度依赖非经常性损益。")
        add("LOW_DEDUCTED", "medium", "扣非净利润占比偏低", detail,
            {"year": cur["year"], "deducted_ratio": dr, "deducted_profit": dp})

    if cur.get("revenue_growth") is not None and cur.get("profit_growth") is not None \
            and cur["revenue_growth"] > 0 and cur["profit_growth"] - cur["revenue_growth"] > 50:
        add("GROWTH_SCISSOR", "medium", "净利润增速远超营收增速",
            f"营收同比 {_r(cur['revenue_growth'], 1)}%，净利润同比 {_r(cur['profit_growth'], 1)}%，利润增长缺乏收入支撑。",
            {"year": cur["year"], "revenue_growth": cur["revenue_growth"], "profit_growth": cur["profit_growth"]})

    if len(periods) >= 3:
        a, b, c = periods[-3], periods[-2], periods[-1]
        a0, a1, a2 = _f(a.get("ar_days")), _f(b.get("ar_days")), _f(c.get("ar_days"))
        if None not in (a0, a1, a2) and a1 > a0 and a2 > a1 and a0 > 0 and (a2 - a0) / a0 > 0.3:
            add("AR_WORSEN", "medium", "应收账款周转天数持续恶化",
                f"应收账款周转天数 {a0} → {a1} → {a2} 天，回款效率下降。",
                {"years": [a["year"], b["year"], c["year"]], "ar_days": [a0, a1, a2]})

    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda x: order.get(x["level"], 3))


# ---------------------------------------------------------------------------
# 组装：完整分析结果
# ---------------------------------------------------------------------------

def analysis(stock_code: str, years: int = 5, with_peers: bool = True) -> dict:
    code = str(stock_code).strip().zfill(6)
    panel = _panel()
    rows = panel[panel["stock_code"] == code]
    if rows.empty:
        return {"error": f"未找到股票代码 {code}"}
    name = rows["company_name"].iloc[-1]
    industry = rows["industry"].iloc[-1]

    periods = load_periods(code, years)
    if not periods:
        return {
            "enterprise": {"stock_code": code, "name": name, "industry": _industry_label(industry)},
            "available": False, "reason": "无财务数据（未采集或非上市企业）",
            "kpi": [], "trends": {}, "dupont": {"rows": [], "attribution": None},
            "models": {}, "peers": None, "anomalies": [],
            "data_quality": {"years": 0, "periods": [], "notes": ["该企业无财务数据"]},
        }

    peer = build_peers(code, years) if with_peers else None
    median = _peer_median(peer)
    cur = _latest(periods)

    # 市值口径的 Altman Z 需要公开行情（阶段 4 数据源接入），当前 Z'' 用账面净资产
    market_cap = None

    models = {
        "altman": build_altman(cur, market_cap),
        "piotroski": build_piotroski(periods),
        "beneish": build_beneish(periods),
    }

    missing_keys = [k for k in METRIC_META if all(_f(p.get(k)) is None for p in periods)]
    notes: list[str] = []
    if len(periods) < 2:
        notes.append("仅有一期财报，同比与 F/M 模型不可用")
    if market_cap is None:
        notes.append("未取到总市值（数据源接入在阶段 4 实现），Altman Z 使用 Z'' 账面净资产口径")
    if not peer or len(peer["rows"]) < 2:
        notes.append("同行业可比企业不足，同业对标样本有限")

    return {
        "enterprise": {"stock_code": code, "name": name, "industry": _industry_label(industry)},
        "available": True,
        "latest_year": cur["year"],
        "kpi": build_kpi(periods),
        "trends": build_trends(periods),
        "dupont": build_dupont(periods),
        "models": models,
        "peers": peer,
        "peer_median": median,
        "anomalies": build_anomalies(periods, median),
        "data_quality": {
            "years": len(periods),
            "periods": [{"year": p["year"], "report_type": p["report_type"],
                         "source": p["source"], "derived": p.get("derived", [])} for p in periods],
            "missing_metrics": missing_keys,
            "notes": notes,
        },
    }


def overview(years: int = 5) -> dict:
    panel = _panel()
    items: list[dict] = []
    for code in sorted(panel["stock_code"].drop_duplicates().tolist()):
        periods = load_periods(code, years)
        cur = _latest(periods)
        name = panel[panel["stock_code"] == code]["company_name"].iloc[-1]
        industry = panel[panel["stock_code"] == code]["industry"].iloc[-1]
        items.append({
            "stock_code": code, "name": name, "industry": _industry_label(industry),
            "has_finance": cur is not None, "years": len(periods),
            "latest_year": cur["year"] if cur else None,
            "revenue": _r(_f(cur.get("revenue")) if cur else None, 2),
            "net_profit": _r(_f(cur.get("net_profit")) if cur else None, 2),
            "revenue_growth": _r(_f(cur.get("revenue_growth")) if cur else None, 2),
            "gross_margin": _r(_f(cur.get("gross_margin")) if cur else None, 2),
            "net_margin": _r(_f(cur.get("net_margin")) if cur else None, 2),
            "roe": _r(_f(cur.get("roe")) if cur else None, 2),
            "debt_ratio": _r(_f(cur.get("debt_ratio")) if cur else None, 2),
        })
    return {"total": len(items), "items": items}


def report_markdown(stock_code: str, years: int = 5) -> str:
    a = analysis(stock_code, years)
    if a.get("error"):
        return f"# 金融分析报告\n\n{a['error']}\n"
    ent = a["enterprise"]
    if not a.get("available"):
        return (f"# {ent['name']} 金融分析报告\n\n"
                f"**结论**：无财务数据（{a.get('reason')}）。\n\n")
    lines = [f"# {ent['name']} 金融分析报告", ""]
    lines.append(f"- 行业：{ent.get('industry') or '—'}　股票代码：{ent.get('stock_code') or '—'}")
    lines.append(f"- 分析期间：{a['data_quality']['periods'][0]['year']}–{a['latest_year']}（{a['data_quality']['years']} 期年报）")
    lines.append(f"- 数据来源：CSMAR 契约表（panel_clean）")
    lines.append("")
    lines.append("## 一、关键指标概览")
    lines.append("")
    lines.append("| 指标 | 最新值 | 上期 | 同比 |")
    lines.append("|---|---|---|---|")
    for kpi in a["kpi"]:
        if not kpi["available"]:
            continue
        v = f"{kpi['value']}{kpi['unit']}"
        prev = f"{kpi['prev']}{kpi['unit']}" if kpi["prev"] is not None else "—"
        yoy = f"{kpi['yoy']}%" if kpi["yoy"] is not None else "—"
        lines.append(f"| {kpi['label']} | {v} | {prev} | {yoy} |")
    lines += ["", "## 二、财务预警模型", ""]
    alt = a["models"]["altman"]
    lines.append(f"- **Altman Z-Score**：{'可用' if alt['z']['available'] else '不可用'}（{alt['z']['note'] or '—'}）")
    lines.append(f"- **Altman Z''-Score**：{'可用' if alt['z2']['available'] else '不可用'}（{alt['z2']['note'] or '—'}）")
    pio = a["models"]["piotroski"]
    lines.append(f"- **Piotroski F-Score**：{pio['score'] if pio['available'] else '不可用'} / {pio.get('max_score', 9)}")
    ben = a["models"]["beneish"]
    lines.append(f"- **Beneish M-Score**：{ben['score'] if ben['available'] else '不可用'}")
    if a["anomalies"]:
        lines += ["", "## 三、异常勾稽信号", ""]
        for an in a["anomalies"]:
            lines.append(f"- **[{an['level']}] {an['title']}**：{an['detail']}")
    lines += ["", "---", "", "> 本报告由「财务风险智能预警平台」自动生成，数据来自 CSMAR 契约表，不构成投资建议。"]
    return "\n".join(lines)


