"""巨潮资讯网年报爬虫：公告检索 → PDF 下载 → MD&A 段落抽取。

数据用途：为 FinBERT 情感分析提供管理层讨论与分析（MD&A）文本。

用法
----
    python -m crawlers.cninfo_spider --codes 600000 600002 --years 2022 2023 --limit 2
    python -m crawlers.cninfo_spider --codes 600000 --dry-run
"""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

import pandas as pd

from config import settings
from crawlers.base import RateLimitedSession, download_file
from etl.io_utils import get_logger, write_table

logger = get_logger("cninfo")

QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
PDF_BASE = "http://static.cninfo.com.cn/"
# 年度报告分类编码（沪深两市通用）
CATEGORY_ANNUAL = "category_ndbg_szsh"

MDNA_START = re.compile(r"管理层讨论与分析|经营情况讨论与分析")
MDNA_END = re.compile(r"重要事项|公司治理|环境和社会责任")


def fetch_announcements(stock_code: str, year: int, session: RateLimitedSession, page_size: int = 30) -> list[dict]:
    """检索某公司某年度的年报公告列表。"""
    payload = {
        "pageNum": 1,
        "pageSize": page_size,
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": stock_code,
        "searchkey": "",
        "secdate": f"{year}-01-01~{year}-12-31",
        "tdate": "",
        "category": CATEGORY_ANNUAL,
        "trade": "",
        "seDate": f"{year}-01-01~{year}-12-31",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    data = session.post_json(QUERY_URL, data=payload, headers={
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
    })
    items = data.get("announcements") or []
    results = []
    for item in items:
        title = re.sub("<[^>]+>", "", item.get("announcementTitle", ""))
        if "年度报告" not in title or "摘要" in title or "英文" in title:
            continue
        results.append(
            {
                "stock_code": str(item.get("secCode", stock_code)).zfill(6),
                "company_name": item.get("secName", ""),
                "year": year,
                "title": title,
                "publish_time": time.strftime("%Y-%m-%d", time.localtime(item.get("announcementTime", 0) / 1000)),
                "url": PDF_BASE + item.get("adjunctUrl", ""),
            }
        )
    return results


def extract_mdna(pdf_path: Path) -> str:
    """从年报 PDF 中抽取 MD&A 段落（约 3-8 页文本），失败返回空串。"""
    try:
        import pdfplumber
    except ImportError:
        logger.warning("未安装 pdfplumber，跳过文本抽取")
        return ""

    chunks: list[str] = []
    started = False
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[10:60]:  # MD&A 通常出现在第 10-60 页
            text = page.extract_text() or ""
            if not started and MDNA_START.search(text):
                started = True
            if started:
                chunks.append(text)
            if started and MDNA_END.search(text) and len("".join(chunks)) > 1500:
                break
    content = "\n".join(chunks)
    logger.info("MD&A 抽取完成：%s（%d 字）", pdf_path.name, len(content))
    return content


def crawl(codes: list[str], years: list[int], limit: int | None = None, dry_run: bool = False) -> Path:
    """批量下载年报并输出清单 CSV。"""
    pdf_dir = settings.RAW_DIR / "annual_reports"
    text_dir = settings.RAW_DIR / "mdna_text"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    session = RateLimitedSession("cninfo")
    records: list[dict] = []

    for code in codes:
        for year in years:
            try:
                items = fetch_announcements(code, year, session)
            except Exception as exc:
                logger.error("%s %s 检索失败：%s", code, year, exc)
                continue
            if not items:
                logger.info("%s %s 未找到年报", code, year)
                continue
            for item in items[: limit or 1]:
                logger.info("发现年报：%s %s %s", item["stock_code"], year, item["title"][:30])
                if dry_run:
                    records.append({**item, "local_path": "", "mdna_chars": 0})
                    continue
                target = pdf_dir / f"{item['stock_code']}_{year}.pdf"
                try:
                    download_file(item["url"], target, session)
                except Exception as exc:
                    logger.error("下载失败：%s", exc)
                    continue
                text = extract_mdna(target)
                if text:
                    text_dir.mkdir(parents=True, exist_ok=True)
                    (text_dir / f"{item['stock_code']}_{year}.txt").write_text(text, encoding="utf-8")
                records.append({**item, "local_path": settings.rel(target), "mdna_chars": len(text)})

    out = write_table(pd.DataFrame(records), settings.RAW_DIR / "annual_report_index.csv")
    logger.info("清单已写出：%s（%d 条）", settings.rel(out), len(records))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="巨潮资讯网年报爬虫")
    parser.add_argument("--codes", nargs="+", required=True, help="股票代码列表")
    parser.add_argument("--years", nargs="+", type=int, default=[2023], help="年度列表")
    parser.add_argument("--limit", type=int, default=1, help="每家公司每年最多下载份数")
    parser.add_argument("--dry-run", action="store_true", help="仅检索不下载")
    args = parser.parse_args()
    crawl(args.codes, args.years, args.limit, args.dry_run)


if __name__ == "__main__":
    main()
