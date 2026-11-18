<script setup lang="ts">
/** 金融分析面板：KPI / 趋势 / 杜邦 / Z-F-M 模型 / 异常勾稽 / 同业对标（完整复刻旧项目） */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { EChartsOption } from 'echarts'

import { api, type FinanceAnalysis, type FinanceOverviewRow, type FinanceTrendSeries, type RulesVerdictResp, type ScoredRow } from '../api'
import BaseChart from '../components/BaseChart.vue'
import { fmtPercent, gradeColor, riskColor } from '../lib/levels'
import { globalFilter } from '../lib/store'
import { C, chartTheme } from '../lib/theme'

const route = useRoute()
const router = useRouter()
const currentCode = ref<string>('')
const overview = ref<FinanceOverviewRow[]>([])
const years = ref(globalFilter.financeYears)
const data = ref<FinanceAnalysis | null>(null)
const model = ref<ScoredRow | null>(null)
const rules = ref<RulesVerdictResp | null>(null)
const loading = ref(false)
const refreshing = ref(false)
const error = ref('')
const toast = ref('')
const query = ref('')
const pickerOpen = ref(false)

// 企业清单跨路由缓存：切换 tab 再回来时不再重复拉取/渲染 4000+ 条
let _overviewCache: Promise<FinanceOverviewRow[]> | null = null

const reportUrl = computed(() => (currentCode.value ? api.financeReportUrl(currentCode.value, years.value) : '#'))
const reportDownloadUrl = computed(() => (currentCode.value ? api.financeReportUrl(currentCode.value, years.value, true) : '#'))

const currentEnterprise = computed(() => overview.value.find((e) => e.stock_code === currentCode.value))
const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  const src = overview.value
  if (!q) return src.slice(0, 50)
  return src.filter((e) => e.name.toLowerCase().includes(q) || e.stock_code.includes(q)
    || (e.industry ?? '').toLowerCase().includes(q)).slice(0, 50)
})

async function loadOverview() {
  try {
    if (!_overviewCache) _overviewCache = api.financeOverview().then((r) => r.items)
    overview.value = await _overviewCache
    if (!currentCode.value) {
      currentCode.value = overview.value.find((x) => x.has_finance)?.stock_code ?? overview.value[0]?.stock_code ?? ''
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function load() {
  if (!currentCode.value) return
  loading.value = true
  error.value = ''
  data.value = null
  model.value = null
  rules.value = null
  try {
    data.value = await api.financeAnalysis(currentCode.value, years.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    loading.value = false
    return
  }
  try {
    model.value = (await api.predictCodes([currentCode.value])).items[0] ?? null
  } catch {
    model.value = null
  }
  try {
    rules.value = await api.riskRules(currentCode.value)
  } catch {
    rules.value = null
  }
  loading.value = false
}

async function refresh() {
  if (!currentCode.value) return
  refreshing.value = true
  toast.value = ''
  try {
    const r = await api.refreshEnterprise(currentCode.value)
    toast.value = r.ok ? '财务数据已刷新（东财实时快照）' : `刷新失败：${r.error || '未知原因'}`
  } catch (e) {
    toast.value = e instanceof Error ? e.message : String(e)
  } finally {
    refreshing.value = false
  }
}

function selectCode() {
  if (!currentCode.value) return
  router.replace(`/finance/${currentCode.value}`)
  load()
}

onMounted(async () => {
  if (route.params.code) currentCode.value = String(route.params.code)
  await loadOverview()
  await load()
})

watch(years, (v) => {
  globalFilter.financeYears = v
  load()
})
watch(
  () => route.params.code,
  (c) => {
    if (c && String(c) !== currentCode.value) {
      currentCode.value = String(c)
      load()
    }
  },
)

// ---------- 图表工具 ----------
const yearsAxis = computed(() => data.value?.data_quality.periods.map((p) => p.year) ?? [])

function seriesFor(key: string): FinanceTrendSeries | null {
  for (const g of Object.values(data.value?.trends ?? {})) {
    const s = g.series.find((x) => x.key === key)
    if (s) return s
  }
  return null
}

function mk(key: string, type: 'line' | 'bar', yAxisIndex = 0, color: string = C.primary) {
  const s = seriesFor(key)
  if (!s) return null
  return {
    name: `${s.label}${s.unit ? `(${s.unit})` : ''}`,
    type,
    yAxisIndex,
    data: s.points.map((p) => p.value),
    smooth: type === 'line',
    symbolSize: 6,
    connectNulls: false,
    itemStyle: { color },
    lineStyle: { width: 2, color },
    barMaxWidth: 26,
  }
}

function baseOption(series: any[], dual: [string, string] | null = null): EChartsOption {
  // 坐标轴/图例/tooltip 全部取自主题层，随浅色/深色自动切换
  const t = chartTheme()
  const ax = { fontSize: 11, color: t.axisText }
  const line = { color: t.splitLine }
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.tooltipText, fontSize: 11 },
      axisPointer: { lineStyle: { color: t.axisLine } },
    },
    legend: { top: 0, itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 11, color: t.axisText } },
    grid: { left: 52, right: dual ? 52 : 16, top: 32, bottom: 22 },
    xAxis: { type: 'category', data: yearsAxis.value, axisLabel: ax, axisLine: { lineStyle: line } },
    yAxis: dual
      ? [
          { type: 'value', name: dual[0], nameTextStyle: ax, axisLabel: ax, splitLine: { lineStyle: line } },
          { type: 'value', name: dual[1], nameTextStyle: ax, axisLabel: ax, splitLine: { show: false } },
        ]
      : [{ type: 'value', axisLabel: ax, splitLine: { lineStyle: line } }],
    series: series.filter(Boolean),
  }
}

