"""企业档案服务（stock_code 主键）。

上市企业清单复用金融分析面板（finance.overview），手动添加的非上市企业落
``enterprise`` 表（供 P6 表格对象与人工数据导入使用），合成代码 ``M`` 前缀。
"""

from __future__ import annotations

from api.db import execute, query
from api.services import finance as finance_service


def _norm(code: str | None) -> str:
    if not code:
        return ""
    return str(code).strip().zfill(6)


def list_enterprises() -> dict:
    """全部企业：面板上市企业 + 手动建档的非上市企业。"""
    panel = finance_service.overview()
    items = [{"stock_code": e["stock_code"], "name": e["name"], "industry": e.get("industry", ""),
              "has_finance": e.get("has_finance", True), "source": "panel",
              "latest_year": e.get("latest_year")} for e in panel.get("items", [])]
    for row in query("SELECT * FROM enterprise ORDER BY created_at DESC"):
        if any(i["stock_code"] == row["stock_code"] for i in items):
            continue
        items.append({"stock_code": row["stock_code"], "name": row["name"],
                      "industry": row["industry"], "has_finance": False, "source": "manual",
                      "latest_year": None, "data_note": row["data_note"]})
    return {"total": len(items), "items": items}


def get_enterprise(stock_code: str) -> dict:
    """单企业档案：优先面板，其次手动建档表。"""
    code = _norm(stock_code)
    row = query("SELECT * FROM enterprise WHERE stock_code = ?", (code,))
    if row:
        return {**row[0], "source": "manual"}
    panel = finance_service.overview()
    for e in panel.get("items", []):
        if e["stock_code"] == code:
            return {**e, "source": "panel"}
    return {"error": f"企业不存在：{code}", "stock_code": code}


def add_enterprise(name: str, stock_code: str | None = None, industry: str = "",
                   auto_refresh: bool = True) -> dict:
    """新建/更新企业档案。上市企业按 stock_code 建档；无代码时用 M 前缀合成码。"""
    name = (name or "").strip()
    if not name:
        return {"error": "企业名称不能为空"}
    code = _norm(stock_code)
    if not code:
        # 非上市企业：合成代码（保证主键唯一且可寻址）
        row = query("SELECT COUNT(*) AS n FROM enterprise WHERE stock_code LIKE 'M%'")
        code = f"M{int(row[0]['n']) + 1:06d}"
    data_note = f"手动添加：股票代码 {code}" if stock_code else f"手动添加：非上市企业（合成码 {code}）"

    existing = query("SELECT stock_code FROM enterprise WHERE stock_code = ?", (code,))
    if existing:
        execute("UPDATE enterprise SET name = ?, industry = ?, updated_at = datetime('now','localtime') WHERE stock_code = ?",
               (name, industry or "上市公司", code))
    else:
        execute("INSERT INTO enterprise (stock_code, name, industry, data_note) VALUES (?, ?, ?, ?)",
               (code, name, industry or "上市公司", data_note))

    out: dict = {"stock_code": code, "name": name, "industry": industry or "上市公司"}

    if auto_refresh and not code.startswith("M"):
        from api.services import datasources
        out["refresh"] = datasources.refresh_enterprise(code)
    return out


def delete_enterprise(stock_code: str) -> dict:
    code = _norm(stock_code)
    execute("DELETE FROM enterprise WHERE stock_code = ?", (code,))
    return {"deleted": code}


def profile(stock_code: str) -> dict:
    """统一风险上下文：企业档案 + 模型评分 + 规则评级 + 金融分析摘要。"""
    code = _norm(stock_code)
    ent = get_enterprise(code)
    if "error" in ent:
        return ent

    out = {"enterprise": ent}
    try:
        from api.services import rules as rules_service
        out["rules"] = rules_service.rules_verdict(code)
    except Exception:  # noqa: BLE001
        out["rules"] = None
    try:
        fin = finance_service.analysis(code, years=5, with_peers=False)
        if not fin.get("error") and fin.get("available"):
            out["finance"] = {
                "latest_year": fin["latest_year"],
                "kpi": {k["key"]: k["value"] for k in fin["kpi"]},
                "models": {
                    "altman_z2": fin["models"]["altman"]["z2"]["score"],
                    "piotroski": fin["models"]["piotroski"]["score"],
                    "beneish": fin["models"]["beneish"]["score"],
                },
                "anomalies": [a["title"] for a in fin["anomalies"]],
            }
    except Exception:  # noqa: BLE001
        out["finance"] = None
    return out
