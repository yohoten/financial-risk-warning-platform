import pandas as pd

from config import settings
from config.feature_registry import FEATURE_KEYS
from etl.feature_engineering import _filter_manufacturing


def test_manufacturing_filter_keeps_all_c_subindustries_only():
    frame = pd.DataFrame({
        "stock_code": ["000001", "000002", "000003", "000004"],
        "year": [2023] * 4,
        "industry": ["C13", "C39", "I65", "K70"],
        "total_assets": [1.0] * 4,
    })
    result = _filter_manufacturing(frame)
    assert result["stock_code"].tolist() == ["000001", "000002"]


def test_availability_flags_are_not_model_features():
    assert not set(settings.AVAILABILITY_COLUMNS) & set(FEATURE_KEYS)
