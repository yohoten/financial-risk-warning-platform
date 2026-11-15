"""FastAPI 服务层冒烟测试：依赖本机已训练模型与数据。

CI 无数据时自动跳过（数据门禁已在 .github/workflows/ci.yml 单独处理）。
"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from config import settings  # noqa: E402

pytestmark = pytest.mark.skipif(
    not settings.MODEL_PATH.exists()
    or not (settings.FEATURE_MATRIX.exists() or settings.FEATURE_PANEL.exists()),
    reason="本机未就绪模型/数据",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    from api.main import app

    with TestClient(app) as c:
        yield c


def _sample_code() -> tuple[str, int]:
    import pandas as pd
    from etl.io_utils import read_table, resolve

    path = settings.FEATURE_MATRIX if resolve(settings.FEATURE_MATRIX) else settings.FEATURE_PANEL
    panel = read_table(path)
    row = panel[panel["year"] == panel["year"].max()].iloc[0]
    return str(row["stock_code"]).zfill(6), int(panel["year"].max())


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"]
    assert body["status"] in {"ok", "degraded"}


def test_model_meta(client: TestClient) -> None:
    resp = client.get("/model/meta")
    assert resp.status_code == 200
    assert "features" in resp.json()


def test_predict_codes(client: TestClient) -> None:
    code, year = _sample_code()
    resp = client.post("/predict/codes", json={"codes": [code, "999999"], "year": year})
    assert resp.status_code == 200
    body = resp.json()
    assert body["unmatched"] == ["999999"]
    assert body["items"][0]["stock_code"] == code
    assert body["semantics"].startswith("特征年")


def test_top_risk(client: TestClient) -> None:
    resp = client.get("/predict/top-risk", params={"limit": 5})
    assert resp.status_code == 200
    assert len(resp.json()["items"]) <= 5


def test_explain(client: TestClient) -> None:
    code, year = _sample_code()
    resp = client.get(f"/explain/{code}", params={"year": year})
    assert resp.status_code == 200
    body = resp.json()
    assert "prediction" in body and "contributions" in body


def test_global_importance(client: TestClient) -> None:
    resp = client.get("/explain/global", params={"top_n": 10})
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 10


def test_features_dictionary(client: TestClient) -> None:
    resp = client.get("/features")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) >= 36
