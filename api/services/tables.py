"""表格对象（TableDoc）：在线创建/编辑/勾稽校验/入库（Python 重实现，stock_code 主键）。

对齐旧项目 Rust 版：表是一等对象；单元格级溯源；中文科目名→引擎字段自动映射；
勾稽校验把视觉幻觉挡在入库前；不覆盖公开信源数据。
"""

from __future__ import annotations

import json
from datetime import datetime

from api.db import execute, query

FIELDS: list[dict] = [
    {"key": "revenue_wan", "label": "营业总收入", "kind": "amount", "unit": "万元",
     "aliases": ["营业总收入", "营业收入", "主营业务收入", "营业总额", "营收", "revenue"]},
    {"key": "operating_cost_wan", "label": "营业成本", "kind": "amount", "unit": "万元",
     "aliases": ["营业成本", "主营业务成本", "营业总成本"]},
    {"key": "operating_profit_wan", "label": "营业利润", "kind": "amount", "unit": "万元", "aliases": ["营业利润"]},
    {"key": "net_profit_total_wan", "label": "净利润（含少数股东）", "kind": "amount", "unit": "万元",
     "aliases": ["净利润", "净利润(含少数股东)"]},
    {"key": "net_profit_wan", "label": "归母净利润", "kind": "amount", "unit": "万元",
     "aliases": ["归属于母公司股东的净利润", "归属于母公司所有者的净利润", "归母净利润",
                "归属于上市公司股东的净利润", "归属于母公司净利润"]},
    {"key": "deducted_profit_wan", "label": "扣非净利润", "kind": "amount", "unit": "万元",
     "aliases": ["扣除非经常性损益后的净利润", "扣非净利润"]},
    {"key": "total_assets_wan", "label": "资产总计", "kind": "amount", "unit": "万元",
     "aliases": ["资产总计", "资产总额", "总资产"]},
    {"key": "total_liabilities_wan", "label": "负债合计", "kind": "amount", "unit": "万元",
     "aliases": ["负债合计", "负债总计", "负债总额", "总负债"]},
    {"key": "equity_wan", "label": "所有者权益合计", "kind": "amount", "unit": "万元",
     "aliases": ["所有者权益合计", "股东权益合计", "净资产", "归属于母公司所有者权益合计", "所有者权益"]},
    {"key": "current_assets_wan", "label": "流动资产合计", "kind": "amount", "unit": "万元",
     "aliases": ["流动资产合计", "流动资产"]},
    {"key": "current_liabilities_wan", "label": "流动负债合计", "kind": "amount", "unit": "万元",
     "aliases": ["流动负债合计", "流动负债"]},
    {"key": "accounts_receivable_wan", "label": "应收账款", "kind": "amount", "unit": "万元",
     "aliases": ["应收账款", "应收账款净额", "应收票据及应收账款"]},
    {"key": "inventory_wan", "label": "存货", "kind": "amount", "unit": "万元", "aliases": ["存货", "存货净额"]},
    {"key": "goodwill_wan", "label": "商誉", "kind": "amount", "unit": "万元", "aliases": ["商誉"]},
    {"key": "fixed_assets_wan", "label": "固定资产", "kind": "amount", "unit": "万元",
     "aliases": ["固定资产", "固定资产净额"]},
    {"key": "ocf_wan", "label": "经营活动现金流净额", "kind": "amount", "unit": "万元",
     "aliases": ["经营活动产生的现金流量净额", "经营活动现金流量净额", "经营现金流", "经营活动现金流净额"]},
    {"key": "capex_wan", "label": "资本开支", "kind": "amount", "unit": "万元",
     "aliases": ["购建固定资产、无形资产和其他长期资产支付的现金", "资本开支", "资本性支出"]},
    {"key": "selling_expense_wan", "label": "销售费用", "kind": "amount", "unit": "万元", "aliases": ["销售费用", "营业费用"]},
    {"key": "admin_expense_wan", "label": "管理费用", "kind": "amount", "unit": "万元", "aliases": ["管理费用"]},
    {"key": "finance_expense_wan", "label": "财务费用", "kind": "amount", "unit": "万元", "aliases": ["财务费用"]},
    {"key": "rd_expense_wan", "label": "研发费用", "kind": "amount", "unit": "万元", "aliases": ["研发费用", "研发支出"]},
    {"key": "gross_margin", "label": "毛利率", "kind": "ratio", "unit": "%", "aliases": ["毛利率", "销售毛利率"]},
    {"key": "net_margin", "label": "销售净利率", "kind": "ratio", "unit": "%", "aliases": ["销售净利率", "净利率"]},
    {"key": "roe", "label": "净资产收益率", "kind": "ratio", "unit": "%",
     "aliases": ["净资产收益率", "roe", "加权平均净资产收益率"]},
    {"key": "roa", "label": "总资产报酬率", "kind": "ratio", "unit": "%", "aliases": ["总资产报酬率", "roa"]},
    {"key": "debt_ratio", "label": "资产负债率", "kind": "ratio", "unit": "%", "aliases": ["资产负债率", "负债率"]},
    {"key": "current_ratio", "label": "流动比率", "kind": "ratio", "unit": "倍", "aliases": ["流动比率"]},
    {"key": "quick_ratio", "label": "速动比率", "kind": "ratio", "unit": "倍", "aliases": ["速动比率"]},
    {"key": "equity_multiplier", "label": "权益乘数", "kind": "ratio", "unit": "倍", "aliases": ["权益乘数"]},
    {"key": "asset_turnover", "label": "总资产周转率", "kind": "ratio", "unit": "次",
     "aliases": ["总资产周转率", "总资产周转次数"]},
    {"key": "ar_days", "label": "应收账款周转天数", "kind": "ratio", "unit": "天", "aliases": ["应收账款周转天数"]},
    {"key": "inventory_days", "label": "存货周转天数", "kind": "ratio", "unit": "天", "aliases": ["存货周转天数"]},
    {"key": "revenue_growth", "label": "营业总收入增速", "kind": "ratio", "unit": "%",
     "aliases": ["营业总收入增速", "营业收入增长率", "营收增速"]},
    {"key": "profit_growth", "label": "归母净利润增速", "kind": "ratio", "unit": "%",
     "aliases": ["归母净利润增速", "净利润增长率", "净利润增速"]},
    {"key": "ocf_to_revenue", "label": "经营现金流/营业收入", "kind": "ratio", "unit": "倍",
     "aliases": ["经营现金流/营业收入", "现金流营收比"]},
    {"key": "ocf_to_profit", "label": "现金含量", "kind": "ratio", "unit": "倍",
     "aliases": ["现金含量", "经营现金流/净利润", "净现比"]},
    {"key": "bvps", "label": "每股净资产", "kind": "ratio", "unit": "元", "aliases": ["每股净资产"]},
]

