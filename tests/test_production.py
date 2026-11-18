"""P4 生产化验收测试。

覆盖：readiness 健康检查、viewer 报告水印、令牌撤销 Redis 回退（REDIS_URL 未设时
不引入外部依赖、走 SQLite+内存）。
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("RISK_AUTH_MODE", "full")

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from api.auth import revocation  # noqa: E402
from api.db import database as dbmod  # noqa: E402
from api.rate_limit import login_limiter, refresh_limiter  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "prod_test.db")
    monkeypatch.setenv("RISK_AUTH_MODE", "full")
    monkeypatch.delenv("REDIS_URL", raising=False)
    dbmod.init_db()
    revocation.clear_memory()
    login_limiter.reset()
    refresh_limiter.reset()

    from api.main import app

    with TestClient(app) as c:
        yield c


def test_health_ready_anonymous(client: TestClient) -> None:
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db"] is True
    assert body["status"] == "ready"


def test_watermark_footer_rule(client: TestClient) -> None:
    from api.main import _watermark_footer

    assert _watermark_footer(None) == ""
    assert _watermark_footer({"role": "analyst", "username": "a"}) == ""
    out = _watermark_footer({"role": "viewer", "username": "v1"})
    assert "v1" in out and "水印" in out


def test_revocation_falls_back_without_redis(client: TestClient) -> None:
    revocation.clear_memory()
    # REDIS_URL 未设 → _redis() 返回 None，revoke/is_revoked 走内存 + SQLite
    assert revocation._redis() is None

    revocation.revoke("jti-prod-1", user_id="u1", kind="access", expires_at=int(time.time()) + 120)
    assert revocation.is_revoked("jti-prod-1") is True
    # SQLite 已持久化
    rows = dbmod.query("SELECT jti FROM revoked_token WHERE jti='jti-prod-1'")
    assert len(rows) == 1
