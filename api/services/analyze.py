"""智能研判（移植自旧项目 server/app/services/risk.py 的 LLM 研判 + 规则交叉校验）。

策略（与旧项目一致）：LLM 输出研判 JSON，规则引擎交叉校验，不一致时以规则为准。
LLM 未配置时退化为纯规则结果（不阻断）。
"""

from __future__ import annotations

import json
import re

from config import settings
from api.services import rules

RISK_SYSTEM = (
    "你是企业经营风险研判分析师。基于给定企业的六维规则评分与模型风险概率，"
    "输出风险研判结论。六个维度：finance 财务健康、legal 法律合规、news 舆情声誉、"
    "operation 经营能力、credit 信用状况、supply 供应链稳定。"
    "最终回复必须是一个严格的 JSON 对象，不要包含任何解释文字。JSON 格式：\n"
    '{"level":"red|orange|yellow|green","summary":"一句话结论",'
    '"evidence":[{"dimension":"finance|legal|news|operation|credit|supply","text":"事实描述","source":"来源"}]}\n'
    "level 取值：red=高风险，orange=较高风险，yellow=关注，green=正常，gray=数据不足。"
    "证据必须逐条来自给定数据，不得编造，最多 5 条。"
)


def _extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1 or e <= s:
        return None
    try:
        obj = json.loads(text[s : e + 1])
        return obj if isinstance(obj, dict) else None
    except ValueError:
        return None


def _llm_configured() -> bool:
    return bool(settings.LLM_BASE_URL and settings.LLM_MODEL)


def _model_prob(stock_code: str) -> dict | None:
    try:
        from models.predict import load_predictions
        scored = load_predictions()
    except Exception:
        return None
    rows = scored[scored["stock_code"] == stock_code]
    if rows.empty:
        return None
    latest = rows.sort_values("year").iloc[-1]
    return {
        "year": int(latest["year"]),
        "st_prob": float(latest["st_prob"]),
        "risk_level": latest["risk_level"],
        "risk_percentile": float(latest["risk_percentile"]),
    }


def _company(stock_code: str) -> tuple[str, str]:
    try:
        from api.services import finance
        panel = finance._panel()
        rows = panel[panel["stock_code"] == stock_code]
        if not rows.empty:
            return str(rows["company_name"].iloc[-1]), str(rows["industry"].iloc[-1])
    except Exception:
        pass
    return stock_code, ""


def _context_text(stock_code: str, verdict: dict, model_prob: dict | None) -> str:
    name, industry = _company(stock_code)
    lines = [f"企业：{name}（{stock_code}）· 行业 {industry}", ""]
    lines.append("规则六维评分：")
    for dim, d in verdict.get("dimensions", {}).items():
        score = d.get("score")
        lines.append(f"  - {d.get('label', dim)}：{score if score is not None else '数据不足'} 分（{d.get('note', '')}）")
    lines.append(f"综合评级：{verdict.get('grade')}（{verdict.get('grade_label')}），规则等级 {verdict.get('level')}")
    if model_prob:
        lines.append(f"模型 ST 风险概率：{model_prob['st_prob']:.4f}（{model_prob['risk_level']}）")
    return "\n".join(lines)


def _llm_verdict(stock_code: str, verdict: dict, model_prob: dict | None) -> tuple[str, str, list]:
    from api.services.llm import LlmClient, LlmConfig

    client = LlmClient(LlmConfig(
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
        model=settings.LLM_MODEL,
        max_tokens=settings.LLM_ANALYSIS_MAX_TOKENS,
        timeout_s=settings.LLM_TIMEOUT_S,
    ))
    messages = [
        {"role": "system", "content": RISK_SYSTEM},
        {"role": "user", "content": _context_text(stock_code, verdict, model_prob)},
    ]
    msg = client.chat(messages)
    obj = _extract_json(msg.get("content") or "")
    obj = obj or {}
    evidence = obj.get("evidence", []) if isinstance(obj.get("evidence"), list) else []
    return obj.get("level", ""), obj.get("summary", ""), evidence


def analyze_by_code(stock_code: str) -> dict:
    code = str(stock_code).strip().zfill(6)
    verdict = rules.rules_verdict(code)
    if "error" in verdict:
        return verdict
    name, industry = _company(code)
    model_prob = _model_prob(code)

    llm_level, summary, evidence = None, "", []
    llm_error = ""
    if _llm_configured():
        try:
            llm_level, summary, evidence = _llm_verdict(code, verdict, model_prob)
        except Exception as exc:  # noqa: BLE001 —— LLM 失败不阻断规则研判
            llm_error = str(exc)
    else:
        llm_error = "LLM 未配置（设置 LLM_BASE_URL / LLM_MODEL 后启用智能研判）"

    rules_level = verdict["level"]
    if llm_level not in ("red", "orange", "yellow", "green"):
        llm_level = "unknown"
    cross_check = llm_level == rules_level
    final_level = rules_level if not cross_check else llm_level

    return {
        "enterprise": {"stock_code": code, "name": name, "industry": industry},
        "verdict": {
            "level": final_level,
            "score": verdict["score"],
            "grade": verdict["grade"],
            "grade_label": verdict["grade_label"],
            "level_by": "rules" if not cross_check else "llm",
            "cross_check_ok": cross_check,
            "llm_level": llm_level,
            "rules_level": rules_level,
            "dimensions": verdict["dimensions"],
            "summary": summary or f"规则评级 {verdict['grade']}（{verdict['grade_label']}），六维综合 {verdict['score']} 分",
            "evidence": evidence,
        },
        "model": model_prob,
        "llm_error": llm_error,
    }
