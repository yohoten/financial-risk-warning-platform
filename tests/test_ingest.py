"""数据实时接入测试（P3 验收）。

覆盖：机器推送 API Key 认证、幂等重放、质量闸门拒收、scope 越权、入库合并、
接入日志权限、数据源配置 CRUD、事件总线、以及"路径→权限点"规则表。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("RISK_AUTH_MODE", "full")

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from api.auth import rbac, revocation  # noqa: E402
from api.auth import service as auth_service  # noqa: E402
from api.auth.guards import _exempt, permission_for  # noqa: E402
from api.db import database as dbmod  # noqa: E402
from api.ingest import security  # noqa: E402
from api.rate_limit import login_limiter, refresh_limiter  # noqa: E402

PASSWORD = "Passw0rd!2026"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """独立 SQLite 库 + 强制登录形态的测试客户端。"""
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "ingest_test.db")
    monkeypatch.setenv("RISK_AUTH_MODE", "full")
    dbmod.init_db()
    revocation.clear_memory()
    login_limiter.reset()
    refresh_limiter.reset()

    from api.main import app

    with TestClient(app) as c:
        yield c


def _make_user(username: str, role: str) -> dict:
    return auth_service.create_user(
        username=username, password=PASSWORD, email=f"{username}@test.local",
        role=role, must_change_password=False,
    )


def _login(client: TestClient, username: str, password: str = PASSWORD):
    return client.post("/auth/login", json={"username": username, "password": password})


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _issue_key(client: TestClient, admin_token: str, scopes=None, name="test-key") -> str:
    resp = client.post("/ingest/keys", headers=_auth(admin_token), json={
        "name": name, "scopes": scopes or ["ingest:*"],
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["plaintext"]


# ---------------------------------------------------------------------------
# 机器推送：认证 / 幂等 / 质量闸门 / scope
# ---------------------------------------------------------------------------

def test_push_requires_api_key(client: TestClient) -> None:
    resp = client.post("/ingest/v1/finance", json={
        "batch_id": "batch12345", "items": [{"stock_code": "000001", "year": 2023}],
    })
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "invalid_api_key"


def test_push_with_valid_key(client: TestClient) -> None:
    _make_user("admin1", rbac.UserRole.ADMIN)
    token = _login(client, "admin1").json()["access_token"]
    key = _issue_key(client, token)

    resp = client.post("/ingest/v1/finance", headers={"X-API-Key": key}, json={
        "batch_id": "batch12345",
        "items": [{"stock_code": "000001", "year": 2023, "revenue": 1000.0}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] == 1
    assert body["status"] == "success"


def test_push_idempotent_replay(client: TestClient) -> None:
    _make_user("admin2", rbac.UserRole.ADMIN)
    token = _login(client, "admin2").json()["access_token"]
    key = _issue_key(client, token)

    payload = {
        "batch_id": "batch12345",
        "items": [{"stock_code": "000001", "year": 2023, "revenue": 1000.0}],
    }
    first = client.post("/ingest/v1/finance", headers={"X-API-Key": key}, json=payload).json()
    second = client.post("/ingest/v1/finance", headers={"X-API-Key": key}, json=payload).json()

    assert first["accepted"] == 1
    assert second["accepted"] == 0
    assert second["duplicated"] == 1
    # 暂存区仅一行
    rows = dbmod.query("SELECT COUNT(*) AS n FROM ingest_staging WHERE batch_id='batch12345'")
    assert rows[0]["n"] == 1


def test_push_quality_gate_rejects_bad_items(client: TestClient) -> None:
    _make_user("admin3", rbac.UserRole.ADMIN)
    token = _login(client, "admin3").json()["access_token"]
    key = _issue_key(client, token)

    resp = client.post("/ingest/v1/finance", headers={"X-API-Key": key}, json={
        "batch_id": "batch12345",
        "items": [
            {"stock_code": "000001", "year": 2023, "revenue": 1000.0},
            {"stock_code": "abc", "year": 2023},                      # 非法代码
            {"stock_code": "000002", "year": 2023, "debt_ratio": 500},  # 值域越界
        ],
    })
    body = resp.json()
    assert body["accepted"] == 1
    assert body["status"] == "partial"
    assert len(body["rejected"]) == 2


def test_push_scope_denied(client: TestClient) -> None:
    _make_user("admin4", rbac.UserRole.ADMIN)
    token = _login(client, "admin4").json()["access_token"]
    key = _issue_key(client, token, scopes=["ingest:news"])

    resp = client.post("/ingest/v1/finance", headers={"X-API-Key": key}, json={
        "batch_id": "batch12345", "items": [{"stock_code": "000001", "year": 2023}],
    })
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "scope_denied"


def test_push_revoked_key_rejected(client: TestClient) -> None:
    _make_user("admin5", rbac.UserRole.ADMIN)
    token = _login(client, "admin5").json()["access_token"]
    key = _issue_key(client, token)
    kid = client.get("/ingest/keys", headers=_auth(token)).json()["items"][0]["id"]
    client.delete(f"/ingest/keys/{kid}", headers=_auth(token))

    resp = client.post("/ingest/v1/finance", headers={"X-API-Key": key}, json={
        "batch_id": "batch12345", "items": [{"stock_code": "000001", "year": 2023}],
    })
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 入库合并
# ---------------------------------------------------------------------------

def test_consume_staging_merges_finance(client: TestClient) -> None:
    _make_user("admin6", rbac.UserRole.ADMIN)
    token = _login(client, "admin6").json()["access_token"]
    key = _issue_key(client, token)

    client.post("/ingest/v1/finance", headers={"X-API-Key": key}, json={
        "batch_id": "batch12345",
        "items": [{"stock_code": "000001", "year": 2023, "revenue": 1000.0,
                   "net_profit": 120.0, "total_assets": 5000.0, "total_liabilities": 2500.0}],
    })
    consumed = client.post("/ingest/staging/consume", headers=_auth(token), json={}).json()
    assert consumed["inserted"] == 1

    rows = dbmod.query("SELECT * FROM finance WHERE stock_code='000001' AND year='2023'")
    assert len(rows) == 1
    assert rows[0]["revenue"] == 1000.0


# ---------------------------------------------------------------------------
# 权限与规则表
# ---------------------------------------------------------------------------

def test_api_key_management_requires_admin(client: TestClient) -> None:
    _make_user("analyst1", rbac.UserRole.ANALYST)
    token = _login(client, "analyst1").json()["access_token"]
    assert client.get("/ingest/keys", headers=_auth(token)).status_code == 403
    assert client.post("/ingest/keys", headers=_auth(token),
                       json={"name": "x", "scopes": ["ingest:*"]}).status_code == 403


def test_ingest_logs_require_data_refresh(client: TestClient) -> None:
    _make_user("viewer1", rbac.UserRole.VIEWER)
    token = _login(client, "viewer1").json()["access_token"]
    assert client.get("/ingest/logs", headers=_auth(token)).status_code == 403


def test_ingest_permission_rules() -> None:
    assert permission_for("POST", "/ingest/keys") == rbac.P_PUSH_INGEST
    assert permission_for("GET", "/ingest/keys") == rbac.P_PUSH_INGEST
    assert permission_for("GET", "/ingest/logs") == rbac.P_REFRESH_DATA
    assert permission_for("POST", "/ingest/staging/consume") == rbac.P_REFRESH_DATA
    # 机器推送通道从 JWT 闸门豁免
    assert _exempt("/ingest/v1/finance") is True
    assert permission_for("POST", "/datasources/config") == rbac.P_MANAGE_DATASOURCE


# ---------------------------------------------------------------------------
# 数据源配置
# ---------------------------------------------------------------------------

def test_datasource_config_crud(client: TestClient) -> None:
    _make_user("admin7", rbac.UserRole.ADMIN)
    admin_token = _login(client, "admin7").json()["access_token"]

    created = client.post("/datasources/config", headers=_auth(admin_token), json={
        "dimension": "finance", "source_name": "akshare_eastmoney",
        "label": "东方财富财务摘要", "merge_mode": "merge",
    })
    assert created.status_code == 200

    listed = client.get("/datasources/config", headers=_auth(admin_token)).json()
    assert listed["total"] >= 1

    # analyst 只读（读走 enterprise:view），写被拒
    _make_user("analyst2", rbac.UserRole.ANALYST)
    analyst_token = _login(client, "analyst2").json()["access_token"]
    assert client.get("/datasources/config", headers=_auth(analyst_token)).status_code == 200
    assert client.post("/datasources/config", headers=_auth(analyst_token), json={
        "dimension": "news", "source_name": "x",
    }).status_code == 403


# ---------------------------------------------------------------------------
# 事件总线
# ---------------------------------------------------------------------------

def test_event_bus_recent_buffer() -> None:
    from api.ingest.events import bus

    before = len(bus._recent)
    bus.publish("test.event", {"x": 1})
    assert len(bus._recent) == before + 1
    assert bus._recent[-1]["type"] == "test.event"