TEMPLATES = [
    ("income", "利润表", ["revenue_wan", "operating_cost_wan", "selling_expense_wan", "admin_expense_wan",
                          "rd_expense_wan", "finance_expense_wan", "operating_profit_wan", "net_profit_total_wan",
                          "net_profit_wan", "deducted_profit_wan"]),
    ("balance", "资产负债表", ["current_assets_wan", "accounts_receivable_wan", "inventory_wan", "fixed_assets_wan",
                              "goodwill_wan", "total_assets_wan", "current_liabilities_wan", "total_liabilities_wan",
                              "equity_wan"]),
    ("cashflow", "现金流量表", ["ocf_wan", "capex_wan"]),
    ("kpi", "关键指标表", ["revenue_wan", "net_profit_wan", "total_assets_wan", "total_liabilities_wan", "equity_wan",
                          "ocf_wan", "gross_margin", "net_margin", "roe", "debt_ratio"]),
]

_FIELD_BY_KEY = {f["key"]: f for f in FIELDS}
_PUNCT = "：:＊*·、,，.。()（）「」【】 \t\n\r"


def normalize_label(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch not in _PUNCT).lower()


def match_field(label: str) -> str | None:
    norm = normalize_label(label)
    if not norm:
        return None
    for f in FIELDS:
        if normalize_label(f["label"]) == norm or normalize_label(f["key"]) == norm:
            return f["key"]
        for a in f["aliases"]:
            if normalize_label(a) == norm:
                return f["key"]
    return None


def _template_rows(kind: str) -> list[str]:
    for k, _t, rows in TEMPLATES:
        if k == kind:
            return list(rows)
    return []


