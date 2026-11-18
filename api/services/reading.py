"""多模态读取：视觉抽取 → 结构化 Reading → 识图填表（source=vision 待确认）。"""

from __future__ import annotations

import base64
import json
import re

from config import settings
from api.services import attachments
from api.services.llm import LlmClient, LlmConfig
from api.services.tables import get as get_table, _persist, match_field

VISION_SYSTEM = (
    "你是财务报表识图引擎。从用户提供的图片中抽取财务科目数值，"
    "输出严格 JSON：{\"items\":[{\"label\":\"科目名称（原样）\",\"value\":数字}]}，"
    "只输出图片中确实出现的数字，不要猜测；无法辨认的科目不要输出。"
)


def _extract_json(text: str) -> dict | None:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text or "", re.S)
    if m:
        text = m.group(1)
    s, e = (text or "").find("{"), (text or "").rfind("}")
    if s == -1 or e <= s:
        return None
    try:
        obj = json.loads(text[s:e + 1])
        return obj if isinstance(obj, dict) else None
    except ValueError:
        return None


def _llm_configured() -> bool:
    return bool(settings.LLM_BASE_URL and settings.LLM_MODEL)


def read_attachment(attachment_id: str, target: str = "auto", table_id: int | None = None,
                    dry_run: bool = False) -> dict:
    att = attachments.get(attachment_id)
    if att is None:
        return {"error": f"附件不存在: {attachment_id}"}
    if not _llm_configured():
        return {"error": "LLM 未配置：识图需要多模态模型（请在「设置」中填写 API 地址与模型）"}

    data = attachments.read_bytes(attachment_id)
    mime = att["mime"]
    b64 = base64.b64encode(data).decode()
    content = [{"type": "text", "text": "请识别图片中的财务科目与数值。"},
               {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]
    client = LlmClient(LlmConfig(base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY,
                                 model=settings.LLM_MODEL, max_tokens=settings.LLM_ANALYSIS_MAX_TOKENS,
                                 timeout_s=settings.LLM_TIMEOUT_S))
    msg = client.chat([{"role": "system", "content": VISION_SYSTEM},
                       {"role": "user", "content": content}])
    obj = _extract_json(msg.get("content") or "")

    items = obj.get("items", []) if obj else []
    fields = []
    for it in items:
        if not isinstance(it, dict):
            continue
        label = str(it.get("label", "")).strip()
        val = it.get("value")
        field = match_field(label)
        if field and isinstance(val, (int, float)):
            fields.append({"field": field, "label": label, "value": float(val), "confidence": 0.8})

    reading = {"target": target, "fields": fields, "raw": (msg.get("content") or "")[:2000]}
    attachments.set_reading(attachment_id, reading)

    filled = 0
    if table_id and not dry_run and fields:
        doc = get_table(table_id)
        if doc is not None:
            for f in fields:
                rk = doc["mapping"].get(f["field"])
                if not rk:
                    rk = f"r{len(doc['sheet'].get('rows', [])) + 1}"
                    doc["sheet"].setdefault("rows", []).append(
                        {"key": rk, "label": f["label"], "field": f["field"], "cells": {}})
                    doc["mapping"][f["field"]] = rk
                # 写入第一个期间列
                cols = doc["sheet"].get("columns", [])
                if not cols:
                    cols = [{"key": "c1", "label": "识别期", "period": "", "report_type": "", "type": "number"}]
                    doc["sheet"]["columns"] = cols
                for row in doc["sheet"]["rows"]:
                    if row.get("key") == rk:
                        row.setdefault("cells", {})["c1"] = {"value": f["value"], "source": "vision", "confidence": 0.8}
                filled += 1
            _persist(doc, True)

    return {"attachment_id": attachment_id, "target": target, "dry_run": dry_run,
            "count": len(fields), "fields": fields, "filled": filled,
            "note": "识图结果 source=vision，需人工确认识别结果后方可入库" if filled else ""}
