"""前端数据访问层：统一缓存策略 + 缺失数据时的友好引导。

所有页面只通过本模块取数，确保：
1. 缓存粒度一致（同一份数据不会重复读盘）；
2. 数据/模型缺失时给出"下一步该运行什么命令"的明确提示，而不是白屏堆栈。
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from config import settings
from config.feature_registry import FEATURE_KEYS

PIPELINE_HINT = (
    "**首次运行请依次执行：**\n"
    "```bash\n"
    "python -m data.gen_demo_data      # 1. 生成演示数据（有 CSMAR 数据可跳过）\n"
    "python -m etl.run_pipeline        # 2. 清洗 + 特征工程 + 特征筛选\n"
    "python -m models.train            # 3. 训练模型\n"
    "python -m models.shap_analysis    # 4. 计算 SHAP 并缓存\n"
    "```"
)


class DataNotReady(Exception):
    """数据或模型尚未准备就绪。"""


def _normalize_keys(df: pd.DataFrame) -> pd.DataFrame:
    """股票代码统一为 6 位字符串（CSV 往返会把 000001 读成 1）。"""
    if "stock_code" not in df.columns:
        return df
    out = df.copy()
    out["stock_code"] = (
        out["stock_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    return out


@st.cache_data(ttl=1800, show_spinner="加载特征数据...")
def load_panel() -> pd.DataFrame:
    from etl.io_utils import read_table, resolve

    path = settings.FEATURE_MATRIX if resolve(settings.FEATURE_MATRIX) else settings.FEATURE_PANEL
    if resolve(path) is None:
        raise DataNotReady(f"未找到特征数据 `{settings.rel(path)}`。\n\n{PIPELINE_HINT}")
    return _normalize_keys(read_table(path))


@st.cache_data(ttl=600, show_spinner="计算风险评分...")
def load_predictions() -> pd.DataFrame:
    from models.predict import load_predictions as _load

    try:
        return _normalize_keys(_load())
    except FileNotFoundError as exc:
        raise DataNotReady(str(exc)) from exc


@st.cache_resource(show_spinner="加载模型与解释器...")
def load_model_meta() -> dict:
    if not settings.MODEL_META.exists():
        raise DataNotReady("未找到模型元信息，请先运行 `python -m models.train`。")
    return json.loads(settings.MODEL_META.read_text(encoding="utf-8"))


@st.cache_data(ttl=300)
def load_thresholds() -> dict:
    """风险分级阈值（来自 model_meta.json，与评估/监控同源）。"""
    from models.metrics import load_thresholds as _load

    return _load()


@st.cache_data(ttl=600)
def load_metrics() -> dict:
    if settings.METRICS_PATH.exists():
        return json.loads(settings.METRICS_PATH.read_text(encoding="utf-8"))
    return {}


@st.cache_data(ttl=600)
def load_evaluation() -> dict:
    path = settings.ARTIFACT_DIR / "evaluation_metrics.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@st.cache_data(ttl=600)
def load_monitor() -> dict:
    if settings.MONITOR_REPORT.exists():
        return json.loads(settings.MONITOR_REPORT.read_text(encoding="utf-8"))
    return {}


@st.cache_data(ttl=600)
def load_feature_report() -> pd.DataFrame:
    if settings.FEATURE_REPORT.exists():
        from etl.io_utils import read_table

        return read_table(settings.FEATURE_REPORT)
    return pd.DataFrame()


@st.cache_data(ttl=600)
def load_selection_meta() -> dict:
    if settings.FEATURE_LIST.exists():
        return json.loads(settings.FEATURE_LIST.read_text(encoding="utf-8"))
    return {}


def company_options() -> pd.DataFrame:
    """可选企业列表（含行业、最新评分），供下拉框使用。"""
    df = load_predictions()
    latest = df.sort_values("year").groupby("stock_code", as_index=False).tail(1)
    cols = [c for c in ["stock_code", "company_name", "industry", "year", "st_prob", "risk_level"] if c in latest.columns]
    return latest[cols].sort_values("st_prob", ascending=False).reset_index(drop=True)


def macro_table() -> pd.DataFrame:
    from etl.io_utils import read_table

    if settings.RAW_MACRO.exists():
        return read_table(settings.RAW_MACRO)
    return pd.DataFrame()


def feature_dict() -> pd.DataFrame:
    """数据字典（特征注册表）。"""
    from config.feature_registry import to_records

    return pd.DataFrame(to_records())


def guard(func):
    """装饰器：捕获 DataNotReady 并渲染引导信息。"""

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except DataNotReady as exc:
            st.error(str(exc))
            st.stop()
        except FileNotFoundError as exc:
            st.error(f"数据文件缺失：{exc}")
            st.stop()

    return wrapper
