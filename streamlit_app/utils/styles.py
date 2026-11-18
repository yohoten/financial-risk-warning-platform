"""全局样式与页面配置。

配色与前端 web/src/lib/theme.ts 的 C 常量保持一致；
深浅色由 Streamlit 主题（.streamlit/config.toml）决定，本模块用 CSS 变量做适配，
避免硬编码浅色值在深色主题下失效。
"""

from __future__ import annotations

import streamlit as st

from config.settings import RISK_COLORS

CSS = """
<style>
    .block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1400px;}
    h1, h2, h3 {font-family: "Microsoft YaHei", "PingFang SC", sans-serif;}
    div[data-testid="stMetric"] {
        background: var(--secondary-background-color);
        border: 1px solid rgba(148,163,184,.25);
        border-left: 4px solid #2563eb;
        border-radius: 10px;
        padding: 14px 16px;
        box-shadow: 0 1px 3px rgba(0,0,0,.25);
    }
    div[data-testid="stMetricLabel"] p {font-size: .82rem; color: var(--text-color); opacity: .72;}
    div[data-testid="stMetricValue"] {font-size: 1.5rem; font-weight: 650;}
    .risk-card {
        border-radius: 12px; padding: 18px 20px; color: #fff;
        display: flex; flex-direction: column; gap: 4px;
    }
    .risk-card .label {font-size: .8rem; opacity: .85;}
    .risk-card .value {font-size: 1.9rem; font-weight: 700; line-height: 1.1;}
    .risk-card .hint {font-size: .78rem; opacity: .9;}
    .insight {
        background: rgba(148,163,184,.10); border-left: 3px solid #94a3b8;
        padding: 10px 14px; border-radius: 6px; font-size: .9rem;
    }
    /* ---- 金融分析面板（对齐 Vue FinanceView 信息架构） ---- */
    .fin-hero {
        display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap;
        padding: 12px 14px; border: 1px solid rgba(148,163,184,.25);
        border-radius: 10px; background: var(--secondary-background-color);
        margin-bottom: 12px;
    }
    .fin-hero-name {font-size: 1.05rem; font-weight: 650;}
    .fin-hero-sub {font-size: .8rem; opacity: .72; margin-top: 3px;}
    .fin-chips {display: flex; gap: 6px; flex-wrap: wrap; align-items: center;}
    .fin-chip {
        padding: 3px 9px; border: 1px solid; border-radius: 999px;
        font-size: .76rem; white-space: nowrap;
    }
    .fin-kpi-grid {display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px;}
    .fin-kpi {
        padding: 9px 11px; border: 1px solid rgba(148,163,184,.22);
        border-radius: 9px; background: var(--secondary-background-color);
    }
    .fin-kpi.off {opacity: .5;}
    .fin-kpi-label {font-size: .72rem; opacity: .72;}
    .fin-kpi-value {font-size: 1.05rem; font-weight: 650; margin: 3px 0;}
    .fin-kpi-value .unit {font-size: .68rem; opacity: .65; margin-left: 3px; font-weight: 400;}
    .fin-kpi-foot {display: flex; justify-content: space-between; font-size: .7rem; opacity: .75;}
    .fin-model {
        border: 1px solid rgba(148,163,184,.22); border-radius: 9px;
        padding: 10px 12px; background: var(--secondary-background-color);
    }
    .fin-model-head {display: flex; justify-content: space-between; align-items: baseline;}
    .fin-model-title {font-weight: 650; font-size: .88rem;}
    .fin-model-score {font-size: 1.05rem; font-weight: 700;}
    .fin-model-sub {font-size: .74rem; opacity: .70; margin: 2px 0 5px;}
    .fin-model-note {font-size: .72rem; color: #d97706; margin-top: 5px;}
    .fin-model-missing {font-size: .72rem; color: #d97706; margin-top: 3px;}
    .fin-sig {list-style: none; padding: 0; margin: 6px 0 0;}
    .fin-sig li {display: flex; gap: 6px; font-size: .76rem; padding: 2px 0; align-items: baseline;}
    .fin-sig li.fail .name {color: #dc2626;}
    .fin-sig li.na {opacity: .55;}
    .fin-sig .icon {width: 14px; text-align: center;}
    .fin-sig .detail {margin-left: auto; text-align: right; opacity: .70;}
    .fin-anomaly {
        border: 1px solid rgba(148,163,184,.22); border-left: 3px solid #d97706;
        border-radius: 7px; padding: 9px 11px; margin-bottom: 8px;
        background: var(--secondary-background-color);
    }
    .fin-anomaly-head {display: flex; gap: 7px; align-items: center;}
    .fin-anomaly .lvl {color: #fff; font-size: .68rem; padding: 1px 7px; border-radius: 4px;}
    .fin-anomaly .title {font-weight: 650; font-size: .85rem;}
    .fin-anomaly .detail {font-size: .78rem; opacity: .78; margin-top: 4px; line-height: 1.55;}
    .fin-attr-row {display: flex; align-items: center; gap: 9px; margin-bottom: 5px; font-size: .8rem;}
    .fin-attr-label {flex: 0 0 118px; opacity: .72;}
    .fin-attr-bar {flex: 1; height: 8px; background: rgba(148,163,184,.22); border-radius: 4px; overflow: hidden;}
    .fin-attr-bar i {display: block; height: 100%;}
    .fin-attr-val {flex: 0 0 52px; text-align: right;}
    .fin-quality {border-top: 1px dashed rgba(148,163,184,.35); padding-top: 10px; font-size: .76rem;}
    .fin-quality .q-row {display: flex; gap: 9px; margin-bottom: 4px; opacity: .82;}
    .fin-quality .q-key {flex: 0 0 62px; font-weight: 600;}
</style>
"""


def setup_page(title: str, icon: str = "🏦") -> None:
    """统一页面配置 + 注入 CSS + 演示口令门禁。"""
    st.set_page_config(page_title=f"{title} | 财务风险预警平台", page_icon=icon, layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    _demo_gate()


def _demo_gate() -> None:
    """内网演示口令门禁（设计稿 §6.6）：未设 DEMO_PASSWORD 时不启用。

    Streamlit 仅作内部演示端，不做完整用户系统；正式多用户走 Vue SPA。
    """
    import os

    password = os.getenv("DEMO_PASSWORD", "").strip()
    if not password:
        return
    if st.session_state.get("demo_authed"):
        return
    with st.form("demo_gate"):
        st.markdown("### 🔒 演示环境访问口令")
        inp = st.text_input("口令", type="password")
        submitted = st.form_submit_button("进入")
    if submitted and inp == password:
        st.session_state.demo_authed = True
        st.rerun()
    elif submitted:
        st.error("口令错误，请重试")
    st.stop()


def risk_card_html(level: str, value: str, label: str = "风险等级", hint: str = "") -> str:
    """风险等级卡片 HTML。"""
    color = RISK_COLORS.get(level, "#64748b")
    return (
        f'<div class="risk-card" style="background:{color}">'
        f'<span class="label">{label}</span>'
        f'<span class="value">{value}</span>'
        f'<span class="hint">{hint}</span></div>'
    )


def insight(text: str) -> None:
    """灰色提示条，用于解释图表读法。"""
    st.markdown(f'<div class="insight">{text}</div>', unsafe_allow_html=True)


def footer() -> None:
    st.markdown("---")
    st.caption(
        "本平台为学术研究工具，输出结果不构成投资建议或信用评级意见。"
        " | 数据来源：CSMAR / 巨潮资讯网 / 国家统计局"
    )
