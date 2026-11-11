"""原始数据校验器测试：正常数据通过、缺列/重复主键被阻断。"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.validate_raw_data import validate_dataset

FILES = {
    "financial": "csmar_financial.csv",
    "governance": "csmar_governance.csv",
    "sentiment": "text_sentiment.csv",
    "market": "market_features.csv",
    "legal": "legal_events.csv",
    "labels": "labels_st.csv",
}


@pytest.fixture
def raw_dirs(tmp_path, raw_tables):
    raw = tmp_path / "raw"
    external = tmp_path / "external"
    raw.mkdir()
    external.mkdir()
    for key, name in FILES.items():
        raw_tables[key].to_csv(raw / name, index=False, encoding="utf-8-sig")
    raw_tables["macro"].to_csv(external / "macro_industry.csv", index=False, encoding="utf-8-sig")
    return raw, external


def test_validate_demo_raw_passes(raw_dirs, tmp_path):
    raw, external = raw_dirs
    report = validate_dataset(raw_dir=raw, external_dir=external, out_dir=tmp_path / "out")

    assert report["summary"]["errors"] == 0
    assert report["summary"]["tables"] == 7
    assert (tmp_path / "out" / "data_quality_report.md").exists()
    assert report["coverage"]["labels_st@modeling_window"] == 1.0


def test_validate_detects_missing_column_and_duplicate_key(raw_dirs, tmp_path):
    raw, external = raw_dirs
    financial = pd.read_csv(raw / "csmar_financial.csv")
    broken = financial.drop(columns=["revenue"])
    broken = pd.concat([broken, broken.head(1)], ignore_index=True)
    broken.to_csv(raw / "csmar_financial.csv", index=False, encoding="utf-8-sig")

    report = validate_dataset(raw_dir=raw, external_dir=external, out_dir=tmp_path / "out")
    checks = {issue["check"] for table in report["tables"] for issue in table["issues"]}

    assert report["summary"]["errors"] >= 2
    assert "required_columns" in checks
    assert "key_duplicate" in checks


def test_validate_detects_invalid_label(raw_dirs, tmp_path):
    raw, external = raw_dirs
    labels = pd.read_csv(raw / "labels_st.csv")
    labels.loc[0, "is_st"] = 7
    labels.to_csv(raw / "labels_st.csv", index=False, encoding="utf-8-sig")

    report = validate_dataset(raw_dir=raw, external_dir=external, out_dir=tmp_path / "out")
    checks = {issue["check"] for table in report["tables"] for issue in table["issues"]}
    assert "label_binary" in checks
