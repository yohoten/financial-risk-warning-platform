"""数据接入业务逻辑：机器推送（幂等 + 质量闸门 → 暂存）、入库合并、配置与日志。

流水线：外部 JSON → 严格 schema → 质量闸门 → ingest_staging（幂等）
        → consume_staging 合并进 finance/news/legal 业务表（worker/手动触发）
        → （后续 P3 阶段）增量特征 → 重打分 → 预警判定 → SSE 推送。
"""

from __future__ import annotations

import json
import time

from api.db.database import execute, query
from api.ingest import quality
from api.ingest.events import bus
from api.ingest.schemas import ITEM_MODELS


def _first_error(exc: Exception) -> str:
    """从 Pydantic ValidationError 提取第一条错误，压缩为可读字符串。"""
    try:
        errs = exc.errors()
        if errs:
            loc = ".".join(str(x) for x in errs[0].get("loc", []))
            msg = errs[0].get("msg", "")
            return f"{loc}:{msg}"
    except Exception:  # noqa: BLE001
        pass
    return str(exc)[:200]


# ---------------------------------------------------------------------------
# 通道 B：机器推送
# ---------------------------------------------------------------------------

def push(dimension: str, batch_id: str, items: list[dict], trigger_by: str = "") -> dict:
    """校验并落暂存；返回 accepted/rejected/duplicated。

    幂等：batch_id + (dimension, stock_code) 唯一约束，重推安全。
    """
    model_cls = ITEM_MODELS.get(dimension)
    if model_cls is None:
        return {"error": f"unsupported dimension {dimension}"}

    started = time.time()
    accepted = 0
    duplicated = 0
    rejected: list[dict] = []

    for idx, raw in enumerate(items):
        try:
            item = model_cls(**raw).model_dump()
        except Exception as exc:  # noqa: BLE001 —— schema 错误记入 rejected
            rejected.append({"index": idx, "reason": f"schema:{_first_error(exc)}"})
            continue

        ok, reason = quality.validate_item(dimension, item)
        if not ok:
            rejected.append({
                "index": idx, "stock_code": item.get("stock_code"), "reason": reason,
            })
            continue

        code = item["stock_code"]
        exists = query(
            "SELECT id FROM ingest_staging WHERE batch_id=? AND dimension=? AND stock_code=?",
            (batch_id, dimension, code),
        )
        if exists:
            duplicated += 1
            continue

        execute(
            "INSERT INTO ingest_staging (batch_id, dimension, stock_code, payload_json,"
            " quality_pass, quality_msg) VALUES (?,?,?,?,1,'')",
            (batch_id, dimension, code, json.dumps(item, ensure_ascii=False)),
        )
        accepted += 1

    status = "success" if accepted and not rejected else ("partial" if accepted else "failed")
    log_id = execute(
        "INSERT INTO ingest_log (task, channel, trigger_by, dimension, status, inserted,"
        " updated, error, detail_json, finished_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,datetime('now','localtime'))",
        (
            f"api_push_{dimension}", "push", trigger_by, dimension, status,
            accepted, 0, "",
            json.dumps({"batch_id": batch_id, "rejected": len(rejected),
                        "duplicated": duplicated}, ensure_ascii=False),
        ),
    )

    bus.publish("ingest.received", {
        "batch_id": batch_id, "dimension": dimension, "status": status,
        "accepted": accepted, "rejected": len(rejected),
        "duplicated": duplicated, "log_id": log_id,
    })

    return {
        "batch_id": batch_id, "dimension": dimension, "status": status,
        "accepted": accepted, "duplicated": duplicated, "rejected": rejected,
        "log_id": log_id, "elapsed_ms": int((time.time() - started) * 1000),
    }


# ---------------------------------------------------------------------------
# 入库合并（staging → 业务表）
# ---------------------------------------------------------------------------

