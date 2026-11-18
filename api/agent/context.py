"""上下文压缩（compaction）——前缀缓存友好（对齐 DSH 设计）。

要点：
- 摘要调用逐字复现最近一次已路由请求的前缀（system + tools + 历史），末尾追加压缩指令；
- thresholdRatio=0.8 触发、retainRatio=0.16 保留，容量/阈值来自 config.settings。
"""

from __future__ import annotations

import json

from config import settings
from api.agent.session import Session, store
from api.services.llm import LlmClient

COMPACTION_INSTRUCTION = (
    "你现在是压缩引擎（compaction engine）。请把上面的对话浓缩成一份可继续工作的检查点，"
    "只保留：用户目标与约束、已确认的事实与数据（企业名称/评分/预警编号）、工具调用结论、未完成的待办。"
    "要求：不要提及本次摘要请求；不要调用任何工具；只输出检查点正文；不超过 400 字；用中文。"
)

OVERFLOW_HINTS = (
    "context length", "context_length_exceeded", "maximum context", "too many tokens",
    "exceed", "上下文长度", "token limit",
)

TOOL_SEQUENCE_HINTS = ("role 'tool'", 'role "tool"', "tool_calls", "tool messages", "tool_call_id")


def estimate_tokens(messages: list[dict], tools: list[dict] | None = None) -> int:
    total = 0
    for m in messages:
        content = m.get("content") or ""
        if isinstance(content, (list, dict)):
            content = json.dumps(content, ensure_ascii=False)
        total += int(len(str(content)) / 1.6) + 6
        for tc in m.get("tool_calls") or []:
            total += int(len(json.dumps(tc, ensure_ascii=False)) / 2.5) + 4
    for t in tools or []:
        total += int(len(json.dumps(t, ensure_ascii=False)) / 2.5) + 4
    return total


def should_compact(messages: list[dict], tools: list[dict] | None = None) -> tuple[bool, int]:
    est = estimate_tokens(messages, tools)
    threshold = int(settings.LLM_CONTEXT_WINDOW * settings.COMPACTION_THRESHOLD_RATIO)
    return est >= threshold, est


def is_overflow_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(h in text for h in OVERFLOW_HINTS)


def is_tool_sequence_error(exc: Exception) -> bool:
    text = str(exc).lower()
    if "400" not in text:
        return False
    return any(h in text for h in TOOL_SEQUENCE_HINTS)


def _split_for_compaction(session: Session) -> tuple[list[dict], int]:
    active = [m for m in session.messages if (m.get("id") or 0) > session.compacted_until]
    if len(active) <= 2:
        return [], 0
    retain_budget = int(settings.LLM_CONTEXT_WINDOW * settings.COMPACTION_RETAIN_RATIO)
    kept: list[dict] = []
    used = 0
    for m in reversed(active):
        used += estimate_tokens([m])
        if used > retain_budget and kept:
            break
        kept.insert(0, m)
    cut_index = len(active) - len(kept)
    if cut_index <= 0:
        return [], 0
    fold = active[:cut_index]
    while fold and fold[-1].get("role") == "assistant" and fold[-1].get("tool_calls"):
        fold.pop()
    if not fold:
        return [], 0
    return fold, fold[-1].get("id") or 0


def compact(session: Session, client: LlmClient, base_messages: list[dict], tools: list[dict]) -> dict | None:
    fold, until_id = _split_for_compaction(session)
    if not fold or not until_id:
        return None
    messages = [*base_messages, {"role": "user", "content": COMPACTION_INSTRUCTION}]
    try:
        msg = client.chat(messages, tools=tools, max_tokens=settings.COMPACTION_SUMMARY_MAX_TOKENS)
    except Exception:  # noqa: BLE001
        return None
    summary = (msg.get("content") or "").strip()
    if not summary:
        return None
    store.set_summary(session, summary, until_id)
    return {"summary": summary, "until_id": until_id, "folded": len(fold), "usage": dict(client.last_usage)}
