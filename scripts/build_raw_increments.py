"""把本轮核验过的 CSMAR 增量写成 data/raw/candidates 候选表。

设计原则
--------
1. **不覆盖在线契约**：`ST_events.csv`、`labels_st.csv`、`csmar_governance.csv`
   保持现状；新表全部写到 `data/raw/candidates/`，经评审后再切换。
2. **保留 CSMAR 原始列名**：两职合一紧凑表继续使用 `Symbol/Enddate/...`；
   只有项目契约表（`governance_ext.csv`、`legal_events.csv`）使用 snake_case。
3. **可复现**：所有输出附带行数、列数、SHA256 与来源，写入 manifest。

运行：
    python -m scripts.build_raw_increments
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INCOMING = ROOT / "data" / "incoming" / "csmar"
CAND = RAW / "candidates"

KEY = ["stock_code", "year"]
A_SHARE_PREFIXES = {"000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688", "689"}
YEAR_MIN, YEAR_MAX = 2013, 2026


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    """写入 UTF-8 BOM CSV；若同名旧文件内容不同，先留时间戳备份。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + f".bak_{datetime.now():%Y%m%d_%H%M%S}")
        shutil.copy2(path, backup)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _normalize_code(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.extract(r"(\d{1,6})", expand=False)
        .str.zfill(6)
    )


def _record(path: Path, source: str, note: str) -> dict:
    df = pd.read_csv(path, encoding="utf-8-sig", nrows=0)
    with path.open(encoding="utf-8-sig") as fh:
        rows = sum(1 for _ in fh) - 1
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "rows": rows,
        "columns": len(df.columns),
        "sha256": _sha256(path),
        "source": source,
        "note": note,
    }


def copy_official_st() -> list[dict]:
    """官方 ST 事件与标签进入候选区，不替换代理标签。"""
    entries = []
    for name, source, note in [
        (
            "ST_events_official.csv",
            "SPT_Trdchg（特殊处理变动文件，1998-04-28 至 2026-11-13）",
            "1,539 段 ST/*ST 区间；保留事件级字段；未替换 data/raw/ST_events.csv",
        ),
        (
            "labels_st_official.csv",
            "ST_events_official.csv + csmar_financial.csv 公司-年键",
            "2013–2025 共 48,290 个公司-年；未替换 data/raw/labels_st.csv",
        ),
    ]:
        src, dst = INCOMING / name, CAND / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        entries.append(_record(dst, source, note))
    return entries


def build_duality() -> list[dict]:
    """两职合一紧凑表 + 项目治理增量契约。"""
    src = INCOMING / "CG_duality_2013_2025.csv"
    df = pd.read_csv(src, encoding="utf-8-sig", dtype=str)
    df["Enddate"] = df["Enddate"].fillna("").str.strip()
    df = df[df["Enddate"].str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)].copy()
    df["year"] = df["Enddate"].str[:4].astype(int)
    df = df[df["year"].between(2013, 2025)]
    df["Symbol"] = _normalize_code(df["Symbol"])
    df = df.dropna(subset=["Symbol", "year"]).drop_duplicates(["Symbol", "Enddate"])
    df = df.sort_values(["Symbol", "Enddate"]).reset_index(drop=True)

    raw_path = CAND / "CG_duality_2013_2025.csv"
    _write_csv(df, raw_path)

    work = df.copy()
    work["stock_code"] = work["Symbol"]
    work["year"] = work["year"].astype(int)
    for src_col, dst_col in [
        ("ConcurrentPosition", "duality"),
        ("Boardsize", "board_size_cg"),
        ("SupervisorSize", "supervisor_size"),
        ("ExecutivesNumber", "executives_number"),
        ("PropertyRightsNature", "ownership_nature"),
    ]:
        work[dst_col] = pd.to_numeric(work[src_col], errors="coerce")
    for src_col, dst_col in [
        ("IndDirectorRatio", "independent_ratio_cg"),
        ("Mngmhldn", "management_holding_cg"),
        ("ContrshrProportion", "control_proportion"),
    ]:
        work[dst_col] = pd.to_numeric(work[src_col], errors="coerce") / 100.0
    work["duality_source"] = "CSMAR.BDT_ManaGovAbil.ConcurrentPosition"
    # CSMAR 用 0 表示缺失/未披露；董事会人数不可能为 0，按缺失处理。
    work["board_size_cg"] = work["board_size_cg"].where(work["board_size_cg"] > 0)

    contract_cols = [
        *KEY, "duality", "board_size_cg", "independent_ratio_cg",
        "management_holding_cg", "supervisor_size", "executives_number",
        "ownership_nature", "control_proportion", "duality_source",
    ]
    contract = work[contract_cols].drop_duplicates(KEY).sort_values(KEY).reset_index(drop=True)
    contract_path = CAND / "governance_ext.csv"
    _write_csv(contract, contract_path)
    return [
        _record(
            raw_path,
            "BDT_ManaGovAbil（管理层治理能力）",
            "保留 CSMAR 原始字段名；2013–2025；Symbol+Enddate 唯一",
        ),
        _record(
            contract_path,
            "BDT_ManaGovAbil；比例已由百分数转为小数",
            "项目治理增量契约；duality 非空率见报告；未合并进 csmar_governance.csv",
        ),
    ]


