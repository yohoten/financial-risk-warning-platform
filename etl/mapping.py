"""CSMAR / Wind 导出字段映射：源系统列名 → 项目 raw 契约列。

设计要点
--------
1. 映射规则集中在 `data/mapping/csmar.yaml`，代码只负责执行，避免口径散落；
2. 匹配时忽略空格、全角/半角与英文大小写，兼容 CSMAR 不同导出模板；
3. 金额单位在映射层换算（元 → 亿元），下游 ETL 不再感知源系统单位；
4. 未命中列、缺失必需列、被忽略的源列都会进入导入报告，先看清再写盘。

用法
----
    python -m etl.mapping --list
    python -m etl.mapping --source D:\\csmar\\export --table financial --dry-run
    python -m etl.mapping --source D:\\csmar\\export --table financial --write
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from config import settings
from etl.io_utils import get_logger, write_table

logger = get_logger("mapping")

MAPPING_PATH = settings.DATA_DIR / "mapping" / "csmar.yaml"


class MappingError(ValueError):
    """映射结果不满足 raw 契约（必需列缺失等）。"""


def load_mapping(path: Path | str | None = None) -> dict:
    """读取映射配置；文件缺失或格式错误时抛出明确异常。"""
    path = Path(path or MAPPING_PATH)
    if not path.exists():
        raise FileNotFoundError(f"未找到字段映射文件：{path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if "tables" not in payload:
        raise MappingError(f"映射文件缺少 tables 节点：{path}")
    return payload


def normalize_name(name: Any) -> str:
    """列名归一化：全角转半角、去空白、英文小写。"""
    text = unicodedata.normalize("NFKC", str(name))
    return re.sub(r"\s+", "", text).lower()


def _to_stock_code(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    digits = text.str.extract(r"(\d{1,6})", expand=False)
    return digits.str.zfill(6)


def _to_year(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.extract(r"(\d{4})", expand=False)
    return pd.to_numeric(text, errors="coerce").astype("Int64")


def _audit_opinion_flag(series: pd.Series) -> pd.Series:
    """审计意见 → 0=标准无保留，1=非标准（保留/无法表示/否定/带强调段）。"""
    numeric = pd.to_numeric(series, errors="coerce")
    text = series.astype(str)
    flag = pd.Series(pd.NA, index=series.index, dtype="Int64")
    known = numeric.notna()
    flag.loc[known] = (numeric.loc[known] != 1).astype(int)
    masked = ~known & series.notna()
    if masked.any():
        standard = text.loc[masked].str.contains("标准无保留", na=False)
        flag.loc[masked] = (~standard).astype(int)
    return flag


def _st_flag(series: pd.Series) -> pd.Series:
    """ST 状态 → 0/1，兼容 0/1、是/否、ST/*ST 等写法。"""
    text = series.astype(str).str.strip().str.upper()
    flag = pd.Series(pd.NA, index=series.index, dtype="Int64")
    positive = {"1", "是", "ST", "*ST", "退市风险警示", "其他风险警示"}
    negative = {"0", "否", "正常", "非ST", "N"}
    flag[text.isin(positive)] = 1
    flag[text.isin(negative)] = 0
    return flag


_TRANSFORMS = {
    "stock_code": _to_stock_code,
    "year": _to_year,
    "audit_opinion_flag": _audit_opinion_flag,
    "st_flag": _st_flag,
}

_DTYPES = {
    "str": "string",
    "float": "float64",
    "int": "Int64",
}


def _cast(series: pd.Series, dtype: str | None, transform: str | None) -> pd.Series:
    if transform:
        if transform not in _TRANSFORMS:
            raise MappingError(f"未知 transform：{transform}")
        series = _TRANSFORMS[transform](series)
    if dtype == "float":
        return pd.to_numeric(series, errors="coerce").astype("float64")
    if dtype == "int":
        return pd.to_numeric(series, errors="coerce").round().astype("Int64")
    if dtype == "str":
        out = series.astype("string").str.strip()
        return out.mask(out.str.lower().isin({"nan", "none", "<na>", ""}))
    return series


def apply_mapping(df: pd.DataFrame, table: str, mapping: dict | None = None, strict: bool = False) -> tuple[pd.DataFrame, dict]:
    """按映射把源表转换为 raw 契约表，返回 (转换结果, 导入报告)。"""
    mapping = mapping or load_mapping()
    if table not in mapping["tables"]:
        raise KeyError(f"映射中不存在表：{table}")
    spec = mapping["tables"][table]

    lookup = {normalize_name(c): c for c in df.columns}
    out = pd.DataFrame(index=df.index)
    matched: dict[str, str] = {}
    missing: list[str] = []
    scaled: list[str] = []

    for target, rule in spec.get("columns", {}).items():
        aliases = [target, *rule.get("aliases", [])]
        source = next((lookup[normalize_name(a)] for a in aliases if normalize_name(a) in lookup), None)
        if source is None:
            missing.append(target)
            continue
        series = df[source]
        scale = float(rule.get("scale", 1.0))
        if scale != 1.0:
            series = pd.to_numeric(series, errors="coerce") * scale
            scaled.append(target)
        out[target] = _cast(series, rule.get("dtype"), rule.get("transform"))
        matched[target] = str(source)

    required_missing = [c for c in spec.get("required", []) if c not in out.columns]
    used_sources = set(matched.values())
    report = {
        "table": table,
        "source_rows": int(len(df)),
        "source_columns": int(df.shape[1]),
        "matched": matched,
        "missing_optional": [c for c in missing if c not in spec.get("required", [])],
        "required_missing": required_missing,
        "scaled_columns": scaled,
        "unused_source": [str(c) for c in df.columns if c not in used_sources],
    }

    if strict and required_missing:
        raise MappingError(f"{table} 缺少必需列：{required_missing}")

    logger.info(
        "映射 %s：命中 %d/%d 列，必需列缺失 %d 个，单位换算 %d 列",
        table, len(matched), len(spec.get("columns", {})), len(required_missing), len(scaled),
    )
    return out, report


def find_source_file(source_dir: Path | str, table: str, mapping: dict | None = None) -> Path | None:
    """按映射中的 files 通配符查找源文件（先精确模式，后递归）。"""
    mapping = mapping or load_mapping()
    spec = mapping["tables"][table]
    root = Path(source_dir)
    if not root.exists():
        raise FileNotFoundError(f"源目录不存在：{root}")
    for pattern in spec.get("files", []):
        hits = sorted(root.glob(pattern))
        if not hits:
            hits = sorted(root.rglob(pattern))
        if hits:
            return hits[0]
    return None


def read_source(path: Path) -> pd.DataFrame:
    """读取源文件：csv 自动尝试 UTF-8/GBK，xlsx 走 openpyxl。"""
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    try:
        return pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="gbk", dtype=str)


def import_table(source_dir: Path | str, table: str, write: bool = False, mapping: dict | None = None) -> dict:
    """导入单表：查找源文件 → 映射 → （可选）写入 raw 目标路径。"""
    mapping = mapping or load_mapping()
    path = find_source_file(source_dir, table, mapping)
    if path is None:
        return {"table": table, "status": "missing_file", "file": None}
    raw = read_source(path)
    mapped, report = apply_mapping(raw, table, mapping)
    report["file"] = str(path)
    report["status"] = "blocked" if report["required_missing"] else "ok"
    if write and not report["required_missing"]:
        target = settings.PROJECT_ROOT / mapping["tables"][table]["target"]
        write_table(mapped, target)
        report["written"] = settings.rel(target)
        logger.info("已写入：%s", settings.rel(target))
    elif write:
        logger.warning("%s 必需列缺失，未写入：%s", table, report["required_missing"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="CSMAR/Wind 字段映射与导入")
    parser.add_argument("--source", type=Path, help="CSMAR 导出目录")
    parser.add_argument("--table", default=None, help="表名；缺省导入全部映射表")
    parser.add_argument("--mapping", type=Path, default=None, help="映射文件路径")
    parser.add_argument("--write", action="store_true", help="写入 data/raw 目标文件（默认仅演练）")
    parser.add_argument("--list", action="store_true", help="列出映射表")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出报告")
    args = parser.parse_args()

    mapping = load_mapping(args.mapping)
    if args.list:
        for name, spec in mapping["tables"].items():
            print(f"{name:18s} → {spec['target']}  required={spec.get('required', [])}")
        return

    if not args.source:
        parser.error("需要 --source 目录，或使用 --list 查看映射表")

    tables = [args.table] if args.table else list(mapping["tables"])
    unknown = [t for t in tables if t not in mapping["tables"]]
    if unknown:
        parser.error(f"未知表名：{unknown}")

    reports = [import_table(args.source, t, write=args.write, mapping=mapping) for t in tables]
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
        return

    for rep in reports:
        if rep.get("status") == "missing_file":
            print(f"[缺失] {rep['table']}：源目录中未找到匹配文件")
            continue
        flag = "OK" if rep["status"] == "ok" else "BLOCKED"
        print(f"[{flag}] {rep['table']}：{rep['source_rows']} 行，命中 {len(rep['matched'])} 列，"
              f"必需列缺失 {rep['required_missing'] or '无'}")
        if rep.get("unused_source"):
            print(f"        忽略源列：{', '.join(rep['unused_source'][:8])}"
                  f"{' ...' if len(rep['unused_source']) > 8 else ''}")
        if rep.get("written"):
            print(f"        已写入：{rep['written']}")
    blocked = sum(1 for r in reports if r.get("status") == "blocked")
    if blocked:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
