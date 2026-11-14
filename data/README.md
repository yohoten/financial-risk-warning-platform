# 数据目录说明

本目录按"落地区 → 暂存区 → 契约层 → 清洗层 → 特征层"五层组织，所有文件均可由流水线重新生成。
仓库默认只保留目录结构与说明，数据文件被 `.gitignore` 排除。

## 目录结构

```
DATA_RAW_Download/               # 落地区（项目根，只读、不入库）
│   ├─ 资产负债表233415143.../FS_Combas.csv    # CSMAR 原始包，保持原目录名与分片
│   ├─ 偿债能力201517087/FI_T1.csv            # 待入库：官方偿债能力比率（586,759 行）
│   ├─ 现金流量表(间接法)201255152/FS_Comscfi.csv  # 待入库：折旧/摊销官方口径（327,535 行）
│   ├─ 年个股回报率文件200943101/TRD_Year.csv  # 待入库：年回报率/市值（60,366 行）
│   └─ 公司文件222913114/SPT_Company.csv      # 抽样 526 家，不建议入模
data/
├── incoming/csmar/              # 暂存区：规范化命名，供导入层读取
│   ├── raw/                     #   FS_Combas.csv、LA_DETAIL.csv… + _manifest_raw_download.json
│   ├── desc/                    #   CSMAR 字段说明 *[DES]*.txt
│   ├── 20261114/                #   分批次归档（TRD_Dly 分段合并等）
│   └── download_log.md          #   下载日志（表名/筛选/年份/行数/备注）
├── raw/                         # 契约层：ETL 唯一读取入口
│   ├── FS_Combas.csv            资产负债表原始导出（科目代码 A001000000…）
│   ├── FS_Comins.csv            利润表原始导出
│   ├── FS_Comscfd.xlsx          现金流量表原始导出（XLSX，需先转换）
│   ├── basic_info.csv           上市公司基本信息年度表
│   ├── AUD_opinion.csv          审计意见表
│   ├── TOP10_holders_A/B/C.csv  十大股东（CSMAR 单次导出 100 万行上限，分三批）
│   ├── CG_manager.csv           高管人数、持股及薪酬
│   ├── csmar_financial.csv      ← 三分表 + 官方折旧（FS_Comscfi）+ 带息债务口径（亿元）
│   ├── csmar_governance.csv     ← 十大股东 + 高管表 + 两职合一（duality 已并入）
│   ├── market_features_trd.csv  ← 审计 + TRD 行情（换手率小数倍数；含覆盖标记）
│   ├── ST_events.csv            ← CSMAR SPT_Trdchg 官方 ST 事件区间
│   ├── labels_st.csv            ← 官方 0/1 ST 标签（48,290 个 A 股公司-年，1,897 正）
│   ├── text_sentiment.csv       年报 MD&A 文本特征（词典基线 lexicon_cn_v1，2001–2024）
│   ├── legal_events.csv         诉讼/处罚（CSMAR 诉讼仲裁 + 违规总表，2013–2026）
│   ├── digital_features.csv     数字化转型词频（2007–2025，未入选最终模型）
│   └── candidates/              已验证但未激活的候选增量（见下）
├── cleaned/panel_clean.parquet  清洗后的公司-年面板（35,618 行，2013–2025）
├── feature_store/
│   ├── panel_features.parquet   80 维全量特征面板（22,814 行，2015–2023）
│   ├── panel_model_input.parquet 建模输入（ID + 标签 + 36 维入选特征）
│   ├── selected_features.json   四步筛选后的特征清单（36 维）
│   └── feature_selection_report.csv 特征筛选证据链
├── external/
│   ├── macro_industry.csv       宏观与行业指标（2013–2025，社融已补）
│   ├── social_financing_pbc.csv 央行社融存量同比来源表（含发布日期与口径）
│   └── macro_industry.demo.csv  演示值，**不参与真实建模**
├── versioned/                   激活/重跑时的版本快照
├── demo_raw/                    演示数据备份（与真实数据物理隔离）
└── gen_demo_data.py
```

> 旧版 `panel_model_input.csv` / `panel_features.csv`（33,191 行）已归档到 `feature_store/_stale/`，
> 当前特征层只保留固定四件套（两个 parquet + `selected_features.json` + `feature_selection_report.csv`）。
> 版本快照策略见 [`versioned/README.md`](./versioned/README.md)。

## 候选增量与激活记录（2026-11-14）

`data/raw/candidates/` 存放本轮新增的已验证候选表，**激活前不替换** `data/raw/` 下的在线契约。

