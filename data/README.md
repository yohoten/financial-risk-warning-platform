# 数据目录说明

本目录按"原始 → 清洗 → 特征库"三层组织，所有文件均可由流水线重新生成。
仓库默认只保留目录结构与说明，数据文件被 `.gitignore` 排除。

```
data/
├── raw/                 # 原始数据（CSMAR 导出 / 爬虫下载）
│   ├── csmar_financial.csv      财务报表主表（股票代码、年度、报表科目）
│   ├── csmar_governance.csv     公司治理（股权结构、董事会、审计特征）
│   ├── text_sentiment.csv       年报 MD&A 情感打分（FinBERT 输出）
│   ├── market_features.csv      市场交易特征（换手率、波动率）
│   ├── legal_events.csv         司法/合规事件（涉诉、处罚次数）
│   ├── labels_st.csv            ST 标签（T 年是否被实施 ST/*ST）
│   └── annual_reports/          年报 PDF + mdna_text/ 抽取文本
├── external/
│   └── macro_industry.csv       宏观与行业指标（GDP/M2/CPI/PPI/PMI/社融）
├── cleaned/
│   └── panel_clean.parquet      清洗后的公司-年面板
└── feature_store/
    ├── panel_features.parquet   73 维全量特征面板
    ├── panel_model_input.parquet 建模输入表（ID + 标签 + 筛选后特征）
    ├── selected_features.json   四步筛选后的特征清单
    └── feature_selection_report.csv  特征筛选证据链
```

## 三层数据契约

| 层 | 粒度 | 主键 | 生成方式 |
|----|------|------|---------|
| raw | 单表原始记录 | `stock_code + year` | CSMAR 导出 / 爬虫 / `data.gen_demo_data` |
| cleaned | 公司-年面板 | `stock_code + year` | `etl.clean_financial`（去重、插补、缩尾） |
| feature_store | 建模宽表 | `stock_code + year` | `etl.feature_engineering` + `etl.feature_selection` |

## 字段与单位约定

- 金额单位统一为**亿元**，比率类为小数（0.35 表示 35%）；
- 所有比率特征经 1%/99% 分位缩尾，极端值不会污染模型；
- 特征口径的唯一事实来源是 `config/feature_registry.py`；
- 标签口径：**T 年 ST 状态**，特征取 **T-2 年**，避免前视偏差。

## 如何替换为真实数据

1. 按上表列名从 CSMAR/Wind 导出 CSV 放入 `data/raw/`；
2. 确认 `stock_code` 为 6 位字符串（如 `000001`）、`year` 为整数；
3. 运行 `python -m etl.run_pipeline`（**不要**加 `--refresh`，避免覆盖真实数据）；
4. 其余流程（特征筛选、训练、解释、看板）完全不变。

> 提示：真实数据往往缺少部分字段，`build_panel` 会记录缺失特征并补 0，
> 同时打印告警；论文中应说明缺失字段及其对结论的影响。
