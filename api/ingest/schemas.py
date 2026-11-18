"""数据接入域请求模型（Pydantic v2）。

机器推送采用"严格 schema"：每维度一份 Item 模型，入口层统一做单位/编码归一；
越权字段拒收（模型未声明的字段被忽略，缺失的必填字段报错）。
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# 支持的接入维度（与 data_source_config.dimension 对齐）
DIMENSIONS = ("finance", "news", "legal", "market")


def _norm_code(v: str) -> str:
    """股票代码归一：6 位数字补零；M 前缀合成码（非上市企业）原样保留。"""
    s = str(v).strip()
    if s.upper().startswith("M"):
        return s.upper()
    return s.zfill(6)


class _Item(BaseModel):
    stock_code: str

    @field_validator("stock_code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _norm_code(v)


class FinanceItem(_Item):
    year: int = Field(ge=1990, le=2035)
    report_type: str = "年报"
    unit: str = "万元"  # 金额口径（入库按 unit 归一）
    revenue: Optional[float] = None
    net_profit: Optional[float] = None
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    debt_ratio: Optional[float] = None
    ocf: Optional[float] = None
    roe: Optional[float] = None


class NewsItem(_Item):
    title: str = Field(min_length=1)
    content: str = ""
    source: str = ""
    url: str = ""
    published_at: str = ""
    sentiment: Literal["positive", "neutral", "negative"] = "neutral"


class LegalItem(_Item):
    title: str = ""
    case_no: str = ""
    doc_type: str = ""
    court: str = ""
    cause: str = ""
    amount: Optional[float] = None
    status: str = ""
    judgment_date: str = ""
    source: str = ""


class MarketItem(_Item):
    market_cap: Optional[float] = None  # 总市值（元）


ITEM_MODELS: dict[str, type[BaseModel]] = {
    "finance": FinanceItem,
    "news": NewsItem,
    "legal": LegalItem,
    "market": MarketItem,
}


class IngestPushRequest(BaseModel):
    batch_id: str = Field(min_length=8, max_length=64)
    items: list[dict] = Field(min_length=1, max_length=5000)


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: ["ingest:*"])
    expires_at: str = ""


class DataSourceConfigIn(BaseModel):
    dimension: str = Field(min_length=1, max_length=20)
    source_name: str = Field(min_length=1, max_length=50)
    label: str = ""
    enabled: bool = True
    priority: int = 0
    merge_mode: str = "fallback"
    schedule_cron: str = ""
    config_json: dict = Field(default_factory=dict)
