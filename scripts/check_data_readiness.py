"""数据与训练就绪度体检（G0–G5 门禁）。

回答三个问题：
1. 原始契约表是否齐全、主键是否干净、标签是否够用；
2. 特征面板/建模输入是否与 ``config/feature_registry.py`` 同源、是否有全零特征；
3. 现有模型产物是否与当前数据版本一致（不一致即需要重训）。

用法::

    python -m scripts.check_data_readiness                 # 体检 + 写报告
    python -m scripts.check_data_readiness --quiet         # 只输出摘要
    python -m scripts.check_data_readiness --no-write      # 不落盘报告

退出码：存在 BLOCK 级问题时返回 1，便于 CI / Makefile 拦截。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import settings
from config.feature_registry import FEATURE_KEYS, ID_COLUMNS, TARGET_COLUMN, group_of
from etl.io_utils import get_logger, read_table, resolve

logger = get_logger("readiness")

KEY = ["stock_code", "year"]
STATUS_RANK = {"BLOCK": 0, "WARN": 1, "PASS": 2}
STATUS_ICON = {"BLOCK": "❌", "WARN": "⚠️", "PASS": "✅"}

# 契约表：(名称, 路径, 是否必需, 说明)
RAW_SPECS = [
    ("财务主表", settings.RAW_FINANCIAL, True, "FS_Combas/FS_Comins/FS_Comscfd + 折旧/扣非"),
    ("治理表", settings.RAW_GOVERNANCE, True, "十大股东 + 高管 + 两职合一"),
    ("市场/审计", settings.RAW_MARKET, True, "FIN_Audit + TRD_Dly 公司-年"),
    ("MD&A 文本", settings.RAW_TEXT_SENTIMENT, True, "词典基线 lexicon_cn_v1"),
    ("司法/处罚", settings.RAW_LEGAL, True, "LA_DETAIL + STK_Violation_Main"),
    ("ST 标签", settings.RAW_LABELS, True, "SPT_Trdchg 官方区间 → 0/1"),
    ("宏观/行业", settings.RAW_MACRO, True, "国家统计局 + 央行社融"),
    ("数字化转型", settings.RAW_DIGITAL, False, "可选维度，未入选最终模型"),
]


def _is_six_digit(value) -> bool:
    """容忍被 Excel/CSV 去掉前导零的代码（1 → 000001）。"""
    if pd.isna(value):
        return False
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    text = text.split(".")[0].zfill(6)
    return len(text) == 6 and text.isdigit()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Report:
    """收集门禁结论；worst 决定退出码。"""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, gate: str, item: str, status: str, detail: str) -> None:
        self.rows.append({"gate": gate, "item": item, "status": status, "detail": detail})

    def worst(self) -> str:
        if not self.rows:
            return "PASS"
        return min((r["status"] for r in self.rows), key=lambda s: STATUS_RANK[s])

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)[["gate", "item", "status", "detail"]]

    def counts(self) -> dict:
        out = {"PASS": 0, "WARN": 0, "BLOCK": 0}
        for row in self.rows:
            out[row["status"]] += 1
        return out


def check_raw(report: Report) -> dict[str, pd.DataFrame]:
    """G0/G1：文件存在性 + 结构 + 主键。"""
    loaded: dict[str, pd.DataFrame] = {}
    for name, path, required, note in RAW_SPECS:
        target = resolve(path)
        if target is None:
            report.add("G0 原始落地", name, "BLOCK" if required else "WARN",
                       f"缺失 {settings.rel(path)}（{note}）")
            continue
        try:
            df = read_table(target)
        except Exception as exc:  # noqa: BLE001 - 体检脚本需要报告而非中断
            report.add("G0 原始落地", name, "BLOCK", f"读取失败：{exc}")
            continue
        loaded[name] = df
        if df.empty:
            report.add("G0 原始落地", name, "BLOCK", "文件为空")
            continue

        detail = f"{len(df):,} 行 × {df.shape[1]} 列"
        if "year" in df.columns:
            years = pd.to_numeric(df["year"], errors="coerce")
            detail += f"，{int(years.min())}–{int(years.max())}"
        if "stock_code" in df.columns:
            detail += f"，{df['stock_code'].nunique():,} 家公司"

        status = "PASS"
        if all(c in df.columns for c in KEY):
            dup = int(df.duplicated(KEY).sum())
            null = int(df[KEY].isna().any(axis=1).sum())
            bad_code = int((~df["stock_code"].map(_is_six_digit)).sum())
            if dup or null or bad_code:
                status = "WARN"
                detail += f"；重复键 {dup}、空键 {null}、非 6 位代码 {bad_code}"
            else:
                detail += "；主键唯一、代码规范"
        elif "year" in df.columns:
            detail += "；年度维表（无公司主键），按 year 关联"
        else:
            status = "WARN"
            detail += "；缺 stock_code/year 主键"
        report.add("G1 原始结构", name, status, detail)
    return loaded


def check_labels(report: Report, raw: dict[str, pd.DataFrame]) -> None:
    """G2：标签覆盖与 T+2 可用性。"""
    labels = raw.get("ST 标签")
    if labels is None:
        return
    if "is_st" not in labels.columns:
        report.add("G2 标签", "标签列", "BLOCK", "缺少 is_st 列")
        return

    rate = float(pd.to_numeric(labels["is_st"], errors="coerce").mean())
    status = "PASS" if 0.01 <= rate <= 0.10 else "WARN"
    report.add("G2 标签", "正样本率", status,
               f"{rate:.2%}（1%–10% 为合理区间；过低会削弱可学习性）")

    need_years = [y + settings.LABEL_HORIZON for y in settings.PANEL_YEARS]
    have = set(pd.to_numeric(labels["year"], errors="coerce").dropna().astype(int))
    missing = sorted(set(need_years) - have)
    if missing:
        report.add("G2 标签", "T+2 覆盖", "BLOCK",
                   f"缺少标签年 {missing}，对应特征年 {[y - settings.LABEL_HORIZON for y in missing]}")
    else:
        report.add("G2 标签", "T+2 覆盖", "PASS",
                   f"特征年 {settings.PANEL_YEARS[0]}–{settings.PANEL_YEARS[-1]} 全部可对齐")

    lock_labels = pd.to_numeric(labels.loc[labels["year"] == settings.LOCKBOX_YEAR, "is_st"],
                                errors="coerce")
    need_lock = settings.LOCKBOX_YEAR + settings.LABEL_HORIZON
    if lock_labels.notna().any():
        report.add("G2 标签", f"{settings.LOCKBOX_YEAR} 锁箱", "WARN",
                   f"标签年 {settings.LOCKBOX_YEAR} 已有 {int(lock_labels.notna().sum())} 行，"
                   f"但锁箱评估需要特征年 {settings.LOCKBOX_YEAR} + 标签年 {need_lock}")
    else:
        report.add("G2 标签", f"{settings.LOCKBOX_YEAR} 锁箱", "PASS",
                   f"已按锁箱处理；需等 {need_lock} 官方标签完整后再评估")


def check_panel(report: Report) -> pd.DataFrame | None:
    """G3：特征面板完整性与可用性。"""
    target = resolve(settings.FEATURE_PANEL)
    if target is None:
        report.add("G3 特征面板", "文件", "BLOCK", f"缺失 {settings.rel(settings.FEATURE_PANEL)}")
        return None
    panel = read_table(target)

    panel_years = pd.to_numeric(panel["year"], errors="coerce").dropna().astype(int)
    if panel_years.max() >= settings.LOCKBOX_YEAR:
        report.add("G3 特征面板", "锁箱隔离", "BLOCK",
                   f"面板出现 {settings.LOCKBOX_YEAR} 年特征行，破坏锁箱约定")
    else:
        report.add("G3 特征面板", "窗口", "PASS",
                   f"{panel_years.min()}–{panel_years.max()}，{len(panel):,} 行 / "
                   f"{panel['stock_code'].nunique():,} 家；锁箱 {settings.LOCKBOX_YEAR} 未泄露")

    missing_feats = [f for f in FEATURE_KEYS if f not in panel.columns]
    report.add("G3 特征面板", "注册表同源", "BLOCK" if missing_feats else "PASS",
               f"注册表 {len(FEATURE_KEYS)} 维，面板缺失 {missing_feats or '无'}")

    avail = [f for f in FEATURE_KEYS if f in panel.columns]
    all_zero = [f for f in avail if float(panel[f].fillna(0).abs().sum()) == 0]
    report.add("G3 特征面板", "全零特征", "WARN" if all_zero else "PASS",
               f"{len(all_zero)} / {len(avail)} 维全零" + (f"：{all_zero}" if all_zero else ""))

    coverage = panel[avail].notna().mean()
    low = coverage[coverage < 0.60].sort_values()
    report.add("G3 特征面板", "覆盖率", "WARN" if len(low) else "PASS",
               f"最低 {coverage.min():.2%}" + (f"；<60% 共 {len(low)} 维：{list(low.index)}" if len(low) else ""))

    pos_rate = float(pd.to_numeric(panel[TARGET_COLUMN], errors="coerce").mean())
    report.add("G3 特征面板", "正样本率", "PASS" if 0.01 <= pos_rate <= 0.10 else "WARN",
               f"{pos_rate:.2%}（{int(panel[TARGET_COLUMN].sum()):,} 正样本）")

    groups = pd.Series(group_of(avail)).value_counts().to_dict()
    report.add("G3 特征面板", "维度分布", "PASS",
               "，".join(f"{k}={v}" for k, v in groups.items()))
    return panel


def check_selection(report: Report, panel: pd.DataFrame | None) -> list[str]:
    """G4：特征筛选产物与模型输入。"""
    if not settings.FEATURE_LIST.exists():
        report.add("G4 筛选产物", "特征清单", "BLOCK", f"缺失 {settings.rel(settings.FEATURE_LIST)}")
        return []
    payload = json.loads(settings.FEATURE_LIST.read_text(encoding="utf-8"))
    features = payload.get("features", [])
    if len(features) < settings.MIN_FEATURES:
        report.add("G4 筛选产物", "特征数量", "BLOCK",
                   f"{len(features)} 维 < 下限 {settings.MIN_FEATURES}")
    else:
        report.add("G4 筛选产物", "特征数量", "PASS", f"{len(features)} 维入选")

    if panel is not None:
        absent = [f for f in features if f not in panel.columns]
        report.add("G4 筛选产物", "面板可满足", "BLOCK" if absent else "PASS",
                   f"缺失 {absent}" if absent else "入选特征全部存在于面板")

    matrix = resolve(settings.FEATURE_MATRIX)
    if matrix is None:
        report.add("G4 筛选产物", "建模输入", "BLOCK", f"缺失 {settings.rel(settings.FEATURE_MATRIX)}")
        return features
    mi = read_table(matrix)
    absent = [c for c in ID_COLUMNS + [TARGET_COLUMN] + features if c not in mi.columns]
    report.add("G4 筛选产物", "建模输入列", "BLOCK" if absent else "PASS",
               f"缺失 {absent}" if absent else f"{mi.shape[0]:,} 行 × {mi.shape[1]} 列，ID/标签/特征齐全")

    if panel is not None and len(mi) != len(panel):
        report.add("G4 筛选产物", "面板-输入一致", "WARN",
                   f"建模输入 {len(mi):,} 行 ≠ 特征面板 {len(panel):,} 行，建议重跑 etl.run_pipeline")
    else:
        report.add("G4 筛选产物", "面板-输入一致", "PASS", "行数与特征面板一致")

    # 旧格式产物检测：CSV 与 parquet 不同步时最容易误导下游
    pairs = [(settings.FEATURE_MATRIX, len(mi)), (settings.FEATURE_PANEL, len(panel) if panel is not None else None)]
    for table, n_parquet in pairs:
        stale = table.with_suffix(".csv")
        if not stale.exists():
            continue
        try:
            n_stale = sum(1 for _ in stale.open(encoding="utf-8-sig")) - 1
            if n_parquet is not None and n_stale != n_parquet:
                report.add("G4 筛选产物", "旧产物", "WARN",
                           f"{settings.rel(stale)} 有 {n_stale:,} 行，与 parquet {n_parquet:,} 行不一致，建议归档")
            else:
                report.add("G4 筛选产物", "旧产物", "PASS", f"{stale.name} 与 parquet 行数一致")
        except OSError as exc:
            report.add("G4 筛选产物", "旧产物", "WARN", f"无法读取 {stale.name}：{exc}")
    return features


def check_split(report: Report, panel: pd.DataFrame | None) -> None:
    """G5：时间切分与样本量。"""
    if panel is None:
        return
    years = pd.to_numeric(panel["year"], errors="coerce")
    splits = {
        f"训练 {settings.TRAIN_YEAR_RANGE[0]}–{settings.TRAIN_YEAR_RANGE[1]}":
            panel[years.between(*settings.TRAIN_YEAR_RANGE)],
        f"验证 {settings.VALID_YEAR}": panel[years == settings.VALID_YEAR],
        f"测试 {settings.TEST_YEAR}": panel[years == settings.TEST_YEAR],
    }
    for name, part in splits.items():
        if part.empty:
            report.add("G5 切分", name, "BLOCK", "切分后为空，无法训练/评估")
            continue
        pos = int(part[TARGET_COLUMN].sum())
        status = "PASS" if pos >= 30 else "WARN"
        report.add("G5 切分", name, status,
                   f"{len(part):,} 行 / {pos} 正样本（{part[TARGET_COLUMN].mean():.2%}）")


def check_artifacts(report: Report, features: list[str]) -> None:
    """模型产物是否与当前数据版本一致。"""
    required = {
        "模型文件": settings.MODEL_PATH,
        "指标": settings.METRICS_PATH,
        "元信息": settings.MODEL_META,
        "运行清单": settings.ARTIFACT_DIR / "run_manifest.json",
    }
    missing = {k: v for k, v in required.items() if not Path(v).exists()}
    report.add("产物", "文件齐全", "WARN" if missing else "PASS",
               f"缺失 {list(missing)}" if missing else "模型/指标/元信息/清单齐全")
    if missing.get("模型文件") or missing.get("元信息"):
        return

    meta = json.loads(Path(settings.MODEL_META).read_text(encoding="utf-8"))
    n_meta = int(meta.get("n_features", 0))
    same = sorted(meta.get("features", [])) == sorted(features)
    report.add("产物", "特征版本", "WARN" if not same else "PASS",
               f"模型 {n_meta} 维 vs 当前 {len(features)} 维"
               + ("" if same else "：特征集已变化，需要重训"))

    manifest_path = Path(settings.ARTIFACT_DIR) / "run_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        recorded = manifest.get("dataset", {}).get("sha256")
        matrix = resolve(settings.FEATURE_MATRIX)
        if recorded and matrix:
            current = _sha256(matrix)
            if current != recorded:
                report.add("产物", "数据版本", "WARN",
                           f"建模输入已变更（{recorded[:8]} → {current[:8]}），"
                           "训练指标只对应旧版本，需要重训")
            else:
                report.add("产物", "数据版本", "PASS", f"建模输入 SHA256 与训练记录一致（{recorded[:8]}）")


def render_markdown(report: Report, meta: dict) -> str:
    counts = report.counts()
    df = report.to_frame()
    lines = [
        "# 数据与训练就绪度报告",
        "",
        f"- 生成时间：{meta['generated_at']}",
        f"- 结论：**{meta['verdict']}**（PASS {counts['PASS']} / WARN {counts['WARN']} / BLOCK {counts['BLOCK']}）",
        f"- 项目根：`{meta['root']}`",
        "",
        "| 门禁 | 检查项 | 状态 | 详情 |",
        "|---|---|---|---|",
    ]
    for _, row in df.iterrows():
        lines.append(f"| {row['gate']} | {row['item']} | {STATUS_ICON[row['status']]} {row['status']} | {row['detail']} |")
    lines += [
        "",
        "## 门禁含义",
        "",
        "- **G0 原始落地**：契约表是否存在；缺失必需表即 BLOCK。",
        "- **G1 原始结构**：主键唯一性、代码格式、年份范围。",
        "- **G2 标签**：正样本率、T+2 覆盖、锁箱隔离。",
        "- **G3 特征面板**：注册表同源、全零特征、覆盖率、正样本率。",
        "- **G4 筛选产物**：入选特征数量下限、面板可满足性、建模输入列完整性。",
        "- **G5 切分**：训练/验证/测试是否非空、正样本是否够评估。",
        "",
        "> 本报告只看“能不能训练/评估”，不替代 `models.evaluate` 的模型指标。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="数据与训练就绪度体检")
    parser.add_argument("--out-dir", type=Path, default=settings.REPORT_DIR / "data_quality")
    parser.add_argument("--no-write", action="store_true", help="不写报告文件")
    parser.add_argument("--quiet", action="store_true", help="只输出结论摘要")
    args = parser.parse_args()

    report = Report()
    raw = check_raw(report)
    check_labels(report, raw)
    panel = check_panel(report)
    features = check_selection(report, panel)
    check_split(report, panel)
    check_artifacts(report, features or [])

    verdict = report.worst()
    stamp = datetime.now()
    meta = {
        "generated_at": stamp.strftime("%Y-%m-%d %H:%M:%S"),
        "verdict": verdict,
        "root": str(settings.PROJECT_ROOT),
        "counts": report.counts(),
        "features": len(features),
    }

    df = report.to_frame()
    if args.quiet:
        print(df.to_string(index=False))
    else:
        print(render_markdown(report, meta))

    if not args.no_write:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"readiness_{stamp:%Y%m%d_%H%M%S}"
        (args.out_dir / f"{stem}.md").write_text(render_markdown(report, meta), encoding="utf-8")
        payload = {**meta, "checks": report.rows}
        (args.out_dir / f"{stem}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("报告已写出：%s", settings.rel(args.out_dir / f"{stem}.md"))

    if verdict == "BLOCK":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
