# 原始数据质量报告

- 生成时间：2026-11-11 22:11:25
- 数据目录：`data\raw` / `data\external`
- 结论：**存在阻断项，需修复后再跑 ETL**
- 汇总：7 张表，205613 行，1 个错误、5 个警告

## 一、总览

| 表 | 行数 | 列数 | 错误 | 警告 | 年度范围 | 文件 |
|---|---|---|---|---|---|---|
| financial | 52203 | 40 | 0 | 3 | 2013–2025 | `data\raw\csmar_financial.csv` |
| governance | 52560 | 10 | 0 | 1 | 2013–2025 | `data\raw\csmar_governance.csv` |
| text_sentiment | 0 | 0 | 0 | 0 | - | `data\raw\text_sentiment.csv` |
| market_features | 52560 | 7 | 0 | 1 | 2013–2025 | `data\raw\market_features.csv` |
| legal_events | 0 | 0 | 0 | 0 | - | `data\raw\legal_events.csv` |
| labels_st | 48290 | 4 | 1 | 0 | 2013–2025 | `data\raw\labels_st.csv` |
| macro_industry | 0 | 0 | 0 | 0 | - | `data\external\macro_industry.csv` |

## 二、问题明细

### financial

- ⚠️ **missing_rate** · 6 列缺失率超过 30%，最高 100.0%：`{"deducted_profit": 1.0, "depreciation": 1.0, "bonds_payable": 0.7322, "lt_debt": 0.403, "rd_expense": 0.3225}`
- ⚠️ **accounting_identity** · 9/51003 行不满足 资产=负债+权益（容差 1%）
- ⚠️ **liabilities_over_assets** · 242 行负债超过总资产 105%（资不抵债口径需确认）

### governance

- ⚠️ **missing_rate** · 1 列缺失率超过 30%，最高 100.0%：`{"duality": 1.0}`

### text_sentiment

- ❌ **file_missing** · 文件不存在：data\raw\text_sentiment.csv

### market_features

- ⚠️ **missing_rate** · 2 列缺失率超过 30%，最高 100.0%：`{"annual_turnover": 1.0, "stock_volatility": 1.0}`

### legal_events

- ❌ **file_missing** · 文件不存在：data\raw\legal_events.csv

### labels_st

- ❌ **label_coverage** · 按 T+2 对齐，建模窗口内仅 86.1% 的公司-年有 ST 标签；缺口最多的特征年：2024(4914)、2022(83)、2021(76)（这些年的 T+2 标签缺失；2024 特征年需要 2026 年 ST 事件）

### macro_industry

- ❌ **file_missing** · 文件不存在：data\external\macro_industry.csv

## 三、跨表覆盖

| 表 | 与财务主表主键覆盖率 |
|---|---|
| governance | 94.86% |
| market_features | 94.86% |
| labels_st | 92.23% |
| labels_st@modeling_window | 86.06% |

## 四、年度分布

| 年份 | 公司-年记录 | ST 正样本率 |
|---|---|---|
| 2013 | 2434 | 2.03% |
| 2014 | 2597 | 1.85% |
| 2015 | 2883 | 1.91% |
| 2016 | 3212 | 2.03% |
| 2017 | 3592 | 2.17% |
| 2018 | 3683 | 2.57% |
| 2019 | 3877 | 3.64% |
| 2020 | 4327 | 5.01% |
| 2021 | 4754 | 3.58% |
| 2022 | 5026 | 2.51% |
| 2023 | 5199 | 2.06% |
| 2024 | 5262 | 2.50% |
| 2025 | 5357 | 3.34% |

## 六、建议

1. 先补齐缺失表/字段，或调整 `data/mapping/csmar.yaml` 的别名与必需列。
2. 核对报表口径与单位（元/万元/亿元）、是否合并报表、少数股东权益是否计入。
3. 检查跨表主键格式与年份范围；标签需覆盖 2015-2024 建模窗口。
4. 高缺失字段需说明缺失机制；必要时在特征筛选中剔除或改用行业-年度中位数。
