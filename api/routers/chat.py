"""对话式研判 API（SSE 流式 + 会话历史持久化）。"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from api.agent.loop import run_agent
from api.agent.session import store

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None
    preset_id: int | None = None


class ApprovalIn(BaseModel):
    approval_id: str
    approved: bool


class SessionPatch(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class BatchDeleteIn(BaseModel):
    ids: list[str]


class SessionImportIn(BaseModel):
    data: dict


@router.post("/approve")
def approve(body: ApprovalIn):
    from api.agent import approvals
    ok = approvals.resolve(body.approval_id, body.approved)
    if not ok:
        raise HTTPException(404, "审批请求不存在或已处理（可能已超时）")
    return {"approval_id": body.approval_id, "approved": body.approved}


@router.get("/sessions")
def list_sessions(limit: int = 50, q: str = ""):
    return {"sessions": store.list_sessions(limit=limit, q=q)}


@router.post("/sessions")
def create_session():
    s = store.create()
    return {"session_id": s.id, "title": s.title, "created_at": s.created_at}


@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    s = store.get(session_id)
    if s is None:
        raise HTTPException(404, "会话不存在")
    return {"session_id": s.id, "title": s.title, "updated_at": s.updated_at, "summary": s.summary,
            "usage": store.usage_stats(s),
            "messages": [{"role": m.get("role"), "content": m.get("content") or "",
                          "tool_calls": m.get("tool_calls") or [], "tool_call_id": m.get("tool_call_id", ""),
                          "tool_name": m.get("tool_name", "")} for m in s.messages]}


@router.patch("/sessions/{session_id}")
def patch_session(session_id: str, body: SessionPatch):
    if body.title is not None:
        result = store.rename(session_id, body.title)
        if result.get("error"):
            raise HTTPException(404, result["error"])
    if body.pinned is not None:
        result = store.set_pinned(session_id, body.pinned)
        if result.get("error"):
            raise HTTPException(404, result["error"])
    return {"ok": True, "session_id": session_id}


@router.post("/sessions/{session_id}/clear")
def clear_session(session_id: str):
    result = store.clear_messages(session_id)
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result


@router.post("/sessions/batch_delete")
def batch_delete(body: BatchDeleteIn):
    return store.batch_delete(body.ids)


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    if not store.delete(session_id):
        raise HTTPException(404, "会话不存在")
    return {"deleted": session_id}


@router.get("/sessions/{session_id}/export")
def export_session(session_id: str, format: str = "md"):
    if format == "json":
        data = store.export_json(session_id)
        if not data:
            raise HTTPException(404, "会话不存在")
        return data
    text = store.export_markdown(session_id)
    if not text:
        raise HTTPException(404, "会话不存在")
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="session-{session_id}.md"'})


@router.post("/sessions/{session_id}/share")
def share_session(session_id: str):
    result = store.share(session_id)
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result


@router.delete("/sessions/{session_id}/share")
def revoke_share(session_id: str):
    result = store.revoke_share(session_id)
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result


@router.post("/import")
def import_session(body: SessionImportIn):
    result = store.import_session(body.data)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.get("/usage")
def usage_summary(session_id: str | None = None):
    from config import settings
    rows = store.list_sessions(limit=100000)
    sessions = len(rows)
    totals = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
              "cache_hit_tokens": 0, "cache_miss_tokens": 0, "compact_count": 0}
    for s in rows:
        st = store.usage_stats(store.get(s["id"])) if store.get(s["id"]) else {}
        for k in totals:
            totals[k] += st.get(k, 0)
    cache_total = totals["cache_hit_tokens"] + totals["cache_miss_tokens"]
    global_stats = {**totals, "sessions": sessions,
                    "cache_hit_rate": round(totals["cache_hit_tokens"] / cache_total, 4) if cache_total else 0.0}
    session_stats = None
    if session_id:
        s = store.get(session_id)
        if s is not None:
            session_stats = {"session_id": s.id, "title": s.title, **store.usage_stats(s)}
    from api.llm.preheat import warmer
    return {"model": settings.LLM_MODEL, "context_window": settings.LLM_CONTEXT_WINDOW,
            "threshold_ratio": settings.COMPACTION_THRESHOLD_RATIO, "retain_ratio": settings.COMPACTION_RETAIN_RATIO,
            "global": global_stats, "session": session_stats, "preheat": warmer.status()}


@router.post("/stream")
def chat_stream(body: ChatIn):
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(400, "消息不能为空")

    def generator():
        session = store.get_or_create(body.session_id)
        yield f"event: session\ndata: {json.dumps({'session_id': session.id, 'title': session.title}, ensure_ascii=False)}\n\n"
        for ev in run_agent(session, message, preset_id=body.preset_id):
            yield ev.to_sse()

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
