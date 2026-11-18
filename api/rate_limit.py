"""轻量限频器（滑动窗口，进程内）。

为何不引 slowapi：单机/桌面形态进程内计数已足够，生产多副本在 P4 换 Redis
后端时只需替换 ``RateLimiter`` 的存储实现，调用方接口不变。
"""

from __future__ import annotations

import threading
import time

from config import settings


class RateLimiter:
    """按 key（通常是 IP 或 IP+用户名）计数的最小限频器。"""

    def __init__(self, max_calls: int, window_seconds: float = 60.0) -> None:
        self.max_calls = max(1, int(max_calls))
        self.window = float(window_seconds)
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        """返回 (是否放行, 建议等待秒数)。"""
        now = time.time()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(hits) >= self.max_calls:
                retry_after = max(1, int(self.window - (now - hits[0])))
                self._hits[key] = hits
                return False, retry_after
            hits.append(now)
            self._hits[key] = hits
            if len(self._hits) > 5000:  # 防内存膨胀
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                    self._hits.pop(k, None)
            return True, 0

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


# 登录/刷新接口限频（每 IP，每分钟）
login_limiter = RateLimiter(settings.LOGIN_RATE_LIMIT, 60.0)
refresh_limiter = RateLimiter(max(10, settings.LOGIN_RATE_LIMIT * 2), 60.0)


def client_ip(request) -> str:
    """取客户端 IP（优先 X-Forwarded-For 首段，反代部署时更准确）。"""
    forwarded = request.headers.get("x-forwarded-for") if request else None
    if forwarded:
        return forwarded.split(",")[0].strip()
    real = request.headers.get("x-real-ip") if request else None
    if real:
        return real.strip()
    client = getattr(request, "client", None) if request else None
    return getattr(client, "host", "") or "unknown"