"""确定性表格导入：CSV / XLSX / 粘贴 TSV（无需模型）。"""

from __future__ import annotations

import csv
import io
import re

from api.db import execute
from api.services.tables import match_field, _FIELD_BY_KEY


def parse_delimited(text: str) -> list[list[str]]:
    """自动识别分隔符（Tab 优先，其次逗号/分号），返回二维字符串网格。"""
    text = (text or "").strip("\ufeff")
    sample = text[:2000]
    delim = "\t"
    if sample.count("\t") == 0 and sample.count(",") > sample.count(";"):
        delim = ","
    elif sample.count("\t") == 0 and sample.count(";") > 0:
        delim = ";"
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    return [[c.strip() for c in row] for row in rows if any(c.strip() for c in row)]


def parse_workbook(data: bytes) -> list[list[str]]:
    """解析 xlsx/xls 第一个工作表为字符串网格。"""
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    grid = []
    for row in ws.iter_rows(values_only=True):
        cells = [("" if c is None else str(c)).strip() for c in row]
        if any(cells):
            grid.append(cells)
    return grid


def _is_year(s: str) -> bool:
    return bool(re.fullmatch(r"(20|19)\d{2}", s))


def _num(s: str) -> float | None:
    t = s.replace(",", "").strip()
    t = t.replace("（", "(").replace("）", ")")
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    if t.endswith("%"):
        try:
            return -float(t[:-1]) if neg else float(t[:-1])
        except ValueError:
            return None
    try:
        return -float(t) if neg else float(t)
    except ValueError:
        return None


def detect_meta(grid: list[list[str]]) -> dict:
    """探测单位与口径。"""
    unit, scope = "", ""
    for row in grid[:6]:
        for c in row:
            for u in ("万元", "亿元", "元"):
                if u in c:
                    unit = unit or u
            if "合并" in c:
                scope = scope or "合并报表"
            elif "母公司" in c or "本部" in c:
                scope = scope or "母公司报表"
    return {"unit": unit, "scope": scope}


def _header_index(grid: list[list[str]]) -> int:
    for i, row in enumerate(grid[:15]):
        hits = sum(1 for c in row if match_field(c))
        if hits >= 2:
            return i
    return 0


def extract(grid: list[list[str]]) -> dict:
    """识别宽表/长表，输出 {period: {field: value}}。"""
    hi = _header_index(grid)
    header = grid[hi]
    # 期间列：表头单元格形如年份（2025/2024…）
    period_cols = [(j, header[j]) for j in range(1, len(header)) if _is_year(header[j])]
    if not period_cols:
        # 长表：期间在某一列
        result: dict[str, dict] = {}
        for row in grid[hi + 1:]:
            if len(row) < 3:
                continue
            field = match_field(row[0])
            if not field:
                continue
            period = next((c for c in row if _is_year(c)), "")
            value = next((_num(c) for c in row if _num(c) is not None), None)
            if period and value is not None:
                result.setdefault(period, {})[field] = value
        return result

    result: dict[str, dict] = {}
    for row in grid[hi + 1:]:
        if not row:
            continue
        field = match_field(row[0])
        if not field:
            continue
        for j, period in period_cols:
            if j < len(row):
                v = _num(row[j])
                if v is not None:
                    result.setdefault(period, {})[field] = v
    return result


def _create_from_ext(ext: dict, stock_code: str | None, title: str, unit: str, scope: str,
                     origin: str, source: str, confidence: float) -> dict:
    periods = sorted(ext.keys())
    fields: list[str] = []
    for p in periods:
        for f in ext[p]:
            if f not in fields:
                fields.append(f)

    columns = [{"key": f"c{i + 1}", "label": f"{p}年报", "period": p, "report_type": "年报", "type": "number"}
               for i, p in enumerate(periods)]
    rows = []
    mapping = {}
    for i, f in enumerate(fields):
        rk = f"r{i + 1}"
        rows.append({"key": rk, "label": _FIELD_BY_KEY[f]["label"] if f in _FIELD_BY_KEY else f,
                     "field": f, "cells": {}})
        mapping[f] = rk
    for j, p in enumerate(periods):
        for f, v in ext[p].items():
            rk = mapping.get(f)
            if rk:
                rows[int(rk[1:]) - 1]["cells"][f"c{j + 1}"] = {"value": v, "source": source, "confidence": confidence}

    sheet = {"columns": columns, "rows": rows, "meta": {}}
    workbook = {"sheets": [{"key": "s1", "name": "Sheet1", "columns": columns, "rows": rows, "mapping": mapping}],
                "active": "s1"}
    import json
    from api.services.tables import get
    table_id = execute(
        "INSERT INTO table_doc (stock_code, title, kind, unit, scope, period_type, sheet_json, mapping_json, status, origin) "
        "VALUES (?, ?, 'kpi', ?, ?, '年报', ?, ?, 'confirmed', ?)",
        (str(stock_code).strip().zfill(6) if stock_code else "", title, unit, scope,
         json.dumps(workbook, ensure_ascii=False), json.dumps(mapping, ensure_ascii=False), origin))
    return {"table_id": table_id, "title": title, "detected_periods": periods, "fields": fields,
            "table": get(table_id)}


def build_table(grid: list[list[str]], stock_code: str | None, title: str, unit: str, scope: str) -> dict:
    ext = extract(grid)
    if not ext:
        return {"error": "未识别出任何财务科目与期间"}
    return _create_from_ext(ext, stock_code, title, unit, scope, "import", "file", 1.0)


def build_flat(grid: list[list[str]], stock_code: str | None, title: str, unit: str, scope: str) -> dict:
    """保持长表原样导入（不做透视），供后续数据透视表处理。"""
    hi = _header_index(grid)
    header = grid[hi]
    columns = [{"key": f"c{i + 1}", "label": header[i] or f"列{i + 1}", "period": "", "report_type": "", "type": "number"}
               for i in range(len(header))]
    rows = []
    for i, row in enumerate(grid[hi + 1:]):
        cells = {}
        for j, v in enumerate(row):
            if j < len(columns):
                cells[columns[j]["key"]] = {"value": v, "source": "file", "confidence": 1.0}
        rows.append({"key": f"r{i + 1}", "label": row[0] if row else "", "field": match_field(row[0]) if row else "", "cells": cells})
    sheet = {"columns": columns, "rows": rows, "meta": {}}
    mapping = {}
    import json
    from api.services.tables import get
    workbook = {"sheets": [{"key": "s1", "name": "Sheet1", "columns": columns, "rows": rows, "mapping": mapping}], "active": "s1"}
    table_id = execute(
        "INSERT INTO table_doc (stock_code, title, kind, unit, scope, period_type, sheet_json, mapping_json, status, origin) "
        "VALUES (?, ?, 'flat', ?, ?, '年报', ?, ?, 'draft', 'import')",
        (str(stock_code).strip().zfill(6) if stock_code else "", title, unit, scope,
         json.dumps(workbook, ensure_ascii=False), json.dumps(mapping, ensure_ascii=False)))
    return {"table_id": table_id, "title": title, "keep_long": True, "table": get(table_id)}
