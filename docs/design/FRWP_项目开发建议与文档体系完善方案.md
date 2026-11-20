---
name: FRWP 项目开发建议与文档体系完善方案
overview: 对上市公司财务风险预警平台做全量代码—文档一致性诊断，产出一份《项目诊断与开发建议书》，并将文档体系重构为 docs/design + 全量索引 + 文档状态治理 + ADR/路线图/API契约/模型卡片/测试策略/Agent设计/证据冻结等 8 类新增设计文档，全程不改动任何 .py/.vue 源码。
todos:
  - id: audit-baseline
    content: 通读核对代码与全部文档，产出问题清单与证据基线，写入《项目诊断与开发建议书》第1-2章
    status: pending
  - id: rename-fixlinks
    content: git mv 改名 docs/design 与 docs/Attachment，修复全仓失效链接并删除重复综述文件
    status: pending
    dependencies:
      - audit-baseline
  - id: core-design-docs
    content: 新增开发路线图、ADR 十篇、API 契约、模型卡片、测试策略、证据冻结清单、文档规范
    status: pending
    dependencies:
      - audit-baseline
  - id: agent-mcp-doc
    content: 用 [subagent:code-explorer] 核实 agent/llm/mcp/plugins 实现细节，产出 LLM-Agent 与 MCP 设计说明
    status: pending
    dependencies:
      - audit-baseline
  - id: index-readme-refresh
    content: 重建 docs/README.md 四分区索引与状态标记，全面修订根 README 项目树、功能特性与开发计划
    status: pending
    dependencies:
      - rename-fixlinks
      - core-design-docs
  - id: references-expand
    content: 用 [skill:pdf] 核对 29 篇 PDF 著录信息，扩展论文参考文献至 23 篇并新增 P 编号映射表
    status: pending
    dependencies:
      - audit-baseline
  - id: verify-delivery
    content: 校验链接、索引、数字一致性与首页数据块，输出交付清单与遗留项说明
    status: pending
    dependencies:
      - index-readme-refresh
      - agent-mcp-doc
      - references-expand
---

## 用户需求

通读项目全部代码、文档与参考文献后，产出**项目开发建议与设计方案**，并**完善设计文档与项目文档**体系。

经澄清确认的交付边界（必须严格遵守）：

- **仅交付文档**：不改动任何 `.py` / `.vue` 源码，代码问题只写成建议与设计方案
- **执行目录治理**：把 `docs/design/` 改名为 `docs/design/` 并全局修正链接
- **新增 5 类设计文档**：开发路线图与里程碑、架构决策记录 ADR、API 契约 + 模型卡片 + 测试策略、LLM Agent 与 MCP 设计说明、证据冻结清单

## 核心交付内容

### 一、项目诊断与开发建议书（核心交付物）

- 五维基线盘点：数据（52,203 公司-年 → 22,814 行建模面板）、特征（80 维候选 → 36 维入选）、模型（五模型 + Optuna + TreeSHAP；2023 留出 AUC 0.8962 / PR-AUC 0.3986 / KS 0.6609 / Recall@Top10% 66.93% / ECE 0.0126）、平台（Streamlit + Vue3 SPA + FastAPI + Electron + Docker）、工程（115 项测试 + CI）
- 问题清单 11 项：每项含证据（文件:行）、严重度 P0/P1/P2、影响面、建议动作
- 5 阶段路线图与验收标准；明确「本轮不改代码」边界与遗留项

### 二、文档体系治理

- 目录改名与链接修复：`docs/design` → `docs/design`；`docs/附件` → `docs/Attachment`（使 README 现有 12 处论文链接生效）；修正 docs 根目录错位链接、`docs/literature/papers` 错写路径、模板目录错写路径；删除 1 份字节重复的综述 md
- `docs/README.md` 重建为四分区全量索引（设计 / 分析 / 文献 / 论文附件），每篇加**状态标记**（已实现 / 设计稿 / 分析结论 / 已废止 / 被取代）与「取代关系」
- 根 `README.md` 修订：项目结构树补齐 `api/` 全部子模块、功能特性补 LLM-Agent/MCP/插件/技能/分享/附件等模块、「九视图」校正为 12 视图、标注 `/predict/frame` 未实现、开发计划表更新、参考文献口径统一

### 三、新增设计文档（8 篇）

