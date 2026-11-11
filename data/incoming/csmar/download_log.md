# CSMAR 下载日志

> 范本见 `docs/CSMAR手动下载清单.md` §0.3。每次下载后追加一行，便于回溯"哪些数据、什么口径、多少行"。
> 镜像站：`https://csmarlsdx.keyanwangshuju.com/`（机构账号登录）

| 表名 | 筛选条件 | 年份范围 | 行数 | 下载时间 | 备注 |
|---|---|---|---|---|---|
| 上市公司基本信息年度表 | A 股 / 年度 | 2001–2025 | 305,976 数据行 | 2026-11-11 | 源文件 `STK_LISTEDCOINFOANL.csv` → `data/raw/basic_info.csv`（41 列） |
| 资产负债表 FS_Combas | 合并+母公司，未筛年份 | 2001–2025 | 650,337 数据行 | 2026-11-11 | 导入时筛 Typrep=A 且 Accper=12-31 → 54,017 行 |
| 利润表 FS_Comins | 同上 | 2010–2025 | 567,798 数据行 | 2026-11-11 | 导入后 55,247 行（含少数只有利润表的样本） |
| 现金流量表（直接法）FS_Comscfd | 同上，XLSX | 2010–2025 | 567,744 数据行 | 2026-11-11 | XLSX 表头 3 行、dimension 声明有误；转换后 55,244 行 |
| 审计意见表 FIN_Audit | 年报 | 2010–2025 | 530,768 数据行 | 2026-11-11 | 222 行字段内逗号未转义，导入时跳过 |
| 十大股东 HLD_Shareholders | 年度，A 股 | 2013–2025 | 1,000,000 + 1,000,000 + 161,653 | 2026-11-11 | 单文件 100 万行上限，分 A/B/C 三批 |
| 高管人数、持股及薪酬 CG_ManagerShareSalary | 年度 | 2010–2025 | 119,085 数据行 | 2026-11-11 | 用于 board_size / independent_directors / management_holding |

## 待下载（按优先级）

| 表名 | 目标文件名 | 优先级 | 阻断影响 |
|---|---|---|---|
| 特别处理表（ST 事件） | `ST_events.csv` | **P0** | 无 `is_st` 标签，无法训练 |
| 财务指标分析 | `FI_indicators.csv` | P1 | 扣非净利润、有息负债缺失 |
| 董事会治理 | `CG_board.csv` | P1 | 两职合一缺失 |
| 诉讼仲裁 / 违规处罚 | `LAW_lawsuit.csv` / `VIO_penalty.csv` | P1 | 司法维度缺失 |
| 年个股回报率 / 日行情 | `TRD_year.csv` / `TRD_daily.csv` | P2 | 换手率、波动率缺失 |
| 宏观经济 | `data/external/macro_industry.csv` | P2 | 宏观控制变量缺失 |
| 年报文本 / MD&A | `MDNA_text.csv` | P2 | 文本情感 6 维缺失（创新点） |
| 现金流量表补充资料 | `FS_Comscfi.csv` | P2 | 折旧摊销缺失 |
