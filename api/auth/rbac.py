"""RBAC：内置四角色 + 权限点矩阵。

角色按金融预警业务的"三权分立"划分（设计稿 §3.1）：
- admin    系统管理员：只管用户/角色/数据源/系统配置，不替代业务研判；
- analyst  分析师：模型、诊断、预警处置、报告、触发数据刷新；
- auditor  审计员：业务只读 + 可查审计日志与模型留痕，不可修改；
- viewer   查看者：只读看板与诊断，导出带水印。

权限点命名沿用 ``域:动作``，与设计稿矩阵一一对应，前端路由 meta 使用同一组字符串。
"""

from __future__ import annotations

from typing import Iterable


class UserRole:
    """用户角色常量（字符串存储，便于未来升级为 RBAC 关联表）。"""

    ADMIN = "admin"
    ANALYST = "analyst"
    AUDITOR = "auditor"
    VIEWER = "viewer"

    ALL = (ADMIN, ANALYST, AUDITOR, VIEWER)


ROLE_LABELS: dict[str, str] = {
    UserRole.ADMIN: "管理员",
    UserRole.ANALYST: "分析师",
    UserRole.AUDITOR: "审计员",
    UserRole.VIEWER: "查看者",
}

# ---------------------------------------------------------------------------
# 权限点
# ---------------------------------------------------------------------------
P_VIEW_DASHBOARD = "dashboard:view"
P_VIEW_ENTERPRISE = "enterprise:view"
P_MANAGE_ENTERPRISE = "enterprise:manage"
P_RUN_PREDICT = "predict:run"
P_VIEW_ALERT = "alert:view"
P_HANDLE_ALERT = "alert:handle"
P_VIEW_EXPLAIN = "explain:view"
P_EXPORT_REPORT = "report:export"
P_USE_CHAT = "chat:use"
P_REFRESH_DATA = "data:refresh"
P_MANAGE_DATASOURCE = "datasource:manage"
P_PUSH_INGEST = "ingest:push"
P_MANAGE_USER = "user:manage"
P_ASSIGN_ROLE = "role:assign"
P_VIEW_AUDIT = "audit:view"
P_CONFIG_SYSTEM = "system:config"

ALL_PERMISSIONS: tuple[str, ...] = (
    P_VIEW_DASHBOARD,
    P_VIEW_ENTERPRISE,
    P_MANAGE_ENTERPRISE,
    P_RUN_PREDICT,
    P_VIEW_ALERT,
    P_HANDLE_ALERT,
    P_VIEW_EXPLAIN,
    P_EXPORT_REPORT,
    P_USE_CHAT,
    P_REFRESH_DATA,
    P_MANAGE_DATASOURCE,
    P_PUSH_INGEST,
    P_MANAGE_USER,
    P_ASSIGN_ROLE,
    P_VIEW_AUDIT,
    P_CONFIG_SYSTEM,
)

_ANALYST_PERMISSIONS: tuple[str, ...] = (
    P_VIEW_DASHBOARD,
    P_VIEW_ENTERPRISE,
    P_MANAGE_ENTERPRISE,
    P_RUN_PREDICT,
    P_VIEW_ALERT,
    P_HANDLE_ALERT,
    P_VIEW_EXPLAIN,
    P_EXPORT_REPORT,
    P_USE_CHAT,
    P_REFRESH_DATA,
)

_AUDITOR_PERMISSIONS: tuple[str, ...] = (
    P_VIEW_DASHBOARD,
    P_VIEW_ENTERPRISE,
    P_VIEW_ALERT,
    P_VIEW_EXPLAIN,
    P_EXPORT_REPORT,
    P_VIEW_AUDIT,
)

_VIEWER_PERMISSIONS: tuple[str, ...] = (
    P_VIEW_DASHBOARD,
    P_VIEW_ENTERPRISE,
    P_VIEW_ALERT,
    P_EXPORT_REPORT,
)

PERMISSIONS: dict[str, list[str]] = {
    UserRole.ADMIN: list(ALL_PERMISSIONS),
    UserRole.ANALYST: list(_ANALYST_PERMISSIONS),
    UserRole.AUDITOR: list(_AUDITOR_PERMISSIONS),
    UserRole.VIEWER: list(_VIEWER_PERMISSIONS),
}

# 权限点中文名（前端"我的权限"与用户管理页展示用）
PERMISSION_LABELS: dict[str, str] = {
    P_VIEW_DASHBOARD: "查看数据看板",
    P_VIEW_ENTERPRISE: "查看企业诊断",
    P_MANAGE_ENTERPRISE: "维护企业/关注清单",
    P_RUN_PREDICT: "运行批量打分",
    P_VIEW_ALERT: "查看预警",
    P_HANDLE_ALERT: "处置预警",
    P_VIEW_EXPLAIN: "查看模型解释",
    P_EXPORT_REPORT: "导出报告",
    P_USE_CHAT: "使用智能工作台",
    P_REFRESH_DATA: "触发数据拉取",
    P_MANAGE_DATASOURCE: "配置数据源",
    P_PUSH_INGEST: "外部数据推送",
    P_MANAGE_USER: "用户管理",
    P_ASSIGN_ROLE: "角色分配",
    P_VIEW_AUDIT: "查看审计日志",
    P_CONFIG_SYSTEM: "系统配置",
}


def normalize_role(role: str | None) -> str:
    """非法/空角色一律降级为最小权限的 viewer（默认拒绝）。"""
    candidate = (role or "").strip().lower()
    return candidate if candidate in UserRole.ALL else UserRole.VIEWER


def permissions_for(role: str | None) -> list[str]:
    """角色 → 权限点列表。"""
    return list(PERMISSIONS.get(normalize_role(role), []))


def role_has(role: str | None, *permissions: str) -> bool:
    """角色是否具备全部给定权限（全部满足才为真）。"""
    granted = set(permissions_for(role))
    return all(p in granted for p in permissions)


def is_valid_role(role: str | None) -> bool:
    return (role or "").strip().lower() in UserRole.ALL


def describe_roles() -> list[dict]:
    """角色字典表（前端权限说明与用户管理下拉使用）。"""
    return [
        {
            "role": role,
            "label": ROLE_LABELS[role],
            "permissions": PERMISSIONS[role],
            "permission_labels": [PERMISSION_LABELS[p] for p in PERMISSIONS[role]],
        }
        for role in UserRole.ALL
    ]


def missing_permissions(role: str | None, required: Iterable[str]) -> list[str]:
    granted = set(permissions_for(role))
    return [p for p in required if p not in granted]