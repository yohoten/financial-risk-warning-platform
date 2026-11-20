# ADR-008 · JWT 双令牌与四角色 RBAC 权限体系

> | 元信息 | 值 |
> |---|---|
> | 状态 | ✅ 已采纳并已实现 |
> | 日期 | 2026-11-17 |
> | 关联文档 | 《平台优化设计方案_用户权限与实时接入（2026-11-17）》、《API 契约与接口参考》 |
> | 影响面 | `api/auth/`、`api/middleware.py`、`web/src/router.ts`、`web/src/auth/` |

## 1. 背景

项目早期 `api/main.py` 全部路由匿名开放、`CORS=*`、无审计，Vue SPA 也无路由守卫——任何知道 URL 的人可访问全部功能。同时桌面端（Electron）与服务端形态对用户体系的需求不同。

## 2. 候选选项

| 选项 | 说明 | 结论 |
|---|---|---|
| A. Session Cookie + 服务端会话 | 传统 | ⚠️ 与 Electron 打包形态、SPA 跨域开发代理配合较繁琐 |
| B. JWT 单令牌 | 简洁 | ❌ 无法撤销；access 过期即需重新登录 |
| C. JWT 双令牌（access + refresh 轮换） | 见下 | ✅ **采纳** |
| D. 引入外部 IdP（OAuth/OIDC） | 企业级 | ❌ 毕设场景无必要，依赖外部服务影响离线交付 |

## 3. 决策

**采用 C**，并配套三项设计：

### 3.1 双令牌

- **access token**：30 分钟有效期，随每个请求携带；
- **refresh token**：7 天有效期，**每次刷新都轮换**并撤销旧令牌（防重放）；
- **撤销机制**：`api/auth/revocation.py` 维护黑名单；用户改密时 `password_version + 1`，该用户全部旧令牌立即失效。

### 3.2 集中式路由闸门（而非逐路由挂依赖）

`api/auth/guards.py` 用一张显式的「方法 + 路径前缀 + 权限点」规则表统一拦截（当前 **30 条规则**）。理由写在代码注释里：30+ 扁平路由 + 10 个子路由逐个挂 `Depends(require_permission(...))` **啰嗦且容易漏——漏一个就是「以为有鉴权、其实裸奔」**。规则表本身即可评审的权限清单。

放行白名单：`/health`、`/health/ready`、`/auth/login`、`/auth/refresh`、`/auth/status`、`/openapi.json`、`/docs`、`/redoc`，以及前缀 `/assets`、`/share`（只读分享）、`/favicon`、`/ingest/v1`（走 X-API-Key 机器通道，不参与 JWT）。

启动时 `api/main.py:_bootstrap_auth()` 调用 `verify_auth_coverage(app)` **自检所有路由是否落在鉴权前缀内**，缺口写日志告警——把「漏配」变成**可观测事件**而非静默风险。

### 3.3 四角色 × 17 权限点

| 角色 | 定位 | 权限点数 |
|---|---|---:|
| `admin` 系统管理员 | 只管用户/角色/数据源/系统配置，不替代业务研判 | 17（全部） |
| `analyst` 分析师 | 模型、诊断、预警处置、报告、触发数据刷新 | 10 |
| `auditor` 审计员 | 业务只读 + 可查审计日志与模型留痕，不可修改 | 6 |
| `viewer` 查看者 | 只读看板与诊断，导出带水印 | 4 |

命名统一为 `域:动作`（如 `enterprise:view`、`alert:handle`、`audit:view`），**前端路由 `meta.permission` 与后端规则表使用同一组字符串**（`web/src/router.ts` 12 条路由全部带 permission）。

## 4. 配套机制

| 机制 | 落点 | 说明 |
|---|---|---|
| 密码哈希 | `api/auth/passwords.py` | bcrypt/argon2，历史 bcrypt 兼容校验 + `needs_rehash` 升级 |
| 口令强度 | `check_strength()` | 最短长度由 `settings.PASSWORD_MIN_LENGTH` 控制 |
| 登录锁定与防枚举 | `api/auth/router.py` | 限频与失败锁定 |
| 审计日志 | `api/audit.py` + `api/routers/audit.py` | `/audit/logs` 分页 + `/audit/summary` 近 7 天概览 |
| 访问日志 | `api/middleware.py` `AccessLogMiddleware` | 中间件顺序：安全头 → 访问日志 → 登录闸门 |
| 安全响应头 | `SecurityHeadersMiddleware` | — |
| 限流 | `api/rate_limit.py` | — |
| viewer 水印 | `api/main.py:_watermark_footer()` | viewer 导出的财务/预警报告自动加水印（属主 + 时间） |
| 初始管理员 | `api/auth/service.py::ensure_admin()` | 口令由 `RISK_ADMIN_PASSWORD` 覆盖，默认 `admin/admin12345` |

## 5. 后果

**正面**：全部路由默认受保护且权限清单可评审；前端菜单与路由按权限点过滤；审计可追溯；桌面端与服务端共用同一套鉴权。

**负面**：引入 `password_version` 与令牌黑名单后，令牌校验路径变长（每请求多一次黑名单查询）；权限点为字符串常量，新增权限点需同步前后端两处（`api/auth/rbac.py` + `web/src/router.ts`）。

**约束**：新增受保护端点时**必须**同时在 `api/auth/guards.py` 规则表中登记，否则 `verify_auth_coverage` 会在启动日志中告警——这是新增端点的强制检查项。