def consume_staging(dimension: str | None = None, limit: int = 500) -> dict:
    """把质量合格的暂存数据合并进 finance/news/legal/market 业务层，并标记 consumed。

    由后台 worker 每日/实时消费；此处同时提供同步版供手动触发与测试。
    """
    from api.services.datasources import _save_market_cap

    clause = " WHERE consumed=0 AND quality_pass=1"
    params: list = []
    if dimension:
        clause += " AND dimension=?"
        params.append(dimension)
    rows = query(
        f"SELECT * FROM ingest_staging{clause} ORDER BY id ASC LIMIT ?",
        tuple(params) + (limit,),
    )

    inserted = 0
    updated = 0
    errors = 0
    affected: set[str] = set()
    for r in rows:
        try:
            payload = json.loads(r["payload_json"])
        except ValueError:
            execute("UPDATE ingest_staging SET consumed=1, quality_msg='bad_json' WHERE id=?",
                    (r["id"],))
            errors += 1
            continue

        dim = r["dimension"]
        code = r["stock_code"]
        affected.add(code)
        try:
            if dim == "finance":
                year = str(payload.get("year") or "")
                report_type = payload.get("report_type") or "年报"
                existing = query(
                    "SELECT id FROM finance WHERE stock_code=? AND year=? AND report_type=?",
                    (code, year, report_type),
                )
                metrics = {k: payload[k] for k in ("ocf", "roe", "unit")
                           if k in payload and payload[k] is not None}
                metrics_json = json.dumps(metrics, ensure_ascii=False)
                vals = (
                    payload.get("total_assets"), payload.get("total_liabilities"),
                    payload.get("revenue"), payload.get("net_profit"),
                    payload.get("debt_ratio"),
                )
                if existing:
                    execute(
                        "UPDATE finance SET total_assets=?, total_liabilities=?, revenue=?,"
                        " net_profit=?, debt_ratio=?, metrics_json=? WHERE id=?",
                        (*vals, metrics_json, existing[0]["id"]),
                    )
                    updated += 1
                else:
                    execute(
                        "INSERT INTO finance (stock_code, year, report_type, total_assets,"
                        " total_liabilities, revenue, net_profit, debt_ratio, source, metrics_json)"
                        " VALUES (?,?,?,?,?,?,?,?,'ingest',?)",
                        (code, year, report_type, *vals, metrics_json),
                    )
                    inserted += 1

            elif dim == "news":
                execute(
                    "INSERT INTO news (stock_code, title, content, source, url, published_at,"
                    " sentiment) VALUES (?,?,?,?,?,?,?)",
                    (code, payload.get("title") or "", payload.get("content") or "",
                     payload.get("source") or "", payload.get("url") or "",
                     payload.get("published_at") or "", payload.get("sentiment") or "neutral"),
                )
                inserted += 1

            elif dim == "legal":
                execute(
                    "INSERT INTO legal_record (stock_code, case_no, doc_type, title, court,"
                    " cause, amount, status, judgment_date, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (code, payload.get("case_no") or "", payload.get("doc_type") or "",
                     payload.get("title") or "", payload.get("court") or "",
                     payload.get("cause") or "", payload.get("amount"),
                     payload.get("status") or "", payload.get("judgment_date") or "",
                     payload.get("source") or ""),
                )
                inserted += 1

            elif dim == "market":
                mc = payload.get("market_cap")
                if mc is not None:
                    _save_market_cap(code, float(mc))
                inserted += 1

        except Exception as exc:  # noqa: BLE001 —— 单条失败不阻断整体
            execute("UPDATE ingest_staging SET quality_msg=? WHERE id=?",
                    (f"consume_error:{type(exc).__name__}:{exc}", r["id"]))
            errors += 1
            continue

        execute("UPDATE ingest_staging SET consumed=1 WHERE id=?", (r["id"],))

    return {"processed": len(rows), "inserted": inserted, "updated": updated,
            "errors": errors, "codes": sorted(affected)}


# ---------------------------------------------------------------------------
# 接入日志 / 暂存查询
# ---------------------------------------------------------------------------

