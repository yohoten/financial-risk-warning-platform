import pandas as pd

from scripts.fetch_depreciation import merge_financial


def test_merge_depreciation_preserves_deducted_profit(tmp_path):
    target = tmp_path / "financial.csv"
    source = pd.DataFrame({
        "stock_code": ["000001", "000001", "000002"],
        "year": [2022, 2023, 2023],
        "depreciation": [None, None, 8.0],
        "deducted_profit": [10.0, 11.0, 12.0],
        "ocf": [1.0, 2.0, 3.0],
    })
    source.to_csv(target, index=False, encoding="utf-8-sig")
    candidate = pd.DataFrame({
        "stock_code": ["000001", "000002"],
        "year": [2023, 2023],
        "depreciation": [1.25, 2.5],
    })
    changed = merge_financial(candidate, target)
    result = pd.read_csv(target, dtype={"stock_code": str})
    assert changed == 1
    assert pd.isna(result.loc[0, "depreciation"])
    assert result.loc[1, "depreciation"] == 1.25
    assert result.loc[2, "depreciation"] == 8.0  # 已有真实值不被候选覆盖
    assert result["deducted_profit"].tolist() == [10.0, 11.0, 12.0]
    assert result["ocf"].tolist() == [1.0, 2.0, 3.0]