开发路线图与里程碑、ADR（10 条）、API 契约与接口参考、模型卡片与模型注册表规范、测试策略与覆盖矩阵、LLM-Agent 与 MCP 设计说明、证据冻结清单、文档编写与状态治理规范

### 四、参考文献口径统一

论文参考文献由 14 条扩展为覆盖综述底稿 23 篇证据基础（依 `docs/literature/papers/` 29 个 PDF 的 P 编号体系核对），并给出 P 编号 ↔ 论文编号映射表

## 视觉呈现

纯 Markdown 产出；沿用仓库既有规范（GB/T 7714-2015 中文 / APA 7th 英文、Mermaid 置于代码块、AUC/KS 4 位小数、金额统一亿元、UTF-8）；文档顶部统一元信息块（版本 / 日期 / 状态 / 取代关系 / 证据边界）。

## 交付形态与技术边界

本轮为纯文档工程：不引入新技术栈、不新增依赖、不改动 `.py` / `.vue` / `config/settings.py`。产出物为 Markdown；唯一非 Markdown 改动是 `index.html` 中 2 处链接文本（该文件仅 `HOMEPAGE-DATA:BEGIN/END` 之间由 `scripts/build_homepage.py` 注入数据块，文档链接为手工维护部分，改动须保持标记完整，否则 `python scripts/build_homepage.py --check` 失败）。

执行方式：`git mv` 做目录改名（保留文件历史），链接修正用精确替换，不做无关重构。

---

## 一、目录治理：改名与链接修复（P0）

### 1.1 改名动作

| 现状 | 目标 | 理由 |
| --- | --- | --- |
| `docs/design/` | `docs/design/` | 拼写错误，全仓 12 处引用（含 `config/settings.py:63`） |
| `docs/附件/` | `docs/Attachment/` | README 与 `docs/README.md` 共 12 处链接已按 `Attachment` 书写，论文交付包全部 404 |


`docs/附件/` 内含 5 个 docx + 2 个 xlsx 原始附件，**只改目录名、不动文件内容**。

### 1.2 链接修复清单（逐项落地，均有实测证据）

| 类型 | 位置 | 修复动作 |
| --- | --- | --- |
| `design` 引用 | `README.md`（483、679–684）、`docs/README.md`（8 处）、`index.html`（708–709）、`docs/literature/文献与资料调研清单.md`（5、121、143）、`docs/design/中期可行性分析与建议方案设计.md:105`、`docs/design/上市公司财务风险预警_文献综述与理论奠基.md:1204-1205`、`docs/design/上市公司财务风险智能预警平台_深度实施方案.md:1045` | 全部改为 `design` |
| `Attachment` 引用 | `README.md`（489、667、693–696、749）、`docs/README.md`（47–50） | 配合目录改名后自然生效 |
| docs 根目录错位 | `docs/README.md` 中 `CSMAR手动下载清单.md`、`CSMAR数据可行性报告.md`、`数据缺口与补齐清单_20261114.md`、`数据治理与目录规范.md`、`数据字典与特征口径.md`、`FastAPI服务层设计.md`、`平台功能与预测设计.md`、`前端架构与图表方案.md`、`训练评估口径与模型选择.md` | 分别改指 `./analysis/…` 与 `./design/…` |
| README 索引错位 | `README.md` 文档索引表中 `docs/CSMAR手动下载清单.md` 等 | 改指 `docs/analysis/…` / `docs/design/…` |
| 文献库路径 | `docs/literature/文献与资料调研清单.md`、`docs/design/中期可行性分析与建议方案设计.md:105` 的 `docs/literature/papers` | 改为 `docs/literature/papers` |
| 模板目录错写 | `docs/design/数据治理与目录规范.md:304` 的 `docs/附件3：毕业设计模板/*` | 改为 `docs/Attachment/…` 实际路径 |
| 分析文档路径 | `docs/design/中期可行性分析与建议方案设计.md:105` 的 `docs/analysis/ST标签补齐与数据可行性核验_20261111.md` | 改为 `docs/analysis/…` |
| 重复文件 | `docs/design/上市公司财务风险预警_文献综述与理论奠基.md` 与 `docs/Attachment/` 下同名文件（均 101849 字节，字节一致） | 保留 `docs/Attachment/` 一份（论文配套），删除 `docs/design/` 副本，design 侧自引改指 Attachment |