def build_sheet(kind: str, periods: list[tuple[str, str]]) -> tuple[dict, dict]:
    columns = [{"key": f"c{i + 1}", "label": f"{p}{rt}", "period": p, "report_type": rt or "年报", "type": "number"}
               for i, (p, rt) in enumerate(periods)]
    rows, mapping = [], {}
    for i, key in enumerate(_template_rows(kind)):
        rk = f"r{i + 1}"
        rows.append({"key": rk, "label": _FIELD_BY_KEY[key]["label"] if key in _FIELD_BY_KEY else key,
                     "field": key, "cells": {}})
        mapping[key] = rk
    return {"columns": columns, "rows": rows, "meta": {}}, mapping


def blank_sheet(rows: int = 8, cols: int = 4) -> dict:
    return {"columns": [{"key": f"c{i + 1}", "label": "", "period": "", "report_type": "", "type": "number"}
                        for i in range(cols)],
            "rows": [{"key": f"r{i + 1}", "label": "", "field": "", "cells": {}} for i in range(rows)], "meta": {}}


def normalize_workbook(raw: dict) -> dict:
    if isinstance(raw.get("sheets"), list):
        sheets = [{"key": s.get("key") or f"s{i + 1}", "name": s.get("name") or f"Sheet{i + 1}",
                   "columns": s.get("columns", []), "rows": s.get("rows", []), "mapping": s.get("mapping", {})}
                  for i, s in enumerate(raw["sheets"])]
        if not sheets:
            sheets = [{"key": "s1", "name": "Sheet1", "columns": [], "rows": [], "mapping": {}}]
        active = raw.get("active") or ""
        if not any(s["key"] == active for s in sheets):
            active = sheets[0]["key"]
        return {"sheets": sheets, "active": active}
    return {"sheets": [{"key": "s1", "name": "Sheet1", "columns": raw.get("columns", []),
                        "rows": raw.get("rows", []), "mapping": {}}], "active": "s1"}


def sheet_of(workbook: dict, key: str) -> dict:
    for s in workbook.get("sheets", []):
        if s.get("key") == key:
            return s
    return {"key": key, "name": "Sheet1", "columns": [], "rows": [], "mapping": {}}


def auto_map(sheet: dict) -> dict:
    mapping = {}
    for row in sheet.get("rows", []):
        key = row.get("key", "")
        if not key:
            continue
        field = row.get("field", "")
        if field:
            mapping[field] = key
            continue
        matched = match_field(row.get("label", ""))
        if matched and matched not in mapping:
            mapping[matched] = key
    return mapping


def cell_value(sheet: dict, row_key: str, col_key: str) -> float | None:
    for row in sheet.get("rows", []):
        if row.get("key") != row_key:
            continue
        cell = row.get("cells", {}).get(col_key)
        if cell is None:
            return None
        if isinstance(cell, (int, float)):
            return float(cell)
        if isinstance(cell, str):
            try:
                return float(cell.replace(",", "").strip())
            except ValueError:
                return None
        if isinstance(cell, dict):
            v = cell.get("value")
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, str):
                try:
                    return float(v.replace(",", "").strip())
                except ValueError:
                    return None
    return None


def unit_factor(unit: str) -> float:
    return {"元": 0.0001, "亿元": 10000.0}.get(unit, 1.0)


