<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { EChartsOption } from 'echarts'

import BaseChart from '../components/BaseChart.vue'
import { api, type ScoredRow } from '../api'
import { fmtPercent, riskColor } from '../lib/levels'
import { chartTheme } from '../lib/theme'

const router = useRouter()
const items = ref<ScoredRow[]>([])
const loading = ref(false)
const error = ref('')
const runId = ref('')

const sorted = computed(() => [...items.value].sort((a, b) => b.st_prob - a.st_prob))
const total = computed(() => items.value.length)
const highCount = computed(() => items.value.filter((i) => i.risk_level === '高风险').length)
const mediumCount = computed(() => items.value.filter((i) => i.risk_level === '中风险').length)
const industryCount = computed(() => new Set(items.value.map((i) => i.industry)).size)

const chartOption = computed<EChartsOption>(() => {
  const rows = sorted.value.slice(0, 12).reverse()
  const t = chartTheme()
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v) => fmtPercent(Number(v)),
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.tooltipText, fontSize: 11 },
    },
    grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
    xAxis: {
      type: 'value',
      max: 1,
      axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%`, color: t.axisText },
      splitLine: { lineStyle: { color: t.splitLine } },
    },
    yAxis: {
      type: 'category',
      data: rows.map((i) => i.company_name),
      axisLabel: { width: 140, overflow: 'truncate', color: t.axisText },
    },
    series: [
      {
        type: 'bar',
        barWidth: 14,
        data: rows.map((i) => ({ value: i.st_prob, itemStyle: { color: riskColor(i.risk_level) } })),
      },
    ],
  }
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const resp = await api.topRisk({ limit: 200 })
    items.value = resp.items
    runId.value = resp.run_id
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function open(code: string) {
  router.push(`/enterprise/${code}`)
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>数据看板</h2>
        <p class="page-sub">模型 run_id：{{ runId || '—' }} · 数据来自 /predict/top-risk</p>
      </div>
      <button class="btn" :disabled="loading" @click="load">{{ loading ? '加载中…' : '刷新' }}</button>
    </div>

    <p v-if="error" class="error-box">{{ error }}</p>

    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-icon">🏢</div>
        <div>
          <div class="stat-value">{{ total }}</div>
          <div class="stat-label">监测企业</div>
        </div>
      </div>
      <div class="stat-card tone-red">
        <div class="stat-icon">🔴</div>
        <div>
          <div class="stat-value">{{ highCount }}</div>
          <div class="stat-label">高风险</div>
        </div>
      </div>
      <div class="stat-card tone-orange">
        <div class="stat-icon">🟠</div>
        <div>
          <div class="stat-value">{{ mediumCount }}</div>
          <div class="stat-label">中风险</div>
        </div>
      </div>
      <div class="stat-card tone-cyan">
        <div class="stat-icon">🏭</div>
        <div>
          <div class="stat-value">{{ industryCount }}</div>
          <div class="stat-label">覆盖行业</div>
        </div>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <div class="card-title">高风险企业 TOP12</div>
        <BaseChart :option="chartOption" height="360px" />
      </div>

      <div class="card">
        <div class="card-title">风险排行</div>
        <table class="table">
          <thead>
            <tr>
              <th>代码</th>
              <th>企业名称</th>
              <th>行业</th>
              <th>年份</th>
              <th>ST 概率</th>
              <th>等级</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in sorted.slice(0, 15)" :key="row.stock_code" class="clickable" @click="open(row.stock_code)">
              <td>{{ row.stock_code }}</td>
              <td class="name">{{ row.company_name }}</td>
              <td>{{ row.industry }}</td>
              <td>{{ row.year }}</td>
              <td class="score-cell">{{ fmtPercent(row.st_prob) }}</td>
              <td>
                <span class="chip" :style="{ background: riskColor(row.risk_level) }">{{ row.risk_level }}</span>
              </td>
            </tr>
            <tr v-if="!items.length">
              <td colspan="6" class="hint">暂无数据，请确认后端服务已启动（uvicorn api.main:app --port 8000）</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 12px;
  align-items: start;
}

@media (max-width: 1100px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
