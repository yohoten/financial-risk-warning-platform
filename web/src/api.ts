/** API 客户端：统一类型与错误处理。
 *
 * 新项目 FastAPI（api/main.py）的路由不含 /api 前缀，
 * 开发期由 vite.config.ts 按前缀代理到 http://127.0.0.1:8000。
 */

// ---------------------------------------------------------------------------
// 响应类型（对照 api/services.py 与 config/feature_registry.py 的真实结构）
// ---------------------------------------------------------------------------

export interface HealthResp {
  status: string
  run_id: string
  artifacts: Record<string, boolean>
  shap: Record<string, unknown>
}

export interface ModelMeta {
  run_id: string
  semantics: string
  risk_thresholds?: { high: number; medium: number }
  features?: string[]
  [key: string]: unknown
}

/** 单条评分结果（cache/predictions.parquet 展示列） */
export interface ScoredRow {
  stock_code: string
  company_name: string
  industry: string
  year: number
  st_prob_raw?: number | null
  st_prob: number
  risk_level: string
  risk_percentile: number | null
}

export interface PredictResp {
  run_id: string
  semantics: string
  items: ScoredRow[]
  unmatched: string[]
}

export interface TopRiskResp {
  run_id: string
  year: number
  semantics: string
  items: ScoredRow[]
}

export interface ExplainResp {
  code?: string
  year?: number
  semantics: string
  contributions: Record<string, unknown>[]
  all_contributions: Record<string, unknown>[]
  [key: string]: unknown
}

export interface GlobalImportanceResp {
  items: Record<string, unknown>[]
}

export interface DependenceResp {
  feature: string
  items: Record<string, unknown>[]
}

export interface InteractionsResp {
  note: string
  items: Record<string, unknown>[]
}

export interface MonitorReportResp {
  available?: boolean
  [key: string]: unknown
}

export interface FeatureDictRow {
  字段名: string
  中文名: string
  维度: string
  方向: string
  来源: string
  口径说明: string
}

export interface FeaturesResp {
  items: FeatureDictRow[]
}

// ---------------------------------------------------------------------------
// 请求封装
// ---------------------------------------------------------------------------

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init)
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) throw new Error((data as { detail?: string }).detail || `HTTP ${resp.status}`)
  return data as T
}

// ---------------------------------------------------------------------------
// API 方法
// ---------------------------------------------------------------------------

export const api = {
  // --- 现有端点（阶段 0 可用） ---
  health: () => request<HealthResp>('/health'),
  modelMeta: () => request<ModelMeta>('/model/meta'),

  topRisk: (params: { year?: number; limit?: number; industry?: string } = {}) => {
    const q = new URLSearchParams()
    if (params.year) q.set('year', String(params.year))
    if (params.limit) q.set('limit', String(params.limit))
    if (params.industry) q.set('industry', params.industry)
    const qs = q.toString()
    return request<TopRiskResp>(`/predict/top-risk${qs ? `?${qs}` : ''}`)
  },

  predictCodes: (codes: string[], year?: number, thresholdOverride?: Record<string, number>) =>
    request<PredictResp>('/predict/codes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ codes, year, threshold_override: thresholdOverride }),
    }),

  explain: (code: string, year?: number) =>
    request<ExplainResp>(`/explain/${code}${year ? `?year=${year}` : ''}`),

  globalImportance: (topN = 20) => request<GlobalImportanceResp>(`/explain/global?top_n=${topN}`),
  dependence: (feature: string) =>
    request<DependenceResp>(`/explain/dependence?feature=${encodeURIComponent(feature)}`),
  interactions: (topN = 8) => request<InteractionsResp>(`/explain/interactions?top_n=${topN}`),

  monitorReport: () => request<MonitorReportResp>('/monitor/report'),
  features: () => request<FeaturesResp>('/features'),

  // --- 阶段 1 新增（后端尚未实现，此处先定契约占位） ---
  riskRules: (code: string) => request<Record<string, unknown>>(`/risk/rules/${code}`),
  financeOverview: () => request<Record<string, unknown>>('/finance/overview'),
  financeAnalysis: (code: string, years = 5, peers = true) =>
    request<Record<string, unknown>>(`/finance/${code}/analysis?years=${years}&peers=${peers}`),
  financeReportUrl: (code: string, years = 5) => `/finance/${code}/report?years=${years}`,
  alerts: () => request<Record<string, unknown>>('/alerts'),
  alertSummary: () => request<Record<string, unknown>>('/alerts/summary'),
  alertReportUrl: (id: number) => `/alerts/${id}/report`,
  datasources: () => request<Record<string, unknown>>('/datasources'),
}
