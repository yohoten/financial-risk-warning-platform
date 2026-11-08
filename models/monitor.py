"""模型监控：PSI 特征漂移 + 性能衰减检测 + 重训练触发建议。

监控口径与训练期特征筛选完全一致（复用 etl.stats_utils），
避免"筛选时稳定、上线后误报"的口径错配。

用法
----
    python -m models.monitor                 # 基准=训练集，对比=测试集
    python -m models.monitor --reference 2022 --current 2024
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd

from config import settings
from etl.io_utils import get_logger, read_table, resolve
from etl.stats_utils import psi_table
from models.data import load_dataset
from models.metrics import evaluate_model
from models.predict import load_model

logger = get_logger("monitor")


def feature_drift(reference_year: int, current_year: int) -> pd.DataFrame:
    """按时点对比特征分布漂移。"""
    panel = read_table(settings.FEATURE_MATRIX) if resolve(settings.FEATURE_MATRIX) else read_table(settings.FEATURE_PANEL)
    ds = load_dataset()
    ref = panel[panel["year"] <= reference_year]
    cur = panel[panel["year"] == current_year]
    if ref.empty or cur.empty:
        raise ValueError(f"缺少 {reference_year} 或 {current_year} 年的数据")
    table = psi_table(ref[ds.features], cur[ds.features])
    table["feature_cn"] = table["feature"].map(lambda f: f)
    return table


def performance_drift() -> dict:
    """在标注可得的最近年份上重算指标，与训练期指标比较。"""
    ds = load_dataset()
    model = load_model()
    result = {"reference": {}, "current": {}}

    for label, X, y in (("valid", ds.X_valid, ds.y_valid), ("test", ds.X_test, ds.y_test)):
        if len(X) == 0:
            continue
        prob = model.predict_proba(X)[:, 1]
        m = evaluate_model(y, prob, name=label)
        result["reference" if label == "valid" else "current"] = m

    ref_auc = result["reference"].get("auc")
    cur_auc = result["current"].get("auc")
    result["delta_auc"] = round((cur_auc - ref_auc), 4) if ref_auc and cur_auc else None
    return result


def build_report(reference_year: int = 2022, current_year: int = settings.TEST_YEAR) -> dict:
    """生成监控报告：漂移明细 + 性能变化 + 处置建议。"""
    drift = feature_drift(reference_year, current_year)
    perf = performance_drift()

    drifting = drift[drift["psi"] > settings.PSI_BLOCK]
    warning = drift[(drift["psi"] > settings.PSI_WARN) & (drift["psi"] <= settings.PSI_BLOCK)]

    actions: list[str] = []
    if len(drifting) > 0:
        actions.append(f"{len(drifting)} 个特征显著漂移（PSI>{settings.PSI_BLOCK}），建议触发重训练")
    if len(warning) > 0:
        actions.append(f"{len(warning)} 个特征轻度漂移，建议纳入下月重点监控")
    if perf.get("delta_auc") is not None and perf["delta_auc"] < -0.03:
        actions.append(f"AUC 下降 {-perf['delta_auc']:.3f} 超过 0.03 阈值，需人工复核并考虑重训练")
    if not actions:
        actions.append("模型与特征分布稳定，维持常规月度监控")

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reference_year": reference_year,
        "current_year": current_year,
        "n_features": int(len(drift)),
        "n_drifting": int(len(drifting)),
        "n_warning": int(len(warning)),
        "top_drift": drift.head(10).to_dict("records"),
        "performance": perf,
        "actions": actions,
    }
    settings.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    settings.MONITOR_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    drift.to_csv(settings.ARTIFACT_DIR / "psi_detail.csv", index=False, encoding="utf-8-sig")
    logger.info("监控报告已生成：%s", settings.rel(settings.MONITOR_REPORT))
    for a in actions:
        logger.info("  → %s", a)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="模型漂移监控")
    parser.add_argument("--reference", type=int, default=2022, help="基准年份")
    parser.add_argument("--current", type=int, default=settings.TEST_YEAR, help="对比年份")
    args = parser.parse_args()
    build_report(args.reference, args.current)


if __name__ == "__main__":
    main()
