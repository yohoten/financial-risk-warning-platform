"""多模态附件：内容寻址（sha256）去重 + 落盘 + 列表/读取/删除。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from config import settings
from api.db import execute, query

ATT_DIR = settings.WRITABLE_DIR / "attachments"

MIME_GUESS = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".gif": "image/gif", ".bmp": "image/bmp", ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}


def guess_mime(filename: str) -> str:
    lower = (filename or "").lower()
    for ext, mime in MIME_GUESS.items():
        if lower.endswith(ext):
            return mime
    return "application/octet-stream"


def save(data: bytes, filename: str, mime: str, session_id: str = "", origin: str = "upload") -> dict:
    if not data:
        return {"error": "文件内容为空"}
    if len(data) > 20 * 1024 * 1024:
        return {"error": "文件超过 20MB 上限"}
    sha = hashlib.sha256(data).hexdigest()
    mime = mime or guess_mime(filename)
    existing = query("SELECT sha256 FROM attachment WHERE sha256 = ?", (sha,))
    if existing:
        return {"attachment_id": sha, "name": filename, "mime": mime, "size": len(data), "dedup": True}
    ATT_DIR.mkdir(parents=True, exist_ok=True)
    (ATT_DIR / sha).write_bytes(data)
    execute("INSERT INTO attachment (sha256, name, mime, size, path, kind, reading_json) VALUES (?, ?, ?, ?, ?, ?, '')",
           (sha, filename, mime, len(data), str(ATT_DIR / sha), "image" if mime.startswith("image/") else "file"))
    return {"attachment_id": sha, "name": filename, "mime": mime, "size": len(data), "dedup": False}


def get(attachment_id: str) -> dict | None:
    rows = query("SELECT * FROM attachment WHERE sha256 = ?", (attachment_id,))
    return dict(rows[0]) if rows else None


def read_bytes(attachment_id: str) -> bytes:
    att = get(attachment_id)
    if att is None:
        raise FileNotFoundError(f"附件不存在: {attachment_id}")
    p = Path(att["path"])
    return p.read_bytes() if p.exists() else b""


def list_attachments(session_id: str = "", limit: int = 50) -> dict:
    sql = "SELECT * FROM attachment"
    params: list = []
    if session_id:
        sql += " WHERE name LIKE ?"
        params.append(f"%{session_id}%")
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = query(sql, tuple(params))
    return {"total": len(rows), "items": [
        {"attachment_id": r["sha256"], "name": r["name"], "mime": r["mime"], "size": r["size"],
         "kind": r["kind"], "reading": json.loads(r["reading_json"] or "{}"), "created_at": r["created_at"]}
        for r in rows]}


def set_reading(attachment_id: str, reading: dict) -> None:
    execute("UPDATE attachment SET reading_json = ? WHERE sha256 = ?",
           (json.dumps(reading, ensure_ascii=False), attachment_id))


def delete(attachment_id: str) -> dict:
    att = get(attachment_id)
    if att is None:
        return {"error": f"附件不存在: {attachment_id}"}
    p = Path(att["path"])
    if p.exists():
        p.unlink(missing_ok=True)
    execute("DELETE FROM attachment WHERE sha256 = ?", (attachment_id,))
    return {"deleted": attachment_id}