const scaleOption = computed<EChartsOption>(() =>
  baseOption([mk('revenue', 'bar', 0, C.primary), mk('net_profit', 'line', 1, C.ok)], ['亿元', '亿元']),
)
const profitOption = computed<EChartsOption>(() =>
  baseOption([
    mk('gross_margin', 'line', 0, C.primary),
    mk('net_margin', 'line', 0, C.accent),
    mk('roe', 'line', 0, C.ok),
    mk('roa', 'line', 0, C.violet),
  ]),
)
const solvencyOption = computed<EChartsOption>(() =>
  baseOption([mk('debt_ratio', 'line', 0, C.danger), mk('current_ratio', 'line', 1, C.primary), mk('quick_ratio', 'line', 1, C.accent)], ['%', '倍']),
)
const operationOption = computed<EChartsOption>(() =>
  baseOption([mk('ar_days', 'line', 0, C.warn), mk('inventory_days', 'line', 0, C.violet), mk('asset_turnover', 'line', 1, C.primary)], ['天', '次']),
)
const cashflowOption = computed<EChartsOption>(() =>
  baseOption([mk('ocf', 'bar', 0, C.ok), mk('ocf_to_profit', 'line', 1, C.primary)], ['亿元', '倍']),
)
const growthOption = computed<EChartsOption>(() =>
  baseOption([mk('revenue_growth', 'bar', 0, C.primary), mk('profit_growth', 'bar', 0, C.accent)]),
)

const peerRadar = computed<EChartsOption>(() => {
  const p = data.value?.peers
  const self = p?.rows.find((r) => r.is_self)
  if (!p || !self?.percentiles) return {}
  const t = chartTheme()
  const keys = p.metrics.filter((m) => self.percentiles?.[m.key] != null)
  return {
    backgroundColor: 'transparent',
    tooltip: {
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.tooltipText, fontSize: 11 },
    },
    radar: {
      indicator: keys.map((m) => ({ name: m.label, max: 100 })),
      radius: '62%',
      center: ['50%', '54%'],
      axisName: { fontSize: 10, color: t.radarAxis },
      splitLine: { lineStyle: { color: t.radarSplit } },
      splitArea: { areaStyle: { color: t.radarArea } },
    },
    series: [{
      type: 'radar',
      symbolSize: 5,
      data: [{
        value: keys.map((m) => self.percentiles?.[m.key] ?? 0),
        name: '同业分位',
        areaStyle: { color: 'rgba(37,99,235,0.22)' },
        lineStyle: { color: C.primary, width: 2 },
        itemStyle: { color: C.primary },
      }],
    }],
  }
})

