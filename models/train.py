"""五模型对比训练与 Optuna 贝叶斯调优。

流程
----
1. 时间序列 5 折交叉验证（TimeSeriesSplit），给出稳定性区间；
2. XGBoost 使用 Optuna TPE 搜索 + MedianPruner 剪枝（--trials 控制预算）；
3. 其余四个模型作为基线/对照，固定合理默认参数；
4. 全部模型在 2023 验证集上比较，XGBoost 作为主模型落盘。

用法
----
    python -m models.train                # 默认 30 次试验
    python -m models.train --trials 100   # 完整调优
    python -m models.train --no-optuna    # 跳过调优，快速验证链路
"""

from __future__ import annotations

import argparse
import json
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from config import settings
from etl.io_utils import get_logger
from models.data import Dataset, load_dataset
from models.metrics import evaluate_model

logger = get_logger("train")


# ---------------------------------------------------------------------------
# 模型工厂
# ---------------------------------------------------------------------------
def build_baselines(scale_pos_weight: float) -> dict:
    """构造基线模型集合（含缺失依赖的自动降级）。"""
    models: dict[str, object] = {
        "LogisticRegression": Pipeline(
            [
                ("scaler", StandardScaler()),
                ("clf", LogisticRegression(max_iter=2000, class_weight="balanced", random_state=settings.RANDOM_SEED)),
            ]
        ),
        "RandomForest": RandomForestClassifier(
            n_estimators=400, max_depth=10, min_samples_leaf=5,
            class_weight="balanced_subsample", n_jobs=-1, random_state=settings.RANDOM_SEED,
        ),
    }

    from xgboost import XGBClassifier

    models["XGBoost"] = XGBClassifier(
        n_estimators=400, max_depth=4, learning_rate=0.05, subsample=0.85,
        colsample_bytree=0.8, min_child_weight=3, reg_lambda=1.0, reg_alpha=0.1,
        scale_pos_weight=scale_pos_weight, objective="binary:logistic",
        eval_metric="auc", tree_method="hist", n_jobs=-1, random_state=settings.RANDOM_SEED,
    )

    try:
        from lightgbm import LGBMClassifier

        models["LightGBM"] = LGBMClassifier(
            n_estimators=400, max_depth=6, learning_rate=0.05, num_leaves=31,
            subsample=0.85, colsample_bytree=0.8, scale_pos_weight=scale_pos_weight,
            n_jobs=-1, random_state=settings.RANDOM_SEED, verbose=-1,
        )
    except Exception:
        logger.warning("LightGBM 未安装，跳过该对照模型")

    try:
        from catboost import CatBoostClassifier

        models["CatBoost"] = CatBoostClassifier(
            iterations=600, depth=5, learning_rate=0.05, verbose=False,
            auto_class_weights="Balanced", random_seed=settings.RANDOM_SEED,
        )
    except Exception:
        logger.warning("CatBoost 未安装，跳过该对照模型")

    return models


def _proba(model, X: pd.DataFrame) -> np.ndarray:
    return model.predict_proba(X)[:, 1]


# ---------------------------------------------------------------------------
# 交叉验证
# ---------------------------------------------------------------------------
def cross_validate(model_factory, ds: Dataset, n_splits: int = settings.CV_SPLITS) -> dict:
    """时间序列交叉验证：按年份排序后做前向滚动切分。"""
    train = ds.train.sort_values("year")
    X, y = train[ds.features], train["is_st"]
    tscv = TimeSeriesSplit(n_splits=n_splits)
    aucs, kss = [], []
    for fold, (tr, te) in enumerate(tscv.split(X), 1):
        model = model_factory()
        model.fit(X.iloc[tr], y.iloc[tr])
        prob = _proba(model, X.iloc[te])
        m = evaluate_model(y.iloc[te], prob, name=f"fold{fold}")
        aucs.append(m["auc"])
        kss.append(m["ks"])
        logger.info("  fold%d: AUC=%.4f KS=%.4f (训练 %d / 测试 %d)",
                    fold, m["auc"], m["ks"], len(tr), len(te))
    return {
        "cv_auc_mean": round(float(np.mean(aucs)), 4),
        "cv_auc_std": round(float(np.std(aucs)), 4),
        "cv_ks_mean": round(float(np.mean(kss)), 4),
        "cv_folds": len(aucs),
    }


