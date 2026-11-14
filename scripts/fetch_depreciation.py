# -*- coding: utf-8 -*-
"""从新浪财经年度现金流量表补充折旧，字段级合并进财务主表。

口径：固定资产折旧、油气资产折耗、生产性物资折旧（合并报表，元→亿元）。
仅使用 12-31 年报；新浪以 0 表示未披露时，不按真实零写入。
保留公告原文口径，不等同于固定资产附注中的“本期计提折旧”。

用法：
    PYTHONPATH=. python -m scripts.fetch_depreciation --limit 20
    PYTHONPATH=. python -m scripts.fetch_depreciation --workers 6 --write
"""
from __future__ import annotations

import argparse
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

from config import settings

BASE = (
    "https://money.finance.sina.com.cn/corp/go.php/vDOWN_CashFlow/"
    "displaytype/4/stockid/{code}/ctrl/all.phtml"
)
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}
DEPR_PREFIX = "固定资产折旧、油气资产折耗、生产性"
CANDIDATE = settings.RAW_DIR / "candidates" / "depreciation_sina_annual.csv"
STATUS = settings.RAW_DIR / "candidates" / "depreciation_sina_fetch_status.csv"


def fetch_one(code: str, retries: int = 3) -> tuple[list[dict], str]:
    """返回一只公司的全部有效年报折旧及错误信息。"""
    url = BASE.format(code=code)
    error = ""
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            if len(response.content) < 100:
                raise ValueError(f"响应过短：{len(response.content)} bytes")
            frame = pd.read_table(io.BytesIO(response.content), encoding="gb18030", header=None)
            frame = frame.iloc[:-1].T
            frame.columns = frame.iloc[0]
            frame = frame.iloc[1:]
            date_col = next(c for c in frame.columns if str(c).strip() == "报表日期")
            depr_col = next(c for c in frame.columns if str(c).startswith(DEPR_PREFIX))
            dates = pd.to_numeric(frame[date_col], errors="coerce")
            values = pd.to_numeric(frame[depr_col], errors="coerce")
            annual = frame.loc[dates.notna() & (dates % 10000 == 1231)].copy()
            annual["year"] = (dates[annual.index] // 10000).astype(int)
            annual["depr_yuan"] = values[annual.index]
            # 季报的 0 明显代表未披露；年报亦保守地仅接纳正值。
            annual = annual[(annual["depr_yuan"] > 0) & annual["year"].between(2013, 2025)]
            # 新浪少数公司同年含年报与招股书两套值；源表首行是精度更高的年报值。
            annual = annual.drop_duplicates("year", keep="first")
            rows = [{
                "stock_code": code,
                "year": int(row.year),
                "depreciation": float(row.depr_yuan) / 1e8,
                "source": "SinaFinance_CashFlow_Supplement",
                "source_unit": "CNY",
                "source_field": str(depr_col),
            } for row in annual.itertuples()]
            return rows, ""
        except Exception as exc:  # 网络/源格式变化进入失败清单，不静默置零
            error = f"{type(exc).__name__}: {exc}"
            if attempt + 1 < retries:
                time.sleep(0.5 * (attempt + 1))
    return [], error


def merge_financial(candidate: pd.DataFrame, target: Path) -> int:
    """只更新 depreciation，其他列（尤其 deducted_profit）逐字保留。"""
    fin = pd.read_csv(target, encoding="utf-8-sig", dtype={"stock_code": str}, low_memory=False)
    fin["stock_code"] = fin["stock_code"].str.zfill(6)
    fin["year"] = pd.to_numeric(fin["year"], errors="coerce").astype(int)
    before = pd.to_numeric(fin["depreciation"], errors="coerce")
    valid = candidate.dropna(subset=["depreciation"]).drop_duplicates(["stock_code", "year"], keep="last")
    mapped = pd.MultiIndex.from_frame(fin[["stock_code", "year"]]).map(
        pd.Series(valid["depreciation"].to_numpy(), index=pd.MultiIndex.from_frame(valid[["stock_code", "year"]]))
    )
    mapped = pd.to_numeric(pd.Series(mapped, index=fin.index), errors="coerce")
    fin["depreciation"] = before.combine_first(mapped)
    fin.to_csv(target, index=False, encoding="utf-8-sig")
    changed = int((before.isna() & fin["depreciation"].notna()).sum())
    assert not fin.duplicated(["stock_code", "year"]).any(), "财务主表出现重复公司-年"
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--write", action="store_true", help="完整抓取后字段级写回财务主表")
    parser.add_argument("--resume", action="store_true", help="跳过状态中已成功的公司")
    args = parser.parse_args()

    fin = pd.read_csv(settings.RAW_FINANCIAL, encoding="utf-8-sig", usecols=["stock_code"], dtype=str)
    codes = sorted(fin["stock_code"].str.zfill(6).unique())
    done: set[str] = set()
    if args.resume and STATUS.exists():
        status = pd.read_csv(STATUS, dtype={"stock_code": str})
        done = set(status.loc[status["status"] == "ok", "stock_code"].str.zfill(6))
    codes = [c for c in codes if c not in done]
    if args.limit:
        codes = codes[: args.limit]

    rows: list[dict] = []
    statuses: list[dict] = []
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_one, code): code for code in codes}
        for i, future in enumerate(as_completed(futures), 1):
            code = futures[future]
            result, error = future.result()
            rows.extend(result)
            statuses.append({"stock_code": code, "status": "error" if error else "ok",
                             "hits": len(result), "error": error})
            if i % 100 == 0 or i == len(codes):
                pd.DataFrame(rows).to_csv(CANDIDATE, index=False, encoding="utf-8-sig")
                pd.DataFrame(statuses).to_csv(STATUS, index=False, encoding="utf-8-sig")
                print(f"进度 {i}/{len(codes)}，有效公司-年 {len(rows)}，失败 {sum(s['status']=='error' for s in statuses)}，"
                      f"耗时 {time.time()-started:.0f}s", flush=True)

    candidate = pd.DataFrame(rows, columns=["stock_code", "year", "depreciation", "source",
                                             "source_unit", "source_field"])
    candidate.to_csv(CANDIDATE, index=False, encoding="utf-8-sig")
    metadata = {
        "source": "新浪财经现金流量表（二手结构化来源，需抽样回查年报）",
        "field": DEPR_PREFIX + "资产折旧",
        "unit": "亿元（原始元除以1e8）",
        "period": "年度12-31，2013-2025",
        "zero_policy": "0和非正值视为未披露，不写成真实零",
        "fetched_at": pd.Timestamp.now().isoformat(),
        "companies": len(codes),
        "failures": sum(s["status"] == "error" for s in statuses),
        "rows": len(candidate),
    }
    CANDIDATE.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write:
        if statuses and any(s["status"] == "error" for s in statuses):
            raise RuntimeError("仍有失败公司；请先 --resume 重试，不写回在线表")
        changed = merge_financial(candidate, settings.RAW_FINANCIAL)
        print(f"已字段级写回 depreciation，新填充 {changed} 行；deducted_profit 未改动")


if __name__ == "__main__":
    main()
