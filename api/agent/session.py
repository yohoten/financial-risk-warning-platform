"""会话管理（sqlite3 持久化 + 上下文压缩 + 用量统计）。"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from api.db import execute, query

WINDOW = 12
MAX_TITLE_LEN = 24


@dataclass
class Session:
    id: str
    title: str = "新对话"
    messages: list[dict] = field(default_factory=list)
    summary: str = ""
    compacted_until: int = 0
    compact_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    llm_calls: int = 0
    est_cost: float = 0.0


def _now() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat()


def _missing_tool_result(tool_call_id: str) -> dict:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps({"error": "工具结果缺失（会话中断或已被裁剪），请重新调用该工具获取数据"}, ensure_ascii=False),
    }


def sanitize_tool_pairs(messages: list[dict]) -> list[dict]:
    """把消息序列整理成提供方要求的合法形态（孤立 tool 丢弃、缺失结果补齐）。"""
    out: list[dict] = []
    pending: set[str] = set()

    def flush_pending() -> None:
        for tcid in list(pending):
            out.append(_missing_tool_result(tcid))
        pending.clear()

    for m in messages:
        role = m.get("role")
        if role == "tool":
            tcid = m.get("tool_call_id") or ""
            if tcid in pending:
                out.append(m)
                pending.discard(tcid)
            continue
        if role == "assistant" and m.get("tool_calls"):
            flush_pending()
            out.append(m)
            for tc in m["tool_calls"]:
                tcid = tc.get("id") or ""
                if tcid:
                    pending.add(tcid)
            continue
        flush_pending()
        out.append(m)
    flush_pending()
    return out


class SessionStore:
    def create(self, title: str = "新对话") -> Session:
        sid = uuid.uuid4().hex[:12]
        execute("INSERT INTO chat_session (id, title) VALUES (?, ?)", (sid, title))
        return Session(id=sid, title=title, created_at=_now(), updated_at=_now())

    def get(self, session_id: str) -> Session | None:
        rows = query("SELECT * FROM chat_session WHERE id = ?", (session_id,))
        if not rows:
            return None
        r = rows[0]
        session = Session(
            id=r["id"], title=r["title"], summary=r["summary"] or "",
            compacted_until=r["compacted_until"] or 0, compact_count=r["compact_count"] or 0,
            created_at=r["created_at"], updated_at=r["updated_at"],
            prompt_tokens=r["prompt_tokens"] or 0, completion_tokens=r["completion_tokens"] or 0,
            cache_hit_tokens=r["cache_hit_tokens"] or 0, cache_miss_tokens=r["cache_miss_tokens"] or 0,
            llm_calls=r["llm_calls"] or 0, est_cost=r["est_cost"] or 0.0,
        )
        for m in query("SELECT * FROM chat_message WHERE session_id = ? ORDER BY id", (session_id,)):
            item: dict = {"id": m["id"], "role": m["role"], "content": m["content"]}
            if m["tool_calls_json"]:
                try:
                    item["tool_calls"] = json.loads(m["tool_calls_json"])
                except ValueError:
                    item["tool_calls"] = []
            if m["tool_call_id"]:
                item["tool_call_id"] = m["tool_call_id"]
            if m["tool_name"]:
                item["tool_name"] = m["tool_name"]
            session.messages.append(item)
        return session

    def get_or_create(self, session_id: str | None) -> Session:
        if session_id:
            existing = self.get(session_id)
            if existing is not None:
                return existing
        return self.create()

    def append(self, session: Session, message: dict) -> dict:
        now = _now()
        session.updated_at = now
        row_id = execute(
            "INSERT INTO chat_message (session_id, role, content, tool_calls_json, tool_call_id, tool_name, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session.id, message.get("role", ""), message.get("content") or "",
             json.dumps(message["tool_calls"], ensure_ascii=False) if message.get("tool_calls") else "",
             message.get("tool_call_id", ""), message.get("tool_name", ""), now),
        )
        message["id"] = row_id
        session.messages.append(message)

        parent = query("SELECT title FROM chat_session WHERE id = ?", (session.id,))
        if parent and parent[0]["title"] in ("", "新对话") and message.get("role") == "user":
            text = (message.get("content") or "").strip().replace("\n", " ")
            if text:
                title = text[:MAX_TITLE_LEN] + ("…" if len(text) > MAX_TITLE_LEN else "")
                execute("UPDATE chat_session SET title = ?, updated_at = ? WHERE id = ?", (title, now, session.id))
                session.title = title
        else:
            execute("UPDATE chat_session SET updated_at = ? WHERE id = ?", (now, session.id))
        return message

    def context(self, session: Session, tool_free: bool = False) -> list[dict]:
        out: list[dict] = []
        if session.summary:
            out.append({"role": "system", "content": "[会话摘要（更早的对话已压缩，视为已知信息）]\n" + session.summary})
        recent = [m for m in session.messages if (m.get("id") or 0) > session.compacted_until]
        if tool_free:
            recent = [m for m in recent if m.get("role") in ("user", "system")
                      or (m.get("role") == "assistant" and not m.get("tool_calls"))]
        else:
            recent = sanitize_tool_pairs(recent[-WINDOW:])
        for m in recent:
            item = {"role": m.get("role"), "content": m.get("content") or ""}
            if m.get("tool_calls"):
                item["tool_calls"] = m["tool_calls"]
            if m.get("tool_call_id"):
                item["tool_call_id"] = m["tool_call_id"]
            out.append(item)
        return out

    def set_summary(self, session: Session, summary: str, until_id: int) -> None:
        session.summary = summary
        session.compacted_until = until_id
        session.compact_count += 1
        execute("UPDATE chat_session SET summary = ?, compacted_until = ?, compact_count = ? WHERE id = ?",
               (summary, until_id, session.compact_count, session.id))

    def add_usage(self, session: Session, usage: dict) -> dict:
        hit = int(usage.get("cache_hit_tokens", 0) or 0)
        miss = int(usage.get("cache_miss_tokens", 0) or 0)
        prompt = int(usage.get("prompt_tokens", 0) or 0)
        output = int(usage.get("completion_tokens", 0) or 0)
        if prompt and not (hit or miss):
            miss = prompt
        session.prompt_tokens += prompt
        session.completion_tokens += output
        session.cache_hit_tokens += hit
        session.cache_miss_tokens += miss
        session.llm_calls += 1
        execute("UPDATE chat_session SET prompt_tokens = ?, completion_tokens = ?, cache_hit_tokens = ?, cache_miss_tokens = ?, llm_calls = ? WHERE id = ?",
               (session.prompt_tokens, session.completion_tokens, session.cache_hit_tokens,
                session.cache_miss_tokens, session.llm_calls, session.id))
        return self.usage_stats(session)

    @staticmethod
    def usage_stats(session: Session) -> dict:
        total_cache = session.cache_hit_tokens + session.cache_miss_tokens
        hit_rate = round(session.cache_hit_tokens / total_cache, 4) if total_cache else 0.0
        return {
            "llm_calls": session.llm_calls, "prompt_tokens": session.prompt_tokens,
            "completion_tokens": session.completion_tokens, "cache_hit_tokens": session.cache_hit_tokens,
            "cache_miss_tokens": session.cache_miss_tokens, "cache_hit_rate": hit_rate,
            "compact_count": session.compact_count,
        }

    def list_sessions(self, limit: int = 50, q: str = "") -> list[dict]:
        sql = "SELECT * FROM chat_session"
        params: tuple = ()
        if q:
            like = f"%{q}%"
            matched = [r["session_id"] for r in query("SELECT DISTINCT session_id FROM chat_message WHERE content LIKE ?", (like,))]
            ids = ",".join("?" for _ in (matched or [""]))
            sql += f" WHERE title LIKE ? OR id IN ({ids})"
            params = (like, *matched) if matched else (like, "")
        sql += " ORDER BY pinned DESC, updated_at DESC LIMIT ?"
        params = (*params, limit)
        rows = query(sql, params)
        out = []
        for r in rows:
            count = query("SELECT COUNT(*) AS n FROM chat_message WHERE session_id = ?", (r["id"],))[0]["n"]
            total_cache = (r["cache_hit_tokens"] or 0) + (r["cache_miss_tokens"] or 0)
            out.append({
                "id": r["id"], "title": r["title"], "pinned": bool(r["pinned"]),
                "updated_at": r["updated_at"], "created_at": r["created_at"],
                "message_count": count,
                "cache_hit_rate": round((r["cache_hit_tokens"] or 0) / total_cache, 4) if total_cache else 0.0,
                "shared": bool(r["share_token"]),
            })
        return out

    def rename(self, session_id: str, title: str) -> dict:
        row = query("SELECT id FROM chat_session WHERE id = ?", (session_id,))
        if not row:
            return {"error": f"会话不存在: {session_id}"}
        title = (title or "").strip()[:120] or "新对话"
        execute("UPDATE chat_session SET title = ?, updated_at = ? WHERE id = ?", (title, _now(), session_id))
        return {"ok": True, "id": session_id, "title": title}

    def set_pinned(self, session_id: str, pinned: bool) -> dict:
        row = query("SELECT id FROM chat_session WHERE id = ?", (session_id,))
        if not row:
            return {"error": f"会话不存在: {session_id}"}
        execute("UPDATE chat_session SET pinned = ? WHERE id = ?", (int(bool(pinned)), session_id))
        return {"ok": True, "id": session_id, "pinned": bool(pinned)}

    def clear_messages(self, session_id: str) -> dict:
        row = query("SELECT id FROM chat_session WHERE id = ?", (session_id,))
        if not row:
            return {"error": f"会话不存在: {session_id}"}
        execute("DELETE FROM chat_message WHERE session_id = ?", (session_id,))
        execute("UPDATE chat_session SET summary = '', compacted_until = 0, compact_count = 0, updated_at = ? WHERE id = ?",
               (_now(), session_id))
        return {"ok": True}

    def batch_delete(self, ids: list[str]) -> dict:
        deleted = 0
        for sid in ids or []:
            if self.delete(sid):
                deleted += 1
        return {"deleted": deleted}

    def share(self, session_id: str) -> dict:
        row = query("SELECT * FROM chat_session WHERE id = ?", (session_id,))
        if not row:
            return {"error": f"会话不存在: {session_id}"}
        token = row[0]["share_token"] or uuid.uuid4().hex[:20]
        execute("UPDATE chat_session SET share_token = ?, share_created_at = ? WHERE id = ?", (token, _now(), session_id))
        return {"ok": True, "session_id": session_id, "token": token, "url": f"/share/{token}"}

    def revoke_share(self, session_id: str) -> dict:
        row = query("SELECT id FROM chat_session WHERE id = ?", (session_id,))
        if not row:
            return {"error": f"会话不存在: {session_id}"}
        execute("UPDATE chat_session SET share_token = '', share_created_at = '' WHERE id = ?", (session_id,))
        return {"ok": True, "session_id": session_id}

    def get_shared(self, token: str) -> dict | None:
        row = query("SELECT * FROM chat_session WHERE share_token = ?", (token,))
        if not row:
            return None
        session = self.get(row[0]["id"])
        if session is None:
            return None
        return {
            "session_id": session.id, "title": session.title,
            "created_at": session.created_at, "updated_at": session.updated_at,
            "usage": self.usage_stats(session),
            "messages": [
                {"role": m.get("role"), "content": m.get("content") or "",
                 "tool_calls": m.get("tool_calls") or [], "tool_name": m.get("tool_name", "")}
                for m in session.messages if m.get("role") in ("user", "assistant", "tool")
            ],
        }

    def export_markdown(self, session_id: str) -> str:
        s = self.get(session_id)
        if s is None:
            return ""
        stats = self.usage_stats(s)
        lines = [f"# {s.title}", "", f"- 会话 ID：`{s.id}`", f"- 创建时间：{s.created_at}",
                 f"- 最后更新：{s.updated_at}",
                 f"- LLM 调用：{stats['llm_calls']} 次 · 输入 {stats['prompt_tokens']} tok（缓存命中 {stats['cache_hit_tokens']}）· 输出 {stats['completion_tokens']} tok",
                 "", "---", ""]
        tool_names: dict[str, str] = {}
        for m in s.messages:
            for tc in m.get("tool_calls") or []:
                if tc.get("id"):
                    tool_names[tc["id"]] = (tc.get("function") or {}).get("name", "")
        for m in s.messages:
            role, content = m.get("role"), (m.get("content") or "").strip()
            if role == "user":
                lines += ["## 🧑 用户", "", content, ""]
            elif role == "assistant":
                if content:
                    lines += ["## 🤖 助手", "", content, ""]
                for tc in m.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    lines += [f"> 🔧 调用工具 `{fn.get('name')}`：`{fn.get('arguments', '')}`", ""]
            elif role == "tool":
                name = m.get("tool_name") or tool_names.get(m.get("tool_call_id", ""), "tool")
                snippet = content[:400].replace("\n", " ")
                lines += [f"> ↩️ `{name}` 返回：{snippet}{'…' if len(content) > 400 else ''}", ""]
        lines += ["---", "", "> 由「财务风险智能预警平台」导出；数据来自公开信源，不构成投资建议。"]
        return "\n".join(lines)

    def export_json(self, session_id: str) -> dict:
        s = self.get(session_id)
        if s is None:
            return {}
        return {
            "kind": "risk-warning-chat-session", "version": 1, "exported_at": _now(), "title": s.title,
            "usage": self.usage_stats(s),
            "messages": [
                {"role": m.get("role"), "content": m.get("content") or "",
                 "tool_calls": m.get("tool_calls") or [], "tool_call_id": m.get("tool_call_id", ""),
                 "tool_name": m.get("tool_name", "")}
                for m in s.messages
            ],
        }

    def import_session(self, data: dict) -> dict:
        if not isinstance(data, dict) or data.get("kind") != "risk-warning-chat-session":
            return {"error": "不是有效的会话导出文件（kind 应为 risk-warning-chat-session）"}
        title = (data.get("title") or "导入的对话")[:120]
        if query("SELECT id FROM chat_session WHERE title = ?", (title,)):
            title = f"{title}（导入）"
        session = self.create(title)
        for m in data.get("messages") or []:
            if m.get("role") not in ("user", "assistant", "tool"):
                continue
            self.append(session, {
                "role": m["role"], "content": m.get("content") or "",
                "tool_calls": m.get("tool_calls") or None, "tool_call_id": m.get("tool_call_id", ""),
                "tool_name": m.get("tool_name", ""),
            })
        return {"ok": True, "session_id": session.id, "title": title, "messages": len(session.messages)}

    def delete(self, session_id: str) -> bool:
        row = query("SELECT id FROM chat_session WHERE id = ?", (session_id,))
        if not row:
            return False
        execute("DELETE FROM chat_message WHERE session_id = ?", (session_id,))
        execute("DELETE FROM chat_session WHERE id = ?", (session_id,))
        return True


store = SessionStore()
