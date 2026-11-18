"""分享链接（只读会话快照，无需登录）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.agent.session import store

router = APIRouter(prefix="/share", tags=["share"])


@router.get("/{token}")
def get_shared(token: str):
    data = store.get_shared(token)
    if data is None:
        raise HTTPException(404, "分享链接无效或已撤销")
    return data
