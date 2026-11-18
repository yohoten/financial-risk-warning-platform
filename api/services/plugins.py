"""用户手搓插件（声明式 HTTP 工具）与 Agent 预设 + 分享包导入/导出。

移植自旧项目 server/app/services/plugins.py，持久化改为标准库 sqlite3。
"""

from __future__ import annotations

import json
from datetime import datetime

import httpx

from api.db import execute, query

BUILTIN_PRESETS = [
    {
        "name": "通用风险分析师",
        "description": "默认预设：全工具、全技能，平衡型风险分析",
        "prompt_extra": "你以稳健、克制的方式分析风险，结论先行，证据必附来源。",
        "tools_json": "[]",
        "skills_json": "[]",
    },
    {
        "name": "合规审查专员",
        "description": "聚焦法律合规与信用维度，只读工具为主，输出合规风险清单",
        "prompt_extra": "你专注合规视角：优先关注司法、行政、失信与监管问询信号；"
                       "对每个结论标注法规/监管依据来源；不给出投资建议。",
        "tools_json": json.dumps(["search_enterprise", "get_score_profile", "get_risk_facts",
                                  "list_skills", "load_skill", "get_alert_report"]),
        "skills_json": json.dumps(["企业风险评估报告", "预警处置建议"]),
    },
    {
        "name": "投资尽调助手",
        "description": "面向投前尽调：财务+经营+舆情并重，输出要点与风险提示",
        "prompt_extra": "你服务投前尽调：先给结论与关键指标，再给风险清单与需补充材料清单；"
                       "明确区分「事实」与「推断」。",
        "tools_json": json.dumps(["search_enterprise", "get_score_profile", "get_risk_facts",
                                  "list_enterprises_by_level", "get_platform_overview", "list_skills", "load_skill"]),
        "skills_json": json.dumps(["企业风险评估报告", "多企业对比分析", "舆情专项研判"]),
    },
    {
        "name": "财务分析师",
        "description": "聚焦财报：杜邦分解 + Z/F/M 模型 + 同业对标 + 异常勾稽，输出财务分析结论",
        "prompt_extra": "你是财务分析师：所有数字必须来自工具返回的财报指标，并标注年份与单位；"
                       "模型结论要写明阈值与输入完整度（可计算/近似/缺失），缺失即说明缺失，不得推测；"
                       "对异常信号要给出可能原因与需进一步核实的材料清单；不构成投资建议。",
        "tools_json": json.dumps(["search_enterprise", "get_financial_analysis", "compare_financials",
                                  "screen_by_financial_metric", "get_score_profile", "get_risk_facts",
                                  "refresh_enterprise_data", "list_skills", "load_skill"]),
        "skills_json": json.dumps(["财务分析", "多企业对比分析", "企业风险评估报告"]),
    },
]


# ---------------------------------------------------------------------------
# 插件（自定义工具）
# ---------------------------------------------------------------------------

def list_custom_tools() -> dict:
    rows = query("SELECT * FROM custom_tool ORDER BY id")
    return {"total": len(rows), "items": [
        {
            "id": r["id"], "name": r["name"], "description": r["description"],
            "parameters": json.loads(r["parameters_json"] or "{}"),
            "method": r["method"], "url": r["url"],
            "headers": json.loads(r["headers_json"] or "{}"),
            "body_template": r["body_template"],
            "enabled": bool(r["enabled"]), "require_approval": bool(r["require_approval"]),
            "builtin": bool(r["builtin"]),
        }
        for r in rows
    ]}


def create_custom_tool(**fields) -> dict:
    name = (fields.get("name") or "").strip()
    if not name:
        return {"error": "工具名称不能为空"}
    if not (fields.get("url") or "").strip():
        return {"error": "调用地址不能为空"}
    if query("SELECT id FROM custom_tool WHERE name = ?", (name,)):
        return {"error": f"工具已存在：{name}"}
    tool_id = execute(
        "INSERT INTO custom_tool (name, description, parameters_json, method, url, headers_json, body_template, enabled, require_approval) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, fields.get("description") or "",
         json.dumps(fields.get("parameters") or {"type": "object", "properties": {}}, ensure_ascii=False),
         (fields.get("method") or "GET").upper(), fields.get("url") or "",
         json.dumps(fields.get("headers") or {}, ensure_ascii=False),
         fields.get("body_template") or "", int(bool(fields.get("enabled", True))),
         int(bool(fields.get("require_approval", False)))),
    )
    return {"tool_id": tool_id, "name": name}


