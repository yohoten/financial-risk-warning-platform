"""预警中心（移植自旧项目 server/app/services/alerts.py）。

闭环：规则评分触发预警 → 人工处置（待处理→处理中→已处置/已忽略）→ 处理流水留痕。
持久化：SQLite（``cache/alerts.db``），与数据资产同目录、可独立删除。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from config import settings

DB_PATH = settings.CACHE_DIR / "alerts.db"

LEVEL_BY_SCORE = [(55, "red"), (70, "orange"), (85, "yellow")]
STATUS_LABEL = {
    "pending": "待处理",
    "handling": "处理中",
    "resolved": "已处置",
    "ignored": "已忽略",
}
OPEN_STATUS = ("pending", "handling")
DIM_LABEL = {
    "finance": "财务健康", "legal": "法律合规", "news": "舆情声誉",
    "operation": "经营能力", "credit": "信用状况", "supply": "供应链稳定",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    settings.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            company_name TEXT DEFAULT '',
            level TEXT,
            dimension TEXT,
            title TEXT,
            summary TEXT,
            evidence_json TEXT DEFAULT '[]',
            score REAL,
            source TEXT,
            fingerprint TEXT,
            status TEXT DEFAULT 'pending',
            handler TEXT DEFAULT '',
            notes_json TEXT DEFAULT '[]',
            created_at TEXT,
            updated_at TEXT,
            handled_at TEXT
        )
        """
    )
    return conn


def _level_of(score: float | None) -> str | None:
    if score is None:
        return None
    for threshold, level in LEVEL_BY_SCORE:
        if score < threshold:
            return level
    return None  # ≥85 正常，不预警


def _company_name(stock_code: str) -> str:
    try:
        from api.services import finance
        panel = finance._panel()
        rows = panel[panel["stock_code"] == stock_code]
        if not rows.empty:
            return str(rows["company_name"].iloc[-1])
    except Exception:
        pass
    return stock_code