const attributionMax = computed(() => {
  const items = data.value?.dupont.attribution?.items ?? []
  return Math.max(1, ...items.map((i) => Math.abs(i.contrib)))
})

function fmt(v: number | null | undefined, unit = '') {
  if (v === null || v === undefined) return '—'
  return `${v}${unit}`
}

function verdictColor(kind: string, verdict: string | null | undefined) {
  if (!verdict) return C.gray
  if (kind === 'beneish') return verdict.includes('嫌疑') ? C.danger : C.ok
  if (verdict.includes('安全')) return C.ok
  if (verdict.includes('灰色')) return C.warn
  if (verdict.includes('困境')) return C.danger
  return C.gray
}

function fScoreColor(score: number | null, max: number) {
  if (score === null || !max) return C.gray
  const r = score / max
  return r >= 0.7 ? C.ok : r >= 0.4 ? C.warn : C.danger
}

const anomalyColor: Record<string, string> = { high: C.danger, medium: C.warn, low: C.gray }
const anomalyLabel: Record<string, string> = { high: '高', medium: '中', low: '低' }
</script>

<template>
  <div class="finance">
    <div class="bar">
      <div class="picker">
        <input
          v-model="query"
          class="sel picker-input"
          :placeholder="currentEnterprise ? `${currentEnterprise.name}（${currentEnterprise.stock_code}）` : '搜索企业名称 / 股票代码'"
          @focus="pickerOpen = true"
          @blur="pickerOpen = false"
        />
        <ul v-if="pickerOpen" class="picker-list">
          <li v-for="e in filtered" :key="e.stock_code" class="picker-item" @mousedown.prevent="currentCode = e.stock_code; query = ''; selectCode()">
            <span class="pi-name">{{ e.name }}</span>
            <span class="pi-code">{{ e.stock_code }}</span>
            <span class="pi-meta">{{ e.industry }} · {{ e.has_finance ? e.latest_year : '无财报' }}</span>
          </li>
          <li v-if="!filtered.length" class="picker-empty">无匹配企业</li>
        </ul>
      </div>
      <select v-model.number="years" class="sel sm">
        <option :value="3">近 3 年</option>
        <option :value="5">近 5 年</option>
        <option :value="8">近 8 年</option>
      </select>
      <button class="btn" :disabled="refreshing" @click="refresh">{{ refreshing ? '刷新中…' : '🔄 刷新' }}</button>
      <a class="btn ghost" :href="reportUrl" target="_blank" rel="noopener">📄 报告预览</a>
      <a class="btn ghost" :href="reportDownloadUrl" download>⬇ 报告下载</a>
    </div>

    <div v-if="toast" class="toast">{{ toast }}</div>
    <div v-if="error" class="err">{{ error }}</div>
    <div v-if="loading" class="hint">加载中…</div>

    <div v-else-if="!data" class="hint">选择一家企业开始分析</div>

    <div v-else-if="!data.available" class="empty">
      <div class="empty-title">无财务数据</div>
      <p>{{ data.reason }}</p>
      <p class="sub">可点击「🔄 刷新」拉取公开财报；非上市企业无公开财报数据。</p>
    </div>

    <template v-else>
      <section class="hero">
        <div class="hero-main">
          <div class="hero-name">{{ data.enterprise.name }}</div>
          <div class="hero-sub">
            {{ data.enterprise.industry || '未标注行业' }}
            <span v-if="data.enterprise.stock_code"> · {{ data.enterprise.stock_code }}</span>
            · 最新 {{ data.latest_year }} 年报 · {{ data.data_quality.years }} 期
          </div>
        </div>
        <div class="hero-chips">
          <span v-if="model" class="chip" :style="{ borderColor: riskColor(model.risk_level), color: riskColor(model.risk_level) }">
            模型 {{ fmtPercent(model.st_prob) }}
          </span>
          <span v-if="rules" class="chip" :style="{ borderColor: gradeColor(rules.grade), color: gradeColor(rules.grade) }">
            评级 {{ rules.grade }}（{{ rules.grade_label }}）
          </span>
          <span class="chip" :style="{ borderColor: verdictColor('altman', data.models.altman.z2.verdict), color: verdictColor('altman', data.models.altman.z2.verdict) }">
            Z'' {{ data.models.altman.z2.score ?? '—' }}
          </span>
          <span class="chip" :style="{ borderColor: fScoreColor(data.models.piotroski.score, data.models.piotroski.max_score), color: fScoreColor(data.models.piotroski.score, data.models.piotroski.max_score) }">
            F {{ data.models.piotroski.score ?? '—' }}/{{ data.models.piotroski.max_score }}
          </span>
          <span class="chip" :style="{ borderColor: verdictColor('beneish', data.models.beneish.verdict), color: verdictColor('beneish', data.models.beneish.verdict) }">
            M {{ data.models.beneish.score ?? '—' }}
          </span>
          <span class="chip" :style="{ borderColor: data.anomalies.length ? C.warn : C.ok, color: data.anomalies.length ? C.warn : C.ok }">
            异常 {{ data.anomalies.length }}
          </span>
        </div>
      </section>

      <section>
        <h4>关键指标</h4>
        <div class="kpi-grid">
          <div v-for="k in data.kpi" :key="k.key" class="kpi" :class="{ off: !k.available }">
            <div class="kpi-label">{{ k.label }}</div>
            <div class="kpi-value">{{ fmt(k.value) }}<span class="unit">{{ k.unit }}</span></div>
            <div class="kpi-foot">
              <span v-if="k.yoy !== null" class="yoy" :class="k.trend">
                {{ k.yoy > 0 ? '↑' : k.yoy < 0 ? '↓' : '—' }} {{ Math.abs(k.yoy) }}%
              </span>
              <span v-else class="yoy flat">无同比</span>
              <span class="prev" v-if="k.prev !== null">上期 {{ fmt(k.prev) }}</span>
            </div>
          </div>
        </div>
      </section>

      <section>
        <h4>趋势分析</h4>
        <div class="charts">
          <div class="chart-card"><div class="chart-title">规模与利润</div><BaseChart :option="scaleOption" height="220px" /></div>
          <div class="chart-card"><div class="chart-title">盈利能力（%）</div><BaseChart :option="profitOption" height="220px" /></div>
          <div class="chart-card"><div class="chart-title">偿债与杠杆</div><BaseChart :option="solvencyOption" height="220px" /></div>
          <div class="chart-card"><div class="chart-title">营运效率</div><BaseChart :option="operationOption" height="220px" /></div>
          <div class="chart-card"><div class="chart-title">现金流质量</div><BaseChart :option="cashflowOption" height="220px" /></div>
          <div class="chart-card"><div class="chart-title">成长性（%）</div><BaseChart :option="growthOption" height="220px" /></div>
        </div>
      </section>

      <section>
        <h4>杜邦分解</h4>
        <p class="formula">{{ data.dupont.formula }}</p>
        <table class="tbl">
          <thead>
            <tr><th>年度</th><th>ROE(%)</th><th>销售净利率(%)</th><th>总资产周转率</th><th>权益乘数</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in data.dupont.rows" :key="r.year">
              <td>{{ r.year }}</td>
              <td>{{ fmt(r.roe) }}</td>
              <td>{{ fmt(r.net_margin) }}</td>
              <td>{{ fmt(r.asset_turnover) }}</td>
              <td>{{ fmt(r.equity_multiplier) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="data.dupont.attribution" class="attr">
          <div class="attr-head">
            {{ data.dupont.attribution.from_year }} → {{ data.dupont.attribution.to_year }}
            ROE 变动 <b>{{ data.dupont.attribution.roe_delta }}</b> 个百分点，归因：
          </div>
          <div v-for="it in data.dupont.attribution.items" :key="it.key" class="attr-row">
            <span class="attr-label">{{ it.label }}</span>
            <div class="attr-bar"><i :style="{ width: `${(Math.abs(it.contrib) / attributionMax) * 100}%`, background: it.contrib >= 0 ? C.ok : C.danger }"></i></div>
            <span class="attr-val" :style="{ color: it.contrib >= 0 ? C.ok : C.danger }">{{ it.contrib > 0 ? '+' : '' }}{{ it.contrib }}</span>
          </div>
        </div>
      </section>

      <section>
        <h4>财务预警模型</h4>
        <div class="models">
          <div class="model" v-for="m in [
            { key: 'z2', title: 'Altman Z\'\'-Score', sub: '非制造业/新兴市场口径', score: data.models.altman.z2.score, verdict: data.models.altman.z2.verdict, thresholds: data.models.altman.z2.thresholds, missing: data.models.altman.z2.missing, note: data.models.altman.z2.note },
            { key: 'z', title: 'Altman Z-Score', sub: '上市制造业口径（需市值）', score: data.models.altman.z.score, verdict: data.models.altman.z.verdict, thresholds: data.models.altman.z.thresholds, missing: data.models.altman.z.missing, note: data.models.altman.z.note },
          ]" :key="m.key">
            <div class="model-head">
              <span class="model-title">{{ m.title }}</span>
              <span class="model-score" :style="{ color: verdictColor('altman', m.verdict) }">{{ m.score ?? '不可计算' }}</span>
            </div>
            <div class="model-sub">{{ m.sub }}</div>
            <div v-if="m.verdict" class="model-verdict" :style="{ color: verdictColor('altman', m.verdict) }">{{ m.verdict }}</div>
            <div class="model-thresholds">{{ m.thresholds }}</div>
            <div v-if="!m.score && m.missing?.length" class="model-missing">缺：{{ m.missing.join('、') }}</div>
          </div>

          <div class="model">
            <div class="model-head">
              <span class="model-title">Piotroski F-Score</span>
              <span class="model-score" :style="{ color: fScoreColor(data.models.piotroski.score, data.models.piotroski.max_score) }">
                {{ data.models.piotroski.score ?? '—' }}/{{ data.models.piotroski.max_score }}
              </span>
            </div>
            <div class="model-sub">{{ data.models.piotroski.verdict || '需要连续两期财报' }}</div>
            <ul class="signals">
              <li v-for="s in data.models.piotroski.signals" :key="s.name" :class="{ fail: s.pass === false, na: s.pass === null }">
                <span class="sig-icon">{{ s.pass === true ? '✓' : s.pass === false ? '✗' : '·' }}</span>
                <span class="sig-name">{{ s.name }}</span>
                <span class="sig-detail">{{ s.detail }}</span>
              </li>
            </ul>
            <div v-if="data.models.piotroski.note" class="model-note">{{ data.models.piotroski.note }}</div>
          </div>

          <div class="model">
            <div class="model-head">
              <span class="model-title">Beneish M-Score</span>
              <span class="model-score" :style="{ color: verdictColor('beneish', data.models.beneish.verdict) }">
                {{ data.models.beneish.score ?? '不可计算' }}
              </span>
            </div>
            <div class="model-sub" :style="{ color: verdictColor('beneish', data.models.beneish.verdict) }">
              {{ data.models.beneish.verdict || '需要连续两期财报' }}
            </div>
            <div class="model-thresholds">{{ data.models.beneish.thresholds }}</div>
            <ul class="signals">
              <li v-for="i in data.models.beneish.indices" :key="i.key" :class="{ na: i.value === null }">
                <span class="sig-icon">{{ i.value === null ? '·' : i.source === 'approx' ? '≈' : '•' }}</span>
                <span class="sig-name">{{ i.label }}</span>
                <span class="sig-detail">{{ i.value ?? '缺' }}</span>
              </li>
            </ul>
            <div v-if="data.models.beneish.note" class="model-note">{{ data.models.beneish.note }}</div>
          </div>
        </div>
      </section>

      <section>
        <h4>异常勾稽</h4>
        <div v-if="!data.anomalies.length" class="hint ok-hint">在现有数据范围内未触发异常规则</div>
        <div v-for="a in data.anomalies" :key="a.code" class="anomaly" :style="{ borderLeftColor: anomalyColor[a.level] }">
          <div class="anomaly-head">
            <span class="lvl" :style="{ background: anomalyColor[a.level] }">{{ anomalyLabel[a.level] }}</span>
            <span class="anomaly-title">{{ a.title }}</span>
          </div>
          <div class="anomaly-detail">{{ a.detail }}</div>
        </div>
      </section>

      <section v-if="data.peers && data.peers.rows.length > 1">
        <h4>同业对标</h4>
        <div class="peer-note">{{ data.peers.note }}</div>
        <div class="peer-wrap">
          <div class="peer-radar"><BaseChart :option="peerRadar" height="240px" /></div>
          <div class="peer-tbl-wrap">
            <table class="tbl">
              <thead>
                <tr><th>企业</th><th v-for="m in data.peers.metrics" :key="m.key">{{ m.label }}</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in data.peers.rows" :key="r.stock_code" :class="{ self: r.is_self }">
                  <td>{{ r.name }}</td>
                  <td v-for="m in data.peers.metrics" :key="m.key">
                    {{ fmt(r.metrics[m.key]) }}
                    <span v-if="r.percentiles && r.percentiles[m.key] != null" class="pct"
                      :style="{ color: (r.percentiles[m.key] ?? 0) >= 75 ? C.ok : (r.percentiles[m.key] ?? 0) <= 25 ? C.danger : C.gray }">{{ r.percentiles[m.key] }}%</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section class="quality">
        <h4>数据说明</h4>
        <div class="q-row"><span class="q-key">来源</span><span>{{ [...new Set(data.data_quality.periods.map((p) => p.source))].join('；') || '—' }}</span></div>
        <div class="q-row" v-if="data.data_quality.missing_metrics.length"><span class="q-key">全期缺失</span><span>{{ data.data_quality.missing_metrics.join('、') }}</span></div>
        <div class="q-row" v-for="(n, i) in data.data_quality.notes" :key="i"><span class="q-key">提示</span><span>{{ n }}</span></div>
        <p class="disclaimer">数据来自公开信源，模型结果为规则化测算，不构成投资建议。</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.finance { color: var(--text); font-size: 13px; }
.bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
.sel { flex: 1; min-width: 140px; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-elev); color: var(--text); font-size: 12.5px; }
.sel.sm { flex: 0 0 auto; min-width: 88px; }
.picker { position: relative; flex: 1; min-width: 200px; }
.picker-input { width: 100%; }
.picker-list { position: absolute; top: calc(100% + 4px); left: 0; right: 0; max-height: 320px; overflow-y: auto; margin: 0; padding: 4px; list-style: none; background: var(--bg-elev); border: 1px solid var(--border); border-radius: 8px; box-shadow: var(--shadow); z-index: 40; }
.picker-item { display: flex; align-items: baseline; gap: 8px; padding: 7px 10px; border-radius: 6px; cursor: pointer; font-size: 12.5px; }
.picker-item:hover { background: var(--hover); }
.pi-name { font-weight: 600; }
.pi-code { color: var(--primary); font-size: 11px; flex: none; }
.pi-meta { margin-left: auto; color: var(--text-sub); font-size: 11px; }
.picker-empty { padding: 8px 10px; color: var(--text-sub); font-size: 12px; }
.btn { padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-elev); color: var(--text); cursor: pointer; font-size: 12.5px; text-decoration: none; }
.btn:hover { background: var(--hover); }
.btn:disabled { opacity: 0.6; cursor: default; }
.btn.ghost { color: var(--primary); border-color: var(--primary); }
.toast { margin: 6px 0; padding: 6px 10px; border-radius: 6px; background: var(--hover); color: var(--text-sub); font-size: 12px; }
.err { margin: 8px 0; color: var(--danger); }
.hint { color: var(--text-sub); padding: 12px 0; }
.ok-hint { color: var(--ok); }
.empty { padding: 18px; border: 1px dashed var(--border); border-radius: 8px; }
.empty-title { font-weight: 600; margin-bottom: 6px; }
.empty .sub { color: var(--text-sub); font-size: 12px; }

