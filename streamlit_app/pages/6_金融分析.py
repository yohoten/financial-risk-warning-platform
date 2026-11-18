"""💰 金融分析：KPI / 趋势 / 杜邦 / Altman·Piotroski·Beneish / 异常勾稽 / 同业对标。

与 Vue 大屏（web/src/views/FinanceView.vue）共用同一套 FastAPI ``/finance/*`` 契约，
按同一信息架构逐项落地六能力面板：
    hero 企业卡 + 6 枚评级 chip → KPI 卡片网格 → 六张双轴趋势图 → 杜邦表 + 归因条
    → Altman Z/Z'' + Piotroski F 九信号 + Beneish M 八指数 → 异常勾稽分级
    → 同业雷达 + 分位表格 → 数据说明
主键统一为 ``stock_code``（6 位数字）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

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
from streamlit_app.components.layout import page_header
from streamlit_app.utils import backend
from streamlit_app.utils.styles import footer, insight, setup_page

setup_page("金融分析", "💰")
page_header("金融分析", "KPI · 趋势 · 杜邦分解 · 财务预警模型 · 同业对标 · 异常勾稽", "💰")

# 与 Streamlit 深色主题（.streamlit/config.toml）一致的图表配色
_PLOT_PAPER = "#131d33"
_TEXT = "#e2e8f0"
_TEXT_SUB = "#94a3b8"
_GRID = "rgba(148,163,184,0.18)"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _fmt(v, unit: str = "") -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    if isinstance(v, float):
        return f"{v:.2f}{unit}"
    return f"{v}{unit}"


def _verdict_color(verdict: str | None, kind: str = "altman") -> str:
    if not verdict:
        return COLOR_GRAY
    if kind == "beneish":
        return COLOR_DANGER if "嫌疑" in verdict else COLOR_OK
    if "安全" in verdict:
        return COLOR_OK
    if "灰色" in verdict:
        return COLOR_WARN
    if "困境" in verdict:
        return COLOR_DANGER
    return COLOR_GRAY


def _fscore_color(score, maximum) -> str:
    if score is None or not maximum:
        return COLOR_GRAY
    r = score / maximum
    return COLOR_OK if r >= 0.7 else (COLOR_WARN if r >= 0.4 else COLOR_DANGER)


def _grade_color(grade: str | None) -> str:
    return {
        "AAA": COLOR_OK, "AA": COLOR_OK, "A": "#65a30d",
        "BBB": "#ca8a04", "BB": "#ea580c", "C": COLOR_DANGER,
    }.get(grade or "", COLOR_GRAY)


def _chart_layout(fig: go.Figure, title: str = "", height: int = 300) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color=_TEXT)) if title else None,
        height=height,
        margin=dict(l=48, r=48, t=36 if title else 14, b=28),
        font=dict(family="Microsoft YaHei, PingFang SC, sans-serif", size=11, color=_TEXT),
        paper_bgcolor=_PLOT_PAPER,
        plot_bgcolor=_PLOT_PAPER,
        legend=dict(font=dict(size=10, color=_TEXT_SUB), orientation="h", y=1.14, x=0),
        hoverlabel=dict(font_size=11),
    )
    fig.update_xaxes(gridcolor=_GRID, linecolor=_GRID, tickfont=dict(size=10, color=_TEXT_SUB))
    fig.update_yaxes(gridcolor=_GRID, linecolor=_GRID, tickfont=dict(size=10, color=_TEXT_SUB))
    return fig


def _chip(text: str, color: str) -> str:
    return f'<span class="fin-chip" style="border-color:{color};color:{color}">{text}</span>'


# ---------------------------------------------------------------------------
# 顶部工具条：企业下拉 + 年份切换 + 刷新 + 报告下载
# ---------------------------------------------------------------------------

ov = backend.finance_overview()
items = ov.get("items", [])
if not items:
    st.error("暂无财务数据，请先完成数据流水线（python -m etl.run_pipeline）。")
    st.stop()

codes = [x["stock_code"] for x in items]
labels = {
    x["stock_code"]: (
        f"{x['name']}（{x['stock_code']}）"
        + (f" · {x['latest_year']}" if x.get("has_finance") else " · 无财报")
    )
    for x in items
}

col_ent, col_years, col_refresh, col_report = st.columns([3, 1, 1, 1])
with col_ent:
    stock_code = st.selectbox(
        "企业（stock_code）",
        codes,
        format_func=lambda c: labels.get(c, c),
        index=0,
        key="fin_code",
    )
with col_years:
    years = st.selectbox("分析窗口", [3, 5, 8], index=1, key="fin_years")
with col_refresh:
    st.write("")
    refresh_clicked = st.button("🔄 刷新", key="fin_refresh", use_container_width=True)
with col_report:
    st.write("")
    try:
        report_md = backend.finance_report_markdown(stock_code, years)
    except Exception:  # noqa: BLE001
        report_md = ""
    st.download_button(
        "📄 报告下载",
        data=report_md or "# 报告暂不可用",
        file_name=f"finance-analysis-{stock_code}-{years}y.md",
        mime="text/markdown",
        key="fin_report_dl",
        use_container_width=True,
        disabled=not report_md,
    )

if refresh_clicked:
    with st.spinner("正在从公开数据源刷新市值与行情快照…"):
        try:
            r = backend.refresh_enterprise(stock_code)
            if r.get("ok"):
                cap = r.get("market_cap")
                cap_txt = f" · 总市值 {cap:,.0f} 元" if cap else ""
                st.toast(f"刷新成功（{r.get('source', '公开信源')}{cap_txt}），Altman Z 现已可计算", icon="✅")
            else:
                st.toast(f"刷新未成功：{r.get('error', '未知原因')}（离线契约表不受影响）", icon="⚠️")
        except Exception as exc:  # noqa: BLE001
            st.toast(f"刷新失败：{exc}", icon="⚠️")
    st.cache_data.clear()
    st.rerun()

# ---------------------------------------------------------------------------
# 取数：分析 + 模型概率 + 规则评级（统一风险上下文）
# ---------------------------------------------------------------------------

a = backend.finance_analysis(stock_code, years=years, peers=True)
if a.get("error"):
    st.error(a["error"])
    st.stop()
if not a.get("available"):
    st.warning(f"无财务数据：{a.get('reason', '未采集')}。可点击「🔄 刷新」拉取公开财报。")
    st.stop()

ent = a["enterprise"]
models = a["models"]

model_row = None
try:
    df = backend.predict_codes([stock_code])
    if df is not None and not df.empty:
        model_row = df.iloc[0]
except Exception:  # noqa: BLE001
    model_row = None

rules = None
try:
    rules = backend.risk_rules(stock_code)
    if isinstance(rules, dict) and rules.get("error"):
        rules = None
except Exception:  # noqa: BLE001
    rules = None

altman = models.get("altman", {})
z2 = altman.get("z2", {})
z = altman.get("z", {})
pio = models.get("piotroski", {})
ben = models.get("beneish", {})
anomalies = a.get("anomalies", [])

# ---------------------------------------------------------------------------
# 1. hero 企业卡 + 6 枚评级 chip
# ---------------------------------------------------------------------------

chips: list[str] = []
if model_row is not None:
    lv = model_row.get("risk_level", "数据不足")
    chips.append(_chip(
        f"模型 ST 概率 {float(model_row.get('st_prob') or 0) * 100:.2f}%",
        RISK_COLORS.get(lv, COLOR_GRAY),
    ))
if rules:
    chips.append(_chip(
        f"规则评级 {rules.get('grade', '—')}（{rules.get('grade_label', '—')}）",
        _grade_color(rules.get("grade")),
    ))
chips.append(_chip(f"Z'' {_fmt(z2.get('score'))}", _verdict_color(z2.get("verdict"))))
chips.append(_chip(
    f"F {_fmt(pio.get('score'))}/{pio.get('max_score', 9)}",
    _fscore_color(pio.get("score"), pio.get("max_score", 9)),
))
chips.append(_chip(f"M {_fmt(ben.get('score'))}", _verdict_color(ben.get("verdict"), "beneish")))
chips.append(_chip(f"异常 {len(anomalies)}", COLOR_WARN if anomalies else COLOR_OK))

hero_sub = (
    f"{ent.get('industry') or '未标注行业'} · {ent.get('stock_code')} · "
    f"最新 {a.get('latest_year')} 年报 · {a.get('data_quality', {}).get('years', 0)} 期"
)
st.markdown(
    f'<div class="fin-hero"><div><div class="fin-hero-name">{ent.get("name", "")}</div>'
    f'<div class="fin-hero-sub">{hero_sub}</div></div>'
    f'<div class="fin-chips">{"".join(chips)}</div></div>',
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# 2. KPI 卡片网格（值 + 单位 + 同比箭头 + 上期）
# ---------------------------------------------------------------------------

st.subheader("📊 关键指标")
kpi_html: list[str] = []
for k in a.get("kpi", []):
    if not k.get("available") or k.get("value") is None:
        kpi_html.append(
            f'<div class="fin-kpi off"><div class="fin-kpi-label">{k.get("label", "")}</div>'
            f'<div class="fin-kpi-value">—</div>'
            f'<div class="fin-kpi-foot"><span>无数据</span></div></div>'
        )
        continue
    yoy, prev = k.get("yoy"), k.get("prev")
    if yoy is None:
        yoy_html = "<span>无同比</span>"
    else:
        arrow = "↑" if yoy > 0 else ("↓" if yoy < 0 else "—")
        color = COLOR_OK if k.get("trend") == "up" else (
            COLOR_DANGER if k.get("trend") == "down" else COLOR_GRAY)
        yoy_html = f'<span style="color:{color}">{arrow} {abs(yoy):.2f}%</span>'
    prev_html = f'<span>上期 {_fmt(prev)}</span>' if prev is not None else ""
    kpi_html.append(
        f'<div class="fin-kpi"><div class="fin-kpi-label">{k.get("label", "")}</div>'
        f'<div class="fin-kpi-value">{_fmt(k.get("value"))}'
        f'<span class="unit">{k.get("unit", "")}</span></div>'
        f'<div class="fin-kpi-foot">{yoy_html}{prev_html}</div></div>'
    )
st.markdown(f'<div class="fin-kpi-grid">{"".join(kpi_html)}</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 3. 六张双轴趋势图
# ---------------------------------------------------------------------------

# (分组 key, 标题, [(series_key, 展示类型, 颜色, 轴)])  轴：0=左轴 1=右轴
CHART_SPECS = [
    ("scale", "规模与利润", [
        ("revenue", "bar", COLOR_PRIMARY, 0), ("net_profit", "line", COLOR_OK, 1)]),
    ("profit", "盈利能力（%）", [
        ("gross_margin", "line", COLOR_PRIMARY, 0), ("net_margin", "line", COLOR_ACCENT, 0),
        ("roe", "line", COLOR_OK, 0), ("roa", "line", COLOR_VIOLET, 0)]),
    ("solvency", "偿债与杠杆", [
        ("debt_ratio", "line", COLOR_DANGER, 0), ("current_ratio", "line", COLOR_PRIMARY, 1),
        ("quick_ratio", "line", COLOR_ACCENT, 1)]),
    ("operation", "营运效率", [
        ("ar_days", "line", COLOR_WARN, 0), ("inventory_days", "line", COLOR_VIOLET, 0),
        ("asset_turnover", "line", COLOR_PRIMARY, 1)]),
    ("cashflow", "现金流质量", [
        ("ocf", "bar", COLOR_OK, 0), ("ocf_to_profit", "line", COLOR_PRIMARY, 1)]),
    ("growth", "成长性（%）", [
        ("revenue_growth", "bar", COLOR_PRIMARY, 0), ("profit_growth", "bar", COLOR_ACCENT, 0)]),
]

st.subheader("📈 趋势分析")
trends = a.get("trends", {})
for gkey, title, spec in CHART_SPECS:
    group = trends.get(gkey)
    if not group:
        continue
    series_map = {s["key"]: s for s in group.get("series", [])}
    dual = any(axis == 1 for _, _, _, axis in spec)
    fig = make_subplots(specs=[[{"secondary_y": True}]]) if dual else go.Figure()
    for skey, ctype, color, axis in spec:
        s = series_map.get(skey)
        if not s:
            continue
        xs = [p["year"] for p in s["points"]]
        ys = [p["value"] for p in s["points"]]
        name = f"{s['label']}（{s['unit']}）" if s.get("unit") else s["label"]
        if ctype == "bar":
            trace = go.Bar(x=xs, y=ys, name=name, marker_color=color, opacity=0.85)
        else:
            trace = go.Scatter(x=xs, y=ys, name=name, mode="lines+markers",
                               line=dict(color=color, width=2),
                               marker=dict(size=5, color=color))
        if dual:
            fig.add_trace(trace, secondary_y=(axis == 1))
        else:
            fig.add_trace(trace)
    layout = _chart_layout(fig, title=title, height=300)
    if dual:
        layout.update_layout(
            yaxis=dict(title="", gridcolor=_GRID, linecolor=_GRID,
                       tickfont=dict(size=10, color=_TEXT_SUB)),
            yaxis2=dict(title="", overlaying="y", side="right", showgrid=False,
                        tickfont=dict(size=10, color=_TEXT_SUB)),
        )
    st.plotly_chart(layout, use_container_width=True)

# ---------------------------------------------------------------------------
# 4. 杜邦分解表 + 归因条
# ---------------------------------------------------------------------------

st.subheader("🧮 杜邦分解")
dup = a.get("dupont", {})
st.caption(dup.get("formula", "ROE = 销售净利率 × 总资产周转率 × 权益乘数"))
dup_rows = dup.get("rows", [])
if dup_rows:
    st.dataframe(
        pd.DataFrame(dup_rows).rename(columns={
            "year": "年度", "roe": "ROE(%)", "net_margin": "销售净利率(%)",
            "asset_turnover": "总资产周转率", "equity_multiplier": "权益乘数",
        })[["年度", "ROE(%)", "销售净利率(%)", "总资产周转率", "权益乘数"]],
        use_container_width=True, hide_index=True,
    )

att = dup.get("attribution")
if att:
    contribs = att.get("items", [])
    amax = max([abs(i.get("contrib", 0)) for i in contribs] + [1e-9])
    st.markdown(
        f'<div style="font-size:.8rem;opacity:.75;margin:8px 0 6px">'
        f'{att.get("from_year")} → {att.get("to_year")}　ROE 变动 '
        f'<b>{att.get("roe_delta")}</b> 个百分点，归因：</div>',
        unsafe_allow_html=True,
    )
    bars = []
    for it in contribs:
        c = it.get("contrib", 0)
        color = COLOR_OK if c >= 0 else COLOR_DANGER
        bars.append(
            f'<div class="fin-attr-row"><span class="fin-attr-label">{it.get("label", "")}</span>'
            f'<span class="fin-attr-bar"><i style="width:{abs(c) / amax * 100:.1f}%;background:{color}"></i></span>'
            f'<span class="fin-attr-val" style="color:{color}">{c:+.2f}</span></div>'
        )
    st.markdown("".join(bars), unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 5. 财务预警模型：Altman Z / Z'' + Piotroski F 九信号 + Beneish M 八指数
# ---------------------------------------------------------------------------

st.subheader("⚠️ 财务预警模型")
m1, m2, m3 = st.columns(3)

with m1:
    for key, title, sub in (("z2", "Altman Z''-Score", "非制造业/新兴市场口径"),
                            ("z", "Altman Z-Score", "上市制造业口径（需市值）")):
        m = altman.get(key, {})
        color = _verdict_color(m.get("verdict"))
        missing_html = ""
        if not m.get("score") and m.get("missing"):
            missing_html = (f'<div class="fin-model-missing">'
                            f'缺：{"、".join(m["missing"])}</div>')
        note_html = (f'<div class="fin-model-note">{m["note"]}</div>' if m.get("note") else "")
        st.markdown(
            f'<div class="fin-model"><div class="fin-model-head">'
            f'<span class="fin-model-title">{title}</span>'
            f'<span class="fin-model-score" style="color:{color}">'
            f'{_fmt(m.get("score")) if m.get("score") is not None else "不可计算"}</span></div>'
            f'<div class="fin-model-sub">{sub}</div>'
            f'<div style="color:{color};font-weight:600;font-size:.8rem">{m.get("verdict") or "—"}</div>'
            f'<div class="fin-model-sub">{m.get("thresholds", "")}</div>'
            f'{missing_html}{note_html}</div>',
            unsafe_allow_html=True,
        )

with m2:
    pcolor = _fscore_color(pio.get("score"), pio.get("max_score", 9))
    sig_html = []
    for s in pio.get("signals", []):
        p = s.get("pass")
        if p is True:
            icon, cls = "✓", ""
        elif p is False:
            icon, cls = "✗", " fail"
        else:
            icon, cls = "·", " na"
        sig_html.append(
            f'<li class="{cls}"><span class="icon">{icon}</span>'
            f'<span class="name">{s.get("name", "")}</span>'
            f'<span class="detail">{s.get("detail", "")}</span></li>'
        )
    note_html = (f'<div class="fin-model-note">{pio["note"]}</div>' if pio.get("note") else "")
    st.markdown(
        f'<div class="fin-model"><div class="fin-model-head">'
        f'<span class="fin-model-title">Piotroski F-Score</span>'
        f'<span class="fin-model-score" style="color:{pcolor}">'
        f'{_fmt(pio.get("score"))}/{pio.get("max_score", 9)}</span></div>'
        f'<div class="fin-model-sub">{pio.get("verdict") or "需要连续两期财报"}</div>'
        f'<ul class="fin-sig">{"".join(sig_html)}</ul>{note_html}</div>',
        unsafe_allow_html=True,
    )

with m3:
    bcolor = _verdict_color(ben.get("verdict"), "beneish")
    idx_html = []
    for i in ben.get("indices", []):
        v = i.get("value")
        if v is None:
            icon, cls, txt = "·", " na", "缺"
        elif i.get("source") == "approx":
            icon, cls, txt = "≈", "", _fmt(v)
        else:
            icon, cls, txt = "•", "", _fmt(v)
        idx_html.append(
            f'<li class="{cls}"><span class="icon">{icon}</span>'
            f'<span class="name">{i.get("label", "")}</span>'
            f'<span class="detail">{txt}</span></li>'
        )
    note_html = (f'<div class="fin-model-note">{ben["note"]}</div>' if ben.get("note") else "")
    st.markdown(
        f'<div class="fin-model"><div class="fin-model-head">'
        f'<span class="fin-model-title">Beneish M-Score</span>'
        f'<span class="fin-model-score" style="color:{bcolor}">'
        f'{_fmt(ben.get("score")) if ben.get("score") is not None else "不可计算"}</span></div>'
        f'<div class="fin-model-sub" style="color:{bcolor}">'
        f'{ben.get("verdict") or "需要连续两期财报"}</div>'
        f'<div class="fin-model-sub">{ben.get("thresholds", "")}</div>'
        f'<ul class="fin-sig">{"".join(idx_html)}</ul>{note_html}</div>',
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# 6. 异常勾稽分级
# ---------------------------------------------------------------------------

st.subheader("🚨 异常勾稽")
if not anomalies:
    insight("在现有数据范围内未触发异常规则。")
else:
    lvl_color = {"high": COLOR_DANGER, "medium": COLOR_WARN, "low": COLOR_GRAY}
    lvl_label = {"high": "高", "medium": "中", "low": "低"}
    for an in anomalies:
        lv = an.get("level", "low")
        color = lvl_color.get(lv, COLOR_GRAY)
        st.markdown(
            f'<div class="fin-anomaly" style="border-left-color:{color}">'
            f'<div class="fin-anomaly-head">'
            f'<span class="lvl" style="background:{color}">{lvl_label.get(lv, lv)}</span>'
            f'<span class="title">{an.get("title", "")}</span></div>'
            f'<div class="detail">{an.get("detail", "")}</div></div>',
            unsafe_allow_html=True,
        )

# ---------------------------------------------------------------------------
# 7. 同业对标：雷达 + 分位表格
# ---------------------------------------------------------------------------

peers = a.get("peers")
if peers and peers.get("rows"):
    st.subheader("🏭 同业对标")
    st.caption(peers.get("note", ""))
    metrics = peers.get("metrics", [])
    rows = peers.get("rows", [])

    col_radar, col_tbl = st.columns([1, 1.6])
    with col_radar:
        self_row = next((r for r in rows if r.get("is_self")), None)
        if self_row and self_row.get("percentiles"):
            keys = [m for m in metrics if self_row["percentiles"].get(m["key"]) is not None]
            if keys:
                fig = go.Figure(go.Scatterpolar(
                    r=[self_row["percentiles"][m["key"]] for m in keys],
                    theta=[m["label"] for m in keys],
                    fill="toself", name="同业分位",
                    line=dict(color=COLOR_PRIMARY, width=2),
                    fillcolor="rgba(37,99,235,0.22)",
                    marker=dict(size=5, color=COLOR_PRIMARY),
                ))
                fig.update_layout(
                    polar=dict(
                        bgcolor=_PLOT_PAPER,
                        radialaxis=dict(range=[0, 100], showline=False, gridcolor=_GRID,
                                        tickfont=dict(size=9, color=_TEXT_SUB)),
                        angularaxis=dict(gridcolor=_GRID, tickfont=dict(size=9, color=_TEXT_SUB)),
                    ),
                    paper_bgcolor=_PLOT_PAPER,
                    font=dict(family="Microsoft YaHei, PingFang SC, sans-serif",
                              size=10, color=_TEXT),
                    height=320, margin=dict(l=30, r=30, t=30, b=20),
                    showlegend=False,
                )
                st.plotly_chart(fig, use_container_width=True)

    with col_tbl:
        table_rows = []
        for r in rows:
            row = {"企业": ("★ " if r.get("is_self") else "") + r.get("name", "")}
            for m in metrics:
                val = r.get("metrics", {}).get(m.get("key"))
                pct = (r.get("percentiles") or {}).get(m.get("key"))
                cell = "—" if val is None else str(val)
                if pct is not None:
                    cell += f"（{pct}%）"
                row[m.get("label", "")] = cell
            table_rows.append(row)
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
        st.caption("括号内为同业分位：≥75% 领先（绿）· ≤25% 落后（红）")

# ---------------------------------------------------------------------------
# 8. 数据说明
# ---------------------------------------------------------------------------

st.subheader("📌 数据说明")
dq = a.get("data_quality", {})
sources = sorted({p.get("source", "") for p in dq.get("periods", []) if p.get("source")})
q_rows = [
    f'<div class="q-row"><span class="q-key">来源</span>'
    f'<span>{"；".join(sources) or "—"}</span></div>',
]
if dq.get("missing_metrics"):
    q_rows.append(
        f'<div class="q-row"><span class="q-key">全期缺失</span>'
        f'<span>{"、".join(dq["missing_metrics"])}</span></div>'
    )
for n in dq.get("notes", []):
    q_rows.append(f'<div class="q-row"><span class="q-key">提示</span><span>{n}</span></div>')
q_rows.append(
    '<div class="q-row"><span class="q-key">免责声明</span>'
    '<span>数据来自公开信源，模型结果为规则化测算，不构成投资建议。</span></div>'
)
st.markdown(f'<div class="fin-quality">{"".join(q_rows)}</div>', unsafe_allow_html=True)

footer()
