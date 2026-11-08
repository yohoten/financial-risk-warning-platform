"""📋 批量预警：粘贴代码或上传 CSV，一键评分并导出清单。"""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from config.settings import RISK_THRESHOLDS
from streamlit_app.components.layout import page_header
from streamlit_app.utils import charts, data as D
from streamlit_app.utils.report import batch_excel
from streamlit_app.utils.styles import footer, insight, setup_page

setup_page("批量预警", "📋")
page_header("批量预警", "支持股票代码批量输入或 CSV 上传，输出风险等级分布与预警清单", "📋")

scored = D.load_predictions()
years = sorted(scored["year"].unique(), reverse=True)

with st.sidebar:
    st.markdown("### ⚙️ 评分参数")
    year = st.selectbox("评分年度", years, index=0)
    high_thr = st.slider("高风险阈值", 0.30, 0.90, float(RISK_THRESHOLDS["high"]), 0.05,
                         help="ST 概率高于该值判定为高风险")
    med_thr = st.slider("中风险阈值", 0.05, float(high_thr) - 0.05, float(RISK_THRESHOLDS["medium"]), 0.05,
                        help="高于该值且低于高风险阈值判定为中风险")

col1, col2 = st.columns(2)
with col1:
    st.markdown("**方式一：粘贴股票代码**（逗号、空格或换行分隔）")
    raw = st.text_area("股票代码", height=130, placeholder="600000, 600002\n600004 600006", label_visibility="collapsed")
with col2:
    st.markdown("**方式二：上传 CSV**（需包含 `stock_code` 或 `股票代码` 列）")
    upload = st.file_uploader("上传 CSV", type=["csv"], label_visibility="collapsed")

codes: list[str] = []
if raw.strip():
    codes = [c.strip() for c in raw.replace("，", ",").replace("\n", ",").replace(" ", ",").split(",") if c.strip()]
if upload is not None:
    try:
        uploaded = pd.read_csv(upload)
        col = "stock_code" if "stock_code" in uploaded.columns else ("股票代码" if "股票代码" in uploaded.columns else None)
        if col is None:
            st.error("CSV 中未找到 `stock_code` 或 `股票代码` 列")
        else:
            codes += uploaded[col].astype(str).str.strip().str.zfill(6).tolist()
    except Exception as exc:
        st.error(f"CSV 解析失败：{exc}")

codes = list(dict.fromkeys(c for c in codes if c))
if not codes:
    st.info("请输入股票代码或上传 CSV 文件；也可点击下方按钮对全市场当期企业批量评分。")
    if st.button("对全市场当期企业评分", type="primary"):
        codes = scored[scored["year"] == year]["stock_code"].tolist()

if codes:
    subset = scored[(scored["stock_code"].isin(codes)) & (scored["year"] == year)].copy()
    missing = sorted(set(codes) - set(subset["stock_code"]))
    if subset.empty:
        st.error("输入的股票代码在当期数据中均未找到，请检查代码或切换年度。")
        st.stop()

    def level(p: float) -> str:
        return "高风险" if p >= high_thr else ("中风险" if p >= med_thr else "低风险")

    subset["risk_level"] = subset["st_prob"].map(level)
    subset = subset.sort_values("st_prob", ascending=False)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("评分企业数", f"{len(subset)}")
    c2.metric("高风险", f"{int((subset['risk_level'] == '高风险').sum())}")
    c3.metric("中风险", f"{int((subset['risk_level'] == '中风险').sum())}")
    c4.metric("平均 ST 概率", f"{subset['st_prob'].mean():.1%}")
    if missing:
        st.warning(f"以下代码未匹配到数据（已跳过）：{', '.join(missing[:20])}")

    left, right = st.columns([1, 1.6])
    with left:
        st.plotly_chart(charts.risk_distribution(subset), use_container_width=True)
    with right:
        display = subset[["stock_code", "company_name", "industry", "st_prob", "risk_level", "risk_percentile"]].copy()
        display["st_prob"] = (display["st_prob"] * 100).round(2)
        st.dataframe(
            display.rename(columns={"stock_code": "股票代码", "company_name": "企业简称", "industry": "行业",
                                    "st_prob": "ST概率(%)", "risk_level": "风险等级", "risk_percentile": "风险分位"}),
            use_container_width=True, hide_index=True, height=360,
        )
        insight("点击表头可排序；阈值调整会实时重算风险等级，不改变模型输出概率。")

    export = subset[["stock_code", "company_name", "industry", "year", "st_prob", "risk_level", "risk_percentile"]].copy()
    export.columns = ["股票代码", "企业简称", "行业", "年度", "ST概率", "风险等级", "风险分位"]
    export["ST概率"] = export["ST概率"].map(lambda v: round(v, 4))
    export["风险分位"] = export["风险分位"].map(lambda v: round(v, 4))

    st.markdown("---")
    colx, coly = st.columns(2)
    colx.download_button(
        "⬇️ 下载预警清单 (Excel)",
        data=batch_excel(export),
        file_name=f"risk_warning_{year}_{len(export)}家.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    coly.download_button(
        "⬇️ 下载 CSV",
        data=export.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"risk_warning_{year}.csv",
        mime="text/csv",
    )

footer()
