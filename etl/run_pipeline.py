"""数据流水线编排：原始数据 → 清洗 → 特征 → 筛选 → 建模输入表。

一条命令跑通数据层，是"答辩现场从零复现"的入口：

    python -m etl.run_pipeline            # 缺数据时自动生成演示数据
    python -m etl.run_pipeline --refresh  # 强制重新生成演示数据
"""

from __future__ import annotations

import argparse
import time

import pandas as pd

from config import settings
from config.feature_registry import FEATURE_KEYS, ID_COLUMNS, TARGET_COLUMN
from etl.feature_engineering import build_panel
from etl.feature_selection import select_features
from etl.io_utils import get_logger, read_table, write_table

logger = get_logger("pipeline")


def ensure_raw_data(refresh: bool = False, companies: int = 240) -> None:
    """原始数据缺失（或强制刷新）时生成演示数据。"""
    if refresh or not settings.RAW_FINANCIAL.exists():
        from data.gen_demo_data import generate

        logger.info("生成演示原始数据（%d 家公司）...", companies)
        generate(companies)
    else:
        logger.info("检测到已有原始数据：%s", settings.rel(settings.RAW_FINANCIAL))


def build_model_input(panel: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """输出建模输入表：ID + 标签 + 选中特征 + 展示用辅助列。"""
    extras = [c for c in ["total_assets", "revenue", "net_profit", "ocf"] if c in panel.columns]
    cols = [c for c in ID_COLUMNS if c in panel.columns] + [TARGET_COLUMN] + features + extras
    out = panel[cols].copy()
    write_table(out, settings.FEATURE_MATRIX)
    logger.info("建模输入表已写出：%s（%d 行 × %d 列）", settings.rel(settings.FEATURE_MATRIX), *out.shape)
    return out


def run(refresh: bool = False, companies: int = 240, skip_selection: bool = False) -> dict:
    started = time.time()
    settings.ensure_dirs()
    ensure_raw_data(refresh, companies)

    panel = build_panel()
    write_table(panel, settings.FEATURE_PANEL)
    write_table(panel, settings.CLEANED_PANEL)

    if skip_selection:
        features = [f for f in FEATURE_KEYS if f in panel.columns]
        logger.info("跳过特征筛选，使用全量 %d 维特征", len(features))
    else:
        features = select_features(panel)

    model_input = build_model_input(panel, features)
    elapsed = round(time.time() - started, 1)
    logger.info("流水线完成：耗时 %.1fs，样本 %d 行，特征 %d 维", elapsed, len(model_input), len(features))
    return {"rows": len(model_input), "features": len(features), "elapsed_sec": elapsed}


def main() -> None:
    parser = argparse.ArgumentParser(description="运行数据流水线")
    parser.add_argument("--refresh", action="store_true", help="强制重新生成演示原始数据")
    parser.add_argument("--companies", type=int, default=240, help="演示数据公司数量")
    parser.add_argument("--skip-selection", action="store_true", help="跳过四步特征筛选")
    args = parser.parse_args()
    run(args.refresh, args.companies, args.skip_selection)


if __name__ == "__main__":
    main()
