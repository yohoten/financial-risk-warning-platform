/** 会话与鉴权请求封装：令牌存储、401 单飞刷新、统一错误解析。
 *
 * 分层约定（避免循环依赖）：
 *   session.ts  ← api.ts / auth/client.ts（只依赖浏览器存储与 fetch）
 *   auth/client.ts → session.ts
 *   auth/store.ts  → client.ts + session.ts
 *
 * 401 处理采用"单飞刷新"（single-flight）：并发多个 401 只触发一次 refresh，
 * 其余请求排队复用同一次结果，避免刷新风暴导致自己把自己踢下线。
 */

const ACCESS_KEY = 'frw-access'
const REFRESH_KEY = 'frw-refresh'

export class ApiError extends Error {
  status: number
  code: string

  constructor(message: string, status = 0, code = '') {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

function read(key: string): string {
  return localStorage.getItem(key) || sessionStorage.getItem(key) || ''
}

export function getAccess(): string {
  return read(ACCESS_KEY)
}

export function getRefresh(): string {
  return read(REFRESH_KEY)
}

/** 写入令牌；remember=false 时只保留在当前标签页会话（关闭浏览器即失效）。 */
export function setTokens(access: string, refresh: string, remember = false): void {
  clearTokens()
  const storage = remember ? localStorage : sessionStorage
  storage.setItem(ACCESS_KEY, access)
  storage.setItem(REFRESH_KEY, refresh)
}

export function clearTokens(): void {
  for (const storage of [localStorage, sessionStorage]) {
    storage.removeItem(ACCESS_KEY)
    storage.removeItem(REFRESH_KEY)
  }
}

export function notifyUnauthorized(): void {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('frw:unauthorized'))
}

let refreshInflight: Promise<boolean> | null = null

/** 用 refresh token 换新令牌；并发调用共享同一次请求。 */
export function refreshSession(): Promise<boolean> {
  if (refreshInflight) return refreshInflight
  const token = getRefresh()
  if (!token) return Promise.resolve(false)
  const remember = !!localStorage.getItem(REFRESH_KEY)
  refreshInflight = (async () => {
    try {
      const resp = await fetch('/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: token }),
      })
      if (!resp.ok) return false
      const data = await resp.json()
      setTokens(data.access_token, data.refresh_token, remember)
      return true
    } catch {
      return false
    } finally {
      refreshInflight = null
    }
  })()
  return refreshInflight
}

/** 带令牌的 fetch：自动注入 Authorization，401 时刷新并重试一次。 */
export async function authFetch(url: string, init?: RequestInit): Promise<Response> {
  const doSend = (token: string) => {
    const headers = new Headers(init?.headers || {})
    if (token) headers.set('Authorization', `Bearer ${token}`)
    return fetch(url, { ...init, headers })
  }

  let resp = await doSend(getAccess())
  const isAuthEndpoint = url.startsWith('/auth/')
  if (resp.status !== 401 || isAuthEndpoint) return resp
  if (!getRefresh()) {
    notifyUnauthorized()
    return resp
  }

  const refreshed = await refreshSession()
  if (!refreshed) {
    clearTokens()
    notifyUnauthorized()
    return resp
  }
  resp = await doSend(getAccess())
  if (resp.status === 401) {
    clearTokens()
    notifyUnauthorized()
  }
  return resp
}

/** FastAPI 的 detail 可能是字符串，也可能是 {code, message} 结构。 */
export function extractError(data: unknown, status: number): ApiError {
  const detail = (data as { detail?: unknown })?.detail
  if (typeof detail === 'string' && detail) return new ApiError(detail, status)
  if (detail && typeof detail === 'object') {
    const obj = detail as { message?: string; code?: string }
    return new ApiError(obj.message || obj.code || '请求失败', status, obj.code || '')
  }
  return new ApiError(`HTTP ${status}`, status)
}