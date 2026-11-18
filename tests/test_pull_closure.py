"""pull 通道与接入后闭环测试（P3 验收）。

覆盖：幂等入库（upsert_records）、受跟踪企业（tracked_codes）、缓存失效、闭环
（close_loop 触发预警 + SSE）、pull 任务执行、以及 consume 端点触发闭环。
全部不依赖网络与已训练模型（用合成 FetchResult / monkeypatch）。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("RISK_AUTH_MODE", "full")

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from api.auth import rbac, revocation  # noqa: E402
from api.auth import service as auth_service  # noqa: E402
from api.datasources.base import FetchResult, NormalizedRecord  # noqa: E402
from api.datasources import registry  # noqa: E402
from api.db import database as dbmod  # noqa: E402
from api.rate_limit import login_limiter, refresh_limiter  # noqa: E402

PASSWORD = "Passw0rd!2026"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "pull_test.db")
    monkeypatch.setenv("RISK_AUTH_MODE", "full")
    dbmod.init_db()
    revocation.clear_memory()
    login_limiter.reset()
    refresh_limiter.reset()

    from api.main import app

    with TestClient(app) as c:
        yield c


def _login(client, username, password=PASSWORD):
    return client.post("/auth/login", json={"username": username, "password": password})


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _finance_record(code="000001", year="2023") -> NormalizedRecord:
    return NormalizedRecord(
        kind="finance", external_id=f"{code}-{year}",
        source="akshare:test",
        payload={
            "year": year, "report_type": "年报", "revenue": 1000.0, "net_profit": 120.0,
            "debt_ratio": 50.0, "total_assets": 5000.0, "total_liabilities": 2500.0,
            "source": "test", "metrics_json": '{"roe": 12.5}',
        },
    )


# ---------------------------------------------------------------------------
# 幂等入库
# ---------------------------------------------------------------------------

def test_upsert_records_finance_idempotent(client) -> None:
    result = FetchResult("finance", "akshare:test", records=[_finance_record()])
    first = registry.upsert_records("000001", result)
    second = registry.upsert_records("000001", result)
    assert first == {"inserted": 1, "updated": 0}
    assert second == {"inserted": 0, "updated": 1}

    rows = dbmod.query("SELECT * FROM finance WHERE stock_code='000001' AND year='2023'")
    assert len(rows) == 1
    assert rows[0]["revenue"] == 1000.0
    # 多源合并：metrics_json 保留 + 来源拼接
    assert "roe" in (rows[0]["metrics_json"] or "")


def test_upsert_records_news_dedup(client) -> None:
    rec = NormalizedRecord(kind="news", external_id="n1", source="akshare:test",
                           payload={"title": "诉讼立案", "sentiment": "negative"})
    result = FetchResult("news", "akshare:test", records=[rec])
    registry.upsert_records("000001", result)
    registry.upsert_records("000001", result)
    rows = dbmod.query("SELECT * FROM news WHERE stock_code='000001'")
    assert len(rows) == 1


def test_fetch_dimension_returns_gap_without_code(client) -> None:
    result = registry.fetch_dimension("", "finance")
    assert not result.ok
    assert result.gap


# ---------------------------------------------------------------------------
# 受跟踪企业与缓存失效
# ---------------------------------------------------------------------------

def test_tracked_codes_from_enterprise_and_watchlist(client) -> None:
    dbmod.execute("INSERT INTO enterprise (stock_code, name) VALUES ('000001','测试A')")
    dbmod.execute("INSERT INTO user_enterprise (user_id, stock_code) VALUES ('u1','000002')")
    codes = registry.tracked_codes()
    assert "000001" in codes
    assert "000002" in codes


def test_invalidate_score_caches_no_error(client) -> None:
    from api.worker import pipeline
    pipeline.invalidate_score_caches()  # 不应抛异常（模块/模型缺失时兜底）


# ---------------------------------------------------------------------------
# 闭环
# ---------------------------------------------------------------------------

def test_close_loop_calls_alerts_and_publishes(client, monkeypatch) -> None:
    from api.worker import pipeline

    calls: list[str] = []
    monkeypatch.setattr("api.services.alerts.generate_for_enterprise",
                        lambda code, source="scoring": calls.append(code)
                        or {"created": [{"level": "red"}], "skipped": 0})
    events: list[tuple] = []
    monkeypatch.setattr(pipeline.bus, "publish",
                        lambda t, d: events.append((t, d)))

    result = pipeline.close_loop(["000001", "000002"], source="push")
    assert calls == ["000001", "000002"]
    assert result["codes"] == 2
    assert any(t == "alert.new" for t, _ in events)
    assert any(t == "score.refreshed" for t, _ in events)


def test_run_pull_dimension_no_tracked_codes(client) -> None:
    from api.worker import pipeline
    result = pipeline.run_pull_dimension("finance")
    assert result.get("skipped") is True
    # 落了一条 ingest_log
    rows = dbmod.query("SELECT * FROM ingest_log WHERE channel='pull'")
    assert len(rows) >= 1


# ---------------------------------------------------------------------------
# consume 端点触发闭环
# ---------------------------------------------------------------------------

def test_consume_endpoint_triggers_closure(client, monkeypatch) -> None:
    auth_service.create_user(username="admin", password=PASSWORD, email="a@x",
                             role=rbac.UserRole.ADMIN, must_change_password=False)
    token = _login(client, "admin").json()["access_token"]
    key = client.post("/ingest/keys", headers=_auth(token),
                      json={"name": "t", "scopes": ["ingest:*"]}).json()["plaintext"]

    client.post("/ingest/v1/finance", headers={"X-API-Key": key}, json={
        "batch_id": "batch12345",
        "items": [{"stock_code": "000001", "year": 2023, "revenue": 1000.0}],
    })

    monkeypatch.setattr("api.services.alerts.generate_for_enterprise",
                        lambda code, source="scoring": {"created": [], "skipped": 0})

    resp = client.post("/ingest/staging/consume", headers=_auth(token), json={})
    body = resp.json()
    assert body["inserted"] == 1
    assert body["codes"] == ["000001"]
    assert "closed" in body
