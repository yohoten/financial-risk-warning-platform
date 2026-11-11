"""字段映射测试：中文列名、单位换算、代码补零与异常值编码。"""

from __future__ import annotations

import pandas as pd

from etl.mapping import apply_mapping, load_mapping, normalize_name


def test_mapping_covers_every_required_column():
    mapping = load_mapping()
    for table, spec in mapping["tables"].items():
        assert spec["required"], f"{table} 未声明必需列"
        for column in spec["required"]:
            assert column in spec["columns"], f"{table} 必需列 {column} 未定义映射"


def test_mapping_financial_converts_units_and_codes():
    raw = pd.DataFrame(
        {
            "证券代码": [1, "600000"],
            "会计年度": ["2023-12-31", "2024-12-31"],
            "证券简称": ["示例A", "示例B"],
            "行业代码": ["C27", "C34"],
            "营业收入": [1.0e8, 2.0e8],
            "资产总计": [5.0e8, 6.0e8],
            "负债合计": [2.0e8, 2.5e8],
            "所有者权益合计": [3.0e8, 3.5e8],
            "净利润": [1.5e7, 3.0e7],
            "经营活动产生的现金流量净额": [1.0e7, 2.0e7],
            "备注": ["忽略我", "忽略我"],
        }
    )

    out, report = apply_mapping(raw, "financial")

    assert report["required_missing"] == []
    assert out.loc[0, "stock_code"] == "000001"
    assert out.loc[1, "stock_code"] == "600000"
    assert out.loc[0, "year"] == 2023
    assert abs(float(out.loc[0, "revenue"]) - 1.0) < 1e-9  # 1 亿元
    assert abs(float(out.loc[0, "total_assets"]) - 5.0) < 1e-9
    assert "备注" in report["unused_source"]


def test_mapping_reports_missing_required_columns():
    raw = pd.DataFrame({"证券代码": ["000001"], "会计年度": [2023], "总资产": [1e8]})
    _, report = apply_mapping(raw, "financial")
    assert "revenue" in report["required_missing"]
    assert "net_profit" in report["required_missing"]


def test_mapping_encodes_audit_opinion():
    raw = pd.DataFrame(
        {
            "证券代码": ["000001"] * 4,
            "会计年度": [2023] * 4,
            "审计意见类型": [1, 2, "标准无保留意见", "保留意见"],
        }
    )
    out, _ = apply_mapping(raw, "market_features")
    assert out["audit_opinion"].tolist() == [0, 1, 0, 1]


def test_mapping_encodes_st_flag():
    raw = pd.DataFrame(
        {
            "证券代码": ["000001"] * 4,
            "会计年度": [2023] * 4,
            "是否ST": ["是", "否", "*ST", "0"],
        }
    )
    out, _ = apply_mapping(raw, "labels_st")
    assert out["is_st"].tolist() == [1, 0, 1, 0]


def test_normalize_name_handles_fullwidth_and_spaces():
    assert normalize_name(" 营业 收入 ") == "营业收入"
    assert normalize_name("ＯｐｅｒａｔｉｎｇＲｅｖｅｎｕｅ") == "operatingrevenue"
