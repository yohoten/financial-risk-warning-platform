# -*- coding: utf-8 -*-
"""字段级激活现金流单位修正，禁止整表覆盖扣非/折旧等后续补充列。"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from config import settings

FIELDS = ["ocf", "icf", "fcf_financing", "capex"]
SOURCE = settings.RAW_DIR / "candidates" / "csmar_financial_cashflow_fixed.csv"


def main() -> None:
    current = pd.read_csv(settings.RAW_FINANCIAL, encoding="utf-8-sig", dtype={"stock_code": str}, low_memory=False)
    fixed = pd.read_csv(SOURCE, encoding="utf-8-sig", dtype={"stock_code": str}, low_memory=False)
    key = ["stock_code", "year"]
    assert not current.duplicated(key).any() and not fixed.duplicated(key).any()
    before_hash = hashlib.sha256(pd.util.hash_pandas_object(
        current["deducted_profit"], index=True).values.tobytes()).hexdigest()
    current["stock_code"] = current["stock_code"].str.zfill(6)
    fixed["stock_code"] = fixed["stock_code"].str.zfill(6)
    mapped = current[key].merge(fixed[key + FIELDS], on=key, how="left", validate="one_to_one")
    for col in FIELDS:
        old = pd.to_numeric(current[col], errors="coerce")
        new = pd.to_numeric(mapped[col], errors="coerce")
        # 当前错误值比候选小约 1e8；仅接纳同方向修正，缺失保留原值。
        ratio = (new.abs() / old.abs()).replace([float("inf")], pd.NA)
        plausible = ratio.isna() | ratio.between(1e6, 1e10)
        current[col] = new.where(plausible, old).combine_first(old)
    after_hash = hashlib.sha256(pd.util.hash_pandas_object(
        current["deducted_profit"], index=True).values.tobytes()).hexdigest()
    assert before_hash == after_hash, "扣非列被改动，停止写回"
    current.to_csv(settings.RAW_FINANCIAL, index=False, encoding="utf-8-sig")
    print("现金流字段级修正完成：", FIELDS)
    print("修正后中位数（亿元）：", current[FIELDS].median().to_dict())
    print("扣非非空数及哈希保持不变：", current["deducted_profit"].notna().sum(), after_hash)


if __name__ == "__main__":
    main()
