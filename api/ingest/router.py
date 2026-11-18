"""数据接入路由：API Key 管理、机器推送、接入日志、数据源配置、事件流。

权限（与 api/auth/guards.py 规则表一致，双保险）：
- /ingest/keys*                → ingest:push（admin 签发/吊销机器推送凭证）
- /ingest/logs* /ingest/staging* → data:refresh（analyst 触发/查看）
- /ingest/v1/{dimension}       → X-API-Key 通道（匿名，不参与 JWT）
- /datasources/config* 写       → datasource:manage，读 → enterprise:view
- /events/stream               → alert:view
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from api.audit import write_audit
from api.auth import rbac
from api.auth.deps import get_current_user, require_permission
from api.ingest import security, service
from api.ingest.events import bus
from api.ingest.schemas import DIMENSIONS, ApiKeyCreate, DataSourceConfigIn, IngestPushRequest
from api.rate_limit import client_ip

router = APIRouter(tags=["数据接入"])


# ---------------------------------------------------------------------------
# API Key（admin，ingest:push）
# ---------------------------------------------------------------------------

@router.post("/ingest/keys", summary="签发 API Key（明文仅返回一次）")
def issue_api_key(payload: ApiKeyCreate, request: Request,
                  actor: dict = Depends(require_permission(rbac.P_PUSH_INGEST))) -> dict:
    result = security.issue_key(payload.name, payload.scopes,
                                created_by=actor.get("username", ""),
                                expires_at=payload.expires_at)
    write_audit(action="apikey.create", user_id=actor.get("id", ""),
                username=actor.get("username", ""), resource=f"apikey:{result['name']}",
                method="POST", path=str(request.url.path), ip=client_ip(request),
                status=200, detail={"scopes": payload.scopes, "id": result["id"]})
    return result


@router.get("/ingest/keys", summary="API Key 列表（脱敏）")
def list_api_keys(_: dict = Depends(require_permission(rbac.P_PUSH_INGEST))) -> dict:
    return security.list_keys()


@router.delete("/ingest/keys/{key_id}", summary="吊销 API Key")
def revoke_api_key(key_id: int, request: Request,
                   actor: dict = Depends(require_permission(rbac.P_PUSH_INGEST))) -> dict:
    security.revoke_key(key_id)
    write_audit(action="apikey.revoke", user_id=actor.get("id", ""),
                username=actor.get("username", ""), resource=f"apikey:{key_id}",
                method="DELETE", path=str(request.url.path), ip=client_ip(request), status=200)
    return {"ok": True, "id": key_id}


# ---------------------------------------------------------------------------
# 机器推送（X-API-Key 通道，匿名）
# ---------------------------------------------------------------------------

@router.post("/ingest/v1/{dimension}", summary="外部数据推送（X-API-Key）")
def ingest_push(dimension: str, payload: IngestPushRequest, request: Request) -> dict:
    if dimension not in DIMENSIONS:
        raise HTTPException(status_code=400, detail={
            "code": "unsupported_dimension",
            "message": f"不支持的维度 {dimension}，可选：{', '.join(DIMENSIONS)}",
        })
    key_plain = (request.headers.get("x-api-key", "").strip()
                 or security.bearer_key(request.headers.get("authorization", "")))
    key_row = security.verify_key(key_plain)
    if key_row is None:
        raise HTTPException(status_code=401, detail={
            "code": "invalid_api_key", "message": "API Key 无效、已吊销或已过期",
        })
    if not security.key_has_scope(key_row, dimension):
        raise HTTPException(status_code=403, detail={
            "code": "scope_denied",
            "message": f"该 API Key 未授权推送维度 {dimension}"
                       f"（scopes={sorted(key_row.get('scopes') or set())}）",
        })
    return service.push(dimension, payload.batch_id, payload.items,
                        trigger_by=f"key:{key_row.get('name')}")


# ---------------------------------------------------------------------------
# 接入日志与暂存（analyst，data:refresh）
# ---------------------------------------------------------------------------

@router.get("/ingest/logs", summary="接入日志分页")
def ingest_logs(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=500),
    dimension: str | None = Query(default=None),
    status: str | None = Query(default=None),
    channel: str | None = Query(default=None),
    _: dict = Depends(require_permission(rbac.P_REFRESH_DATA)),
) -> dict:
    return service.list_logs(page=page, size=size, dimension=dimension,
                             status=status, channel=channel)


@router.get("/ingest/staging", summary="推送暂存区查询")
def ingest_staging(
    dimension: str | None = Query(default=None),
    quality_pass: int | None = Query(default=None),
    consumed: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    _: dict = Depends(require_permission(rbac.P_REFRESH_DATA)),
) -> dict:
    return service.list_staging(dimension=dimension, quality_pass=quality_pass,
                                consumed=consumed, limit=limit)


@router.post("/ingest/staging/consume", summary="合并暂存数据入业务库并触发闭环（手动触发/演示）")
def ingest_consume(payload: dict | None = None,
                   _: dict = Depends(require_permission(rbac.P_REFRESH_DATA))) -> dict:
    from api.worker import pipeline

    dimension = (payload or {}).get("dimension")
    limit = int((payload or {}).get("limit", 500))
    result = service.consume_staging(dimension=dimension, limit=limit)
    codes = result.get("codes", [])
    if codes:
        result["closed"] = pipeline.close_loop(codes, source="push")
    return result


@router.post("/datasources/pull", summary="触发数据源拉取（pull 通道，data:refresh）")
def datasources_pull(payload: dict | None = None,
                     _: dict = Depends(require_permission(rbac.P_REFRESH_DATA))) -> dict:
    from api.datasources import registry
    from api.worker import pipeline

    body = payload or {}
    dimension = body.get("dimension")
    stock_code = body.get("stock_code")

    if stock_code:
        codes = [str(stock_code).strip().zfill(6)]
        return pipeline.pull_and_close(codes, dimensions=[dimension] if dimension else None,
                                       source="manual")

    if dimension:
        return pipeline.run_pull_dimension(dimension, task_name="manual_pull")

    codes = registry.tracked_codes()
    return pipeline.pull_and_close(codes, dimensions=None, source="manual")


# ---------------------------------------------------------------------------
# 数据源配置（读 enterprise:view，写 datasource:manage）
# ---------------------------------------------------------------------------

@router.get("/datasources/config", summary="数据源配置列表")
def datasource_config_list(_: dict = Depends(get_current_user)) -> dict:
    return service.list_config()


@router.post("/datasources/config", summary="新增数据源配置")
def datasource_config_create(payload: DataSourceConfigIn, request: Request,
                             actor: dict = Depends(require_permission(rbac.P_MANAGE_DATASOURCE))) -> dict:
    result = service.upsert_config(
        payload.dimension, payload.source_name, label=payload.label, enabled=payload.enabled,
        priority=payload.priority, merge_mode=payload.merge_mode,
        schedule_cron=payload.schedule_cron, config=payload.config_json,
        updated_by=actor.get("username", ""),
    )
    write_audit(action="datasource.config_create", user_id=actor.get("id", ""),
                username=actor.get("username", ""),
                resource=f"datasource:{payload.dimension}/{payload.source_name}",
                method="POST", path=str(request.url.path), ip=client_ip(request), status=200)
    return result


@router.patch("/datasources/config/{config_id}", summary="更新数据源配置")
def datasource_config_update(config_id: int, payload: DataSourceConfigIn, request: Request,
                             actor: dict = Depends(require_permission(rbac.P_MANAGE_DATASOURCE))) -> dict:
    result = service.upsert_config(
        payload.dimension, payload.source_name, label=payload.label, enabled=payload.enabled,
        priority=payload.priority, merge_mode=payload.merge_mode,
        schedule_cron=payload.schedule_cron, config=payload.config_json,
        updated_by=actor.get("username", ""),
    )
    write_audit(action="datasource.config_update", user_id=actor.get("id", ""),
                username=actor.get("username", ""), resource=f"datasource:{config_id}",
                method="PATCH", path=str(request.url.path), ip=client_ip(request), status=200)
    return result


@router.delete("/datasources/config/{config_id}", summary="删除数据源配置")
def datasource_config_delete(config_id: int, request: Request,
                             actor: dict = Depends(require_permission(rbac.P_MANAGE_DATASOURCE))) -> dict:
    result = service.delete_config(config_id)
    write_audit(action="datasource.config_delete", user_id=actor.get("id", ""),
                username=actor.get("username", ""), resource=f"datasource:{config_id}",
                method="DELETE", path=str(request.url.path), ip=client_ip(request), status=200)
    return result


# ---------------------------------------------------------------------------
# 事件流（SSE，alert:view）
# ---------------------------------------------------------------------------

@router.get("/events/stream", summary="实时事件流（SSE）")
async def events_stream(request: Request) -> StreamingResponse:
    async def gen():
        q = bus.subscribe()
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                payload = json.dumps(event["data"], ensure_ascii=False)
                yield f"event: {event['type']}\ndata: {payload}\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")
