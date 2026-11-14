"""清洗 CSMAR 导出中因未转义换行/逗号导致的错列行。

保留字段数恰好等于表头宽度、且指定日期列匹配 YYYY-MM-DD 的记录；不改列名、不改数值。

用法：
    python -m scripts.clean_ragged_csv --input raw.csv --output clean.csv --date-col 2
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def clean(src: Path, dst: Path, date_col: int) -> tuple[int, int]:
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
            if len(row) != width or date_col >= width or not DATE_RE.match(row[date_col].strip()):
                skipped += 1
                continue
            writer.writerow(row)
            kept += 1
    return kept, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="清洗 CSMAR 错列/多行 CSV")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--date-col", type=int, required=True, help="0-based 日期列索引")
    args = parser.parse_args()
    kept, skipped = clean(Path(args.input), Path(args.output), args.date_col)
    print(f"保留 {kept:,} 行，跳过 {skipped:,} 行")
    print(f"输出: {args.output}")


if __name__ == "__main__":
    main()
