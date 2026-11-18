/**
 * 统一主题层：配色常量 + 主题感知（浅色/深色）。
 *
 * 设计约定：
 *  1. `C` 是旧项目 risk-warning-platform 的配色常量，作为全站唯一色源；
 *     各 view 不再各自声明一份，避免改主题要改 N 处。
 *  2. 结构性颜色（文字、边框、卡片底）一律从 CSS 变量读取，
 *     这样 ECharts 坐标轴/图例/雷达分割线能随 data-theme 自动切换，
 *     不会再出现「深色卡片上画着浅色轴线」或反之的不可读问题。
 *  3. `themeVersion` 是一个 ref：主题切换时自增，依赖它的 computed 会重算，
 *     ECharts 实例随之重建。
 */
import { ref } from 'vue'

/** 旧项目配色常量（primary / ok / warn / danger …），全站唯一来源 */
export const C = {
  primary: '#2563eb',
  primaryDeep: '#1e40af',
  accent: '#06b6d4',
  ok: '#16a34a',
  warn: '#d97706',
  danger: '#dc2626',
  gray: '#94a3b8',
  violet: '#7c3aed',
} as const

/** 主题版本号：data-theme 变化时自增 */
export const themeVersion = ref(0)

/** 结构性颜色（随主题变化，从 CSS 变量取值） */
export interface ThemeTokens {
  text: string
  textSub: string
  border: string
  borderSoft: string
  card: string
  bgElev: string
  hover: string
  isDark: boolean
}

function cssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

/** 读取当前主题的结构性颜色 */
export function themeTokens(): ThemeTokens {
  const isDark = document?.documentElement?.dataset?.theme === 'dark'
  return {
    text: cssVar('--text', '#1f2937'),
    textSub: cssVar('--text-sub', '#6b7280'),
    border: cssVar('--border', '#e5e9f2'),
    borderSoft: cssVar('--border-soft', '#eef1f7'),
    card: cssVar('--card', '#ffffff'),
    bgElev: cssVar('--bg-elev', '#ffffff'),
    hover: cssVar('--hover', '#f8fafc'),
    isDark,
  }
}

/** 图表专用配色包：坐标轴/图例/分割线/tooltip 全部随主题切换 */
export function chartTheme() {
  // 依赖 themeVersion，主题切换时触发依赖重算
  void themeVersion.value
  const t = themeTokens()
  return {
    /** 坐标轴刻度文字、图例文字 */
    axisText: t.textSub,
    /** 坐标轴轴线 */
    axisLine: t.border,
    /** 网格分割线 */
    splitLine: t.borderSoft,
    /** 图表背景（跟随卡片） */
    background: t.card,
    /** 文本主色 */
    text: t.text,
    /** tooltip 背景与描边 */
    tooltipBg: t.isDark ? 'rgba(17,26,46,0.96)' : 'rgba(255,255,255,0.98)',
    tooltipBorder: t.border,
    tooltipText: t.text,
    /** 雷达轴名 */
    radarAxis: t.textSub,
    /** 雷达分割线 */
    radarSplit: t.isDark ? 'rgba(148,163,184,0.28)' : 'rgba(100,116,139,0.24)',
    /** 雷达交替底色 */
    radarArea: t.isDark
      ? ['rgba(37,99,235,0.03)', 'rgba(37,99,235,0.06)']
      : ['rgba(37,99,235,0.02)', 'rgba(37,99,235,0.05)'],
    isDark: t.isDark,
  }
}

/** 安装主题监听：data-theme 属性变化时自增 themeVersion 并通知订阅者 */
export function initThemeWatcher(onChange?: () => void): void {
  if (typeof document === 'undefined' || typeof MutationObserver === 'undefined') return
  const apply = () => {
    themeVersion.value += 1
    onChange?.()
  }
  const observer = new MutationObserver(apply)
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  })
}
