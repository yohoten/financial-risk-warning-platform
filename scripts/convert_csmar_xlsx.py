"""把 CSMAR 导出的超大 XLSX（现金流量表直接法）流式转换为精简 CSV。

为什么需要
----------
CSMAR 现金流量表只有 XLSX 格式（199 MB，约 100 万行 × 200 列）。
`pandas.read_excel` 会一次性载入全部单元格，内存与耗时都不可接受。
本脚本用 openpyxl 的 read_only 模式逐行流式读取，只保留项目需要的 4 个现金流科目，
并按「合并报表 + 年报 + 起始年份」过滤，输出体积约 1-2 MB。

用法
----
    python -m scripts.convert_csmar_xlsx --input data/raw/FS_Comscfd.xlsx \
        --output data/incoming/csmar/FS_Comscfd_filtered.csv --min-year 2013
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# CSMAR 现金流量表（直接法）字段代码 → 项目字段
TARGET_CODES = {
    "Stkcd": "stock_code",
    "Accper": "accper",
    "Typrep": "typrep",
    "DeclareDate": "declare_date",
    "C001000000": "ocf",              # 经营活动产生的现金流量净额
    "C002000000": "icf",              # 投资活动产生的现金流量净额
    "C003000000": "fcf_financing",    # 筹资活动产生的现金流量净额
    "C002006000": "capex",            # 购建固定资产、无形资产和其他长期资产支付的现金
}


def convert(input_path: Path, output_path: Path, min_year: int = 2013, report_every: int = 100_000) -> dict:
    """流式转换：CSMAR 的 XLSX 表头分三行（代码 / 中文名 / 单位），第 4 行起为数据。

    坑：文件的 `dimension` 被写成 `A1:A567747`（只有 1 列），
    openpyxl 在 read_only 模式下会据此截断列，因此必须 `reset_dimensions()` 后才能读到全部列。
    """
    from openpyxl import load_workbook

    started = time.time()
    wb = load_workbook(input_path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    ws.reset_dimensions()

    rows = ws.iter_rows(values_only=True)
    header = next(rows)          # 第 1 行：字段代码
    next(rows, None)             # 第 2 行：中文字段名
    next(rows, None)             # 第 3 行：单位说明
    index = {str(name): i for i, name in enumerate(header) if name is not None}
    missing = [code for code in TARGET_CODES if code not in index]
    if missing:
        raise SystemExit(f"缺少必需列：{missing}\n实际表头前 20 列：{header[:20]}")

    picks = [(index[code], field) for code, field in TARGET_CODES.items()]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    scanned = kept = 0
    with open(output_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)                       # 统一转义，避免逗号污染列
        writer.writerow([field for _, field in picks])
        for row in rows:
            if row is None:
                continue
            scanned += 1
            accper = str(row[picks[1][0]] or "")       # Accper
            typrep = str(row[picks[2][0]] or "").strip().upper()
            if typrep != "A" or not accper.endswith("-12-31"):
                continue
            year = accper[:4]
            if not year.isdigit() or int(year) < min_year:
                continue
            values = ["" if row[i] is None else str(row[i]).strip() for i, _ in picks]
            writer.writerow(values)
            kept += 1
            if report_every and scanned % report_every == 0:
                print(f"  已扫描 {scanned:,} 行，保留 {kept:,} 行，耗时 {time.time()-started:.0f}s", flush=True)

    wb.close()
    elapsed = time.time() - started
    result = {
        "input": str(input_path),
        "output": str(output_path),
        "scanned_rows": scanned,
        "kept_rows": kept,
        "elapsed_sec": round(elapsed, 1),
        "size_mb": round(output_path.stat().st_size / 1e6, 2),
    }
    print(f"完成：扫描 {scanned:,} 行 → 保留 {kept:,} 行，{result['size_mb']} MB，{elapsed:.0f}s", flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="CSMAR XLSX 流式转 CSV")
    parser.add_argument("--input", type=Path, default=ROOT / "data/raw/FS_Comscfd.xlsx")
    parser.add_argument("--output", type=Path, default=ROOT / "data/incoming/csmar/FS_Comscfd_filtered.csv")
    parser.add_argument("--min-year", type=int, default=2013)
    parser.add_argument("--report-every", type=int, default=200_000)
    args = parser.parse_args()
    convert(args.input, args.output, args.min_year, args.report_every)


if __name__ == "__main__":
    main()
