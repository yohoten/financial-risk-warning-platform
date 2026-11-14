# -*- coding: utf-8 -*-
"""从 Baostock 抓取个股年度换手率与年化波动率，补齐 market_features.csv。

字段映射：
- annual_turnover：年换手率（%）= 当年逐日换手率 turn 求和。
- stock_volatility：年化波动率 = 当年日涨跌幅 pctChg/100 的标准差 × sqrt(252)。

口径：前复权（adjustflag=2）日线，按自然年度聚合。

baostock 是单 socket、不支持多线程（并发会触发服务器限流），因此本脚本采用
**单线程 + 每只之间 sleep + 失败重试 + 定期落盘断点**，可后台长时间跑。

断点续传：已抓取的公司-年写入 cache/market_baostock.parquet，重启后跳过已完成股票。

用法：
    python scripts/fetch_market_baostock.py --limit 20      # 小批量验证
    python scripts/fetch_market_baostock.py                 # 全量（后台跑，数小时）
"""
from __future__ import annotations

import argparse
import math
import time

import baostock as bs
import pandas as pd

YMIN, YMAX = 2013, 2025
TRADING_DAYS = 252.0
CACHE = "cache/market_baostock.parquet"
OUT = "data/raw/market_features.csv"
SLEEP_BETWEEN = 0.5          # 每只之间间隔，避免触发限流
MAX_RETRY = 3                # 单只失败重试次数
SAVE_EVERY = 100             # 每 N 只落盘一次断点


def _baos_code(code: str) -> str:
    if code.startswith(("6", "9", "5")):
        return "sh." + code
    if code.startswith(("0", "3", "2")):
        return "sz." + code
    return "bj." + code


def fetch_one(code: str) -> list[dict]:
    """抓取一只股票全部日线，按年聚合（含重试）。"""
    bcode = _baos_code(code)
    for attempt in range(MAX_RETRY):
        rs = bs.query_history_k_data_plus(
            bcode, "date,pctChg,turn", f"{YMIN}-01-01", f"{YMAX}-12-31",
            frequency="d", adjustflag="2",
        )
        if rs.error_code != "0":
            time.sleep(1.0 * (attempt + 1))
            continue
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return []  # 停牌/退市无数据，不算失败
        df = pd.DataFrame(rows, columns=["date", "pctChg", "turn"])
        df["year"] = df["date"].str[:4].astype(int)
        df["pctChg"] = pd.to_numeric(df["pctChg"], errors="coerce")
        df["turn"] = pd.to_numeric(df["turn"], errors="coerce")
        out = []
        for year, g in df.groupby("year"):
            turnover = g["turn"].sum(skipna=True)
            ret = g["pctChg"].dropna() / 100.0
            vol = ret.std(ddof=0) * math.sqrt(TRADING_DAYS) if len(ret) > 1 else float("nan")
            out.append({
                "stock_code": code,
                "year": int(year),
                "annual_turnover": round(float(turnover), 4),
                "stock_volatility": round(float(vol), 6),
            })
        return out
    return []


def _load_done() -> tuple[pd.DataFrame, set]:
    try:
        df = pd.read_parquet(CACHE)
        per_code_years = df.groupby("stock_code")["year"].apply(set)
        skip = {c for c, ys in per_code_years.items() if len(ys) >= (YMAX - YMIN + 1)}
        return df, skip
    except FileNotFoundError:
        return pd.DataFrame(columns=["stock_code", "year", "annual_turnover", "stock_volatility"]), set()


def _save(df: pd.DataFrame) -> None:
    df = df.drop_duplicates(subset=["stock_code", "year"], keep="last")
    df["stock_code"] = df["stock_code"].astype(str).str.zfill(6)
    df.to_parquet(CACHE, index=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只抓前 N 只（0=全量）")
    args = ap.parse_args()

    fin = pd.read_csv("data/raw/csmar_financial.csv", encoding="utf-8-sig", low_memory=False)
    codes = sorted(fin["stock_code"].astype(str).str.zfill(6).unique())
    if args.limit:
        codes = codes[: args.limit]

    cache_df, skip = _load_done()
    todo = [c for c in codes if c not in skip]
    print(f"共 {len(codes)} 只，已完成 {len(skip)} 只，待抓 {len(todo)} 只", flush=True)

    lg = bs.login()
    print("Baostock login:", lg.error_code, lg.error_msg, flush=True)
    t0 = time.time()
    new_rows: list[dict] = []
    for i, code in enumerate(todo, 1):
        new_rows.extend(fetch_one(code))
        if i % SAVE_EVERY == 0:
            cache_df = pd.concat([cache_df, pd.DataFrame(new_rows)], ignore_index=True)
            _save(cache_df)
            new_rows = []
            print(f"  进度 {i}/{len(todo)} 用时 {time.time()-t0:.0f}s 缓存 {len(cache_df)} 公司-年", flush=True)
        time.sleep(SLEEP_BETWEEN)
    bs.logout()

    cache_df = pd.concat([cache_df, pd.DataFrame(new_rows)], ignore_index=True)
    _save(cache_df)

    mkt = pd.read_csv(OUT, encoding="utf-8-sig", low_memory=False)
    mkt["stock_code"] = mkt["stock_code"].astype(str).str.zfill(6)
    mkt["year"] = pd.to_numeric(mkt["year"], errors="coerce").astype(int)
    mkt = mkt.drop(columns=["annual_turnover", "stock_volatility"], errors="ignore")
    mkt = mkt.merge(cache_df, on=["stock_code", "year"], how="left")
    mkt.to_csv(OUT, index=False, encoding="utf-8-sig")

    print(f"完成：缓存合计 {len(cache_df)} 公司-年；耗时 {time.time()-t0:.0f}s", flush=True)
    print(f"annual_turnover 非空率 {mkt['annual_turnover'].notna().mean():.1%}，"
          f"stock_volatility 非空率 {mkt['stock_volatility'].notna().mean():.1%}", flush=True)


if __name__ == "__main__":
    main()
