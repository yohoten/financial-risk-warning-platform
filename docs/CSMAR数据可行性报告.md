# CSMAR 数据可行性报告

| 项 | 内容 |
|----|------|
| 报告日期 | 2026-11-11 |
| 数据来源 | CSMAR 镜像站（手动下载，`F:\（8）Desktop\CSMAR_download_links\pakage`） |
| 数据落地 | `data/raw/`（按 `docs/CSMAR手动下载清单.md` 重命名） |
| 校验脚本 | `python -m scripts.validate_raw_data` |
| 关联文档 | [CSMAR手动下载清单](./CSMAR手动下载清单.md) · [数据字典](./数据字典与特征口径.md) |

---

## 一、结论摘要

| 维度 | 状态 | 说明 |
|------|------|------|
| 财务主表（资产负债表/利润表/现金流量表） | ✅ 可用 | 52,203 行、5,643 家公司、2013–2025，勾稽错误率 0.02% |
| 公司治理（十大股东 + 高管持股） | ✅ 可用 | 52,560 行，覆盖财务主表 94.85% |
| 审计意见 / 审计费用 / 四大识别 | ✅ 可用 | 非标意见 4.55%，四大占比 6.90%，审计费用中位数 100 万元 |
| 公司基本信息（行业/上市日期/简称） | ✅ 可用 | 60,403 行，91 个行业代码，行业缺失已按公司前后向填充 |
| **ST 标签（P0）** | ❌ **阻断** | 未下载「特别处理表」，`is_st` 无法生成，**模型无法训练** |
| 扣非净利润 / 有息负债（财务指标分析表） | ❌ 缺失 | 影响 `deducted_profit_ratio` 等 2 个特征 |
| 董事会治理（两职合一） | ❌ 缺失 | `duality` 全空 |
| 诉讼/处罚 | ❌ 缺失 | 司法维度 2 个特征为空 |
| 年个股回报率 / 日行情 | ❌ 缺失 | 换手率、波动率 2 个特征为空 |
| 宏观指标 | ❌ 缺失 | 现有 `macro_industry.demo.csv` 为演示值，**不得用于论文** |
| 年报文本 MD&A | ❌ 缺失 | 文本情感 6 个特征为空 |

> **一句话结论**：财务、治理、审计三块已可支撑 **52/73 维**特征（另有 4 维为代理口径）；但 **ST 标签缺失导致全链路在「标签对齐」处阻断**，补齐 P0 的《特别处理表》后即可跑通真实数据训练。

---

## 二、已到数据清单

复制位置：`data/raw/`；原始包保留在 `F:\（8）Desktop\CSMAR_download_links\pakage`（未删除）。

| # | 原始文件 | 重命名后 | 大小 | 行数（含表头） | 清单编号 |
|---|---------|---------|------|--------------|---------|
| 1 | `STK_LISTEDCOINFOANL.csv` | `basic_info.csv` | 113 MB | 336,492 | P0-1 |
| 2 | `FS_Combas.csv` | `FS_Combas.csv` | 641 MB | 650,338 | P0-2 |
| 3 | `FS_Comins.csv` | `FS_Comins.csv` | 316 MB | 567,799 | P0-3 |
| 4 | `FS_Comscfd.xlsx` | `FS_Comscfd.xlsx` | 199 MB | 567,747 | P0-4 |
| 5 | 现金流量表（转换产物） | `data/incoming/csmar/FS_Comscfd_filtered.csv` | 4.7 MB | 55,244 | — |
| 6 | `FIN_Audit.csv` | `AUD_opinion.csv` | 67 MB | 530,769 | P1-7 |
| 7 | `HLD_Shareholders.csv` | `TOP10_holders_A.csv` | 196 MB | 1,000,001 | P1-8 |
| 8 | `HLD_Shareholders1.csv` | `TOP10_holders_B.csv` | 197 MB | 1,000,001 | P1-8 |
| 9 | `HLD_Shareholders2.csv` | `TOP10_holders_C.csv` | 33 MB | 161,654 | P1-8 |
| 10 | `CG_ManagerShareSalary.csv` | `CG_manager.csv` | 33 MB | 119,086 | P1-9 |

**说明**：

- 十大股东单文件恰好 1,000,000 行数据，是 CSMAR 单次导出上限，A/B/C 三批为**同表分批**，导入时按 `Stkcd + Reptdt` 合并；
- 现金流量表仅提供 XLSX，已用 `scripts/convert_csmar_xlsx.py` 流式转换为精简 CSV（只保留 4 个现金流科目）；
- 表头说明文件（`*[DES][csv].txt`）保留在原始包中，未复制进仓库（体积小但无运行价值）。

