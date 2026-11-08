"""东方财富新闻爬虫：个股新闻标题/摘要/发布时间采集。

采集结果用于构建舆情因子（正负面词比例、新闻热度），
与年报 MD&A 情感互为补充：年报是低频高信噪，新闻是高频高噪音。

用法
----
    python -m crawlers.eastmoney_spider --codes 600000 600002 --pages 1
"""

from __future__ import annotations

import argparse
import json
import re
import time

import pandas as pd

from config import settings
from crawlers.base import RateLimitedSession
from etl.io_utils import get_logger, write_table

logger = get_logger("eastmoney")

SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp"


def _strip_jsonp(text: str) -> dict:
    """东方财富接口返回 jsonp 包裹，剥离回调后解析。"""
    match = re.search(r"\((.*)\)\s*$", text, flags=re.S)
    raw = match.group(1) if match else text
    return json.loads(raw)


def fetch_news(stock_code: str, page_size: int = 20, page_index: int = 1,
               session: RateLimitedSession | None = None) -> list[dict]:
    """检索个股新闻列表。"""
    session = session or RateLimitedSession("eastmoney")
    param = {
        "uid": "",
        "keyword": stock_code,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "time",
                "pageIndex": page_index,
                "pageSize": page_size,
                "preTag": "<em>",
                "postTag": "</em>",
            }
        },
    }
    resp = session.request(
        "GET", SEARCH_URL,
        params={"cb": f"cb{int(time.time() * 1000)}", "param": json.dumps(param, ensure_ascii=False)},
        headers={"Referer": "https://so.eastmoney.com/"},
    )
    payload = _strip_jsonp(resp.text)
    items = (payload.get("result") or {}).get("cmsArticleWebOld") or []

    records = []
    for item in items:
        records.append(
            {
                "stock_code": stock_code.zfill(6),
                "title": re.sub("<[^>]+>", "", item.get("title", "")),
                "summary": re.sub("<[^>]+>", "", item.get("content", ""))[:200],
                "publish_time": item.get("date", ""),
                "source": item.get("mediaName", ""),
                "url": item.get("url", ""),
            }
        )
    return records


def crawl(codes: list[str], pages: int = 1) -> pd.DataFrame:
    """批量采集并落盘（按 URL 去重）。"""
    session = RateLimitedSession("eastmoney")
    frames = []
    for code in codes:
        for page in range(1, pages + 1):
            try:
                records = fetch_news(code, page_index=page, session=session)
            except Exception as exc:
                logger.error("%s 第 %d 页采集失败：%s", code, page, exc)
                continue
            logger.info("%s 第 %d 页：%d 条", code, page, len(records))
            frames.extend(records)

    if not frames:
        logger.warning("未采集到任何新闻")
        return pd.DataFrame()

    df = pd.DataFrame(frames).drop_duplicates(subset=["url"])
    out = write_table(df, settings.RAW_DIR / "news_raw.csv")
    logger.info("新闻已写出：%s（%d 条）", settings.rel(out), len(df))
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="东方财富个股新闻爬虫")
    parser.add_argument("--codes", nargs="+", required=True)
    parser.add_argument("--pages", type=int, default=1)
    args = parser.parse_args()
    crawl(args.codes, args.pages)


if __name__ == "__main__":
    main()
