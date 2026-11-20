# API 契约与接口参考

> | 元信息 | 值 |
> |---|---|
> | 状态 | ✅ 与代码一致（基于 `api/main.py` 与 `api/routers/` 实测，2026-11-19） |
> | 版本 | v1.0 |
> | 取代关系 | **取代**《FastAPI服务层设计》（该文档仅覆盖早期 `/predict` `/explain` 契约，已与当前 100+ 端点脱节，保留作历史留存） |
> | 适用对象 | 前端开发、第三方接入、答辩演示 |
> | 基址 | 开发期 `http://127.0.0.1:8000`（Vite 代理按前缀转发，**路由不带 `/api` 前缀**） |

---

## 1. 全局约定

### 1.1 中间件与鉴权

```
请求 → SecurityHeadersMiddleware → AccessLogMiddleware → AuthGateMiddleware
     → Depends(enforce_route_permission)  ← 集中式路由闸门
     → 业务路由
```

- **令牌**：`Authorization: Bearer <access_token>`；access 30 分钟，refresh 7 天且每次刷新轮换。
- **放行白名单**：`/health`、`/health/ready`、`/auth/login`、`/auth/refresh`、`/auth/status`、`/openapi.json`、`/docs`、`/redoc`；前缀 `/assets`、`/share`、`/favicon`、`/ingest/v1`。
- **机器通道**：`/ingest/v1/*` 走 `X-API-Key`，不参与 JWT；API Key 仅存 SHA256 摘要，明文只在签发时返回一次。
- **权限点**：`域:动作` 命名，17 个；前端 `router.ts` 的 `meta.permission` 与后端规则表 `api/auth/guards.py` 使用同一组字符串。

### 1.2 错误映射

| 情形 | HTTP | 响应 |
|---|:---:|---|
| 未登录 / 令牌无效或过期 | 401 | `{"detail": "...", "code": "unauthorized"}` |
| 权限不足 | 403 | `{"detail": "...", "code": "forbidden"}` |
| 领域层返回 `{"error": ...}` | 404 | `{"detail": "<error 文本>"}`（经 `_or_404()` 统一转换） |
| 参数校验失败 | 422 | FastAPI 标准校验错误体 |
| 依赖服务不可用（模型/数据缺失） | 503 | `{"detail": "<ServiceUnavailable 文本>"}` |
| 未捕获异常 | 500 | `{"detail": "<ExceptionType>: <message>"}` |

> ⚠️ 全局异常处理器会把异常类型名与消息一并返回。生产部署前建议改为记录到日志并返回通用文案（列入 P2）。

### 1.3 统一响应约定

- 列表类接口统一返回 `{"total": N, "items": [...]}`；
- 领域层（`models/*`）以 `{"error": "..."}` 表示「未找到」，服务层负责转为 404；
- 前端 `web/src/api.ts` 统一封装 `fetch()`，含令牌注入与 401 处理。

---

## 2. 核心域路由（`api/main.py` 直接注册）

| 方法 | 路径 | 说明 | 权限点 |
|:---:|---|---|---|
| GET | `/health` | 存活探针 | 放行 |
| GET | `/health/ready` | 就绪探针：DB 可写 + 模型产物就绪；DB 不可写返回 503 | 放行 |
| GET | `/model/meta` | 模型元信息（run_id、特征数、训练参数） | `dashboard:view` |
| POST | `/predict/codes` | 按股票代码批量打分；请求体 `{codes: [...], year?, threshold_override?}` | `enterprise:view` |
| POST | `/predict/frame` | **what-if 反向模拟** | `predict:run` |
| GET | `/predict/top-risk` | 高风险企业榜；查询参数 `year?, limit(1–1000), industry?` | `enterprise:view` |
| GET | `/explain/global` | 全局特征重要性；`top_n(5–100)` | `enterprise:view` |
| GET | `/explain/dependence` | 特征依赖效应；`feature`（必填） | `enterprise:view` |
| GET | `/explain/interactions` | 特征交互强度；`top_n(3–20)` | `enterprise:view` |
| GET | `/explain/{code}` | 单企业 SHAP 归因；`year?` | `enterprise:view` |
| GET | `/monitor/report` | PSI 漂移与性能衰减监控报告 | `explain:view` |
| GET | `/features` | 特征字典（由注册表生成） | `enterprise:view` |

> **`/predict/frame` 当前返回 501**（`api/main.py:137-140`）：「what-if 预测尚未实现（P1）」。单企业体检（`/explain/{code}`）所需的原始字段 → 特征单行计算尚未落地。**不得**在对外材料中描述该端点可用。

