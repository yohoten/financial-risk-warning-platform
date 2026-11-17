/** API 客户端：统一类型与错误处理。
 *
 * 新项目 FastAPI（api/main.py）的路由不含 /api 前缀，
 * 开发期由 vite.config.ts 按前缀代理到 http://127.0.0.1:8000。
 */

// ---------------------------------------------------------------------------
// 基础类型
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

// ---------------------------------------------------------------------------
// SHAP 解释
// ---------------------------------------------------------------------------

export interface ContributionRow {
  feature: string
  中文名: string
  取值: number
  SHAP值: number
  方向: string
}

export interface ExplainResp {
  stock_code: string
  year: number
  base_value: number
  prediction: number
  raw_probability: number
  calibrated: boolean
  semantics: string
  contributions: ContributionRow[]
  all_contributions: ContributionRow[]
}

export interface ImportanceRow {
  feature: string
  importance: number
  中文名: string
  方向: string
  维度: string
}

export interface GlobalImportanceResp {
  items: ImportanceRow[]
}

export interface DependenceRow {
  feature_value: number
  shap_value: number
  stock_code: string
}

export interface DependenceResp {
  feature: string
  items: DependenceRow[]
}

export interface InteractionRow {
  feature_a: string
  feature_b: string
  交互强度: number
  相关系数: number
}

export interface InteractionsResp {
  note: string
  items: InteractionRow[]
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

export interface MonitorReportResp {
  available?: boolean
  [key: string]: unknown
}

// ---------------------------------------------------------------------------
// 财务分析
// ---------------------------------------------------------------------------

export interface FinanceKpi {
  key: string
  label: string
  unit: string
  group: string
  value: number | null
  prev: number | null
  yoy: number | null
  trend: 'up' | 'down' | 'flat'
  higher_better: boolean
  available: boolean
  year: number | null
  note: string
}

export interface FinanceTrendSeries {
  key: string
  label: string
  unit: string
  points: { year: number; value: number | null }[]
}

export interface FinanceTrendGroup {
  label: string
  series: FinanceTrendSeries[]
}

export interface DupontRow {
  year: number
  roe: number | null
  net_margin: number | null
  asset_turnover: number | null
  equity_multiplier: number | null
  complete: boolean
}

export interface DupontAttribution {
  from_year: number
  to_year: number
  roe_delta: number
  items: { key: string; label: string; contrib: number }[]
  note: string
}

export interface AltmanComponent {
  value: number | null
  source: string
  label: string
}

export interface AltmanModel {
  score: number | null
  verdict: string | null
  available: boolean
  basis: string
  thresholds: string
  components: Record<string, AltmanComponent>
  missing: string[]
  note: string
}

export interface PiotroskiSignal {
  name: string
  group: string
  pass: boolean | null
  detail: string
}

export interface PiotroskiModel {
  key: string
  name: string
  period: number
  available: boolean
  reason?: string
  score: number | null
  max_score: number
  full_score: number
  verdict: string | null
  complete: boolean
  signals: PiotroskiSignal[]
  note: string
}

export interface BeneishIndex {
  key: string
  label: string
  value: number | null
  source: string
  detail: string
}

export interface BeneishModel {
  key: string
  name: string
  period: number
  available: boolean
  reason?: string
  score: number | null
  thresholds: string
  verdict: string | null
  indices: BeneishIndex[]
  missing: string[]
  approx: string[]
  note: string
}

export interface PeerRow {
  stock_code: string
  name: string
  industry: string
  is_self: boolean
  year: number
  metrics: Record<string, number | null>
  percentiles: Record<string, number | null>
}

export interface FinanceAnomaly {
  code: string
  level: string
  title: string
  detail: string
  evidence: Record<string, unknown>
}

export interface FinanceAnalysis {
  enterprise: { stock_code: string; name: string; industry: string }
  available: boolean
  reason?: string
  latest_year: number
  kpi: FinanceKpi[]
  trends: Record<string, FinanceTrendGroup>
  dupont: { formula: string; rows: DupontRow[]; attribution: DupontAttribution | null }
  models: {
    altman: { key: string; name: string; period: number; z: AltmanModel; z2: AltmanModel }
    piotroski: PiotroskiModel
    beneish: BeneishModel
  }
  peers: {
    industry: string
    rows: PeerRow[]
    metrics: { key: string; label: string; unit: string; higher_better: boolean }[]
    note: string
  } | null
  peer_median: Record<string, number>
  anomalies: FinanceAnomaly[]
  data_quality: {
    years: number
    periods: { year: number; report_type: string; source: string; derived: string[] }[]
    missing_metrics: string[]
    notes: string[]
  }
}

export interface FinanceOverviewRow {
  stock_code: string
  name: string
  industry: string
  has_finance: boolean
  years: number
  latest_year: number | null
  revenue: number | null
  net_profit: number | null
  revenue_growth: number | null
  gross_margin: number | null
  net_margin: number | null
  roe: number | null
  debt_ratio: number | null
}

export interface FinanceOverviewResp {
  total: number
  items: FinanceOverviewRow[]
}

// ---------------------------------------------------------------------------
// 规则评分与预警
// ---------------------------------------------------------------------------

export interface RuleDimension {
  score: number | null
  level: string
  label: string
  indicators: Record<string, unknown>
  note: string
}

export interface RulesVerdictResp {
  stock_code: string
  score: number | null
  grade: string
  grade_label: string
  level: string
  dimensions: Record<string, RuleDimension>
  indicators: Record<string, unknown>
  data_status: Record<string, string>
}

export interface AnalyzeEvidence {
  dimension: string
  text: string
  source?: string
}

export interface AnalyzeResp {
  enterprise: { stock_code: string; name: string; industry: string }
  verdict: {
    level: string
    score: number | null
    grade: string
    grade_label: string
    level_by: string
    cross_check_ok: boolean
    llm_level: string
    rules_level: string
    dimensions: Record<string, RuleDimension>
    summary: string
    evidence: AnalyzeEvidence[]
  }
  model: { year: number; st_prob: number; risk_level: string; risk_percentile: number } | null
  llm_error: string
}

export interface DatasourcesResp {
  akshare_available: boolean
  sources: {
    dimension: string
    mode: string
    sources: { name: string; label: string; dims: string[] }[]
  }[]
}

export interface RefreshResp {
  ok: boolean
  stock_code: string
  source?: string
  market_cap?: number
  items?: Record<string, unknown>[]
  error?: string
}

export interface AlertNote {
  ts: string
  action?: string
  status?: string
  status_label?: string
  handler?: string
  note?: string
}

export interface AlertRow {
  id: number
  stock_code: string
  company_name: string
  level: string
  dimension: string
  dimension_label: string
  title: string
  summary: string
  score: number | null
  status: string
  status_label: string
  handler: string
  created_at: string
  updated_at: string
  handled_at: string | null
  notes: AlertNote[]
  evidence: Record<string, unknown>[]
}

export interface AlertsResp {
  total: number
  items: AlertRow[]
}

export interface AlertsSummaryResp {
  total: number
  by_status: Record<string, number>
  by_level: Record<string, number>
  pending: number
  handling: number
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
  // --- 基础 ---
  health: () => request<HealthResp>('/health'),
  modelMeta: () => request<ModelMeta>('/model/meta'),

