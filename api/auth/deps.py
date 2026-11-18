"""认证依赖：从请求中解析并校验身份，供路由以 Depends 挂载。

与 ZNCBZS `PermissionChecker` / `require_role` 等价，差异：
- 角色以数据库为准（令牌里的 role 仅作快照），改角色立即生效；
- 校验 password_version（pv），改密/重置后旧令牌立刻失效；
- RISK_AUTH_MODE=local 时返回内置 local-admin（桌面端免登录）。
"""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.auth import jwt_utils, rbac, revocation, service
from config import settings

bearer_scheme = HTTPBearer(auto_error=False, description="登录后获取的 access_token")


def local_admin_user() -> dict:
    """local/off 模式的合成身份（拥有全部权限，不落库）。"""
    return {
        "id": "local-admin",
        "username": "local-admin",
        "email": "",
        "role": rbac.UserRole.ADMIN,
        "role_label": rbac.ROLE_LABELS[rbac.UserRole.ADMIN],
        "permissions": rbac.permissions_for(rbac.UserRole.ADMIN),
        "is_active": True,
        "must_change_password": False,
        "auth_mode": settings.auth_mode(),
        "token_jti": "",
    }


def _unauthorized(message: str, code: str = "unauthorized") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": code, "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(message: str, code: str = "forbidden") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": code, "message": message},
    )


def resolve_user_from_token(token: str | None) -> dict:
    """令牌 → 用户；失败抛 401。"""
    if not token:
        raise _unauthorized("未登录，请先登录", "missing_token")
    payload = jwt_utils.decode(token, expected_kind="access")
    if not payload:
        raise _unauthorized("登录状态无效或已过期", "invalid_token")
    jti = str(payload.get("jti") or "")
    if revocation.is_revoked(jti):
        raise _unauthorized("登录状态已注销，请重新登录", "token_revoked")

    user_id = str(payload.get("uid") or "")
    row = service.get_by_id(user_id)
    if not row:
        raise _unauthorized("账号不存在或已被删除", "user_missing")
    if not row.get("is_active", 1):
        raise _forbidden("账户已被禁用，请联系管理员", "user_disabled")
    if int(payload.get("pv") or 0) != int(row.get("password_version") or 1):
        raise _unauthorized("密码已变更，请重新登录", "password_changed")

    role = rbac.normalize_role(row.get("role"))
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row.get("email", "") or "",
        "role": role,
        "role_label": rbac.ROLE_LABELS.get(role, role),
        "permissions": rbac.permissions_for(role),
        "is_active": True,
        "must_change_password": bool(row.get("must_change_password", 0)),
        "auth_mode": settings.auth_mode(),
        "token_jti": jti,
    }


async def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict | None:
    """可选身份：未登录返回 None（local 模式返回 local-admin）。"""
    if not settings.auth_enabled():
        return local_admin_user()
    token = credentials.credentials if credentials else None
    if not token:
        return None
    try:
        user = resolve_user_from_token(token)
    except HTTPException:
        return None
    request.state.user = user
    return user


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """必须登录；local 模式直接放行 local-admin。"""
    if not settings.auth_enabled():
        user = local_admin_user()
        request.state.user = user
        return user
    token = credentials.credentials if credentials else None
    user = resolve_user_from_token(token)
    request.state.user = user
    return user


def require_permission(*permissions: str) -> Callable:
    """权限校验依赖工厂：``Depends(require_permission("user:manage"))``。

    多个权限点为"且"关系；管理员走通配（其权限集本就包含全部点位）。
    """
    required = tuple(p for p in permissions if p)

    async def _checker(user: dict = Depends(get_current_user)) -> dict:
        granted = set(user.get("permissions") or [])
        missing = [p for p in required if p not in granted]
        if missing:
            labels = [rbac.PERMISSION_LABELS.get(p, p) for p in missing]
            raise _forbidden(f"权限不足，缺少：{'、'.join(labels)}", "permission_denied")
        return user

    return _checker


def require_role(*roles: str) -> Callable:
    """角色白名单依赖工厂（保留 ZNCBZS 同名能力，业务优先用权限点）。"""
    allowed = {rbac.normalize_role(r) for r in roles if r}

    async def _checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in allowed:
            labels = "、".join(rbac.ROLE_LABELS.get(r, r) for r in allowed)
            raise _forbidden(f"需要以下角色之一：{labels}", "role_denied")
        return user

    return _checker


async def require_authenticated(user: dict = Depends(get_current_user)) -> dict:
    """仅要求登录（登录即可访问的接口使用）。"""
    return user


def has_permission(user: dict | None, permission: str) -> bool:
    if not user:
        return False
    return permission in set(user.get("permissions") or [])