"""📄 报告导出：单企业 PDF、批量 Excel、模型评估报告与数据字典。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from config import settings
from streamlit_app.components.layout import page_header
from streamlit_app.utils import charts, data as D
from streamlit_app.utils.report import batch_excel, evaluation_markdown, risk_report_pdf, save_report
from streamlit_app.utils.styles import footer, insight, setup_page

setup_page("报告导出", "📄")
page_header("报告导出", "一键生成单企业诊断报告与批量预警清单，支撑答辩材料与实务交付", "📄")

scored = D.load_predictions()
options = D.company_options()

tab1, tab2, tab3, tab4 = st.tabs(["🏢 单企业诊断报告", "📦 批量预警清单", "📊 模型评估报告", "📚 数据字典"])

with tab1:
    c1, c2 = st.columns([2, 1])
    labels = options["company_name"].astype(str) + "（" + options["stock_code"].astype(str) + "）"
    with c1:
        choice = st.selectbox("选择企业", labels.tolist(), key="pdf_company")
    with c2:
        years = sorted(scored[scored["stock_code"] == choice.split("（")[-1].rstrip("）")]["year"].unique(), reverse=True)
        year = st.selectbox("数据年度", years, key="pdf_year")

    stock_code = choice.split("（")[-1].rstrip("）")
    company = scored[(scored["stock_code"] == stock_code) & (scored["year"] == year)].iloc[0]
    peers = scored[(scored["year"] == year) & (scored["industry"] == company["industry"])]
    history = scored[scored["stock_code"] == stock_code].sort_values("year")
    scores = charts.dimension_scores(company, scored)

    profile = {
        "stock_code": stock_code,
        "company_name": company["company_name"],
        "industry": company["industry"],
        "year": int(year),
        "st_prob": float(company["st_prob"]),
        "risk_level": company["risk_level"],
        "risk_percentile": float(company["risk_percentile"]),
        "peer_count": len(peers),
        "peer_rank": int((peers["st_prob"] > company["st_prob"]).sum() + 1),
        "peer_avg_prob": float(peers["st_prob"].mean()),
    }

    try:
        from models.shap_analysis import local_contribution

        contrib = local_contribution(stock_code, int(year))["contributions"]
    except Exception as exc:
        contrib = pd.DataFrame(columns=["中文名", "取值", "SHAP值", "方向"])
        st.warning(f"SHAP 归因不可用（{exc}），报告将省略归因章节。")

    left, right = st.columns([1, 1])
    with left:
        st.markdown("**报告预览**")
        st.dataframe(
            pd.DataFrame(
                {
                    "项目": ["企业", "行业", "年度", "风险等级", "ST 概率", "同业排名"],
                    "内容": [str(v) for v in [
                        company["company_name"], company["industry"], year, company["risk_level"],
                        f"{company['st_prob']:.2%}", f"{profile['peer_rank']}/{profile['peer_count']}",
                    ]],
                }
            ),
            use_container_width=True, hide_index=True,
        )
        st.markdown("**六维健康度**")
        st.dataframe(scores, use_container_width=True, hide_index=True)
    with right:
        st.markdown("**归因 Top 5**")
        st.dataframe(contrib.head(5), use_container_width=True, hide_index=True)
        insight("PDF 报告包含：风险概览、六维健康度、SHAP 归因、历史轨迹、方法论与免责声明。")

    if st.button("📄 生成 PDF 报告", type="primary"):
        try:
            pdf = risk_report_pdf(profile, scores, contrib, history)
            path = save_report(pdf, f"{stock_code}_{year}_risk_report.pdf")
            st.success(f"已生成并归档至 {settings.rel(path)}")
            st.download_button("⬇️ 下载 PDF", data=pdf, file_name=path.name, mime="application/pdf")
        except Exception as exc:
            st.error(f"PDF 生成失败：{exc}")

with tab2:
    year_b = st.selectbox("导出年度", sorted(scored["year"].unique(), reverse=True), key="batch_year")
    thresholds = D.load_thresholds()
    threshold = st.slider("高风险阈值", 0.05, 0.95, float(thresholds["high"]), 0.01,
                          help=f"默认值来自模型元信息（{thresholds['selected_on']} 冻结）")
    subset = scored[scored["year"] == year_b].sort_values("st_prob", ascending=False).copy()
    subset["risk_level"] = subset["st_prob"].map(
        lambda p: "高风险" if p >= threshold else ("中风险" if p >= thresholds["medium"] else "低风险")
    )
    export = subset[["stock_code", "company_name", "industry", "year", "st_prob", "risk_level"]].copy()
    export.columns = ["股票代码", "企业简称", "行业", "年度", "ST概率", "风险等级"]

    c1, c2, c3 = st.columns(3)
    c1.metric("导出企业数", f"{len(export):,}")
    c2.metric("高风险", f"{int((export['风险等级'] == '高风险').sum())}")
    c3.metric("平均概率", f"{export['ST概率'].mean():.1%}")

    st.dataframe(export.head(50), use_container_width=True, hide_index=True, height=320)
    st.download_button(
        "⬇️ 下载 Excel（含汇总 Sheet）",
        data=batch_excel(export),
        file_name=f"risk_warning_batch_{year_b}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

with tab3:
    markdown = evaluation_markdown()
    st.markdown(markdown)
    st.download_button("⬇️ 下载评估报告 (Markdown)", data=markdown.encode("utf-8"),
                       file_name="evaluation_report.md", mime="text/markdown")

    metrics = D.load_metrics()
    if metrics:
        st.download_button("⬇️ 下载全量指标 (JSON)",
                           data=json.dumps(metrics, ensure_ascii=False, indent=2).encode("utf-8"),
                           file_name="model_metrics.json", mime="application/json")

with tab4:
    dictionary = D.feature_dict()
    st.caption(f"共 {len(dictionary)} 维特征，字段口径与 `config/feature_registry.py` 保持同源。")
    st.dataframe(dictionary, use_container_width=True, hide_index=True, height=420)
    st.download_button(
        "⬇️ 下载数据字典 (CSV)",
        data=dictionary.to_csv(index=False).encode("utf-8-sig"),
        file_name="feature_dictionary.csv",
        mime="text/csv",
    )

footer()
