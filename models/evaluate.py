"""模型评估报告生成：PR-AUC / Recall@Top-k / ECE / 阈值与成本敏感性。

输出 `models/artifacts/evaluation_report.md`，可直接作为论文"模型评估"章节素材。
所有概率均为校准后概率；阈值与校准器均在验证集冻结，测试集只应用。
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from config import settings
from etl.io_utils import get_logger, write_table
from models.calibration import cross_fitted_probabilities, load_calibrator
from models.data import load_dataset
from models.metrics import (
    calibration_dataframe,
    cost_optimal_threshold,
    evaluate_model,
    group_metrics,
    load_thresholds,
)
from models.predict import load_model

logger = get_logger("evaluate")

CORE_COLS = [
    "model", "n_samples", "positive_rate", "auc", "pr_auc", "ks",
    "precision", "recall", "f1", "brier", "ece", "threshold",
    "tp", "fp", "tn", "fn", "cost",
]


def threshold_sensitivity(
    y_true, y_prob, thresholds=(0.2, 0.3, 0.4, 0.5, 0.6),
    cost_fn: float | None = None, cost_fp: float | None = None,
) -> pd.DataFrame:
    """阈值敏感性：不同误报/漏报成本偏好对应不同阈值。"""
    rows = []
    for t in thresholds:
        m = evaluate_model(y_true, y_prob, threshold=t, name=f"thr={t}", cost_fn=cost_fn, cost_fp=cost_fp)
        rows.append({
            "threshold": t, "precision": m["precision"], "recall": m["recall"],
            "f1": m["f1"], "fp": m["fp"], "fn": m["fn"], "cost": m["cost"],
        })
    return pd.DataFrame(rows)


def cost_ratio_sensitivity(y_true, y_prob, ratios=(5, 10, 20)) -> pd.DataFrame:
    """成本比敏感性：漏报:误报 = 5:1 / 10:1 / 20:1 的最优阈值与表现。"""
    rows = []
    for ratio in ratios:
        thr = cost_optimal_threshold(y_true, y_prob, cost_fn=float(ratio), cost_fp=1.0)
        m = evaluate_model(y_true, y_prob, threshold=thr, name=f"cost={ratio}:1",
                           cost_fn=float(ratio), cost_fp=1.0)
        rows.append({
            "cost_fn_fp": f"{ratio}:1", "threshold": round(thr, 4),
            "precision": m["precision"], "recall": m["recall"], "f1": m["f1"],
            "fp": m["fp"], "fn": m["fn"], "cost": m["cost"],
        })
    return pd.DataFrame(rows)


def _md_table(df: pd.DataFrame, float_fmt: str = "{:.4f}") -> str:
    """DataFrame → Markdown 表格（不依赖 tabulate）。"""
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, row in df.iterrows():
        cells = [float_fmt.format(v) if isinstance(v, (float, np.floating)) else str(v) for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _core_table(metrics: dict) -> pd.DataFrame:
    row = {k: metrics.get(k) for k in CORE_COLS}
    return pd.DataFrame([row])


def _topk_table(valid: dict, test: dict | None) -> pd.DataFrame:
    rows = []
    for split, metrics in (("valid", valid), ("test", test)):
        if not metrics:
            continue
        for key, item in (metrics.get("top_k") or {}).items():
            rows.append({
                "split": split, "bucket": key, "fraction": item["fraction"],
                "n_reviewed": item["n_reviewed"], "tp": item["tp"],
                "precision": item["precision"], "recall": item["recall"],
                "lift": item["lift"], "score_threshold": item["score_threshold"],
            })
    return pd.DataFrame(rows)


def build_report() -> str:
    """生成完整评估报告并落盘。"""
    settings.ensure_dirs()
    ds = load_dataset()
    model = load_model()
    calibrator = load_calibrator()

    # 阈值唯一来源：训练时在验证集冻结的 model_meta.json，测试集不得重选
    thresholds = load_thresholds()
    threshold = float(thresholds["value"])

    prob_valid_raw = model.predict_proba(ds.X_valid)[:, 1]
    prob_valid = cross_fitted_probabilities(
        ds.y_valid, prob_valid_raw, method=settings.CALIBRATION_METHOD
    )
    valid_metrics = evaluate_model(
        ds.y_valid, prob_valid, threshold=threshold,
        name=f"XGBoost_{settings.VALID_YEAR}",
    )
    valid_metrics["calibration"] = {
        **calibrator.describe(), "scope": "cross_fitted_valid_5fold"
    }

    test_metrics = None
    if not ds.test.empty:
        prob_test = calibrator.apply(model.predict_proba(ds.X_test)[:, 1])
        test_metrics = evaluate_model(
            ds.y_test, prob_test, threshold=threshold,
            name=f"XGBoost_{settings.TEST_YEAR}",
        )
    else:
        prob_test = None

    sens_thresholds = tuple(sorted({0.1, 0.2, 0.3, 0.4, 0.5, round(threshold, 4)}))
    sens = threshold_sensitivity(ds.y_valid.to_numpy(), prob_valid, thresholds=sens_thresholds)
    cost_sens = cost_ratio_sensitivity(ds.y_valid.to_numpy(), prob_valid)
    by_industry = group_metrics(ds.valid, prob_valid, "industry", threshold=threshold)
    calib = calibration_dataframe(ds.y_valid, prob_valid)
    topk = _topk_table(valid_metrics, test_metrics)

    write_table(sens, settings.ARTIFACT_DIR / "threshold_sensitivity.csv")
    write_table(cost_sens, settings.ARTIFACT_DIR / "cost_threshold_sensitivity.csv")
    write_table(by_industry, settings.ARTIFACT_DIR / "metrics_by_industry.csv")
    write_table(calib, settings.ARTIFACT_DIR / "calibration_curve.csv")
    write_table(topk, settings.ARTIFACT_DIR / "topk_metrics.csv")
    if prob_test is not None:
        write_table(calibration_dataframe(ds.y_test, prob_test), settings.ARTIFACT_DIR / "calibration_curve_test.csv")

    lines = [
        "# 模型评估报告",
        "",
        f"- 数据集：训练 {len(ds.train)} / 验证 {len(ds.valid)} / 测试 {len(ds.test)}"
        f"（锁箱 {settings.LOCKBOX_YEAR}，待 2026 官方标签后评估）",
        f"- 特征数：{len(ds.features)} 维",
        f"- 标签口径：T 年 ST 状态，特征取自 T-{settings.LABEL_HORIZON} 年（无前视偏差）",
        f"- 概率校准：{calibrator.method}，部署校准器在 valid_{settings.VALID_YEAR} 拟合；"
        f"验证集报告用 5 折交叉拟合，测试集只应用",
        f"- 决策阈值：{threshold:.4f}（{thresholds['method']}，成本 FN:FP="
        f"{settings.COST_FN:g}:{settings.COST_FP:g}；在 {thresholds['selected_on']} 冻结；"
        f"风险分级：高≥{thresholds['high']:.4f}、中≥{thresholds['medium']:.4f}）",
        f"- 主指标：PR-AUC、Recall@Top{int(settings.TOP_K_PRIMARY * 100)}%、ECE；AUC/KS 仅作辅助",
        "",
        f"## 1. 核心指标（验证集 {settings.VALID_YEAR}，校准后）",
        "",
        _md_table(_core_table(valid_metrics)),
        "",
    ]
    if test_metrics:
        lines += [
            f"## 2. 最终测试集表现（{settings.TEST_YEAR}，不参与任何调优/校准/阈值选择）",
            "",
            _md_table(_core_table(test_metrics)),
            "",
        ]

    lines += [
        "## 3. Top-k 复核容量",
        "",
        _md_table(topk),
        "",
        "## 4. 阈值敏感性（验证集）",
        "",
        _md_table(sens),
        "",
        "## 5. 成本比敏感性（验证集，FN:FP）",
        "",
        _md_table(cost_sens),
        "",
        "## 6. 分群一致性（验证集按行业）",
        "",
        _md_table(by_industry),
        "",
        "## 7. 结论",
        "",
        f"- 验证集 PR-AUC {valid_metrics['pr_auc']:.4f}、Recall@Top10 "
        f"{valid_metrics['top_k']['top_10pct']['recall']:.2%}、ECE {valid_metrics['ece']:.4f}；"
        f"校准前 ECE 见 `metrics.json` 的 raw_valid 字段。",
        f"- 冻结阈值 {threshold:.4f} 下召回率 {valid_metrics['recall']:.2%}、精确率 "
        f"{valid_metrics['precision']:.2%}；成本 FN:FP={settings.COST_FN:g}:{settings.COST_FP:g} 时"
        f"验证集期望成本 {valid_metrics['cost']:.2f}。",
        "- 精确率受 3%—4% 基础率限制，不能把 AUC 当作准确率；业务使用应优先看 "
        "Recall@Top-k、校准曲线与复核容量。",
    ]
    if test_metrics:
        lines.append(
            f"- 测试集（{settings.TEST_YEAR}）PR-AUC {test_metrics['pr_auc']:.4f}、"
            f"Recall@Top10 {test_metrics['top_k']['top_10pct']['recall']:.2%}、"
            f"ECE {test_metrics['ece']:.4f}；该结果只评估一次。"
        )
    report = "\n".join(lines)
    settings.EVAL_REPORT.write_text(report, encoding="utf-8")
    logger.info("评估报告已生成：%s", settings.rel(settings.EVAL_REPORT))

    metrics_json = {
        f"valid_{settings.VALID_YEAR}": valid_metrics,
        f"test_{settings.TEST_YEAR}": test_metrics,
        "calibration": {**calibrator.describe(), "scope": "cross_fitted_valid_5fold"},
        "threshold_policy": {
            "method": thresholds["method"], "value": threshold,
            "cost_fn": settings.COST_FN, "cost_fp": settings.COST_FP,
            "top_k_fraction": settings.TOP_K_PRIMARY,
            "lockbox_year": settings.LOCKBOX_YEAR,
        },
    }
    (settings.ARTIFACT_DIR / "evaluation_metrics.json").write_text(
        json.dumps(metrics_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    print(build_report())
