# -*- coding: utf-8 -*-
"""消融研究：财务-only → +治理 → +审计 → 全量，逐步累加特征维度。

复现中期报告 §0.4 的「财务-only vs +治理 vs +审计」消融表。
训练 2015—2021，一次性在测试集 2023 上评估（不调参、不重选阈值），
报告 AUC / PR-AUC / KS / Recall@Top10，形成可辩护的增量证据。

用法：
    python -m scripts.ablation_study
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from config import settings
from config.feature_registry import group_of
from etl.io_utils import get_logger, write_table
from models.metrics import ks_statistic

logger = get_logger("ablation")

FINANCIAL_GROUPS = {"solvency", "profitability", "operation", "growth", "cashflow"}


def _xgb(scale_pos_weight: float) -> XGBClassifier:
    return XGBClassifier(
        n_estimators=400, max_depth=4, learning_rate=0.05, subsample=0.85,
        colsample_bytree=0.8, min_child_weight=3, reg_lambda=1.0, reg_alpha=0.1,
        scale_pos_weight=scale_pos_weight, objective="binary:logistic",
        eval_metric="auc", tree_method="hist", n_jobs=-1,
        random_state=settings.RANDOM_SEED,
    )


def _recall_topk(y_true: np.ndarray, prob: np.ndarray, k_frac: float = 0.10) -> float:
    k = int(np.ceil(k_frac * len(y_true)))
    top = y_true[np.argsort(-prob)[:k]]
    return float(top.sum() / max(y_true.sum(), 1))


def main() -> None:
    panel = pd.read_parquet(settings.FEATURE_PANEL)
    selected = json.loads(settings.FEATURE_LIST.read_text(encoding="utf-8"))["features"]
    selected = [f for f in selected if f in panel.columns]

    groups = group_of(selected)
    financial = [f for f in selected if groups[f] in FINANCIAL_GROUPS]
    governance = [f for f in selected if groups[f] == "governance"]
    audit = [f for f in selected if groups[f] == "audit_market_legal"]
    macro = [f for f in selected if groups[f] == "macro_industry"]

    variants = [
        ("财务-only", financial),
        ("+治理", financial + governance),
        ("+审计", financial + governance + audit),
        ("+宏观/行业", financial + governance + audit + macro),
        ("全量", selected),
    ]

    tr = panel[panel["year"].between(*settings.TRAIN_YEAR_RANGE)]
    te = panel[panel["year"] == settings.TEST_YEAR]
    spw = float((tr["is_st"] == 0).sum() / max((tr["is_st"] == 1).sum(), 1))

    rows = []
    for name, feats in variants:
        m = _xgb(spw).fit(tr[feats], tr["is_st"])
        prob = m.predict_proba(te[feats])[:, 1]
        y = te["is_st"].to_numpy()
        from sklearn.metrics import average_precision_score, roc_auc_score
        rows.append({
            "变体": name, "特征数": len(feats),
            "AUC": round(roc_auc_score(y, prob), 4),
            "PR-AUC": round(average_precision_score(y, prob), 4),
            "KS": round(ks_statistic(y, prob), 4),
            "Recall@Top10": round(_recall_topk(y, prob), 4),
        })
        logger.info("%-12s n=%d AUC=%.4f PR=%.4f KS=%.4f R@10=%.4f",
                    name, len(feats), rows[-1]["AUC"], rows[-1]["PR-AUC"],
                    rows[-1]["KS"], rows[-1]["Recall@Top10"])

    df = pd.DataFrame(rows)
    write_table(df, settings.ARTIFACT_DIR / "ablation.csv")

    cols = list(df.columns)
    md_lines = [
        "# 特征消融研究（训练 2015—2021 → 测试 2023）",
        "",
        f"- 主模型：XGBoost（{len(selected)} 维，含 audit_opinion）",
        f"- 标签：T 年 ST 状态，特征取 T-{settings.LABEL_HORIZON} 年",
        "- 指标为测试集 2023 一次性评估（不调参、不重选阈值）；概率为校准前原始输出",
        "",
        "| " + " | ".join(cols) + " |",
        "|" + "|".join(["---"] * len(cols)) + "|",
    ]
    for _, row in df.iterrows():
        cells = [f"{v:.4f}" if isinstance(v, (float, np.floating)) else str(v) for v in row]
        md_lines.append("| " + " | ".join(cells) + " |")
    md_lines.append("")
    md_lines.append("> 读法：从「财务-only」到「全量」，PR-AUC 与 Recall@Top10 的变化即各维度的边际增量。")
    (settings.ARTIFACT_DIR / "ablation_report.md").write_text("\n".join(md_lines), encoding="utf-8")
    logger.info("消融表已写出：%s / %s",
                settings.rel(settings.ARTIFACT_DIR / "ablation.csv"),
                settings.rel(settings.ARTIFACT_DIR / "ablation_report.md"))


if __name__ == "__main__":
    main()
