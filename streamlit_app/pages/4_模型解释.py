"""🔍 模型解释：全局重要性、依赖效应、交互效应、模型对比与漂移监控。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from config import settings
from config.feature_registry import FEATURE_GROUP_LABELS, FEATURE_MAP
from streamlit_app.components.layout import page_header
from streamlit_app.utils import charts, data as D
from streamlit_app.utils.styles import footer, insight, setup_page

setup_page("模型解释", "🔍")
page_header("模型解释", "从全局到局部理解模型：为什么整体这样判断，为什么这家企业是高风险", "🔍")

if not settings.SHAP_VALUES.exists():
    st.warning("尚未生成 SHAP 缓存，请先运行 `python -m models.shap_analysis`。")
    st.stop()

from models.shap_analysis import (  # noqa: E402
    dependence,
    global_importance,
    interaction_pairs,
    load_cache,
)

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["🌍 全局重要性", "📈 依赖效应", "🔗 交互效应", "⚖️ 模型对比", "🩺 漂移监控"]
)

with tab1:
    top_n = st.slider("展示特征数", 10, 40, 20, step=5)
    imp = global_importance(top_n)
    st.plotly_chart(charts.importance_bar(imp, top_n), use_container_width=True)

    c1, c2 = st.columns([1.2, 1])
    with c1:
        st.dataframe(
            imp[["中文名", "feature", "维度", "方向", "importance"]].rename(
                columns={"feature": "字段名", "维度": "所属维度", "方向": "指标方向", "importance": "mean|SHAP|"}),
            use_container_width=True, hide_index=True, height=320,
        )
    with c2:
        group_imp = imp.copy()
        group_imp["维度"] = group_imp["维度"].map(lambda g: FEATURE_GROUP_LABELS.get(g, g))
        agg = group_imp.groupby("维度")["importance"].sum().sort_values()
        import plotly.graph_objects as go

        fig = go.Figure(go.Bar(x=agg.values, y=agg.index, orientation="h", marker_color="#1f77b4"))
        fig.update_layout(template=charts.PLOT_TEMPLATE, height=320, margin=dict(l=10, r=10, t=30, b=10),
                          title="维度贡献合计")
        st.plotly_chart(fig, use_container_width=True)
        insight("维度贡献=该维度特征 mean|SHAP| 之和，可回答「哪类信息对预警最关键」。")

    cache = load_cache()
    st.caption(f"SHAP 样本数 {len(cache['values']):,}｜基准值（log-odds）{cache['base_value']:.4f}")

with tab2:
    cache = load_cache()
    names = [FEATURE_MAP[f].cn if f in FEATURE_MAP else f for f in cache["features"]]
    label = st.selectbox("选择特征", names, index=0)
    feature = cache["features"][names.index(label)]
    st.plotly_chart(charts.dependence_scatter(dependence(feature), label), use_container_width=True)
    insight("横轴为指标取值，纵轴为 SHAP 贡献。若曲线在某处陡变，说明该阈值附近风险敏感度剧增，"
            "可作为业务预警阈值的参考。")

with tab3:
    top_k = st.slider("参与分析的特征数", 5, 15, 8)
    pairs = interaction_pairs(top_k)
    st.plotly_chart(charts.interaction_heatmap(pairs, top_k), use_container_width=True)
    st.dataframe(
        pairs.assign(
            feature_a=pairs["feature_a"].map(lambda f: FEATURE_MAP[f].cn if f in FEATURE_MAP else f),
            feature_b=pairs["feature_b"].map(lambda f: FEATURE_MAP[f].cn if f in FEATURE_MAP else f),
        ).rename(columns={"feature_a": "特征A", "feature_b": "特征B"}),
        use_container_width=True, hide_index=True, height=300,
    )
    insight("交互强度 = |SHAP 相关系数| × 重要性几何均值，用于快速定位需要联合解读的特征组合。")

with tab4:
    metrics = D.load_metrics()
    st.plotly_chart(charts.metric_compare(metrics), use_container_width=True)

    rows = []
    for name, m in metrics.items():
        if not isinstance(m, dict) or "auc" not in m:
            continue
        rows.append({
            "模型": name, "AUC": m.get("auc"), "PR-AUC": m.get("pr_auc"),
            "KS": m.get("ks"), "F1": m.get("f1"), "ECE": m.get("ece"),
            "Brier": m.get("brier"), "CV-AUC均值": m.get("cv_auc_mean"),
            "CV-AUC标准差": m.get("cv_auc_std"),
        })
    if rows:
        df = pd.DataFrame(rows).sort_values("PR-AUC", ascending=False)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption("主指标为 PR-AUC、Recall@Top10% 与 ECE；AUC/KS/F1 仅作辅助。")

    eval_metrics = D.load_evaluation()
    if eval_metrics:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**验证集（{settings.VALID_YEAR}）**")
            st.json(eval_metrics.get(f"valid_{settings.VALID_YEAR}", {}))
        with c2:
            st.markdown(f"**测试集（{settings.TEST_YEAR}）**")
            st.json(eval_metrics.get(f"test_{settings.TEST_YEAR}") or {"提示": "测试集未生成"})

    calib_path = settings.ARTIFACT_DIR / "calibration_curve.csv"
    if calib_path.exists():
        st.plotly_chart(charts.calibration_scatter(pd.read_csv(calib_path)), use_container_width=True)
        insight("校准曲线贴近对角线说明概率可信，可直接用于「概率即风险」的业务沟通。")

with tab5:
    monitor = D.load_monitor()
    if not monitor:
        st.info("尚未生成监控报告，请先运行 `python -m models.monitor`。")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("监控特征数", monitor.get("n_features"))
        c2.metric("显著漂移", monitor.get("n_drifting"), delta_color="inverse")
        c3.metric("轻度漂移", monitor.get("n_warning"))

        perf = monitor.get("performance", {})
        st.markdown("**性能对比**")
        st.json({f"基准（{settings.VALID_YEAR} 验证）": perf.get("reference"),
                 f"当前（{settings.TEST_YEAR} 测试）": perf.get("current"),
                 "AUC 变化": perf.get("delta_auc")})

        psi_path = settings.ARTIFACT_DIR / "psi_detail.csv"
        if psi_path.exists():
            psi_df = pd.read_csv(psi_path)
            st.plotly_chart(charts.psi_bar(psi_df, 20), use_container_width=True)
            st.dataframe(psi_df.head(20), use_container_width=True, hide_index=True)

        st.markdown("**处置建议**")
        for action in monitor.get("actions", []):
            st.markdown(f"- {action}")

footer()
