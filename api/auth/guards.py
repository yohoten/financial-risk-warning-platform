"""路由级权限闸门（集中式规则表）。

为什么不在每个路由上挂 ``Depends(require_permission(...))``：
现有 app 有 30+ 个扁平路由 + 10 个子路由，逐个挂载既啰嗦又容易漏（漏一个就是
"以为有鉴权、其实裸奔"）。这里用一张显式的「路径 → 权限点」规则表统一拦截，
规则表本身就是可评审的权限清单；需要单点覆盖时仍可在路由上叠加依赖。

匹配顺序即优先级：先匹配到的规则生效（写操作规则排在读规则之前）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import HTTPException, Request, status

from api.auth import rbac
from api.auth.deps import resolve_user_from_token
from api.auth.jwt_utils import bearer_token
from config import settings

# 闸门自身放行的路径（认证域与健康检查、只读分享）
EXEMPT_EXACT: frozenset[str] = frozenset({
    "/", "/health", "/health/ready", "/auth/login", "/auth/refresh", "/auth/status",
    "/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect",
})
EXEMPT_PREFIXES: tuple[str, ...] = ("/assets", "/share", "/favicon", "/ingest/v1")

_WRITE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class Rule:
    """一条权限规则：方法集合（None=任意）+ 路径前缀 + 可选后缀 + 所需权限点。"""

    permission: str
    prefix: str
    methods: frozenset[str] | None = None
    suffix: str | None = None

    def matches(self, method: str, path: str) -> bool:
        if self.methods is not None and method not in self.methods:
            return False
        if not path.startswith(self.prefix):
            return False
        if self.suffix is not None and not path.endswith(self.suffix):
            return False
        return True


# ---------------------------------------------------------------------------
# 权限规则表（与设计稿 §3.1 权限矩阵一一对应）
# ---------------------------------------------------------------------------
RULES: tuple[Rule, ...] = (
    # 用户与角色
    Rule(rbac.P_MANAGE_USER, "/users"),
    # 审计
    Rule(rbac.P_VIEW_AUDIT, "/audit"),
    # 系统配置类（技能/插件/MCP/设置面板）
    Rule(rbac.P_CONFIG_SYSTEM, "/settings"),
    Rule(rbac.P_CONFIG_SYSTEM, "/skills"),
    Rule(rbac.P_CONFIG_SYSTEM, "/plugins"),
    Rule(rbac.P_CONFIG_SYSTEM, "/mcp"),
    # 预警：写操作需处置权，读需查看权
    Rule(rbac.P_HANDLE_ALERT, "/alerts", methods=_WRITE),
    Rule(rbac.P_VIEW_ALERT, "/alerts"),
    # 报告导出（财务报告/预警报告）
    Rule(rbac.P_EXPORT_REPORT, "/finance", suffix="/report"),
    Rule(rbac.P_EXPORT_REPORT, "/alerts", suffix="/report"),
    # 打分与解释：单企业体检所需的是"只读计算"，与查看诊断同权限；
    # what-if 反向模拟（写语义）才需要 predict:run。
    Rule(rbac.P_RUN_PREDICT, "/predict", suffix="/frame"),
    Rule(rbac.P_VIEW_ENTERPRISE, "/predict"),
    Rule(rbac.P_VIEW_ENTERPRISE, "/explain"),
    Rule(rbac.P_VIEW_EXPLAIN, "/monitor"),
    # 数据刷新与数据源
    Rule(rbac.P_REFRESH_DATA, "/datasources/pull", methods=_WRITE),
    Rule(rbac.P_MANAGE_DATASOURCE, "/datasources", methods=_WRITE),
    Rule(rbac.P_REFRESH_DATA, "/enterprise/"),
    Rule(rbac.P_VIEW_ENTERPRISE, "/datasources"),
    # 数据接入中心：API Key 管理（admin）、接入日志/暂存（analyst）
    Rule(rbac.P_PUSH_INGEST, "/ingest/keys"),
    Rule(rbac.P_REFRESH_DATA, "/ingest/logs"),
    Rule(rbac.P_REFRESH_DATA, "/ingest/staging"),
    # 机器推送 /ingest/v1/* 走 X-API-Key 通道（见 EXEMPT_PREFIXES，不参与 JWT 鉴权）
    # 企业档案
    Rule(rbac.P_MANAGE_ENTERPRISE, "/enterprises", methods=_WRITE),
    Rule(rbac.P_VIEW_ENTERPRISE, "/enterprises"),
    Rule(rbac.P_MANAGE_ENTERPRISE, "/tables", methods=_WRITE),
    Rule(rbac.P_VIEW_ENTERPRISE, "/tables"),
    # 财务与规则评分
    Rule(rbac.P_VIEW_ENTERPRISE, "/finance"),
    Rule(rbac.P_VIEW_ENTERPRISE, "/risk"),
    Rule(rbac.P_VIEW_ENTERPRISE, "/features"),
    # 模型元信息 / 看板 / 对话
    Rule(rbac.P_VIEW_DASHBOARD, "/model"),
    Rule(rbac.P_VIEW_DASHBOARD, "/dashboard"),
    Rule(rbac.P_USE_CHAT, "/chat"),
    Rule(rbac.P_USE_CHAT, "/analyze"),
    Rule(rbac.P_USE_CHAT, "/attachments"),
    # 事件流（P3）
    Rule(rbac.P_VIEW_ALERT, "/events"),
)


def permission_for(method: str, path: str) -> str | None:
    """返回该请求所需权限点；None 表示只需登录（或不匹配任何规则）。"""
    method = (method or "GET").upper()
    for rule in RULES:
        if rule.matches(method, path):
            return rule.permission
    return None


def _exempt(path: str) -> bool:
    normalized = (path or "/").rstrip("/") or "/"
    if normalized in EXEMPT_EXACT:
        return True
    return any(normalized.startswith(p) for p in EXEMPT_PREFIXES)


async def enforce_route_permission(request: Request) -> None:
    """FastAPI 全局依赖：集中校验"路径+方法 → 权限点"。"""
    if not settings.auth_enabled():
        return
    path = request.url.path
    if _exempt(path):
        return

    permission = permission_for(request.method, path)
    if permission is None:
        return

    token = bearer_token(request.headers.get("authorization"))
    user = resolve_user_from_token(token)  # 失败直接 401
    if permission not in set(user.get("permissions") or []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "permission_denied",
                "message": f"权限不足，缺少：{rbac.PERMISSION_LABELS.get(permission, permission)}",
                "required": permission,
            },
        )
    request.state.user = user


def describe_rules() -> list[dict]:
    """规则表可读视图（自检/文档/前端"权限说明"页复用）。"""
    return [
        {
            "permission": rule.permission,
            "permission_label": rbac.PERMISSION_LABELS.get(rule.permission, rule.permission),
            "prefix": rule.prefix,
            "methods": sorted(rule.methods) if rule.methods else ["ANY"],
            "suffix": rule.suffix,
        }
        for rule in RULES
    ]


PermissionGuard = Callable[..., None]