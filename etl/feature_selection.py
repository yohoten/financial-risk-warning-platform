"""四步特征筛选：IV 值 → 相关性/VIF 去冗余 → PSI 稳定性 → Boruta 重要性。

设计要点
--------
1. 全部统计量只在**训练集**（2015-2022）上估计，验证/测试集只做变换；
2. 每一步的结果写入报告 CSV，形成可复现的筛选证据链（答辩可直接展示）；
3. Boruta 为可选依赖，缺失时自动降级为"随机森林置换重要性"，保证链路不断。
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from config import settings
from config.feature_registry import FEATURE_KEYS, TARGET_COLUMN
from etl.io_utils import get_logger, read_table, write_table
from etl.stats_utils import calculate_iv, calculate_vif, drop_high_corr, psi_table

logger = get_logger("feature-selection")


def _train_valid_split(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """按时间切分：训练窗口内再前后对半，用于 PSI 稳定性检验。"""
    train = panel[panel["year"].between(*settings.TRAIN_YEAR_RANGE)]
    years = sorted(train["year"].unique())
    mid = years[len(years) // 2]
    return train[train["year"] < mid], train[train["year"] >= mid]


def step1_iv(panel: pd.DataFrame, features: list[str]) -> tuple[list[str], pd.DataFrame]:
    train = panel[panel["year"].between(*settings.TRAIN_YEAR_RANGE)]
    iv_table = calculate_iv(train[features], train[TARGET_COLUMN])
    kept = iv_table.loc[iv_table["iv"] >= settings.IV_MIN, "feature"].tolist()
    logger.info("Step1 IV 筛选：%d → %d 维（阈值 IV≥%.2f）", len(features), len(kept), settings.IV_MIN)
    return kept, iv_table


def step2_collinearity(
    panel: pd.DataFrame, features: list[str], iv_table: pd.DataFrame
) -> tuple[list[str], pd.DataFrame]:
    train = panel[panel["year"].between(*settings.TRAIN_YEAR_RANGE)]
    iv_scores = iv_table.set_index("feature")["iv"]
    drop_corr = drop_high_corr(train[features], iv_scores, settings.CORR_MAX)

    remaining = [f for f in features if f not in drop_corr]
    drop_vif: list[str] = []
    working = remaining.copy()
    while True:
        vif = calculate_vif(train[working])
        if len(working) <= settings.MIN_FEATURES or vif.max() <= settings.VIF_MAX:
            break
        worst = vif.idxmax()
        drop_vif.append(worst)
        working.remove(worst)

    full_vif = calculate_vif(train[features])
    report = pd.DataFrame({"feature": features})
    report["iv"] = report["feature"].map(iv_table.set_index("feature")["iv"]).fillna(0.0)
    report["dropped_by_corr"] = report["feature"].isin(drop_corr)
    report["dropped_by_vif"] = report["feature"].isin(drop_vif)
    report["vif"] = report["feature"].map(full_vif).round(2)
    logger.info(
        "Step2 共线性：剔除高相关 %d 维、高 VIF %d 维，保留 %d 维",
        len(drop_corr), len(drop_vif), len(working),
    )
    return working, report


def step3_psi(panel: pd.DataFrame, features: list[str]) -> tuple[list[str], pd.DataFrame]:
    dev, val = _train_valid_split(panel)
    table = psi_table(dev[features], val[features])
    good = table.loc[table["psi"] <= settings.PSI_BLOCK, "feature"].tolist()
    table["dropped"] = ~table["feature"].isin(good)
    logger.info("Step3 PSI 稳定性：保留 %d 维（PSI>%.2f 剔除 %d 维）",
                len(good), settings.PSI_BLOCK, len(features) - len(good))
    return good, table


def step4_boruta(panel: pd.DataFrame, features: list[str]) -> tuple[list[str], pd.DataFrame]:
    """Boruta 重要性确认；无 boruta 依赖时降级为 RF 置换重要性。"""
    train = panel[panel["year"].between(*settings.TRAIN_YEAR_RANGE)]
    X, y = train[features].to_numpy(dtype=float), train[TARGET_COLUMN].to_numpy()

    try:
        from boruta import BorutaPy
        from sklearn.ensemble import RandomForestClassifier

        rf = RandomForestClassifier(n_estimators=200, max_depth=8, n_jobs=-1, random_state=settings.RANDOM_SEED)
        boruta = BorutaPy(rf, n_estimators="auto", verbose=0, max_iter=60, random_state=settings.RANDOM_SEED)
        boruta.fit(X, y)
        support = boruta.support_ | boruta.support_weak_
        scores = boruta.ranking_
        method = "Boruta"
    except Exception as exc:  # ImportError 或其他运行时问题
        from sklearn.ensemble import RandomForestClassifier

        rf = RandomForestClassifier(n_estimators=300, max_depth=8, n_jobs=-1, random_state=settings.RANDOM_SEED)
        rf.fit(X, y)
        scores = rf.feature_importances_
        threshold = np.quantile(scores, 0.35)
        support = scores >= threshold
        method = f"RF-importance 降级（{type(exc).__name__}）"

    table = pd.DataFrame({"feature": features, "importance_rank": scores, "selected": support})
    kept = table.loc[table["selected"], "feature"].tolist()
    logger.info("Step4 %s：保留 %d 维", method, len(kept))
    table.attrs["method"] = method
    return kept, table


def select_features(panel: pd.DataFrame, write: bool = True) -> list[str]:
    """执行四步筛选并落盘特征清单与筛选报告。"""
    available = [f for f in FEATURE_KEYS if f in panel.columns]
    f1, iv_table = step1_iv(panel, available)
    f2, corr_report = step2_collinearity(panel, f1, iv_table)
    f3, psi_report = step3_psi(panel, f2)
    f4, boruta_report = step4_boruta(panel, f3)

    if len(f4) < settings.MIN_FEATURES:  # 保险丝：避免过度筛选导致特征过少
        f4 = f3
        logger.warning("Boruta 保留特征少于 %d 维，回退到 PSI 步骤结果", settings.MIN_FEATURES)

    # 合并报告
    report = (
        corr_report.rename(columns={"dropped_by_corr": "drop_corr"})
        .merge(psi_report[["feature", "psi", "dropped"]].rename(columns={"dropped": "drop_psi"}), on="feature", how="left")
        .merge(boruta_report.rename(columns={"selected": "keep_boruta"}), on="feature", how="left")
    )
    report["final_keep"] = report["feature"].isin(f4)
    chain = [available, f1, f2, f3, f4]
    logger.info("筛选链路维度：%s", " → ".join(str(len(x)) for x in chain))

    if write:
        write_table(report, settings.FEATURE_REPORT)
        settings.FEATURE_LIST.parent.mkdir(parents=True, exist_ok=True)
        settings.FEATURE_LIST.write_text(
            json.dumps(
                {
                    "features": f4,
                    "n_features": len(f4),
                    "selection_chain": {"raw": len(available), "iv": len(f1), "collinearity": len(f2), "psi": len(f3), "boruta": len(f4)},
                    "boruta_method": boruta_report.attrs.get("method", "Boruta"),
                    "train_years": list(settings.TRAIN_YEAR_RANGE),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info("特征清单已保存：%s", settings.rel(settings.FEATURE_LIST))
    return f4


def main() -> None:
    panel = read_table(settings.FEATURE_PANEL)
    select_features(panel)


if __name__ == "__main__":
    main()
