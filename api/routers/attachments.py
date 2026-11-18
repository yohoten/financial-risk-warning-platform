"""多模态附件 API：上传 / 读取（视觉识别）/ 删除。"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel

from api.services import attachments, reading

router = APIRouter(prefix="/attachments", tags=["attachments"])


class UploadJson(BaseModel):
    filename: str
    data_base64: str
    mime: str = ""
    session_id: str = ""
    origin: str = "upload"


class ReadIn(BaseModel):
    target: str = "auto"
    table_id: int | None = None
    dry_run: bool = False


def _decode_base64(raw: str) -> bytes:
    body = raw.split("base64,", 1)[1] if "base64," in raw else raw
    try:
        return base64.b64decode(body.strip())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"base64 解码失败：{exc}")


@router.get("")
def list_attachments(session_id: str = "", limit: int = 50):
    return attachments.list_attachments(session_id, limit)


@router.post("")
def upload_json(body: UploadJson):
    data = _decode_base64(body.data_base64)
    mime = body.mime or attachments.guess_mime(body.filename)
    result = attachments.save(data, body.filename, mime, body.session_id, body.origin)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.post("/raw")
async def upload_raw(request_body: bytes, x_filename: str = Header("upload.bin"),
                     content_type: str = Header("application/octet-stream"),
                     x_session_id: str = Header("")):
    result = attachments.save(request_body, x_filename, content_type, x_session_id, "upload")
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.get("/{attachment_id}")
def get_raw(attachment_id: str):
    att = attachments.get(attachment_id)
    if att is None:
        raise HTTPException(404, f"附件不存在: {attachment_id}")
    data = attachments.read_bytes(attachment_id)
    return Response(content=data, media_type=att["mime"] or "application/octet-stream")


@router.get("/{attachment_id}/meta")
def get_meta(attachment_id: str):
    att = attachments.get(attachment_id)
    if att is None:
        raise HTTPException(404, f"附件不存在: {attachment_id}")
    return att


@router.delete("/{attachment_id}")
def delete_attachment(attachment_id: str):
    result = attachments.delete(attachment_id)
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result


@router.post("/{attachment_id}/read")
def read_attachment(attachment_id: str, body: ReadIn | None = None):
    result = reading.read_attachment(attachment_id, (body.target if body else "auto"),
                                     (body.table_id if body else None), (body.dry_run if body else False))
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result
