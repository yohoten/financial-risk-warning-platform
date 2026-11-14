"""Combine and profile a CSMAR ZIP export without loading the full table in memory.

CSMAR splits large exports into several CSV files, each repeating the header and
sometimes a UTF-8 BOM.  This script concatenates those parts into one CSV and
writes a machine-readable profile next to it.  It validates the observed date
range and duplicate (code, date) keys before the file is accepted as a candidate
raw input.

Usage:
    python -m scripts.ingest_csmar_export \
        --zip data/incoming/csmar/20261114/TRD_Dly_20130101_20171231.zip \
        --out data/incoming/csmar/20261114/TRD_Dly/TRD_Dly_2013_2017.csv \
        --code-col Stkcd --date-col Trddt \
        --start 2013-01-01 --end 2017-12-31
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shutil
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path


def _part_order(name: str) -> tuple[int, str]:
    base = name.rsplit("/", 1)[-1]
    m = re.search(r"(\d+)\.csv$", base, flags=re.IGNORECASE)
    return (int(m.group(1)) if m else 0, base.lower())


def _decode_header(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise ValueError("Cannot decode CSV header as UTF-8 or GB18030")


def combine_csv_parts(zip_path: Path, out_path: Path) -> dict:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        entries = sorted(
            (e for e in zf.infolist() if e.filename.lower().endswith(".csv")),
            key=lambda e: _part_order(e.filename),
        )
        if not entries:
            raise ValueError(f"No CSV entries in {zip_path}")

        header_bytes: bytes | None = None
        header_text: str | None = None
        encoding: str | None = None
        written_parts: list[str] = []

        with out_path.open("wb") as fout:
            for entry in entries:
                with zf.open(entry) as fin:
                    this_header = fin.readline()
                    if not this_header:
                        continue
                    if header_text is None:
                        header_text, encoding = _decode_header(this_header)
                        # Normalise the output to a single UTF-8 BOM header.
                        header_bytes = header_text.encode("utf-8")
                        fout.write(b"\xef\xbb\xbf" + header_bytes)
                    else:
                        other_text, _ = _decode_header(this_header)
                        if other_text != header_text:
                            raise ValueError(
                                f"Header mismatch in {entry.filename}: "
                                f"{other_text[:120]!r} != {header_text[:120]!r}"
                            )

                    last = b""
                    while True:
                        chunk = fin.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        fout.write(chunk)
                        last = chunk[-1:]
                    if last and last not in (b"\n", b"\r"):
                        fout.write(b"\r\n")
                    written_parts.append(entry.filename)

    if header_text is None:
        raise ValueError(f"No readable CSV header in {zip_path}")
    return {
        "zip_path": str(zip_path),
        "out_path": str(out_path),
        "source_parts": written_parts,
        "header": header_text,
        "encoding": encoding,
        "out_size_bytes": out_path.stat().st_size,
    }


def profile_csv(
    path: Path,
    code_col: str,
    date_col: str,
    expected_start: date | None,
    expected_end: date | None,
) -> dict:
    null_codes = 0
    null_dates = 0
    bad_dates = 0
    outside_range = 0
    min_date: str | None = None
    max_date: str | None = None
    rows = 0
    codes: set[str] = set()
    keys: set[tuple[str, str]] = set()
    duplicate_rows = 0
    market_types: Counter[str] = Counter()
    trade_status: Counter[str] = Counter()
    code_prefix: Counter[str] = Counter()

    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError(f"Empty CSV: {path}") from exc
        index = {name: i for i, name in enumerate(header)}
        for required in (code_col, date_col):
            if required not in index:
                raise ValueError(f"Missing column {required!r}; header={header}")
        ci, di = index[code_col], index[date_col]
        mi = index.get("Markettype")
        si = index.get("Trdsta")

        for row in reader:
            rows += 1
            if len(row) <= max(ci, di):
                bad_dates += 1
                continue
            code = row[ci].strip()
            raw_date = row[di].strip()
            if not code:
                null_codes += 1
            else:
                codes.add(code)
                code_prefix[code[:3]] += 1
            if not raw_date:
                null_dates += 1
                continue
            try:
                d = date.fromisoformat(raw_date[:10])
            except ValueError:
                bad_dates += 1
                continue
            ds = d.isoformat()
            if min_date is None or ds < min_date:
                min_date = ds
            if max_date is None or ds > max_date:
                max_date = ds
            if expected_start and d < expected_start:
                outside_range += 1
            if expected_end and d > expected_end:
                outside_range += 1
            key = (code, ds)
            if key in keys:
                duplicate_rows += 1
            else:
                keys.add(key)
            if mi is not None and len(row) > mi:
                market_types[row[mi].strip()] += 1
            if si is not None and len(row) > si:
                trade_status[row[si].strip()] += 1

    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "row_count": rows,
        "column_count": len(header),
        "columns": header,
        "code_column": code_col,
        "date_column": date_col,
        "min_date": min_date,
        "max_date": max_date,
        "outside_expected_range": outside_range,
        "null_codes": null_codes,
        "null_dates": null_dates,
        "bad_dates": bad_dates,
        "unique_codes": len(codes),
        "duplicate_key_rows": duplicate_rows,
        "markettype_counts": dict(market_types.most_common()),
        "trdsta_counts": dict(trade_status.most_common()),
        "code_prefix_top": dict(code_prefix.most_common(30)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--code-col", default="Stkcd")
    parser.add_argument("--date-col", default="Trddt")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.out.exists() and not args.force:
        raise SystemExit(f"Output exists (use --force): {args.out}")

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None
    meta = combine_csv_parts(args.zip, args.out)
    meta.update(
        profile_csv(args.out, args.code_col, args.date_col, start, end)
    )
    meta["expected_start"] = args.start
    meta["expected_end"] = args.end
    profile_path = args.out.with_suffix(args.out.suffix + ".profile.json")
    profile_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: meta[k] for k in (
        "out_path", "size_bytes", "row_count", "column_count",
        "min_date", "max_date", "outside_expected_range",
        "unique_codes", "duplicate_key_rows", "null_codes", "null_dates",
        "bad_dates",
    )}, ensure_ascii=False, indent=2))
    print(f"profile: {profile_path}")


if __name__ == "__main__":
    main()
