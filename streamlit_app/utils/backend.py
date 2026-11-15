"""前端数据访问统一入口：API 优先、本地回退。

页面统一通过本模块取数，屏蔽「远程 FastAPI」与「本地领域层」两种后端：
- ``RISK_API_URL`` 未设置 → 直接调用 ``models.predict`` / ``models.shap_analysis``；
- ``RISK_API_URL`` 已设置 → 走 ``api_client``，请求失败自动回退本地。

这样 Streamlit 既是「壳」，也能在答辩离线环境零依赖运行。
"""

from __future__ import annotations

import pandas as pd

from config import settings
from streamlit_app.utils import api_client

_local_cache = {}


def mode() -> str:
    return "api" if settings.RISK_API_URL else "local"


def _local_predictions() -> pd.DataFrame:
    from models.predict import load_predictions

    return load_predictions()


def _local_predict_codes(codes: list[str], year: int | None = None) -> pd.DataFrame:
    from models.predict import predict_codes

    return predict_codes(codes, year=year)


def _local_explain(code: str, year: int | None = None) -> dict:
    from models.shap_analysis import local_contribution

    result = local_contribution(code, year)
    result["contributions"] = result["contributions"].to_dict("records")
    result["all_contributions"] = result["all_contributions"].to_dict("records")
    return result


def _local_global_importance(top_n: int = 20) -> pd.DataFrame:
    from models.shap_analysis import global_importance

    return global_importance(top_n)


def get_predictions() -> pd.DataFrame:
    """全量评分结果（看板/批量共用）。"""
    return _local_predictions()


def predict_codes(codes: list[str], year: int | None = None) -> pd.DataFrame:
    """按代码打分；返回 DataFrame（与 models.predict.predict_codes 同构）。"""
    if mode() == "api":
        try:
            payload = api_client.predict_codes(codes, year)
            df = pd.DataFrame(payload.get("items", []))
            if not df.empty:
                return df
        except api_client.BackendUnavailable:
            pass  # 回退本地
    return _local_predict_codes(codes, year)


def local_contribution(code: str, year: int | None = None) -> dict:
    """单企业 SHAP 归因；返回 dict（contributions 已转 records）。"""
    if mode() == "api":
        try:
            return api_client.explain(code, year)
        except api_client.BackendUnavailable:
            pass
    return _local_explain(code, year)


def global_importance(top_n: int = 20) -> pd.DataFrame:
    if mode() == "api":
        try:
            payload = api_client.global_importance(top_n)
            df = pd.DataFrame(payload.get("items", []))
            if not df.empty:
                return df
        except api_client.BackendUnavailable:
            pass
    return _local_global_importance(top_n)


def health() -> dict:
    if mode() == "api":
        try:
            return api_client.health()
        except api_client.BackendUnavailable as exc:
            return {"status": "api_unreachable", "detail": str(exc)}
    return {"status": "local", "detail": "本地直连领域层（未配置 RISK_API_URL）"}