def validate(doc: dict) -> dict:
    issues: list[dict] = []

    def push(level, code, message, row="", col=""):
        issues.append({"level": level, "code": code, "message": message, "row": row, "col": col})

    if not doc.get("stock_code"):
        push("error", "NO_ENTERPRISE", "表格未绑定企业，入库前需要选择企业")
    columns = doc.get("sheet", {}).get("columns", [])
    if not columns:
        push("error", "NO_PERIOD", "至少需要一列期间（如 2025 年报）")
    seen: list[str] = []
    for c in columns:
        key = c.get("key", "")
        period = (c.get("period") or "").strip()
        if not period:
            push("error", "EMPTY_PERIOD", "存在没有期间的列（需填年份/报告期）", "", key)
        elif period in seen:
            push("warn", "DUP_PERIOD", f"期间 {period} 重复，入库时会互相覆盖", "", key)
        else:
            seen.append(period)

    mapping = doc.get("mapping", {})
    mapped = list(mapping.keys())
    if not any(k in mapped for k in ("revenue_wan", "net_profit_wan", "total_assets_wan")):
        push("error", "NO_CORE_FIELD", "尚未映射任何核心科目（营业收入 / 归母净利润 / 资产总计 至少其一）")
    if "total_assets_wan" not in mapped:
        push("warn", "NO_ASSETS", "缺「资产总计」：Z″ 值与 ROA 不可计算")
    if "ocf_wan" not in mapped:
        push("warn", "NO_OCF", "缺「经营活动现金流净额」：现金流质量与部分异常规则不可用")
    if len(seen) < 2:
        push("warn", "ONLY_ONE_PERIOD", "只有一期数据：同比、趋势与 Beneish M-Score 不可用")

    sheet = doc.get("sheet", {})
    unconfirmed: list[str] = []
    for r in sheet.get("rows", []):
        row_key, label = r.get("key", ""), r.get("label") or r.get("key", "")
        for col, cell in (r.get("cells") or {}).items():
            if isinstance(cell, dict) and cell.get("source") == "vision":
                col_label = next((c.get("label") or col for c in columns if c.get("key") == col), col)
                unconfirmed.append(f"{label}@{col_label}")
    if unconfirmed:
        push("error", "VISION_UNCONFIRMED",
             f"有 {len(unconfirmed)} 个由图片识别的数字尚未确认（{'、'.join(unconfirmed[:5])}）——请在表格里核对后点「确认识别结果」")

    def get(field, col):
        rk = mapping.get(field)
        return cell_value(sheet, rk, col) if rk else None

    for c in columns:
        col, label = c.get("key", ""), c.get("label") or c.get("key", "")
        ta, tl, eq = get("total_assets_wan", col), get("total_liabilities_wan", col), get("equity_wan", col)
        if ta is not None and tl is not None and eq is not None:
            diff, tol = abs(ta - (tl + eq)), max(abs(ta) * 0.01, 1.0)
            if diff > tol:
                push("error", "BALANCE_MISMATCH", f"{label}：资产总计 {ta} ≠ 负债 {tl} + 权益 {eq}（差 {diff:.2f}）", "", col)
        elif ta is not None and tl is not None and eq is None:
            push("warn", "MISSING_EQUITY", f"{label}：缺「所有者权益合计」，无法做 资产=负债+权益 勾稽", "", col)
        if ta is not None and tl is not None and ta != 0:
            ratio = tl / ta * 100.0
            if ratio < 0 or ratio > 150:
                push("warn", "DEBT_RATIO_RANGE", f"{label}：推算资产负债率 {ratio:.2f}%，超出常见区间", "", col)
            dr = get("debt_ratio", col)
            if dr is not None and abs(dr - ratio) > 1.0:
                push("error", "DEBT_RATIO_MISMATCH", f"{label}：填写资产负债率 {dr:.2f}% 与推算值 {ratio:.2f}% 不一致", "", col)
        rev, np_ = get("revenue_wan", col), get("net_profit_wan", col)
        if rev is not None and np_ is not None:
            if rev == 0 and np_ != 0:
                push("warn", "REVENUE_ZERO", f"{label}：营业收入为 0 但有净利润，请核对", "", col)
            if rev != 0 and abs(np_) > abs(rev) * 3:
                push("warn", "PROFIT_OUTLIER", f"{label}：净利润与营业收入量级差异过大，请核对单位", "", col)

    errors = sum(1 for i in issues if i["level"] == "error")
    warnings = sum(1 for i in issues if i["level"] == "warn")
    return {"ok": errors == 0, "errors": errors, "warnings": warnings, "issues": issues}


# ---------------------------------------------------------------------------
# 文档读写
# ---------------------------------------------------------------------------

