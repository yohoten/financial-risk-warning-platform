# 数据目录说明

本目录按"原始 → 清洗 → 特征库"三层组织，所有文件均可由流水线重新生成。
仓库默认只保留目录结构与说明，数据文件被 `.gitignore` 排除。

```
data/
├── raw/                 # 原始数据
│   ├── FS_Combas.csv            资产负债表原始导出（科目代码 A001000000…）
│   ├── FS_Comins.csv            利润表原始导出
│   ├── FS_Comscfd.xlsx          现金流量表原始导出（XLSX，需先转换）
│   ├── basic_info.csv           上市公司基本信息年度表
│   ├── AUD_opinion.csv          审计意见表
│   ├── TOP10_holders_A/B/C.csv  十大股东（CSMAR 单次导出 100 万行上限，分三批）
│   ├── CG_manager.csv           高管人数、持股及薪酬
│   ├── csmar_financial.csv      ← 由三分表合并（契约表，单位已换算为亿元）
│   ├── csmar_governance.csv     ← 十大股东 + 高管表 + 四大审计
│   ├── market_features.csv      ← 审计意见 + 审计费用（交易字段待补）
│   ├── ST_events.csv            ← ST 事件表（当前为基本信息简称代理，官方表待补）
│   ├── labels_st.csv            ← 完整 0/1 ST 标签（48,290 个 A 股公司-年，2013–2025）
│   ├── text_sentiment.csv       年报 MD&A 情感（待补）
│   ├── legal_events.csv         诉讼/处罚（待补）
│   └── annual_reports/          年报 PDF + mdna_text/ 抽取文本
├── incoming/csmar/
│   ├── FS_Comscfd_filtered.csv  XLSX 流式转换产物（4 个现金流科目）
│   ├── download_log.md          下载日志（表名/筛选/年份/行数）
│   └── desc/                    CSMAR 字段说明文件（*[DES].txt）
├── external/
│   ├── macro_industry.csv       宏观与行业指标（待补；当前只有 .demo.csv）
│   └── macro_industry.demo.csv  演示值，**不参与真实建模**
├── demo_raw/            演示数据备份（gen_demo_data 生成，避免与真实代码混用）
├── cleaned/
│   └── panel_clean.parquet      清洗后的公司-年面板
└── feature_store/
    ├── panel_features.parquet   73 维全量特征面板
    ├── panel_model_input.parquet 建模输入表（ID + 标签 + 筛选后特征）
    ├── selected_features.json   四步筛选后的特征清单
    └── feature_selection_report.csv  特征筛选证据链
```

## 真实数据接入流程（CSMAR）

```bash
# 1. 原始导出放入 data/raw（命名见 docs/CSMAR手动下载清单.md）
# 2. 现金流量表 XLSX → 精简 CSV（约 7 分钟，一次性）
python -m scripts.convert_csmar_xlsx
# 3. 科目代码解码 + 三表合并 + 治理/审计映射 → 写入契约表
python -m etl.csmar_import --step all --write
# 4. 质量体检
python -m scripts.validate_raw_data      # 报告：reports/data_quality/
# 5. 当前用基本信息简称生成代理 ST 标签（官方表到位后改为官方 ST_events.csv）
python -m scripts.build_st_labels_proxy --write
python -m etl.csmar_import --step labels --write
python -m etl.run_pipeline                  # 特征 2015–2023；2024 测试需 2026 标签
```

当前进度与缺口见 [`docs/CSMAR数据可行性报告.md`](../docs/CSMAR数据可行性报告.md)。

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

1. 用映射层导入 CSMAR/Wind 导出文件（不建议手工改列名）：
   ```bash
   python -m etl.mapping --list                                      # 查看目标表与必需列
   python -m etl.mapping --source D:\csmar\export --table financial --dry-run
   python -m etl.mapping --source D:\csmar\export --write          # 确认命中率后写盘
   ```
2. 运行数据质量校验，确认 0 错误后再进入 ETL：
   ```bash
   python -m scripts.validate_raw_data
   python -m scripts.validate_raw_data --source D:\csmar\export     # 同时检查映射覆盖率
   ```
   报告输出到 `reports/data_quality/`（Markdown + JSON）。
3. 确认 `stock_code` 为 6 位字符串（如 `000001`）、`year` 为整数；
4. 运行 `python -m etl.run_pipeline`（**不要**加 `--refresh`，避免覆盖真实数据）；
5. 其余流程（特征筛选、训练、解释、看板）完全不变。

> 单位约定：`data/mapping/csmar.yaml` 默认 CSMAR 金额为“元”，按 `1e-8` 转为“亿元”；
> 若导出已是亿元，请把对应列的 `scale` 改为 `1`。治理类持股比例默认按百分数导出（`0.01`），
> 若已是小数请同样改为 `1`。

> 提示：真实数据往往缺少部分字段，`build_panel` 会记录缺失特征并补 0，
> 同时打印告警；论文中应说明缺失字段及其对结论的影响。
