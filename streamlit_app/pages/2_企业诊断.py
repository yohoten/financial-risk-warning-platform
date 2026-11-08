"""🏢 单企业风险诊断：评级、六维雷达、SHAP 归因、历史轨迹。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from config.feature_registry import FEATURE_MAP
from streamlit_app.components.layout import page_header
from streamlit_app.utils import charts, data as D
from streamlit_app.utils.styles import footer, insight, risk_card_html, setup_page

setup_page("企业诊断", "🏢")
page_header("企业诊断", "输入股票代码，获取风险评级、归因解释与历史轨迹", "🏢")

options = D.company_options()
if options.empty:
    st.error("暂无企业评分数据，请先运行 python -m models.predict 或刷新页面。")
    st.stop()

scored = D.load_predictions()

col_a, col_b = st.columns([1.6, 1])
with col_a:
    labels = options["company_name"].astype(str) + "（" + options["stock_code"].astype(str) + "）"
    choice = st.selectbox("选择企业", labels.tolist(), index=0)
    stock_code = choice.split("（")[-1].rstrip("）")
with col_b:
    years = sorted(scored[scored["stock_code"] == stock_code]["year"].unique(), reverse=True)
    year = st.selectbox("数据年度", years, index=0)

company = scored[(scored["stock_code"] == stock_code) & (scored["year"] == year)].iloc[0]
peers = scored[(scored["year"] == year) & (scored["industry"] == company["industry"])]
rank = int((peers["st_prob"] > company["st_prob"]).sum() + 1)

st.markdown("---")
c1, c2, c3, c4, c5 = st.columns([1.3, 1, 1, 1, 1])
with c1:
    st.markdown(
        risk_card_html(company["risk_level"], company["risk_level"],
                       label=f"{company['company_name']} · {company['industry']}",
                       hint=f"ST 概率 {company['st_prob']:.1%}"),
        unsafe_allow_html=True,
    )
c2.metric("ST 概率", f"{company['st_prob']:.1%}")
c3.metric("风险分位", f"{company['risk_percentile']:.0%}", help="全样本中风险高于该企业的比例")
c4.metric("同业排名", f"{rank}/{len(peers)}", help="同行业同年度企业中的风险位次")
c5.metric("行业均值", f"{peers['st_prob'].mean():.1%}", delta=f"{(company['st_prob'] - peers['st_prob'].mean()):+.1%}",
          delta_color="inverse")

st.markdown("---")
left, right = st.columns([1, 1.15])

row = scored[(scored["stock_code"] == stock_code) & (scored["year"] == year)].iloc[0]
scores = charts.dimension_scores(row, scored)
with left:
    st.plotly_chart(charts.radar(scores, str(company["company_name"])), use_container_width=True)
    insight("健康度为同侪相对分位（0-100，越高越健康）；某维度低于 40 分即提示该环节存在明显短板。")

with right:
    st.subheader("🔍 SHAP 风险归因")
    try:
        from models.shap_analysis import local_contribution

        contrib = local_contribution(stock_code, int(year))
        st.plotly_chart(
            charts.waterfall(contrib["contributions"], contrib["base_value"], contrib["prediction"]),
            use_container_width=True,
        )
        insight("红色向右为推高风险的因子，绿色向左为降低风险的因子；"
                "数值为 log-odds 贡献，绝对值越大影响越强。")
    except Exception as exc:
        st.warning(f"SHAP 归因不可用：{exc}")
        st.info("请先运行 `python -m models.shap_analysis` 生成解释缓存。")
        contrib = None

st.markdown("---")
st.subheader("📉 历史风险轨迹")
history = scored[scored["stock_code"] == stock_code].sort_values("year")
st.plotly_chart(charts.history_line(history), use_container_width=True)

st.markdown("---")
col_l, col_r = st.columns([1.1, 1])
with col_l:
    st.subheader("⚠️ 关键风险因子明细")
    if contrib is not None:
        table = contrib["contributions"].head(12).copy()
        table["取值"] = table["取值"].map(lambda v: f"{v:,.3f}")
        st.dataframe(table.rename(columns={"中文名": "指标", "SHAP值": "SHAP贡献", "方向": "作用方向"}),
                     use_container_width=True, hide_index=True)
with col_r:
    st.subheader("📌 核心财务指标")
    keys = ["roa", "debt_to_asset", "current_ratio", "ocf_to_net_profit", "revenue_growth", "mdna_negative"]
    rows = []
    for k in keys:
        if k not in scored.columns:
            continue
        value = company[k]
        peer_med = peers[k].median()
        rows.append({
            "指标": FEATURE_MAP[k].cn,
            "企业值": round(float(value), 3),
            "行业中位数": round(float(peer_med), 3),
            "偏离": round(float(value - peer_med), 3),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    insight("偏离为负且指标为正向指标时，说明该环节弱于同业，应结合 SHAP 归因共同判断。")

footer()
