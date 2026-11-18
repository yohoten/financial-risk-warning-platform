"""ECharts 选配层：本地组件渲染 + 看板图表的 option 工厂。

设计约定：
- ECharts 是「选配」，只在 ``streamlit_app/components/echarts_local/echarts.min.js``
  存在时才可用（``has_echarts()``），否则前端自动退回 Plotly；
- 本模块只做「数据 → ECharts option」的纯转换，不依赖 Plotly，便于单测；
- 配色与 ``charts.py`` 的 BLUE/RED/ORANGE/GREEN 保持一致。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from config.settings import (
    COLOR_ACCENT,
    COLOR_DANGER,
    COLOR_GRAY,
    COLOR_OK,
    COLOR_PRIMARY,
    COLOR_VIOLET,
    COLOR_WARN,
    RISK_COLORS,
)

BLUE = COLOR_PRIMARY
RED = COLOR_DANGER
GREEN = COLOR_OK
ORANGE = COLOR_WARN
GRAY = COLOR_GRAY
ACCENT = COLOR_ACCENT
VIOLET = COLOR_VIOLET

_COMPONENT_DIR = Path(__file__).resolve().parents[1] / "components" / "echarts_local"
_ECHARTS_JS = _COMPONENT_DIR / "echarts.min.js"

# 组件在导入时声明一次；缺少 echarts.min.js 时 index.html 会给出提示并退化为 64px，
# 不会抛异常。has_echarts() 用于在 Python 侧提前拦截，避免渲染空组件。
_render = components.declare_component("echarts_local", path=str(_COMPONENT_DIR))


def has_echarts() -> bool:
    return _ECHARTS_JS.exists()


def render_echarts(option: dict, height: int = 400, key: str | None = None,
                   events: tuple[str, ...] = ("click",)):
    """渲染 ECharts；返回点击事件（无事件时为 None）。"""
    if not has_echarts():
        st.caption("未检测到本地 echarts.min.js，已退回 Plotly 渲染。")
        return None
    return _render(option=option, height=int(height), events=list(events), key=key, default=None)


# ---------------------------------------------------------------------------
# 看板 option 工厂（与 charts.py 对应）
# ---------------------------------------------------------------------------
def _level_color(avg: float, th: dict) -> str:
    if avg >= th["high"]:
        return RED
    if avg >= th["medium"]:
        return ORANGE
    return GREEN


def _thresholds() -> dict:
    from models.metrics import load_thresholds

    return load_thresholds()


def industry_risk_bar_option(df: pd.DataFrame, top_n: int = 12) -> dict:
    """行业平均风险概率横向柱（颜色按阈值）。"""
    th = _thresholds()
    g = df.groupby("industry").agg(avg_prob=("st_prob", "mean"),
                                   count=("stock_code", "nunique")).reset_index()
    g = g.sort_values("avg_prob", ascending=True).tail(top_n)
    items = [
        {"value": round(v, 4), "name": ind,
         "itemStyle": {"color": _level_color(v, th)}}
        for ind, v in zip(g["industry"], g["avg_prob"])
    ]
    return {
        "grid": {"left": 8, "right": 40, "top": 8, "bottom": 8, "containLabel": True},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "xAxis": {"type": "value", "axisLabel": {"formatter": "{value}%"}},
        "yAxis": {"type": "category", "data": g["industry"].tolist()},
        "series": [{"type": "bar", "data": items,
                    "label": {"show": True, "position": "right", "formatter": "{c}%"},
                    "barMaxWidth": 22}],
    }


def industry_year_heatmap_option(df: pd.DataFrame) -> dict:
    """行业 × 年度 风险热力图。"""
    pivot = df.pivot_table(index="industry", columns="year", values="st_prob", aggfunc="mean")
    years = [int(y) for y in pivot.columns]
    industries = [str(i) for i in pivot.index]
    data = []
    for yi, ind in enumerate(industries):
        for xi, y in enumerate(years):
            val = pivot.iloc[yi, xi]
            if pd.notna(val):
                data.append([xi, yi, round(float(val), 4)])
    return {
        "grid": {"left": 8, "right": 16, "top": 8, "bottom": 8, "containLabel": True},
        "tooltip": {"formatter": "{b} · {c} 年<br/>平均ST概率 {d}%"},
        "xAxis": {"type": "category", "data": years, "splitArea": {"show": True}},
        "yAxis": {"type": "category", "data": industries, "splitArea": {"show": True}},
        "visualMap": {"min": 0, "max": max((d[2] for d in data), default=1), "calculable": True,
                      "orient": "vertical", "right": 0, "inRange": {"color": ["#e8f5e9", "#ffd54f", "#c62828"]}},
        "series": [{"type": "heatmap", "data": data,
                    "label": {"show": False},
                    "emphasis": {"itemStyle": {"shadowBlur": 8, "shadowColor": "rgba(0,0,0,.4)"}}}],
    }


def st_trend_option(df: pd.DataFrame) -> dict:
    """年度 ST 家数（柱）+ ST 占比 / 平均预测概率（双线，右轴）。"""
    g = df.groupby("year").agg(companies=("stock_code", "nunique"),
                               st=("is_st", "sum"), avg_prob=("st_prob", "mean")).reset_index()
    g["st_ratio"] = g["st"] / g["companies"]
    years = [int(y) for y in g["year"]]
    return {
        "tooltip": {"trigger": "axis"},
        "legend": {"data": ["实际 ST 家数", "ST 占比", "平均预测概率"], "top": 0},
        "grid": {"left": 8, "right": 8, "top": 32, "bottom": 8, "containLabel": True},
        "xAxis": {"type": "category", "data": years},
        "yAxis": [
            {"type": "value", "name": "企业数"},
            {"type": "value", "name": "占比", "axisLabel": {"formatter": "{value}%"},
             "splitLine": {"show": False}},
        ],
        "series": [
            {"name": "实际 ST 家数", "type": "bar", "itemStyle": {"color": GRAY},
             "data": g["st"].tolist()},
            {"name": "ST 占比", "type": "line", "yAxisIndex": 1,
             "itemStyle": {"color": RED}, "lineStyle": {"width": 3},
             "data": [round(v * 100, 2) for v in g["st_ratio"]]},
            {"name": "平均预测概率", "type": "line", "yAxisIndex": 1,
             "itemStyle": {"color": BLUE}, "lineStyle": {"width": 2, "type": "dashed"},
             "data": [round(v * 100, 2) for v in g["avg_prob"]]},
        ],
    }


def risk_sankey_option(df: pd.DataFrame, top_features: list[str] | None = None) -> dict:
    """风险桑基图：特征维度 → 高风险贡献方向 → 风险等级（示意，可按需扩展）。"""
    # 简化示意：三大风险等级的企业数流向。真实特征级桑基需 SHAP 归因聚合，放 P1。
    counts = df["risk_level"].value_counts().reindex(["高风险", "中风险", "低风险"]).fillna(0)
    levels = ["高风险", "中风险", "低风险"]
    nodes = [{"name": "预警平台"}]
    nodes += [{"name": lv, "itemStyle": {"color": RISK_COLORS[lv]}} for lv in levels]
    links = [{"source": "预警平台", "target": lv, "value": int(counts[lv])} for lv in levels]
    return {
        "tooltip": {"trigger": "item", "triggerOn": "mousemove"},
        "series": [{"type": "sankey", "data": nodes, "links": links,
                    "nodeWidth": 24, "nodeGap": 12, "left": 40, "right": 120,
                    "label": {"fontSize": 12}}],
    }
