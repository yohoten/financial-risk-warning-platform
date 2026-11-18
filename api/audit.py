"""审计日志：写入、查询（移植 ZNCBZS core/security.log_operation 的语义）。

设计要点（设计稿 §3.4）：
- 所有非 GET 业务请求由中间件自动落库；
- 登录/登出/改密/角色变更等敏感动作由业务显式埋点；
- 只增不改不删（admin 亦无删除接口），供 auditor 与 admin 查证。
"""

from __future__ import annotations

import json

from config import settings


def write_audit(
    *,
    action: str,
    user_id: str = "",
    username: str = "",
    resource: str = "",
    method: str = "",
    path: str = "",
    ip: str = "",
    ua: str = "",
    status: int = 0,
    latency_ms: int = 0,
    detail: dict | None = None,
) -> None:
    """写一条审计日志；任何失败都不应影响业务主流程。"""
    if not settings.audit_enabled():
        return
    try:
        from api.db.database import execute

        execute(
            "INSERT INTO audit_log (user_id, username, action, resource, method, path, ip, ua,"
            " status, latency_ms, detail_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                user_id or "",
                username or "",
                action,
                resource or "",
                method or "",
                path or "",
                ip or "",
                (ua or "")[:300],
                int(status or 0),
                int(latency_ms or 0),
                json.dumps(detail or {}, ensure_ascii=False),
            ),
        )
    except Exception:  # noqa: BLE001 —— 审计失败不得阻断业务
        pass


def list_audit(
    *,
    page: int = 1,
    size: int = 50,
    action: str | None = None,
    username: str | None = None,
    ip: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    """分页查询审计日志（audit:view 权限）。"""
    from api.db.database import query

    where: list[str] = []
    params: list = []
    if action:
        where.append("action LIKE ?")
        params.append(f"%{action}%")
    if username:
        where.append("username LIKE ?")
        params.append(f"%{username}%")
    if ip:
        where.append("ip LIKE ?")
        params.append(f"%{ip}%")
    if since:
        where.append("created_at >= ?")
        params.append(since)
    if until:
        where.append("created_at <= ?")
        params.append(until)
    clause = f" WHERE {' AND '.join(where)}" if where else ""

    total_rows = query(f"SELECT COUNT(*) AS n FROM audit_log{clause}", tuple(params))
    total = int(total_rows[0]["n"]) if total_rows else 0

    size = max(1, min(int(size), 500))
    page = max(1, int(page))
    offset = (page - 1) * size
    items = query(
        f"SELECT * FROM audit_log{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        tuple(params) + (size, offset),
    )
    for row in items:
        raw = row.get("detail_json") or "{}"
        try:
            row["detail"] = json.loads(raw)
        except ValueError:
            row["detail"] = {}
        row.pop("detail_json", None)
    return {"total": total, "page": page, "size": size, "items": items}


def summary() -> dict:
    """审计概览：近 7 天按动作计数 + 失败登录次数。"""
    from api.db.database import query

    by_action = query(
        "SELECT action, COUNT(*) AS n FROM audit_log"
        " WHERE created_at >= datetime('now','localtime','-7 day')"
        " GROUP BY action ORDER BY n DESC LIMIT 20"
    )
    failed_login = query(
        "SELECT COUNT(*) AS n FROM audit_log"
        " WHERE action = 'login' AND status >= 400"
        " AND created_at >= datetime('now','localtime','-7 day')"
    )
    return {
        "by_action": by_action,
        "failed_login_7d": int(failed_login[0]["n"]) if failed_login else 0,
    }