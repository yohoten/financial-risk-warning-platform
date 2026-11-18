/** 认证域接口客户端（登录/续期/注销/用户管理）。 */

import { ApiError, authFetch, extractError } from './session'

export interface PermissionCatalog {
  [key: string]: string
}

export interface RoleInfo {
  role: string
  label: string
  permissions: string[]
  permission_labels: string[]
}

export interface AuthUser {
  id: string
  username: string
  email: string
  role: string
  role_label: string
  permissions: string[]
  must_change_password: boolean
  auth_mode?: string
  last_login_at?: string
  is_active?: boolean
  note?: string
  created_at?: string
}

export interface AuthStatus {
  auth_enabled: boolean
  mode: 'full' | 'local' | 'off'
  user_count: number
  needs_setup: boolean
  password_min_length: number
  token_minutes: number
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: AuthUser
}

export interface UserListResponse {
  total: number
  items: AuthUser[]
  roles: RoleInfo[]
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await authFetch(url, init)
  // 后端异常时可能回吐 SPA 的 HTML（如服务未启动/版本过旧/路径被兜底路由接管），
  // 此时应视为后端不可用，而不是把解析失败的 {} 当作合法数据返回。
  const contentType = resp.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) {
    throw new ApiError('后端服务不可用或版本过旧，请重启后端服务', resp.status, 'backend_unreachable')
  }
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) throw extractError(data, resp.status)
  return data as T
}

const jsonInit = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const authApi = {
  status: () => call<AuthStatus>('/auth/status'),

  login: (username: string, password: string, remember = false) =>
    call<TokenResponse>('/auth/login', jsonInit('POST', { username, password, remember })),

  me: () => call<AuthUser>('/auth/me'),

  logout: (refreshToken?: string) =>
    call<{ ok: boolean; message: string }>(
      '/auth/logout',
      jsonInit('POST', { refresh_token: refreshToken || '' }),
    ),

  changePassword: (oldPassword: string, newPassword: string) =>
    call<{ ok: boolean; message: string }>(
      '/auth/change-password',
      jsonInit('POST', { old_password: oldPassword, new_password: newPassword }),
    ),

  roles: () => call<{ roles: RoleInfo[]; permissions: PermissionCatalog }>('/auth/roles'),

  // --- 用户管理（user:manage） ---
  users: (params: { keyword?: string; role?: string } = {}) => {
    const q = new URLSearchParams()
    if (params.keyword) q.set('keyword', params.keyword)
    if (params.role) q.set('role', params.role)
    const qs = q.toString()
    return call<UserListResponse>(`/users${qs ? `?${qs}` : ''}`)
  },

  createUser: (payload: {
    username: string
    password: string
    email?: string
    role?: string
    note?: string
  }) => call<AuthUser>('/users', jsonInit('POST', payload)),

  updateUser: (
    userId: string,
    payload: { email?: string; role?: string; is_active?: boolean; note?: string },
  ) => call<AuthUser>(`/users/${userId}`, jsonInit('PATCH', payload)),

  resetPassword: (userId: string, newPassword?: string) =>
    call<{ user: AuthUser; password: string | null }>(
      `/users/${userId}/reset-password`,
      jsonInit('POST', { new_password: newPassword || null }),
    ),

  deactivateUser: (userId: string) =>
    call<AuthUser>(`/users/${userId}`, { method: 'DELETE' }),
}

export { ApiError }