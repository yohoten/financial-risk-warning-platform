"""清洗 CSMAR《治理综合信息文件》CG_Ybasic 导出。

原始 CSV 的 `Y1901b`（备注）含未转义换行/逗号，pandas 直接读会把一条记录拆成多行。
本脚本只保留字段数等于表头（23 列）且 `Reptdt` 为 YYYY-MM-DD 的记录，输出规范 CSV，
不修改任何列名和数值。

用法：
    python -m scripts.clean_cg_ybasic --input <CG_Ybasic.csv> --output <clean.csv>
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def clean(src: Path, dst: Path) -> tuple[int, int]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    kept = skipped = 0
    with src.open(encoding="utf-8-sig", errors="replace", newline="") as fh, \
            dst.open("w", encoding="utf-8-sig", newline="") as out:
        reader = csv.reader(fh)
        writer = csv.writer(out, quoting=csv.QUOTE_ALL)
        header = next(reader)
        width = len(header)
        writer.writerow(header)
        for row in reader:
            if len(row) != width or not DATE_RE.match(row[1].strip()):
                skipped += 1
                continue
            writer.writerow(row)
            kept += 1
    return kept, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="清洗 CG_Ybasic 多行字段")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    kept, skipped = clean(Path(args.input), Path(args.output))
    print(f"保留 {kept:,} 行，跳过 {skipped:,} 行（多行/错列/非日期）")
    print(f"输出: {args.output}")


if __name__ == "__main__":
    main()