> 静态路由 `/explain/global` 必须先于 `/explain/{code}` 注册，否则 `"global"` 会被路径参数吞掉——新增同类静态路径时需注意注册顺序。

---

## 3. 财务与规则（阶段 1 移植）

| 方法 | 路径 | 说明 | 权限点 |
|:---:|---|---|---|
| GET | `/finance/overview` | 全平台财务概览；`years(1–20)` | `enterprise:view` |
| GET | `/finance/{code}/analysis` | 单企业财务分析（杜邦、Altman Z/Z''、Piotroski、Beneish、同业对标）；`years(1–20), peers` | `enterprise:view` |
| GET | `/finance/{code}/report` | 财务分析报告（Markdown）；`download=1` 触发下载；**viewer 自动加水印** | `report:export` |
| GET | `/risk/rules/{code}` | 规则六维评分与评级结论 | `enterprise:view` |

---

## 4. 预警闭环（阶段 1 移植）

| 方法 | 路径 | 说明 | 权限点 |
|:---:|---|---|---|
| GET | `/alerts` | 预警工单列表；`status?, level?, stock_code?, limit(1–1000)` | `alert:view` |
| GET | `/alerts/summary` | 预警汇总统计 | `alert:view` |
| POST | `/alerts/generate` | 生成预警（带 `stock_code` 则单家，否则全量） | `alert:handle` |
| POST | `/alerts/{alert_id}/handle` | 处置预警；请求体 `{action, handler, note}` | `alert:handle` |
| GET | `/alerts/{alert_id}/report` | 预警处置报告（Markdown）；`download=1` 触发下载；**viewer 自动加水印** | `report:export` |

**处置动作**：`start` / `resolve` / `ignore` / `reopen`（与 Agent 工具 `handle_alert` 一致）。

---

## 5. 数据源与研判

| 方法 | 路径 | 说明 | 权限点 |
|:---:|---|---|---|
| GET | `/datasources` | 数据源状态（东财 / 新浪 / 巨潮 等） | `enterprise:view` |
| POST | `/enterprise/{code}/refresh` | 触发单企业数据刷新 | `data:refresh` |
| POST | `/analyze/{code}` | LLM 智能研判（结合规则评分交叉校验） | `chat:use` |

---

## 6. 平台扩展路由（`api/routers/`）

### 6.1 认证与权限（`api/auth/router.py`，无前缀）

| 方法 | 路径 | 说明 | 权限点 |
|:---:|---|---|---|
| GET | `/auth/status` | 认证状态探测（登录页用，匿名可访问） | 放行 |
| POST | `/auth/login` | 登录，签发双令牌 | 放行 |
| POST | `/auth/refresh` | 刷新令牌（轮换 + 撤销旧令牌） | 放行 |
| POST | `/auth/logout` | 注销 | 登录即可 |
| GET | `/auth/me` | 当前用户信息 | 登录即可 |
| GET | `/auth/roles` | 角色与权限字典 | 登录即可 |
| POST | `/auth/change-password` | 修改本人密码 | 登录即可 |
| GET | `/users` | 用户列表 | `user:manage` |
| POST | `/users` | 新建用户（仅管理员） | `user:manage` |
| PATCH | `/users/{user_id}` | 修改用户（邮箱 / 角色 / 启停） | `user:manage` |
| POST | `/users/{user_id}/reset-password` | 重置密码 | `user:manage` |
| DELETE | `/users/{user_id}` | 停用用户 | `user:manage` |

### 6.2 数据接入中心（`api/auth/router.py` + `api/ingest/router.py`）

| 方法 | 路径 | 说明 | 权限点 |
|:---:|---|---|---|
| POST | `/ingest/keys` | 签发 API Key（**明文仅返回一次**） | `ingest:push` |
| GET | `/ingest/keys` | API Key 列表（脱敏） | `ingest:push` |
| DELETE | `/ingest/keys/{key_id}` | 吊销 API Key | `ingest:push` |
| POST | `/ingest/v1/{dimension}` | **外部数据推送**（`X-API-Key` 鉴权，幂等 + 质量闸门） | 机器通道 |
| GET | `/ingest/logs` | 接入日志分页 | `data:refresh` |
| GET | `/ingest/staging` | 推送暂存区查询 | `data:refresh` |
| POST | `/ingest/staging/consume` | 合并暂存数据入业务库并触发闭环 | `data:refresh` |
| POST | `/datasources/pull` | 触发数据源拉取（pull 通道） | `data:refresh` |
| GET | `/datasources/config` | 数据源配置列表 | `enterprise:view` |
| POST | `/datasources/config` | 新增数据源配置 | `datasource:manage` |
| PATCH | `/datasources/config/{config_id}` | 更新数据源配置 | `datasource:manage` |
| DELETE | `/datasources/config/{config_id}` | 删除数据源配置 | `datasource:manage` |
| GET | `/events/stream` | **实时事件流（SSE）** | `alert:view` |

