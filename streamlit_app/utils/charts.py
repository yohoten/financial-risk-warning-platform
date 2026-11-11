"""Plotly 图表工厂。

全部图表使用 Plotly 而非 Matplotlib，原因：
1. 中文字体无需额外配置，容器内不会出现方块；
2. 原生支持悬停、缩放、导出，交互体验更好；
3. 主题可通过 `PLOT_TEMPLATE` 统一控制。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from config.feature_registry import FEATURE_MAP, FEATURE_GROUP_LABELS, RADAR_DIMENSIONS, by_group
from config.settings import RISK_COLORS

PLOT_TEMPLATE = "plotly_white"
BLUE = "#1f77b4"
RED = "#d62728"
GREEN = "#2ca02c"
ORANGE = "#ff7f0e"


def _thresholds() -> dict:
    """与评估/监控同源的风险分级阈值（缺失元信息时退回 settings 兜底值）。"""
    from models.metrics import load_thresholds

    return load_thresholds()


def _layout(fig: go.Figure, title: str = "", height: int = 360) -> go.Figure:
    fig.update_layout(
        template=PLOT_TEMPLATE,
        title=title,
        height=height,
        margin=dict(l=10, r=10, t=40 if title else 16, b=10),
        font=dict(family="Microsoft YaHei, PingFang SC, sans-serif", size=12),
        hoverlabel=dict(font_size=12),
    )
    return fig


# ---------------------------------------------------------------------------
# 看板
# ---------------------------------------------------------------------------
def industry_risk_bar(df: pd.DataFrame, top_n: int = 12) -> go.Figure:
    """行业平均风险概率 + 企业数量双轴图。"""
    th = _thresholds()
    g = df.groupby("industry").agg(avg_prob=("st_prob", "mean"), count=("stock_code", "nunique"),
                                   high=("risk_level", lambda s: (s == "高风险").sum())).reset_index()
    g = g.sort_values("avg_prob", ascending=True).tail(top_n)

    fig = go.Figure()
    fig.add_bar(x=g["avg_prob"], y=g["industry"], orientation="h", name="平均风险概率",
                marker_color=[RED if v >= th["high"] else ORANGE if v >= th["medium"] else GREEN for v in g["avg_prob"]],
                text=[f"{v:.1%}" for v in g["avg_prob"]], textposition="outside")
    fig.add_scatter(x=g["avg_prob"], y=g["industry"], mode="markers", name="高风险企业数",
                    marker=dict(size=np.clip(g["high"] * 3 + 6, 6, 26), color="rgba(31,119,180,.45)",
                                line=dict(color=BLUE, width=1)),
                    hovertemplate="%{y}<br>高风险企业数 %{marker.size}<extra></extra>")
    fig.update_xaxes(title="平均 ST 概率", tickformat=".0%")
    return _layout(fig, "行业风险分布（气泡大小=高风险企业数）", 400)


def industry_year_heatmap(df: pd.DataFrame) -> go.Figure:
    """行业 × 年度 风险热力图。"""
    pivot = df.pivot_table(index="industry", columns="year", values="st_prob", aggfunc="mean")
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values, x=pivot.columns, y=pivot.index,
            colorscale=[[0, "#e8f5e9"], [0.5, "#ffd54f"], [1, "#c62828"]],
            colorbar=dict(title="平均<br>ST概率", tickformat=".0%"),
            hovertemplate="%{y} · %{x}年<br>平均ST概率 %{z:.1%}<extra></extra>",
        )
    )
    fig.update_yaxes(autorange="reversed")
    return _layout(fig, "行业 × 年度 风险热力图", 420)


def st_trend(df: pd.DataFrame) -> go.Figure:
    """年度 ST 企业数与占比趋势。"""
    g = df.groupby("year").agg(companies=("stock_code", "nunique"),
                               st=("is_st", "sum"), avg_prob=("st_prob", "mean")).reset_index()
    g["st_ratio"] = g["st"] / g["companies"]

    fig = go.Figure()
    fig.add_bar(x=g["year"], y=g["st"], name="实际 ST 家数", marker_color="#90a4ae",
                hovertemplate="%{x}年<br>ST %{y} 家<extra></extra>")
    fig.add_scatter(x=g["year"], y=g["st_ratio"], name="ST 占比", yaxis="y2", mode="lines+markers",
                    line=dict(color=RED, width=3), hovertemplate="%{x}年<br>占比 %{y:.2%}<extra></extra>")
    fig.add_scatter(x=g["year"], y=g["avg_prob"], name="平均预测概率", yaxis="y2", mode="lines",
                    line=dict(color=BLUE, width=2, dash="dot"),
                    hovertemplate="%{x}年<br>平均概率 %{y:.1%}<extra></extra>")
    fig.update_layout(yaxis=dict(title="企业数"), yaxis2=dict(title="占比", overlaying="y", side="right", tickformat=".0%"))
    return _layout(fig, "年度 ST 趋势与模型预测均值", 380)


def top_risk_bar(df: pd.DataFrame, top_n: int = 20) -> go.Figure:
    """TOP-N 高风险企业。"""
    top = df.sort_values("st_prob", ascending=True).tail(top_n)
    labels = top["company_name"].astype(str) + " (" + top["stock_code"].astype(str) + ")"
    fig = go.Figure(
        go.Bar(x=top["st_prob"], y=labels, orientation="h",
               marker_color=[RISK_COLORS.get(lv, BLUE) for lv in top["risk_level"]],
               text=[f"{v:.1%}" for v in top["st_prob"]], textposition="outside",
               hovertemplate="%{y}<br>ST概率 %{x:.1%}<extra></extra>")
    )
    fig.update_xaxes(title="ST 概率", tickformat=".0%")
    return _layout(fig, f"TOP {top_n} 高风险企业", max(360, top_n * 22))


def risk_distribution(df: pd.DataFrame) -> go.Figure:
    """风险等级分布（环形图）。"""
    counts = df["risk_level"].value_counts().reindex(["高风险", "中风险", "低风险"]).fillna(0)
    fig = go.Figure(
        go.Pie(labels=counts.index, values=counts.values, hole=0.55,
               marker=dict(colors=[RISK_COLORS[k] for k in counts.index]),
               textinfo="label+percent", hovertemplate="%{label}: %{value} 家<extra></extra>")
    )
    return _layout(fig, "风险等级分布", 320)


def macro_dashboard(macro: pd.DataFrame, year: int) -> go.Figure:
    """宏观指标雷达（当年 vs 近五年均值）。"""
    if macro.empty:
        return _layout(go.Figure(), "宏观指标缺失", 300)
    cols = ["gdp_growth", "m2_growth", "cpi_yoy", "ppi_yoy", "social_financing_growth", "pmi_manufacturing"]
    labels = ["GDP增速", "M2增速", "CPI", "PPI", "社融增速", "制造业PMI"]
    cols = [c for c in cols if c in macro.columns]
    labels = labels[: len(cols)]
    current = macro[macro["year"] == year][cols].iloc[0] if (macro["year"] == year).any() else macro[cols].iloc[-1]
    mean5 = macro[macro["year"].between(year - 4, year)][cols].mean()

    fig = go.Figure()
    fig.add_scatterpolar(r=current.values, theta=labels, fill="toself", name=f"{year}年", line_color=BLUE)
    fig.add_scatterpolar(r=mean5.values, theta=labels, fill="toself", name="近5年均值",
                         line_color=ORANGE, opacity=0.6)
    fig.update_layout(polar=dict(radialaxis=dict(visible=True, showticklabels=False)))
    return _layout(fig, "宏观环境（当年 vs 近五年均值）", 360)


# ---------------------------------------------------------------------------
# 企业诊断
# ---------------------------------------------------------------------------
def dimension_scores(row: pd.Series, panel: pd.DataFrame) -> pd.DataFrame:
    """六维健康度评分（0-100，分数越高越健康）。

    口径：企业该维度内所有特征在全样本中的分位排名，按指标方向翻转后取均值。
    这是"相对同侪"的评价，便于跨企业横向比较。
    """
    scores = []
    for dim in RADAR_DIMENSIONS:
        specs = [f for f in by_group(dim) if f.key in panel.columns and f.key in row.index]
        vals = []
        for spec in specs:
            series = pd.to_numeric(panel[spec.key], errors="coerce").dropna()
            value = pd.to_numeric(pd.Series([row[spec.key]]), errors="coerce").iloc[0]
            if series.empty or pd.isna(value):
                continue
            pct = float((series <= value).mean()) * 100
            vals.append(pct if spec.higher_better else 100 - pct)
        scores.append({"维度": FEATURE_GROUP_LABELS[dim], "健康度": round(float(np.mean(vals)), 1) if vals else 50.0})
    return pd.DataFrame(scores)


def radar(scores: pd.DataFrame, name: str) -> go.Figure:
    dims = scores["维度"].tolist()
    vals = scores["健康度"].tolist()
    fig = go.Figure(
        go.Scatterpolar(r=vals + vals[:1], theta=dims + dims[:1], fill="toself",
                        line=dict(color=BLUE, width=2), name=name,
                        hovertemplate="%{theta}: %{r:.0f} 分<extra></extra>")
    )
    fig.add_scatterpolar(r=[60] * (len(dims) + 1), theta=dims + dims[:1], mode="lines",
                         line=dict(color="#cbd5e1", dash="dot", width=1), name="同业基准 60")
    fig.update_layout(polar=dict(radialaxis=dict(range=[0, 100], showticklabels=True, tickfont=dict(size=9))))
    return _layout(fig, "六维健康度雷达", 400)


def history_line(history: pd.DataFrame) -> go.Figure:
    th = _thresholds()
    fig = go.Figure()
    fig.add_scatter(x=history["year"], y=history["st_prob"], mode="lines+markers+text",
                    text=[f"{v:.1%}" for v in history["st_prob"]], textposition="top center",
                    line=dict(color=RED, width=3), marker=dict(size=9),
                    hovertemplate="%{x}年<br>ST概率 %{y:.1%}<extra></extra>")
    fig.add_hrect(y0=th["high"], y1=1, fillcolor=RED, opacity=0.06, line_width=0)
    fig.add_hrect(y0=th["medium"], y1=th["high"], fillcolor=ORANGE, opacity=0.06, line_width=0)
    fig.update_yaxes(title="ST 概率", tickformat=".0%", range=[0, max(0.6, history["st_prob"].max() * 1.25)])
    fig.update_xaxes(title="年度", dtick=1)
    return _layout(fig, "历史风险轨迹", 320)


def waterfall(contributions: pd.DataFrame, base_value: float, prediction: float, top_n: int = 12) -> go.Figure:
    """SHAP 归因瀑布图（Plotly 实现，中文友好）。

    正的 SHAP 值推高 ST 概率，负值降低 ST 概率；末端为标准化的模型输出概率。
    """
    df = contributions.head(top_n).iloc[::-1]
    labels = df["中文名"].tolist() + ["模型基准值"]
    values = df["SHAP值"].tolist() + [base_value]

    fig = go.Figure(
        go.Waterfall(
            orientation="h",
            measure=["relative"] * len(df) + ["absolute"],
            y=labels,
            x=values,
            text=[f"{v:+.3f}" for v in df["SHAP值"]] + [f"{base_value:+.3f}"],
            textposition="outside",
            connector=dict(line=dict(color="#cbd5e1")),
            increasing=dict(marker=dict(color=RED)),
            decreasing=dict(marker=dict(color=GREEN)),
            totals=dict(marker=dict(color="#64748b")),
        )
    )
    fig.update_xaxes(title="对 log-odds 的贡献（+ 推高风险 / - 降低风险）")
    fig.update_layout(title=f"风险归因瀑布图（模型输出 P(ST)={prediction:.1%}）")
    return _layout(fig, f"风险归因瀑布图（P(ST)={prediction:.1%}）", max(380, len(labels) * 26))


# ---------------------------------------------------------------------------
# 模型解释
# ---------------------------------------------------------------------------
def importance_bar(imp: pd.DataFrame, top_n: int = 20) -> go.Figure:
    df = imp.head(top_n).iloc[::-1]
    fig = go.Figure(
        go.Bar(x=df["importance"], y=df["中文名"], orientation="h",
               marker_color=BLUE, text=[f"{v:.4f}" for v in df["importance"]], textposition="outside",
               customdata=df["feature"], hovertemplate="%{y} (%{customdata})<br>mean|SHAP| %{x:.4f}<extra></extra>")
    )
    fig.update_xaxes(title="平均 |SHAP| 值")
    return _layout(fig, f"全局特征重要性 TOP {top_n}", max(360, top_n * 24))


def dependence_scatter(df: pd.DataFrame, feature_cn: str) -> go.Figure:
    fig = go.Figure(
        go.Scattergl(x=df["feature_value"], y=df["shap_value"], mode="markers",
                     marker=dict(size=5, color=df["shap_value"], colorscale="RdBu_r", opacity=0.65,
                                 colorbar=dict(title="SHAP")),
                     hovertemplate=f"{feature_cn}: %{{x:.3f}}<br>SHAP %{{y:+.3f}}<extra></extra>")
    )
    fig.add_hline(y=0, line=dict(color="#94a3b8", dash="dot"))
    fig.update_xaxes(title=feature_cn)
    fig.update_yaxes(title="SHAP 值（正=推高风险）")
    return _layout(fig, f"{feature_cn} 的边际效应", 380)


def interaction_heatmap(pairs: pd.DataFrame, top_n: int = 8) -> go.Figure:
    """交互强度热力图：把长表还原为对称矩阵。"""
    if pairs.empty:
        return _layout(go.Figure(), "无交互数据", 300)
    top_pairs = pairs.head(40)
    names = list(dict.fromkeys(top_pairs["feature_a"].tolist() + top_pairs["feature_b"].tolist()))[:top_n]
    matrix = pd.DataFrame(0.0, index=names, columns=names)
    for _, r in top_pairs.iterrows():
        if r["feature_a"] in names and r["feature_b"] in names:
            matrix.loc[r["feature_a"], r["feature_b"]] = r["交互强度"]
            matrix.loc[r["feature_b"], r["feature_a"]] = r["交互强度"]

    labels = [FEATURE_MAP[n].cn if n in FEATURE_MAP else n for n in names]
    fig = go.Figure(
        go.Heatmap(z=matrix.values, x=labels, y=labels, colorscale="YlOrRd",
                   hovertemplate="%{y} × %{x}<br>交互强度 %{z:.4f}<extra></extra>")
    )
    return _layout(fig, "特征交互强度热力图", 420)


def metric_compare(metrics: dict) -> go.Figure:
    """五模型 AUC/KS/F1/Brier 对比。"""
    rows = []
    for name, m in metrics.items():
        if not isinstance(m, dict) or "auc" not in m:
            continue
        rows.append({"model": name, "AUC": m.get("auc"), "KS": m.get("ks"), "F1": m.get("f1")})
    df = pd.DataFrame(rows)
    if df.empty:
        return _layout(go.Figure(), "暂无模型指标", 300)

    fig = go.Figure()
    for metric, color in (("AUC", BLUE), ("KS", ORANGE), ("F1", GREEN)):
        fig.add_bar(x=df["model"], y=df[metric], name=metric, marker_color=color,
                    text=[f"{v:.3f}" for v in df[metric]], textposition="outside")
    fig.update_layout(barmode="group", yaxis=dict(range=[0, 1.05], title="指标值"))
    return _layout(fig, "五模型对比（验证集 2023）", 380)


def calibration_scatter(calib: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_scatter(x=[0, 1], y=[0, 1], mode="lines", name="完美校准",
                    line=dict(color="#94a3b8", dash="dot"))
    fig.add_scatter(x=calib["预测概率"], y=calib["实际违约率"], mode="lines+markers", name="模型",
                    line=dict(color=BLUE, width=3), marker=dict(size=8))
    fig.update_xaxes(title="预测 ST 概率", tickformat=".0%")
    fig.update_yaxes(title="实际 ST 比例", tickformat=".0%")
    return _layout(fig, "概率校准曲线", 380)


def psi_bar(psi: pd.DataFrame, top_n: int = 20) -> go.Figure:
    df = psi.head(top_n).iloc[::-1].copy()
    df["name"] = df["feature"].map(lambda f: FEATURE_MAP[f].cn if f in FEATURE_MAP else f)
    colors = [RED if v > 0.25 else ORANGE if v > 0.1 else GREEN for v in df["psi"]]
    fig = go.Figure(
        go.Bar(x=df["psi"], y=df["name"], orientation="h", marker_color=colors,
               text=[f"{v:.3f}" for v in df["psi"]], textposition="outside",
               hovertemplate="%{y}<br>PSI %{x:.4f}<extra></extra>")
    )
    fig.add_vline(x=0.1, line=dict(color=ORANGE, dash="dash"), annotation_text="关注线 0.1")
    fig.add_vline(x=0.25, line=dict(color=RED, dash="dash"), annotation_text="重训练线 0.25")
    fig.update_xaxes(title="PSI")
    return _layout(fig, f"特征漂移 TOP {top_n}", max(360, top_n * 22))