### 1.3 已知残留（本轮不动代码）

`config/settings.py:63` 定义 `DESIGN_DIR = DOCS_DIR / "design"`。全仓检索确认该常量**无任何引用点**（仅定义处 1 处命中），改名后不产生运行时破坏，但成为悬空常量。处置：在《项目诊断与开发建议书》中列为「需后续一行修复的残留项」并给出建议改法（`DOCS_DIR / "design"`）。

---

## 二、文档状态治理机制（解决「哪份是当前口径」）

### 2.1 状态标记语义（在 `docs/README.md` 新增「文档状态约定」章节定义）

| 标记 | 语义 | 典型文档 |
| --- | --- | --- |
| 已实现 | 与当前代码事实一致，可直接依赖 | 系统架构设计说明书、数据字典与特征口径 |
| 设计稿 | 方案已定稿，实现已完成或待补验收记录 | 平台优化设计方案（2026-11-17）、大屏平台开发设计方案 |
| 分析结论 | 某一时点的诊断结论，可能已被后续修复超越 | 中期可行性分析与建议方案设计（2026-11-13） |
| 被取代 | 已被更新口径取代，仅作历史留存 | 早期调研报告中的部分指标表 |
| 已废止 | 结论或路径已失效，禁止再引用 | 旧目录名 `docs/design` 相关旧链接写法 |


**关键标注规则**（避免误用）：

- 《中期可行性分析与建议方案设计》§0.3 的 5 项修复中 **4 项已落地**（二值 IV 修复 `etl/stats_utils.py:19-24`；按年分组扩展窗口 CV `models/train.py:113` 与 `cv_protocol=year_grouped_expanding`；2022/2023 切分；官方 ST 标签），**仅第 4 项「预处理泄漏」未落地** → 标注「🔄 部分被取代（4/5 已修复）」，禁止写成「中期报告问题已全部解决」
- 《平台优化设计方案》《大屏平台开发设计方案》标为「设计稿（实现已完成，待补验收记录）」，保留不删
- 中期报告内引用的 `docs/literature/papers` 等旧路径须同步修正，否则文档内部链接继续失效

### 2.2 索引结构

`docs/README.md` 重建为四分区全量索引：**① 研究设计**（`docs/design/` 16 篇 + 新增 8 篇）**② 数据与可行性分析**（`docs/analysis/` 7 篇）**③ 文献与资料**（`docs/literature/` 2 篇 + `papers/` 29 个 PDF）**④ 论文与附件**（`docs/Attachment/` 4 个 md + docx/xlsx 交付包）。每行含：文档名 / 一句话作用 / 状态标记 / 取代关系 / 建议阅读顺序。

---

## 三、新增设计文档设计（8 篇）

### 3.1 《项目诊断与开发建议书》（`docs/design/`）

五维基线（第 1 章，所有数字取自现有产物与代码）→ 11 项问题清单（第 2 章，表格化：编号 / 问题 / 证据文件:行 / 严重度 / 影响 / 建议动作 / 所属阶段）→ 5 阶段路线图（第 3 章）→ 边界声明（第 4 章：本轮不改代码、不重训、不改论文实测数字，待决代码项以 ADR 挂起）→ 遗留项清单（第 5 章，含 `config/settings.py:63`）。

### 3.2 《开发路线图与里程碑》

把 README 待办、中期报告 §0.4、优化设计方案 4 期路线收敛为 5 阶段：

- **P0 学术正确性与文档归一**（1 周）：预处理无泄漏化方案定稿（ADR-007/010）+ 文档改名与索引重建
- **P1 稳健性证据链**（1 月）：消融表（财务-only / +治理 / +审计）含 bootstrap CI、代理标签 vs 官方标签敏感性、全样本 vs 制造业对照、SHAP 加和一致性与排名稳定性、2024 锁箱声明；复用既有 `scripts/ablation_study.py`
- **P2 工程契约与可观测**（1–2 月）：OpenAPI 静态快照、模型卡片与轻量注册表、CI 增强（ruff / 前端 build / 文档链接检查 / 契约 diff）
- **P3 增量与运营**（季度）：在线增量更新、PSI 告警接入、大屏深化
- **P4 论文定稿**：证据冻结 → 参考文献扩展 → 终稿

