"""技能库 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.services import skills

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillIn(BaseModel):
    name: str
    description: str = ""
    content: str = ""


class SkillPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    enabled: bool | None = None


@router.get("")
def list_skills():
    return skills.list_skills()


@router.post("")
def create_skill(body: SkillIn):
    result = skills.create_skill(body.name, body.description, body.content)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.patch("/{skill_id}")
def update_skill(skill_id: int, body: SkillPatch):
    result = skills.update_skill(skill_id, **body.model_dump(exclude_none=True))
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result


@router.delete("/{skill_id}")
def delete_skill(skill_id: int):
    result = skills.delete_skill(skill_id)
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result
