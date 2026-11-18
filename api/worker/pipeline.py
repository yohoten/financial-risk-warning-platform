"""接入后闭环与 pull 任务执行：缓存失效 → 重打分 → 预警判定 → SSE 推送（设计稿 §5.4）。

关键联动点说明（设计稿 §4.4 的风险项）：
规则评分（rules.py）与 ML 推理（models/predict.py）读取的是 CSMAR 契约表（parquet），
入库到 sqlite 业务表（finance/news/legal_record）**不会改变契约表本身**。因此这里的
``invalidate_score_caches`` 是为「契约表经 ETL 刷新后」的重打分兜底，并保证预警工单
按最新进程内缓存重新判定（指纹去重、幂等）。要真正让新接入数据改变 ML 分数，需在
下游再跑 ``etl`` 增量特征 + ``models.predict --refresh``（P3 后续，不引入常驻热打分）。
"""

from __future__ import annotations

import json

from api.ingest.events import bus


def _cached_callables() -> list:
    """评分链路中带 cache_clear 的缓存函数（惰性收集，避免硬依赖）。"""
    out = []
    for mod_name, names in (
        ("api.services.rules", ("_panel",)),
        ("api.services.finance", ("_panel",)),
        ("api.services", ("_meta",)),
        ("models.predict", ("load_model", "load_meta")),
    ):
        try:
            import importlib

            mod = importlib.import_module(mod_name)
            for n in names:
                fn = getattr(mod, n, None)
                if fn is not None and hasattr(fn, "cache_clear"):
                    out.append(fn)
        except Exception:  # noqa: BLE001 —— 模块缺失/模型未训练不影响闭环
            continue
    return out


def invalidate_score_caches() -> None:
    """失效评分链路涉及的进程内缓存（lru_cache）。"""
    for fn in _cached_callables():
        try:
            fn.cache_clear()
        except Exception:  # noqa: BLE001
            pass


def close_loop(codes, source: str = "ingest") -> dict:
    """对受影响代码重打分并生成/更新预警工单，推送 SSE 事件（幂等，指纹去重）。"""
    invalidate_score_caches()
    codes = [str(c).strip().zfill(6) for c in codes if str(c).strip()]
    results = []
    for code in codes:
        try:
            from api.services import alerts

            r = alerts.generate_for_enterprise(code, source=source)
            created = r.get("created", [])
            results.append({
                "stock_code": code, "created": len(created),
                "skipped": r.get("skipped", 0),
            })
            if created:
                bus.publish("alert.new", {
                    "stock_code": code, "count": len(created), "source": source,
                })
        except Exception as exc:  # noqa: BLE001 —— 单代码失败不阻断整体
            results.append({"stock_code": code, "error": f"{type(exc).__name__}: {exc}"})

    bus.publish("score.refreshed", {"codes": codes, "source": source, "count": len(codes)})
    return {"codes": len(codes), "results": results}


def pull_and_close(codes, dimensions=None, source: str = "pull") -> dict:
    """pull 一批企业并触发闭环（供手工触发与调度器复用）。"""
    from api.datasources import registry

    pulled = []
    for code in codes:
        try:
            pulled.append(registry.pull_enterprise(code, dimensions))
        except Exception as exc:  # noqa: BLE001
            pulled.append({"stock_code": code, "error": f"{type(exc).__name__}: {exc}"})
    closed = close_loop(codes, source=source)
    return {"pulled": pulled, "closed": closed}


def run_pull_dimension(dimension: str, source_name: str = "", task_name: str = "") -> dict:
    """执行一次维度拉取任务（tracked_codes → pull_enterprise → close_loop → ingest_log 落库）。"""
    from api.datasources import registry

    codes = registry.tracked_codes()
    if not codes:
        _write_ingest_log(task_name, "pull", dimension, "success",
                          detail={"skipped": "no_tracked_codes"})
        return {"skipped": True, "codes": 0}

    inserted = updated = 0
    errors: list[str] = []
    for code in codes:
        try:
            r = registry.pull_enterprise(code, [dimension])
            for v in r["dimensions"].values():
                if v.get("ok"):
                    inserted += v.get("inserted", 0)
                    updated += v.get("updated", 0)
                else:
                    errors.append(f"{code}:{v.get('error') or v.get('gap')}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{code}:{type(exc).__name__}:{exc}")

    status = "success" if not errors else "partial"
    _write_ingest_log(task_name, "pull", dimension, status, inserted=inserted, updated=updated,
                      error="; ".join(errors[:20]),
                      detail={"codes": len(codes), "errors": len(errors)})
    close_loop(codes, source="pull")
    return {"codes": len(codes), "inserted": inserted, "updated": updated, "errors": len(errors)}


def _write_ingest_log(task: str, channel: str, dimension: str, status: str,
                      inserted: int = 0, updated: int = 0, error: str = "",
                      detail: dict | None = None) -> None:
    from api.db.database import execute

    execute(
        "INSERT INTO ingest_log (task, channel, trigger_by, dimension, status, inserted, updated,"
        " error, detail_json, finished_at) VALUES (?,?,?,?,?,?,?,?,?,datetime('now','localtime'))",
        (task or f"pull_{dimension}", channel, "worker", dimension, status, inserted, updated,
         error, json.dumps(detail or {}, ensure_ascii=False)),
    )
