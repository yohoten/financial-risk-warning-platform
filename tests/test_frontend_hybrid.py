"""前端混合架构冒烟：backend 抽象 + ECharts option 工厂（纯数据转换）。"""

from __future__ import annotations

import pandas as pd
import pytest

from config import settings


def test_backend_mode_and_health_local() -> None:
    from streamlit_app.utils import backend

    assert backend.mode() in {"api", "local"}
    assert isinstance(backend.health(), dict)


@pytest.mark.skipif(not settings.MODEL_META.exists(), reason="本机未就绪模型")
def test_echarts_option_factories() -> None:
    from streamlit_app.utils import echarts_options as E

    assert isinstance(E.has_echarts(), bool)

    scored = pd.DataFrame({
        "industry": ["C27", "C27", "C38", "C38"],
        "year": [2022, 2023, 2022, 2023],
        "stock_code": ["000001", "000002", "000003", "000004"],
        "company_name": ["a", "b", "c", "d"],
        "is_st": [0, 1, 1, 0],
        "st_prob": [0.01, 0.08, 0.05, 0.02],
        "risk_level": ["低风险", "高风险", "中风险", "低风险"],
    })

    heat = E.industry_year_heatmap_option(scored)
    assert heat["series"][0]["type"] == "heatmap"
    assert heat["series"][0]["data"], "热力图数据不应为空"

    trend = E.st_trend_option(scored)
    assert len(trend["series"]) == 3
    assert {s["type"] for s in trend["series"]} == {"bar", "line"}

    bar = E.industry_risk_bar_option(scored)
    assert bar["series"][0]["type"] == "bar"
