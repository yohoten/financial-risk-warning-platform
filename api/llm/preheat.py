"""提示词缓存预热（prompt cache preheat）。

原理：提供方按请求 token 序列的前缀做 KV Cache；静态前缀（system + tools）在每个
请求都出现。用完全相同的前缀发一个 max_tokens=1 的最小请求，把前缀提前写进提供方缓存。
TTL 内不重复预热；本地 mock 端点直接跳过。
"""

from __future__ import annotations

import threading
import time

from config import settings
from api.services.llm import LlmClient, LlmConfig

WARM_USER_TEXT = "预热"


class PromptCacheWarmer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.last_warm_at: float = 0.0
        self.last_label: str = ""
        self.warm_count: int = 0
        self.last_usage: dict = {}
        self.last_error: str = ""
        self.last_hit_tokens: int = 0

    def status(self) -> dict:
        return {
            "enabled": settings.PREHEAT_ENABLED,
            "warm_count": self.warm_count,
            "last_warm_at": self.last_warm_at,
            "last_warm_ago": round(time.time() - self.last_warm_at, 1) if self.last_warm_at else None,
            "last_label": self.last_label,
            "last_hit_tokens": self.last_hit_tokens,
            "ttl_seconds": settings.PREHEAT_TTL_SECONDS,
            "last_error": self.last_error,
        }

    def is_fresh(self) -> bool:
        return bool(self.last_warm_at) and (time.time() - self.last_warm_at) < settings.PREHEAT_TTL_SECONDS

    def warm(self, system_prompt: str, tools: list[dict], force: bool = False, label: str = "manual") -> dict:
        if not settings.PREHEAT_ENABLED:
            return {"skipped": "preheat disabled"}
        if not settings.LLM_BASE_URL or not settings.LLM_MODEL:
            return {"skipped": "LLM 未配置"}
        if _is_local_endpoint(settings.LLM_BASE_URL):
            return {"skipped": "本地 mock 端点无需预热"}
        with self._lock:
            if self.is_fresh() and not force:
                return {"skipped": f"缓存仍新鲜（{round(time.time() - self.last_warm_at, 1)}s 前预热）"}
            client = LlmClient(LlmConfig(
                base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY,
                model=settings.LLM_MODEL, max_tokens=1, timeout_s=settings.LLM_TIMEOUT_S,
                disable_thinking=settings.LLM_DISABLE_THINKING,
            ))
            try:
                client.chat(
                    [{"role": "system", "content": system_prompt}, {"role": "user", "content": WARM_USER_TEXT}],
                    tools=tools or None, max_tokens=1,
                )
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{type(exc).__name__}: {exc}"
                return {"error": self.last_error}
            usage = dict(client.last_usage)
            self.last_usage = usage
            self.last_warm_at = time.time()
            self.last_label = label
            self.warm_count += 1
            self.last_hit_tokens = int(usage.get("cache_hit_tokens", 0) or 0)
            return {"ok": True, "label": label, "usage": usage, **self.status()}

    def warm_async(self, system_prompt: str, tools: list[dict], label: str = "startup", force: bool = False) -> None:
        threading.Thread(
            target=self.warm, args=(system_prompt, tools), kwargs={"force": force, "label": label}, daemon=True,
        ).start()


def _is_local_endpoint(base_url: str) -> bool:
    return any(h in (base_url or "") for h in ("127.0.0.1", "localhost", "0.0.0.0"))


warmer = PromptCacheWarmer()
