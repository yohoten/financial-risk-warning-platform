<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { EChartsOption } from 'echarts'

import BaseChart from '../components/BaseChart.vue'
import { api, type FinanceAnalysis, type FinanceKpi, type FinanceOverviewRow, type FinanceTrendGroup } from '../api'
import { fmtNum } from '../lib/levels'

const route = useRoute()
const router = useRouter()
const code = computed(() => String(route.params.code || ''))
const loading = ref(false)
const error = ref('')
const analysis = ref<FinanceAnalysis | null>(null)
const overview = ref<FinanceOverviewRow[]>([])
const inputCode = ref('')
const keyword = ref('')

const filteredOverview = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return overview.value
  return overview.value.filter(
    (r) => r.name.toLowerCase().includes(k) || r.stock_code.includes(k) || r.industry.toLowerCase().includes(k),
  )
})

const groupKpis = computed<Record<string, FinanceKpi[]>>(() => {
  const out: Record<string, FinanceKpi[]> = {}
  for (const kpi of analysis.value?.kpi ?? []) {
    if (!out[kpi.group]) out[kpi.group] = []
    out[kpi.group].push(kpi)
  }
  return out
})

const groupLabels: Record<string, string> = {
  scale: '规模', profit: '盈利能力', solvency: '偿债与杠杆',
  operation: '营运效率', cashflow: '现金流质量', growth: '成长性',
}

function trendColor(kpi: FinanceKpi): string {
  if (kpi.trend === 'up') return '#16a34a'
  if (kpi.trend === 'down') return '#dc2626'
  return '#94a3b8'
}

function trendArrow(kpi: FinanceKpi): string {
  if (kpi.trend === 'up') return '↑'
  if (kpi.trend === 'down') return '↓'
  return '→'
}

function buildTrendOption(g: FinanceTrendGroup): EChartsOption {
  const years = [...new Set(g.series.flatMap((s) => s.points.map((p) => p.year)))].sort()
  return {
    tooltip: { trigger: 'axis' },
    legend: { textStyle: { color: '#94a3b8', fontSize: 11 }, top: 0 },
    grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },
    xAxis: { type: 'category', data: years, axisLabel: { color: '#94a3b8' } },
    yAxis: { type: 'value', axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: '#24314f' } } },
    series: g.series.map((s) => ({
      name: s.label,
      type: 'line',
      smooth: true,
      symbolSize: 5,
      data: years.map((y) => s.points.find((p) => p.year === y)?.value ?? null),
    })),
  }
}

const trendCharts = computed(() =>
  Object.entries(analysis.value?.trends ?? {}).map(([key, g]) => ({ key, label: g.label, option: buildTrendOption(g) })),
)

const peerRadar = computed<EChartsOption>(() => {
  const peers = analysis.value?.peers
  if (!peers) return {}
  const self = peers.rows.find((r) => r.is_self)
  return {
    tooltip: {},
    radar: {
      indicator: peers.metrics.map((m) => ({ name: m.label, max: 100 })),
      radius: '60%',
      axisName: { color: '#94a3b8', fontSize: 11 },
      splitLine: { lineStyle: { color: '#24314f' } },
      splitArea: { areaStyle: { color: ['transparent'] } },
      axisLine: { lineStyle: { color: '#24314f' } },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: peers.metrics.map((m) => self?.percentiles[m.key] ?? 0),
            name: '本企业分位（越高越好）',
            areaStyle: { color: 'rgba(37,99,235,0.22)' },
            lineStyle: { color: '#2563eb', width: 2 },
            itemStyle: { color: '#2563eb' },
          },
        ],
      },
    ],
  }
})

function anomalyColor(level: string): string {
  if (level === 'high') return '#dc2626'
  if (level === 'medium') return '#ea580c'
  return '#16a34a'
}

function passIcon(pass: boolean | null): string {
  if (pass === true) return '✓'
  if (pass === false) return '✗'
  return '?'
}