每阶段含目标 / 任务 / 交付物 / 验收标准 / 风险预案 / 责任边界；显式承接 README 待办四项（2024 锁箱待 2026 官方标签、FI_Indicators 扣非口径、2025 MD&A 文本、模型注册表）。

### 3.3 《架构决策记录 ADR》（`docs/design/adr/`，ADR-001…010）

每条含背景 / 候选选项 / 决策 / 后果 / 状态 / 证据出处：
ADR-001 展示层一次性 Vue 3 化｜ADR-002 官方 ST 标签取代代理标签｜ADR-003 OOT 切分 2015–2021 / 2022 / 2023 + 2024 锁箱｜ADR-004 按年分组扩展窗口 CV 取代行级 TimeSeriesSplit｜ADR-005 二值特征 IV 分箱修复与 `audit_opinion` 领域先验保留｜ADR-006 主模型 XGBoost「设定优先」（`selection.rule=designated_primary_model`）而非按测试集竞标｜ADR-007 **预处理无泄漏化（已识别未落地 / 待决）**——记录 `etl/clean_financial.py:60` 的 `limit_direction="both"`、`:66-71` 全样本中位数、`:87` 全样本分位缩尾三处泄漏点，与 `docs/Attachment/论文_第1-4章.md:189` 「按训练窗口估计分位点、避免测试集信息泄露」的表述冲突，给出三个候选修复方案与影响评估｜ADR-008 JWT 双令牌 + 四角色 RBAC 权限点矩阵｜ADR-009 SQLite（桌面/演示）与 PostgreSQL（服务端）双形态边界｜ADR-010 论文表述与代码实现的口径统一决策（二选一并记录理由）。

### 3.4 《API 契约与接口参考》

按 `api/main.py` 实际注册的 13 个 router + 主路由逐条整理：方法 / 路径 / 请求体 / 响应 / 权限点 / 错误码 / 前端调用方。分组：核心域（`/health`、`/health/ready`、`/model/meta`、`/predict/codes`、`/predict/frame`（**标注 501**，`api/main.py:137-140`）、`/predict/top-risk`、`/explain/*`、`/monitor/report`、`/features`）｜财务与规则（`/finance/*`、`/risk/rules/{code}`）｜预警闭环（`/alerts*`，含 viewer 水印规则）｜数据接入与研判（`/datasources`、`/enterprise/{code}/refresh`、`/analyze/{code}`）｜平台扩展（`/auth/*`、`/audit`、`/enterprises`、`/dashboard`、`/chat`、`/skills`、`/plugins`、`/settings`、`/mcp`、`/share`、`/tables`、`/attachments`、`/ingest/v1`）。附鉴权约定（`enforce_route_permission` + `AuthGateMiddleware` / `AccessLogMiddleware` / `SecurityHeadersMiddleware`，顺序：安全头 → 访问日志 → 登录闸门）、错误映射（`ServiceUnavailable`→503、全局异常→500、`{'error':…}`→404）与「导出 OpenAPI 静态快照」流程说明（仅说明，不执行）。

### 3.5 《模型卡片与模型注册表规范》

复用 `models/run_manifest.json` 既有能力（run_id、数据 SHA256、特征 hash、参数、阈值、随机种子、`cv_protocol`）与 `models/artifacts/runs/<run_id>/` 快照。卡片字段：用途 / 适用域（证监会 C 制造业 2015–2023）/ 训练与切分 / 指标（PR-AUC 0.3986、Recall@Top10% 0.6693、ECE 0.0126）/ 适用与禁用场景 / 已知限制（正样本率 3.93%、2024 锁箱未解锁、预处理泄漏待决）/ 伦理与合规 / 失效条件（PSI 阈值、年度漂移）。注册表：`candidate → shadow → champion → archived` 四态目录与元数据约定，作为 README 待办中 MLflow 的最小替代路径。

### 3.6 《测试策略与覆盖矩阵》

以 `tests/` 21 个文件为基线产出「模块 ↔ 测试 ↔ CI 门禁」矩阵；标注未覆盖风险面（`api/agent/`、`api/mcp/`、`api/llm/`、`routers/plugins.py`、`routers/skills.py`、`routers/tables.py`、`routers/attachments.py`、`services/reading.py`、SSE 事件流、`api/worker/scheduler.py`）；CI 增强建议仅写入文档（现有 `.github/workflows/ci.yml` 仅 `test` 与 `data-gate` 两个 job）。

