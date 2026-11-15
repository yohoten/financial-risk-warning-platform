"""FastAPI 服务层的轻量客户端。

前端默认本地直连领域层；设置 ``RISK_API_URL`` 后，``backend.py`` 会通过本模块
访问 ``api/main.py``，失败时自动回退本地，避免单点故障影响答辩演示。
"""

from __future__ import annotations

import httpx

from config import settings


class BackendUnavailable(Exception):
    """API 不可达，用于触发本地回退。"""


def _client() -> httpx.Client:
    if not settings.RISK_API_URL:
        raise BackendUnavailable("未配置 RISK_API_URL")
    return httpx.Client(base_url=settings.RISK_API_URL, timeout=settings.RISK_API_TIMEOUT)


def _get(path: str, **params) -> dict:
    with _client() as c:
        resp = c.get(path, params=params)
        _raise_for(resp)
        return resp.json()


def _post(path: str, payload: dict) -> dict:
    with _client() as c:
        resp = c.post(path, json=payload)
        _raise_for(resp)
        return resp.json()


def _raise_for(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        raise BackendUnavailable(f"{resp.status_code}: {resp.text[:200]}")


def health() -> dict:
    return _get("/health")


def model_meta() -> dict:
    return _get("/model/meta")


def predict_codes(codes: list[str], year: int | None = None) -> dict:
    return _post("/predict/codes", {"codes": codes, "year": year})


def top_risk(year: int | None = None, limit: int = 50, industry: str | None = None) -> dict:
    return _get("/predict/top-risk", year=year, limit=limit, industry=industry)


def explain(code: str, year: int | None = None) -> dict:
    return _get(f"/explain/{code}", year=year)


def global_importance(top_n: int = 20) -> dict:
    return _get("/explain/global", top_n=top_n)


def monitor_report() -> dict:
    return _get("/monitor/report")
