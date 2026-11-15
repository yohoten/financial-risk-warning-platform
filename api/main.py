"""FastAPI 入口：预警平台服务层。

启动：
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

契约见 docs/FastAPI服务层设计.md；薄封装在 api/services.py。
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import services
from api.schemas import CodesRequest, FrameRequest

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
