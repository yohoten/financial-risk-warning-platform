"""API Key：签发 / 校验（SHA256，明文仅签发时返回一次）。

与 JWT 通道互补：机器推送（/ingest/v1/*）走 X-API-Key，不经用户登录。
只存哈希、scopes 做维度授权、支持过期与吊销、记录 last_used。
"""

from __future__ import annotations

import hashlib
import secrets

from api.db.database import execute, query

KEY_PREFIX = "risk_"
SCOPE_ANY = "ingest:*"


def _hash(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def bearer_key(authorization: str) -> str:
    """从 ``Authorization: Bearer <key>`` 提取明文；非 Bearer 返回空串。"""
    if not authorization:
        return ""
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return ""


def issue_key(name: str, scopes: list[str], created_by: str = "", expires_at: str = "") -> dict:
    """签发新 Key；返回 dict（含一次性明文 plaintext，之后不再可查）。"""
    plain = KEY_PREFIX + secrets.token_hex(24)
    kid = execute(
        "INSERT INTO api_key (name, key_hash, scopes, created_by, expires_at)"
        " VALUES (?,?,?,?,?)",
        (name, _hash(plain), ",".join(scopes), created_by, expires_at),
    )
    return {
        "id": kid, "name": name, "scopes": list(scopes),
        "plaintext": plain, "prefix": plain[:10],
    }


def list_keys() -> dict:
    """列出 Key（脱敏：不返回 key_hash，仅前缀与掩码）。"""
    rows = query("SELECT * FROM api_key ORDER BY id DESC")
    for r in rows:
        r["scopes"] = (r.get("scopes") or "").split(",")
        r["masked"] = KEY_PREFIX + "****" + (r.get("key_hash") or "")[:6]
        r.pop("key_hash", None)
    return {"total": len(rows), "items": rows}


def revoke_key(key_id: int) -> None:
    execute("UPDATE api_key SET revoked=1 WHERE id=?", (key_id,))


def verify_key(plain: str) -> dict | None:
    """校验明文 Key，返回有效 key 行（含 scopes 集合）；无效/吊销/过期返回 None。"""
    if not plain:
        return None
    rows = query(
        "SELECT * FROM api_key WHERE key_hash=? AND revoked=0"
        " AND (expires_at='' OR expires_at >= datetime('now','localtime'))",
        (_hash(plain),),
    )
    if not rows:
        return None
    row = rows[0]
    execute("UPDATE api_key SET last_used_at=datetime('now','localtime') WHERE id=?", (row["id"],))
    row["scopes"] = set((row.get("scopes") or "").split(","))
    return row


def key_has_scope(key_row: dict, dimension: str) -> bool:
    """该 Key 是否被授权推送指定维度（ingest:* 通配或 ingest:{dimension}）。"""
    scopes = key_row.get("scopes") or set()
    return SCOPE_ANY in scopes or f"ingest:{dimension}" in scopes
