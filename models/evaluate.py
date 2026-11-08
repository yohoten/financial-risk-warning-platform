"""模型评估报告生成：指标表、阈值敏感性、分群一致性、校准曲线。

输出 `models/artifacts/evaluation_report.md`，可直接作为论文"模型评估"章节素材。
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from config import settings
from etl.io_utils import get_logger, write_table
from models.data import load_dataset
from models.metrics import calibration_dataframe, evaluate_model, group_metrics
from models.predict import load_model


logger = get_logger("evaluate")


def threshold_sensitivity(y_true, y_prob, thresholds=(0.2, 0.3, 0.4, 0.5, 0.6)) -> pd.DataFrame:
    """阈值敏感性：业务上不同误报/漏报成本偏好对应不同阈值。"""
    rows = []
    for t in thresholds:
        m = evaluate_model(y_true, y_prob, threshold=t, name=f"thr={t}")
        rows.append({"threshold": t, "precision": m["precision"], "recall": m["recall"],
                     "f1": m["f1"], "fp": m["fp"], "fn": m["fn"]})
    return pd.DataFrame(rows)


def _md_table(df: pd.DataFrame, float_fmt: str = "{:.4f}") -> str:
    """DataFrame → Markdown 表格（不依赖 tabulate）。"""
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, row in df.iterrows():
        cells = [float_fmt.format(v) if isinstance(v, (float, np.floating)) else str(v) for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build_report() -> str:
    """生成完整评估报告并落盘。"""
    settings.ensure_dirs()
    ds = load_dataset()
    model = load_model()

    prob_valid = model.predict_proba(ds.X_valid)[:, 1]
    valid_metrics = evaluate_model(ds.y_valid, prob_valid, name="XGBoost_2023")
    test_metrics = None
    if not ds.test.empty:
        prob_test = model.predict_proba(ds.X_test)[:, 1]
        test_metrics = evaluate_model(ds.y_test, prob_test, name="XGBoost_2024")

    sens = threshold_sensitivity(ds.y_valid.to_numpy(), prob_valid)
    by_industry = group_metrics(ds.valid, prob_valid, "industry")
    calib = calibration_dataframe(ds.y_valid, prob_valid)

    write_table(sens, settings.ARTIFACT_DIR / "threshold_sensitivity.csv")
    write_table(by_industry, settings.ARTIFACT_DIR / "metrics_by_industry.csv")
    write_table(calib, settings.ARTIFACT_DIR / "calibration_curve.csv")

    lines = [
        "# 模型评估报告",
        "",
        f"- 数据集：训练 {len(ds.train)} / 验证 {len(ds.valid)} / 测试 {len(ds.test)}",
        f"- 特征数：{len(ds.features)} 维",
        f"- 标签口径：T 年 ST 状态，特征取自 T-{settings.LABEL_HORIZON} 年（无前视偏差）",
        "",
        "## 1. 核心指标（验证集 2023）",
        "",
        _md_table(pd.DataFrame([valid_metrics])),
        "",
    ]
    if test_metrics:
        lines += ["## 2. 最终测试集表现（2024，不参与任何调优）", "", _md_table(pd.DataFrame([test_metrics])), ""]

    lines += [
        "## 3. 阈值敏感性",
        "",
        _md_table(sens),
        "",
        "## 4. 分群一致性（验证集按行业）",
        "",
        _md_table(by_industry),
        "",
        "## 5. 结论",
        "",
        f"- 验证集 AUC {valid_metrics['auc']:.4f}、KS {valid_metrics['ks']:.4f}、Brier {valid_metrics['brier']:.4f}，"
        f"{'达到' if valid_metrics['auc'] >= 0.85 else '未达到'}合格线（AUC≥0.85，KS≥0.40，Brier≤0.15）。",
        f"- 默认阈值 {valid_metrics['threshold']:.3f} 下召回率 {valid_metrics['recall']:.2%}、精确率 {valid_metrics['precision']:.2%}，"
        "可通过业务阈值滑块在漏报与误报之间取舍。",
        "- 分群看板用于检查行业间的性能漂移，若某行业 AUC 显著低于整体，需在论文局限性章节说明。",
    ]
    report = "\n".join(lines)
    settings.EVAL_REPORT.write_text(report, encoding="utf-8")
    logger.info("评估报告已生成：%s", settings.rel(settings.EVAL_REPORT))

    metrics_json = {"valid_2023": valid_metrics, "test_2024": test_metrics}
    (settings.ARTIFACT_DIR / "evaluation_metrics.json").write_text(
        json.dumps(metrics_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    print(build_report())
