"""📊 数据看板：全局风险态势与数据质量监控。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from streamlit_app.components.layout import kpi_row, page_header
from streamlit_app.utils import charts, data as D
from streamlit_app.utils.styles import footer, insight, setup_page

setup_page("数据看板", "📊")
page_header("数据看板", "全市场风险态势、行业对比与数据质量监控", "📊")

scored = D.load_predictions()
panel = D.load_panel()
latest_year = int(scored["year"].max())
latest = scored[scored["year"] == latest_year]

high = int((latest["risk_level"] == "高风险").sum())
kpi_row(
    [
        {"label": "样本企业数", "value": f"{latest['stock_code'].nunique():,}", "help": f"{latest_year} 年在册样本"},
        {"label": "高风险企业", "value": f"{high}", "delta": f"{high / max(len(latest), 1):.1%}",
         "delta_color": "inverse", "help": "ST 概率 ≥ 50%"},
        {"label": "平均 ST 概率", "value": f"{latest['st_prob'].mean():.1%}", "help": "当期全样本均值"},
        {"label": "实际 ST 家数", "value": f"{int(latest['is_st'].sum())}", "help": "当期真实标签（用于回溯校验）"},
        {"label": "覆盖年度", "value": f"{int(panel['year'].min())}-{latest_year}"},
    ]
)

st.markdown("---")
tab1, tab2, tab3 = st.tabs(["🌡️ 行业态势", "📈 时间趋势", "🏭 企业排行"])

with tab1:
    left, right = st.columns([1.2, 1])
    with left:
        st.plotly_chart(charts.industry_risk_bar(latest), use_container_width=True)
    with right:
        st.plotly_chart(charts.risk_distribution(latest), use_container_width=True)
    st.plotly_chart(charts.industry_year_heatmap(scored), use_container_width=True)
    insight("读法：颜色越深代表该行业当年平均 ST 概率越高；纵向对比可发现行业性风险周期，"
            "横向对比用于识别相对更脆弱的行业。")

with tab2:
    st.plotly_chart(charts.st_trend(scored), use_container_width=True)
    yearly = (
        scored.groupby("year")
        .agg(企业数=("stock_code", "nunique"), 实际ST=("is_st", "sum"), 平均概率=("st_prob", "mean"),
             高风险=("risk_level", lambda s: int((s == "高风险").sum())))
        .reset_index()
    )
    yearly["平均概率"] = (yearly["平均概率"] * 100).round(2).astype(str) + "%"
    st.dataframe(yearly, use_container_width=True, hide_index=True)
    insight("模型预测均值（蓝点线）应领先于实际 ST 家数（灰柱）的变化，这正是预警价值所在；"
            "若两者同步甚至滞后，说明模型的信息含量不足。")

with tab3:
    top_n = st.slider("展示企业数", 10, 50, 20, step=5)
    st.plotly_chart(charts.top_risk_bar(latest, top_n), use_container_width=True)
    table = latest.sort_values("st_prob", ascending=False).head(top_n)[
        ["stock_code", "company_name", "industry", "st_prob", "risk_level", "risk_percentile"]
    ].copy()
    table["st_prob"] = (table["st_prob"] * 100).round(2)
    table["risk_percentile"] = (table["risk_percentile"] * 100).round(1)
    st.dataframe(
        table.rename(columns={"stock_code": "股票代码", "company_name": "企业简称", "industry": "行业",
                              "st_prob": "ST概率(%)", "risk_level": "风险等级", "risk_percentile": "风险分位(%)"}),
        use_container_width=True, hide_index=True,
    )

st.markdown("---")
st.subheader("🌏 宏观环境")
macro = D.macro_table()
if macro.empty:
    st.info("未找到宏观指标数据（data/external/macro_industry.csv）")
else:
    c1, c2 = st.columns([1, 1.3])
    with c1:
        year = st.selectbox("选择年份", sorted(macro["year"].unique(), reverse=True))
        st.plotly_chart(charts.macro_dashboard(macro, int(year)), use_container_width=True)
    with c2:
        row = macro[macro["year"] == year].iloc[0]
        labels = {"gdp_growth": "GDP 增速", "m2_growth": "M2 增速", "cpi_yoy": "CPI 同比",
                  "ppi_yoy": "PPI 同比", "social_financing_growth": "社融增速", "pmi_manufacturing": "制造业 PMI"}
        cols = st.columns(3)
        for i, (col, label) in enumerate(labels.items()):
            if col in row:
                cols[i % 3].metric(label, f"{row[col]:.1f}%")
        insight("宏观指标作为控制变量进入模型，用于剥离系统性环境变化，"
                "使企业间比较聚焦于个体经营差异，而非行业或周期红利。")

st.markdown("---")
st.subheader("🧪 数据质量监控")
q1, q2, q3, q4 = st.columns(4)
from config.feature_registry import FEATURE_KEYS

feature_cols = [c for c in FEATURE_KEYS if c in panel.columns]
q1.metric("特征缺失率", f"{panel[feature_cols].isna().mean().mean():.2%}")
q2.metric("重复记录", f"{int(panel.duplicated(['stock_code', 'year']).sum())}")
q3.metric("正样本率", f"{panel['is_st'].mean():.2%}")
q4.metric("数据年度数", f"{panel['year'].nunique()}")

quality = pd.DataFrame(
    {
        "检查项": ["主键唯一性", "标签完整性", "特征缺失率", "行业覆盖", "异常值处理"],
        "结果": [
            "通过" if panel.duplicated(["stock_code", "year"]).sum() == 0 else "存在重复",
            "通过" if panel["is_st"].notna().all() else "存在缺失",
            f"{panel[feature_cols].isna().mean().mean():.2%}",
            f"{panel['industry'].nunique()} 个行业",
            "已按 1%/99% 缩尾",
        ],
    }
)
st.dataframe(quality, use_container_width=True, hide_index=True)

footer()