### 6.3 企业、看板与审计

| 方法 | 路径 | 说明 | 权限点 |
|:---:|---|---|---|
| GET | `/enterprises` | 企业列表 | `enterprise:view` |
| GET | `/enterprises/{stock_code}` | 企业详情 | `enterprise:view` |
| POST | `/enterprises` | 新增企业 | `enterprise:manage` |
| DELETE | `/enterprises/{stock_code}` | 删除企业 | `enterprise:manage` |
| GET | `/enterprises/{stock_code}/profile` | 企业画像 | `enterprise:view` |
| GET | `/dashboard/summary` | 看板汇总 | `dashboard:view` |
| GET | `/dashboard/risk-facts` | 风险事实流 | `dashboard:view` |
| GET | `/audit/logs` | 审计日志分页；`page, size(1–500)` | `audit:view` |
| GET | `/audit/summary` | 审计概览（近 7 天动作分布） | `audit:view` |

### 6.4 对话工作台（`/chat`）

| 方法 | 路径 | 说明 |
|:---:|---|---|
| POST | `/chat/stream` | Agent 流式对话（SSE），请求体 `{message, session_id?, preset?}` |
| POST | `/chat/approve` | 审批 Agent 的高风险工具调用，��体 `{approval_id, approved}` |
| GET | `/chat/sessions` | 会话列表；`limit, q` |
| POST | `/chat/sessions` | 新建会话 |
| GET | `/chat/sessions/{session_id}` | 会话详情 |
| PATCH | `/chat/sessions/{session_id}` | 重命名会话 |
| POST | `/chat/sessions/{session_id}/clear` | 清空消息 |
| POST | `/chat/sessions/batch_delete` | 批量删除会话 |
| DELETE | `/chat/sessions/{session_id}` | 删除会话 |
| GET | `/chat/sessions/{session_id}/export` | 导出会话；`format=md\|json` |
| POST | `/chat/sessions/{session_id}/share` | 创建只读分享链接 |
| DELETE | `/chat/sessions/{session_id}/share` | 撤销分享 |
| POST | `/chat/import` | 导入会话 |
| GET | `/chat/usage` | Token 用量汇总；`session_id?` |

### 6.5 技能、插件、MCP

| 方法 | 路径 | 说明 | 权限点 |
|:---:|---|---|---|
| GET/POST | `/skills` | 技能列表 / 新建 | `system:config` |
| PATCH/DELETE | `/skills/{skill_id}` | 修改 / 删除技能 | `system:config` |
| GET/POST | `/plugins/tools` | 插件工具列表 / 新增 | `system:config` |
| PATCH/DELETE | `/plugins/tools/{tool_id}` | 修改 / 删除插件工具 | `system:config` |
| GET/POST | `/plugins/presets` | 预设列表 / 新建 | `system:config` |
| PATCH/DELETE | `/plugins/presets/{preset_id}` | 修改 / 删除预设 | `system:config` |
| GET | `/plugins/presets/{preset_id}/export` | 导出预设 | `system:config` |
| GET | `/plugins/export` | 导出全部配置 | `system:config` |
| POST | `/plugins/import` | 导入配置 | `system:config` |
| GET/POST | `/mcp/servers` | MCP 服务列表 / 新增 | `system:config` |
| PATCH/DELETE | `/mcp/servers/{server_id}` | 修改 / 删除 MCP 服务 | `system:config` |
| POST | `/mcp/servers/{server_id}/test` | 连通性测试 | `system:config` |
| POST | `/mcp/servers/{server_id}/sync` | 同步工具清单 | `system:config` |
| POST | `/mcp` | **把本平台作为 MCP 工具服务器对外提供**（JSON-RPC 风格） | `system:config` |

### 6.6 设置、表格、附件与分享

