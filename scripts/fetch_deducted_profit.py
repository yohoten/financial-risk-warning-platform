# -*- coding: utf-8 -*-
"""从东方财富 F10 财务指标接口抓取扣非净利润，补齐 csmar_financial.csv 的 deducted_profit。

字段映射：东财 KCFJCXSYJLR（扣除非经常性损益后的净利润，元）→ 项目 deducted_profit（亿元）。
只取年报口径（REPORT_TYPE='年报'），按 stock_code + year 对齐。

用法：
    python scripts/fetch_deducted_profit.py --limit 20      # 小批量验证
    python scripts/fetch_deducted_profit.py                # 全量（约 5000 只，后台跑）
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://emweb.securities.eastmoney.com/"}
BASE = "https://datacenter.eastmoney.com/securities/api/data/v1/get"


def _suffix(code: str) -> str:
    """6 位证券代码 → 东财交易所后缀。"""
    if code.startswith(("6", "9", "5")):
        return ".SH"
    if code.startswith(("0", "3", "2")):
        return ".SZ"
    return ".BJ"  # 8/4 开头北交所


def fetch_one(code: str) -> list[dict]:
    """抓取一只股票的全部年报扣非净利润。"""
    secucode = code + _suffix(code)
    url = (
        f"{BASE}?reportName=RPT_F10_FINANCE_MAINFINADATA"
        f"&columns=REPORT_DATE,REPORT_TYPE,SECURITY_CODE,KCFJCXSYJLR"
        f"&filter=(SECUCODE%3D%22{secucode}%22)"
        f"&pageNumber=1&pageSize=200&sortColumns=REPORT_DATE&sortTypes=-1"
        f"&source=HSF10&client=PC"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        res = r.json().get("result")
        if not res or not res.get("data"):
            return []
        rows = []
        for row in res["data"]:
            if row.get("REPORT_TYPE") == "年报" and row.get("KCFJCXSYJLR") is not None:
                rows.append({
                    "stock_code": str(row["SECURITY_CODE"]).zfill(6),
                    "year": int(str(row["REPORT_DATE"])[:4]),
                    "deducted_profit": float(row["KCFJCXSYJLR"]) / 1e8,  # 元 → 亿元
                })
        return rows
    except Exception:
        return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只抓前 N 只（0=全量）")
    ap.add_argument("--workers", type=int, default=6, help="并发请求数")
    args = ap.parse_args()

    fin = pd.read_csv("data/raw/csmar_financial.csv", encoding="utf-8-sig", low_memory=False)
    codes = sorted(fin["stock_code"].astype(str).str.zfill(6).unique())
    if args.limit:
        codes = codes[: args.limit]

    collected: dict[tuple[str, int], float] = {}
    t0 = time.time()
    # pageSize=200 必须覆盖全部历史报告期；旧值 40 会截断 2015 及更早年度。
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_one, code): code for code in codes}
        for i, future in enumerate(as_completed(futures), 1):
            for row in future.result():
                collected[(row["stock_code"], row["year"])] = row["deducted_profit"]
            if i % 200 == 0 or i == len(codes):
                print(f"  进度 {i}/{len(codes)} 用时 {time.time()-t0:.0f}s 命中 {len(collected)}", flush=True)

    # 写回
    fin["stock_code"] = fin["stock_code"].astype(str).str.zfill(6)
    fin["year"] = pd.to_numeric(fin["year"], errors="coerce").astype(int)
    hit = 0
    for idx, row in fin.iterrows():
        v = collected.get((row["stock_code"], row["year"]))
        if v is not None:
            fin.at[idx, "deducted_profit"] = v
            hit += 1
    fin.to_csv("data/raw/csmar_financial.csv", index=False, encoding="utf-8-sig")
    print(f"完成：{len(codes)} 只 → 命中 {len(collected)} 条公司-年，写回 {hit} 条，耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
