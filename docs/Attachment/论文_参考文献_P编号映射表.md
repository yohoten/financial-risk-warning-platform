# 论文参考文献 · P 编号映射表

> | 元信息 | 值 |
> |---|---|
> | 状态 | ✅ 生效（v1.0） |
> | 版本 | v1.0 |
> | 日期 | 2026-11-19 |
> | 用途 | 在**本地 PDF 编号（P）**、**论文引用编号（[n]）**与**综述证据分级（A/B/C）**三者之间提供双向可检索的映射 |
> | 权威来源 | P 编号来自 `docs/literature/papers/` 的文件命名；[n] 来自 [《论文_参考文献》](./论文_参考文献.md)；证据分级来自 [《文献综述与理论奠基》](./上市公司财务风险预警_文献综述与理论奠基.md) §附录 A |

---

## 0. 为什么需要这张表

项目内存在**三套并行的文献标识**：

| 标识体系 | 载体 | 用途 |
|---|---|---|
| `P01`–`P33` | `docs/literature/papers/` 文件名前缀 | 标识本地 PDF 原文 |
| `[1]`–`[37]` | 论文正文与《论文_参考文献》 | 标识论文引用 |
| `A` / `B` / `C` | 综述底稿 §附录 A | 标识证据强度（可核性 + 同行评议） |

此前三者之间**没有公开对照表**，导致「某条综述结论引用了哪篇原文」「某篇 PDF 对应论文哪一条」需要人工反查。本表一次性固化。

---

## 1. 完整映射表