def update_custom_tool(tool_id: int, **fields) -> dict:
    row = query("SELECT * FROM custom_tool WHERE id = ?", (tool_id,))
    if not row:
        return {"error": f"工具不存在: {tool_id}"}
    r = row[0]
    vals = {
        "name": fields.get("name") or r["name"],
        "description": fields.get("description") if fields.get("description") is not None else r["description"],
        "parameters_json": json.dumps(fields["parameters"], ensure_ascii=False) if fields.get("parameters") is not None else r["parameters_json"],
        "method": fields.get("method", r["method"]).upper(),
        "url": fields.get("url") or r["url"],
        "headers_json": json.dumps(fields["headers"], ensure_ascii=False) if fields.get("headers") is not None else r["headers_json"],
        "body_template": fields.get("body_template") if fields.get("body_template") is not None else r["body_template"],
        "enabled": int(bool(fields["enabled"])) if fields.get("enabled") is not None else r["enabled"],
        "require_approval": int(bool(fields["require_approval"])) if fields.get("require_approval") is not None else r["require_approval"],
    }
    execute("UPDATE custom_tool SET name=?, description=?, parameters_json=?, method=?, url=?, headers_json=?, body_template=?, enabled=?, require_approval=? WHERE id=?",
           (vals["name"], vals["description"], vals["parameters_json"], vals["method"], vals["url"],
            vals["headers_json"], vals["body_template"], vals["enabled"], vals["require_approval"], tool_id))
    return {"ok": True, "tool_id": tool_id}


def delete_custom_tool(tool_id: int) -> dict:
    row = query("SELECT * FROM custom_tool WHERE id = ?", (tool_id,))
    if not row:
        return {"error": f"工具不存在: {tool_id}"}
    if row[0]["builtin"]:
        return {"error": "内置工具不可删除"}
    execute("DELETE FROM custom_tool WHERE id = ?", (tool_id,))
    return {"deleted": tool_id, "name": row[0]["name"]}


def _render(template: str, args: dict) -> str:
    out = template or ""
    for k, v in (args or {}).items():
        out = out.replace("{" + k + "}", str(v))
    return out


def run_custom_tool(row: dict, args: dict) -> dict:
    url = _render(row["url"], args)
    headers = {}
    try:
        headers = json.loads(row["headers_json"] or "{}")
    except ValueError:
        headers = {}
    headers = {k: _render(str(v), args) for k, v in headers.items()}
    body = None
    if row["method"] in ("POST", "PUT", "PATCH"):
        if row["body_template"]:
            rendered = _render(row["body_template"], args)
            try:
                body = json.loads(rendered)
            except ValueError:
                body = rendered
        else:
            body = args
    with httpx.Client(timeout=30) as c:
        resp = c.request(row["method"], url, headers=headers, json=body)
    text = resp.text[:4000]
    if resp.status_code // 100 != 2:
        return {"error": f"HTTP {resp.status_code}: {text[:300]}"}
    try:
        return {"status": resp.status_code, "data": resp.json()}
    except ValueError:
        return {"status": resp.status_code, "text": text}


def enabled_custom_tools() -> list[dict]:
    return query("SELECT * FROM custom_tool WHERE enabled = 1 ORDER BY id")


# ---------------------------------------------------------------------------
# Agent 预设
# ---------------------------------------------------------------------------

def list_presets() -> dict:
    rows = query("SELECT * FROM agent_preset ORDER BY builtin DESC, id")
    return {"total": len(rows), "items": [
        {
            "id": r["id"], "name": r["name"], "description": r["description"],
            "prompt_extra": r["prompt_extra"],
            "tools": json.loads(r["tools_json"] or "[]"),
            "skills": json.loads(r["skills_json"] or "[]"),
            "model_override": r["model_override"],
            "enabled": bool(r["enabled"]), "builtin": bool(r["builtin"]),
        }
        for r in rows
    ]}


def get_preset(preset_id: int | None) -> dict | None:
    if not preset_id:
        return None
    row = query("SELECT * FROM agent_preset WHERE id = ?", (preset_id,))
    if not row or not row[0]["enabled"]:
        return None
    return row[0]


