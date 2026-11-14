"""把下载落地区（DATA_RAW_Download）规范化到暂存区（data/incoming/csmar）。

为什么需要这一层
----------------
CSMAR 下载包是"人读"的：目录名带表名与订单号、同一张表被拆成 ``xxx.csv`` /
``xxx1.csv``、重复下载产生多个目录、还混着版权声明 PDF 和字段说明 TXT。
直接让 ETL 读这些路径会把"下载批次"写死进代码，换一次导出就会崩。

本脚本只做三件事，且不改动落地区：

1. **识别**：按目录关键字把每张表映射到 CSMAR 表代码（如 ``FS_Combas``）；
2. **规整**：把分片按文件名自然序拼接为一个 CSV（表头只保留一次），
   单表文件用硬链接/复制写入 ``data/incoming/csmar/raw/<表代码>.csv``；
3. **留痕**：写 manifest（行数、字节、SHA256、源目录、分片列表、是否新建），
   并把字段说明 ``*[DES]*.txt`` 收进 ``data/incoming/csmar/desc/``。

用法::

    python -m scripts.sync_raw_download               # 预演（默认，不写文件）
    python -m scripts.sync_raw_download --write       # 实际执行
    python -m scripts.sync_raw_download --write --force   # 已存在也重建
    python -m scripts.sync_raw_download --only FS_Combas,LA_DETAIL

大文件（资产负债表、日行情）默认按流式拼接，不整体读入内存。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from config import settings
from etl.io_utils import get_logger

logger = get_logger("raw-sync")

SRC = settings.RAW_DOWNLOAD_DIR
DST = settings.STAGING_DIR / "raw"
DESC = settings.STAGING_DIR / "desc"
CHUNK = 8 * 1024 * 1024

# 表代码 ← 目录关键字；order 决定报表顺序，仅用于打印
TABLES: list[dict] = [
    {"code": "FS_Combas", "keywords": ["资产负债表"], "file": "FS_Combas.csv", "kind": "concat"},
    {"code": "FS_Comins", "keywords": ["利润表"], "file": "FS_Comins.csv", "kind": "concat"},
    {"code": "FS_Comscfd", "keywords": ["现金流量表"], "file": "FS_Comscfd.xlsx", "kind": "xlsx"},
    {"code": "FIN_Audit", "keywords": ["审计意见表"], "file": "FIN_Audit.csv", "kind": "concat"},
    {"code": "HLD_Shareholders", "keywords": ["十大股东"], "file": "HLD_Shareholders.csv", "kind": "concat"},
    {"code": "CG_ManagerShareSalary", "keywords": ["高管人数"], "file": "CG_ManagerShareSalary.csv", "kind": "single"},
    {"code": "CG_Ybasic", "keywords": ["治理综合信息"], "file": "CG_Ybasic.csv", "kind": "concat"},
    {"code": "BDT_ManaGovAbil", "keywords": ["管理层治理能力"], "file": "BDT_ManaGovAbil.csv", "kind": "single"},
    {"code": "STK_LISTEDCOINFOANL", "keywords": ["基本信息年度表"], "file": "STK_LISTEDCOINFOANL.csv", "kind": "single"},
    {"code": "SPT_Trdchg", "keywords": ["特殊处理"], "file": "SPT_Trdchg.csv", "kind": "single"},
    {"code": "STK_Violation_Main", "keywords": ["违规信息"], "file": "STK_Violation_Main.csv", "kind": "single"},
    {"code": "LA_DETAIL", "keywords": ["诉讼仲裁"], "file": "LA_DETAIL.csv", "kind": "concat", "pick": "largest"},
    # 尚未入库但已核对可用的三张官方表（见 docs/数据缺口与补齐清单_20261114.md §3.3）
    {"code": "FI_T1", "keywords": ["偿债能力"], "file": "FI_T1.csv", "kind": "single"},
    {"code": "FS_Comscfi", "keywords": ["间接法"], "file": "FS_Comscfi.csv", "kind": "single"},
    {"code": "TRD_Year", "keywords": ["年个股回报率"], "file": "TRD_Year.csv", "kind": "single"},
    {"code": "SPT_Company", "keywords": ["公司文件"], "file": "SPT_Company.csv", "kind": "single"},
    {
        "code": "TRD_Dalyr",
        "keywords": ["日个股回报率"],
        "kind": "inventory",
        "note": "多个批次目录、分片年份区间重叠，禁止直接拼接；"
                "合并请用 scripts.ingest_csmar_export（见 data/incoming/csmar/20261114/TRD_Dly）",
    },
    {"code": "MDNA_TXT", "keywords": ["年报MDA"], "kind": "tree"},
    {"code": "DT_DB", "keywords": ["数字化转型"], "kind": "xlsx_set"},
]

PART_RE = re.compile(r"^(?P<stem>.+?)(?P<idx>\d*)\.csv$", re.IGNORECASE)
TXT_RE = re.compile(r"(?P<code>\d{6})_(?P<year>\d{4})-\d{2}-\d{2}\.txt$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count_lines(path: Path) -> int:
    """二进制计行，避免把 GB 级 CSV 读进内存；返回数据行数（不含表头）。"""
    newlines = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            newlines += chunk.count(b"\n")
    return max(newlines - 1, 0)


def _part_order(path: Path) -> tuple[int, str]:
    m = PART_RE.match(path.name)
    if not m:
        return (0, path.name.lower())
    return (int(m.group("idx") or 0), path.name.lower())


def _find_folders(keywords: list[str]) -> list[Path]:
    if not SRC.exists():
        raise FileNotFoundError(
            f"下载落地区不存在：{SRC}\n"
            "请把 CSMAR 原始导出解压到该目录，或用 RISK_RAW_DOWNLOAD_DIR 指定路径。"
        )
    hits = []
    for folder in sorted(p for p in SRC.iterdir() if p.is_dir()):
        if any(k in folder.name for k in keywords):
            hits.append(folder)
    return hits


def _csv_parts(folders: list[Path], stem: str) -> list[Path]:
    """收集某表的所有 CSV 分片，按 (序号, 文件名) 排序。"""
    parts: list[Path] = []
    for folder in folders:
        for path in folder.rglob("*.csv"):
            if path.stem.lower().startswith(stem.lower()):
                parts.append(path)
    return sorted(set(parts), key=_part_order)


def _copy_desc(folders: list[Path], write: bool) -> list[str]:
    """收集 CSMAR 字段说明（*[DES]*.txt）。"""
    moved: list[str] = []
    for folder in folders:
        for path in folder.glob("*[DES]*.txt"):
            moved.append(path.name)
            if write:
                DESC.mkdir(parents=True, exist_ok=True)
                target = DESC / path.name
                if not target.exists():
                    shutil.copy2(path, target)
    return moved


def _link_or_copy(src: Path, dst: Path) -> str:
    """同盘优先硬链接（省空间），跨盘/无权限时回退复制。"""
    try:
        os.link(src, dst)
        return "hardlink"
    except OSError:
        shutil.copy2(src, dst)
        return "copy"


def _concat(parts: list[Path], dst: Path, write: bool) -> int:
    """流式拼接分片：只保留第一个文件的表头，其余跳过首行。"""
    rows = 0
    if not write:
        return sum(_count_lines(p) for p in parts)
    with dst.open("wb") as fout:
        for i, part in enumerate(parts):
            with part.open("rb") as fin:
                if i:
                    fin.readline()  # 跳过重复表头
                last = b""
                for chunk in iter(lambda: fin.read(CHUNK), b""):
                    fout.write(chunk)
                    last = chunk[-1:]
                if last and last not in (b"\n", b"\r"):
                    fout.write(b"\r\n")
            rows += _count_lines(part)
    return rows


def plan_table(spec: dict) -> dict | None:
    folders = _find_folders(spec["keywords"])
    if not folders:
        return None

    entry: dict = {
        "code": spec["code"],
        "kind": spec["kind"],
        "sources": [str(f) for f in folders],
        "desc_files": _copy_desc(folders, write=False),
    }

    if spec["kind"] == "tree":
        files = [p for f in folders for p in f.rglob("*.txt")]
        years, codes = [], set()
        for path in files:
            m = TXT_RE.search(path.name)
            if m:
                years.append(int(m.group("year")))
                codes.add(m.group("code"))
        entry.update({
            "file_count": len(files),
            "companies": len(codes),
            "year_min": min(years) if years else None,
            "year_max": max(years) if years else None,
            "note": "文本树只做画像，不复制；用 scripts.build_text_features 直接读取落地区",
        })
        return entry

    if spec["kind"] == "xlsx_set":
        files = [p for f in folders for p in f.glob("*.xlsx")]
        entry.update({"file_count": len(files), "files": [p.name for p in files]})
        return entry

    if spec["kind"] == "inventory":
        files = sorted(p for f in folders for p in f.rglob("*.csv"))
        entry.update({
            "file_count": len(files),
            "size_bytes": sum(p.stat().st_size for p in files),
            "files": [p.name for p in files],
            "note": spec.get("note", ""),
        })
        return entry

    if spec["kind"] == "xlsx":
        files = [p for f in folders for p in f.glob("*.xlsx")]
        if not files:
            return None
        src = max(files, key=lambda p: p.stat().st_size)
        entry.update({
            "source_file": str(src),
            "size_bytes": src.stat().st_size,
            "target": str(DST / spec["file"]),
            "parts": [src.name],
        })
        return entry

    parts = _csv_parts(folders, spec.get("stem") or Path(spec["file"]).stem)
    if not parts:
        return None
    if spec.get("pick") == "largest":
        # 同表多次导出：取分片总字节最大的那批目录，避免半量导出覆盖全量
        by_folder: dict[Path, int] = {}
        for path in parts:
            by_folder[path.parent] = by_folder.get(path.parent, 0) + path.stat().st_size
        best = max(by_folder, key=by_folder.get)
        parts = [p for p in parts if p.parent == best]

    entry.update({
        "parts": [str(p) for p in parts],
        "size_bytes": sum(p.stat().st_size for p in parts),
        "target": str(DST / spec["file"]),
    })
    return entry


def execute(entry: dict, write: bool, force: bool) -> dict:
    target = Path(entry["target"])
    exists = target.exists()

    if entry["kind"] == "xlsx":
        if exists and not force:
            entry.update({"status": "skip_existing", "rows": None})
            return entry
        if write:
            DST.mkdir(parents=True, exist_ok=True)
            if exists:
                target.unlink()
            shutil.copy2(entry["source_file"], target)
            entry["sha256"] = _sha256(target)
        entry["status"] = "planned" if not write else "written"
        return entry

    parts = [Path(p) for p in entry["parts"]]
    if exists and not force:
        entry.update({"status": "skip_existing", "rows": _count_lines(target)})
        return entry

    if len(parts) == 1 and not exists:
        entry["rows"] = _count_lines(parts[0])
        entry["status"] = "planned" if not write else "written"
        if write:
            DST.mkdir(parents=True, exist_ok=True)
            entry["link"] = _link_or_copy(parts[0], target)
            entry["sha256"] = _sha256(target)
        return entry

    entry["rows"] = _concat(parts, target, write)
    entry["status"] = "planned" if not write else "written"
    if write:
        entry["sha256"] = _sha256(target)
    return entry


def main() -> None:
    parser = argparse.ArgumentParser(description="规范化 CSMAR 下架包到 data/incoming/csmar")
    parser.add_argument("--write", action="store_true", help="实际写盘（默认只预演）")
    parser.add_argument("--force", action="store_true", help="目标已存在时重建")
    parser.add_argument("--only", default=None, help="只处理指定表代码，逗号分隔")
    parser.add_argument("--manifest", type=Path, default=DST / "_manifest_raw_download.json")
    args = parser.parse_args()

    only = {s.strip() for s in args.only.split(",")} if args.only else None
    entries: list[dict] = []

    for spec in TABLES:
        if only and spec["code"] not in only:
            continue
        entry = plan_table(spec)
        if entry is None:
            logger.warning("未找到 %s（关键字 %s）", spec["code"], spec["keywords"])
            continue
        if entry["kind"] in {"tree", "xlsx_set", "inventory"}:
            entry["status"] = "profiled"
        else:
            entry = execute(entry, args.write, args.force)
        entries.append(entry)

    width = max((len(e["code"]) for e in entries), default=10)
    print(f"\n{'表代码'.ljust(width)}  {'状态':<14} {'分片':>4}  {'数据行':>12}  目标")
    for e in entries:
        print(
            f"{e['code'].ljust(width)}  {e['status']:<14} {len(e.get('parts', [])):>4}  "
            f"{(e.get('rows') or 0):>12,}  {Path(e.get('target', '')).name or e['kind']}"
        )

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_root": str(SRC),
        "staging_root": str(DST),
        "mode": "write" if args.write else "dry-run",
        "tables": entries,
    }
    if args.write:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("manifest：%s", settings.rel(args.manifest))
        logger.info("下一步：python -m scripts.convert_csmar_xlsx && python -m etl.csmar_import --step all --write")
    else:
        logger.info("预演完成；确认无误后加 --write 执行")


if __name__ == "__main__":
    main()