# ---------------------------------------------------------------------------
# Optuna 调优
# ---------------------------------------------------------------------------
def tune_xgboost(ds: Dataset, n_trials: int = 30) -> dict:
    """TPE 贝叶斯搜索 + MedianPruner 剪枝。"""
    import optuna
    from xgboost import XGBClassifier

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    scale_pos_weight = float((ds.y_train == 0).sum() / max((ds.y_train == 1).sum(), 1))

    def objective(trial: "optuna.Trial") -> float:
        params = {
            "max_depth": trial.suggest_int("max_depth", 3, 7),
            "min_child_weight": trial.suggest_float("min_child_weight", 1, 15, log=True),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "gamma": trial.suggest_float("gamma", 0, 3),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 5, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 5, log=True),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 200, 900, step=100),
            "scale_pos_weight": trial.suggest_float("scale_pos_weight", 1.0, 8.0),
        }
        model = XGBClassifier(
            **params, objective="binary:logistic", eval_metric="auc",
            tree_method="hist", n_jobs=-1, random_state=settings.RANDOM_SEED,
        )
        model.fit(
            ds.X_train, ds.y_train,
            eval_set=[(ds.X_valid, ds.y_valid)],
            verbose=False,
        )
        return evaluate_model(ds.y_valid, _proba(model, ds.X_valid))["auc"]

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=settings.RANDOM_SEED),
        pruner=optuna.pruners.MedianPruner(n_warmup_steps=10),
    )
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    logger.info("Optuna 完成：最佳验证 AUC=%.4f（%d 次试验）", study.best_value, len(study.trials))
    return {"params": study.best_params, "best_auc": round(study.best_value, 4), "n_trials": len(study.trials)}


# ---------------------------------------------------------------------------
# 主训练流程
# ---------------------------------------------------------------------------
def train_all(trials: int = 30, use_optuna: bool = True, cv: bool = True) -> dict:
    settings.ensure_dirs()
    ds = load_dataset()
    scale_pos_weight = float((ds.y_train == 0).sum() / max((ds.y_train == 1).sum(), 1))

    results: dict[str, dict] = {}
    models = build_baselines(scale_pos_weight)
    started = time.time()

    for name, model in models.items():
        logger.info("训练 %s ...", name)
        if cv:
            cv_result = cross_validate(lambda m=model: clone(m), ds)
        else:
            cv_result = {}

        model.fit(ds.X_train, ds.y_train)
        valid_metrics = evaluate_model(ds.y_valid, _proba(model, ds.X_valid), name=name)
        metrics = {**valid_metrics, **cv_result, "split": "valid_2023"}
        if not ds.test.empty:
            metrics["test_2024"] = evaluate_model(ds.y_test, _proba(model, ds.X_test), name=name)
        results[name] = metrics
        logger.info("%-20s 验证 AUC=%.4f KS=%.4f F1=%.4f Brier=%.4f",
                    name, metrics["auc"], metrics["ks"], metrics["f1"], metrics["brier"])

    # ---- XGBoost 调优 ----
    tuning = {}
    if use_optuna and trials > 0:
        logger.info("开始 Optuna 调优（%d 次试验）...", trials)
        tuning = tune_xgboost(ds, trials)
        from xgboost import XGBClassifier

        best = XGBClassifier(
            **tuning["params"], objective="binary:logistic", eval_metric="auc",
            tree_method="hist", n_jobs=-1, random_state=settings.RANDOM_SEED,
        )
        best.fit(ds.X_train, ds.y_train)
        models["XGBoost"] = best
        tuned = evaluate_model(ds.y_valid, _proba(best, ds.X_valid), name="XGBoost(tuned)")
        results["XGBoost(tuned)"] = {**tuned, "split": "valid_2023"}
        if not ds.test.empty:
            results["XGBoost(tuned)"]["test_2024"] = evaluate_model(
                ds.y_test, _proba(best, ds.X_test), name="XGBoost(tuned)"
            )
        logger.info("调优后 XGBoost 验证 AUC=%.4f（提升 %.4f）",
                    tuned["auc"], tuned["auc"] - results["XGBoost"]["auc"])

    # ---- 落盘 ----
    final_model = models["XGBoost"]
    final_model.save_model(str(settings.MODEL_PATH))
    joblib.dump(models, settings.MODEL_ALL_PATH)
    joblib.dump(ds.features, settings.ARTIFACT_DIR / "feature_names.pkl")

    meta = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - started, 1),
        "n_features": len(ds.features),
        "features": ds.features,
        "train_years": list(settings.TRAIN_YEAR_RANGE),
        "valid_year": settings.VALID_YEAR,
        "test_year": settings.TEST_YEAR,
        "label_horizon": settings.LABEL_HORIZON,
        "scale_pos_weight": round(scale_pos_weight, 3),
        "dataset": {
            "train": int(len(ds.train)), "valid": int(len(ds.valid)),
            "test": int(len(ds.test)), "positive_rate": round(float(ds.y_train.mean()), 4),
        },
        "tuning": tuning,
        "risk_thresholds": settings.RISK_THRESHOLDS,
    }
    settings.MODEL_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    settings.METRICS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("模型已保存：%s", settings.rel(settings.MODEL_PATH))
    logger.info("指标已保存：%s", settings.rel(settings.METRICS_PATH))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="训练五模型并调优 XGBoost")
    parser.add_argument("--trials", type=int, default=30, help="Optuna 试验次数（0 表示跳过）")
    parser.add_argument("--no-optuna", action="store_true", help="跳过贝叶斯调优")
    parser.add_argument("--no-cv", action="store_true", help="跳过交叉验证（节省时间）")
    args = parser.parse_args()
    train_all(trials=args.trials, use_optuna=not args.no_optuna, cv=not args.no_cv)


if __name__ == "__main__":
    main()
