"""运行时设置：DB 覆盖 + 前端展示元数据（移植自旧项目，适配模块级 settings）。

- 默认值来自 ``config.settings`` 模块级常量
- 用户在设置面板修改后写入 ``app_setting`` 表，并立即 setattr 覆盖 settings 字段
- 敏感字段（API Key）只回显掩码，不回传明文
"""

from __future__ import annotations

import json

from config import settings
from api.db import execute, query

MASK_CHAR = "•"

# 可编辑字段元数据：分组 → [字段]
FIELDS: dict[str, list[dict]] = {
    "模型服务": [
        {"key": "LLM_BASE_URL", "label": "API 地址", "type": "text", "desc": "OpenAI 兼容端点；选择提供商后自动填入"},
        {"key": "LLM_API_KEY", "label": "API Key", "type": "password", "desc": "仅保存在本地，不会回传明文"},
        {"key": "LLM_MODEL", "label": "模型名称", "type": "text", "desc": "点击「获取可用模型」后从列表选择"},
        {"key": "LLM_MAX_TOKENS", "label": "单次输出上限", "type": "int", "desc": "普通对话的 max_tokens"},
        {"key": "LLM_ANALYSIS_MAX_TOKENS", "label": "研判输出上限", "type": "int", "desc": "风险研判（需输出完整 JSON）的 max_tokens"},
        {"key": "LLM_DISABLE_THINKING", "label": "关闭模型思考", "type": "bool", "desc": "推理型模型先输出思考内容，关闭后响应更快"},
    ],
    "上下文与压缩": [
        {"key": "LLM_CONTEXT_WINDOW", "label": "上下文窗口", "type": "int", "desc": "模型窗口 token 数，压缩阈值按它缩放"},
        {"key": "COMPACTION_ENABLED", "label": "启用自动压缩", "type": "bool", "desc": "上下文接近上限时把历史折叠为摘要"},
        {"key": "COMPACTION_THRESHOLD_RATIO", "label": "压缩触发比例", "type": "float", "desc": "用量 ≥ 窗口 × 该比例时触发（默认 0.8）"},
        {"key": "COMPACTION_RETAIN_RATIO", "label": "压缩保留比例", "type": "float", "desc": "压缩后保留最近的比例（默认 0.16）"},
        {"key": "COMPACTION_SUMMARY_MAX_TOKENS", "label": "摘要输出上限", "type": "int", "desc": "生成摘要的 max_tokens"},
    ],
    "动作审批": [
        {"key": "AGENT_REQUIRE_APPROVAL", "label": "动作工具需授权", "type": "bool", "desc": "写操作（刷新/研判/处置）执行前需用户确认"},
        {"key": "AGENT_APPROVAL_TIMEOUT", "label": "授权超时(秒)", "type": "int", "desc": "超时视为拒绝"},
    ],
}

