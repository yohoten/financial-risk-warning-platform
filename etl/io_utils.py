"""ETL 通用 I/O 与日志工具。

统一 read/write 入口，自动处理 parquet/csv 差异与目录创建，
并内置"文件不存在时给出可执行提示"的友好报错。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from config import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def get_logger(name: str) -> logging.Logger:
    """获取带统一格式的 logger（重复调用不会重复添加 handler）。"""
    if hasattr(sys.stdout, "reconfigure"):
        try:  # Windows 终端默认 GBK，统一为 UTF-8 避免日志乱码
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(settings.LOG_LEVEL)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt="%H:%M:%S"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def csv_fallback(path: Path) -> Path:
    """parquet 不可用时的同名 CSV 路径（Windows 迷你环境常见）。"""
    return Path(path).with_suffix(".csv")


def resolve(path: Path | str) -> Path | None:
    """返回实际存在的文件路径：优先 parquet，其次同名 CSV；都不存在返回 None。"""
    path = Path(path)
    if path.exists():
        return path
    alt = csv_fallback(path)
    return alt if alt.exists() else None


def read_table(path: Path | str, **kwargs: Any) -> pd.DataFrame:
    """读取 parquet/csv；parquet 引擎缺失时自动回退到 CSV。"""
    path = Path(path)
    target = resolve(path)
    if target is None:
        raise FileNotFoundError(
            f"未找到数据文件: {settings.rel(path)}\n"
            f"请先执行: python -m data.gen_demo_data  (生成演示数据)\n"
            f"或运行:   python -m etl.run_pipeline    (完整数据流水线)"
        )
    if target.suffix in {".parquet", ".pq"}:
        try:
            return pd.read_parquet(target, **kwargs)
        except ImportError:
            fallback = csv_fallback(target)
            if fallback.exists():
                return pd.read_csv(fallback, **kwargs)
            raise
    return pd.read_csv(target, **kwargs)


def write_table(df: pd.DataFrame, path: Path | str, index: bool = False) -> Path:
    """写出 parquet/csv，自动创建父目录；无 pyarrow 时降级写 CSV。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix in {".parquet", ".pq"}:
        try:
            df.to_parquet(path, index=index)
            return path
        except (ImportError, ValueError):
            path = csv_fallback(path)
    df.to_csv(path, index=index, encoding="utf-8-sig")
    return path
