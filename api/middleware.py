"""HTTP 中间件：认证闸门 + 安全响应头 + 访问日志/审计（P1）。

移植自 ZNCBZS `backend/core/middleware.py`，按本项目"扁平路由、无 /api 前缀"的
现状做了适配：

- ``AuthGateMiddleware``：粗粒度闸门。凡是已知业务前缀的请求都必须带有效
  access_token；SPA 静态资源（html/assets）与登录类接口放行。细粒度权限由路由
  上的 ``require_permission(...)`` 负责。
- ``SecurityHeadersMiddleware``：nosniff / 禁止被 iframe 嵌套 / 不泄漏 Referer。
- ``AccessLogMiddleware``：记录耗时，并把所有写操作落审计（登录类接口自身已写，
  避免重复）。
"""

from __future__ import annotations

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.audit import write_audit
from api.auth import jwt_utils, revocation
from config import settings

try:  # 项目其余模块用 loguru；缺失时退化为标准库，避免硬依赖
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger("api.middleware")

# 匿名可访问的精确路径（登录页探测、健康检查、文档、分享只读）
PUBLIC_EXACT: frozenset[str] = frozenset({
    "/",
    "/health",
    "/health/ready",
    "/auth/login",
    "/auth/refresh",
    "/auth/status",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/docs/oauth2-redirect",
})

# 匿名可访问的前缀（前端静态资源、只读分享链接、机器推送 X-API-Key 通道）
PUBLIC_PREFIXES: tuple[str, ...] = ("/assets", "/share", "/ingest/v1")

# 需要登录的业务前缀（含 auth 域自身：/auth/me、/auth/logout… 需令牌）
PROTECTED_PREFIXES: tuple[str, ...] = (
    "/auth", "/users", "/audit",
    "/model", "/predict", "/explain", "/monitor", "/features",
    "/finance", "/risk", "/alerts", "/datasources", "/enterprise", "/enterprises",
    "/analyze", "/dashboard", "/chat", "/skills", "/plugins", "/settings",
    "/mcp", "/tables", "/attachments", "/events", "/ingest",
)

# 自身已写审计的路径（中间件不重复记录）
SELF_AUDITED_PATHS: frozenset[str] = frozenset({
    "/auth/login", "/auth/logout", "/auth/change-password",
})

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def needs_auth(path: str) -> bool:
    """该路径是否要求登录（供中间件与自检使用）。"""
    normalized = (path or "/").rstrip("/") or "/"
    if normalized in PUBLIC_EXACT:
        return False
    if any(normalized == p or normalized.startswith(p + "/") or normalized.startswith(p)
           for p in PUBLIC_PREFIXES):
        return False
    return any(normalized == p or normalized.startswith(p + "/") for p in PROTECTED_PREFIXES)


def _json_response(status_code: int, payload: bytes) -> list[dict]:
    """构造一对 ASGI 响应消息（Message 是 TypedDict，不能用它构造实例）。"""
    return [
        {"type": "http.response.start", "status": status_code, "headers": [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(payload)).encode()),
            (b"www-authenticate", b"Bearer"),
        ]},
        {"type": "http.response.body", "body": payload},
    ]


class AuthGateMiddleware:
    """粗粒度登录闸门（纯 ASGI，避免 BaseHTTPMiddleware 对流式响应的干扰）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        if not settings.auth_enabled():
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "/")
        method = scope.get("method", "GET").upper()
        if method == "OPTIONS" or not needs_auth(path):
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        token = jwt_utils.bearer_token(headers.get("authorization"))
        payload = jwt_utils.decode(token, expected_kind="access") if token else None
        reason = ""
        if not token:
            reason = "missing_token"
        elif not payload:
            reason = "invalid_token"
        elif revocation.is_revoked(str(payload.get("jti") or "")):
            reason = "token_revoked"
        if reason:
            body = b'{"detail":{"code":"' + reason.encode() + \
                   b'","message":"\\u672a\\u767b\\u5f55\\u6216\\u767b\\u5f55\\u5df2\\u8fc7\\u671f\\uff0c\\u8bf7\\u91cd\\u65b0\\u767b\\u5f55"}}'
            for message in _json_response(401, body):
                await send(message)
            return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    """安全响应头（不引入 CSP，避免误伤内联样式的现有页面）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {k.decode("latin-1").lower() for k, _ in headers}
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"SAMEORIGIN"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"permissions-policy", b"geolocation=(), microphone=(), camera=()"),
                ]
                for key, value in extra:
                    if key.decode("latin-1") not in existing:
                        headers.append((key, value))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class AccessLogMiddleware:
    """访问日志 + 写操作审计。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 500))
            await send(message)

        await self.app(scope, receive, send_wrapper)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        if path.startswith(("/assets", "/favicon")):
            return
        logger.debug(f"{method} {path} {status_code} {elapsed_ms}ms")

        if method not in _WRITE_METHODS or path in SELF_AUDITED_PATHS:
            return
        state = scope.get("state") or {}
        user = state.get("user") or {}
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        client = scope.get("client") or ("unknown", 0)
        write_audit(
            action=f"http.{method.lower()}",
            user_id=str(user.get("id") or ""),
            username=str(user.get("username") or ""),
            resource=path,
            method=method,
            path=path,
            ip=headers.get("x-forwarded-for", "").split(",")[0].strip() or str(client[0]),
            ua=headers.get("user-agent", ""),
            status=status_code,
            latency_ms=elapsed_ms,
        )


def verify_auth_coverage(app) -> list[str]:
    """自检：所有 API 路由应落在"公开"或"受保护前缀"内，返回遗漏路径列表。

    新增路由忘记登记前缀时，启动日志会告警——避免出现"以为有鉴权、实际裸奔"。
    """
    from fastapi.routing import APIRoute

    gaps: list[str] = []
    for route in getattr(app, "routes", []):
        if not isinstance(route, APIRoute):
            continue
        path = getattr(route, "path", "")
        if path.startswith(("/assets", "/favicon")):
            continue
        if not needs_auth(path) and path not in PUBLIC_EXACT and not any(
            path.startswith(p) for p in PUBLIC_PREFIXES
        ):
            gaps.append(path)
    return gaps