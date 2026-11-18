"""股票代码解析与归一（移植自旧项目 server/app/datasources/codes.py）。

所有入口都同时接受名称与股票代码（含 SH600519 / 600519.SH / 000001.XSHE 等写法）。
"""

from __future__ import annotations

import re
import time

_CACHE: dict = {"ts": 0.0, "rows": []}
TTL = 24 * 3600  # 一天

# 常见代码写法：SH600519 / sh.600519 / 600519.SH / 600519.SS / 000001.XSHE
_CODE_RE = re.compile(r"^(?:(?:SH|SZ|BJ|SS)\.?)?(\d{6})(?:\.(?:SH|SZ|BJ|SS|XSHE|XSHG))?$", re.IGNORECASE)


def normalize_code(raw: str) -> str:
    """把常见股票代码写法归一为 6 位数字代码；不是代码则返回空串。"""
    text = (raw or "").strip().upper().replace(" ", "").replace("－", "-")
    m = _CODE_RE.match(text)
    return m.group(1) if m else ""


def _table() -> list[dict]:
    now = time.time()
    if _CACHE["rows"] and now - _CACHE["ts"] < TTL:
        return _CACHE["rows"]
    try:
        import akshare as ak

        df = ak.stock_info_a_code_name()
        rows = [
            {"code": str(r["code"]).zfill(6), "name": str(r["name"]).strip()}
            for _, r in df.iterrows()
        ]
        _CACHE.update(ts=now, rows=rows)
    except Exception:  # noqa: BLE001 —— 网络失败时保留旧缓存
        pass
    return _CACHE["rows"]


def resolve_code(name: str, limit: int = 8) -> list[dict]:
    """按名称或股票代码匹配（供"自由添加企业"使用）。"""
    query = (name or "").strip()
    if not query:
        return []
    code = normalize_code(query)
    if code:
        return [r for r in _table() if r["code"] == code][:limit]
    rows = _table()
    hits = [r for r in rows if query in r["name"]]
    hits.sort(key=lambda r: (0 if r["name"] == query else 1 if r["name"].startswith(query) else 2, len(r["name"])))
    return hits[:limit]


def name_of(code: str) -> str:
    code = normalize_code(code) or (code or "").strip().zfill(6)
    for r in _table():
        if r["code"] == code:
            return r["name"]
    return ""


def market_prefix(code: str) -> str:
    """新浪接口需要 sh/sz/bj 前缀。"""
    code = normalize_code(code) or (code or "").strip()
    if code.startswith(("6", "9")):
        return "sh" + code
    if code.startswith(("0", "3", "2")):
        return "sz" + code
    return "bj" + code
