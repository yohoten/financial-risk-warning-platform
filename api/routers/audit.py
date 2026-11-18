"""审计日志接口（audit:view：admin / auditor）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.audit import list_audit, summary as audit_summary
from api.auth.deps import require_permission

router = APIRouter(tags=["审计"])


@router.get("/audit/logs", summary="审计日志分页查询")
def audit_logs(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=500),
    action: str | None = Query(default=None),
    username: str | None = Query(default=None),
    ip: str | None = Query(default=None),
    since: str | None = Query(default=None, description="起始时间 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS"),
    until: str | None = Query(default=None),
    _: dict = Depends(require_permission("audit:view")),
) -> dict:
    return list_audit(page=page, size=size, action=action, username=username, ip=ip,
                      since=since, until=until)


@router.get("/audit/summary", summary="审计概览（近 7 天动作分布）")
def audit_overview(_: dict = Depends(require_permission("audit:view"))) -> dict:
    return audit_summary()