def create_preset(**fields) -> dict:
    name = (fields.get("name") or "").strip()
    if not name:
        return {"error": "预设名称不能为空"}
    if query("SELECT id FROM agent_preset WHERE name = ?", (name,)):
        return {"error": f"预设已存在：{name}"}
    preset_id = execute(
        "INSERT INTO agent_preset (name, description, prompt_extra, tools_json, skills_json, model_override, enabled) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, fields.get("description") or "", fields.get("prompt_extra") or "",
         json.dumps(fields.get("tools") or [], ensure_ascii=False),
         json.dumps(fields.get("skills") or [], ensure_ascii=False),
         fields.get("model_override") or "", int(bool(fields.get("enabled", True)))),
    )
    return {"preset_id": preset_id, "name": name}


def update_preset(preset_id: int, **fields) -> dict:
    row = query("SELECT * FROM agent_preset WHERE id = ?", (preset_id,))
    if not row:
        return {"error": f"预设不存在: {preset_id}"}
    r = row[0]
    vals = {
        "name": fields.get("name") or r["name"],
        "description": fields.get("description") if fields.get("description") is not None else r["description"],
        "prompt_extra": fields.get("prompt_extra") if fields.get("prompt_extra") is not None else r["prompt_extra"],
        "tools_json": json.dumps(fields["tools"], ensure_ascii=False) if fields.get("tools") is not None else r["tools_json"],
        "skills_json": json.dumps(fields["skills"], ensure_ascii=False) if fields.get("skills") is not None else r["skills_json"],
        "model_override": fields.get("model_override") if fields.get("model_override") is not None else r["model_override"],
        "enabled": int(bool(fields["enabled"])) if fields.get("enabled") is not None else r["enabled"],
    }
    execute("UPDATE agent_preset SET name=?, description=?, prompt_extra=?, tools_json=?, skills_json=?, model_override=?, enabled=?, updated_at=datetime('now','localtime') WHERE id=?",
           (vals["name"], vals["description"], vals["prompt_extra"], vals["tools_json"], vals["skills_json"],
            vals["model_override"], vals["enabled"], preset_id))
    return {"ok": True, "preset_id": preset_id}


def delete_preset(preset_id: int) -> dict:
    row = query("SELECT * FROM agent_preset WHERE id = ?", (preset_id,))
    if not row:
        return {"error": f"预设不存在: {preset_id}"}
    if row[0]["builtin"]:
        return {"error": "内置预设不可删除，可停用或另存为新预设"}
    execute("DELETE FROM agent_preset WHERE id = ?", (preset_id,))
    return {"deleted": preset_id, "name": row[0]["name"]}


def seed_builtin_presets() -> int:
    created = 0
    for item in BUILTIN_PRESETS:
        if query("SELECT id FROM agent_preset WHERE name = ?", (item["name"],)):
            continue
        execute("INSERT INTO agent_preset (name, description, prompt_extra, tools_json, skills_json, builtin, enabled) VALUES (?, ?, ?, ?, ?, 1, 1)",
               (item["name"], item["description"], item["prompt_extra"], item["tools_json"], item["skills_json"]))
        created += 1
    return created


# ---------------------------------------------------------------------------
# 导入 / 导出（JSON 分享包）
# ---------------------------------------------------------------------------

BUNDLE_KIND = "risk-warning-agent-bundle"
BUNDLE_VERSION = 1


def _skill_dict(name: str) -> dict | None:
    row = query("SELECT name, description, content FROM skill WHERE name = ?", (name,))
    if not row:
        return None
    r = row[0]
    return {"name": r["name"], "description": r["description"], "content": r["content"]}


def _tool_dict(name: str) -> dict | None:
    raw = name[7:] if name.startswith("custom_") else name
    row = query("SELECT * FROM custom_tool WHERE name = ?", (raw,))
    if not row:
        return None
    r = row[0]
    return {
        "name": r["name"], "description": r["description"],
        "parameters": json.loads(r["parameters_json"] or "{}"),
        "method": r["method"], "url": r["url"],
        "headers": json.loads(r["headers_json"] or "{}"),
        "body_template": r["body_template"], "require_approval": bool(r["require_approval"]),
    }


def list_skills_dict() -> list[dict]:
    rows = query("SELECT name, description, content FROM skill ORDER BY id")
    return [{"name": r["name"], "description": r["description"], "content": r["content"]} for r in rows]


def export_preset(preset_id: int) -> dict:
    preset = next((p for p in list_presets()["items"] if p["id"] == preset_id), None)
    if preset is None:
        return {"error": f"预设不存在: {preset_id}"}
    skills = [s for name in preset.get("skills", []) if (s := _skill_dict(name))]
    tools = [t for name in preset.get("tools", []) if (t := _tool_dict(name))]
    return {
        "kind": BUNDLE_KIND, "version": BUNDLE_VERSION,
        "exported_at": datetime.utcnow().isoformat(),
        "presets": [preset], "skills": skills, "tools": tools,
    }


