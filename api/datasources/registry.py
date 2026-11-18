"""数据源注册表：按维度选择数据源 + 降级链 + 多信源合并 + 幂等入库（pull 通道）。

移植自旧项目 `server/app/datasources/registry.py`，把 SQLAlchemy ORM 改为本项目
`api.db.database` 的裸 sqlite3（``finance`` / ``news`` / ``legal_record`` 业务表）。
"""

from __future__ import annotations

import json

from api.datasources.akshare_src import akshare_source
from api.datasources.announcement_src import announcement_source
from api.datasources.base import DataSource, FetchResult
from api.datasources.sina_src import sina_source

# 维度 → 数据源优先级（靠前者优先；news/finance 维度多信源合并）
SOURCES: dict[str, list[DataSource]] = {
    "finance": [akshare_source, sina_source],        # 东财摘要 + 新浪三表（字段级合并）
    "news": [akshare_source, announcement_source],   # 东财个股新闻 + 东财公告（合并）
    "legal": [akshare_source],                       # 巨潮诉讼统计
}
MERGE_DIMS = {"news", "finance"}


def fetch_dimension(stock_code: str, dimension: str) -> FetchResult:
    """按优先级拉取：news 合并多源；其余首个成功源生效。全部失败返回带 error/gap 的结果。"""
    sources = SOURCES.get(dimension, [])
    if not sources:
        return FetchResult(dimension, "none", error=f"无数据源: {dimension}")

    merged = []
    used: list[str] = []
    errors: list[str] = []
    gap = ""

    for source in sources:
        result = source.fetch(stock_code, dimension)
        if result.ok and result.records:
            merged.extend(result.records)
            used.append(result.source)
            if dimension not in MERGE_DIMS:
                break
        elif result.ok:
            used.append(result.source)
            if dimension not in MERGE_DIMS:
                break
        else:
            errors.append(f"{result.source}: {result.gap or result.error}")
            gap = gap or result.gap

    if merged:
        return FetchResult(dimension, "+".join(used), records=merged)
    if used:
        return FetchResult(dimension, "+".join(used), records=[])
    return FetchResult(dimension, "none", error="; ".join(errors), gap=gap)


def _load_json(raw) -> dict:
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def upsert_records(stock_code: str, result: FetchResult) -> dict:
    """幂等入库：财务按 (代码, 年份, 报告类型) 覆盖并做指标字段级合并；新闻/法律按标题去重。"""
    from api.db.database import execute, query

    inserted = updated = 0
    for rec in result.records:
        if rec.kind == "finance":
            payload = dict(rec.payload)
            incoming = _load_json(payload.pop("metrics_json", ""))
            row = query(
                "SELECT * FROM finance WHERE stock_code=? AND year=? AND report_type=?",
                (stock_code, payload.get("year"), payload.get("report_type")),
            )
            if not row:
                execute(
                    "INSERT INTO finance (stock_code, year, report_type, total_assets,"
                    " total_liabilities, revenue, net_profit, debt_ratio, source, metrics_json)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (stock_code, payload.get("year"), payload.get("report_type"),
                     payload.get("total_assets"), payload.get("total_liabilities"),
                     payload.get("revenue"), payload.get("net_profit"),
                     payload.get("debt_ratio"), payload.get("source", ""),
                     json.dumps(incoming, ensure_ascii=False)),
                )
                inserted += 1
            else:
                merged = _load_json(row[0]["metrics_json"])
                merged.update(incoming)
                src = row[0]["source"] or ""
                new_src = payload.get("source", "")
                if new_src and new_src not in src:
                    src = (f"{src}+{new_src}" if src else new_src)[:200]
                # 顶层字段：非零值才覆盖，避免缺失信源把已有数据清零
                def pick(col: str, v):
                    if v or not row[0][col]:
                        return v
                    return row[0][col]

                execute(
                    "UPDATE finance SET total_assets=?, total_liabilities=?, revenue=?,"
                    " net_profit=?, debt_ratio=?, source=?, metrics_json=? WHERE id=?",
                    (pick("total_assets", payload.get("total_assets")),
                     pick("total_liabilities", payload.get("total_liabilities")),
                     pick("revenue", payload.get("revenue")),
                     pick("net_profit", payload.get("net_profit")),
                     pick("debt_ratio", payload.get("debt_ratio")),
                     src, json.dumps(merged, ensure_ascii=False), row[0]["id"]),
                )
                updated += 1

        elif rec.kind == "news":
            exists = query("SELECT id FROM news WHERE stock_code=? AND title=?",
                           (stock_code, rec.payload.get("title")))
            if not exists:
                p = rec.payload
                execute(
                    "INSERT INTO news (stock_code, title, content, source, url, published_at,"
                    " sentiment) VALUES (?,?,?,?,?,?,?)",
                    (stock_code, p.get("title") or "", p.get("content") or "",
                     p.get("source") or "", p.get("url") or "",
                     p.get("published_at") or "", p.get("sentiment") or "neutral"),
                )
                inserted += 1

        elif rec.kind == "legal":
            exists = query("SELECT id FROM legal_record WHERE stock_code=? AND title=?",
                           (stock_code, rec.payload.get("title")))
            if not exists:
                p = rec.payload
                execute(
                    "INSERT INTO legal_record (stock_code, case_no, doc_type, title, court, cause,"
                    " amount, status, judgment_date, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (stock_code, p.get("case_no") or "", p.get("doc_type") or "",
                     p.get("title") or "", p.get("court") or "", p.get("cause") or "",
                     p.get("amount"), p.get("status") or "", p.get("judgment_date") or "",
                     p.get("source") or ""),
                )
                inserted += 1

    return {"inserted": inserted, "updated": updated}


def pull_enterprise(stock_code: str, dimensions: list[str] | None = None) -> dict:
    """从数据源拉取一家企业（返回每个维度的拉取/入库统计）。"""
    code = str(stock_code).strip().zfill(6)
    dims = dimensions or ["finance", "news", "legal"]
    out: dict = {"stock_code": code, "dimensions": {}}
    for dim in dims:
        result = fetch_dimension(code, dim)
        if not result.ok:
            out["dimensions"][dim] = {
                "ok": False, "source": result.source,
                "error": result.error, "gap": result.gap,
            }
            continue
        stats = upsert_records(code, result)
        out["dimensions"][dim] = {
            "ok": True, "source": result.source,
            "fetched": len(result.records), **stats,
        }
    return out


def tracked_codes(limit: int = 100) -> list[str]:
    """受跟踪企业（自建企业 + 关注清单）的代码列表，作为定时拉取范围。"""
    from api.db.database import query

    rows = query(
        "SELECT DISTINCT stock_code FROM enterprise"
        " WHERE stock_code != '' ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    codes = [r["stock_code"] for r in rows]
    watch = query("SELECT DISTINCT stock_code FROM user_enterprise")
    codes += [r["stock_code"] for r in watch]
    # 去重保序
    return list(dict.fromkeys(codes))