async function loadAnalysis() {
  if (!code.value) return
  loading.value = true
  error.value = ''
  try {
    analysis.value = await api.financeAnalysis(code.value)
    overview.value = []
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function loadOverview() {
  loading.value = true
  error.value = ''
  try {
    overview.value = (await api.financeOverview()).items
    analysis.value = null
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function goto(code: string) {
  router.push(`/finance/${code}`)
}

function submit() {
  const c = inputCode.value.trim().replace(/\.0$/, '').padStart(6, '0')
  if (/^\d{6}$/.test(c)) goto(c)
}

onMounted(() => (code.value ? loadAnalysis() : loadOverview()))
watch(code, (c) => (c ? loadAnalysis() : loadOverview()))
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>财务分析</h2>
        <p class="page-sub">
          <template v-if="analysis">
            {{ analysis.enterprise.name }}（{{ analysis.enterprise.stock_code }}）· {{ analysis.enterprise.industry }} · 最新 {{ analysis.latest_year }}
          </template>
          <template v-else>KPI · 趋势 · 杜邦分解 · Altman/Piotroski/Beneish · 同业对标 · 异常勾稽</template>
        </p>
      </div>
      <div class="toolbar">
        <input v-model="inputCode" class="toolbar-input" placeholder="证券代码" @keyup.enter="submit" />
        <button class="btn" @click="submit">分析</button>
        <a v-if="code" class="btn" :href="api.financeReportUrl(code)" target="_blank">下载报告</a>
      </div>
    </div>

    <p v-if="error" class="error-box">{{ error }}</p>

    <!-- 列表模式 -->
    <div v-if="!code" class="card">
      <div class="toolbar" style="margin-bottom: 8px">
        <input v-model="keyword" class="toolbar-input" placeholder="按名称 / 代码 / 行业筛选" />
      </div>
      <table class="table">
        <thead>
          <tr>
            <th>代码</th><th>企业名称</th><th>行业</th><th>营收(亿)</th><th>净利(亿)</th>
            <th>营收增速</th><th>ROE</th><th>资产负债率</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in filteredOverview" :key="r.stock_code" class="clickable" @click="goto(r.stock_code)">
            <td>{{ r.stock_code }}</td>
            <td class="name">{{ r.name }}</td>
            <td>{{ r.industry }}</td>
            <td>{{ fmtNum(r.revenue) }}</td>
            <td>{{ fmtNum(r.net_profit) }}</td>
            <td>{{ r.revenue_growth != null ? r.revenue_growth.toFixed(1) + '%' : '—' }}</td>
            <td>{{ r.roe != null ? r.roe.toFixed(1) + '%' : '—' }}</td>
            <td>{{ r.debt_ratio != null ? r.debt_ratio.toFixed(1) + '%' : '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 分析详情模式 -->
    <template v-else-if="analysis">
      <div v-if="!analysis.available" class="card">
        <p class="hint">{{ analysis.reason || '无财务数据' }}</p>
      </div>

      <template v-else>
        <!-- KPI -->
        <div v-for="(kpis, g) in groupKpis" :key="g" class="card">
          <div class="card-title">{{ groupLabels[g] ?? g }}</div>
          <div class="kpi-grid">
            <div v-for="kpi in kpis" :key="kpi.key" class="kpi">
              <div class="kpi-label">{{ kpi.label }}</div>
              <div class="kpi-value">
                {{ kpi.value != null ? fmtNum(kpi.value) + ' ' + kpi.unit : '—' }}
              </div>
              <div class="kpi-yoy" v-if="kpi.value != null">
                <span :style="{ color: trendColor(kpi) }">
                  {{ trendArrow(kpi) }} 同比 {{ kpi.yoy != null ? kpi.yoy.toFixed(1) + '%' : '—' }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 趋势 -->
        <div class="grid">
          <div v-for="tc in trendCharts" :key="tc.key" class="card">
            <div class="card-title">{{ tc.label }}</div>
            <BaseChart :option="tc.option" height="240px" />
          </div>
        </div>

        <!-- 杜邦 -->
        <div class="card">
          <div class="card-title">杜邦分解：{{ analysis.dupont.formula }}</div>
          <table class="table">
            <thead>
              <tr><th>年份</th><th>ROE(%)</th><th>净利率(%)</th><th>周转率</th><th>权益乘数</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in analysis.dupont.rows" :key="row.year">
                <td>{{ row.year }}</td>
                <td>{{ fmtNum(row.roe) }}</td>
                <td>{{ fmtNum(row.net_margin) }}</td>
                <td>{{ fmtNum(row.asset_turnover, 4) }}</td>
                <td>{{ fmtNum(row.equity_multiplier, 4) }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="analysis.dupont.attribution" class="attribution">
            <p class="hint">
              ROE 变动 {{ analysis.dupont.attribution.from_year }}→{{ analysis.dupont.attribution.to_year }}：
              {{ fmtNum(analysis.dupont.attribution.roe_delta) }} 个百分点
            </p>
            <div v-for="it in analysis.dupont.attribution.items" :key="it.key" class="att-row">
              <span class="att-label">{{ it.label }}</span>
              <div class="att-bar">
                <div class="att-fill" :style="{ width: Math.min(Math.abs(it.contrib) * 4, 100) + '%', background: it.contrib >= 0 ? '#dc2626' : '#16a34a' }"></div>
              </div>
              <span class="att-val">{{ it.contrib >= 0 ? '+' : '' }}{{ fmtNum(it.contrib) }}pp</span>
            </div>
          </div>
        </div>

        <!-- 财务预警模型 -->
        <div class="grid3">
          <div class="card">
            <div class="card-title">Altman Z-Score</div>
            <p v-if="!analysis.models.altman.z.available" class="hint">{{ analysis.models.altman.z.note }}</p>
            <template v-else>
              <div class="model-score">{{ fmtNum(analysis.models.altman.z.score, 3) }}</div>
              <p class="hint">{{ analysis.models.altman.z.verdict }} · {{ analysis.models.altman.z.thresholds }}</p>
            </template>
            <p class="hint">
              Z''-Score：
              <template v-if="analysis.models.altman.z2.available">
                {{ fmtNum(analysis.models.altman.z2.score, 3) }}（{{ analysis.models.altman.z2.verdict }}）
              </template>
              <template v-else>{{ analysis.models.altman.z2.note }}</template>
            </p>
          </div>

          <div class="card">
            <div class="card-title">Piotroski F-Score</div>
            <p v-if="!analysis.models.piotroski.available" class="hint">{{ analysis.models.piotroski.reason ?? '不可用' }}</p>
            <template v-else>
              <div class="model-score">{{ analysis.models.piotroski.score }}<span class="hint"> / {{ analysis.models.piotroski.max_score }}</span></div>
              <p class="hint">{{ analysis.models.piotroski.verdict }}</p>
            </template>
            <ul class="signal-list">
              <li v-for="s in analysis.models.piotroski.signals" :key="s.name">
                <span class="pass" :style="{ color: s.pass === true ? '#16a34a' : s.pass === false ? '#dc2626' : '#94a3b8' }">{{ passIcon(s.pass) }}</span>
                <span>{{ s.name }}</span>
              </li>
            </ul>
          </div>

          <div class="card">
            <div class="card-title">Beneish M-Score</div>
            <p v-if="!analysis.models.beneish.available" class="hint">不可用：{{ analysis.models.beneish.missing.join('、') }}</p>
            <template v-else>
              <div class="model-score">{{ fmtNum(analysis.models.beneish.score, 3) }}</div>
              <p class="hint">{{ analysis.models.beneish.verdict }}</p>
            </template>
            <p v-if="analysis.models.beneish.note" class="hint">{{ analysis.models.beneish.note }}</p>
          </div>
        </div>

        <!-- 同业对标 -->
        <div class="grid">
          <div class="card" v-if="analysis.peers?.rows.length">
            <div class="card-title">同业对标（{{ analysis.peers.industry }}）</div>
            <BaseChart :option="peerRadar" height="300px" />
            <p class="hint">{{ analysis.peers.note }}</p>
          </div>
          <div class="card">
            <div class="card-title">异常勾稽信号</div>
            <ul v-if="analysis.anomalies.length" class="anomaly-list">
              <li v-for="a in analysis.anomalies" :key="a.code">
                <span class="chip" :style="{ background: anomalyColor(a.level) }">{{ a.level }}</span>
                <div>
                  <div class="a-title">{{ a.title }}</div>
                  <div class="a-detail">{{ a.detail }}</div>
                </div>
              </li>
            </ul>
            <p v-else class="hint">未发现明显异常勾稽信号。</p>
          </div>
        </div>

        <div class="card" v-if="analysis.data_quality.notes.length">
          <div class="card-title">数据质量说明</div>
          <ul class="hint">
            <li v-for="(n, i) in analysis.data_quality.notes" :key="i">{{ n }}</li>
          </ul>
        </div>
      </template>
    </template>

    <p v-else-if="!loading" class="hint">输入证券代码开始财务分析。</p>
  </div>
</template>

<style scoped>
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.kpi {
  border: 1px solid var(--border-soft);
  border-radius: 8px;
  padding: 10px 12px;
}

.kpi-label {
  font-size: 12px;
  color: var(--text-sub);
}

.kpi-value {
  font-size: 18px;
  font-weight: 700;
  margin: 2px 0;
}

.kpi-yoy {
  font-size: 11.5px;
}

.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  align-items: start;
}

.grid3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  align-items: start;
}

.attribution {
  margin-top: 10px;
}

.att-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 6px 0;
}

.att-label {
  width: 120px;
  font-size: 12.5px;
  color: var(--text-sub);
}

.att-bar {
  flex: 1;
  height: 8px;
  background: var(--border-soft);
  border-radius: 999px;
  overflow: hidden;
}

.att-fill {
  height: 100%;
  border-radius: 999px;
}

.att-val {
  width: 80px;
  font-size: 12px;
  text-align: right;
}

.model-score {
  font-size: 26px;
  font-weight: 700;
}

.signal-list,
.anomaly-list {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12.5px;
}

.signal-list li {
  display: flex;
  gap: 8px;
  align-items: baseline;
}

.pass {
  font-weight: 700;
  width: 16px;
}

.anomaly-list li {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  border-bottom: 1px dashed var(--border-soft);
  padding-bottom: 6px;
}

.a-title {
  font-weight: 600;
}

.a-detail {
  font-size: 12px;
  color: var(--text-sub);
}

@media (max-width: 1100px) {
  .kpi-grid,
  .grid,
  .grid3 {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 700px) {
  .kpi-grid,
  .grid,
  .grid3 {
    grid-template-columns: 1fr;
  }
}
</style>