def export_all() -> dict:
    return {
        "kind": BUNDLE_KIND, "version": BUNDLE_VERSION,
        "exported_at": datetime.utcnow().isoformat(),
        "presets": list_presets()["items"],
        "skills": list_skills_dict(),
        "tools": list_custom_tools()["items"],
    }


def _unique_name(table: str, name: str) -> str:
    base, i = name, 1
    while query(f"SELECT id FROM {table} WHERE name = ?", (name,)):
        i += 1
        name = f"{base}（导入{i}）"
    return name


def import_bundle(data: dict, strategy: str = "rename") -> dict:
    if not isinstance(data, dict) or data.get("kind") != BUNDLE_KIND:
        return {"error": f"不是有效的分享包（kind 应为 {BUNDLE_KIND}）"}
    if int(data.get("version") or 0) > BUNDLE_VERSION:
        return {"error": f"分享包版本过新（{data.get('version')} > {BUNDLE_VERSION}），请升级平台"}

    result = {"tools": [], "skills": [], "presets": [], "skipped": [], "strategy": strategy}

    # 1) 插件
    for t in data.get("tools") or []:
        name = (t.get("name") or "").strip()
        if not name:
            continue
        existing = query("SELECT * FROM custom_tool WHERE name = ?", (name,))
        if existing and existing[0]["url"] == (t.get("url") or "") and existing[0]["method"] == (t.get("method") or "GET").upper():
            result["tools"].append(f"{name}（已存在，复用）")
            continue
        if existing and strategy == "skip":
            result["skipped"].append(f"插件 {name}")
            continue
        final = _unique_name("custom_tool", name) if (existing and strategy == "rename") else name
        if existing:
            update_custom_tool(existing[0]["id"], name=final, description=t.get("description"),
                               parameters=t.get("parameters"), method=t.get("method"), url=t.get("url"),
                               headers=t.get("headers"), body_template=t.get("body_template"),
                               require_approval=t.get("require_approval"))
            result["tools"].append(f"{name}（覆盖）")
        else:
            create_custom_tool(name=final, description=t.get("description"), parameters=t.get("parameters"),
                               method=t.get("method"), url=t.get("url"), headers=t.get("headers"),
                               body_template=t.get("body_template"), require_approval=t.get("require_approval"))
            result["tools"].append(final)

    # 2) 技能
    for s in data.get("skills") or []:
        name = (s.get("name") or "").strip()
        if not name or not (s.get("content") or "").strip():
            continue
        existing = query("SELECT * FROM skill WHERE name = ?", (name,))
        if existing and (existing[0]["content"] or "").strip() == (s.get("content") or "").strip():
            result["skills"].append(f"{name}（已存在，复用）")
            continue
        if existing and strategy == "skip":
            result["skipped"].append(f"技能 {name}")
            continue
        final = _unique_name("skill", name) if (existing and strategy == "rename") else name
        if existing:
            execute("UPDATE skill SET description = ?, content = ? WHERE id = ?",
                   (s.get("description") or existing[0]["description"], s.get("content") or existing[0]["content"], existing[0]["id"]))
            result["skills"].append(f"{name}（覆盖）")
        else:
            execute("INSERT INTO skill (name, description, content) VALUES (?, ?, ?)",
                   (final, s.get("description") or "", s.get("content") or ""))
            result["skills"].append(final)

    # 3) 预设
    for p in data.get("presets") or []:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        existing = query("SELECT * FROM agent_preset WHERE name = ?", (name,))
        if existing and strategy == "skip":
            result["skipped"].append(f"预设 {name}")
            continue
        final = _unique_name("agent_preset", name) if (existing and strategy == "rename") else name
        if existing:
            update_preset(existing[0]["id"], name=final, description=p.get("description"),
                          prompt_extra=p.get("prompt_extra"), tools=p.get("tools"), skills=p.get("skills"),
                          model_override=p.get("model_override"))
            result["presets"].append(f"{name}（覆盖）")
        else:
            create_preset(name=final, description=p.get("description"), prompt_extra=p.get("prompt_extra"),
                          tools=p.get("tools"), skills=p.get("skills"), model_override=p.get("model_override"))
            result["presets"].append(final)

    return result
