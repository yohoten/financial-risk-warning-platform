# -*- coding: utf-8 -*-
"""从东方财富历史 K 线接口抓取个股年度换手率与年化波动率，写入归档的遗留百分数表。

契约表已切到 `settings.RAW_MARKET`（market_features_trd.csv，小数口径），
本脚本只维护 `data/raw/market_features_legacy_percent.csv`，供审计对照。


字段映射（东财 K 线 fields2=f51..f61）：
- f51 = 日期, f59 = 涨跌幅(%), f61 = 换手率(%)
- annual_turnover：年换手率（%）= 当年逐日换手率 f61 求和。
- stock_volatility：年化波动率 = 当年日涨跌幅 f59/100 的标准差 × sqrt(252)。

口径：前复权（fqt=1）日线，按自然年度聚合。断点续传：
已抓取的公司-年写入 cache/market_eastmoney.parquet，重启后跳过已完成股票。

用法：
    python scripts/fetch_market_eastmoney.py --limit 20      # 小批量验证
    python scripts/fetch_market_eastmoney.py                 # 全量（约 5600 只，后台跑）
    python scripts/fetch_market_eastmoney.py --workers 8     # 指定并发线程数
"""
from __future__ import annotations

import argparse
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

YMIN, YMAX = 2013, 2025
TRADING_DAYS = 252.0
CACHE = "cache/market_eastmoney.parquet"
OUT = "data/raw/market_features_legacy_percent.csv"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


def _secid(code: str) -> str:
    """6 位证券代码 → 东财 secid（1=沪，0=深/北）。"""
    if code.startswith(("6", "9", "5")):
        return "1." + code
    return "0." + code  # 0/3/2/8/4 开头（深主板/创业板/北交所）


def fetch_one(code: str) -> list[dict]:
    """抓取一只股票 2013-2025 全部日线，按年聚合换手率与波动率。"""
    secid = _secid(code)
    url = (
        f"{KLINE}?secid={secid}&klt=101&fqt=1"
        f"&beg={YMIN}0101&end={YMAX}1231"
        f"&fields1=f1,f2,f3&fields2=f51,f59,f61"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        data = r.json().get("data")
        if not data or not data.get("klines"):
            return []
        rows = []
        for line in data["klines"]:
            parts = line.split(",")
            if len(parts) < 3:
                continue
            date, pct, turn = parts[0], parts[1], parts[2]
            if pct in ("", "-") and turn in ("", "-"):
                continue
            rows.append((int(date[:4]), _f(pct), _f(turn)))
    except Exception:
        return []
    if not rows:
        return []

    df = pd.DataFrame(rows, columns=["year", "pct", "turn"])
    out = []
    for year, g in df.groupby("year"):
        turnover = g["turn"].sum(skipna=True)
        ret = g["pct"].dropna() / 100.0
        vol = ret.std(ddof=0) * math.sqrt(TRADING_DAYS) if len(ret) > 1 else float("nan")
        out.append({
            "stock_code": code,
            "year": int(year),
            "annual_turnover": round(float(turnover), 4),
            "stock_volatility": round(float(vol), 6),
        })
    return out


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def _load_done() -> tuple[set, pd.DataFrame]:
    try:
        df = pd.read_parquet(CACHE)
        return set(zip(df["stock_code"], df["year"])), df
    except FileNotFoundError:
        return set(), pd.DataFrame(columns=["stock_code", "year", "annual_turnover", "stock_volatility"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只抓前 N 只（0=全量）")
    ap.add_argument("--workers", type=int, default=8, help="并发线程数")
    args = ap.parse_args()

    fin = pd.read_csv("data/raw/csmar_financial.csv", encoding="utf-8-sig", low_memory=False)
    codes = sorted(fin["stock_code"].astype(str).str.zfill(6).unique())
    if args.limit:
        codes = codes[: args.limit]

    done, cache_df = _load_done()
    per_code_years = cache_df.groupby("stock_code")["year"].apply(set)
    skip = {c for c, ys in per_code_years.items() if len(ys) >= (YMAX - YMIN + 1)}
    todo = [c for c in codes if c not in skip]

    print(f"共 {len(codes)} 只，已完成 {len(skip)} 只，待抓 {len(todo)} 只", flush=True)
    t0 = time.time()
    new_rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_one, c): c for c in todo}
        done_n = 0
        for fut in as_completed(futs):
            new_rows.extend(fut.result())
            done_n += 1
            if done_n % 200 == 0:
                print(f"  进度 {done_n}/{len(todo)} 累计公司-年 {len(new_rows)} 用时 {time.time()-t0:.0f}s", flush=True)

    merged = pd.concat([cache_df, pd.DataFrame(new_rows)], ignore_index=True)
    merged = merged.drop_duplicates(subset=["stock_code", "year"], keep="last")
    merged["stock_code"] = merged["stock_code"].astype(str).str.zfill(6)
    merged.to_parquet(CACHE, index=False)

    mkt = pd.read_csv(OUT, encoding="utf-8-sig", low_memory=False)
    mkt["stock_code"] = mkt["stock_code"].astype(str).str.zfill(6)
    mkt["year"] = pd.to_numeric(mkt["year"], errors="coerce").astype(int)
    mkt = mkt.drop(columns=["annual_turnover", "stock_volatility"], errors="ignore")
    mkt = mkt.merge(merged, on=["stock_code", "year"], how="left")
    mkt.to_csv(OUT, index=False, encoding="utf-8-sig")

    print(f"完成：本轮新增 {len(new_rows)} 公司-年；缓存合计 {len(merged)}；耗时 {time.time()-t0:.0f}s", flush=True)
    print(f"annual_turnover 非空率 {mkt['annual_turnover'].notna().mean():.1%}，"
          f"stock_volatility 非空率 {mkt['stock_volatility'].notna().mean():.1%}", flush=True)


if __name__ == "__main__":
    main()
