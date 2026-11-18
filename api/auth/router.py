"""认证与用户管理路由。

接口契约（设计稿 §3.2）：
    POST   /auth/login               账号密码登录（限频 10/min/IP）
    POST   /auth/refresh             refresh 换新对（旧 refresh 立即撤销）
    POST   /auth/logout              注销当前令牌
    GET    /auth/me                  当前用户 + 权限点
    GET    /auth/status              认证开关状态（登录页探测，匿名）
    GET    /auth/roles               角色与权限字典（登录即可）
    POST   /auth/change-password     自助改密（改密后全端令牌失效）
    GET    /users                    用户列表（user:manage）
    POST   /users                    新建用户（user:manage）
    PATCH  /users/{user_id}          改邮箱/角色/启停（user:manage + role:assign）
    POST   /users/{user_id}/reset-password   重置密码（user:manage）
    DELETE /users/{user_id}          停用用户（user:manage）
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.audit import write_audit
from api.auth import jwt_utils, rbac, revocation, service
from api.auth.deps import get_current_user, require_permission
from api.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserCreateRequest,
    UserUpdateRequest,
)
from api.rate_limit import client_ip, login_limiter, refresh_limiter
from config import settings

router = APIRouter(tags=["认证与权限"])


def _http_error(exc: service.AuthError) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    if exc.retry_after:
        headers = {**(headers or {}), "Retry-After": str(int(exc.retry_after))}
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
        headers=headers,
    )


def _issue_tokens(row: dict) -> dict:
    role = rbac.normalize_role(row.get("role"))
    pv = int(row.get("password_version") or 1)
    access, _, access_exp = jwt_utils.create_access_token(
        subject=row["username"], user_id=row["id"], role=role, password_version=pv,
    )
    refresh, _, _ = jwt_utils.create_refresh_token(
        subject=row["username"], user_id=row["id"], role=role, password_version=pv,
    )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": max(1, int(access_exp - time.time())),
        "user": service.public_user(row),
    }


# ---------------------------------------------------------------------------
# 登录 / 刷新 / 注销 / 当前用户
# ---------------------------------------------------------------------------

@router.get("/auth/status", summary="认证状态（登录页探测，匿名可访问）")
def auth_status() -> dict:
    from api.db.database import query

    try:
        rows = query("SELECT COUNT(*) AS n FROM user")
        user_count = int(rows[0]["n"]) if rows else 0
    except Exception:  # noqa: BLE001
        user_count = 0
    return {
        "auth_enabled": settings.auth_enabled(),
        "mode": settings.auth_mode(),
        "user_count": user_count,
        "needs_setup": user_count == 0,
        "password_min_length": settings.PASSWORD_MIN_LENGTH,
        "token_minutes": settings.ACCESS_TOKEN_MINUTES,
    }


@router.post("/auth/login", response_model=TokenResponse, summary="登录")
def login(payload: LoginRequest, request: Request) -> dict:
    ip = client_ip(request)
    allowed, retry_after = login_limiter.allow(ip)
    if not allowed:
        write_audit(action="login", username=payload.username, resource="/auth/login",
                    method="POST", path=str(request.url.path), ip=ip,
                    ua=request.headers.get("user-agent", ""), status=429,
                    detail={"reason": "rate_limited"})
        raise HTTPException(
            status_code=429,
            detail={"code": "too_many_requests", "message": f"尝试过于频繁，请 {retry_after} 秒后重试"},
            headers={"Retry-After": str(retry_after)},
        )

    try:
        row = service.authenticate(payload.username, payload.password)
    except service.AuthError as exc:
        write_audit(action="login", username=payload.username, resource="/auth/login",
                    method="POST", path=str(request.url.path), ip=ip,
                    ua=request.headers.get("user-agent", ""), status=exc.status_code,
                    detail={"code": exc.code})
        raise _http_error(exc) from exc

    data = _issue_tokens(row)
    request.state.user = {
        "id": row["id"], "username": row["username"], "role": row["role"],
    }
    write_audit(action="login", user_id=row["id"], username=row["username"],
                resource="/auth/login", method="POST", path=str(request.url.path),
                ip=ip, ua=request.headers.get("user-agent", ""), status=200,
                detail={"remember": bool(payload.remember)})
    return data


@router.post("/auth/refresh", response_model=TokenResponse, summary="刷新令牌")
def refresh(payload: RefreshRequest, request: Request) -> dict:
    ip = client_ip(request)
    allowed, retry_after = refresh_limiter.allow(ip)
    if not allowed:
        raise HTTPException(status_code=429, detail={
            "code": "too_many_requests", "message": f"刷新过于频繁，请 {retry_after} 秒后重试",
        }, headers={"Retry-After": str(retry_after)})

    decoded = jwt_utils.decode(payload.refresh_token, expected_kind="refresh")
    if not decoded:
        raise HTTPException(status_code=401, detail={
            "code": "invalid_refresh", "message": "刷新令牌无效或已过期，请重新登录",
        })
    jti = str(decoded.get("jti") or "")
    if revocation.is_revoked(jti):
        raise HTTPException(status_code=401, detail={
            "code": "refresh_revoked", "message": "刷新令牌已失效，请重新登录",
        })

    row = service.get_by_id(str(decoded.get("uid") or ""))
    if not row or not row.get("is_active", 1):
        raise HTTPException(status_code=401, detail={
            "code": "user_unavailable", "message": "账号不可用，请重新登录",
        })
    if int(decoded.get("pv") or 0) != int(row.get("password_version") or 1):
        raise HTTPException(status_code=401, detail={
            "code": "password_changed", "message": "密码已变更，请重新登录",
        })

    # 轮换：旧 refresh 立即作废，避免重放
    revocation.revoke(jti, user_id=row["id"], kind="refresh",
                      expires_at=int(decoded.get("exp") or 0))
    return _issue_tokens(row)


@router.post("/auth/logout", response_model=MessageResponse, summary="注销")
def logout(request: Request, payload: LogoutRequest | None = None,
           user: dict = Depends(get_current_user)) -> dict:
    jti = user.get("token_jti") or ""
    exp = 0
    if jti:
        from api.auth import jwt_utils as _j

        auth_header = request.headers.get("authorization", "")
        token = _j.bearer_token(auth_header)
        decoded = _j.decode(token, verify_exp=False) if token else None
        exp = int((decoded or {}).get("exp") or 0)
        revocation.revoke(jti, user_id=user.get("id", ""), kind="access", expires_at=exp)
    if payload and payload.refresh_token:
        decoded_refresh = jwt_utils.decode(payload.refresh_token, verify_exp=False)
        if decoded_refresh:
            revocation.revoke(str(decoded_refresh.get("jti") or ""),
                              user_id=user.get("id", ""), kind="refresh",
                              expires_at=int(decoded_refresh.get("exp") or 0))
    write_audit(action="logout", user_id=user.get("id", ""), username=user.get("username", ""),
                resource="/auth/logout", method="POST", path=str(request.url.path),
                ip=client_ip(request), ua=request.headers.get("user-agent", ""), status=200)
    return {"ok": True, "message": "已退出登录"}


@router.get("/auth/me", summary="当前用户")
def me(user: dict = Depends(get_current_user)) -> dict:
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "email": user.get("email", ""),
        "role": user.get("role"),
        "role_label": user.get("role_label"),
        "permissions": user.get("permissions", []),
        "must_change_password": user.get("must_change_password", False),
        "auth_mode": user.get("auth_mode", settings.auth_mode()),
        "permission_labels": rbac.PERMISSION_LABELS,
    }


@router.get("/auth/roles", summary="角色与权限字典")
def roles(_: dict = Depends(get_current_user)) -> dict:
    return {"roles": rbac.describe_roles(), "permissions": rbac.PERMISSION_LABELS}


@router.post("/auth/change-password", response_model=MessageResponse, summary="修改本人密码")
def change_password(payload: ChangePasswordRequest, request: Request,
                    user: dict = Depends(get_current_user)) -> dict:
    try:
        service.change_own_password(user["id"], payload.old_password, payload.new_password)
    except service.AuthError as exc:
        write_audit(action="password.change", user_id=user.get("id", ""),
                    username=user.get("username", ""), resource="/auth/change-password",
                    method="POST", path=str(request.url.path), ip=client_ip(request),
                    status=exc.status_code, detail={"code": exc.code})
        raise _http_error(exc) from exc
    write_audit(action="password.change", user_id=user.get("id", ""),
                username=user.get("username", ""), resource="/auth/change-password",
                method="POST", path=str(request.url.path), ip=client_ip(request), status=200)
    return {"ok": True, "message": "密码已更新，请重新登录"}


# ---------------------------------------------------------------------------
# 用户管理（admin）
# ---------------------------------------------------------------------------

@router.get("/users", summary="用户列表")
def users_list(
    keyword: str | None = Query(default=None),
    role: str | None = Query(default=None),
    _: dict = Depends(require_permission("user:manage")),
) -> dict:
    return service.list_users(keyword, role)


@router.post("/users", summary="新建用户")
def users_create(payload: UserCreateRequest, request: Request,
                 actor: dict = Depends(require_permission("user:manage"))) -> dict:
    if payload.role and payload.role != rbac.UserRole.VIEWER and "role:assign" not in actor.get("permissions", []):
        raise HTTPException(status_code=403, detail={
            "code": "permission_denied", "message": "缺少权限：角色分配",
        })
    try:
        created = service.create_user(
            username=payload.username, password=payload.password, email=payload.email,
            role=payload.role, note=payload.note,
        )
    except service.AuthError as exc:
        raise _http_error(exc) from exc
    write_audit(action="user.create", user_id=actor.get("id", ""),
                username=actor.get("username", ""), resource=f"user:{created['username']}",
                method="POST", path=str(request.url.path), ip=client_ip(request),
                status=200, detail={"role": created["role"], "username": created["username"]})
    return created


@router.patch("/users/{user_id}", summary="修改用户（邮箱/角色/启停）")
def users_update(user_id: str, payload: UserUpdateRequest, request: Request,
                 actor: dict = Depends(require_permission("user:manage"))) -> dict:
    if payload.role is not None and "role:assign" not in actor.get("permissions", []):
        raise HTTPException(status_code=403, detail={
            "code": "permission_denied", "message": "缺少权限：角色分配",
        })
    if user_id == actor.get("id") and payload.is_active is False:
        raise HTTPException(status_code=409, detail={
            "code": "self_disable", "message": "不能停用当前登录账号",
        })
    try:
        updated = service.update_user(
            user_id, email=payload.email, role=payload.role,
            is_active=payload.is_active, note=payload.note,
        )
    except service.AuthError as exc:
        raise _http_error(exc) from exc
    write_audit(action="user.update", user_id=actor.get("id", ""),
                username=actor.get("username", ""), resource=f"user:{updated['username']}",
                method="PATCH", path=str(request.url.path), ip=client_ip(request),
                status=200, detail=payload.model_dump(exclude_none=True))
    return updated


@router.post("/users/{user_id}/reset-password", summary="重置密码")
def users_reset_password(user_id: str, payload: ResetPasswordRequest, request: Request,
                         actor: dict = Depends(require_permission("user:manage"))) -> dict:
    try:
        result = service.reset_password(user_id, payload.new_password)
    except service.AuthError as exc:
        raise _http_error(exc) from exc
    write_audit(action="user.reset_password", user_id=actor.get("id", ""),
                username=actor.get("username", ""),
                resource=f"user:{result['user']['username']}", method="POST",
                path=str(request.url.path), ip=client_ip(request), status=200)
    return result


@router.delete("/users/{user_id}", summary="停用用户")
def users_delete(user_id: str, request: Request,
                 actor: dict = Depends(require_permission("user:manage"))) -> dict:
    if user_id == actor.get("id"):
        raise HTTPException(status_code=409, detail={
            "code": "self_disable", "message": "不能停用当前登录账号",
        })
    try:
        updated = service.deactivate_user(user_id)
    except service.AuthError as exc:
        raise _http_error(exc) from exc
    write_audit(action="user.deactivate", user_id=actor.get("id", ""),
                username=actor.get("username", ""), resource=f"user:{updated['username']}",
                method="DELETE", path=str(request.url.path), ip=client_ip(request), status=200)
    return updated