---

## 三、可行性验证

### 3.1 三表合并结果

| 指标 | 数值 | 判断 |
|------|------|------|
| 公司-年记录 | 52,203 | 与 A 股 2013–2025 实际规模一致（2013 年 2,434 家 → 2025 年 5,357 家） |
| 公司数 | 5,643 | 覆盖全部 A 股（含退市样本） |
| 年份范围 | 2013–2025 | 满足建模窗口 2015–2024，且留出 2 年标签前瞻 |
| 制造业（C）占比 | 68.2%（4,124 家） | 与"制造业为主"的论文样本设定吻合，可直接筛 C |
| 行业代码数 | 91 | 证监会 2012 版门类+大类，可用于行业固定效应 |

年度分布：

| 年份 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 公司-年 | 2,434 | 2,597 | 2,883 | 3,212 | 3,592 | 3,683 | 3,877 | 4,327 | 4,754 | 5,026 | 5,199 | 5,262 | 5,357 |

### 3.2 勾稽与合理性检查

| 检查 | 结果 | 说明 |
|------|------|------|
| 资产 = 负债 + 权益 | 50,994 / 51,003 通过（99.98%） | 9 行差额来自追溯调整与少数股东权益口径 |
| 负债率 > 105% | 242 行 | 真实存在的资不抵债公司，保留（正是预警对象） |
| 单位换算 | 元 → 亿元 | 总资产中位数 33.14 亿元，最大 3.56 万亿元，量级正确 |
| 审计意见分布 | 非标 4.55% | 与既有文献的 4%–6% 一致 |
| 四大占比 | 6.90% | 与 A 股实际情况一致（约 6%–10%） |
| 审计费用 | 中位数 100 万元 | 量级合理 |
| 第一大股东持股 | 均值 33.0% | 与"一股独大"的 A 股特征一致 |
| 董事会规模 | 均值 8.37 人 | 与《公司法》5–19 人要求一致 |
| 管理层持股 | 均值 8.54%（非空 96.7%） | 合理 |

### 3.3 跨表覆盖

| 表 | 与财务主表主键覆盖率 |
|---|---|
| `csmar_governance.csv` | 94.85% |
| `market_features.csv` | 94.85% |
| `labels_st.csv` | 0%（文件缺失） |

覆盖率未达 100% 的原因：财务表含 2013 年部分公司（治理/审计表当年未收录），以及少量只有利润表无资产负债表的样本。ETL 的插补会处理，论文中应说明匹配率。

### 3.4 全链路演练（用占位标签验证 ETL 是否真的跑得通）

ST 标签缺失，但不影响验证"除标签外"的链路。用 `is_st=0` 的占位标签跑一遍：

```python
fin = pd.read_csv("data/raw/csmar_financial.csv", dtype={"stock_code": str})
fake = fin[["stock_code", "year"]].drop_duplicates().assign(is_st=0)
panel = add_features(build_base_panel(labels=fake))
```

| 指标 | 结果 |
|------|------|
| 清洗面板 | 52,203 行 × 64 列（5,643 家公司，2013–2025） |
| 缺失插补 | 15.14% → 8.11%（公司内插值 → 行业-年度中位数） |
| 特征面板 | 36,046 行 × 73 维（2015–2023，2024 因无 2026 标签被截断） |
| 有真实数值特征 | 52 维 |
| 全零特征 | 21 维（与缺失表一一对应） |
| 运行耗时 | 约 45 秒（含三次大表读盘） |

**结论**：ETL 在真实数据上无代码级故障，缺的只是数据本身。补齐 ST 表后，`etl.run_pipeline` 可直接产出可训练的建模输入表。

---

## 四、字段级可用性矩阵

图例：✅ 直接可用 ｜ ⚠️ 代理指标 ｜ ❌ 缺失（需补表）

