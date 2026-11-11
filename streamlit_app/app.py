"""财务风险智能预警平台 · 主入口。

启动方式（在项目根目录执行）：
    streamlit run streamlit_app/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from config import settings
from config.feature_registry import FEATURE_GROUP_LABELS, FEATURES
from streamlit_app.utils import data as D
from streamlit_app.utils.styles import footer, insight, setup_page

setup_page("平台首页", "🏦")


def _status() -> dict:
    """系统就绪状态：数据、模型、解释缓存。"""
    from etl.io_utils import resolve

    return {
        "panel": bool(resolve(settings.FEATURE_MATRIX) or resolve(settings.FEATURE_PANEL)),
        "model": settings.MODEL_PATH.exists(),
        "shap": settings.SHAP_VALUES.exists(),
        "predictions": bool(resolve(settings.PREDICTION_PATH)),
        "evaluation": (settings.ARTIFACT_DIR / "evaluation_metrics.json").exists(),
    }


st.title("🏦 上市公司财务风险智能预警平台")
st.markdown(
    "基于 **XGBoost + SHAP** 的财务风险预警系统 —— 覆盖 70+ 维多源异构特征，"
    "在保证预测精度的同时提供可审计的模型解释，弥合学术研究与实务应用之间的落地鸿沟。"
)

status = _status()
ready = all([status["panel"], status["model"]])

if not ready:
    st.error("系统尚未初始化完成，请按下方步骤准备数据与模型。")
    st.markdown(D.PIPELINE_HINT)
    st.stop()

col1, col2, col3, col4 = st.columns(4)
metrics = D.load_metrics()
valid = metrics.get("XGBoost(tuned)") or metrics.get("XGBoost") or {}
col1.metric("样本规模", f"{len(D.load_panel()):,}", help="公司-年 观测值")
col2.metric("特征维度", f"{len(FEATURES)} 维", help="覆盖 9 大维度")
col3.metric("验证集 AUC", f"{valid.get('auc', float('nan')):.3f}", help="2023 年时间外验证")
col4.metric("验证集 KS", f"{valid.get('ks', float('nan')):.3f}", help="行业标准 ≥0.40")

st.markdown("---")
st.subheader("🧭 五大功能模块")

modules = [
    ("📊", "数据看板", "行业风险热力图、年度 ST 趋势、TOP20 高风险企业、宏观环境仪表盘", "pages/1_数据看板.py"),
    ("🏢", "企业诊断", "风险评级卡片、六维健康度雷达、SHAP 归因瀑布图、历史风险轨迹", "pages/2_企业诊断.py"),
    ("📋", "批量预警", "粘贴股票代码或上传 CSV，一键评分、阈值调节、导出预警清单", "pages/3_批量预警.py"),
    ("🔍", "模型解释", "全局特征重要性、特征依赖、交互效应、五模型对比、漂移监控", "pages/4_模型解释.py"),
    ("📄", "报告导出", "单企业 PDF 诊断报告、批量 Excel 预警清单、模型评估报告", "pages/5_报告导出.py"),
]
for row in [modules[:3], modules[3:]]:
    cols = st.columns(len(row))
    for col, (icon, name, desc, _) in zip(cols, row):
        with col:
            with st.container(border=True):
                st.markdown(f"#### {icon} {name}")
                st.caption(desc)

st.markdown("---")
left, right = st.columns([1.4, 1])

with left:
    st.subheader("🗂️ 特征体系")
    panel = D.load_panel()
    rows = []
    for group, label in FEATURE_GROUP_LABELS.items():
        keys = [f.key for f in FEATURES if f.group == group and f.key in panel.columns]
        rows.append({"维度": label, "特征数": len(keys), "示例指标": "、".join(f.cn for f in FEATURES if f.group == group)[:42]})
    st.dataframe(rows, use_container_width=True, hide_index=True)
    insight(
        "特征筛选采用四步法：IV 值（预测力）→ 相关性/VIF（去冗余）→ PSI（跨期稳定性）→ Boruta（重要性确认）。"
        "完整证据链见 `data/feature_store/feature_selection_report.csv`。"
    )

with right:
    st.subheader("⚙️ 系统状态")
    icons = {True: "🟢", False: "⚪"}
    checkpoints = [
        ("特征面板", status["panel"], "data/feature_store/panel_model_input.parquet"),
        ("模型权重", status["model"], "models/artifacts/xgboost_final.json"),
        ("SHAP 缓存", status["shap"], "cache/shap_values.pkl"),
        ("评分缓存", status["predictions"], "cache/predictions.parquet"),
        ("评估报告", status["evaluation"], "models/artifacts/evaluation_report.md"),
    ]
    for name, ok, path in checkpoints:
        st.markdown(f"{icons[ok]} **{name}** · `{path}`")

    if settings.MODEL_META.exists():
        meta = D.load_model_meta()
        th = meta.get("threshold") or {}
        st.caption(
            f"模型生成于 {meta.get('created_at', '-')}；训练窗口 {meta.get('train_years')}；"
            f"标签前瞻 {meta.get('label_horizon')} 年；决策阈值 {th.get('value', '-')}"
            f"（{th.get('selected_on', '-')} 冻结）"
        )

    st.subheader("🚀 快速命令")
    st.code(
        "python -m etl.run_pipeline\n"
        "python -m models.train --trials 30\n"
        "python -m models.evaluate\n"
        "python -m models.shap_analysis\n"
        "python -m models.monitor",
        language="bash",
    )

st.markdown("---")
st.subheader("📐 设计与方法论")
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("**标签定义**")
    st.caption("T 年被实施 ST/*ST 为正样本，特征取 T-2 年，规避前视偏差（Look-ahead Bias）。")
with c2:
    st.markdown("**验证策略**")
    st.caption("5 折 TimeSeriesSplit + 2023 年 OOT 验证 + 2024 年留出测试，随机切分被严格禁止。")
with c3:
    st.markdown("**可解释性**")
    st.caption("TreeSHAP 四维度：全局重要性、单样本归因、依赖效应、交互效应。")

footer()