| 方法 | 路径 | 说明 | 权限点 |
|:---:|---|---|---|
| GET/PUT | `/settings` | 读取 / 保存系统设置 | `system:config` |
| POST | `/settings/reset` | 恢复默认设置 | `system:config` |
| POST | `/settings/models` | 切换模型配置 | `system:config` |
| GET | `/tables` | 表格列表 | `enterprise:view` |
| GET | `/tables/templates` | 表格模板 | `enterprise:view` |
| POST | `/tables/import` | 导入表格 | `enterprise:manage` |
| POST | `/tables` | 新建表格 | `enterprise:manage` |
| GET | `/tables/{table_id}` | 表格详情 | `enterprise:view` |
| PATCH | `/tables/{table_id}` | 修改表格 | `enterprise:manage` |
| POST | `/tables/{table_id}/cells` | 写入单元格 | `enterprise:manage` |
| POST | `/tables/{table_id}/validate` | 校验 | `enterprise:manage` |
| GET | `/tables/{table_id}/preview` | 预览 | `enterprise:view` |
| POST | `/tables/{table_id}/ingest` | 入库 | `enterprise:manage` |
| POST | `/tables/{table_id}/confirm` | 确认 | `enterprise:manage` |
| DELETE | `/tables/{table_id}` | 删除表格 | `enterprise:manage` |
| GET | `/attachments` | 附件列表；`session_id, limit` | `chat:use` |
| POST | `/attachments` | 上传（base64 JSON） | `chat:use` |
| POST | `/attachments/raw` | 上传（二进制流） | `chat:use` |
| GET | `/attachments/{attachment_id}` | 下载原始内容 | `chat:use` |
| GET | `/attachments/{attachment_id}/meta` | 附件元信息 | `chat:use` |
| DELETE | `/attachments/{attachment_id}` | 删除附件 | `chat:use` |
| POST | `/attachments/{attachment_id}/read` | **视觉识别 / 内容读取**；`{target, table_id?, dry_run?}` | `chat:use` |
| GET | `/share/{token}` | 只读分享内容 | 放行（前缀） |

---

## 7. 前端视图 ↔ 端点对照

| 视图（`web/src/views/`） | 路由 | 主要端点 |
|---|---|---|
| `LoginView.vue` | `/login` | `/auth/login`、`/auth/refresh`、`/auth/me` |
| `DashboardView.vue` | `/` | `/dashboard/summary`、`/dashboard/risk-facts`、`/model/meta` |
| `EnterprisesView.vue` | `/enterprises` | `/enterprises`、`/predict/top-risk` |
| `EnterpriseView.vue` | `/enterprise/:code` | `/enterprises/{code}`、`/explain/{code}`、`/finance/{code}/analysis`、`/risk/rules/{code}` |
| `AlertsView.vue` | `/alerts` | `/alerts*`、`/events/stream` |
| `ExplainView.vue` | `/explain` | `/explain/global|dependence|interactions`、`/monitor/report` |
| `FinanceView.vue` | `/finance/:code?` | `/finance/*` |
| `ReportView.vue` | `/report` | `/finance/{code}/report`、`/alerts/{id}/report` |
| `WorkspaceView.vue` | `/workspace` | `/chat/*`、`/attachments/*`、`/tables/*` |
| `DataSourceView.vue` | `/datasources` | `/datasources*`、`/ingest/keys`、`/ingest/logs` |
| `UsersView.vue` | `/admin/users` | `/users*`、`/auth/roles` |
| `ForbiddenView.vue` | `/forbidden` | —（纯前端 403 页） |

---

## 8. 契约快照与变更管理

### 8.1 导出 OpenAPI 静态快照

```bash
python -c "import json, api.main as m; json.dump(m.app.openapi(), open('docs/design/api/openapi.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)"
```

> 需先启动依赖（模型产物、DB）。当前 `docs/design/api/` 目录尚未建立，**本轮不执行导出**（属 P2-1）。

### 8.2 变更约束

1. 新增端点时**必须**同时在 `api/auth/guards.py` 的 `RULES` 中登记，否则启动时 `verify_auth_coverage()` 会打印告警；
2. 请求/响应模型统一放在 `api/schemas.py` 或各 router 的 `Pydantic` 模型中，禁止返回裸 dict 之外的自定义结构；
3. 权限点新增需同步 `api/auth/rbac.py`（`ALL_PERMISSIONS` + 角色矩阵 + `PERMISSION_LABELS`）与 `web/src/router.ts`；
4. 破坏性变更必须在本文件与《证据冻结清单》同步记录。

---

## 9. 相关

- 《系统架构设计说明书》——分层架构与数据契约
- 《LLM-Agent 与 MCP 设计说明》——`/chat`、`/mcp`、`/attachments` 的内部机制
- 《测试策略与覆盖矩阵》——各端点的测试覆盖情况
- 《FastAPI服务层设计》（已被本文件取代，保留作历史留存）
