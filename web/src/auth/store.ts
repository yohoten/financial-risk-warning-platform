/** 认证状态（轻量 reactive store，延续项目既有的"不用 Pinia"约定）。 */

import { reactive } from 'vue'

import { authApi, type AuthStatus, type AuthUser, type RoleInfo } from './client'
import { clearTokens, getAccess, getRefresh, setTokens } from './session'

export interface NavItem {
  to: string
  label: string
  /** 访问该页所需权限点（空=登录即可） */
  permission?: string
}

/** 顶栏导航（按权限过滤；顺序即菜单顺序）。 */
export const NAV_ITEMS: NavItem[] = [
  { to: '/', label: '数据看板', permission: 'dashboard:view' },
  { to: '/enterprises', label: '企业列表', permission: 'enterprise:view' },
  { to: '/alerts', label: '预警中心', permission: 'alert:view' },
  { to: '/explain', label: '模型解释', permission: 'explain:view' },
  { to: '/finance', label: '财务分析', permission: 'enterprise:view' },
  { to: '/report', label: '报告导出', permission: 'report:export' },
  { to: '/workspace', label: '智能工作台', permission: 'chat:use' },
  { to: '/datasources', label: '数据接入中心', permission: 'data:refresh' },
  { to: '/admin/users', label: '用户与角色', permission: 'user:manage' },
]

export const auth = reactive({
  ready: false,
  enabled: true,
  mode: 'full' as AuthStatus['mode'],
  user: null as AuthUser | null,
  roles: [] as RoleInfo[],
  /** 最近一次认证相关错误（登录页展示） */
  error: '',
  bootstrapping: false,
})

let readyPromise: Promise<void> | null = null

export function hasPerm(permission?: string): boolean {
  if (!permission) return true
  const user = auth.user
  if (!user) return false
  if (user.role === 'admin') return true
  return (user.permissions || []).includes(permission)
}

export function isLoggedIn(): boolean {
  return !!auth.user
}

/** 权限过滤后的可见菜单。 */
export function visibleNav(): NavItem[] {
  return NAV_ITEMS.filter((item) => hasPerm(item.permission))
}

/** 登录后落地的第一个可访问页面（避免 viewer 落到 403）。 */
export function firstAllowedRoute(): string {
  const visible = visibleNav()
  return visible.length ? visible[0].to : '/forbidden'
}

/** 应用启动时水合一次：拉认证开关 + 当前用户（幂等，多处 await 共享同一 Promise）。 */
export function ensureAuthReady(): Promise<void> {
  if (auth.ready) return Promise.resolve()
  if (readyPromise) return readyPromise

  readyPromise = (async () => {
    auth.bootstrapping = true
    try {
      const status = await authApi.status()
      // 只有拿到合法的布尔才更新开关，避免异常响应把 enabled 变成 undefined
      if (typeof status?.auth_enabled === 'boolean') {
        auth.enabled = status.auth_enabled
        auth.mode = status.mode
      }
    } catch (err) {
      // 后端不可达：保持 enabled 默认值，路由守卫会把用户导向登录页并提示
      auth.error = err instanceof Error ? err.message : '认证服务不可用'
    }

    const hasToken = !!getAccess()
    // local/off 形态后端会直接返回 local-admin，无令牌也要探一次
    if (hasToken || !auth.enabled) {
      try {
        const user = await authApi.me()
        // 防御：响应必须是含 username 的合法用户对象（异常兜底会把 HTML 解析成 {}）
        auth.user = user && typeof user.username === 'string' && user.username ? user : null
        if (!auth.user && hasToken) clearTokens()
      } catch {
        auth.user = null
        if (hasToken) clearTokens()
      }
    }
    auth.ready = true
    auth.bootstrapping = false
  })()

  return readyPromise
}

export async function login(username: string, password: string, remember = false): Promise<void> {
  auth.error = ''
  const data = await authApi.login(username, password, remember)
  setTokens(data.access_token, data.refresh_token, remember)
  auth.user = data.user
  auth.ready = true
  // 拉一次角色字典供用户管理页使用（失败不阻断登录）
  void loadRoles()
}

export async function loadRoles(): Promise<void> {
  try {
    const data = await authApi.roles()
    auth.roles = data.roles
  } catch {
    // 权限不足或后端不可用时静默（仅用户管理页需要）
  }
}

export async function logout(): Promise<void> {
  try {
    await authApi.logout(getRefresh())
  } catch {
    // 令牌已失效也要清本地
  } finally {
    clearTokens()
    auth.user = null
  }
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<string> {
  const resp = await authApi.changePassword(oldPassword, newPassword)
  return resp.message || '密码已更新'
}

/** 改密成功后后端让全部令牌失效：前端需要重新登录。 */
export function resetSession(): void {
  clearTokens()
  auth.user = null
}

if (typeof window !== 'undefined') {
  window.addEventListener('frw:unauthorized', () => {
    auth.user = null
  })
}