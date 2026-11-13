"""五模型对比训练与 Optuna 贝叶斯调优。

流程
----
1. 按年分组扩展窗口交叉验证（训练年份严格早于测试年份），给出稳定性区间；
2. XGBoost 使用 Optuna TPE 搜索 + MedianPruner 剪枝（--trials 控制预算）；
3. 其余四个模型作为基线/对照，固定合理默认参数；
4. 全部模型在验证集上比较并做概率校准，XGBoost 作为主模型落盘。

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
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from config import settings
from etl.io_utils import get_logger
from models.calibration import cross_fitted_probabilities, fit_calibrator, save_calibrator
from models.data import Dataset, load_dataset
from models.metrics import cost_optimal_threshold, evaluate_model, top_k_metrics
from models.run_manifest import record_run

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
def _year_expanding_splits(years: np.ndarray, n_splits: int):
    """按年份分组的扩展窗口切分，保证训练年份严格早于测试年份。

    消除按行 `TimeSeriesSplit` 造成的同年重叠问题（训练/测试含同一年份的公司，
    见中期可行性报告 §3.3 问题二、§4.4）。
    """
    unique_years = np.sort(np.unique(years))
    if len(unique_years) < 2:
        raise ValueError("训练集年份不足，无法做时间交叉验证")
    n_splits = max(1, min(n_splits, len(unique_years) - 1))
    for test_year in unique_years[-n_splits:]:
        yield years < test_year, years == test_year


def cross_validate(model_factory, ds: Dataset, n_splits: int = settings.CV_SPLITS) -> dict:
    """按年分组扩展窗口交叉验证：训练年份严格早于测试年份。"""
    train = ds.train.sort_values("year")
    X, y = train[ds.features], train["is_st"]
    years = train["year"].to_numpy()
    aucs, kss = [], []
    folds = 0
    for fold, (tr, te) in enumerate(_year_expanding_splits(years, n_splits), 1):
        if te.sum() == 0:
            continue
        if len(np.unique(y.iloc[te])) < 2:
            logger.warning("  fold%d 测试年份只有单一类别，跳过", fold)
            continue
        model = model_factory()
        model.fit(X.iloc[tr], y.iloc[tr])
        prob = _proba(model, X.iloc[te])
        m = evaluate_model(y.iloc[te], prob, name=f"fold{fold}")
        aucs.append(m["auc"])
        kss.append(m["ks"])
        folds += 1
        logger.info("  fold%d: 训练≤%d / 测试%s: AUC=%.4f KS=%.4f",
                    fold, int(np.unique(years[tr]).max()), np.unique(years[te]).tolist(),
                    m["auc"], m["ks"])
    if folds == 0:
        return {"cv_auc_mean": None, "cv_auc_std": None, "cv_ks_mean": None, "cv_folds": 0}
    return {
        "cv_auc_mean": round(float(np.mean(aucs)), 4),
        "cv_auc_std": round(float(np.std(aucs)), 4),
        "cv_ks_mean": round(float(np.mean(kss)), 4),
        "cv_folds": folds,
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
            "scale_pos_weight": trial.suggest_float("scale_pos_weight", 1.0, 30.0),
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
    calibrators: dict[str, object] = {}
    models = build_baselines(scale_pos_weight)
    started = time.time()

    for name, model in models.items():
        logger.info("训练 %s ...", name)
        if cv:
            cv_result = cross_validate(lambda m=model: clone(m), ds)
        else:
            cv_result = {}

        model.fit(ds.X_train, ds.y_train)
        raw_valid = _proba(model, ds.X_valid)
        raw_test = _proba(model, ds.X_test) if not ds.test.empty else None

        # 校准只在验证集拟合；阈值在“交叉拟合校准后验证集”上用业务成本选择。
        calibrator = fit_calibrator(ds.y_valid, raw_valid, fit_year=settings.VALID_YEAR)
        cal_valid = cross_fitted_probabilities(ds.y_valid, raw_valid, method=settings.CALIBRATION_METHOD)
        threshold = cost_optimal_threshold(ds.y_valid, cal_valid)
        valid_metrics = evaluate_model(ds.y_valid, cal_valid, threshold=threshold, name=name)
        raw_metrics = evaluate_model(ds.y_valid, raw_valid, name=f"{name}(raw)")
        valid_metrics["raw_valid"] = {
            key: raw_metrics[key] for key in ("auc", "pr_auc", "brier", "ece", "threshold")
        }
        valid_metrics["calibration"] = {
            **calibrator.describe(),
            "scope": "cross_fitted_valid_5fold",
            "brier_raw": raw_metrics["brier"],
            "brier_cal": valid_metrics["brier"],
            "ece_raw": raw_metrics["ece"],
            "ece_cal": valid_metrics["ece"],
        }

        metrics = {**valid_metrics, **cv_result, "split": f"valid_{settings.VALID_YEAR}"}
        if raw_test is not None:
            # 阈值来自验证集，测试集只应用、不重选，避免测试集信息泄露
            metrics[f"test_{settings.TEST_YEAR}"] = evaluate_model(
                ds.y_test, calibrator.apply(raw_test),
                threshold=threshold, name=name,
            )
        results[name] = metrics
        calibrators[name] = calibrator
        logger.info("%-20s 验证 PR-AUC=%.4f AUC=%.4f Recall@Top10=%.4f ECE=%.4f（校准前 ECE=%.4f）",
                    name, metrics["pr_auc"], metrics["auc"],
                    metrics["top_k"]["top_10pct"]["recall"], metrics["ece"], raw_metrics["ece"])

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
        raw_valid = _proba(best, ds.X_valid)
        calibrator = fit_calibrator(ds.y_valid, raw_valid, fit_year=settings.VALID_YEAR)
        cal_valid = cross_fitted_probabilities(ds.y_valid, raw_valid, method=settings.CALIBRATION_METHOD)
        threshold = cost_optimal_threshold(ds.y_valid, cal_valid)
        tuned = evaluate_model(ds.y_valid, cal_valid, threshold=threshold, name="XGBoost(tuned)")
        calibrated_raw = evaluate_model(ds.y_valid, raw_valid, name="XGBoost(tuned, raw)")
        tuned["raw_valid"] = {k: calibrated_raw[k] for k in ("auc", "pr_auc", "brier", "ece", "threshold")}
        tuned["calibration"] = {
            **calibrator.describe(),
            "scope": "cross_fitted_valid_5fold",
            "brier_raw": calibrated_raw["brier"], "brier_cal": tuned["brier"],
            "ece_raw": calibrated_raw["ece"], "ece_cal": tuned["ece"],
        }
        results["XGBoost(tuned)"] = {**tuned, "split": f"valid_{settings.VALID_YEAR}"}
        calibrators["XGBoost"] = calibrator
        if not ds.test.empty:
            results["XGBoost(tuned)"][f"test_{settings.TEST_YEAR}"] = evaluate_model(
                ds.y_test, calibrator.apply(_proba(best, ds.X_test)),
                threshold=threshold, name="XGBoost(tuned)",
            )
        logger.info("调优后 XGBoost 验证 PR-AUC=%.4f（提升 %.4f）",
                    tuned["pr_auc"], tuned["pr_auc"] - results["XGBoost"]["pr_auc"])

    # ---- 落盘 ----
    final_model = models["XGBoost"]
    final_calibrator = calibrators["XGBoost"]

    # 成本敏感阈值：在“校准后验证集”上冻结；中风险 = 预警阈值 × RISK_MEDIUM_RATIO
    raw_valid_final = _proba(final_model, ds.X_valid)
    cal_valid_final = cross_fitted_probabilities(
        ds.y_valid, raw_valid_final, method=settings.CALIBRATION_METHOD
    )
    frozen_threshold = round(
        cost_optimal_threshold(ds.y_valid, cal_valid_final, settings.COST_FN, settings.COST_FP), 4
    )
    risk_thresholds = {
        "high": frozen_threshold,
        "medium": round(frozen_threshold * settings.RISK_MEDIUM_RATIO, 4),
    }
    final_valid_metrics = evaluate_model(
        ds.y_valid, cal_valid_final, threshold=frozen_threshold, name="XGBoost_final"
    )
    final_test_metrics = None
    if not ds.test.empty:
        final_test_metrics = evaluate_model(
            ds.y_test, final_calibrator.apply(_proba(final_model, ds.X_test)),
            threshold=frozen_threshold, name="XGBoost_final",
        )
    topk_validation = top_k_metrics(ds.y_valid, cal_valid_final)
    topk_key = f"top_{int(round(settings.TOP_K_PRIMARY * 100))}pct"
    topk_primary = topk_validation[topk_key]

    final_model.save_model(str(settings.MODEL_PATH))
    save_calibrator(final_calibrator, settings.CALIBRATOR_PATH)
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
        "lockbox_year": settings.LOCKBOX_YEAR,
        "label_horizon": settings.LABEL_HORIZON,
        "scale_pos_weight": round(scale_pos_weight, 3),
        "dataset": {
            "train": int(len(ds.train)), "valid": int(len(ds.valid)),
            "test": int(len(ds.test)), "positive_rate": round(float(ds.y_train.mean()), 4),
        },
        "tuning": tuning,
        "calibration": {
            **final_calibrator.describe(),
            "fit_on": f"valid_{settings.VALID_YEAR}",
            "brier_raw": results.get("XGBoost(tuned)", results["XGBoost"]).get("raw_valid", {}).get("brier"),
            "brier_cal": final_valid_metrics["brier"],
            "ece_raw": results.get("XGBoost(tuned)", results["XGBoost"]).get("raw_valid", {}).get("ece"),
            "ece_cal": final_valid_metrics["ece"],
        },
        "risk_thresholds": risk_thresholds,
        "threshold": {
            "value": frozen_threshold,
            "high": risk_thresholds["high"],
            "medium": risk_thresholds["medium"],
            "method": "cost",
            "cost_fn": settings.COST_FN,
            "cost_fp": settings.COST_FP,
            "selected_on": f"valid_{settings.VALID_YEAR}",
            "medium_ratio": settings.RISK_MEDIUM_RATIO,
            "note": "在校准后验证集上按 FN:FP 成本最小化选择；测试集仅应用阈值，不重新选择",
        },
        "top_k": {
            "fraction": settings.TOP_K_PRIMARY,
            "value": topk_primary["score_threshold"],
            "selected_on": f"valid_{settings.VALID_YEAR}",
            "validation": topk_validation,
            "test": final_test_metrics["top_k"] if final_test_metrics else None,
        },
    }
    settings.MODEL_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    settings.METRICS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    record_run(
        run_type="train",
        params={
            "trials": trials,
            "use_optuna": use_optuna,
            "cv": cv,
            "cv_protocol": "year_grouped_expanding",
            "tuning_best_params": tuning.get("params", {}),
            "random_seed": settings.RANDOM_SEED,
            "train_years": list(settings.TRAIN_YEAR_RANGE),
            "calibration": final_calibrator.describe(),
            "cost_fn": settings.COST_FN,
            "cost_fp": settings.COST_FP,
            "top_k_fraction": settings.TOP_K_PRIMARY,
        },
        metrics={
            "XGBoost": results.get("XGBoost"),
            "XGBoost(tuned)": results.get("XGBoost(tuned)"),
            "final_valid": final_valid_metrics,
            "final_test": final_test_metrics,
        },
        threshold={
            **risk_thresholds,
            "method": "cost",
            "cost_fn": settings.COST_FN,
            "cost_fp": settings.COST_FP,
            "top_k": meta["top_k"],
        },
        dataset=meta["dataset"],
        features=ds.features,
        extra={
            "model_path": settings.rel(settings.MODEL_PATH),
            "calibrator_path": settings.rel(settings.CALIBRATOR_PATH),
            "lockbox_year": settings.LOCKBOX_YEAR,
        },
    )

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
