"""FastAPI 入口：预警平台服务层。

启动：
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

契约见 docs/FastAPI服务层设计.md；薄封装在 api/services.py。
"""

from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from api import services
from config import settings
# P1 认证与权限：集中式路由闸门 + 认证/用户/审计路由
from api.auth.guards import enforce_route_permission
from api.auth.deps import get_optional_user
from api.auth.router import router as auth_router
from api.middleware import (
    AccessLogMiddleware,
    AuthGateMiddleware,
    SecurityHeadersMiddleware,
    verify_auth_coverage,
)
from api.schemas import CodesRequest, FrameRequest
from api.services import alerts as alerts_service
from api.services import analyze as analyze_service
from api.services import datasources as datasources_service
from api.services import finance as finance_service
from api.services import rules as rules_service

# 平台扩展路由（对话 / 企业 / 技能 / 插件 / 设置 / MCP / 分享 / 驾驶舱）
from api.routers import chat as chat_router
from api.routers import dashboard as dashboard_router
from api.routers import enterprises as enterprises_router
from api.routers import mcp as mcp_router
from api.routers import plugins as plugins_router
from api.routers import settings as settings_router
from api.routers import share as share_router
from api.routers import skills as skills_router
from api.routers import tables as tables_router
from api.routers import attachments as attachments_router
from api.routers import audit as audit_router
from api.ingest.router import router as ingest_router

app = FastAPI(
    title="财务风险智能预警平台 API",
    version="0.1.0",
    description="XGBoost + TreeSHAP 预警：评分、解释、监控、特征字典。",
    dependencies=[Depends(enforce_route_permission)],
)

_origins = [o.strip() for o in os.getenv("RISK_CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# 中间件（Starlette：后注册者在外层）——外→内：安全头 → 访问日志 → 登录闸门
app.add_middleware(AuthGateMiddleware)
app.add_middleware(AccessLogMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


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


@app.get("/health/ready")
def health_ready() -> JSONResponse:
    """readiness 探针：DB 可写 + 模型产物就绪（供 nginx/编排健康检查）。"""
    from api.db import database as _db

    db_ok = False
    try:
        _db.query("SELECT 1")
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    ready = {
        "status": "ready" if db_ok else "not_ready",
        "db": db_ok,
        "model": settings.MODEL_PATH.exists(),
        "meta": settings.MODEL_META.exists(),
    }
    return JSONResponse(status_code=200 if db_ok else 503, content=ready)


def _watermark_footer(user: dict | None) -> str:
    """viewer 导出报告加水印（属主用户名 + 时间）；其余角色不加水印（设计稿 §3.1）。"""
    if not user or user.get("role") != "viewer":
        return ""
    from datetime import datetime

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (f"\n\n---\n\n> 🔒 水印：仅供 {user.get('username', 'viewer')} 内部查看"
            f" · 导出于 {stamp} · 请勿外传")


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
    try:
        return services.dependence(feature)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/explain/interactions")
def interactions(top_n: int = Query(default=8, ge=3, le=20)) -> dict:
    return services.interactions(top_n)


@app.get("/explain/{code}")
def explain(code: str, year: int | None = Query(default=None)) -> dict:
    try:
        return services.explain(code, year)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


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
def finance_report(code: str, years: int = Query(default=5, ge=1, le=20),
                   download: bool = Query(default=False),
                   user: dict | None = Depends(get_optional_user)) -> Response:
    """财务分析报告（Markdown）。

    ``download=1`` 时带 Content-Disposition，浏览器直接落盘为 .md 文件；
    默认以内联方式在浏览器中预览。viewer 角色自动加水印。
    """
    body = finance_service.report_markdown(code, years) + _watermark_footer(user)
    headers = {}
    if download:
        filename = f"finance-analysis-{code}-{years}y.md"
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(content=body, media_type="text/markdown; charset=utf-8", headers=headers)


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
def alerts_report(alert_id: int, download: bool = Query(default=False),
                  user: dict | None = Depends(get_optional_user)) -> Response:
    """预警报告（Markdown）；``download=1`` 时浏览器直接落盘。viewer 角色自动加水印。"""
    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="alert-{alert_id}.md"'
    body = alerts_service.report_markdown(alert_id) + _watermark_footer(user)
    return Response(content=body,
                    media_type="text/markdown; charset=utf-8", headers=headers)


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


# ---------------------------------------------------------------------------
# 平台扩展（对话 / 企业 / 技能 / 插件 / 设置 / MCP / 分享 / 驾驶舱）
# ---------------------------------------------------------------------------

app.include_router(auth_router)
app.include_router(audit_router.router)
app.include_router(enterprises_router.router)
app.include_router(dashboard_router.router)
app.include_router(chat_router.router)
app.include_router(skills_router.router)
app.include_router(plugins_router.router)
app.include_router(settings_router.router)
app.include_router(mcp_router.router)
app.include_router(share_router.router)
app.include_router(tables_router.router)
app.include_router(attachments_router.router)
app.include_router(ingest_router)


def _bootstrap_auth() -> None:
    """播种初始管理员 + 鉴权覆盖率自检（幂等；任何异常都不阻断启动）。"""
    try:
        from api.auth import service as auth_service
        from api.middleware import logger

        created = auth_service.ensure_admin()
        if created:
            if created.get("_demo_password"):
                logger.warning(
                    "已创建初始管理员 {}，演示口令为 {} —— 请首次登录后立即修改，"
                    "或设置环境变量 RISK_ADMIN_PASSWORD 覆盖。",
                    created.get("username"), created.get("_password"),
                )
            else:
                logger.info("已创建初始管理员 {}", created.get("username"))
        gaps = verify_auth_coverage(app)
        if gaps:
            logger.warning(
                "以下路由未落在鉴权前缀内（可能绕过登录闸门）：{}", ", ".join(sorted(set(gaps)))
            )
    except Exception as exc:  # noqa: BLE001
        try:
            from api.middleware import logger

            logger.warning("认证初始化失败（不影响只读功能）：{}", exc)
        except Exception:  # noqa: BLE001
            pass


def _init_platform() -> None:
    """建表 + 灌入内置技能/预设 + 应用 DB 设置覆盖（幂等，失败不阻断）。"""
    from api.db import init_db
    from api.db.seed import seed_builtin

    init_db()
    _bootstrap_auth()
    seed_builtin()
    try:
        from api.ingest import service as ingest_service
        ingest_service.seed_default_sources()
    except Exception:  # noqa: BLE001
        pass
    try:
        from api.services.settings_store import load_and_apply
        load_and_apply()
    except Exception:  # noqa: BLE001
        pass


_init_platform()


# ---------------------------------------------------------------------------
# SPA 静态托管：生产 / Electron 形态由后端直接提供 web/dist
# ---------------------------------------------------------------------------

def _mount_spa() -> None:
    """挂载 web/dist 并提供 SPA 回退；dist 不存在时静默跳过（纯 API 模式）。"""
    from pathlib import Path

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    default_dist = Path(__file__).resolve().parents[1] / "web" / "dist"
    dist = Path(os.getenv("RISK_WEB_DIST", str(default_dist)))
    if not (dist / "index.html").is_file():
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        target = (dist / full_path).resolve()
        if full_path and target.is_file() and str(target).startswith(str(dist.resolve())):
            return FileResponse(str(target))
        return FileResponse(str(dist / "index.html"))


_mount_spa()