def _to_doc(r: dict) -> dict:
    workbook = normalize_workbook(json.loads(r["sheet_json"] or "{}"))
    active = workbook.get("active", "s1")
    s = sheet_of(workbook, active)
    return {
        "id": r["id"], "stock_code": r["stock_code"], "title": r["title"], "kind": r["kind"],
        "unit": r["unit"], "scope": r["scope"], "period_type": r["period_type"], "currency": r["currency"],
        "sheet": {"columns": s.get("columns", []), "rows": s.get("rows", []), "meta": s.get("meta", {})},
        "workbook": workbook, "active": active, "mapping": json.loads(r["mapping_json"] or "{}"),
        "macros": json.loads(r["macro_json"] or "[]"), "status": r["status"], "version": r["version"],
        "origin": r["origin"], "note": r["note"], "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


def _write_back(doc: dict) -> None:
    for s in doc["workbook"].get("sheets", []):
        if s.get("key") == doc["active"]:
            s["columns"], s["rows"], s["mapping"] = doc["sheet"].get("columns", []), doc["sheet"].get("rows", []), doc["mapping"]
            return


def _persist(doc: dict, bump: bool) -> int:
    _write_back(doc)
    version = doc["version"] + 1 if bump else doc["version"]
    execute("UPDATE table_doc SET stock_code=?, title=?, kind=?, unit=?, scope=?, period_type=?, currency=?, "
            "sheet_json=?, mapping_json=?, macro_json=?, version=?, note=?, updated_at=? WHERE id=?",
           (doc["stock_code"], doc["title"], doc["kind"], doc["unit"], doc["scope"], doc["period_type"],
            doc["currency"], json.dumps(doc["workbook"], ensure_ascii=False),
            json.dumps(doc["mapping"], ensure_ascii=False), json.dumps(doc["macros"], ensure_ascii=False),
            version, doc["note"], datetime.utcnow().isoformat(), doc["id"]))
    doc["version"] = version
    return version


def get(table_id: int) -> dict | None:
    rows = query("SELECT * FROM table_doc WHERE id = ?", (table_id,))
    return _to_doc(rows[0]) if rows else None


def to_json(doc: dict) -> dict:
    return {"id": doc["id"], "stock_code": doc["stock_code"], "title": doc["title"], "kind": doc["kind"],
            "unit": doc["unit"], "scope": doc["scope"], "period_type": doc["period_type"],
            "sheet": doc["sheet"], "workbook": doc["workbook"], "active": doc["active"],
            "mapping": doc["mapping"], "status": doc["status"], "version": doc["version"],
            "origin": doc["origin"], "created_at": doc["created_at"], "updated_at": doc["updated_at"]}


def list_tables(stock_code: str | None = None, status: str | None = None) -> dict:
    sql = "SELECT t.*, e.name AS enterprise FROM table_doc t LEFT JOIN enterprise e ON e.stock_code = t.stock_code WHERE 1=1"
    params: list = []
    if stock_code:
        sql += " AND t.stock_code = ?"
        params.append(str(stock_code).strip().zfill(6))
    if status:
        sql += " AND t.status = ?"
        params.append(status)
    sql += " ORDER BY t.updated_at DESC, t.id DESC LIMIT 200"
    rows = query(sql, tuple(params))
    return {"total": len(rows), "items": [{
        "id": r["id"], "stock_code": r["stock_code"], "enterprise": r["enterprise"], "title": r["title"],
        "kind": r["kind"], "unit": r["unit"], "scope": r["scope"], "status": r["status"],
        "version": r["version"], "origin": r["origin"], "updated_at": r["updated_at"]} for r in rows]}


def create(stock_code: str | None, title: str, kind: str, periods: list[tuple[str, str]],
           unit: str, scope: str, period_type: str, origin: str) -> dict:
    if kind in ("blank", ""):
        sheet, mapping, sheet_name = blank_sheet(), {}, "Sheet1"
    else:
        sheet, mapping = build_sheet(kind, periods)
        sheet_name = next((t for k, t, _ in TEMPLATES if k == kind), "Sheet1")
    if not title.strip():
        title = next((f"{t}（新建）" for k, t, _ in TEMPLATES if k == kind), "空白表格")
    workbook = {"sheets": [{"key": "s1", "name": sheet_name, "columns": sheet["columns"],
                            "rows": sheet["rows"], "mapping": mapping}], "active": "s1"}
    table_id = execute(
        "INSERT INTO table_doc (stock_code, title, kind, unit, scope, period_type, sheet_json, mapping_json, status, origin) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)",
        (str(stock_code).strip().zfill(6) if stock_code else "", title.strip(), kind, unit, scope, period_type,
         json.dumps(workbook, ensure_ascii=False), json.dumps(mapping, ensure_ascii=False), origin))
    return {"table_id": table_id, "title": title.strip(), "kind": kind, "table": to_json(get(table_id))}


def update(table_id: int, body: dict) -> dict:
    doc = get(table_id)
    if doc is None:
        return {"error": f"表格不存在: {table_id}"}
    bump = False
    for key in ("title", "kind", "unit", "scope", "period_type", "currency", "note"):
        if body.get(key) is not None:
            doc[key] = body[key]
    if "stock_code" in body:
        doc["stock_code"] = str(body["stock_code"]).strip().zfill(6) if body.get("stock_code") else ""
    if body.get("sheet") is not None:
        doc["sheet"], bump = body["sheet"], True
    if body.get("mapping") is not None:
        doc["mapping"], bump = body["mapping"], True
    elif bump:
        doc["mapping"] = auto_map(doc["sheet"])
    if body.get("macros") is not None:
        doc["macros"] = body["macros"]
    version = _persist(doc, bump)
    return {"ok": True, "table_id": table_id, "version": version}


def _set_cell(sheet: dict, row_key: str, col_key: str, value, source: str, confidence: float) -> None:
    for row in sheet.get("rows", []):
        if row.get("key") != row_key:
            continue
        cells = row.setdefault("cells", {})
        if value is None:
            cells.pop(col_key, None)
            return
        if isinstance(value, (int, float)):
            num = float(value)
        elif isinstance(value, str):
            try:
                num = float(value.replace(",", "").strip())
            except ValueError:
                num = 0.0
        else:
            num = 0.0
        cells[col_key] = {"value": num, "raw": value, "source": source, "confidence": confidence}
        return


def write_cells(table_id: int, body: dict) -> dict:
    doc = get(table_id)
    if doc is None:
        return {"error": f"表格不存在: {table_id}"}
    source, confidence, written = body.get("source", "user"), body.get("confidence", 1.0), 0
    if body.get("row") and body.get("col") and "value" in body:
        _set_cell(doc["sheet"], body["row"], body["col"], body["value"], source, confidence)
        written += 1
    if body.get("row") and body.get("cells"):
        for col, value in body["cells"].items():
            _set_cell(doc["sheet"], body["row"], col, value, source, confidence)
            written += 1
    if not written:
        return {"error": "没有可写入的单元格（需要 row/col/value 或 row/cells）"}
    doc["mapping"] = auto_map(doc["sheet"])
    version = _persist(doc, True)
    execute("UPDATE table_doc SET status = CASE WHEN status = 'ingested' THEN 'confirmed' ELSE status END WHERE id = ?", (table_id,))
    return {"ok": True, "table_id": table_id, "written": written, "version": version}


def confirm_cells(table_id: int, cells: list[dict]) -> dict:
    doc = get(table_id)
    if doc is None:
        return {"error": f"表格不存在: {table_id}"}
    targets = []
    if not cells:
        for r in doc["sheet"].get("rows", []):
            for col, cell in (r.get("cells") or {}).items():
                if isinstance(cell, dict) and cell.get("source") == "vision":
                    targets.append((r["key"], col))
    else:
        targets = [(c.get("row"), c.get("col")) for c in cells if c.get("row") and c.get("col")]
    confirmed = 0
    for row_key, col_key in targets:
        for r in doc["sheet"].get("rows", []):
            if r.get("key") != row_key:
                continue
            cell = (r.get("cells") or {}).get(col_key)
            if isinstance(cell, dict):
                cell["source"], cell["confidence"], cell["confirmed_at"] = "user", 1.0, datetime.utcnow().isoformat()
                confirmed += 1
    _persist(doc, False)
    execute("UPDATE table_doc SET status = CASE WHEN status = 'draft' THEN 'confirmed' ELSE status END WHERE id = ?", (table_id,))
    return {"ok": True, "table_id": table_id, "confirmed": confirmed}


def delete(table_id: int) -> dict:
    n = execute("DELETE FROM table_doc WHERE id = ?", (table_id,))
    return {"error": f"表格不存在: {table_id}"} if not n else {"deleted": table_id}


def ingest(table_id: int, overwrite: bool = False) -> dict:
    doc = get(table_id)
    if doc is None:
        return {"error": f"表格不存在: {table_id}"}
    if not doc["stock_code"]:
        return {"error": "表格未绑定企业，无法入库"}
    check = validate(doc)
    if not check["ok"]:
        return {"error": "勾稽校验未通过，已阻止入库", "validation": check}

    factor, source_tag = unit_factor(doc["unit"]), f"用户提供（{'在线表格' if doc['origin'] == 'manual' else doc['origin']} #{doc['id']}）"
    created, updated, skipped, conflicts = [], [], [], []
    stock_code = doc["stock_code"]

    for c in doc["sheet"].get("columns", []):
        col, period = c.get("key", ""), (c.get("period") or "").strip()
        if not period:
            continue
        report_type = c.get("report_type") or doc["period_type"]
        metrics = {}
        for field, rk in doc["mapping"].items():
            raw = cell_value(doc["sheet"], rk, col)
            if raw is None:
                continue
            metrics[field] = round((raw * factor if field.endswith("_wan") else raw) * 10000) / 10000
        if not metrics:
            continue
        num = lambda k: metrics.get(k, 0.0)  # noqa: E731
        existing = query("SELECT id, source FROM finance WHERE stock_code = ? AND year = ? AND report_type = ?",
                         (stock_code, period, report_type))
        if existing:
            e = existing[0]
            if "用户提供" not in (e["source"] or "") and not overwrite:
                conflicts.append({"period": period, "report_type": report_type,
                                  "reason": "已有公开信源数据，默认不覆盖", "public_source": e["source"]})
                skipped.append({"period": period, "report_type": report_type})
                continue
            execute("UPDATE finance SET total_assets=?, total_liabilities=?, revenue=?, net_profit=?, debt_ratio=?, source=?, metrics_json=? WHERE id=?",
                   (num("total_assets_wan"), num("total_liabilities_wan"), num("revenue_wan"), num("net_profit_wan"),
                    num("debt_ratio"), source_tag, json.dumps(metrics, ensure_ascii=False), e["id"]))
            updated.append({"period": period, "report_type": report_type})
        else:
            execute("INSERT INTO finance (stock_code, year, report_type, total_assets, total_liabilities, revenue, net_profit, debt_ratio, source, metrics_json) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (stock_code, period, report_type, num("total_assets_wan"), num("total_liabilities_wan"),
                    num("revenue_wan"), num("net_profit_wan"), num("debt_ratio"), source_tag,
                    json.dumps(metrics, ensure_ascii=False)))
            created.append({"period": period, "report_type": report_type})

    execute("UPDATE table_doc SET status='ingested', updated_at=? WHERE id=?", (datetime.utcnow().isoformat(), table_id))
    return {"ok": True, "table_id": table_id, "stock_code": stock_code, "unit": doc["unit"],
            "source": source_tag, "created": created, "updated": updated, "skipped": skipped,
            "conflicts": conflicts, "validation": check}


