"""Agent 循环（流式）：模型 ↔ 工具，直到给出最终回答。"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterator

from config import settings
from api.agent import approvals, context
from api.agent.events import AgentEvent
from api.agent.prompt import SYSTEM_PROMPT
from api.agent.session import Session, store
from api.agent.tools import build_registry, register_custom_tools, register_mcp
from api.services.llm import LlmClient, LlmConfig

MAX_STEPS = 5
MAX_TOOL_RESULT_CHARS = 6000


def _registry_for(preset: dict | None = None):
    reg = build_registry(preset)
    try:
        register_custom_tools(reg)
    except Exception:  # noqa: BLE001
        pass
    try:
        register_mcp(reg)
    except Exception:  # noqa: BLE001
        pass
    return reg


def _client(model_override: str | None = None) -> LlmClient:
    return LlmClient(LlmConfig(
        base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY,
        model=model_override or settings.LLM_MODEL, max_tokens=settings.LLM_MAX_TOKENS,
        timeout_s=settings.LLM_TIMEOUT_S, disable_thinking=settings.LLM_DISABLE_THINKING,
    ))


def _summarize(result: dict) -> dict:
    if "error" in result:
        return {"ok": False, "error": result["error"]}
    keys = ("count", "score", "grade", "level", "summary", "enterprise_total", "avg_st_prob", "stock_code")
    summary = {k: result[k] for k in keys if k in result}
    ent = result.get("enterprise")
    if isinstance(ent, dict):
        summary["stock_code"] = ent.get("stock_code")
        summary["enterprise_name"] = ent.get("name")
    if "enterprises" in result:
        summary["enterprises"] = [
            {"name": e.get("name"), "stock_code": e.get("stock_code"), "score": e.get("score") or e.get("st_prob")}
            for e in result["enterprises"][:5]]
    if "dimensions" in result:
        summary["dimensions"] = {k: {"score": v.get("score"), "label": v.get("label")}
                                 for k, v in result["dimensions"].items()}
    if "facts" in result:
        summary["facts"] = [f["text"][:60] for f in result["facts"][:5]]
    if "items" in result and isinstance(result["items"], list):
        summary["alerts"] = [{"id": a.get("id"), "level": a.get("level"), "title": (a.get("title") or "")[:40],
                              "status": a.get("status_label")} for a in result["items"][:5] if isinstance(a, dict)]
    return {"ok": True, **summary}


def _build_messages(session: Session, system_prompt: str = SYSTEM_PROMPT, tool_free: bool = False) -> list[dict]:
    return [{"role": "system", "content": system_prompt}, *store.context(session, tool_free=tool_free)]


def _dump_tool_result(result: dict, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    text = json.dumps(result, ensure_ascii=False)
    if len(text) <= limit:
        return text
    payload = {"truncated": True, "note": f"结果过大（{len(text)} 字符）已截断；如需完整数据请缩小查询范围",
               "summary": _summarize(result)}
    return json.dumps(payload, ensure_ascii=False)[:limit]


def _tool_result_event(session: Session, tc: dict, name: str, result: dict, latency_ms: int) -> AgentEvent:
    store.append(session, {"role": "tool", "tool_call_id": tc.get("id", ""), "tool_name": name,
                           "content": _dump_tool_result(result)})
    return AgentEvent("tool_result", {"id": tc.get("id", ""), "name": name,
                                      "result": _summarize(result), "latency_ms": latency_ms})


def _run_parallel(session: Session, reg, batch: list[tuple[dict, str, dict]]):
    def call_one(name: str, args: dict):
        t = time.perf_counter()
        result = reg.call(name, args)
        return result, int((time.perf_counter() - t) * 1000)

    with ThreadPoolExecutor(max_workers=min(4, len(batch))) as pool:
        futures = {pool.submit(call_one, name, args): (tc, name) for tc, name, args in batch}
        for fut in as_completed(futures):
            tc, name = futures[fut]
            try:
                result, latency_ms = fut.result()
            except Exception as exc:  # noqa: BLE001
                result, latency_ms = {"error": f"{type(exc).__name__}: {exc}"}, 0
            yield _tool_result_event(session, tc, name, result, latency_ms)


def _maybe_compact(session: Session, client: LlmClient, reg, messages: list[dict], force: bool = False) -> Iterator[AgentEvent]:
    if not settings.COMPACTION_ENABLED:
        return
    over, est = context.should_compact(messages, reg.definitions())
    if not (force or over):
        return
    yield AgentEvent("compaction", {"phase": "start", "estimated_tokens": est,
                                    "window": settings.LLM_CONTEXT_WINDOW, "forced": force})
    result = context.compact(session, client, messages, reg.definitions())
    if result:
        store.add_usage(session, result.get("usage") or {})
        yield AgentEvent("compaction", {"phase": "done", "folded": result["folded"],
                                        "summary_chars": len(result["summary"]),
                                        "compact_count": session.compact_count,
                                        "usage": store.usage_stats(session)})
    else:
        yield AgentEvent("compaction", {"phase": "skipped", "reason": "无可折叠历史或摘要失败"})


def run_agent(session: Session, user_text: str, preset_id: int | None = None) -> Iterator[AgentEvent]:
    if not settings.LLM_BASE_URL or not settings.LLM_MODEL:
        yield AgentEvent("error", {"message": "LLM 未配置：请在「设置」中填写 API 地址与模型后重试"})
        return

    store.append(session, {"role": "user", "content": user_text})

    preset: dict | None = None
    system_prompt = SYSTEM_PROMPT
    model_override: str | None = None
    if preset_id:
        from api.services import plugins
        preset_row = plugins.get_preset(preset_id)
        if preset_row is not None:
            preset = {"tools": json.loads(preset_row["tools_json"] or "[]"),
                      "skills": json.loads(preset_row["skills_json"] or "[]")}
            if preset_row["prompt_extra"]:
                system_prompt = f"{SYSTEM_PROMPT}\n\n[当前预设：{preset_row['name']}]\n{preset_row['prompt_extra']}"
            model_override = preset_row["model_override"] or None

    client = _client(model_override)
    reg = _registry_for(preset)

    messages = _build_messages(session, system_prompt)
    for ev in _maybe_compact(session, client, reg, messages):
        yield ev
        messages = _build_messages(session, system_prompt)

    tool_free_retry = False
    for step in range(MAX_STEPS):
        messages = _build_messages(session, system_prompt, tool_free=tool_free_retry)
        text_parts: list[str] = []
        tool_calls: list[dict] | None = None

        while True:
            text_parts, tool_calls = [], None
            try:
                for ev in client.chat_stream(messages, tools=reg.definitions()):
                    if ev["type"] == "text":
                        text_parts.append(ev["text"])
                        yield AgentEvent("token", {"text": ev["text"]})
                    elif ev["type"] == "reasoning":
                        yield AgentEvent("reasoning", {"text": ev["text"]})
                    elif ev["type"] == "tool_calls":
                        tool_calls = ev["tool_calls"]
                if client.last_usage:
                    stats = store.add_usage(session, client.last_usage)
                    yield AgentEvent("usage", {"call": dict(client.last_usage),
                                               "timing": dict(client.last_timing), **stats})
                break
            except Exception as exc:  # noqa: BLE001
                if context.is_tool_sequence_error(exc) and not tool_free_retry:
                    tool_free_retry = True
                    yield AgentEvent("compaction", {"phase": "skipped", "reason": "工具消息序列异常，已改用精简上下文重试"})
                    continue
                if context.is_overflow_error(exc) and settings.COMPACTION_ENABLED:
                    forced = False
                    for ev in _maybe_compact(session, client, reg, messages, force=True):
                        yield ev
                        forced = True
                    if forced:
                        continue
                yield AgentEvent("error", {"message": f"模型调用失败：{exc}"})
                return

        if tool_calls:
            store.append(session, {"role": "assistant", "content": "".join(text_parts), "tool_calls": tool_calls})
            readonly_batch: list[tuple[dict, str, dict]] = []
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                tool = reg.get(name)
                yield AgentEvent("tool", {"id": tc.get("id", ""), "name": name, "args": args,
                                          "read_only": bool(tool and tool.read_only)})

                if tool and not tool.read_only and settings.AGENT_REQUIRE_APPROVAL:
                    pa = approvals.create(session.id, tc.get("id", ""), name, args, tool.description)
                    yield AgentEvent("approval", {"approval_id": pa.id, "id": tc.get("id", ""), "name": name,
                                                  "args": args, "description": tool.description,
                                                  "timeout": settings.AGENT_APPROVAL_TIMEOUT})
                    decided = pa.event.wait(timeout=settings.AGENT_APPROVAL_TIMEOUT)
                    approved = bool(decided and pa.approved)
                    approvals.discard(pa.id)
                    if not approved:
                        rejected = {"error": "用户拒绝执行该操作" if decided else f"等待授权超时（{settings.AGENT_APPROVAL_TIMEOUT}s）"}
                        store.append(session, {"role": "tool", "tool_call_id": tc.get("id", ""),
                                               "tool_name": name, "content": json.dumps(rejected, ensure_ascii=False)})
                        yield AgentEvent("tool_result", {"id": tc.get("id", ""), "name": name,
                                                         "result": {"ok": False, **rejected}})
                        continue

                if tool is not None and not tool.read_only:
                    t_tool = time.perf_counter()
                    result = reg.call(name, args)
                    yield _tool_result_event(session, tc, name, result, int((time.perf_counter() - t_tool) * 1000))
                    continue
                readonly_batch.append((tc, name, args))

            if len(readonly_batch) == 1:
                tc, name, args = readonly_batch[0]
                t_tool = time.perf_counter()
                result = reg.call(name, args)
                yield _tool_result_event(session, tc, name, result, int((time.perf_counter() - t_tool) * 1000))
            elif len(readonly_batch) > 1:
                yield from _run_parallel(session, reg, readonly_batch)
            continue

        final_text = "".join(text_parts)
        store.append(session, {"role": "assistant", "content": final_text})
        yield AgentEvent("done", {"session_id": session.id, "steps": step + 1, "title": session.title,
                                  "usage": store.usage_stats(session)})
        return

    yield AgentEvent("error", {"message": f"达到最大工具调用轮次（{MAX_STEPS}），请换一种问法"})
