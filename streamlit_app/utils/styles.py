"""全局样式与页面配置。"""

from __future__ import annotations

import streamlit as st

from config.settings import RISK_COLORS

CSS = """
<style>
    .block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1400px;}
    h1, h2, h3 {font-family: "Microsoft YaHei", "PingFang SC", sans-serif;}
    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e6e8eb;
        border-left: 4px solid #1f77b4;
        border-radius: 10px;
        padding: 14px 16px;
        box-shadow: 0 1px 3px rgba(16,24,40,.06);
    }
    div[data-testid="stMetricLabel"] p {font-size: .82rem; color: #667085;}
    .risk-card {
        border-radius: 12px; padding: 18px 20px; color: #fff;
        display: flex; flex-direction: column; gap: 4px;
    }
    .risk-card .label {font-size: .8rem; opacity: .85;}
    .risk-card .value {font-size: 1.9rem; font-weight: 700; line-height: 1.1;}
    .risk-card .hint {font-size: .78rem; opacity: .9;}
    .insight {
        background: #f8fafc; border-left: 3px solid #94a3b8;
        padding: 10px 14px; border-radius: 6px; font-size: .9rem; color: #334155;
    }
</style>
"""


def setup_page(title: str, icon: str = "🏦") -> None:
    """统一页面配置 + 注入 CSS。"""
    st.set_page_config(page_title=f"{title} | 财务风险预警平台", page_icon=icon, layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)


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
