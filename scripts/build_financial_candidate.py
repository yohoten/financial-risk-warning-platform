"""在不覆盖在线契约的前提下，重建一份修正现金流缩放后的财务候选表。

背景：历史 `_load_cashflow` 与 `build_financial` 对现金流量表各乘一次 1e-8，
使 `ocf/icf/fcf_financing/capex` 比正确值小 1e8 倍。本脚本调用已修正的
`etl.csmar_import.build_financial(write=False)`，把结果写到
`data/raw/candidates/csmar_financial_cashflow_fixed.csv`，并与在线表逐列对比。

运行：
    python -m scripts.build_financial_candidate
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from etl.csmar_import import build_financial

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CAND = RAW / "candidates"
OUT = ROOT / "reports" / "data_quality"
KEY = ["stock_code", "year"]
CASHFLOW = ["ocf", "icf", "fcf_financing", "capex"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    CAND.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    fixed = build_financial(write=False)
    fixed = fixed.sort_values(KEY).reset_index(drop=True)
    path = CAND / "csmar_financial_cashflow_fixed.csv"
    fixed.to_csv(path, index=False, encoding="utf-8-sig")

    active = pd.read_csv(RAW / "csmar_financial.csv", encoding="utf-8-sig",
                         dtype={"stock_code": str}, low_memory=False)
    active["stock_code"] = active["stock_code"].astype(str).str.zfill(6)
    active["year"] = pd.to_numeric(active["year"], errors="coerce").astype(int)
    active = active.sort_values(KEY).reset_index(drop=True)

    merged = active.merge(fixed, on=KEY, how="outer", suffixes=("_active", "_fixed"), indicator=True)
    both = merged[merged["_merge"].eq("both")]

    diffs = []
    for col in active.columns:
        if col in KEY or col not in fixed.columns:
            continue
        a = pd.to_numeric(both[f"{col}_active"], errors="coerce")
        b = pd.to_numeric(both[f"{col}_fixed"], errors="coerce")
        if a.notna().sum() == 0 and b.notna().sum() == 0:
            continue
        abs_diff = (a - b).abs()
        denom = a.abs().replace(0, np.nan)
        rel = (abs_diff / denom).replace([np.inf, -np.inf], np.nan)
        diffs.append({
            "column": col,
            "max_abs_diff": float(abs_diff.max()) if abs_diff.notna().any() else None,
            "median_rel_diff": float(rel.median()) if rel.notna().any() else None,
            "rows_diff_gt_1e-9": int((abs_diff > 1e-9).sum()),
            "active_nonnull": int(a.notna().sum()),
            "fixed_nonnull": int(b.notna().sum()),
        })
    diff_df = pd.DataFrame(diffs).sort_values("rows_diff_gt_1e-9", ascending=False)
    diff_df.to_csv(OUT / "cashflow_fix_column_diff_20261114.csv", index=False, encoding="utf-8-sig")

    cashflow_summary = {}
    for col in CASHFLOW:
        a = pd.to_numeric(both[f"{col}_active"], errors="coerce")
        b = pd.to_numeric(both[f"{col}_fixed"], errors="coerce")
        ratio = (b / a.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
        cashflow_summary[col] = {
            "median_ratio_fixed_over_active": float(ratio.median()) if ratio.notna().any() else None,
            "active_median": float(a.median()) if a.notna().any() else None,
            "fixed_median": float(b.median()) if b.notna().any() else None,
        }

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "active_path": "data/raw/csmar_financial.csv",
        "candidate_path": path.relative_to(ROOT).as_posix(),
        "active_rows": int(len(active)),
        "fixed_rows": int(len(fixed)),
        "key_merge": merged["_merge"].value_counts().to_dict(),
        "cashflow": cashflow_summary,
        "non_cashflow_identical": bool(
            diff_df.loc[~diff_df["column"].isin(CASHFLOW), "rows_diff_gt_1e-9"].sum() == 0
        ),
        "columns_with_differences": diff_df.loc[diff_df["rows_diff_gt_1e-9"] > 0, "column"].tolist(),
        "sha256": sha256(path),
    }
    (OUT / "cashflow_fix_20261114.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 把候选财务表登记进 candidates manifest，保持“候选、不覆盖在线契约”的口径。
    manifest_path = CAND / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = {
            "path": path.relative_to(ROOT).as_posix(),
            "rows": int(len(fixed)),
            "columns": int(fixed.shape[1]),
            "sha256": summary["sha256"],
            "source": "etl.csmar_import.build_financial（现金流单次缩放修正）",
            "note": "仅候选；在线 csmar_financial.csv 未被覆盖；现金流列已由 1e-16 修正为 1e-8",
        }
        manifest["files"] = [f for f in manifest["files"] if f.get("path") != entry["path"]] + [entry]
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