| 维度 | 字段 | 状态 | 来源 / 处理 |
|------|------|------|------------|
| 偿债 | total_assets / total_liabilities / equity / current_assets / current_lia | ✅ | 资产负债表 |
| 偿债 | short_borrow / lt_debt / bonds_payable / current_lt_debt | ✅ | 资产负债表（长期借款缺失率 40%，多为无长期借款企业） |
| 偿债 | interest_debt | ⚠️ | 短借+长借+应付债券+一年内到期非流动负债（代理） |
| 偿债 | interest_expense | ✅ | 利润表「其中：利息费用」，缺失用财务费用代理 |
| 盈利 | revenue / cost / net_profit / net_profit_parent / ebit | ✅ | 利润表（ebit 用利润总额代理，需在论文注明） |
| 盈利 | opex | ✅ | 销售费用+管理费用+财务费用（三项均在利润表） |
| 盈利 | rd_expense | ✅ | 研发费用（2018 年起科目，缺失率 32%，符合制度变迁） |
| 盈利 | deducted_profit | ❌ | 需《财务指标分析》表 |
| 盈利 | eps | ⚠️ | 净利润 / 实收资本（近似总股本） |
| 营运 | inventory / receivables / payable / fixed_assets | ✅ | 资产负债表 |
| 成长 | revenue / total_assets / equity / ocf / rd 的同比 | ✅ | 由主表计算 |
| 现金流 | ocf / icf / fcf_financing / capex | ✅ | 现金流量表（直接法） |
| 现金流 | depreciation | ❌ | 需现金流量表**补充资料（间接法）** |
| 文本 | mdna_positive / negative / uncertainty / polarity / volatility / forward_looking | ❌ | 需年报文本或 MD&A 文本库 |
| 治理 | top1_holding / top2_5_holding / institutional_holding | ✅ | 十大股东（比例字段 /100） |
| 治理 | board_size / independent_directors | ✅ | 高管人数表（DirectorNumber / IndependentDirectorNumber） |
| 治理 | management_holding | ⚠️ | 高管持股数 / 十大股东反推总股本 |
| 治理 | duality（两职合一） | ❌ | 需《董事会治理》表 |
| 治理 | big4_audit | ✅ | 审计意见表「境内审计机构」关键词匹配 |
| 审计 | audit_opinion | ✅ | 审计意见类型 → 0/1 |
| 审计 | audit_fee | ✅ | 合计审计费用（元→亿元） |
| 市场 | annual_turnover / stock_volatility | ❌ | 需《年个股回报率》/ 日行情 |
| 司法 | litigation_count / penalty_count | ❌ | 需《诉讼仲裁》/《违规处罚》 |
| 宏观 | gdp / m2 / cpi / ppi / 社融 / pmi | ❌ | 需国家统计局或 CSMAR 宏观库 |
| 标签 | is_st | ❌ | **需《特别处理表》（ST 事件表）** |

**可用特征实测**（以占位标签跑通全链路后统计，见 §3.4）：

| 类别 | 维数 | 说明 |
|------|-----|------|
| 有真实数值 | **52** | 含 4 个代理口径（interest_debt / interest_expense / eps / management_holding） |
| 因缺表而全零 | **21** | 文本 6、宏观 6、司法 2、市场 2、扣非 1、两职合一 1、折旧相关 3 |

全零特征清单：`lt_debt_to_ebitda`、`ebitda_margin`、`capex_to_depreciation`（缺折旧）、
`deducted_profit_ratio`（缺扣非）、`mdna_*`×3 + `sentiment_*`×2 + `forward_looking_ratio`（缺文本）、
`duality`（缺董事会治理）、`annual_turnover`、`stock_volatility`（缺行情）、
`litigation_count`、`penalty_count`（缺诉讼处罚）、`gdp_growth`、`m2_growth`、`cpi_yoy`、`ppi_yoy`、
`social_financing_growth`、`pmi_manufacturing`（缺宏观）。

---

## 五、缺失项与影响

| 优先级 | 缺失表 | 影响特征 | 影响程度 |
|--------|--------|---------|---------|
| **P0** | 特别处理表（ST 事件） | `is_st` 标签 | **致命：无法训练、无法评估** |
| P1 | 财务指标分析 | deducted_profit_ratio | 中：少 1 维盈利质量特征 |
| P1 | 董事会治理 | duality | 低：少 1 维治理特征 |
| P1 | 诉讼仲裁 / 违规处罚 | litigation_count / penalty_count | 中：司法维度缺失，削弱"非财务信息"卖点 |
| P2 | 年个股回报率 / 日行情 | annual_turnover / stock_volatility | 中：市场维度缺失 |
| P2 | 宏观数据库 | 6 个宏观特征 | 低：控制变量，可先用公开数据替代 |
| P2 | 年报文本 / MD&A | 6 个文本特征 | **高（对创新点）**：文本维度是差异化贡献，建议必补 |
| P2 | 现金流量表补充资料 | depreciation | 低：只影响 EBITDA 口径精度 |

