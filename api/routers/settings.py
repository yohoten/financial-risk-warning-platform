"""设置面板 API（DB 覆盖热生效）。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from api.services import settings_store

router = APIRouter(prefix="/settings", tags=["settings"])


class ModelsIn(BaseModel):
    base_url: str
    api_key: str | None = None


@router.get("")
def get_settings():
    return settings_store.get_view()


@router.put("")
def update_settings(body: dict):
    return settings_store.update(body)


@router.post("/reset")
def reset_settings():
    return settings_store.reset()


@router.post("/models")
def list_models(body: ModelsIn):
    return settings_store.list_models(body.base_url, body.api_key)
