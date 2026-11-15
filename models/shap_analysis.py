"""SHAP 四维度可解释性分析：全局重要性 / 局部归因 / 依赖效应 / 交互效应。

计算一次、缓存复用。缓存内容为纯 numpy 数组 + 元信息，
避免 pickle SHAP Explanation 对象在不同 shap 版本间失效。
"""

from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd

from config import settings
from config.feature_registry import FEATURE_MAP, TARGET_COLUMN, cn_names, direction_of
from etl.io_utils import get_logger
from models.data import load_dataset
from models.predict import load_model, load_meta
from models.run_manifest import current_run_id

logger = get_logger("shap")


def _explanation_paths():
    return settings.SHAP_VALUES, settings.SHAP_EXPLAINER


def compute_and_cache(max_samples: int | None = None) -> dict:
    """计算全量 SHAP 值并写入缓存。"""
    import shap

    settings.ensure_dirs()
    ds = load_dataset()
    model = load_model()

    X = ds.X_all
    index = pd.concat([ds.train[["stock_code", "year"]], ds.valid[["stock_code", "year"]], ds.test[["stock_code", "year"]]])
    if max_samples and len(X) > max_samples:
        X = X.sample(max_samples, random_state=settings.RANDOM_SEED).sort_index()
        index = index.loc[X.index]

    explainer = shap.TreeExplainer(model)
    values = explainer.shap_values(X)
    base_value = float(np.array(explainer.expected_value).ravel()[0])

    cache = {
        "values": np.asarray(values, dtype=float),
        "base_value": base_value,
        "features": list(X.columns),
        "feature_values": X.to_numpy(dtype=float),
        "index": index.reset_index(drop=True),
    }
    joblib.dump(cache, settings.SHAP_VALUES)
    joblib.dump(explainer, settings.SHAP_EXPLAINER)
    meta = {
        "run_id": current_run_id(),
        "n_samples": int(len(X)),
        "n_features": len(X.columns),
        "base_value": base_value,
        "model_created_at": load_meta().get("created_at", "unknown"),
    }
    (settings.CACHE_DIR / "shap_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    logger.info("SHAP 计算完成并缓存：%s 样本 × %s 特征，基准值 %.4f", len(X), len(X.columns), base_value)
    return cache


def cache_status() -> dict:
    """缓存是否与当前模型同版本：run_id、特征数、样本数。"""
    meta_path = settings.CACHE_DIR / "shap_meta.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    model_meta = load_meta() if settings.MODEL_META.exists() else {}
    expected_run = model_meta.get("run_id", "unknown")
    n_model_features = int(model_meta.get("n_features", 0))
    return {
        "cache_exists": settings.SHAP_VALUES.exists(),
        "cache_run_id": meta.get("run_id"),
        "model_run_id": expected_run,
        "cache_features": meta.get("n_features"),
        "model_features": n_model_features,
        "cache_samples": meta.get("n_samples"),
        "is_current": bool(
            settings.SHAP_VALUES.exists()
            and meta.get("run_id") == expected_run
            and int(meta.get("n_features", -1)) == n_model_features
        ),
    }


def load_cache(force: bool = False) -> dict:
    """读取 SHAP 缓存；缺失或与当前模型版本不一致时自动重算。

    只比较文件是否存在会让"重训后仍用旧解释"静默发生，因此这里校验
    `shap_meta.json` 中的 run_id 与特征数，不一致即重算并告警。
    """
    if force:
        return compute_and_cache()
    status = cache_status()
    if status["cache_exists"] and not status["is_current"]:
        logger.warning("SHAP 缓存与当前模型不一致（cache=%s / model=%s，特征 %s / %s），自动重算",
                       status["cache_run_id"], status["model_run_id"],
                       status["cache_features"], status["model_features"])
        return compute_and_cache()
    if status["cache_exists"]:
        return joblib.load(settings.SHAP_VALUES)
    return compute_and_cache()


# ---------------------------------------------------------------------------
# 维度一：全局特征重要性
# ---------------------------------------------------------------------------
def global_importance(top_n: int = 20) -> pd.DataFrame:
    """按 mean(|SHAP|) 排序，返回带中文名与方向的特征重要性表。"""
    cache = load_cache()
    values = cache["values"]
    importance = np.abs(values).mean(axis=0)
    df = pd.DataFrame({"feature": cache["features"], "importance": importance})
    df["中文名"] = df["feature"].map(cn_names(df["feature"]))
    df["方向"] = df["feature"].map(lambda f: "正向" if direction_of([f])[f] > 0 else "逆向")
    df["维度"] = df["feature"].map(lambda f: FEATURE_MAP[f].group if f in FEATURE_MAP else "other")
    return df.sort_values("importance", ascending=False).head(top_n).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 维度二：局部单样本归因
# ---------------------------------------------------------------------------
def local_contribution(stock_code: str, year: int | None = None, top_n: int = 15) -> dict:
    """单样本归因：返回基准值、预测值、贡献最大的特征列表。"""
    cache = load_cache()
    index = cache["index"]
    mask = index["stock_code"].astype(str).str.zfill(6) == str(stock_code).zfill(6)
    if year is not None:
        mask &= index["year"] == year
    if not mask.any():
        raise ValueError(f"SHAP 缓存中未找到 {stock_code} 的样本")

    pos = int(np.where(mask.to_numpy())[0][-1])  # 取最新一期
    values = cache["values"][pos]
    feature_values = cache["feature_values"][pos]
    base = cache["base_value"]
    raw_prob = float(1 / (1 + np.exp(-(base + values.sum()))))
    # SHAP 加和给出的是未校准概率；对外展示需与风险卡片一致，故再过一遍校准器
    try:
        from models.calibration import load_calibrator

        prob = float(np.asarray(load_calibrator().apply(np.array([raw_prob]))).ravel()[0])
        calibrated = True
    except Exception as exc:  # 校准器缺失/版本不兼容时退回原始概率，不阻断解释
        logger.warning("校准器不可用，返回未校准概率：%s", exc)
        prob = raw_prob
        calibrated = False

    df = pd.DataFrame(
        {
            "feature": cache["features"],
            "中文名": [FEATURE_MAP.get(f).cn if f in FEATURE_MAP else f for f in cache["features"]],
            "取值": np.round(feature_values, 4),
            "SHAP值": np.round(values, 4),
            "方向": ["推高风险" if v > 0 else "降低风险" for v in values],
        }
    )
    df["绝对值"] = df["SHAP值"].abs()
    df = df.sort_values("绝对值", ascending=False)

    return {
        "stock_code": str(stock_code).zfill(6),
        "year": int(index.loc[pos, "year"]),
        "base_value": base,
        "prediction": prob,
        "raw_probability": raw_prob,
        "calibrated": calibrated,
        "contributions": df.head(top_n).drop(columns=["绝对值"]).reset_index(drop=True),
        "all_contributions": df.reset_index(drop=True),
    }


# ---------------------------------------------------------------------------
# 维度三：特征依赖效应
# ---------------------------------------------------------------------------
def dependence(feature: str) -> pd.DataFrame:
    """单特征依赖：特征取值 vs 该特征的 SHAP 值，用于识别非线性拐点。"""
    cache = load_cache()
    if feature not in cache["features"]:
        raise ValueError(f"特征 {feature} 不在 SHAP 缓存中")
    j = cache["features"].index(feature)
    return pd.DataFrame(
        {
            "feature_value": cache["feature_values"][:, j],
            "shap_value": cache["values"][:, j],
            "stock_code": cache["index"]["stock_code"].values,
        }
    )


# ---------------------------------------------------------------------------
# 维度四：交互效应
# ---------------------------------------------------------------------------
def interaction_pairs(top_n: int = 10, max_samples: int = 400) -> pd.DataFrame:
    """Top-N 特征两两交互强度（近似：SHAP 值的相关系数 × 重要性乘积）。

    精确的 SHAP interaction values 计算量为 O(T·L·D²)，在演示场景下过慢，
    因此这里使用"重要性加权相关性"作为交互强度的代理指标，并在文档中标注。
    """
    cache = load_cache()
    values = cache["values"]
    importance = np.abs(values).mean(axis=0)
    top_idx = np.argsort(importance)[::-1][: min(top_n, values.shape[1])]
    sub = values[:, top_idx]

    sample = sub[: max_samples] if len(sub) > max_samples else sub
    corr = np.corrcoef(sample, rowvar=False)
    names = [cache["features"][i] for i in top_idx]

    rows = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            rows.append(
                {
                    "feature_a": names[i],
                    "feature_b": names[j],
                    "交互强度": round(float(abs(corr[i, j]) * np.sqrt(importance[top_idx[i]] * importance[top_idx[j]])), 5),
                    "相关系数": round(float(corr[i, j]), 3),
                }
            )
    return pd.DataFrame(rows).sort_values("交互强度", ascending=False).head(15).reset_index(drop=True)


def four_dimension_summary() -> dict:
    """四维度分析摘要，供报告导出与答辩材料引用。"""
    cache = load_cache()
    imp = global_importance(20)
    return {
        "n_samples": int(len(cache["values"])),
        "base_value": cache["base_value"],
        "top_features": imp.head(10)[["feature", "中文名", "importance"]].to_dict("records"),
        "top_interactions": interaction_pairs(8).head(5).to_dict("records"),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="TreeSHAP 四维度解释与缓存")
    parser.add_argument("--force", action="store_true", help="忽略缓存强制重算")
    parser.add_argument("--max-samples", type=int, default=None, help="只解释前 N 个样本（调试用）")
    parser.add_argument("--check", action="store_true", help="只检查缓存是否与当前模型同版本")
    args = parser.parse_args()

    if args.check:
        status = cache_status()
        for key, value in status.items():
            print(f"{key:16s} {value}")
        raise SystemExit(0 if status["is_current"] else 1)

    if args.force or args.max_samples:
        compute_and_cache(max_samples=args.max_samples)
    else:
        load_cache()
    print(global_importance(10).to_string(index=False))


if __name__ == "__main__":
    main()
