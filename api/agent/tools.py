"""Agent 工具注册表：模型只能通过工具访问数据与动作（stock_code 主键）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from api.services import rules
from api.services.rules import DIM_META


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., dict]
    read_only: bool = True

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def definitions(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def call(self, name: str, args: dict) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"unknown tool: {name}"}
        try:
            return tool.handler(**args)
        except TypeError as exc:
            return {"error": f"参数错误: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}


def register_mcp(reg: ToolRegistry) -> int:
    """把启用的外部 MCP 服务工具注册进本次运行。"""
    try:
        from api.mcp.client import McpClient
        from api.mcp.service import enabled_tools
    except Exception:  # noqa: BLE001
        return 0
    count = 0
    for item in enabled_tools():
        tool = item["tool"]
        name = item["openai_name"]
        url, auth, mcp_name = item["server_url"], item["auth_header"], tool.name

        def handler(_url=url, _auth=auth, _name=mcp_name, **kwargs):
            client = McpClient(_url, _auth)
            return {"mcp_result": client.call_tool(_name, kwargs)}

        try:
            reg.register(Tool(
                name=name, description=f"[MCP:{item['server_name']}] {tool.description or tool.name}",
                parameters=tool.input_schema or {"type": "object", "properties": {}},
                handler=handler, read_only=not item["require_approval"],
            ))
            count += 1
        except ValueError:
            continue
    return count


def register_custom_tools(reg: ToolRegistry) -> int:
    from api.services.plugins import enabled_custom_tools, run_custom_tool

    count = 0
    for row in enabled_custom_tools():
        def handler(_row=row, **kwargs):
            return run_custom_tool(_row, kwargs)

        try:
            reg.register(Tool(
                name=f"custom_{row['name']}"[:64], description=f"[插件] {row['description'] or row['name']}",
                parameters=json.loads(row["parameters_json"] or "{}") or {"type": "object", "properties": {}},
                handler=handler, read_only=not row["require_approval"],
            ))
            count += 1
        except ValueError:
            continue
    return count


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _predictions():
    """加载模型预测缓存（一次）。"""
    try:
        from models.predict import load_predictions
        return load_predictions()
    except Exception:  # noqa: BLE001
        return None


def _prob_level(p: float) -> str:
    if p >= 0.5:
        return "red"
    if p >= 0.25:
        return "orange"
    if p >= 0.10:
        return "yellow"
    return "green"


def _brief(ent: dict, verdict: dict) -> dict:
    return {"stock_code": ent.get("stock_code"), "name": ent.get("name"),
            "industry": ent.get("industry", ""), "score": verdict["score"],
            "grade": verdict["grade"], "level": verdict["level"]}


def build_registry(preset: dict | None = None) -> ToolRegistry:
    reg = ToolRegistry()
    allowed_tools = set((preset or {}).get("tools") or [])
    allowed_skills = set((preset or {}).get("skills") or [])
    ALWAYS = {"list_skills", "load_skill"}

    def _find_enterprise(code_or_kw: str, limit: int = 5) -> list[dict]:
        from api.services import enterprise
        data = enterprise.list_enterprises()
        kw = (code_or_kw or "").strip()
        code = kw.zfill(6) if kw.isdigit() and len(kw) <= 6 else ""
        if code:
            exact = [e for e in data["items"] if e["stock_code"] == code]
            if exact:
                return exact
        low = kw.lower()
        return [e for e in data["items"] if low in e["name"].lower() or low in e["stock_code"]
                or low in (e.get("industry") or "").lower()][:limit]

    def search_enterprise(keyword: str = "", limit: int = 5) -> dict:
        kw = (keyword or "").strip()
        matches = _find_enterprise(kw, limit)
        if matches:
            briefs = []
            for e in matches:
                v = rules.rules_verdict(e["stock_code"])
                if "error" not in v:
                    briefs.append(_brief(e, v))
            return {"count": len(briefs), "enterprises": briefs,
                    "hint": "如需详细画像请调用 get_score_profile(stock_code)"}
        return {"count": 0, "hint": "未找到企业，可尝试其他关键词，或直接输入 6 位股票代码"}

    def get_score_profile(stock_code: str) -> dict:
        code = str(stock_code).strip().zfill(6)
        from api.services import enterprise
        ent = enterprise.get_enterprise(code)
        if "error" in ent:
            return ent
        v = rules.rules_verdict(code)
        return {"enterprise": {"stock_code": code, "name": ent.get("name"), "industry": ent.get("industry", "")},
                "score": v["score"], "grade": v["grade"], "grade_label": v["grade_label"], "level": v["level"],
                "dimensions": {k: {"label": DIM_META[k], "score": v["dimensions"][k]["score"],
                                   "level": v["dimensions"][k]["level"], "note": v["dimensions"][k]["note"]}
                               for k in DIM_META}}

    def get_risk_facts(stock_code: str, dimension: str = "", limit: int = 10) -> dict:
        from api.services import risk
        code = str(stock_code).strip().zfill(6)
        facts = [f for f in risk.facts(code, limit=50) if not dimension or f["dimension"] == dimension][:limit]
        return {"stock_code": code, "count": len(facts),
                "facts": [{"dimension": f["dimension"], "dimension_label": DIM_META.get(f["dimension"], f["dimension"]),
                           "text": f["text"], "evidence": f["evidence"], "confidence": f["confidence"]} for f in facts]}

    def list_enterprises_by_level(level: str = "red") -> dict:
        df = _predictions()
        if df is None or df.empty:
            return {"error": "预测缓存不可用"}
        rows = df.sort_values("year").groupby("stock_code", as_index=False).tail(1)
        out = []
        for _, r in rows.iterrows():
            if _prob_level(float(r["st_prob"])) == level:
                out.append({"stock_code": r["stock_code"], "st_prob": round(float(r["st_prob"]), 4),
                            "risk_level": r["risk_level"]})
        out.sort(key=lambda x: x["st_prob"])
        return {"level": level, "count": len(out), "enterprises": out[:50]}

    def get_platform_overview() -> dict:
        df = _predictions()
        from api.services import alerts as alerts_service
        if df is None or df.empty:
            return {"error": "预测缓存不可用"}
        rows = df.sort_values("year").groupby("stock_code", as_index=False).tail(1)
        levels: dict[str, int] = {}
        for p in rows["st_prob"]:
            lv = _prob_level(float(p))
            levels[lv] = levels.get(lv, 0) + 1
        try:
            alert_summary = alerts_service.summary()
        except Exception:  # noqa: BLE001
            alert_summary = {}
        return {"enterprise_total": int(len(rows)),
                "avg_st_prob": round(float(rows["st_prob"].mean()), 4),
                "level_counts": levels, "alerts": alert_summary}

    def list_alerts(status: str = "", level: str = "", stock_code: str = "", limit: int = 10) -> dict:
        from api.services import alerts as alerts_service
        return alerts_service.list_alerts(status or None, level or None, stock_code or None, limit)

    def handle_alert(alert_id: int, action: str, handler: str = "", note: str = "") -> dict:
        from api.services import alerts as alerts_service
        return alerts_service.handle_alert(alert_id, action, handler, note)

    def get_alert_report(alert_id: int) -> dict:
        from api.services import alerts as alerts_service
        text = alerts_service.report_markdown(alert_id)
        if not text:
            return {"error": f"预警不存在: {alert_id}"}
        return {"alert_id": alert_id, "report_markdown": text[:4000]}

    def refresh_enterprise_data(stock_code: str) -> dict:
        from api.services import datasources
        return datasources.refresh_enterprise(stock_code)

    def resolve_stock_code(name: str) -> dict:
        kw = (name or "").strip()
        code = kw.zfill(6) if kw.isdigit() and len(kw) <= 6 else ""
        matches = _find_enterprise(kw, 5)
        return {"query": kw, "stock_code": code or None,
                "candidates": [{"name": e["name"], "stock_code": e["stock_code"]} for e in matches]}

    def add_enterprise(name: str, stock_code: str = "", auto_fetch: bool = True) -> dict:
        from api.services import enterprise
        return enterprise.add_enterprise(name, stock_code or None, auto_refresh=auto_fetch)

    def list_skills() -> dict:
        from api.services import skills
        items = skills.skills_for_tool()
        if allowed_skills:
            items = [s for s in items if s["name"] in allowed_skills]
        return {"count": len(items), "skills": items, "hint": "选定后用 load_skill(name) 载入该技能的完整执行指令"}

    def load_skill(name: str) -> dict:
        from api.services import skills
        if allowed_skills and name not in allowed_skills:
            return {"error": f"当前预设未启用该技能：{name}", "available": sorted(allowed_skills)}
        row = skills.get_by_name(name)
        if row is None or not row["enabled"]:
            return {"error": f"技能不存在或已停用：{name}", "available": [s["name"] for s in skills.skills_for_tool()]}
        return {"skill": row["name"], "description": row["description"], "instructions": row["content"]}

    def run_risk_analysis(stock_code: str) -> dict:
        from api.services import analyze, risk
        code = str(stock_code).strip().zfill(6)
        result = analyze.analyze_by_code(code)
        if "error" in result:
            return result
        v = result["verdict"]
        n = risk.save_evidence(code, v.get("evidence", []))
        return {"stock_code": code, "enterprise": result["enterprise"]["name"], "score": v["score"],
                "grade": v["grade"], "level": v["level"], "llm_level": v["llm_level"],
                "rules_level": v["rules_level"], "cross_check_ok": v["cross_check_ok"],
                "summary": v["summary"], "evidence_count": n, "evidence": v["evidence"][:8]}

    # ---------- 金融分析模块 ----------

    def _models_brief(models: dict) -> dict:
        alt = models.get("altman", {})
        z, z2 = alt.get("z", {}), alt.get("z2", {})
        f, b = models.get("piotroski", {}), models.get("beneish", {})
        return {
            "altman_z": {"score": z.get("score"), "verdict": z.get("verdict"), "available": z.get("available"),
                         "missing": z.get("missing", [])},
            "altman_z2": {"score": z2.get("score"), "verdict": z2.get("verdict"), "available": z2.get("available")},
            "piotroski_f": {"score": f.get("score"), "max_score": f.get("max_score"), "verdict": f.get("verdict"),
                            "failed": [s["name"] for s in f.get("signals", []) if s.get("pass") is False],
                            "note": f.get("note", "")},
            "beneish_m": {"score": b.get("score"), "verdict": b.get("verdict"), "available": b.get("available"),
                          "missing": b.get("missing", []), "note": b.get("note", "")},
        }

    def get_financial_analysis(stock_code: str, include_peers: bool = True) -> dict:
        from api.services import finance
        a = finance.analysis(stock_code, with_peers=include_peers)
        if a.get("error"):
            return a
        if not a.get("available"):
            return {"enterprise": a["enterprise"], "available": False, "reason": a.get("reason"),
                    "hint": "可用 refresh_enterprise_data 拉取公开财报，或确认企业是否有股票代码"}
        peers = a.get("peers") or {}
        return {
            "enterprise": a["enterprise"], "available": True, "latest_year": a["latest_year"],
            "kpi": [{k: v for k, v in item.items() if k != "note"} for item in a["kpi"] if item["available"]],
            "dupont": a["dupont"], "models": _models_brief(a["models"]), "anomalies": a["anomalies"],
            "peers": {"industry": peers.get("industry"), "note": peers.get("note"),
                      "rows": [{"name": r["name"], "is_self": r["is_self"], "year": r["year"],
                                "metrics": r["metrics"], "percentiles": r.get("percentiles", {})}
                               for r in peers.get("rows", [])]} if peers else None,
            "data_quality": a["data_quality"],
        }

    def compare_financials(stock_codes: list[str]) -> dict:
        from api.services import finance
        codes = [str(c).strip().zfill(6) for c in (stock_codes or [])][:5]
        if len(codes) < 2:
            return {"error": "至少需要 2 个 stock_code"}
        rows = []
        for code in codes:
            a = finance.analysis(code, with_peers=False)
            if a.get("error") or not a.get("available"):
                rows.append({"stock_code": code, "name": a.get("enterprise", {}).get("name", code),
                             "available": False, "reason": a.get("reason", "无数据")})
                continue
            kpi = {k["key"]: k["value"] for k in a["kpi"] if k["available"]}
            rows.append({"stock_code": code, "name": a["enterprise"]["name"], "industry": a["enterprise"]["industry"],
                         "available": True, "latest_year": a["latest_year"],
                         "metrics": {k: kpi.get(k) for k in ("revenue", "net_profit", "revenue_growth",
                                                             "gross_margin", "net_margin", "roe", "debt_ratio",
                                                             "ocf", "ocf_to_profit")},
                         "models": _models_brief(a["models"]), "anomaly_count": len(a["anomalies"])})
        return {"count": len(rows), "rows": rows, "hint": "数值单位：万元 / % / 倍"}

    def screen_by_financial_metric(metric: str, op: str = "lt", value: float = 0, limit: int = 10) -> dict:
        from api.services import finance
        alias = {"revenue": "revenue", "net_profit": "net_profit", "debt_ratio": "debt_ratio"}
        key = alias.get((metric or "").strip(), "")
        if key not in alias:
            return {"error": f"不支持的指标：{metric}", "supported": sorted(alias)}
        ops = {"lt": lambda x: x < value, "le": lambda x: x <= value, "gt": lambda x: x > value, "ge": lambda x: x >= value}
        if op not in ops:
            return {"error": f"不支持的比较符：{op}", "supported": sorted(ops)}
        data = finance.overview()
        hit = []
        for item in data["items"]:
            v = item.get(key)
            if v is None:
                continue
            if ops[op](float(v)):
                hit.append({"stock_code": item["stock_code"], "name": item["name"],
                            "industry": item["industry"], "year": item["latest_year"], "value": v})
        hit.sort(key=lambda x: x["value"])
        return {"metric": key, "op": op, "threshold": value, "count": len(hit),
                "items": hit[:max(1, min(limit, 50))], "scanned": len(data["items"])}

    reg.register(Tool("search_enterprise",
        "按企业名称、行业关键词或股票代码搜索企业，返回 stock_code/名称/行业/评分/等级。首次接触某企业时先调用它拿到 stock_code。",
        {"type": "object", "properties": {"keyword": {"type": "string", "description": "企业名称、行业关键词或 6 位股票代码"},
                                          "limit": {"type": "integer", "description": "返回条数，默认 5"}},
         "required": ["keyword"]}, search_enterprise))
    reg.register(Tool("get_score_profile",
        "获取指定企业的六维评分画像（财务/法律/舆情/经营/信用/供应链）、综合评分与 AAA~C 评级。",
        {"type": "object", "properties": {"stock_code": {"type": "string", "description": "6 位股票代码"}},
         "required": ["stock_code"]}, get_score_profile))
    reg.register(Tool("get_risk_facts",
        "获取企业已沉淀的风险事实与证据（含来源与置信度），可按维度筛选。",
        {"type": "object", "properties": {"stock_code": {"type": "string"},
                                          "dimension": {"type": "string", "description": "可选：finance/legal/news/operation/credit/supply"},
                                          "limit": {"type": "integer"}}, "required": ["stock_code"]}, get_risk_facts))
    reg.register(Tool("list_enterprises_by_level",
        "列出指定模型风险等级的企业（red/orange/yellow/green），按 ST 概率升序。",
        {"type": "object", "properties": {"level": {"type": "string", "description": "red/orange/yellow/green，默认 red"}},
         "required": []}, list_enterprises_by_level))
    reg.register(Tool("get_platform_overview",
        "获取平台整体统计：企业总数、平均 ST 概率、各风险等级数量、预警汇总。",
        {"type": "object", "properties": {}, "required": []}, get_platform_overview))
    reg.register(Tool("list_alerts",
        "查询预警工单：可按状态（pending/handling/resolved/ignored）、等级（red/orange/yellow）、股票代码筛选。",
        {"type": "object", "properties": {"status": {"type": "string"}, "level": {"type": "string"},
                                          "stock_code": {"type": "string"}, "limit": {"type": "integer"}},
         "required": []}, list_alerts))
    reg.register(Tool("handle_alert",
        "处置预警工单（写操作，需授权）：start/resolve/ignore/reopen。",
        {"type": "object", "properties": {"alert_id": {"type": "integer"}, "action": {"type": "string"},
                                          "handler": {"type": "string"}, "note": {"type": "string"}},
         "required": ["alert_id", "action"]}, handle_alert, read_only=False))
    reg.register(Tool("get_alert_report",
        "生成指定预警的处置报告（Markdown 文本，含证据链与处理流水）。",
        {"type": "object", "properties": {"alert_id": {"type": "integer"}}, "required": ["alert_id"]}, get_alert_report))
    reg.register(Tool("refresh_enterprise_data",
        "从公开数据源（AkShare）刷新指定企业的实时快照并落盘。这是写操作，需用户授权。",
        {"type": "object", "properties": {"stock_code": {"type": "string"}}, "required": ["stock_code"]},
        refresh_enterprise_data, read_only=False))
    reg.register(Tool("resolve_stock_code",
        "按企业名称或股票代码查询 A 股标的：输入名称返回代码，输入代码返回简称。",
        {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}, resolve_stock_code))
    reg.register(Tool("add_enterprise",
        "添加一家新企业到平台（可自动拉取公开数据）。这是写操作，需用户授权。",
        {"type": "object", "properties": {"name": {"type": "string"}, "stock_code": {"type": "string"},
                                          "auto_fetch": {"type": "boolean"}}, "required": ["name"]},
        add_enterprise, read_only=False))
    reg.register(Tool("get_financial_analysis",
        "金融分析模块：KPI、杜邦分解、Altman Z/Z''、Piotroski F、Beneish M、同业对标分位与异常勾稽。",
        {"type": "object", "properties": {"stock_code": {"type": "string"},
                                          "include_peers": {"type": "boolean", "description": "默认 true"}},
         "required": ["stock_code"]}, get_financial_analysis))
    reg.register(Tool("compare_financials",
        "多家企业财务横向对比（最多 5 家）。",
        {"type": "object", "properties": {"stock_codes": {"type": "array", "items": {"type": "string"}}},
         "required": ["stock_codes"]}, compare_financials))
    reg.register(Tool("screen_by_financial_metric",
        "按财务指标筛选企业。可用指标：revenue/net_profit/debt_ratio；比较符 lt/le/gt/ge。",
        {"type": "object", "properties": {"metric": {"type": "string"}, "op": {"type": "string"},
                                          "value": {"type": "number"}, "limit": {"type": "integer"}},
         "required": ["metric", "op", "value"]}, screen_by_financial_metric))
    reg.register(Tool("list_skills",
        "列出平台可用技能（如「企业风险评估报告」「多企业对比分析」）。需要专门分析方法时先调用它。",
        {"type": "object", "properties": {}, "required": []}, list_skills))
    reg.register(Tool("load_skill",
        "载入指定技能的完整执行指令，然后严格按该指令完成任务。",
        {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}, load_skill))
    reg.register(Tool("run_risk_analysis",
        "触发指定企业的完整风险研判（LLM + 规则交叉校验），耗时 10~40 秒。仅在用户明确要求分析/重新研判时使用。",
        {"type": "object", "properties": {"stock_code": {"type": "string"}}, "required": ["stock_code"]},
        run_risk_analysis, read_only=False))

    if allowed_tools:
        for name in list(reg._tools):
            if name not in allowed_tools and name not in ALWAYS:
                reg._tools.pop(name, None)
    return reg
