"""风险事实读写与读侧快照（stock_code 主键）。

LLM 研判本体在 api/services/analyze.py（LLM + 规则交叉校验）；本模块负责：
- 把研判产出的 evidence 落库 risk_fact（供证据引用与人工复核）
- 读侧快照（不触发 LLM，页面/工具刷新用）
"""

from __future__ import annotations

import json

from api.db import execute, query
from api.services import rules


def save_evidence(stock_code: str, evidence: list[dict], confidence: float = 0.8) -> int:
    """把证据写入 risk_fact。返回写入条数。"""
    code = str(stock_code).strip().zfill(6)
    n = 0
    for ev in evidence or []:
        if not isinstance(ev, dict):
            continue
        text = str(ev.get("text", "")).strip()
        if not text:
            continue
        execute(
            "INSERT INTO risk_fact (stock_code, dimension, text, evidence_json, confidence) VALUES (?, ?, ?, ?, ?)",
            (code, str(ev.get("dimension", "other"))[:30], text[:1000],
             json.dumps({"source": ev.get("source", ""), "date": ev.get("date", "")}, ensure_ascii=False),
             float(confidence)),
        )
        n += 1
    return n


def facts(stock_code: str, limit: int = 50) -> list[dict]:
    code = str(stock_code).strip().zfill(6)
    rows = query("SELECT * FROM risk_fact WHERE stock_code = ? ORDER BY ts DESC LIMIT ?", (code, limit))
    return [
        {"id": r["id"], "dimension": r["dimension"], "text": r["text"],
         "evidence": json.loads(r["evidence_json"]) if r["evidence_json"] else {},
         "confidence": r["confidence"], "ts": r["ts"]}
        for r in rows
    ]


def snapshot(stock_code: str) -> dict:
    """读侧快照：规则评级 + 风险事实（不触发 LLM）。"""
    code = str(stock_code).strip().zfill(6)
    verdict = rules.rules_verdict(code)
    if "error" in verdict:
        return verdict
    return {
        "stock_code": code,
        "verdict_level": verdict["level"],
        "score": verdict["score"],
        "grade": verdict["grade"],
        "grade_label": verdict["grade_label"],
        "dimensions": verdict["dimensions"],
        "facts": facts(code),
    }
