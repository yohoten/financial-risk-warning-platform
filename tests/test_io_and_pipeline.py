"""I/O 与流水线冒烟测试。"""

from __future__ import annotations

import pandas as pd

from etl.io_utils import read_table, resolve, write_table
from etl.feature_selection import step1_iv, step3_psi


def test_write_read_roundtrip(tmp_path):
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    path = write_table(df, tmp_path / "t.parquet")
    assert path.exists()
    back = read_table(tmp_path / "t.parquet")
    pd.testing.assert_frame_equal(back, df)


def test_resolve_falls_back_to_csv(tmp_path):
    df = pd.DataFrame({"a": [1]})
    csv_path = tmp_path / "t.csv"
    df.to_csv(csv_path, index=False)
    assert resolve(tmp_path / "t.parquet") == csv_path


def test_step1_iv_keeps_informative_features(panel):
    features = ["roa", "debt_to_asset", "current_ratio", "ocf_to_net_profit"]
    kept, table = step1_iv(panel, features)
    assert isinstance(kept, list)
    assert set(kept) <= set(features)
    assert {"feature", "iv"}.issubset(table.columns)


def test_step3_psi_returns_bounded_scores(panel):
    features = ["roa", "debt_to_asset"]
    kept, table = step3_psi(panel, features)
    assert (table["psi"] >= 0).all()
    assert set(kept) <= set(features)
