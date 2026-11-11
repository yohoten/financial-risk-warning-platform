"""阈值链路：model_meta.json → score_to_level / 评估报告同源。"""

from __future__ import annotations

import json

from config import settings
from models import metrics


def _write_meta(path, threshold: dict) -> None:
    path.write_text(json.dumps({"threshold": threshold}, ensure_ascii=False), encoding="utf-8")


def test_thresholds_come_from_model_meta(tmp_path, monkeypatch):
    path = tmp_path / "model_meta.json"
    _write_meta(
        path,
        {
            "value": 0.27,
            "high": 0.27,
            "medium": 0.135,
            "method": "youden",
            "selected_on": "valid_2023",
        },
    )
    monkeypatch.setattr(settings, "MODEL_META", path)

    thresholds = metrics.load_thresholds()
    assert thresholds["source"] == "model_meta"
    assert thresholds["high"] == 0.27
    assert thresholds["medium"] == 0.135
    assert metrics.score_to_level(0.30) == "高风险"
    assert metrics.score_to_level(0.20) == "中风险"
    assert metrics.score_to_level(0.10) == "低风险"


def test_thresholds_fallback_without_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_META", tmp_path / "missing.json")

    thresholds = metrics.load_thresholds()
    assert thresholds["source"] == "settings"
    assert thresholds["high"] == settings.RISK_THRESHOLDS["high"]
    assert thresholds["medium"] == settings.RISK_THRESHOLDS["medium"]


def test_thresholds_repair_inverted_bands(tmp_path, monkeypatch):
    path = tmp_path / "meta.json"
    _write_meta(path, {"value": 0.2, "high": 0.2, "medium": 0.3})
    monkeypatch.setattr(settings, "MODEL_META", path)

    thresholds = metrics.load_thresholds()
    assert thresholds["medium"] < thresholds["high"]
    assert thresholds["medium"] == round(0.2 * settings.RISK_MEDIUM_RATIO, 4)