---

## 六、下一步下载指引

登录地址（镜像站，需机构账号）：`https://csmarlsdx.keyanwangshuju.com/`

### 6.1 必下（P0，1 张表，10 分钟）

| 项 | 设置 |
|----|------|
| 表名 | 特别处理表 / ST 事件表（搜索"特别处理"） |
| 路径 | 数据中心 → 专题研究系列 → 特别处理 |
| 筛选 | 事件年份 2013-01-01 至 2026-12-31；A 股 |
| 字段 | 证券代码、证券简称、实施日期、特别处理类型、撤销日期、公告日期 |
| 导出名 | `data/raw/ST_events.csv` |
| 注意 | 要**事件表**而非年度状态快照；保留 2020 年退市新规前后的原始类型字段 |

下载后执行：

```bash
python -m etl.csmar_import --step labels --write
python -m scripts.validate_raw_data
python -m etl.run_pipeline          # 至此可跑通真实数据全链路
```

### 6.2 强烈建议（P1，3 张表）

| 表 | 导出名 | 关键字段 |
|----|-------|---------|
| 财务指标分析 | `FI_indicators.csv` | 扣非净利润、有息负债、总股本、ROA、ROE |
| 董事会治理 | `CG_board.csv` | 董事会人数、独立董事人数、两职合一、管理层持股比例 |
| 诉讼仲裁 + 违规处罚 | `LAW_lawsuit.csv`、`VIO_penalty.csv` | 证券代码、公告日期、案件/处罚类型、涉案金额 |

### 6.3 增强项（P2）

| 表 | 导出名 | 用途 |
|----|-------|------|
| 年个股回报率 | `TRD_year.csv` | 年换手率 |
| 日行情 | `TRD_daily.csv` | 年化波动率 |
| 宏观经济 | `data/external/macro_industry.csv` | 6 个宏观控制变量（也可用国家统计局公开数据） |
| 年报文本 / MD&A | `MDNA_text.csv` | 文本情感 6 维（**创新点，建议必补**） |
| 现金流量表补充资料（间接法） | `FS_Comscfi.csv` | 折旧摊销 |

> 导出统一要求：**合并报表（Typrep=A）+ 年报（12-31）+ 金额单位元**；单表超 100 万行按年份拆 A/B 批。

---

## 七、已知问题与处理

| 问题 | 处理方式 |
|------|---------|
| 现金流量表为 XLSX 且 `dimension` 只声明 1 列 | `scripts/convert_csmar_xlsx.py` 中 `reset_dimensions()` 后流式读取 |
| 该 XLSX 表头占 3 行（代码/中文名/单位） | 跳过 2 行、以第 1 行为字段名 |
| 审计意见表 222 行字段内逗号未转义（ragged） | 用 `csv` 逐行容错解析，坏行跳过并计数 |
| 十大股东单文件 100 万行上限 | 三批合并，按 `Stkcd + Reptdt` 去重 |
| 审计机构误用签字会计师字段 | 改用 `Dadtunit`（境内所）/`Iadtunit`，四大占比由 0% 修正为 6.90% |
| 行业代码在部分年份缺失 | 按公司前后向填充，仍缺失记为 `UNKNOWN` |
| 2013 年样本偏少 | 属正常（当年上市公司数量少），论文可做 2015 年起样本 |
| 2025 年年报不完整 | 建模窗口仍为 2015–2024，2025 仅用于最新一期预警 |
| 演示数据残留 | 已迁移至 `data/demo_raw/`；宏观演示值改名为 `macro_industry.demo.csv`，**不参与真实建模** |

---

## 八、命令速查

```bash
# 1. 原始包 → data/raw（已完成，重新执行亦安全）
python -m etl.csmar_import --step all --write

# 2. 超大 XLSX → 精简 CSV（约 7 分钟）
python -m scripts.convert_csmar_xlsx

# 3. 数据质量体检
python -m scripts.validate_raw_data     # 报告：reports/data_quality/

# 4. 补齐 ST 表后
python -m etl.csmar_import --step labels --write
python -m etl.run_pipeline
```

---

## 九、修订记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-11-11 | v1.0 | 首次接入 10 个原始导出文件；三表合并与治理/审计映射完成；确认 ST 标签为唯一阻断项 |