### 3.7 《LLM-Agent 与 MCP 设计说明》

基于真实实现核实后撰写：`api/agent/loop.py`（`MAX_STEPS=5`、`MAX_TOOL_RESULT_CHARS=6000`、`ThreadPoolExecutor` 流式事件）、`tools.py`（`build_registry` / `register_custom_tools` / `register_mcp`）、`approvals.py`、`session.py`、`prompt.py`（`SYSTEM_PROMPT`）、`context.py`、`events.py`（`AgentEvent`）、`api/llm/`（`LlmClient` / `LlmConfig` / `preheat.py`；`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_MAX_TOKENS`、`LLM_TIMEOUT_S`、`LLM_DISABLE_THINKING`）、`api/mcp/client.py` + `service.py`、`api/routers/chat.py|plugins.py|skills.py|share.py|tables.py|attachments.py`、`api/services/reading.py|plugins.py|skills.py`、`api/ingest/`（events / quality / security）、前端 `web/src/views/WorkspaceView.vue`。内容：Agent 循环时序、工具注册契约与返回值约束、MCP 接入路径、审批与安全边界（工具白名单、超时、结果截断、密钥不落盘）、权限与审计衔接、扩展开发指南（新增工具/插件/技能/MCP Server 的步骤）、「LLM 结论仅作研判辅助，不得直接作为风险评级或处置依据」的显式约束。

### 3.8 《证据冻结清单》

唯一真源表（数据层 / 切分层 / 模型层 / 解释层）+ 五处引用点同步检查清单（`docs/Attachment/论文_第1-4章.md`、`README.md`、`index.html` 的 `HOMEPAGE-DATA` 块、`reports/` 导出报告、答辩稿），并与 `scripts/build_homepage.py --check` 机制对齐；明确列出「不得改动」数字清单。

### 3.9 《文档编写与状态治理规范》

元信息块模板、写作规范速查、新增文档登记流程（新增 → 更新 `docs/README.md` 与根 README 索引 → 标状态）、失效文档处理流程（标「已废止/被取代」而非直接删除）。

---

## 四、根 `README.md` 修订要点（不改任何数值）

项目结构树补齐 `api/routers/`(12)、`api/services/`(16)、`api/auth/`(10)、`api/agent/`(8)、`api/llm/`、`api/mcp/`、`api/ingest/`、`api/worker/`、`api/db/`、`api/datasources/`、`api/middleware.py`、`api/rate_limit.py`、`api/audit.py`，`docs/` 树改为四区；功能特性表新增 LLM/Agent 研判、MCP 接入、插件系统、技能系统、只读分享、表格编辑、多模态附件与视觉识别、数据接入中心、用户与角色、审计日志；「九视图」→「12 视图」并逐项列出（含 `/workspace` 智能工作台、`/admin/users`、403 页）；标注 `/predict/frame` 501；开发计划表新增「文档体系治理（本轮已完成）」「稳健性证据链（待办）」「参考文献扩展（待办）」三行并保留原有四项待办；文档索引表与新 `docs/README.md` 对齐；参考文献表加口径统一说明（正文 [1]–[14]，完整证据基础见 P03–P33 与 49 项资源清单）；新增「文档状态与索引」小节。

---

## 五、参考文献扩展（口径统一）

以 `docs/literature/papers/` 29 个 PDF（P01–P11、P17–P33，P27 有中译与原文两版；P12–P16 缺号，去重后 23 篇唯一文献）与综述底稿 **P03–P33 编号体系**为唯一权威映射依据，逐篇核对作者/年份/题名/期刊后按 GB/T 7714-2015（中文）/ APA 7th（英文）扩写 `docs/Attachment/论文_参考文献.md`（14 → 覆盖 23 篇），并新增「P 编号 ↔ 论文引用编号」映射表；**仅追加条目**，不改动论文正文现有 [1]–[14] 的编号与引用位置，避免正文与文后表脱节。

---

## 六、质量校验（交付前必做）