.hero { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--card); box-shadow: var(--shadow); margin-bottom: 14px; }
.hero-name { font-size: 15px; font-weight: 600; }
.hero-sub { color: var(--text-sub); font-size: 12px; margin-top: 2px; }
.hero-chips { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.chip { padding: 3px 8px; border: 1px solid var(--border); border-radius: 999px; font-size: 11.5px; white-space: nowrap; }

section { margin-bottom: 16px; }
h4 { margin: 0 0 8px; font-size: 13px; font-weight: 600; color: var(--text); border-left: 3px solid var(--primary); padding-left: 8px; }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(126px, 1fr)); gap: 8px; }
.kpi { padding: 8px 10px; border: 1px solid var(--border-soft); border-radius: 8px; background: var(--card); }
.kpi.off { opacity: 0.5; }
.kpi-label { color: var(--text-sub); font-size: 11.5px; }
.kpi-value { font-size: 16px; font-weight: 600; margin: 3px 0; }
.kpi-value .unit { font-size: 10.5px; color: var(--text-sub); margin-left: 3px; font-weight: 400; }
.kpi-foot { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-sub); }
.yoy.up { color: var(--ok); }
.yoy.down { color: var(--danger); }
.yoy.flat { color: var(--text-sub); }

.charts { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px; }
.chart-card { border: 1px solid var(--border-soft); border-radius: 8px; padding: 8px 6px 2px; background: var(--card); }
.chart-title { font-size: 12px; color: var(--text-sub); padding-left: 8px; }