| P 编号 | 论文编号 | 证据等级 | 本地文件 | 核心著录信息 | 本地核实状态 |
|:---:|:---:|:---:|---|---|---|
| P01 | [36] | — | `P01_基于Z-Score指标决策树的财务风险预警.pdf` | 杨蕴毅, 孙中和, 卢靖. 现代管理, 2017, 7(5): 185-193 | ✅ 2026-11-19 核（DOI 10.12677/mm.2017.75026） |
| P02 | [35] | — | `P02_大数据驱动企业财务风险预警的有效性研究.pdf` | 李岩, 云立新. 运筹与模糊学, 2025, 15(3): 140-145 | ✅ 2026-11-19 核（DOI 10.12677/orf.2025.153147） |
| P03 | [1] | A | `P03_Financial Ratios As Predictors of Failure _ JSTOR.pdf` | Beaver. Journal of Accounting Research, 1966, 4: 71-111 | ⚠️ 仅 1 页预览，全文未核 |
| P04 | [15] | A | `P04_Aggregate Confusion——The Divergence of ESG Ratings.pdf` | Berg et al. Review of Finance, 2022, 26(6): 1315-1344 | ✅ 出版版（两份重复已去重） |
| P05 | [37] | — | `P05_大数据背景下中小企业财务风险预警体系构建.pdf` | 郭本默. 社会文化与经济, 2025(11): 29-31 | ⚠️ 期刊名据 PDF 页脚，建议再核 |
| P06 | [16] | A | `P06_Why Is Corporate Virtue in the Eye of the Beholder.pdf` | Christensen et al. The Accounting Review, 2022, 97(1): 147-175 | ⚠️ 本地为 HBS WP 20-084，出版信息经外部核对 |
| P07 | [29] | B | `P07_Explainable Machine Learning Models of Consumer Credit Risk∗.pdf` | Davis et al. Journal of Financial Data Science, 2023, 5(4): 9-39 | ⚠️ 本地为 SSRN WP（2022-01-12），出版信息经作者主页核对 |
| P08 | [17] | A | `P08_Natural_Language_Processing_and_Deep_Learning_for_Bankruptcy_Prediction....pdf` | Lombardo et al. IEEE Access, 2024, 12: 151075-151091 | ✅ 出版版（页码按起始页与页数推算） |
| P09 | [30] | B | `P09_Financial Distress Prediction for Small and Medium Enterprises Using Machine.pdf` | Gao et al. arXiv:2302.12118, 2023 | ⚠️ 无同行评议 |
| P10 | [33] | — | `P10_财务困境预警：概念界定与理论辨析-中国社会科学院工业经济研究所.pdf` | 张金昌, 王大伟. 财经论丛, 2020(12) | ⚠️ 本地为公众号转载页 |
| P11 | [34] | — | `P11_系统性风险与企业财务危机预警——基于前沿机器学习的新视角.pdf` | 杨子晖, 张平淼, 林师涵. 金融研究, 2022(8): 152- | ⚠️ 起始页已核，止页待补 |
| P17 | [31] | B | `P17_Financial Sentiment Analysis on News and Reports Using Large Language Models.pdf` | Shen & Zhang. arXiv:2410.01987, 2024 | ⚠️ 无同行评议 |
| P18 | [4] | A | `P18_Methodological Issues Related to the Estimation of Financial Distress Pr....pdf` | Zmijewski. Journal of Accounting Research, 1984, 22: 59-82 | ✅ 出版版 |
| P19 | [20] | A | `P19_ESG评级分歧对企业绿色创新效率的影响研究.pdf` | 李季鹏, 李叶. 工业技术经济, 2024(10) | ⚠️ 页码未提取（竖排版式） |
| P20 | [21] | A | `P20_企业数字化转型的测度难题：基于大语言模型的新方法与新发现.pdf` | 金星晔等. 经济研究, 2024(3) | ✅ 期刊排版 PDF |
| P21 | [22] | A | `P21_企业包容性创新的测度：基于大语言模型的新方法.pdf` | 梁宇奇等. 科学决策, 2024(12): 86-99 | ✅（页码按起始页与页数推算） |
| P22 | [23] | A | `P22_基于多期超额收益法评估数据资产价值——以A企业为例.pdf` | 杨洋, 宋良荣. 运筹与模糊学, 2025, 15(3): 422-429 | ✅ |
| P23 | [24] | A | `P23_基于lightGBM算法的信息技术类上市公司财务危机预测研究.pdf` | 路优. 电子商务评论, 2025, 14(3): 1254-1263 | ✅ |
| P24 | [25] | A | `P24_基于XGBoost算法的财务造假识别研究.pdf` | 王圣洁. 山东理工大学学报(自然科学版), 2022, 36(6): 74-79 | ✅ |
| P25 | [19] | A | `P25_ESG评级分歧与债务资本成本.pdf` | 张云齐等. 金融评论, 2023(4): 22-43, 124 | ✅（页码经外部核对） |
| P26 | [26] | A | `P26_ESG表现与企业财务绩效——融资约束、数字化转型的中介效应研究.pdf` | 成佳敏. 电子商务评论, 2025, 14(1): 2556-2570 | ✅ 2026-11-19 核（DOI 10.12677/ecl.2025.141320） |
| P27 | [7] | A | `P27_XGBoost_ A Scalable Tree Boosting System.pdf`（英文原版）<br>`P27_..._1_13_translate_20261113235906-中译.pdf`（中译） | Chen & Guestrin. KDD, 2016: 785-794 | ✅ 会议 PDF；**中译本与原版去重后计 1 篇** |
| P28 | [14] | A | `P28_Optuna_ A Next-generation Hyperparameter Optimization Framework.pdf` | Akiba et al. KDD, 2019: 2623-2631 | ✅ 预印本 PDF |
| P29 | [32] | A | `P29_Bankruptcy Prediction Using Machine Learning and Data Preprocessing Techniques.pdf` | Samara & Shinde. Analytics, 2025, 4(3): 22 | ✅ 2026-11-19 核（DOI 10.3390/analytics4030022） |
| P30 | [27] | A | `P30_Fardapaper-Bankruptcy-prediction-using-imaged-financial-ratios-and-convolutional-neural-networks.pdf` | Hosaka. Expert Systems with Applications, 2019, 117: 287-299 | ⚠️ 本地为 2018 接受稿（DOI 10.1016/j.eswa.2018.09.039）；出版卷页依 DOI 记录 |
| P31 | [5] / [28] | A | `P31_我国上市公司财务困境的预测模型研究_吴世农.pdf` | 吴世农, 卢贤义. 经济研究, 2001(6) | ⚠️ 页码未提取；**与 [5] 为同一条目，需合并**（见《论文_参考文献》§四） |
| P32 | [18] | A | `P32_On the pricing of corporate debt：The risk structure of interest rates.pdf` | Merton. The Journal of Finance, 1974, 29(2): 449-470 | ✅ 1973 工作论文 PDF；出版信息为标准文献信息 |
| P33 | [13] | A | `P33_From Local Explanations to Global Understanding with...pdf` | Lundberg et al. Nature Machine Intelligence, 2020, 2(1): 56-67 | ✅ PMC 作者稿 |