  // --- 评分 ---
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

  // --- SHAP 解释 ---
  explain: (code: string, year?: number) =>
    request<ExplainResp>(`/explain/${code}${year ? `?year=${year}` : ''}`),
  globalImportance: (topN = 20) => request<GlobalImportanceResp>(`/explain/global?top_n=${topN}`),
  dependence: (feature: string) =>
    request<DependenceResp>(`/explain/dependence?feature=${encodeURIComponent(feature)}`),
  interactions: (topN = 8) => request<InteractionsResp>(`/explain/interactions?top_n=${topN}`),
  monitorReport: () => request<MonitorReportResp>('/monitor/report'),
  features: () => request<FeaturesResp>('/features'),

  // --- 规则评分 ---
  riskRules: (code: string) => request<RulesVerdictResp>(`/risk/rules/${code}`),

  // --- 财务分析 ---
  financeOverview: () => request<FinanceOverviewResp>('/finance/overview'),
  financeAnalysis: (code: string, years = 5, peers = true) =>
    request<FinanceAnalysis>(`/finance/${code}/analysis?years=${years}&peers=${peers}`),
  financeReportUrl: (code: string, years = 5) => `/finance/${code}/report?years=${years}`,

  // --- 预警闭环 ---
  alerts: (params: { status?: string; level?: string; stock_code?: string } = {}) => {
    const q = new URLSearchParams()
    if (params.status) q.set('status', params.status)
    if (params.level) q.set('level', params.level)
    if (params.stock_code) q.set('stock_code', params.stock_code)
    const qs = q.toString()
    return request<AlertsResp>(`/alerts${qs ? `?${qs}` : ''}`)
  },
  alertSummary: () => request<AlertsSummaryResp>('/alerts/summary'),
  generateAlerts: (stockCode?: string) =>
    request<{ enterprises?: number; created?: number; skipped?: number; error?: string }>('/alerts/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(stockCode ? { stock_code: stockCode } : {}),
    }),
  handleAlert: (id: number, action: string, handler = '', note = '') =>
    request<{ alert_id: number; status: string; status_label: string; handler: string; notes: AlertNote[] }>(
      `/alerts/${id}/handle`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, handler, note }),
      },
    ),
  alertReportUrl: (id: number) => `/alerts/${id}/report`,

  // --- 数据源接入与智能研判（阶段 4） ---
  datasources: () => request<DatasourcesResp>('/datasources'),
  refreshEnterprise: (code: string) =>
    request<RefreshResp>(`/enterprise/${code}/refresh`, { method: 'POST' }),
  analyze: (code: string) => request<AnalyzeResp>(`/analyze/${code}`, { method: 'POST' }),
}
