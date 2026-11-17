"""LLM 网关（移植自旧项目 server/app/llm/client.py，非流式）。

OpenAI 兼容 chat/completions 客户端：三参数 base_url/api_key/model，
支持 DeepSeek / OpenAI / vLLM 等切换；解析采用防御链（状态码 → error → choices → message）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx


class LlmException(RuntimeError):
    """LLM 调用失败（结构化错误）。

    status_code：-1 = 网络/IO；0 = 响应异常（无 HTTP 码）；其它 = HTTP 状态码。
    """

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code

    def retryable(self) -> bool:
        return self.status_code < 0 or self.status_code in (408, 429) or self.status_code >= 500


def _retryable_status(status_code: int) -> bool:
    return status_code in (408, 429) or status_code >= 500


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    api_key: str
    model: str
    max_tokens: int = 1024
    timeout_s: float = 60.0
    max_retries: int = 1
    disable_thinking: bool = False


class LlmClient:
    def __init__(self, config: LlmConfig):
        self._config = config
        self._http = httpx.Client(timeout=config.timeout_s)
        self.last_usage: dict = {}

    @property
    def config(self) -> LlmConfig:
        return self._config

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             max_tokens: int | None = None) -> dict:
        url = self._config.base_url.rstrip("/") + "/chat/completions"
        body: dict = {
            "model": self._config.model,
            "messages": messages,
            "max_tokens": max_tokens or self._config.max_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if self._config.disable_thinking:
            body["thinking"] = {"type": "disabled"}

        resp = None
        last_exc: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                resp = self._http.post(url, json=body,
                                       headers={"Authorization": f"Bearer {self._config.api_key}"})
                if resp.status_code // 100 == 2 or not _retryable_status(resp.status_code):
                    break
            except httpx.HTTPError as exc:
                last_exc = exc
                resp = None
            if attempt < self._config.max_retries:
                time.sleep(0.8 * (attempt + 1))
        if resp is None:
            raise LlmException(-1, f"LLM call failed: {last_exc}") from last_exc

        if resp.status_code // 100 != 2:
            raise LlmException(resp.status_code, f"LLM HTTP {resp.status_code}: {resp.text[:500]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise LlmException(0, "LLM 响应体无效（非 JSON）: " + resp.text[:200]) from exc
        if data is None or (isinstance(data, dict) and data.get("error")):
            raise LlmException(0, f"LLM error: {data}")
        usage = (data or {}).get("usage") or {}
        if usage:
            self.last_usage = {
                "prompt_tokens": usage.get("prompt_tokens", 0) or 0,
                "completion_tokens": usage.get("completion_tokens", 0) or 0,
            }
        choices = data.get("choices") or []
        if not choices:
            raise LlmException(0, "LLM returned no choices")
        msg = choices[0].get("message") or {}
        if not msg:
            raise LlmException(0, "LLM message missing")
        return msg
