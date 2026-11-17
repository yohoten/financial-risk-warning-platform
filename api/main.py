"""FastAPI 入口：预警平台服务层。

启动：
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

契约见 docs/FastAPI服务层设计.md；薄封装在 api/services.py。
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from api import services
from api.schemas import CodesRequest, FrameRequest
from api.services import alerts as alerts_service
from api.services import analyze as analyze_service
from api.services import datasources as datasources_service
from api.services import finance as finance_service
from api.services import rules as rules_service

app = FastAPI(
    title="财务风险智能预警平台 API",
    version="0.1.0",
    description="XGBoost + TreeSHAP 预警：评分、解释、监控、特征字典。",
)

_origins = [o.strip() for o in os.getenv("RISK_CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(services.ServiceUnavailable)
async def _unavailable(_: Request, exc: services.ServiceUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def _internal(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


def _or_404(result: dict) -> dict:
    """领域层以 {'error': ...} 表示"未找到"，统一转 404。"""
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/health")
def health() -> dict:
    return services.health()


@app.get("/model/meta")
def model_meta() -> dict:
    return services.model_meta()


@app.post("/predict/codes")
def predict_codes(req: CodesRequest) -> dict:
    if not req.codes:
        raise HTTPException(status_code=422, detail="codes 不能为空")
    return services.predict_codes(req.codes, req.year, req.threshold_override)


@app.post("/predict/frame")
def predict_frame(_: FrameRequest) -> dict:
    # what-if 打分：需先实现原始字段 → 特征 的单行计算（见平台功能设计 §4.2 模式 C）
    raise HTTPException(status_code=501, detail="what-if 预测尚未实现（P1）")


@app.get("/predict/top-risk")
def top_risk(year: int | None = Query(default=None),
             limit: int = Query(default=50, ge=1, le=1000),
             industry: str | None = Query(default=None)) -> dict:
    return services.top_risk(year, limit, industry)


# 静态路由必须先于 /explain/{code} 注册，否则 "global" 会被路径参数吞掉
@app.get("/explain/global")
def global_importance(top_n: int = Query(default=20, ge=5, le=100)) -> dict:
    return services.global_importance(top_n)


@app.get("/explain/dependence")
def dependence(feature: str = Query(...)) -> dict:
    return services.dependence(feature)


@app.get("/explain/interactions")
def interactions(top_n: int = Query(default=8, ge=3, le=20)) -> dict:
    return services.interactions(top_n)


@app.get("/explain/{code}")
def explain(code: str, year: int | None = Query(default=None)) -> dict:
    return services.explain(code, year)


@app.get("/monitor/report")
def monitor_report() -> dict:
    return services.monitor_report()


@app.get("/features")
def features() -> dict:
    return services.feature_dictionary()


# ---------------------------------------------------------------------------
# 财务分析（阶段 1 移植）
# ---------------------------------------------------------------------------

@app.get("/finance/overview")
def finance_overview(years: int = Query(default=5, ge=1, le=20)) -> dict:
    return finance_service.overview(years)


@app.get("/finance/{code}/analysis")
def finance_analysis(code: str, years: int = Query(default=5, ge=1, le=20),
                     peers: bool = Query(default=True)) -> dict:
    return _or_404(finance_service.analysis(code, years, peers))


@app.get("/finance/{code}/report")
def finance_report(code: str, years: int = Query(default=5, ge=1, le=20)) -> Response:
    return Response(content=finance_service.report_markdown(code, years),
                    media_type="text/markdown; charset=utf-8")


# ---------------------------------------------------------------------------
# 规则六维评分（阶段 1 移植）
# ---------------------------------------------------------------------------

@app.get("/risk/rules/{code}")
def risk_rules(code: str) -> dict:
    return _or_404(rules_service.rules_verdict(code))


# ---------------------------------------------------------------------------
# 预警闭环（阶段 1 移植）
# ---------------------------------------------------------------------------

@app.get("/alerts")
def alerts(status: str | None = Query(default=None),
           level: str | None = Query(default=None),
           stock_code: str | None = Query(default=None),
           limit: int = Query(default=200, ge=1, le=1000)) -> dict:
    return alerts_service.list_alerts(status, level, stock_code, limit)


@app.get("/alerts/summary")
def alerts_summary() -> dict:
    return alerts_service.summary()


@app.post("/alerts/generate")
def alerts_generate(payload: dict | None = None) -> dict:
    stock_code = (payload or {}).get("stock_code")
    if stock_code:
        return _or_404(alerts_service.generate_for_enterprise(str(stock_code)))
    return alerts_service.generate_all()


@app.post("/alerts/{alert_id}/handle")
def alerts_handle(alert_id: int, payload: dict) -> dict:
    return alerts_service.handle_alert(
        alert_id,
        str((payload or {}).get("action", "")),
        str((payload or {}).get("handler", "")),
        str((payload or {}).get("note", "")),
    )


@app.get("/alerts/{alert_id}/report")
def alerts_report(alert_id: int) -> Response:
    return Response(content=alerts_service.report_markdown(alert_id),
                    media_type="text/markdown; charset=utf-8")


# ---------------------------------------------------------------------------
# 数据源接入（阶段 4 移植）
# ---------------------------------------------------------------------------

@app.get("/datasources")
def datasources() -> dict:
    return datasources_service.source_status()


@app.post("/enterprise/{code}/refresh")
def enterprise_refresh(code: str) -> dict:
    return datasources_service.refresh_enterprise(code)


# ---------------------------------------------------------------------------
# LLM 智能研判（阶段 4 移植）
# ---------------------------------------------------------------------------

@app.post("/analyze/{code}")
def analyze(code: str) -> dict:
    return _or_404(analyze_service.analyze_by_code(code))
