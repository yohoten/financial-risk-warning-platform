"""领域服务层。

- 本文件：核心评分/解释/监控的薄封装（原 ``api/services.py`` 迁入，避免与包同名冲突）；
- ``finance.py``：财务分析（阶段 1 移植）；
- ``rules.py``：规则六维评分（阶段 1 移植）；
- ``alerts.py``：预警闭环（规则触发 → 人工处置 → 流水留痕，SQLite 持久化）。

约定：所有成功响应带 ``run_id`` 与 ``semantics``；未匹配代码进 ``unmatched``。
"""

from __future__ import annotations

import json
from functools import lru_cache

import numpy as np

from config import settings

SEMANTICS = "特征年 T → 标签年 T+2 的 ST 风险概率"


class ServiceUnavailable(Exception):
    """模型/数据缺失等可恢复错误，映射为 503。"""


def _model_ready() -> dict:
    return {
        "model": settings.MODEL_PATH.exists(),
        "meta": settings.MODEL_META.exists(),
        "panel": (settings.FEATURE_MATRIX.exists() or settings.FEATURE_PANEL.exists()),
    }


@lru_cache(maxsize=1)
def _meta() -> dict:
    if not settings.MODEL_META.exists():
        raise ServiceUnavailable("未找到模型元信息，请先运行 python -m models.train")
    return json.loads(settings.MODEL_META.read_text(encoding="utf-8"))


def _default_thresholds() -> dict[str, float]:
    return _meta().get("risk_thresholds", {"high": 0.5, "medium": 0.25})


def _level(prob: float, high: float, medium: float) -> str:
    if prob >= high:
        return "高风险"
    if prob >= medium:
        return "中风险"
    return "低风险"


def health() -> dict:
    from models.shap_analysis import cache_status

    meta = None
    if settings.MODEL_META.exists():
        try:
            meta = json.loads(settings.MODEL_META.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = None

    ready = _model_ready()
    healthy = all(ready.values())
    return {
        "status": "ok" if healthy else "degraded",
        "run_id": (meta or {}).get("run_id", "unknown"),
        "artifacts": ready,
        "shap": cache_status() if settings.MODEL_META.exists() else {},
    }


def model_meta() -> dict:
    return {
        **_meta(),
        "semantics": SEMANTICS,
    }


def predict_codes(codes: list[str], year: int | None = None,
                  threshold_override: dict[str, float] | None = None) -> dict:
    from models.predict import load_panel_for_inference, predict_frame

    if not _model_ready()["model"]:
        raise ServiceUnavailable("未找到模型文件，请先运行 python -m models.train")

    panel = load_panel_for_inference()
    codes = [c.zfill(6) for c in codes]
    subset = panel[panel["stock_code"].isin(codes)]
    if year is not None:
        subset = subset[subset["year"] == year]
    else:
        subset = subset.sort_values("year").groupby("stock_code", as_index=False).tail(1)

    unmatched = [c for c in codes if c not in set(subset["stock_code"])]
    if subset.empty:
        return {"run_id": _meta().get("run_id"), "semantics": SEMANTICS,
                "items": [], "unmatched": unmatched}

    scored = predict_frame(subset)
    thr = threshold_override or _default_thresholds()
    high, medium = float(thr["high"]), float(thr["medium"])
    scored["risk_level"] = scored["st_prob"].map(lambda p: _level(p, high, medium))

    items = []
    keep = ["stock_code", "company_name", "industry", "year", "st_prob_raw", "st_prob",
            "risk_level", "risk_percentile"]
    for _, row in scored.sort_values("st_prob", ascending=False).iterrows():
        item = {k: (None if isinstance(row[k], float) and np.isnan(row[k]) else row[k])
                for k in keep if k in scored.columns}
        items.append(item)
    return {"run_id": _meta().get("run_id"), "semantics": SEMANTICS,
            "items": items, "unmatched": unmatched}


def top_risk(year: int | None = None, limit: int = 50, industry: str | None = None) -> dict:
    from models.predict import load_predictions

    scored = load_predictions()
    if year is None:
        year = int(scored["year"].max())
    out = scored[scored["year"] == year]
    if industry:
        out = out[out["industry"].astype(str) == industry]
    out = out.sort_values("st_prob", ascending=False).head(limit)
    keep = ["stock_code", "company_name", "industry", "year", "st_prob", "risk_level",
            "risk_percentile"]
    return {
        "run_id": _meta().get("run_id"), "year": year, "semantics": SEMANTICS,
        "items": out[keep].to_dict("records"),
    }


def explain(code: str, year: int | None = None) -> dict:
    from models.shap_analysis import local_contribution

    result = local_contribution(code, year)
    result["contributions"] = result["contributions"].to_dict("records")
    result["all_contributions"] = result["all_contributions"].to_dict("records")
    result["semantics"] = SEMANTICS
    return result


def global_importance(top_n: int = 20) -> dict:
    from models.shap_analysis import global_importance as _gi

    return {"items": _gi(top_n).to_dict("records")}


def dependence(feature: str) -> dict:
    from models.shap_analysis import dependence as _dep

    df = _dep(feature)
    # 依赖散点降采样：全量 2 万+ 点对前端过重，抽样 2000 点仍能呈现非线性拐点
    if len(df) > 2000:
        df = df.sample(2000, random_state=42)
    return {"feature": feature, "items": df.to_dict("records")}


def interactions(top_n: int = 8) -> dict:
    from models.shap_analysis import interaction_pairs

    return {"note": "代理指标（重要性加权相关性），非 TreeSHAP 精确交互值",
            "items": interaction_pairs(top_n).to_dict("records")}


def monitor_report() -> dict:
    if settings.MONITOR_REPORT.exists():
        return json.loads(settings.MONITOR_REPORT.read_text(encoding="utf-8"))
    return {"available": False, "hint": "请先运行 python -m models.monitor"}


def feature_dictionary() -> dict:
    from config.feature_registry import to_records

    return {"items": to_records()}
