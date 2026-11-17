"""数据源接入（移植自旧项目 server/app/datasources/registry.py）。

AkShare 作为增量补充源（东财摘要 / 新浪三表 / 巨潮诉讼），与已有 crawlers
（巨潮/东财/企查查离线爬虫）互补；本模块只做「状态查询 + 单企业实时刷新」，
不改变 offline 的 CSMAR 契约表流水线。
"""

from __future__ import annotations

# 维度 → 数据源优先级（news/finance 多源合并，其余降级优先）
SOURCES: dict[str, list[dict]] = {
    "finance": [
        {"name": "akshare_eastmoney", "label": "东方财富财务摘要", "dims": ["finance", "market_cap"]},
        {"name": "akshare_sina", "label": "新浪三表", "dims": ["finance"]},
    ],
    "news": [
        {"name": "akshare_news", "label": "东财个股新闻", "dims": ["news"]},
        {"name": "announcement", "label": "东财公告", "dims": ["news"]},
    ],
    "legal": [
        {"name": "akshare_cninfo", "label": "巨潮诉讼统计", "dims": ["legal"]},
    ],
}
MERGE_DIMS = {"news", "finance"}


def _akshare_available() -> bool:
    try:
        import akshare  # noqa: F401
        return True
    except ImportError:
        return False


def source_status() -> dict:
    """供前端「数据源」页展示：数据源配置与 AkShare 可用性。"""
    return {
        "akshare_available": _akshare_available(),
        "sources": [
            {
                "dimension": dim,
                "mode": "merge" if dim in MERGE_DIMS else "fallback",
                "sources": sources,
            }
            for dim, sources in SOURCES.items()
        ],
    }


def refresh_enterprise(stock_code: str) -> dict:
    """从 AkShare 拉取单企业实时快照（东财个股信息，含总市值，可补 Altman Z 的 X4）。

    离线 CSMAR 契约表不受影响；本接口为「实时增量」补充。akshare 未安装或网络失败时优雅降级。
    """
    code = str(stock_code).strip().zfill(6)
    if not _akshare_available():
        return {
            "ok": False,
            "stock_code": code,
            "error": "akshare 未安装，请先 pip install akshare（数据源接入为阶段 4 增量能力，offline 契约表不受影响）",
        }
    try:
        import akshare as ak
        info = ak.stock_individual_info_em(symbol=code)
        records = info.to_dict("records") if info is not None else []
        # 总市值（用于 Altman Z 市值口径）
        market_cap = None
        for r in records:
            for k, v in r.items():
                if "总市值" in str(k):
                    market_cap = v
        return {
            "ok": True,
            "stock_code": code,
            "source": "eastmoney",
            "market_cap": market_cap,
            "items": records,
        }
    except Exception as exc:  # noqa: BLE001 —— 网络/接口异常不阻断服务
        return {"ok": False, "stock_code": code, "error": f"{type(exc).__name__}: {exc}"}