def build_legal_events() -> list[dict]:
    """诉讼 + 处罚 → 公司-年契约表；缺失事件显式补 0。"""
    legal = pd.read_csv(
        INCOMING / "LEGAL_company_year_2013_2026.csv", encoding="utf-8-sig", dtype=str
    )
    legal["stock_code"] = _normalize_code(legal["stock_code"])
    legal["year"] = pd.to_numeric(legal["year"], errors="coerce")
    legal = legal.dropna(subset=["stock_code", "year"]).copy()
    legal["year"] = legal["year"].astype(int)
    # 与财务/标签同一 A 股口径；原始 LAW_lawsuit.csv 仍保留全量。
    legal = legal[legal["stock_code"].str[:3].isin(A_SHARE_PREFIXES)].copy()
    for col in ["lawsuit_count", "lawsuit_amount_cny", "non_cny_count", "penalty_count", "penalty_amount_sum"]:
        legal[col] = pd.to_numeric(legal[col], errors="coerce")
    legal = legal.rename(columns={"lawsuit_count": "litigation_count"})
    legal = legal.drop_duplicates(KEY)

    fin = pd.read_csv(
        RAW / "csmar_financial.csv",
        encoding="utf-8-sig",
        dtype={"stock_code": str},
        usecols=["stock_code", "year"],
    )
    fin["stock_code"] = _normalize_code(fin["stock_code"])
    fin["year"] = pd.to_numeric(fin["year"], errors="coerce")
    fin = fin.dropna(subset=KEY).copy()
    fin["year"] = fin["year"].astype(int)
    fin = fin[fin["year"].between(2013, 2025)]
    fin = fin[fin["stock_code"].str[:3].isin(A_SHARE_PREFIXES)]
    keys = fin[KEY].drop_duplicates()

    # 2026 年财务键尚未披露，但诉讼/处罚公告已存在；保留已观测的 2026 键，
    # 不把 2025 年公司集合外推到 2026（避免幸存者偏差）。
    legal_2026 = legal[legal["year"].eq(2026)][KEY]
    grid = pd.concat([keys, legal_2026], ignore_index=True).drop_duplicates(KEY)

    out = grid.merge(legal, on=KEY, how="left", validate="one_to_one")
    out["has_lawsuit"] = out["litigation_count"].fillna(0).gt(0).astype(int)
    out["has_penalty"] = out["penalty_count"].fillna(0).gt(0).astype(int)
    for col in ["litigation_count", "penalty_count", "non_cny_count"]:
        out[col] = out[col].fillna(0).astype(int)
    out["legal_event_count"] = out["litigation_count"] + out["penalty_count"]
    out["legal_source"] = out["legal_event_count"].gt(0).map(
        {True: "CSMAR.LA_DETAIL+STK_Violation_Main", False: "none_observed"}
    )
    out = out.sort_values(KEY).reset_index(drop=True)
    out = out[
        [
            *KEY, "litigation_count", "lawsuit_amount_cny", "non_cny_count",
            "penalty_count", "penalty_amount_sum", "legal_event_count",
            "has_lawsuit", "has_penalty", "legal_source",
        ]
    ]
    path = CAND / "legal_events.csv"
    _write_csv(out, path)
    return [
        _record(
            path,
            "LA_DETAIL（诉讼仲裁）+ STK_Violation_Main（违规处罚）",
            "2013–2025 财务公司-年全集 + 2026 已观测事件键；无事件补 0",
        )
    ]


def main() -> None:
    CAND.mkdir(parents=True, exist_ok=True)
    entries = []
    entries += copy_official_st()
    entries += build_duality()
    entries += build_legal_events()

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "policy": "candidate_only; active raw contracts are not overwritten",
        "candidate_dir": CAND.relative_to(ROOT).as_posix(),
        "files": entries,
    }
    manifest_path = CAND / "manifest.json"
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        known = {e["path"] for e in entries}
        for entry in old.get("files", []):
            if entry.get("path") not in known and (ROOT / entry["path"]).exists():
                entries.append(entry)
        manifest["files"] = entries
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
