"""驾驶舱聚合接口（工作台总览 / 风险事实）。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from api.db import query
from api.services.rules import DIM_META

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

DIM_LABEL = dict(DIM_META)


def _predictions_summary() -> dict:
    from models.predict import load_predictions
    df = load_predictions()
    if df is None or df.empty:
        return {"enterprise_total": 0, "avg_st_prob": None, "level_counts": {}, "top_risk": []}
    rows = df.sort_values("year").groupby("stock_code", as_index=False).tail(1)
    level_counts = {"red": 0, "orange": 0, "yellow": 0, "green": 0}

    def _lv(p: float) -> str:
        if p >= 0.5:
            return "red"
        if p >= 0.25:
            return "orange"
        if p >= 0.10:
            return "yellow"
        return "green"

    for p in rows["st_prob"]:
        level_counts[_lv(float(p))] += 1
    top = rows.nlargest(20, "st_prob")[["stock_code", "st_prob", "risk_level"]]
    return {"enterprise_total": int(len(rows)), "avg_st_prob": round(float(rows["st_prob"].mean()), 4),
            "level_counts": level_counts,
            "top_risk": [{"stock_code": r["stock_code"], "st_prob": round(float(r["st_prob"]), 4),
                          "risk_level": r["risk_level"]} for _, r in top.iterrows()]}


@router.get("/summary")
def dashboard_summary():
    pred = _predictions_summary()
    facts = query("SELECT * FROM risk_fact ORDER BY ts DESC LIMIT 12")
    return {**pred, "fact_total": query("SELECT COUNT(*) AS n FROM risk_fact")[0]["n"],
            "recent_facts": [{"stock_code": f["stock_code"], "dimension": f["dimension"],
                              "dimension_label": DIM_LABEL.get(f["dimension"], f["dimension"]),
                              "text": f["text"], "ts": f["ts"]} for f in facts]}


@router.get("/risk-facts")
def list_risk_facts(dimension: str | None = Query(None), stock_code: str | None = Query(None),
                    limit: int = Query(100, le=500)):
    sql = "SELECT * FROM risk_fact"
    cond, params = [], []
    if dimension:
        cond.append("dimension = ?")
        params.append(dimension)
    if stock_code:
        cond.append("stock_code = ?")
        params.append(str(stock_code).strip().zfill(6))
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    rows = query(sql, tuple(params))
    return {"total": len(rows), "items": [
        {"id": r["id"], "stock_code": r["stock_code"], "dimension": r["dimension"],
         "dimension_label": DIM_LABEL.get(r["dimension"], r["dimension"]), "text": r["text"],
         "confidence": r["confidence"], "ts": r["ts"]} for r in rows]}
