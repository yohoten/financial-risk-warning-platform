"""插件（自定义 HTTP 工具）与 Agent 预设 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.services import plugins

router = APIRouter(prefix="/plugins", tags=["plugins"])


class ToolIn(BaseModel):
    name: str
    description: str = ""
    parameters: dict | None = None
    method: str = "GET"
    url: str = ""
    headers: dict | None = None
    body_template: str = ""
    enabled: bool = True
    require_approval: bool = False


class ToolPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    parameters: dict | None = None
    method: str | None = None
    url: str | None = None
    headers: dict | None = None
    body_template: str | None = None
    enabled: bool | None = None
    require_approval: bool | None = None


class PresetIn(BaseModel):
    name: str
    description: str = ""
    prompt_extra: str = ""
    tools: list[str] | None = None
    skills: list[str] | None = None
    model_override: str = ""
    enabled: bool = True


class PresetPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    prompt_extra: str | None = None
    tools: list[str] | None = None
    skills: list[str] | None = None
    model_override: str | None = None
    enabled: bool | None = None


class ImportIn(BaseModel):
    data: dict
    strategy: str = "rename"


@router.get("/tools")
def list_tools():
    return plugins.list_custom_tools()


@router.post("/tools")
def create_tool(body: ToolIn):
    result = plugins.create_custom_tool(**body.model_dump())
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.patch("/tools/{tool_id}")
def update_tool(tool_id: int, body: ToolPatch):
    result = plugins.update_custom_tool(tool_id, **body.model_dump(exclude_none=True))
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result


@router.delete("/tools/{tool_id}")
def delete_tool(tool_id: int):
    result = plugins.delete_custom_tool(tool_id)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.get("/presets")
def list_presets():
    return plugins.list_presets()


@router.post("/presets")
def create_preset(body: PresetIn):
    result = plugins.create_preset(**body.model_dump())
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.patch("/presets/{preset_id}")
def update_preset(preset_id: int, body: PresetPatch):
    result = plugins.update_preset(preset_id, **body.model_dump(exclude_none=True))
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: int):
    result = plugins.delete_preset(preset_id)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.get("/presets/{preset_id}/export")
def export_preset(preset_id: int):
    result = plugins.export_preset(preset_id)
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result


@router.get("/export")
def export_all():
    return plugins.export_all()


@router.post("/import")
def import_bundle(body: ImportIn):
    result = plugins.import_bundle(body.data, body.strategy)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result