.formula { color: var(--text-sub); font-size: 12px; margin: 0 0 6px; }
.tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
.tbl th, .tbl td { border-bottom: 1px solid var(--border-soft); padding: 5px 6px; text-align: right; }
.tbl th:first-child, .tbl td:first-child { text-align: left; }
.tbl th { color: var(--text-sub); font-weight: 500; }
.tbl tr.self { background: var(--hover); font-weight: 600; }
.pct { font-size: 10.5px; color: var(--text-sub); margin-left: 3px; }

.attr { margin-top: 10px; }
.attr-head { font-size: 12px; color: var(--text-sub); margin-bottom: 6px; }
.attr-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; font-size: 12px; }
.attr-label { flex: 0 0 108px; color: var(--text-sub); }
.attr-bar { flex: 1; height: 8px; background: var(--hover); border-radius: 4px; overflow: hidden; }
.attr-bar i { display: block; height: 100%; }
.attr-val { flex: 0 0 46px; text-align: right; }

.models { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
.model { border: 1px solid var(--border-soft); border-radius: 8px; padding: 9px 10px; background: var(--card); }
.model-head { display: flex; justify-content: space-between; align-items: baseline; }
.model-title { font-weight: 600; font-size: 12.5px; }
.model-score { font-size: 15px; font-weight: 700; }
.model-sub { color: var(--text-sub); font-size: 11.5px; margin: 2px 0 4px; }
.model-verdict { font-size: 12px; font-weight: 600; margin-bottom: 3px; }
.model-thresholds { color: var(--text-sub); font-size: 11px; }
.model-missing { color: var(--warn); font-size: 11px; margin-top: 3px; }
.model-note { color: var(--warn); font-size: 11px; margin-top: 5px; }
.signals { list-style: none; padding: 0; margin: 6px 0 0; }
.signals li { display: flex; gap: 5px; font-size: 11.5px; padding: 2px 0; align-items: baseline; }
.signals li.fail .sig-name { color: var(--danger); }
.signals li.na { opacity: 0.55; }
.sig-icon { width: 12px; text-align: center; }
.sig-name { flex: 0 0 auto; }
.sig-detail { color: var(--text-sub); margin-left: auto; text-align: right; }

.anomaly { border: 1px solid var(--border-soft); border-left: 3px solid var(--warn); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; background: var(--card); }
.anomaly-head { display: flex; gap: 6px; align-items: center; }
.lvl { color: #fff; font-size: 10.5px; padding: 1px 6px; border-radius: 4px; }
.anomaly-title { font-weight: 600; font-size: 12.5px; }
.anomaly-detail { color: var(--text-sub); font-size: 12px; margin-top: 4px; line-height: 1.55; }

.peer-note { color: var(--text-sub); font-size: 11.5px; margin-bottom: 8px; }
.peer-wrap { display: grid; grid-template-columns: minmax(220px, 1fr) minmax(280px, 1.6fr); gap: 10px; }
@media (max-width: 900px) { .peer-wrap { grid-template-columns: 1fr; } }
.peer-tbl-wrap { overflow-x: auto; }

.quality { border-top: 1px dashed var(--border); padding-top: 10px; }
.q-row { display: flex; gap: 8px; font-size: 11.5px; color: var(--text-sub); margin-bottom: 3px; }
.q-key { flex: 0 0 56px; color: var(--text); }
.disclaimer { color: var(--text-sub); font-size: 11px; margin-top: 8px; font-style: italic; }
</style>
