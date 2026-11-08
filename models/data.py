"""建模数据加载：按时间切分 训练/验证/测试，禁止随机切分。

切分口径（与实施方案一致）
--------------------------
训练：2015-2022（用于拟合与交叉验证）
验证：2023（用于阈值选择、早停与模型比较）
测试：2024（只在最终评估时使用一次）
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd

from config import settings
from config.feature_registry import FEATURE_KEYS, TARGET_COLUMN
from etl.io_utils import get_logger, read_table, resolve

logger = get_logger("data")


@dataclass
class Dataset:
    train: pd.DataFrame
    valid: pd.DataFrame
    test: pd.DataFrame
    features: list[str]

    @property
    def X_train(self) -> pd.DataFrame:
        return self.train[self.features]

    @property
    def y_train(self) -> pd.Series:
        return self.train[TARGET_COLUMN]

    @property
    def X_valid(self) -> pd.DataFrame:
        return self.valid[self.features]

    @property
    def y_valid(self) -> pd.Series:
        return self.valid[TARGET_COLUMN]

    @property
    def X_test(self) -> pd.DataFrame:
        return self.test[self.features]

    @property
    def y_test(self) -> pd.Series:
        return self.test[TARGET_COLUMN]

    @property
    def X_all(self) -> pd.DataFrame:
        return pd.concat([self.X_train, self.X_valid, self.X_test])

    def describe(self) -> str:
        return (
            f"训练 {len(self.train)} 行(正样本 {self.y_train.mean():.2%}) | "
            f"验证 {len(self.valid)} 行(正样本 {self.y_valid.mean():.2%}) | "
            f"测试 {len(self.test)} 行(正样本 {self.y_test.mean():.2%}) | "
            f"特征 {len(self.features)} 维"
        )


def load_feature_list() -> list[str]:
    """读取筛选后的特征清单；文件缺失时回退到全量特征。"""
    if settings.FEATURE_LIST.exists():
        payload = json.loads(settings.FEATURE_LIST.read_text(encoding="utf-8"))
        return payload["features"]
    logger.warning("未找到特征清单，使用全量 %d 维特征（建议先运行特征筛选）", len(FEATURE_KEYS))
    return list(FEATURE_KEYS)


def load_panel() -> pd.DataFrame:
    """优先读取建模输入表，其次读取完整特征面板。"""
    if resolve(settings.FEATURE_MATRIX):
        return read_table(settings.FEATURE_MATRIX)
    return read_table(settings.FEATURE_PANEL)


def load_dataset(features: list[str] | None = None) -> Dataset:
    """加载并按时间切分数据集。"""
    panel = load_panel()
    features = features or load_feature_list()
    features = [f for f in features if f in panel.columns]
    if not features:
        raise ValueError("数据集中没有任何可用特征，请先运行 etl 流水线")

    train = panel[panel["year"].between(*settings.TRAIN_YEAR_RANGE)].copy()
    valid = panel[panel["year"] == settings.VALID_YEAR].copy()
    test = panel[panel["year"] == settings.TEST_YEAR].copy()

    if train.empty or valid.empty:
        raise ValueError(
            f"时间切分后训练集({len(train)})或验证集({len(valid)})为空，"
            f"请检查数据年份覆盖（当前 {sorted(panel['year'].unique())}）"
        )

    ds = Dataset(train=train, valid=valid, test=test, features=features)
    logger.info("数据加载完成：%s", ds.describe())
    return ds
