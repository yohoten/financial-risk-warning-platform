"""原始数据质量校验：接入真实数据前的最低门槛检查。

检查项
------
1. 文件与表结构：文件存在、必需列齐全、表非空；
2. 主键完整性：stock_code/year 非空、唯一，股票代码为 6 位；
3. 数值健康度：inf、缺失率、资产=负债+权益、流动资产与存货关系、资不抵债比例；
4. 标签口径：is_st ∈ {0,1}、正样本率是否落在合理区间；
5. 跨表覆盖：治理/文本/市场/司法与财务主表的主键覆盖率，标签对建模窗口的覆盖；
6. 年份覆盖：2015-2024 建模窗口是否齐全。

输出
----
`reports/data_quality/data_quality_report.md` + `.json`；存在阻断项时退出码为 1。

用法
----
    python -m scripts.validate_raw_data
    python -m scripts.validate_raw_data --raw-dir data/raw --out-dir reports/data_quality
    python -m scripts.validate_raw_data --source D:\\csmar\\export   # 同时检查字段映射覆盖率
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from config import settings
from config.feature_registry import TARGET_COLUMN
from etl.io_utils import get_logger, read_table, resolve

logger = get_logger("data-quality")

MISSING_RATE_WARN = 0.30
IDENTITY_TOL = 0.01
MODELING_YEARS = list(range(settings.TRAIN_YEAR_RANGE[0], settings.TEST_YEAR + 1))
TARGET_LEVELS = {"error", "warning", "info"}
# 与 etl/csmar_import.py 的标签样本口径保持一致：只保留沪深 A 股
A_SHARE_PREFIXES = ("000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688")


@dataclass(frozen=True)
class TableSpec:
    name: str
    path: Path
    key: tuple[str, ...]
    required: tuple[str, ...]
    kind: str = "panel"  # panel / labels / macro


def build_specs(raw_dir: Path | str | None = None, external_dir: Path | str | None = None) -> dict[str, TableSpec]:
    raw = Path(raw_dir or settings.RAW_DIR)
    external = Path(external_dir or settings.EXTERNAL_DIR)
    return {
        "financial": TableSpec(
            "financial", raw / settings.RAW_FINANCIAL.name, ("stock_code", "year"),
            ("stock_code", "year", "total_assets", "total_liabilities", "equity",
             "revenue", "net_profit", "ocf"), "panel",
        ),
        "governance": TableSpec(
            "governance", raw / settings.RAW_GOVERNANCE.name, ("stock_code", "year"),
            ("stock_code", "year", "top1_holding", "board_size", "independent_directors"), "panel",
        ),
        "text_sentiment": TableSpec(
            "text_sentiment", raw / settings.RAW_TEXT_SENTIMENT.name, ("stock_code", "year"),
            ("stock_code", "year", "sentiment_polarity", "mdna_uncertainty"), "panel",
        ),
        "market_features": TableSpec(
            "market_features", raw / settings.RAW_MARKET.name, ("stock_code", "year"),
            ("stock_code", "year", "audit_opinion"), "panel",
        ),
        "legal_events": TableSpec(
            "legal_events", raw / settings.RAW_LEGAL.name, ("stock_code", "year"),
            ("stock_code", "year", "litigation_count"), "panel",
        ),
        "labels_st": TableSpec(
            "labels_st", raw / settings.RAW_LABELS.name, ("stock_code", "year"),
            ("stock_code", "year", TARGET_COLUMN), "labels",
        ),
        "macro_industry": TableSpec(
            "macro_industry", external / settings.RAW_MACRO.name, ("year",),
            ("year", "gdp_growth", "m2_growth"), "macro",
        ),
    }


def _issue(level: str, table: str, check: str, message: str, detail: Any = None) -> dict:
    if level not in TARGET_LEVELS:
        raise ValueError(f"未知级别：{level}")
    return {"level": level, "table": table, "check": check, "message": message, "detail": detail}


def _display_path(path: Path) -> str:
    try:
        return settings.rel(path)
    except Exception:
        return str(path)


def _missing_rate_issues(df: pd.DataFrame, table: str) -> list[dict]:
    issues: list[dict] = []
    rates = df.isna().mean()
    bad = rates[rates > MISSING_RATE_WARN].sort_values(ascending=False)
    if len(bad):
        top = {str(k): round(float(v), 4) for k, v in bad.head(5).items()}
        issues.append(_issue(
            "warning", table, "missing_rate",
            f"{len(bad)} 列缺失率超过 {MISSING_RATE_WARN:.0%}，最高 {bad.iloc[0]:.1%}", top,
        ))
    return issues


def _key_issues(df: pd.DataFrame, table: str, key: tuple[str, ...]) -> list[dict]:
    issues: list[dict] = []
    if not all(k in df.columns for k in key):
        return issues
    nulls = int(df[list(key)].isna().any(axis=1).sum())
    if nulls:
        issues.append(_issue("error", table, "key_null", f"主键存在 {nulls} 行空值"))
    dup = int(df.duplicated(subset=list(key)).sum())
    if dup:
        issues.append(_issue("error", table, "key_duplicate", f"主键重复 {dup} 行"))
    return issues


def _stock_code_issues(df: pd.DataFrame, table: str) -> list[dict]:
    if "stock_code" not in df.columns:
        return []
    # CSV 往返会丢失前导零（002000 → 2000），先按 ETL 同口径补零再校验
    codes = (df["stock_code"].astype(str).str.strip()
             .str.replace(r"\.0$", "", regex=True).str.zfill(6))
    bad = codes[~codes.str.fullmatch(r"\d{6}")]
    if len(bad):
        return [_issue("warning", table, "stock_code_format",
                       f"{len(bad)} 行股票代码无法恢复为 6 位数字", sorted(bad.unique())[:5])]
    return []


def _year_issues(df: pd.DataFrame, table: str) -> list[dict]:
    if "year" not in df.columns:
        return []
    years = pd.to_numeric(df["year"], errors="coerce")
    bad = int(years.isna().sum() + ((years < 2000) | (years > 2100)).sum())
    if bad:
        return [_issue("warning", table, "year_format", f"{bad} 行年度缺失或越界（2000-2100）")]
    return []


def _infinite_issues(df: pd.DataFrame, table: str) -> list[dict]:
    numeric = df.select_dtypes(include=["number"])
    if numeric.empty:
        return []
    count = int((numeric == float("inf")).sum().sum() + (numeric == float("-inf")).sum().sum())
    if count:
        return [_issue("error", table, "infinite_value", f"存在 {count} 个 inf/-inf 值")]
    return []


def _numeric_column(df: pd.DataFrame, name: str) -> pd.Series | None:
    if name not in df.columns:
        return None
    return pd.to_numeric(df[name], errors="coerce")


def _financial_issues(df: pd.DataFrame) -> list[dict]:
    table = "financial"
    issues: list[dict] = []
    assets = _numeric_column(df, "total_assets")
    liabilities = _numeric_column(df, "total_liabilities")
    equity = _numeric_column(df, "equity")

    if assets is not None and (assets <= 0).any():
        issues.append(_issue("error", table, "assets_nonpositive",
                             f"{(assets <= 0).sum()} 行总资产 ≤ 0"))

    if assets is not None and liabilities is not None and equity is not None:
        mask = assets.notna() & liabilities.notna() & equity.notna()
        if mask.any():
            diff = (assets[mask] - liabilities[mask] - equity[mask]).abs() / assets[mask].abs().clip(lower=1e-6)
            bad = int((diff > IDENTITY_TOL).sum())
            if bad:
                issues.append(_issue("warning", table, "accounting_identity",
                                     f"{bad}/{int(mask.sum())} 行不满足 资产=负债+权益（容差 {IDENTITY_TOL:.0%}）"))

    ca = _numeric_column(df, "current_assets")
    inventory = _numeric_column(df, "inventory")
    if ca is not None and inventory is not None:
        mask = ca.notna() & inventory.notna()
        bad = int((inventory[mask] > ca[mask]).sum())
        if bad:
            issues.append(_issue("warning", table, "current_assets_inventory",
                                 f"{bad} 行存货大于流动资产，疑似口径或单位错误"))

    if assets is not None and liabilities is not None:
        mask = assets.notna() & liabilities.notna() & (assets > 0)
        bad = int((liabilities[mask] > assets[mask] * 1.05).sum())
        if bad:
            issues.append(_issue("warning", table, "liabilities_over_assets",
                                 f"{bad} 行负债超过总资产 105%（资不抵债口径需确认）"))
    return issues


def _label_issues(df: pd.DataFrame) -> list[dict]:
    table = "labels_st"
    issues: list[dict] = []
    if TARGET_COLUMN not in df.columns:
        return issues
    values = pd.to_numeric(df[TARGET_COLUMN], errors="coerce")
    invalid = int((~values.isin([0, 1])).sum())
    if invalid:
        issues.append(_issue("error", table, "label_binary", f"{invalid} 行标签不是 0/1"))
    valid = values.dropna()
    if len(valid):
        rate = float(valid.mean())
        if not 0.01 <= rate <= 0.50:
            issues.append(_issue("warning", table, "label_rate",
                                 f"ST 正样本率 {rate:.2%} 超出合理区间 [1%, 50%]"))
    return issues


def inspect_table(spec: TableSpec) -> dict:
    path = resolve(spec.path)
    result = {
        "name": spec.name, "path": _display_path(spec.path),
        "exists": path is not None, "rows": 0, "columns": 0,
        "issues": [],
    }
    if path is None:
        result["issues"].append(_issue("error", spec.name, "file_missing", f"文件不存在：{result['path']}"))
        return result

    try:
        df = read_table(spec.path)
    except Exception as exc:  # 文件损坏 / 编码异常
        result["issues"].append(_issue("error", spec.name, "read_failed", f"读取失败：{exc}"))
        return result

    result.update(rows=int(len(df)), columns=int(df.shape[1]))
    if df.empty:
        result["issues"].append(_issue("error", spec.name, "empty_table", "表为空"))
        return result

    missing = [c for c in spec.required if c not in df.columns]
    if missing:
        result["issues"].append(_issue("error", spec.name, "required_columns",
                                       f"缺少必需列 {len(missing)} 个", missing))

    issues = result["issues"]
    issues += _key_issues(df, spec.name, spec.key)
    if spec.kind != "macro":
        issues += _stock_code_issues(df, spec.name)
    issues += _year_issues(df, spec.name)
    issues += _infinite_issues(df, spec.name)
    issues += _missing_rate_issues(df, spec.name)

    if spec.name == "financial":
        issues += _financial_issues(df)
    if spec.kind == "labels":
        issues += _label_issues(df)

    result["errors"] = sum(1 for i in issues if i["level"] == "error")
    result["warnings"] = sum(1 for i in issues if i["level"] == "warning")
    result["year_min"] = int(pd.to_numeric(df["year"], errors="coerce").min()) if "year" in df else None
    result["year_max"] = int(pd.to_numeric(df["year"], errors="coerce").max()) if "year" in df else None
    return result


def _keys(df: pd.DataFrame, columns: tuple[str, ...]) -> set[tuple]:
    if not all(c in df.columns for c in columns):
        return set()
    return set(df[list(columns)].astype(str).itertuples(index=False, name=None))


def cross_table_checks(frames: dict[str, pd.DataFrame]) -> tuple[list[dict], dict]:
    issues: list[dict] = []
    fin = frames.get("financial")
    if fin is None or fin.empty:
        return issues, {}

    fin_keys = _keys(fin, ("stock_code", "year"))
    fin_modeling = fin[pd.to_numeric(fin["year"], errors="coerce").isin(MODELING_YEARS)]
    fin_modeling_keys = _keys(fin_modeling, ("stock_code", "year"))
    coverage: dict[str, float] = {}
    for name, df in frames.items():
        if name in {"financial", "macro_industry"}:
            continue
        keys = _keys(df, ("stock_code", "year"))
        expected = fin_keys
        if name == "labels_st":
            # 标签按 T-2 对齐，只要求覆盖建模窗口，不强求覆盖更早的特征年份
            keys = _keys(df[pd.to_numeric(df["year"], errors="coerce").isin(MODELING_YEARS)],
                         ("stock_code", "year"))
            expected = fin_modeling_keys
        if not expected:
            continue
        ratio = len(expected & keys) / len(expected)
        coverage[name] = round(ratio, 4)
        if ratio < 0.90 and name != "labels_st":
            issues.append(_issue("warning", name, "key_coverage",
                                 f"与财务主表主键覆盖率仅 {ratio:.1%}，可能导致大量样本在合并时丢失"))

    labels = frames.get("labels_st")
    if labels is not None and not labels.empty:
        # 标签按 T-2 对齐：特征年 y 需要 y+LABEL_HORIZON 年的 ST 状态
        label_years = {y + settings.LABEL_HORIZON for y in MODELING_YEARS}
        modeling = labels[pd.to_numeric(labels["year"], errors="coerce").isin(label_years)]
        label_keys = _keys(modeling, ("stock_code", "year"))
        # 财务表含 B 股/北交所；标签已按 A 股过滤，覆盖检查也只看 A 股
        fin_a_keys = {
            k for k in fin_modeling_keys
            if str(k[0]).strip().zfill(6)[:3] in A_SHARE_PREFIXES
        }
        if fin_a_keys:
            def _shifted(key: tuple) -> tuple | None:
                code, year = key
                try:
                    return code, str(int(float(year)) + settings.LABEL_HORIZON)
                except (TypeError, ValueError):
                    return None

            covered = {k for k in fin_a_keys if _shifted(k) in label_keys}
            ratio = len(covered) / len(fin_a_keys)
            coverage["labels_st@modeling_window"] = round(ratio, 4)
            if ratio < 0.95:
                missing_keys = fin_a_keys - covered
                year_counts: dict[int, int] = {}
                for _, year in missing_keys:
                    if str(year).strip().isdigit():
                        y = int(year)
                        year_counts[y] = year_counts.get(y, 0) + 1
                top_years = sorted(year_counts.items(), key=lambda item: -item[1])[:3]
                hint = ("；缺口最多的特征年："
                        + "、".join(f"{y}({n})" for y, n in top_years)
                        + "（这些年的 T+2 标签缺失；2024 特征年需要 2026 年 ST 事件）"
                        if top_years else "")
                issues.append(_issue("error", "labels_st", "label_coverage",
                                     f"按 T+{settings.LABEL_HORIZON} 对齐，建模窗口内仅 {ratio:.1%} 的公司-年有 ST 标签{hint}"))

    return issues, coverage


def year_coverage(frames: dict[str, pd.DataFrame]) -> dict:
    fin = frames.get("financial")
    if fin is None or fin.empty or "year" not in fin.columns:
        return {}
    years = pd.to_numeric(fin["year"], errors="coerce")
    counts = years.value_counts().sort_index()
    labels = frames.get("labels_st")
    label_map = {}
    if labels is not None and TARGET_COLUMN in labels.columns:
        label_map = (labels.groupby(pd.to_numeric(labels["year"], errors="coerce"))[TARGET_COLUMN]
                     .mean().round(4).to_dict())
    return {
        int(y): {"rows": int(n), "st_rate": float(label_map.get(y, float("nan"))) if y in label_map else None}
        for y, n in counts.items()
    }


def _markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        "# 原始数据质量报告",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 数据目录：`{report['raw_dir']}` / `{report['external_dir']}`",
        f"- 结论：**{'存在阻断项，需修复后再跑 ETL' if s['errors'] else '通过最低门槛，可进入 ETL'}**",
        f"- 汇总：{s['tables']} 张表，{s['rows']} 行，{s['errors']} 个错误、{s['warnings']} 个警告",
        "",
        "## 一、总览",
        "",
        "| 表 | 行数 | 列数 | 错误 | 警告 | 年度范围 | 文件 |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in report["tables"]:
        years = f"{t.get('year_min')}–{t.get('year_max')}" if t.get("year_min") else "-"
        lines.append(
            f"| {t['name']} | {t['rows']} | {t['columns']} | {t.get('errors', 0)} | "
            f"{t.get('warnings', 0)} | {years} | `{t['path']}` |"
        )

    lines += ["", "## 二、问题明细", ""]
    any_issue = False
    for t in report["tables"]:
        if not t["issues"]:
            continue
        any_issue = True
        lines.append(f"### {t['name']}")
        lines.append("")
        for item in t["issues"]:
            icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}[item["level"]]
            detail = f"：`{json.dumps(item['detail'], ensure_ascii=False)}`" if item.get("detail") else ""
            lines.append(f"- {icon} **{item['check']}** · {item['message']}{detail}")
        lines.append("")
    if not any_issue:
        lines.append("未发现结构、主键、数值或标签层面的问题。")
        lines.append("")

    lines += ["## 三、跨表覆盖", "", "| 表 | 与财务主表主键覆盖率 |", "|---|---|"]
    for name, ratio in report.get("coverage", {}).items():
        lines.append(f"| {name} | {ratio:.2%} |")

    lines += ["", "## 四、年度分布", "", "| 年份 | 公司-年记录 | ST 正样本率 |", "|---|---|---|"]
    for year, info in report.get("year_coverage", {}).items():
        rate = "-" if info.get("st_rate") is None else f"{info['st_rate']:.2%}"
        lines.append(f"| {year} | {info['rows']} | {rate} |")

    if report.get("mapping"):
        lines += ["", "## 五、字段映射检查", "", "| 表 | 源文件 | 行数 | 命中列 | 必需列缺失 |", "|---|---|---|---|---|"]
        for rep in report["mapping"]:
            if rep.get("status") == "missing_file":
                lines.append(f"| {rep['table']} | 未找到 | - | - | - |")
                continue
            lines.append(
                f"| {rep['table']} | `{Path(rep['file']).name}` | {rep['source_rows']} | "
                f"{len(rep['matched'])} | {rep['required_missing'] or '无'} |"
            )

    lines += ["", "## 六、建议", ""]
    codes = {i["check"] for t in report["tables"] for i in t["issues"]}
    advice = []
    if "file_missing" in codes or "required_columns" in codes:
        advice.append("先补齐缺失表/字段，或调整 `data/mapping/csmar.yaml` 的别名与必需列。")
    if "key_duplicate" in codes or "key_null" in codes:
        advice.append("按 `stock_code + year` 去重并检查主键空值；注意股票代码前导零。")
    if "stock_code_format" in codes:
        advice.append("股票代码统一为 6 位字符串（如 `000001`），避免合并时静默丢样本。")
    if "accounting_identity" in codes or "liabilities_over_assets" in codes:
        advice.append("核对报表口径与单位（元/万元/亿元）、是否合并报表、少数股东权益是否计入。")
    if "key_coverage" in codes or "label_coverage" in codes:
        advice.append("检查跨表主键格式与年份范围；标签需覆盖 2015-2024 建模窗口。")
    if "missing_rate" in codes:
        advice.append("高缺失字段需说明缺失机制；必要时在特征筛选中剔除或改用行业-年度中位数。")
    if not advice:
        advice.append("数据满足进入 ETL 的最低要求；建议先跑 `python -m etl.run_pipeline`，"
                      "再对照 `feature_selection_report.csv` 检查筛选链是否异常。")
    lines += [f"{i}. {a}" for i, a in enumerate(advice, 1)]
    lines.append("")
    return "\n".join(lines)


def validate_dataset(
    raw_dir: Path | str | None = None,
    external_dir: Path | str | None = None,
    out_dir: Path | str | None = None,
    write: bool = True,
    source_dir: Path | str | None = None,
) -> dict:
    """执行全量校验，返回报告字典；write=True 时落盘 Markdown/JSON。"""
    specs = build_specs(raw_dir, external_dir)
    frames: dict[str, pd.DataFrame] = {}
    tables: list[dict] = []

    for name, spec in specs.items():
        result = inspect_table(spec)
        tables.append(result)
        path = resolve(spec.path)
        if path is not None:
            try:
                frames[name] = read_table(spec.path)
            except Exception:
                pass

    coverage_issues, coverage = cross_table_checks(frames)
    if coverage_issues:
        by_table = {t["name"]: t for t in tables}
        for item in coverage_issues:
            by_table[item["table"]]["issues"].append(item)
            by_table[item["table"]]["errors"] = sum(
                1 for i in by_table[item["table"]]["issues"] if i["level"] == "error")
            by_table[item["table"]]["warnings"] = sum(
                1 for i in by_table[item["table"]]["issues"] if i["level"] == "warning")

    years = year_coverage(frames)
    missing_years = [y for y in MODELING_YEARS if y not in years]
    if missing_years:
        tables[0]["issues"].append(_issue(
            "error", "financial", "modeling_years",
            f"建模窗口缺少年份：{missing_years}", missing_years))
        tables[0]["errors"] = sum(1 for i in tables[0]["issues"] if i["level"] == "error")

    mapping_report = None
    if source_dir:
        try:
            from etl.mapping import import_table, load_mapping

            mapping = load_mapping()
            mapping_report = [import_table(source_dir, t, write=False, mapping=mapping)
                              for t in mapping["tables"]]
        except Exception as exc:
            logger.warning("字段映射检查失败：%s", exc)
            mapping_report = [{"table": "mapping", "status": "error", "error": str(exc)}]

    errors = sum(t.get("errors", 0) for t in tables)
    warnings = sum(t.get("warnings", 0) for t in tables)
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "raw_dir": _display_path(Path(raw_dir or settings.RAW_DIR)),
        "external_dir": _display_path(Path(external_dir or settings.EXTERNAL_DIR)),
        "summary": {
            "tables": len(tables), "rows": sum(t["rows"] for t in tables),
            "errors": errors, "warnings": warnings,
        },
        "tables": tables,
        "coverage": coverage,
        "year_coverage": years,
        "mapping": mapping_report,
    }

    if write:
        target = Path(out_dir or (settings.REPORT_DIR / "data_quality"))
        target.mkdir(parents=True, exist_ok=True)
        (target / "data_quality_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        (target / "data_quality_report.md").write_text(_markdown(report), encoding="utf-8")
        logger.info("数据质量报告：%s", _display_path(target / "data_quality_report.md"))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="原始数据质量校验")
    parser.add_argument("--raw-dir", type=Path, default=None, help="raw 数据目录")
    parser.add_argument("--external-dir", type=Path, default=None, help="外部数据目录")
    parser.add_argument("--out-dir", type=Path, default=None, help="报告输出目录")
    parser.add_argument("--source", type=Path, default=None, help="CSMAR 导出目录（额外检查字段映射）")
    parser.add_argument("--no-write", action="store_true", help="只打印摘要，不写报告")
    parser.add_argument("--strict", action="store_true", help="警告也视为失败")
    args = parser.parse_args()

    report = validate_dataset(
        raw_dir=args.raw_dir, external_dir=args.external_dir,
        out_dir=args.out_dir, write=not args.no_write, source_dir=args.source,
    )
    summary = report["summary"]
    print(f"表 {summary['tables']} / 行 {summary['rows']} / 错误 {summary['errors']} / 警告 {summary['warnings']}")
    for table in report["tables"]:
        for item in table["issues"]:
            icon = {"error": "ERROR", "warning": "WARN ", "info": "INFO "}[item["level"]]
            print(f"  [{icon}] {table['name']}.{item['check']}: {item['message']}")

    failed = summary["errors"] > 0 or (args.strict and summary["warnings"] > 0)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
