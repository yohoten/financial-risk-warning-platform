"""API 请求模型（Pydantic v2）。

响应一律返回 dict（由领域层直接构造），不做严格响应模型校验，
避免 NaN / None 在序列化时抛错；字段口径见 docs/FastAPI服务层设计.md §3。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

CODE_PATTERN = r"^\d{6}$"


class CodesRequest(BaseModel):
    codes: list[str] = Field(min_length=1, max_length=1000)
    year: int | None = Field(default=None, ge=2013, le=2026)
    threshold_override: dict[str, float] | None = None

    @field_validator("codes")
    @classmethod
    def _normalize_codes(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        for code in values:
            code = str(code).strip()
            if code.endswith(".0"):
                code = code[:-2]
            code = code.zfill(6)
            if len(code) == 6 and code.isdigit():
                out.append(code)
        return list(dict.fromkeys(out))


class FrameRequest(BaseModel):
    """what-if 原始字段打分（P1 占位）。"""

    rows: list[dict] = Field(min_length=1, max_length=500)
    year: int = Field(default=2023, ge=2013, le=2026)
