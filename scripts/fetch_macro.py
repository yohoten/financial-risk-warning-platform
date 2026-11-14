# -*- coding: utf-8 -*-
"""抓取东方财富宏观月度数据，聚合为年度值，补齐 data/external/macro_industry.csv。

补齐字段：ppi_yoy（PPI 同比，年均）、pmi_manufacturing（制造业 PMI，年均）、
cpi_yoy（CPI 同比，年均，用于校验）、social_financing_growth（社融存量同比）。

口径：PPI/PMI/CPI 年度值 = 当年 12 个月度同比/指数的算术平均；
社融增速 = 当年 12 月末存量同比（%），来自央行年度发布值，留存于
`data/external/social_financing_pbc.csv`。不采用后续年鉴修订值，避免历史
特征混入事后修订口径；社融增量同比不能替代本字段。
"""
from __future__ import annotations

import requests
import pandas as pd

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _fetch(report_name: str, columns: str) -> pd.DataFrame:
    url = (
        f"{BASE}?columns={columns}&pageNumber=1&pageSize=300"
        f"&sortColumns=REPORT_DATE&sortTypes=1&source=WEB&client=WEB"
        f"&reportName={report_name}"
    )
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()["result"]["data"]
    return pd.DataFrame(data)


def _annual_mean(df: pd.DataFrame, date_col: str, value_col: str, ymin: int, ymax: int) -> pd.Series:
    df = df.copy()
    df["year"] = pd.to_datetime(df[date_col]).dt.year
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    g = df[(df["year"] >= ymin) & (df["year"] <= ymax)].groupby("year")[value_col].mean()
    return g.round(6)


def main() -> None:
    ymin, ymax = 2013, 2025

    ppi = _fetch("RPT_ECONOMY_PPI", "REPORT_DATE,TIME,BASE,BASE_SAME")
    pmi = _fetch("RPT_ECONOMY_PMI", "REPORT_DATE,TIME,MAKE_INDEX,MAKE_SAME")
    cpi = _fetch("RPT_ECONOMY_CPI", "REPORT_DATE,TIME,NATIONAL_SAME")

    ppi_y = _annual_mean(ppi, "REPORT_DATE", "BASE_SAME", ymin, ymax)
    pmi_y = _annual_mean(pmi, "REPORT_DATE", "MAKE_INDEX", ymin, ymax)
    cpi_y = _annual_mean(cpi, "REPORT_DATE", "NATIONAL_SAME", ymin, ymax)

    path = "data/external/macro_industry.csv"
    macro = pd.read_csv(path)
    social = pd.read_csv("data/external/social_financing_pbc.csv")
    assert not social["year"].duplicated().any(), "社融来源表年份重复"
    assert social["period"].str.endswith("12-31").all(), "社融必须使用12月末存量同比"
    social = social.set_index("year")["social_financing_growth"]
    for year in range(ymin, ymax + 1):
        if year in social.index:
            macro.loc[macro["year"] == year, "social_financing_growth"] = social[year]
        if year in ppi_y.index:
            macro.loc[macro["year"] == year, "ppi_yoy"] = ppi_y[year]
        if year in pmi_y.index:
            macro.loc[macro["year"] == year, "pmi_manufacturing"] = pmi_y[year]
        if year in cpi_y.index:
            macro.loc[macro["year"] == year, "cpi_yoy"] = cpi_y[year]

    macro.to_csv(path, index=False, encoding="utf-8")
    print("=== 补全后的宏观数据 ===")
    print(macro.to_string(index=False))
    print("\n已写入:", path)


if __name__ == "__main__":
    main()
