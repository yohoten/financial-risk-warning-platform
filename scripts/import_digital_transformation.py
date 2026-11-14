"""把 CSMAR 数字化转型辅助数据整理成公司-年度面板。

输入（CSMAR 导出，两行表头，第二行为单位/说明）：
    上市公司数字化转型程度(年)/*.xlsx
    管理层数字创新导向指标统计表/*.xlsx

输出：
    data/external/digital_transformation.csv

口径：
- 只保留沪深 A 股代码（000/001/002/003/300/301/600/601/603/605/688）；
- 代码统一补足 6 位，年份统一为整数；
- 五类词频保留原始计数，另给出合计；
- 两张表按 公司-年度 外连接，缺失不填 0，用 *_available 标记来源是否存在；
- 同一公司-年度只保留一行。

用法：
    python -m scripts.import_digital_transformation \
        --source "F:/Download/Google download/3.上市公司数字化转型数据库（2007-2025年）"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402

FIRM_PATTERN = "*数字化转型程度*.xlsx"
MGMT_PATTERN = "*管理层数字创新导向指标统计表*.xlsx"

A_SHARE_PREFIXES = (
    "000", "001", "002", "003",
    "300", "301",
    "600", "601", "603", "605", "688",
)

FIRM_COLUMNS = {
    "AITechnology": "dt_ai",
    "BlockChainTechnology": "dt_blockchain",
    "CloudComputingTech": "dt_cloud",
    "BigDataTechnology": "dt_bigdata",
    "DigitalTechApplication": "dt_application",
}

MGMT_COLUMNS = {
    "AITechnology": "mgmt_dt_ai",
    "BlockChainTechnology": "mgmt_dt_blockchain",
    "CloudComputingTech": "mgmt_dt_cloud",
    "BigDataTechnology": "mgmt_dt_bigdata",
    "DigitalTechApplication": "mgmt_dt_application",
}


def find_one(source: Path, pattern: str) -> Path:
    """找唯一输入文件，跳过浏览器重复下载产生的 (1) 副本。"""
    candidates = [
        p for p in source.rglob(pattern)
        if p.is_file() and "(1)" not in p.name and not p.name.startswith("~$")
    ]
    if not candidates:
        raise FileNotFoundError(f"未找到 {pattern}（目录：{source}）")
    return sorted(candidates, key=lambda p: (len(p.name), str(p)))[0]


def normalize_code(series: pd.Series) -> pd.Series:
    """提取 6 位股票代码，兼容 1 / 1.0 / 000001 / 000001.SZ。"""
    raw = series.astype("string").str.strip()
    extracted = raw.str.extract(r"(\d{6})")[0]
    numeric = pd.to_numeric(raw, errors="coerce")
    padded = numeric.dropna().astype("int64").astype(str).str.zfill(6)
    extracted.loc[padded.index] = padded
    return extracted.fillna("")


def normalize_year(series: pd.Series) -> pd.Series:
    """兼容 2020 / 2020.0 / 2020-12-31。"""
    numeric = pd.to_numeric(series, errors="coerce")
    year = numeric.where(numeric.between(1900, 2100))
    year = year.fillna(pd.to_datetime(series, errors="coerce").dt.year)
    return year.astype("Int64")


def read_table(path: Path, value_columns: dict[str, str]) -> pd.DataFrame:
    """读取两行表头的 CSMAR 表，并统一代码、年份、数值类型。"""
    frame = pd.read_excel(path, header=0, skiprows=[1])
    frame.columns = [str(c).strip() for c in frame.columns]

    required = {"Symbol", "SgnYear", *value_columns}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{path.name} 缺少列：{sorted(missing)}")

    frame["stock_code"] = normalize_code(frame["Symbol"])
    frame["year"] = normalize_year(frame["SgnYear"])
    for source_col in value_columns:
        frame[source_col] = pd.to_numeric(frame[source_col], errors="coerce")

    frame = frame.loc[
        frame["stock_code"].str.startswith(A_SHARE_PREFIXES) & frame["year"].notna()
    ].copy()
    frame["year"] = frame["year"].astype("int64")

    duplicated = frame.duplicated(["stock_code", "year"])
    if duplicated.any():
        raise ValueError(f"{path.name} 存在 {int(duplicated.sum())} 条重复公司-年度")

    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 data/external/digital_transformation.csv")
    parser.add_argument(
        "--source",
        type=Path,
        default=PROJECT_ROOT / "data" / "incoming" / "csmar" / "digital_transformation",
        help="CSMAR 数字化转型数据库目录（含两张 xlsx 所在子目录）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=settings.EXTERNAL_DIR / "digital_transformation.csv",
    )
    args = parser.parse_args()

    if not args.source.exists():
        raise FileNotFoundError(f"源目录不存在：{args.source}")

    firm_path = find_one(args.source, FIRM_PATTERN)
    mgmt_path = find_one(args.source, MGMT_PATTERN)
    print(f"公司数字化转型：{firm_path}")
    print(f"管理层数字创新：{mgmt_path}")

    firm = read_table(firm_path, FIRM_COLUMNS)
    firm = firm.rename(columns=FIRM_COLUMNS)[
        ["stock_code", "year", *FIRM_COLUMNS.values()]
    ].copy()
    firm["dt_total"] = firm[list(FIRM_COLUMNS.values())].sum(axis=1)
    firm["dt_available"] = 1

    mgmt = read_table(mgmt_path, MGMT_COLUMNS)
    mgmt = mgmt.rename(columns=MGMT_COLUMNS)[
        ["stock_code", "year", *MGMT_COLUMNS.values()]
    ].copy()
    mgmt["mgmt_dt_total"] = mgmt[list(MGMT_COLUMNS.values())].sum(axis=1)
    mgmt["mgmt_dt_available"] = 1

    panel = firm.merge(mgmt, on=["stock_code", "year"], how="outer")
    panel["dt_available"] = panel["dt_available"].fillna(0).astype("int64")
    panel["mgmt_dt_available"] = panel["mgmt_dt_available"].fillna(0).astype("int64")

    value_cols = [
        *FIRM_COLUMNS.values(), "dt_total",
        *MGMT_COLUMNS.values(), "mgmt_dt_total",
    ]
    for col in value_cols:
        panel[col] = panel[col].astype("Int64")

    panel = panel.sort_values(["stock_code", "year"]).reset_index(drop=True)
    if panel.duplicated(["stock_code", "year"]).any():
        raise ValueError("合并后仍存在重复公司-年度")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(args.output, index=False, encoding="utf-8")

    summary = {
        "output": str(args.output),
        "rows": int(len(panel)),
        "stock_codes": int(panel["stock_code"].nunique()),
        "year_min": int(panel["year"].min()),
        "year_max": int(panel["year"].max()),
        "dt_rows": int(panel["dt_available"].sum()),
        "mgmt_rows": int(panel["mgmt_dt_available"].sum()),
        "dt_zero_total_rows": int(
            ((panel["dt_available"] == 1) & (panel["dt_total"] == 0)).sum()
        ),
        "mgmt_zero_total_rows": int(
            ((panel["mgmt_dt_available"] == 1) & (panel["mgmt_dt_total"] == 0)).sum()
        ),
        "duplicates": int(panel.duplicated(["stock_code", "year"]).sum()),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
