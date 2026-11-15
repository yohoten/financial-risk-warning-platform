"""六维企业评分引擎（移植自旧项目 server/app/services/rules.py）。

数据源改为 ``data/cleaned/panel_clean.parquet``：
- finance  财务健康  ← 资产负债率/净利润/营收/亏损年数
- legal    法律合规  ← litigation_count / penalty_count
- news     舆情声誉  ← MD&A 文本情感（负面占比，舆情代理）
- operation 经营能力 ← 净利润率 / 营收增速（无成立年限）
- credit   信用状况  ← 行政处罚次数（失信/被执行暂缺）
- supply   供应链稳定 ← 暂缺（P2 数据缺口）

原则：没有数据 ≠ 没有风险；数据不足的维度不参与综合评分。
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd

from config import settings
from etl.io_utils import read_table

LEVEL_ORDER = {"green": 0, "yellow": 1, "orange": 2, "red": 3}

DIM_META: dict[str, str] = {
    "finance": "财务健康",
    "legal": "法律合规",
    "news": "舆情声誉",
    "operation": "经营能力",
    "credit": "信用状况",
    "supply": "供应链稳定",
}

GRADE_TABLE = [
    (90, "AAA", "优秀"),
    (80, "AA", "良好"),
    (70, "A", "稳健"),
    (60, "BBB", "关注"),
    (50, "BB", "预警"),
    (0, "C", "高风险"),
]


def _clamp(v: float) -> int:
    return int(max(0, min(100, round(v))))


def score_to_level(score: int | None) -> str:
    if score is None:
        return "gray"
    if score >= 85:
        return "green"
    if score >= 70:
        return "yellow"
    if score >= 55:
        return "orange"
    return "red"


def grade_of(score: float | None) -> tuple[str, str]:
    if score is None:
        return "—", "数据不足"
    for threshold, grade, label in GRADE_TABLE:
        if score >= threshold:
            return grade, label
    return "C", "高风险"


@lru_cache(maxsize=1)
def _panel() -> pd.DataFrame:
    df = read_table(settings.CLEANED_PANEL).copy()
    if "stock_code" in df.columns:
        df["stock_code"] = df["stock_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    if "year" in df.columns:
        df["year"] = df["year"].astype(int)
    return df


def _f(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def compute_indicators(stock_code: str) -> dict | None:
    code = str(stock_code).strip().zfill(6)
    rows = _panel()[_panel()["stock_code"] == code].sort_values("year")
    if rows.empty:
        return None

    latest = rows.iloc[-1]
    prev = rows.iloc[-2] if len(rows) > 1 else None

    # --- 财务 ---
    debt_ratio = _f(latest.get("total_liabilities")) / _f(latest.get("total_assets")) * 100 \
        if _f(latest.get("total_liabilities")) is not None and _f(latest.get("total_assets")) else None
    net_profit = _f(latest.get("net_profit_parent")) or _f(latest.get("net_profit"))
    revenue = _f(latest.get("revenue"))
    growth = None
    if prev is not None and _f(prev.get("revenue")) and revenue is not None:
        growth = round((revenue - _f(prev.get("revenue"))) / abs(_f(prev.get("revenue"))) * 100, 1)
    margin = round(net_profit / revenue * 100, 1) if net_profit is not None and revenue else None
    loss_years = int((rows["net_profit"].fillna(0) < 0).sum()) if "net_profit" in rows.columns else 0
    finance_ok = revenue is not None and debt_ratio is not None
    finance = {
        "available": finance_ok,
        "year": int(latest["year"]),
        "debt_ratio": round(debt_ratio, 2) if debt_ratio is not None else None,
        "net_profit": net_profit,
        "revenue": revenue,
        "revenue_growth": growth,
        "net_margin": margin,
        "source": "CSMAR",
        "loss_years": loss_years,
    } if finance_ok else {"available": False, "note": "无公开财报（数据不足）"}

    # --- 法律 / 信用（同源） ---
    litigation = _f(latest.get("litigation_count")) or 0
    penalty = _f(latest.get("penalty_count")) or 0
    legal_available = bool(_f(latest.get("legal_available")))

    # --- 舆情（MD&A 文本情感，舆情代理） ---
    pos = _f(latest.get("mdna_positive")) or 0
    neg = _f(latest.get("mdna_negative")) or 0
    unc = _f(latest.get("mdna_uncertainty")) or 0
    text_available = bool(_f(latest.get("text_available")))
    news_total = 1.0 if text_available else 0.0
    negative_ratio = round(neg / (pos + neg + unc), 3) if (pos + neg + unc) > 0 else 0.0

    data_status = {
        "finance": "ok" if finance_ok else "never",
        "legal": "ok" if legal_available and (litigation or penalty) else ("empty" if legal_available else "never"),
        "news": "ok" if text_available else "never",
    }

    return {
        "data_status": data_status,
        "finance": finance,
        "legal": {
            "count": int(litigation),
            "amount": 0.0,           # 涉案金额契约表未含
            "penalty": int(penalty),
            "criminal": 0,           # 刑事案件契约表未含
            "trademark_admin": 0,
        },
        "news": {
            "total": news_total,
            "negative": neg,
            "negative_ratio": negative_ratio,
            "recent_negative": 0,    # MD&A 无时间维度
        },
        "operation": {
            "age_years": None,       # 契约表未含成立日期
            "revenue_growth": growth,
            "net_margin": margin,
        },
        "credit": {"shixin": 0, "zhixing": 0, "penalty": int(penalty)},
        "supply": {"contract_disputes": 0, "supply_news_negative": 0},
    }


def _status(ind: dict, dim: str) -> str:
    return (ind.get("data_status") or {}).get(dim, "never")


def dim_score(dim: str, ind: dict) -> tuple[int | None, str]:
    if dim == "finance":
        if _status(ind, "finance") != "ok" or not ind["finance"].get("available"):
            return None, "无公开财报数据（未采集或数据不足）"
        fin = ind["finance"]
        s = 100.0
        debt = fin.get("debt_ratio") or 0
        if debt >= 85:
            s -= 45
        elif debt >= 70:
            s -= 30
        elif debt >= 60:
            s -= 15
        if (fin.get("net_profit") or 0) < 0:
            s -= 25
        if fin.get("loss_years", 0) >= 2:
            s -= 10
        return _clamp(s), f"资产负债率 {debt}% · 净利润 {fin.get('net_profit')} 亿元（{fin.get('year')}）"

    if dim == "legal":
        st = _status(ind, "legal")
        if st not in ("ok", "empty"):
            return None, "司法数据未采集（数据不足）"
        s = 100.0
        s -= min(50, ind["legal"]["count"] * 6)
        s -= min(25, ind["legal"]["penalty"] * 10)
        s -= min(20, ind["legal"]["criminal"] * 20)
        return _clamp(s), f"司法/行政记录 {ind['legal']['count']} 项 · 行政处罚 {ind['legal']['penalty']} 次"

    if dim == "news":
        st = _status(ind, "news")
        if st not in ("ok", "empty"):
            return None, "舆情数据未采集（数据不足）"
        n = ind["news"]
        s = 100.0
        s -= min(60, n["negative_ratio"] * 120)
        return _clamp(s), f"MD&A 负面情感占比 {round(n['negative_ratio'] * 100)}%（舆情代理）"

    if dim == "operation":
        op = ind["operation"]
        age = op.get("age_years")
        has_fin = _status(ind, "finance") == "ok" and (
            op.get("net_margin") is not None or op.get("revenue_growth") is not None
        )
        if age is None and not has_fin:
            return None, "无成立年限与财务数据（数据不足）"
        s = 95.0 if age is not None else 90.0
        if op.get("net_margin") is not None:
            if op["net_margin"] < 0:
                s -= 30
            elif op["net_margin"] < 5:
                s -= 8
            elif op["net_margin"] > 20:
                s += 3
        if op.get("revenue_growth") is not None:
            if op["revenue_growth"] < 0:
                s -= 15
            elif op["revenue_growth"] > 20:
                s += 3
        note = "成立年限未知" if age is None else f"成立 {age} 年"
        if op.get("net_margin") is not None:
            note += f" · 净利润率 {op['net_margin']}%"
        if op.get("revenue_growth") is not None:
            note += f" · 营收增速 {op['revenue_growth']}%"
        return _clamp(s), note

    if dim == "credit":
        if _status(ind, "legal") not in ("ok", "empty"):
            return None, "信用/司法数据未采集（数据不足）"
        c = ind["credit"]
        s = 100.0
        s -= min(45, c["shixin"] * 40)
        s -= min(35, c["zhixing"] * 30)
        s -= min(25, c["penalty"] * 12)
        note = f"失信 {c['shixin']} 次 · 被执行 {c['zhixing']} 次 · 行政处罚 {c['penalty']} 次"
        return _clamp(s), note

    if dim == "supply":
        return None, "供应链相关数据未采集（数据不足）"

    return None, "未知维度"


def rules_verdict(stock_code: str) -> dict:
    ind = compute_indicators(stock_code)
    if ind is None:
        return {"error": f"未找到股票代码 {stock_code}"}
    dims: dict[str, dict] = {}
    scores: list[float] = []
    for dim in DIM_META:
        score, note = dim_score(dim, ind)
        level = score_to_level(score)
        dims[dim] = {
            "score": score, "level": level, "label": DIM_META[dim],
            "indicators": ind[dim], "note": note,
        }
        if score is not None:
            scores.append(score)

    overall = round(sum(scores) / len(scores), 1) if scores else None
    grade, grade_label = grade_of(overall)
    level = score_to_level(int(overall) if overall is not None else None)
    if not scores:
        grade, grade_label, level = "—", "无数据，无法评估", "gray"
    return {
        "stock_code": str(stock_code).strip().zfill(6),
        "score": overall, "grade": grade, "grade_label": grade_label, "level": level,
        "dimensions": dims, "indicators": ind,
        "data_status": ind.get("data_status", {}),
    }
