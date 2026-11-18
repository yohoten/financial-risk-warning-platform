"""表格对象 API：在线创建 / 编辑 / 勾稽校验 / 入库。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.services import sheet_import, tables

router = APIRouter(prefix="/tables", tags=["tables"])


class CreateIn(BaseModel):
    stock_code: str | None = None
    title: str = ""
    kind: str = "kpi"
    periods: list | None = None
    unit: str = "万元"
    scope: str = "合并报表"
    period_type: str = "年报"
    origin: str = "manual"


class UpdateIn(BaseModel):
    title: str | None = None
    kind: str | None = None
    unit: str | None = None
    scope: str | None = None
    period_type: str | None = None
    stock_code: str | None = None
    note: str | None = None
    sheet: dict | None = None
    mapping: dict | None = None
    macros: list | None = None


class CellsIn(BaseModel):
    row: str | None = None
    col: str | None = None
    value: float | str | None = None
    cells: dict | None = None
    source: str = "user"
    confidence: float = 1.0


class ConfirmIn(BaseModel):
    cells: list[dict] = []


class IngestIn(BaseModel):
    overwrite: bool = False


class ImportIn(BaseModel):
    attachment_id: str | None = None
    text: str | None = None
    stock_code: str | None = None
    title: str = ""
    unit: str | None = None
    scope: str | None = None
    keep_long: bool = False


@router.get("")
def list_tables(stock_code: str | None = None, status: str | None = None):
    return tables.list_tables(stock_code, status)


@router.get("/templates")
def templates():
    return tables.templates()


@router.post("/import")
def import_table(body: ImportIn):
    if body.text and body.text.strip():
        grid = sheet_import.parse_delimited(body.text)
        title = body.title or "粘贴导入的表格"
    elif body.attachment_id:
        from api.services import attachments
        att = attachments.get(body.attachment_id)
        if att is None:
            raise HTTPException(404, f"附件不存在: {body.attachment_id}")
        data = attachments.read_bytes(body.attachment_id)
        grid = (sheet_import.parse_delimited(data.decode("utf-8", "ignore"))
                if att["mime"].endswith("csv") else sheet_import.parse_workbook(data))
        title = body.title or att["name"]
    else:
        raise HTTPException(400, "需要 attachment_id 或 text")

    meta = sheet_import.detect_meta(grid)
    unit = body.unit or meta.get("unit") or "万元"
    scope = body.scope or meta.get("scope") or "合并报表"
    result = (sheet_import.build_flat(grid, body.stock_code, title, unit, scope) if body.keep_long
              else sheet_import.build_table(grid, body.stock_code, title, unit, scope))
    if result.get("error"):
        raise HTTPException(400, result["error"])
    result["detected"] = {"unit": unit, "scope": scope, "meta": meta}
    return result


@router.post("")
def create_table(body: CreateIn):
    periods = _parse_periods(body.periods)
    result = tables.create(body.stock_code, body.title, body.kind, periods,
                           body.unit, body.scope, body.period_type, body.origin)
    return result


@router.get("/{table_id}")
def get_table(table_id: int):
    doc = tables.get(table_id)
    if doc is None:
        raise HTTPException(404, f"表格不存在: {table_id}")
    return tables.to_json(doc)


@router.patch("/{table_id}")
def update_table(table_id: int, body: UpdateIn):
    result = tables.update(table_id, body.model_dump(exclude_none=True))
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result


@router.post("/{table_id}/cells")
def write_cells(table_id: int, body: CellsIn):
    result = tables.write_cells(table_id, body.model_dump())
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.post("/{table_id}/validate")
def validate_table(table_id: int):
    doc = tables.get(table_id)
    if doc is None:
        raise HTTPException(404, f"表格不存在: {table_id}")
    return tables.validate(doc)


@router.get("/{table_id}/preview")
def preview(table_id: int):
    result = tables.preview_ingest(table_id)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.post("/{table_id}/ingest")
def ingest(table_id: int, body: IngestIn | None = None):
    result = tables.ingest(table_id, body.overwrite if body else False)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.post("/{table_id}/confirm")
def confirm(table_id: int, body: ConfirmIn | None = None):
    result = tables.confirm_cells(table_id, body.cells if body else [])
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result


@router.delete("/{table_id}")
def delete_table(table_id: int):
    result = tables.delete(table_id)
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result


def _parse_periods(raw) -> list[tuple[str, str]]:
    out = []
    for p in raw or []:
        if isinstance(p, str):
            out.append((p, "年报"))
        elif isinstance(p, list) and p:
            out.append((str(p[0]), str(p[1]) if len(p) > 1 else "年报"))
    return out or [("2025", "年报")]
