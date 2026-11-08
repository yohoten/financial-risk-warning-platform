"""特征注册表一致性测试：防止文档与代码口径漂移。"""

from __future__ import annotations

from collections import Counter

from config.feature_registry import (
    FEATURES,
    FEATURE_GROUP_LABELS,
    FEATURE_KEYS,
    RADAR_DIMENSIONS,
    by_group,
    cn_names,
    direction_of,
    to_records,
)


def test_feature_count_and_uniqueness():
    assert len(FEATURES) >= 70, "特征总数应不少于 70 维"
    assert len(FEATURE_KEYS) == len(set(FEATURE_KEYS)), "特征 key 必须唯一"


def test_every_group_has_features():
    for group in FEATURE_GROUP_LABELS:
        assert by_group(group), f"维度 {group} 没有任何特征"


def test_group_counts_match_documented_design():
    counts = Counter(f.group for f in FEATURES)
    assert counts["solvency"] == 10
    assert counts["profitability"] == 10
    assert counts["operation"] == 10
    assert counts["growth"] == 8
    assert counts["cashflow"] == 7
    assert counts["text"] == 6
    assert counts["governance"] == 6
    assert counts["audit_market_legal"] == 8
    assert counts["macro_industry"] == 8


def test_radar_dimensions_are_valid_groups():
    for dim in RADAR_DIMENSIONS:
        assert dim in FEATURE_GROUP_LABELS
        assert len(by_group(dim)) >= 6, f"雷达维度 {dim} 特征过少，雷达图会失真"


def test_helpers_return_expected_types():
    names = cn_names(FEATURE_KEYS[:5])
    assert all(isinstance(v, str) for v in names.values())
    assert set(direction_of(FEATURE_KEYS).values()) <= {1, -1}
    records = to_records()
    assert len(records) == len(FEATURES)
    assert set(records[0]) == {"字段名", "中文名", "维度", "方向", "来源", "口径说明"}


def test_every_feature_has_documentation():
    for spec in FEATURES:
        assert spec.note and len(spec.note) >= 6, f"{spec.key} 缺少口径说明"
        assert spec.cn and spec.source in {"csmar", "derived", "text", "crawl", "macro"}
