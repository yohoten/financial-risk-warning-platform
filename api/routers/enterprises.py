"""企业档案 API（stock_code 主键）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.services import enterprise

router = APIRouter(prefix="/enterprises", tags=["enterprises"])


class EnterpriseIn(BaseModel):
    name: str
    stock_code: str | None = None
    industry: str = ""
    auto_refresh: bool = True


@router.get("")
def list_enterprises():
    return enterprise.list_enterprises()


@router.get("/{stock_code}")
def get_enterprise(stock_code: str):
    result = enterprise.get_enterprise(stock_code)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.post("")
def add_enterprise(body: EnterpriseIn):
    result = enterprise.add_enterprise(body.name, body.stock_code, body.industry, body.auto_refresh)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.delete("/{stock_code}")
def delete_enterprise(stock_code: str):
    return enterprise.delete_enterprise(stock_code)


@router.get("/{stock_code}/profile")
def profile(stock_code: str):
    result = enterprise.profile(stock_code)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result