# 提供商预设
PROVIDERS: list[dict] = [
    {"id": "deepseek", "label": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "default_model": "deepseek-chat", "key_hint": "sk-..."},
    {"id": "openai", "label": "OpenAI", "base_url": "https://api.openai.com/v1", "default_model": "gpt-4o-mini", "key_hint": "sk-..."},
    {"id": "dashscope", "label": "阿里云百炼（通义千问）", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen-plus", "key_hint": "sk-..."},
    {"id": "zhipu", "label": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4", "default_model": "glm-4-plus", "key_hint": "..."},
    {"id": "siliconflow", "label": "硅基流动 SiliconFlow", "base_url": "https://api.siliconflow.cn/v1", "default_model": "deepseek-ai/DeepSeek-V3", "key_hint": "sk-..."},
    {"id": "ollama", "label": "本地 Ollama", "base_url": "http://127.0.0.1:11434/v1", "default_model": "qwen2.5:7b", "key_hint": "可留空", "key_optional": True},
    {"id": "custom", "label": "其他（自定义 OpenAI 兼容端点）", "base_url": "", "default_model": "", "key_hint": "按需填写"},
]


def _mask(value: str) -> str:
    if not value:
        return ""
    return value[:6] + MASK_CHAR * 6 + value[-4:] if len(value) > 12 else MASK_CHAR * 8


def get_view() -> dict:
    groups = []
    for group, fields in FIELDS.items():
        items = []
        for f in fields:
            raw = getattr(settings, f["key"], None)
            if f["type"] == "password":
                items.append({**f, "value": _mask(str(raw or "")), "has_value": bool(raw)})
            else:
                items.append({**f, "value": raw})
        groups.append({"group": group, "items": items})
    return {
        "groups": groups,
        "providers": PROVIDERS,
        "runtime": {
            "model": settings.LLM_MODEL,
            "base_url": settings.LLM_BASE_URL,
            "context_window": settings.LLM_CONTEXT_WINDOW,
            "compaction_enabled": settings.COMPACTION_ENABLED,
            "require_approval": settings.AGENT_REQUIRE_APPROVAL,
            "has_api_key": bool(settings.LLM_API_KEY),
        },
    }


def list_models(base_url: str, api_key: str | None = None) -> dict:
    """拉取提供商可用模型列表（OpenAI 兼容 /models）。"""
    import httpx

    url = (base_url or "").rstrip("/")
    if not url:
        return {"error": "请先选择提供商或填写 API 地址", "models": []}
    if not url.endswith("/v1") and "/v1" not in url:
        url = url + "/v1"
    key = (api_key or "").strip()
    if not key or MASK_CHAR in key:
        key = (settings.LLM_API_KEY or "").strip()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        with httpx.Client(timeout=30) as c:
            resp = c.get(url + "/models", headers=headers)
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}", "models": []}
        data = resp.json()
        items = data.get("data") or data.get("models") or []
        models = []
        for m in items:
            if isinstance(m, dict):
                mid = m.get("id") or m.get("name") or m.get("model")
            else:
                mid = str(m)
            if mid:
                models.append(mid)
        return {"models": sorted(set(models)), "count": len(models)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}", "models": []}


def _coerce(field: dict, value):
    t = field["type"]
    if t == "bool":
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("1", "true", "yes", "on")
    if t == "int":
        return int(value)
    if t == "float":
        return float(value)
    return str(value)


def _is_password_unchanged(field: dict, value) -> bool:
    return field["type"] == "password" and (not value or MASK_CHAR in str(value))


def update(payload: dict) -> dict:
    """保存并立即生效。payload: {field_key: value}"""
    applied, errors = {}, []
    for _group, fields in FIELDS.items():
        for f in fields:
            key = f["key"]
            if key not in payload:
                continue
            value = payload[key]
            if _is_password_unchanged(f, value):
                continue
            try:
                coerced = _coerce(f, value)
            except (TypeError, ValueError) as exc:
                errors.append(f"{f['label']}: {exc}")
                continue
            existing = query("SELECT key FROM app_setting WHERE key = ?", (key,))
            if existing:
                execute("UPDATE app_setting SET value = ?, updated_at = datetime('now','localtime') WHERE key = ?",
                       (json.dumps(coerced, ensure_ascii=False), key))
            else:
                execute("INSERT INTO app_setting (key, value) VALUES (?, ?)",
                       (key, json.dumps(coerced, ensure_ascii=False)))
            applied[key] = coerced

    for key, value in applied.items():
        try:
            setattr(settings, key, value)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{key}: 应用失败 {exc}")

    # 切换模型/端点后触发预热（若预热模块已加载）
    if any(k in applied for k in ("LLM_MODEL", "LLM_BASE_URL", "PREHEAT_ENABLED")):
        try:
            from api.llm.preheat import warmer  # noqa: F401
            if settings.PREHEAT_ENABLED:
                from api.agent.prompt import SYSTEM_PROMPT
                from api.agent.tools import build_registry
                warmer.warm_async(SYSTEM_PROMPT, build_registry().definitions(), label="settings", force=True)
        except Exception:  # noqa: BLE001
            pass

    return {"applied": applied, "errors": errors}


def load_and_apply() -> dict:
    """启动时把 DB 中的覆盖值应用回 settings。"""
    applied = {}
    allowed = {f["key"] for _g, fields in FIELDS.items() for f in fields}
    for row in query("SELECT key, value FROM app_setting"):
        key, raw = row["key"], row["value"]
        if key not in allowed:
            continue
        try:
            setattr(settings, key, json.loads(raw))
            applied[key] = getattr(settings, key)
        except Exception:  # noqa: BLE001
            pass
    return applied


def reset() -> dict:
    execute("DELETE FROM app_setting")
    return {"reset": True, "note": "已清除覆盖值，重启后端后完全恢复默认配置"}