def generate_for_enterprise(stock_code: str, source: str = "scoring") -> dict:
    from api.services import rules

    code = str(stock_code).strip().zfill(6)
    verdict = rules.rules_verdict(code)
    if "error" in verdict:
        return verdict
    name = _company_name(code)
    conn = _conn()
    created: list[dict] = []
    skipped = 0
    try:
        def create(level: str, dimension: str, title: str, summary: str, score, evidence) -> None:
            nonlocal skipped
            fp = f"{code}:{dimension}:{level}"
            exists = conn.execute(
                "SELECT 1 FROM alerts WHERE fingerprint = ? AND status IN ('pending','handling')", (fp,)
            ).fetchone()
            if exists:
                skipped += 1
                return
            conn.execute(
                """INSERT INTO alerts
                   (stock_code, company_name, level, dimension, title, summary, evidence_json,
                    score, source, fingerprint, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (code, name, level, dimension, title, summary, json.dumps(evidence, ensure_ascii=False),
                 score, source, fp, "pending", _now(), _now()),
            )
            created.append({"level": level, "dimension": dimension, "title": title, "score": score})

        for dim, info in verdict["dimensions"].items():
            level = _level_of(info.get("score"))
            if level is None:
                continue
            evidence = [{"text": info.get("note", ""), "source": "规则引擎指标"}]
            create(level, dim, f"{DIM_LABEL.get(dim, dim)}风险预警（{info['score']} 分）",
                   info.get("note", ""), info.get("score"), evidence)

        overall_level = verdict["level"]
        if overall_level in ("red", "orange"):
            create(overall_level, "overall",
                   f"综合风险预警：{name}（{verdict['score']} 分 / {verdict['grade']}）",
                   f"六维综合评级 {verdict['grade']}（{verdict['grade_label']}），建议按预警流程核查处置。",
                   verdict["score"],
                   [{"dimension": d, "score": v["score"], "note": v.get("note", "")}
                    for d, v in verdict["dimensions"].items() if v.get("score") is not None])

        conn.commit()
    finally:
        conn.close()
    return {"stock_code": code, "company": name, "created": created, "skipped": skipped}


def generate_all(source: str = "scoring") -> dict:
    from api.services import finance
    codes = finance._panel()["stock_code"].drop_duplicates().tolist()
    result = {"enterprises": len(codes), "created": 0, "skipped": 0, "details": []}
    for code in codes:
        r = generate_for_enterprise(code, source)
        if "created" not in r:
            continue
        result["created"] += len(r.get("created", []))
        result["skipped"] += r.get("skipped", 0)
        if r.get("created"):
            result["details"].append({"stock_code": code, "created": len(r["created"])})
    return result


def list_alerts(status: str | None = None, level: str | None = None,
                stock_code: str | None = None, limit: int = 200) -> dict:
    conn = _conn()
    try:
        sql = "SELECT * FROM alerts"
        conds: list[str] = []
        args: list = []
        if status:
            conds.append("status = ?")
            args.append(status)
        if level:
            conds.append("level = ?")
            args.append(level)
        if stock_code:
            conds.append("stock_code = ?")
            args.append(str(stock_code).strip().zfill(6))
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        rows = conn.execute(sql, args).fetchall()
        items = []
        for a in rows:
            items.append({
                "id": a["id"], "stock_code": a["stock_code"], "company_name": a["company_name"],
                "level": a["level"],
                "dimension": a["dimension"],
                "dimension_label": DIM_LABEL.get(a["dimension"], "综合" if a["dimension"] == "overall" else a["dimension"]),
                "title": a["title"], "summary": a["summary"], "score": a["score"],
                "status": a["status"], "status_label": STATUS_LABEL.get(a["status"], a["status"]),
                "handler": a["handler"], "created_at": a["created_at"], "updated_at": a["updated_at"],
                "handled_at": a["handled_at"],
                "notes": json.loads(a["notes_json"] or "[]"),
                "evidence": json.loads(a["evidence_json"] or "[]"),
            })
        return {"total": len(items), "items": items}
    finally:
        conn.close()


def summary() -> dict:
    conn = _conn()
    try:
        rows = conn.execute("SELECT status, level FROM alerts").fetchall()
        by_status: dict[str, int] = {}
        by_level: dict[str, int] = {}
        for status, level in rows:
            by_status[status] = by_status.get(status, 0) + 1
            by_level[level] = by_level.get(level, 0) + 1
        return {
            "total": len(rows),
            "by_status": {k: by_status.get(k, 0) for k in STATUS_LABEL},
            "by_level": by_level,
            "pending": by_status.get("pending", 0),
            "handling": by_status.get("handling", 0),
        }
    finally:
        conn.close()


def handle_alert(alert_id: int, action: str, handler: str = "", note: str = "") -> dict:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if row is None:
            return {"error": f"预警不存在: {alert_id}"}
        transitions = {
            "start": ("handling", {"pending", "handling", "ignored", "resolved"}),
            "resolve": ("resolved", {"pending", "handling"}),
            "ignore": ("ignored", {"pending", "handling"}),
            "reopen": ("pending", {"resolved", "ignored"}),
        }
        if action not in transitions:
            return {"error": f"不支持的动作: {action}（可选 start/resolve/ignore/reopen）"}
        new_status, allowed = transitions[action]
        if row["status"] not in allowed:
            return {"error": f"当前状态「{STATUS_LABEL.get(row['status'])}」不能执行 {action}"}

        now = _now()
        if handler:
            conn.execute("UPDATE alerts SET handler = ? WHERE id = ?", (handler, alert_id))
            handler = handler
        else:
            handler = row["handler"] or ""
        notes = json.loads(row["notes_json"] or "[]")
        notes.append({
            "ts": now, "action": action, "status": new_status,
            "status_label": STATUS_LABEL.get(new_status), "handler": handler, "note": note,
        })
        handled_at = now if new_status in ("resolved", "ignored") else row["handled_at"]
        conn.execute(
            "UPDATE alerts SET status = ?, notes_json = ?, updated_at = ?, handled_at = ? WHERE id = ?",
            (new_status, json.dumps(notes, ensure_ascii=False), now, handled_at, alert_id),
        )
        conn.commit()
        return {
            "alert_id": alert_id, "status": new_status,
            "status_label": STATUS_LABEL.get(new_status), "handler": handler, "notes": notes,
        }
    finally:
        conn.close()


def report_markdown(alert_id: int) -> str:
    conn = _conn()
    try:
        a = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if a is None:
            return f"# 预警报告\n\n预警不存在: {alert_id}\n"
        evidence = json.loads(a["evidence_json"] or "[]")
        notes = json.loads(a["notes_json"] or "[]")
        lines = [
            "# 企业经营风险预警报告", "",
            f"- **企业**：{a['company_name']}（{a['stock_code']}）",
            f"- **预警等级**：{a['level']} · {a['title']}",
            f"- **维度**：{DIM_LABEL.get(a['dimension'], '综合')}",
            f"- **评分**：{a['score'] if a['score'] is not None else '—'}",
            f"- **状态**：{STATUS_LABEL.get(a['status'], a['status'])}｜处理人：{a['handler'] or '—'}",
            f"- **生成时间**：{a['created_at']}",
            f"- **数据来源**：CSMAR 契约表 + 规则引擎",
            "", "## 预警摘要", "", a["summary"] or "（无）", "", "## 证据链", "",
        ]
        if evidence:
            for i, ev in enumerate(evidence, 1):
                text = ev.get("text") or json.dumps(ev, ensure_ascii=False)
                src = ev.get("source") or ""
                lines.append(f"{i}. {text}" + (f"（来源：{src}）" if src else ""))
        else:
            lines.append("（暂无证据记录）")
        lines += ["", "## 处置流水", ""]
        if notes:
            for n in notes:
                lines.append(f"- {n.get('ts', '')[:19]} · {n.get('status_label', '')} · {n.get('handler', '')} · {n.get('note', '')}")
        else:
            lines.append("（尚未处置）")
        lines += ["", "---", "", "> 本报告由「财务风险智能预警平台」自动生成，不构成投资建议。"]
        return "\n".join(lines)
    finally:
        conn.close()