1. 全仓 Markdown 相对链接可达性检查（改名后所有 `./design/…`、`./analysis/…`、`./Attachment/…` 链接与锚点）
2. 索引完备性检查：`docs/README.md` 条目与实际文件一一对应（无遗漏、无幽灵条目）
3. 重复文件检查：同名 md 仅保留 1 份
4. 数字一致性检查：README / 论文 / 证据冻结清单三处指标逐项比对（AUC 0.8962、PR-AUC 0.3986、KS 0.6609、Recall@Top10% 66.93%、ECE 0.0126、切分规模 16,233/712、3,209/75、3,372/127），确保**只增来源说明、不改数值**
5. `python scripts/build_homepage.py --check` 通过
6. Mermaid 可渲染性抽查（GitHub / Typora / VS Code）

---

## 七、目录结构（最终变更清单）

```
financial-risk-warning-platform/
├── README.md                                    # [MODIFY] 项目树补齐 api/ 全部子模块；功能特性补 LLM-Agent/MCP/插件/技能/分享/附件/接入中心/用户与角色；九视图→12 视图；标注 /predict/frame 501；开发计划表新增三行；文档索引表与 docs/README.md 对齐；参考文献口径说明；新增「文档状态与索引」小节。不得改动任何实测数值
├── index.html                                   # [MODIFY] 修正 2 处 docs/design/… → docs/design/…；保持 HOMEPAGE-DATA:BEGIN/END 标记完整
├── docs/
│   ├── README.md                                # [MODIFY] 重建四分区全量索引（design 16+8 / analysis 7 / literature 2+29PDF / Attachment 论文包）；每篇加状态标记与取代关系；新增「文档状态约定」章节；修正 9 处 docs 根目录错位 + 8 处 design 链接
│   ├── design/                                  # [RENAME] 由 docs/design/ 改名（git mv）
│   │   ├── 项目诊断与开发建议书.md               # [NEW] 五维基线 / 11 项问题清单（证据文件:行 + 严重度）/ 5 阶段路线图 / 验收标准 / 边界声明 / 遗留项（config/settings.py:63 悬空常量）
│   │   ├── 开发路线图与里程碑.md                 # [NEW] P0 文档归一与学术正确性 → P1 稳健性证据链 → P2 工程契约与可观测 → P3 增量与运营 → P4 论文定稿；每阶段目标/任务/交付物/验收/风险/边界；承接 2024 锁箱、FI_Indicators、2025 MD&A、模型注册表
│   │   ├── API契约与接口参考.md                  # [NEW] 13 router + 主路由逐条契约；鉴权中间件顺序与错误映射；标注 /predict/frame 501；OpenAPI 静态快照导出流程（仅说明）
│   │   ├── 模型卡片与模型注册表规范.md           # [NEW] 基于 run_manifest.json 与 artifacts/runs/<run_id>/ 的卡片字段模板；candidate→shadow→champion→archived 四态注册表；限制与失效条件；MLflow 最小替代路径
│   │   ├── 测试策略与覆盖矩阵.md                 # [NEW] 21 个测试文件 → 模块/测试/CI 门禁矩阵；标注 agent、mcp、llm、plugins、skills、tables、attachments、reading、SSE、scheduler 未覆盖区；CI 增强建议（不改 CI）
│   │   ├── LLM-Agent与MCP设计说明.md            # [NEW] Agent 循环（MAX_STEPS=5 / 结果截断 6000 / 流式事件）、工具注册契约、MCP 接入、审批与安全边界、权限审计衔接、扩展开发指南、LLM 结论不得直接用于评级的约束
│   │   ├── 证据冻结清单.md                       # [NEW] 数据/切分/模型/解释四层唯一真源表与「不得改动」数字清单；论文、README、index.html、报告、答辩稿五处同步检查清单
│   │   ├── 文档编写规范.md                       # [NEW] 元信息块模板、写作规范速查、新增与失效文档处理流程
│   │   ├── adr/                                 # [NEW] ADR-001…ADR-010，每条含背景/选项/决策/后果/状态/证据；ADR-007 记录预处理泄漏三处代码位置与论文表述冲突及三个候选修复方案
│   │   ├── 中期可行性分析与建议方案设计.md        # [MODIFY] 修正 docs/literature/papers、docs/ST标签补齐… 等失效路径；顶部加状态标记「4/5 已修复，待决项见 ADR-007/010」
│   │   ├── 上市公司财务风险预警_文献综述与理论奠基.md  # [DELETE] 删除与 docs/Attachment/ 字节重复副本（101849 字节），自引改指 Attachment
│   │   ├── 上市公司财务风险智能预警平台_深度实施方案.md # [MODIFY] 修正第 1045 行目录树 design；标注与新路线图取代关系
│   │   ├── 数据治理与目录规范.md                  # [MODIFY] 修正第 304 行模板目录错写路径
│   │   ├── 大屏平台开发设计方案.md                # [MODIFY] 「Streamlit 6 页 / web 8 视图」校正为 7 页 / 12 视图；补 llm/agent 章节指向新设计说明；加状态标记
│   │   ├── 平台优化设计方案_用户权限与实时接入_20261117.md # [MODIFY] 状态改「设计稿（实现已完成，待补验收记录）」；76 项测试口径对齐；加取代关系
│   │   ├── 系统架构设计说明书.md / 平台使用与运维手册.md / 平台功能与预测设计.md / 前端架构与图表方案.md / 训练评估口径与模型选择.md / FastAPI服务层设计.md / 数据字典与特征口径.md / 开题报告_研究内容与技术路线写作蓝图.md / 开题报告_文献综述章节写作蓝图.md / 上市公司财务风险智能预警平台_深度调研报告与文献综述.md  # [MODIFY] 仅补状态标记与索引链接、清理 design 自引；不改结论与数字
│   ├── analysis/                                # [MODIFY-链接] 7 篇：CSMAR手动下载清单 / CSMAR数据可行性报告 / 数据查缺与可行性分析_20261114 / 数据缺口与补齐清单_20261114 / CSMAR数据补齐进展_20261113 / CSMAR_FS_Combas_字段说明 / ST标签补齐与数据可行性核验_20261111 —— 加状态标记与索引链接
│   ├── literature/                              # [MODIFY-链接]
│   │   ├── 文献与资料调研清单.md                 # [MODIFY] 第 5、121、143 行 design→design；docs/literature/papers→docs/literature/papers
│   │   └── 文献精读笔记_P08_P07.md               # [MODIFY] 加状态标记与索引链接
│   └── Attachment/                              # [RENAME] 由 docs/附件/ 改名（git mv），使 README/docs/README 现有 12 处链接生效；内部 docx/xlsx 不动
│       ├── 论文_参考文献.md                      # [MODIFY] 14 条 → 覆盖 23 篇证据基础（GB/T 7714-2015 / APA 7th），仅追加不改 [1]-[14]
│       ├── 论文_参考文献_P编号映射表.md            # [NEW] P01–P33（含缺号 P12–P16 说明、P27 双版本去重）↔ 论文 [n] 映射与证据等级
│       ├── 论文_第1-4章.md                      # [MODIFY-核对] 不改实测数字；在第 188–190 行清洗描述处加「与代码实现的对照说明」小节，标注缩尾/插补表述与 ADR-007 的待决状态
│       ├── 论文_系统设计与实现.md                 # [MODIFY-链接] 视图数与模块清单校正、补指向新设计文档的交叉引用
│       ├── 论文_全文.docx / 毕业设计模板及格式要求.docx / 毕业设计样本.docx / 毕业设计附件（任务书与开题报告）模板.docx / 毕设选题题目表.xlsx / 毕业设计题库.xlsx / 维普系统_学生.docx  # [UNCHANGED] 原始交付物不动，仅路径引用修正
```

## Agent Extensions

### Skill

- **pdf**
- Purpose: 逐篇核对 `docs/literature/papers/` 下 29 个 PDF 的题名、作者、年份、期刊/会议、卷期页码，纠正既有中文/英文文献著录误差
- Expected outcome: 产出可直接写入 `docs/Attachment/论文_参考文献.md` 的 GB/T 7714-2015 / APA 7th 规范条目（14 → 23 篇），并使「P 编号 ↔ 论文编号」映射表可核验

### SubAgent

- **code-explorer**
- Purpose: 为《LLM-Agent 与 MCP 设计说明》《API 契约与接口参考》《测试策略与覆盖矩阵》核实 `api/agent/`、`api/llm/`、`api/mcp/`、`api/routers/`、`api/ingest/`、`api/worker/` 的真实实现细节、调用链与端点全集
- Expected outcome: 三份设计文档中的接口清单、参数、阈值、权限点与调用关系全部有代码依据，无臆造条目