def preview_ingest(table_id: int) -> dict:
    doc = get(table_id)
    if doc is None:
        return {"error": f"表格不存在: {table_id}"}
    if not doc["stock_code"]:
        return {"error": "表格未绑定企业"}
    plan = []
    for c in doc["sheet"].get("columns", []):
        period = (c.get("period") or "").strip()
        if not period:
            continue
        report_type = c.get("report_type") or doc["period_type"]
        existing = query("SELECT source FROM finance WHERE stock_code = ? AND year = ? AND report_type = ?",
                         (doc["stock_code"], period, report_type))
        src = existing[0]["source"] if existing else None
        action = "create" if src is None else ("update" if "用户提供" in (src or "") else "conflict")
        plan.append({"period": period, "report_type": report_type, "action": action, "existing_source": src})
    return {"table_id": table_id, "stock_code": doc["stock_code"], "unit": doc["unit"],
            "plan": plan, "validation": validate(doc)}


def templates() -> dict:
    items = [{"kind": k, "title": t,
              "rows": [{"field": f, "label": _FIELD_BY_KEY[f]["label"] if f in _FIELD_BY_KEY else f} for f in rows]}
             for k, t, rows in TEMPLATES]
    fields = [{"key": f["key"], "label": f["label"], "kind": f["kind"], "unit": f["unit"], "aliases": f["aliases"]}
              for f in FIELDS]
    return {"templates": items, "fields": fields}
