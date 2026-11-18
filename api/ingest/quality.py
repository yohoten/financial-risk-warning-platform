"""质量闸门：复用 scripts/validate_raw_data 的规则思路（主键存在性、值域、极值预警）。

对每条接入记录做轻量校验，不合格的写入 ingest_staging.quality_pass=false，
数据接入中心可查看/导出错误明细。注意：这里只做"显式非法"拦截，不引入
训练窗口分位点（缩尾由 ETL 阶段统一处理，避免入口层重复造口径）。
"""

from __future__ import annotations

import re

_CODE_RE = re.compile(r"^(?:\d{6}|M\d+)$")

# 各维度显式值域（越界即拒收）
_FINANCE_RANGES: tuple[tuple[str, float, float], ...] = (
    ("debt_ratio", 0.0, 150.0),
    ("roe", -100.0, 100.0),
)

_FINANCE_NONNEGATIVE: tuple[str, ...] = (
    "revenue", "net_profit", "total_assets", "total_liabilities",
)


def _to_float(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN → None


def validate_item(dimension: str, item: dict) -> tuple[bool, str]:
    """返回 (是否合格, 原因)；原因是空串表示合格。"""
    code = str(item.get("stock_code") or "").strip()
    if not _CODE_RE.match(code):
        return False, "stock_code 非法（需 6 位数字或 M 前缀合成码）"

    if dimension == "finance":
        if not item.get("year"):
            return False, "finance 缺失 year"
        for key, lo, hi in _FINANCE_RANGES:
            v = item.get(key)
            if v is None:
                continue
            f = _to_float(v)
            if f is None:
                return False, f"{key} 非数值"
            if not (lo <= f <= hi):
                return False, f"{key} 越界（{lo}~{hi}）"
        for key in _FINANCE_NONNEGATIVE:
            v = item.get(key)
            if v is None:
                continue
            f = _to_float(v)
            if f is None:
                return False, f"{key} 非数值"
            if f < 0:
                return False, f"{key} 不能为负"

    elif dimension == "news":
        if not str(item.get("title") or "").strip():
            return False, "news 缺失 title"

    elif dimension == "legal":
        if not (str(item.get("title") or "").strip() or str(item.get("case_no") or "").strip()):
            return False, "legal 需 title 或 case_no"

    elif dimension == "market":
        v = item.get("market_cap")
        if v is not None:
            f = _to_float(v)
            if f is None:
                return False, "market_cap 非数值"
            if f < 0:
                return False, "market_cap 不能为负"

    else:
        return False, f"不支持的维度 {dimension}"

    return True, ""