| 文件 | 行 × 列 | 内容 | 状态 |
|---|---:|---|---|
| `ST_events_official.csv` | 1,539 × 11 | 官方 ST/*ST 区间（1998–2026） | 已激活到 `ST_events.csv` |
| `labels_st_official.csv` | 48,290 × 4 | 官方标签 2013–2025，1,897 正（3.93%） | 已激活到 `labels_st.csv` |
| `CG_duality_2013_2025.csv` | 51,907 × 12 | 两职合一原始字段 | 已合并（`duality` 非空 97%+） |
| `governance_ext.csv` | 51,907 × 11 | 治理增量契约；比例已转小数 | 已合并 `csmar_governance.csv` |
| `legal_events.csv` | 49,393 × 11 | 诉讼/处罚公司-年；无事件补 0 | 已激活到 `legal_events.csv` |
| `csmar_financial_cashflow_fixed.csv` | 52,203 × 40 | 现金流单次缩放修正版 | 已按 4 字段合并 |
| `depreciation_sina_annual.csv` | 65,690 × 6 | 年报折旧项（2013–2025，5,643 家） | 已被官方值替换（保留备查）；重叠相关 0.9988 |
| `depreciation_comscfi_annual.csv` | 55,244 × 5 | 官方间接法折旧/无形资产摊销/长期待摊摊销 | 已激活：`depreciation` 覆盖 99.94% |
| `market_annual.csv` | 52,025 × 6 | `TRD_Year` 年回报率、ln(总市值)、交易天数 | 仅消融候选，未入生产模型 |

**2026-11-14 口径修正**

1. `depreciation` ← `FS_Comscfi.D000103000`（官方），`scripts.import_comscfi_official --write`；
2. `interest_debt` ← `非流动负债合计 + 短期借款 + 一年内到期非流动负债`（CSMAR 带息债务口径），
   `lt_debt` 用 `F011301A × 总资产` 回填，覆盖 56.94% → 100%，`scripts.fix_interest_debt --write`；
3. 新增列 `interest_debt_imputed`（0=报表科目直取，1=官方比率兜底），契约表由 40 列变 41 列。

- 每个文件都有 SHA256/来源/未替换声明，见 `candidates/manifest.json`。
- 校验：`python -m scripts.validate_candidates`，结果 `reports/data_quality/candidate_validation_20261114.json`。
- 激活顺序：显式合并 → 重跑 `etl.run_pipeline` → 重训/重校准 → 版本化；不要只替换 raw 表而沿用旧特征/旧模型。

> **口径已统一**：现金流字段级修正；诉讼按 `DeclareDate` 年 + `EventID` 去重；TRD 换手率统一小数倍数；文本/司法/数字化/行情均保留 availability 标记。

## 真实数据接入流程（CSMAR）

```bash
# 0) 原始包解压到 DATA_RAW_Download/（保持原始目录名），在 download_log.md 追加一行
# 1) 落地区 → 暂存区：规范命名 + 分片拼接 + manifest（默认预演）
python -m scripts.sync_raw_download
python -m scripts.sync_raw_download --write

# 2) 现金流量表 XLSX → 精简 CSV（约 7 分钟，一次性）
python -m scripts.convert_csmar_xlsx
# 3) 科目代码解码 + 三表合并 + 治理/审计映射 → 写入契约表
python -m etl.csmar_import --step all --write

# 4) 质量体检 + 训练就绪体检（BLOCK 时退出码 1）
python -m scripts.validate_raw_data
python -m scripts.check_data_readiness

# 5) 特征工程 + 四步筛选（需 ST 标签表）
python -m etl.run_pipeline
```

当前进度与缺口见 [`docs/数据缺口与补齐清单_20261114.md`](../docs/数据缺口与补齐清单_20261114.md)，
目录与清洗规则见 [`docs/数据治理与目录规范.md`](../docs/数据治理与目录规范.md)。

## 三层数据契约

| 层 | 粒度 | 主键 | 生成方式 |
|----|------|------|---------|
| raw | 单表原始记录 | `stock_code + year` | CSMAR 导出 / `sync_raw_download` + `csmar_import` |
| cleaned | 公司-年面板 | `stock_code + year` | `etl.clean_financial`（去重、三级插补、样本剔除） |
| feature_store | 建模宽表 | `stock_code + year` | `etl.feature_engineering` + `etl.feature_selection` |

## 字段与单位约定

- 金额单位统一为**亿元**，比率类为小数（0.35 表示 35%）；
- 比率特征经 1%/99% 分位缩尾，缩尾边界**只用训练窗口**估计；
- 特征口径的唯一事实来源是 `config/feature_registry.py`（80 维）；
- 标签口径：**T 年 ST 状态**，特征取 **T-2 年**，避免前视偏差；
- `*_available` 标记区分"真实缺失"与"业务 0 值"，入模前不得删除。

## 如何替换为真实数据

1. 把下载包放入 `DATA_RAW_Download/`，先 `python -m scripts.sync_raw_download` 预演；
2. 若导出文件已是合约列名的合并表（而非 CSMAR 原始分表），改用通用映射层：
   ```bash
   python -m etl.mapping --list
   python -m etl.mapping --source D:\csmar\export --table financial --dry-run
   python -m etl.mapping --source D:\csmar\export --write
   ```
3. 运行 `python -m scripts.validate_raw_data` 与 `python -m scripts.check_data_readiness`，确认无 BLOCK；
4. 确认 `stock_code` 为 6 位字符串（如 `000001`）、`year` 为整数；
5. 运行 `python -m etl.run_pipeline`（**不要**加 `--refresh`，避免覆盖真实数据）；
6. 其余流程（特征筛选、训练、解释、看板）完全不变。

> 单位约定：`data/mapping/csmar.yaml` 默认 CSMAR 金额为"元"，按 `1e-8` 转为"亿元"；
> 若导出已是亿元，请把对应列的 `scale` 改为 `1`。治理类持股比例默认按百分数导出（`0.01`），
> 若已是小数请同样改为 `1`。

> 提示：真实数据往往缺少部分字段，`build_panel` 会记录缺失特征并补 0，
> 同时打印告警；论文中应说明缺失字段及其对结论的影响。