---

## 2. 论文独有条目（本地无 PDF 原文）

以下条目在论文引用列表中存在，但本地 `papers/` 无对应原文（综述底稿 §10.4 已列为待补下载清单）：

| 论文编号 | 条目 | 说明 |
|:---:|---|---|
| [2] | Altman E I (1968). *The Journal of Finance*, 23(4): 589-609 | 经典基准，公开可得 |
| [3] | Ohlson J A (1980). *Journal of Accounting Research*, 18(1): 109-131 | 经典基准，公开可得 |
| [6] | Breiman L (2001). *Machine Learning*, 45(1): 5-32 | 随机森林原始文献 |
| [8] | Ke G, et al (2017). NeurIPS 30: 3146-3154 | LightGBM 原始文献 |
| [9] | Prokhorenkova L, et al (2018). NeurIPS 31: 6638-6648 | CatBoost 原始文献 |
| [10] | Loughran T, McDonald B (2011). *The Journal of Finance*, 66(1): 35-65 | 金融文本情感词典 |
| [11] | 姜付秀, 张敏, 陆正飞, 等 (2009). 经济研究 (1): 131-143 | 中文财务困境行为研究 |
| [12] | Lundberg S M, Lee S I (2017). NeurIPS 30: 4765-4774 | SHAP 原始文献 |

> 📌 引用这些条目时，**只能引用公认的方法学与结论，不得引用具体数值**（本地无原文可核）——这是综述底稿 §C.3 的第一条硬约束。

---

## 3. 编号体系说明

| 事项 | 说明 |
|---|---|
| **P12–P16 缺号** | 检索阶段预留但未获得有效原文，编号保留不回收，以免破坏既有引用 |
| **P27 双文件** | 英文原版 + 中译本；中译本为项目自译（文件名含 `translate_20261113235906`），**著录以英文原版为准**，中译本不单独计数 |
| **文件数 vs 文献数** | `papers/` 下 **29 个 PDF 文件**，去重后对应 **28 个 P 编号**、**27 篇唯一文献**（P27 计入 1 篇） |
| **综述证据基础 23 篇** | 指综述底稿 §附录 A 实际建立了逐篇卡片并做了证据分级的 23 篇（P03–P33 中的 23 个编号）；P01/P02/P05/P10/P11 已下载但未建卡 |
| **论文参考文献 37 条** | v2.0 扩展后共 37 条，对应 **31 篇唯一文献**（27 篇本地可核 + 4 篇论文独有的经典方法文献；[11] 为中文原文未下载） |

---

## 4. 待办

| # | 待办 | 阶段 |
|---|---|---|
| 1 | 合并 [5] 与 [28]（同一条目），核对《经济研究》2001(6) 页码（通行著录 48-57） | P1 论文定稿 |
| 2 | 补齐 [20][21][33][34] 的中文期刊页码（CNKI 检索） | P1 |
| 3 | 为 P01/P02/P05/P10/P11 补做综述证据卡片，纳入 A/B/C 分级 | P1 |
| 4 | 下载 [2][3][6][8][9][10][11][12] 原文，使「凡引数字必可核」约束全覆盖 | P2 |
| 5 | 为 P10（财务困境概念界定）与 P11（系统性风险视角）在论文第 2 章确定引用位置 | P1 |

---

## 5. 相关

- [《论文_参考文献》](./论文_参考文献.md)——被映射的引用列表
- [《上市公司财务风险预警_文献综述与理论奠基》](./上市公司财务风险预警_文献综述与理论奠基.md)——证据分级与逐篇卡片
- [`docs/literature/文献与资料调研清单.md`](../literature/文献与资料调研清单.md)——49 项资源清单与检索策略
- [《开题报告_文献综述章节写作蓝图》](../design/开题报告_文献综述章节写作蓝图.md)——引用衔接规则