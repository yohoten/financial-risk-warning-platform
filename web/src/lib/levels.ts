/** 风险等级元数据与展示工具（与新项目 config/settings.py 的 RISK_COLORS 对齐） */

export interface RiskLevelMeta {
  label: string
  color: string
}

/** 模型概率三档（主风险等级） */
export const RISK_LEVELS: Record<string, RiskLevelMeta> = {
  高风险: { label: '高风险', color: '#dc2626' },
  中风险: { label: '中风险', color: '#ea580c' },
  低风险: { label: '低风险', color: '#16a34a' },
  数据不足: { label: '数据不足', color: '#94a3b8' },
}

/** 规则引擎五档（经营风险视角） */
export const RULE_LEVELS: Record<string, RiskLevelMeta> = {
  red: { label: '高风险', color: '#dc2626' },
  orange: { label: '较高风险', color: '#ea580c' },
  yellow: { label: '关注', color: '#ca8a04' },
  green: { label: '正常', color: '#16a34a' },
  gray: { label: '数据不足', color: '#94a3b8' },
}

export function riskColor(level?: string | null): string {
  return (level && RISK_LEVELS[level]?.color) || RISK_LEVELS['数据不足'].color
}

export function riskLabel(level?: string | null): string {
  return (level && RISK_LEVELS[level]?.label) || level || '数据不足'
}

export function ruleLevelColor(level?: string | null): string {
  return (level && RULE_LEVELS[level]?.color) || RULE_LEVELS.gray.color
}

export function ruleLevelLabel(level?: string | null): string {
  return (level && RULE_LEVELS[level]?.label) || level || '数据不足'
}

/** 信用评级 AAA~C 颜色（沿用旧项目 gradeColor） */
export function gradeColor(grade?: string | null): string {
  switch (grade) {
    case 'AAA':
    case 'AA':
      return '#16a34a'
    case 'A':
      return '#65a30d'
    case 'BBB':
      return '#ca8a04'
    case 'BB':
      return '#ea580c'
    case 'C':
      return '#dc2626'
    default:
      return '#94a3b8'
  }
}

export function fmtPercent(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(1)}%`
}

export function fmtNum(v: number | null | undefined, nd = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toFixed(nd)
}

export function fmtTime(ts?: string | null): string {
  return ts ? new Date(ts).toLocaleString('zh-CN', { hour12: false }) : '-'
}

/** 模型语义：特征年 T → 标签年 T+2 的 ST 风险概率 */
export const MODEL_SEMANTICS = '特征年 T → 标签年 T+2 的 ST 风险概率'
