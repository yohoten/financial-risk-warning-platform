"""令牌撤销表（jti 黑名单）：内存热缓存 + SQLite 持久兜底。

P4 生产形态可把 ``_store_backend`` 换 Redis（多 worker 共享），接口保持不变。
"""

from __future__ import annotations

import time

_MEMORY: dict[str, int] = {}  # jti -> expires_at(epoch)
_MEMORY_LIMIT = 20_000

# 可选 Redis 后端（生产多 worker 共享黑名单）；单机/测试无 REDIS_URL 时回退 SQLite+内存。
_REDIS_STATE: dict = {"client": None, "checked": False}


def _redis():
    """惰性返回 Redis 客户端（连接一次并缓存结果；不可用返回 None）。"""
    if _REDIS_STATE["checked"]:
        return _REDIS_STATE["client"]
    _REDIS_STATE["checked"] = True
    import os

    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return None
    try:
        import redis

        client = redis.Redis.from_url(url, decode_responses=True,
                                      socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        _REDIS_STATE["client"] = client
        return client
    except Exception:  # noqa: BLE001 —— Redis 未就绪时回退
        return None


def _set_redis(jti: str, expires_at: int) -> None:
    try:
        client = _redis()
        if client is None:
            return
        client.setex(f"revoked:{jti}", max(1, int(expires_at) - int(time.time())), "1")
    except Exception:  # noqa: BLE001
        pass


def _remember(jti: str, expires_at: int) -> None:
    if len(_MEMORY) > _MEMORY_LIMIT:
        purge_expired()
    _MEMORY[jti] = int(expires_at)


def revoke(jti: str, *, user_id: str = "", kind: str = "access", expires_at: int = 0) -> None:
    """撤销单个令牌（加入黑名单并落库）。"""
    if not jti:
        return
    exp = int(expires_at) or int(time.time()) + 86400
    _remember(jti, exp)
    _set_redis(jti, exp)
    try:
        from api.db.database import execute

        execute(
            "INSERT OR REPLACE INTO revoked_token (jti, user_id, kind, expires_at) VALUES (?,?,?,?)",
            (jti, user_id, kind, exp),
        )
    except Exception:  # noqa: BLE001 —— 库表未就绪时以内存为准，不阻断登出
        pass


def is_revoked(jti: str) -> bool:
    """令牌是否已撤销。"""
    if not jti:
        return False
    exp = _MEMORY.get(jti)
    if exp is not None:
        if exp > int(time.time()):
            return True
        _MEMORY.pop(jti, None)
    # Redis 优先（多 worker 共享）
    try:
        client = _redis()
        if client is not None and client.exists(f"revoked:{jti}"):
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        from api.db.database import query

        rows = query("SELECT expires_at FROM revoked_token WHERE jti = ?", (jti,))
    except Exception:  # noqa: BLE001
        return False
    if not rows:
        return False
    exp = int(rows[0].get("expires_at") or 0)
    if exp and exp <= int(time.time()):
        return False
    _remember(jti, exp)
    return True


def purge_expired() -> int:
    """清理过期记录（worker 每日任务复用），返回删除行数。"""
    now = int(time.time())
    for jti in [k for k, v in _MEMORY.items() if v <= now]:
        _MEMORY.pop(jti, None)
    try:
        from api.db.database import execute

        return int(execute("DELETE FROM revoked_token WHERE expires_at <= ?", (now,)) or 0)
    except Exception:  # noqa: BLE001
        return 0


def clear_memory() -> None:
    """仅测试/切换认证模式时使用。"""
    _MEMORY.clear()
    _REDIS_STATE["client"] = None
    _REDIS_STATE["checked"] = False