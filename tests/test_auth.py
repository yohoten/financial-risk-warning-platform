"""认证与权限测试（P1 验收）。

覆盖：未登录拦截、登录/刷新轮换、注销撤销、改密失效旧令牌、失败锁定、
角色越权 403、免登录形态（local）、以及"路径→权限点"规则表本身。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("RISK_AUTH_MODE", "full")

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from api.auth import rbac, revocation  # noqa: E402
from api.auth import service as auth_service  # noqa: E402
from api.auth.guards import permission_for  # noqa: E402
from api.db import database as dbmod  # noqa: E402
from api.rate_limit import login_limiter, refresh_limiter  # noqa: E402
from config import settings  # noqa: E402

PASSWORD = "Passw0rd!2026"
NEW_PASSWORD = "Str0ngPass!2027"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """独立 SQLite 库 + 强制登录形态的测试客户端。"""
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "auth_test.db")
    monkeypatch.setenv("RISK_AUTH_MODE", "full")
    dbmod.init_db()
    revocation.clear_memory()
    login_limiter.reset()
    refresh_limiter.reset()

    from api.main import app

    with TestClient(app) as c:
        yield c


def _make_user(username: str, role: str, password: str = PASSWORD) -> dict:
    return auth_service.create_user(
        username=username, password=password, email=f"{username}@test.local",
        role=role, must_change_password=False,
    )


def _login(client: TestClient, username: str, password: str = PASSWORD):
    return client.post("/auth/login", json={"username": username, "password": password})


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 闸门与登录
# ---------------------------------------------------------------------------

def test_protected_route_requires_login(client: TestClient) -> None:
    resp = client.get("/predict/top-risk")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] in {"missing_token", "invalid_token"}


def test_health_is_public(client: TestClient) -> None:
    # 健康检查不鉴权（供探针使用）；数据未就绪时允许 200/503
    assert client.get("/health").status_code in {200, 503}


def test_login_success_returns_tokens_and_permissions(client: TestClient) -> None:
    _make_user("viewer01", rbac.UserRole.VIEWER)
    resp = _login(client, "viewer01")
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["user"]["role"] == rbac.UserRole.VIEWER
    assert "alert:view" in body["user"]["permissions"]
    assert "predict:run" not in body["user"]["permissions"]

    me = client.get("/auth/me", headers=_auth(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["username"] == "viewer01"


def test_login_wrong_password_is_generic(client: TestClient) -> None:
    _make_user("viewer02", rbac.UserRole.VIEWER)
    resp = _login(client, "viewer02", "WrongPass!2026")
    assert resp.status_code == 401
    message = resp.json()["detail"]["message"]
    # 不能泄漏"用户是否存在"
    assert "用户名或密码错误" in message


def test_login_lockout_after_repeated_failures(client: TestClient) -> None:
    _make_user("viewer03", rbac.UserRole.VIEWER)
    for _ in range(settings.LOGIN_MAX_ATTEMPTS):
        _login(client, "viewer03", "WrongPass!2026")
    resp = _login(client, "viewer03", PASSWORD)
    assert resp.status_code == 423
    assert resp.json()["detail"]["code"] == "account_locked"


# ---------------------------------------------------------------------------
# 权限矩阵
# ---------------------------------------------------------------------------

def test_viewer_cannot_manage_users(client: TestClient) -> None:
    _make_user("viewer04", rbac.UserRole.VIEWER)
    token = _login(client, "viewer04").json()["access_token"]
    resp = client.get("/users", headers=_auth(token))
    assert resp.status_code == 403
    assert resp.json()["detail"]["required"] == "user:manage"


def test_admin_can_manage_users(client: TestClient) -> None:
    _make_user("admin01", rbac.UserRole.ADMIN)
    token = _login(client, "admin01").json()["access_token"]
    assert client.get("/users", headers=_auth(token)).status_code == 200

    created = client.post("/users", headers=_auth(token), json={
        "username": "analyst01", "password": PASSWORD, "role": rbac.UserRole.ANALYST,
    })
    assert created.status_code == 200
    assert created.json()["role"] == rbac.UserRole.ANALYST


def test_auditor_can_read_audit_but_not_handle_alerts(client: TestClient) -> None:
    _make_user("auditor01", rbac.UserRole.AUDITOR)
    token = _login(client, "auditor01").json()["access_token"]
    assert client.get("/audit/logs", headers=_auth(token)).status_code == 200
    denied = client.post("/alerts/1/handle", headers=_auth(token), json={"action": "close"})
    assert denied.status_code == 403


def test_last_admin_cannot_be_demoted(client: TestClient) -> None:
    admin = _make_user("admin02", rbac.UserRole.ADMIN)
    with pytest.raises(auth_service.AuthError) as exc:
        auth_service.update_user(admin["id"], role=rbac.UserRole.VIEWER)
    assert exc.value.code == "last_admin"


# ---------------------------------------------------------------------------
# 令牌生命周期
# ---------------------------------------------------------------------------

def test_refresh_rotation_rejects_replay(client: TestClient) -> None:
    _make_user("viewer05", rbac.UserRole.VIEWER)
    first = _login(client, "viewer05").json()

    rotated = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != first["refresh_token"]

    replay = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401
    assert replay.json()["detail"]["code"] == "refresh_revoked"


def test_logout_revokes_access_token(client: TestClient) -> None:
    _make_user("viewer06", rbac.UserRole.VIEWER)
    tokens = _login(client, "viewer06").json()
    headers = _auth(tokens["access_token"])

    # 回归：注销允许不带 refresh_token（前端可能只持有 access token）
    assert client.post("/auth/logout", headers=headers).status_code == 200
    after = client.get("/auth/me", headers=headers)
    assert after.status_code == 401
    assert after.json()["detail"]["code"] == "token_revoked"


def test_password_change_invalidates_old_tokens(client: TestClient) -> None:
    _make_user("viewer07", rbac.UserRole.VIEWER)
    tokens = _login(client, "viewer07").json()
    headers = _auth(tokens["access_token"])

    changed = client.post("/auth/change-password", headers=headers, json={
        "old_password": PASSWORD, "new_password": NEW_PASSWORD,
    })
    assert changed.status_code == 200

    stale = client.get("/auth/me", headers=headers)
    assert stale.status_code == 401
    assert stale.json()["detail"]["code"] == "password_changed"

    assert _login(client, "viewer07", NEW_PASSWORD).status_code == 200


def test_disabled_user_cannot_login(client: TestClient) -> None:
    user = _make_user("viewer08", rbac.UserRole.VIEWER)
    auth_service.deactivate_user(user["id"])
    resp = _login(client, "viewer08")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "user_disabled"


# ---------------------------------------------------------------------------
# 免登录形态与规则表
# ---------------------------------------------------------------------------

def test_local_mode_bypasses_login(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("RISK_AUTH_MODE", "local")
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == rbac.UserRole.ADMIN
    # 业务接口不再要求令牌（模型未就绪时会 5xx/503，但不是 401）
    assert client.get("/predict/top-risk").status_code != 401


def test_permission_rules_cover_sensitive_paths() -> None:
    assert permission_for("GET", "/users") == "user:manage"
    assert permission_for("GET", "/audit/logs") == "audit:view"
    assert permission_for("GET", "/alerts") == "alert:view"
    assert permission_for("POST", "/alerts/12/handle") == "alert:handle"
    assert permission_for("POST", "/predict/codes") == "enterprise:view"
    assert permission_for("POST", "/predict/frame") == "predict:run"
    assert permission_for("GET", "/finance/000004/report") == "report:export"
    assert permission_for("GET", "/finance/000004/analysis") == "enterprise:view"
    assert permission_for("POST", "/enterprise/000004/refresh") == "data:refresh"
    assert permission_for("GET", "/settings") == "system:config"
    assert permission_for("GET", "/health") is None


def test_password_strength_rules() -> None:
    with pytest.raises(auth_service.AuthError) as exc:
        auth_service.create_user(username="weak01", password="12345678")
    assert exc.value.code == "weak_password"