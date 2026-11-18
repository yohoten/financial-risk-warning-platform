"""MCP 服务管理：注册 / 测试 / 同步工具 / 供 Agent 使用（sqlite3）。"""

from __future__ import annotations

import json

from api.db import execute, query
from api.mcp.client import McpClient, McpTool


def _now() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat()


def list_servers() -> dict:
    rows = query("SELECT * FROM mcp_server ORDER BY id")
    return {"total": len(rows), "items": [
        {"id": r["id"], "name": r["name"], "url": r["url"], "enabled": bool(r["enabled"]),
         "require_approval": bool(r["require_approval"]), "status": r["status"],
         "status_detail": r["status_detail"], "tool_count": r["tool_count"],
         "tools": json.loads(r["tools_json"] or "[]"), "synced_at": r["synced_at"] or None}
        for r in rows
    ]}


def add_server(name: str, url: str, auth_header: str = "", require_approval: bool = False) -> dict:
    name = (name or "").strip()
    url = (url or "").strip()
    if not name or not url:
        return {"error": "名称与地址不能为空"}
    if query("SELECT id FROM mcp_server WHERE name = ?", (name,)):
        return {"error": f"MCP 服务已存在：{name}"}
    server_id = execute("INSERT INTO mcp_server (name, url, auth_header, require_approval) VALUES (?, ?, ?, ?)",
                       (name, url, auth_header, int(bool(require_approval))))
    result = sync_tools(server_id)
    return {"server_id": server_id, "name": name, **result}


def update_server(server_id: int, **fields) -> dict:
    row = query("SELECT * FROM mcp_server WHERE id = ?", (server_id,))
    if not row:
        return {"error": f"MCP 服务不存在: {server_id}"}
    r = row[0]
    vals = {
        "name": fields.get("name") or r["name"],
        "url": fields.get("url") or r["url"],
        "auth_header": fields.get("auth_header") if fields.get("auth_header") is not None else r["auth_header"],
        "enabled": int(bool(fields["enabled"])) if fields.get("enabled") is not None else r["enabled"],
        "require_approval": int(bool(fields["require_approval"])) if fields.get("require_approval") is not None else r["require_approval"],
    }
    execute("UPDATE mcp_server SET name=?, url=?, auth_header=?, enabled=?, require_approval=? WHERE id=?",
           (vals["name"], vals["url"], vals["auth_header"], vals["enabled"], vals["require_approval"], server_id))
    return {"ok": True, "server_id": server_id}


def delete_server(server_id: int) -> dict:
    row = query("SELECT name FROM mcp_server WHERE id = ?", (server_id,))
    if not row:
        return {"error": f"MCP 服务不存在: {server_id}"}
    execute("DELETE FROM mcp_server WHERE id = ?", (server_id,))
    return {"deleted": server_id, "name": row[0]["name"]}


def test_server(server_id: int) -> dict:
    row = query("SELECT * FROM mcp_server WHERE id = ?", (server_id,))
    if not row:
        return {"error": f"MCP 服务不存在: {server_id}"}
    r = row[0]
    try:
        client = McpClient(r["url"], r["auth_header"])
        info = client.initialize()
        tools = client.list_tools()
        execute("UPDATE mcp_server SET status='ok', status_detail=? WHERE id=?", (f"初始化成功，发现 {len(tools)} 个工具", server_id))
        return {"ok": True, "server": r["name"], "info": info, "tools": [t.name for t in tools]}
    except Exception as exc:  # noqa: BLE001
        execute("UPDATE mcp_server SET status='error', status_detail=? WHERE id=?", (f"{type(exc).__name__}: {exc}", server_id))
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def sync_tools(server_id: int) -> dict:
    row = query("SELECT * FROM mcp_server WHERE id = ?", (server_id,))
    if not row:
        return {"error": f"MCP 服务不存在: {server_id}"}
    r = row[0]
    try:
        client = McpClient(r["url"], r["auth_header"])
        tools = client.list_tools()
    except Exception as exc:  # noqa: BLE001
        execute("UPDATE mcp_server SET status='error', status_detail=? WHERE id=?", (f"{type(exc).__name__}: {exc}", server_id))
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    execute("UPDATE mcp_server SET tools_json=?, tool_count=?, status='ok', status_detail=?, synced_at=? WHERE id=?",
           (json.dumps([{"name": t.name, "description": t.description, "inputSchema": t.input_schema} for t in tools], ensure_ascii=False),
            len(tools), f"同步成功：{len(tools)} 个工具", _now(), server_id))
    return {"ok": True, "tool_count": len(tools), "tools": [t.name for t in tools]}


def enabled_tools(prefix: str = "mcp_") -> list[dict]:
    out = []
    for r in query("SELECT * FROM mcp_server WHERE enabled = 1"):
        try:
            raw = json.loads(r["tools_json"] or "[]")
        except ValueError:
            raw = []
        for t in raw:
            name = t.get("name")
            if not name:
                continue
            out.append({
                "server_id": r["id"], "server_name": r["name"], "server_url": r["url"],
                "auth_header": r["auth_header"], "require_approval": bool(r["require_approval"]),
                "tool": McpTool(name=name, description=t.get("description") or "",
                                input_schema=t.get("inputSchema") or {"type": "object", "properties": {}}),
                "openai_name": f"{prefix}{r['id']}_{name}"[:64],
            })
    return out