def list_logs(*, page: int = 1, size: int = 50, dimension: str | None = None,
              status: str | None = None, channel: str | None = None) -> dict:
    where: list[str] = []
    params: list = []
    if dimension:
        where.append("dimension=?"); params.append(dimension)
    if status:
        where.append("status=?"); params.append(status)
    if channel:
        where.append("channel=?"); params.append(channel)
    clause = f" WHERE {' AND '.join(where)}" if where else ""

    total_rows = query(f"SELECT COUNT(*) AS n FROM ingest_log{clause}", tuple(params))
    total = int(total_rows[0]["n"]) if total_rows else 0
    size = max(1, min(int(size), 500))
    page = max(1, int(page))
    items = query(
        f"SELECT * FROM ingest_log{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        tuple(params) + (size, (page - 1) * size),
    )
    for r in items:
        raw = r.get("detail_json") or "{}"
        try:
            r["detail"] = json.loads(raw)
        except ValueError:
            r["detail"] = {}
        r.pop("detail_json", None)
    return {"total": total, "page": page, "size": size, "items": items}


def list_staging(*, dimension: str | None = None, quality_pass: int | None = None,
                 consumed: int | None = None, limit: int = 200) -> dict:
    where: list[str] = []
    params: list = []
    if dimension:
        where.append("dimension=?"); params.append(dimension)
    if quality_pass is not None:
        where.append("quality_pass=?"); params.append(int(quality_pass))
    if consumed is not None:
        where.append("consumed=?"); params.append(int(consumed))
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    items = query(
        f"SELECT * FROM ingest_staging{clause} ORDER BY id DESC LIMIT ?",
        tuple(params) + (min(int(limit), 1000),),
    )
    for r in items:
        try:
            r["payload"] = json.loads(r.get("payload_json") or "{}")
        except ValueError:
            r["payload"] = {}
        r.pop("payload_json", None)
    return {"total": len(items), "items": items}


# ---------------------------------------------------------------------------
# 数据源配置
# ---------------------------------------------------------------------------

def list_config() -> dict:
    rows = query("SELECT * FROM data_source_config ORDER BY dimension, priority")
    for r in rows:
        raw = r.get("config_json") or "{}"
        try:
            r["config"] = json.loads(raw)
        except ValueError:
            r["config"] = {}
        r.pop("config_json", None)
    return {"total": len(rows), "items": rows}


def upsert_config(dimension: str, source_name: str, *, label: str = "", enabled: bool = True,
                  priority: int = 0, merge_mode: str = "fallback", schedule_cron: str = "",
                  config: dict | None = None, updated_by: str = "") -> dict:
    config_json = json.dumps(config or {}, ensure_ascii=False)
    existing = query(
        "SELECT id FROM data_source_config WHERE dimension=? AND source_name=?",
        (dimension, source_name),
    )
    if existing:
        execute(
            "UPDATE data_source_config SET label=?, enabled=?, priority=?, merge_mode=?,"
            " schedule_cron=?, config_json=?, updated_by=?, updated_at=datetime('now','localtime')"
            " WHERE id=?",
            (label, int(enabled), priority, merge_mode, schedule_cron, config_json,
             updated_by, existing[0]["id"]),
        )
        return {"id": existing[0]["id"], "dimension": dimension,
                "source_name": source_name, "updated": True}
    cid = execute(
        "INSERT INTO data_source_config (dimension, source_name, label, enabled, priority,"
        " merge_mode, schedule_cron, config_json, updated_by) VALUES (?,?,?,?,?,?,?,?,?)",
        (dimension, source_name, label, int(enabled), priority, merge_mode,
         schedule_cron, config_json, updated_by),
    )
    return {"id": cid, "dimension": dimension, "source_name": source_name, "updated": False}


def delete_config(config_id: int) -> dict:
    execute("DELETE FROM data_source_config WHERE id=?", (config_id,))
    return {"ok": True, "id": config_id}


def seed_default_sources() -> int:
    """把 datasources.py 硬编码注册表同步进 data_source_config（幂等）。"""
    from api.services.datasources import MERGE_DIMS, SOURCES

    count = 0
    for dimension, sources in SOURCES.items():
        merge_mode = "merge" if dimension in MERGE_DIMS else "fallback"
        for idx, s in enumerate(sources):
            existing = query(
                "SELECT id FROM data_source_config WHERE dimension=? AND source_name=?",
                (dimension, s["name"]),
            )
            if existing:
                continue
            upsert_config(dimension, s["name"], label=s.get("label", ""),
                          priority=idx, merge_mode=merge_mode,
                          config={"dims": s.get("dims", [])})
            count += 1
    return count
