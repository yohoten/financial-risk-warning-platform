<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { EChartsOption } from 'echarts'

import BaseChart from '../components/BaseChart.vue'
import { api, type DependenceRow, type ImportanceRow, type InteractionRow } from '../api'
import { fmtNum } from '../lib/levels'
import { C, chartTheme } from '../lib/theme'

const loading = ref(false)
const error = ref('')
const importance = ref<ImportanceRow[]>([])
const dependence = ref<DependenceRow[]>([])
const interactions = ref<InteractionRow[]>([])
const feature = ref('')

const importanceOption = computed<EChartsOption>(() => {
  const rows = [...importance.value].reverse()
  const t = chartTheme()
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.tooltipText, fontSize: 11 },
    },
    grid: { left: 8, right: 28, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: 'value', axisLabel: { color: t.axisText } },
    yAxis: {
      type: 'category',
      data: rows.map((r) => r.中文名),
      axisLabel: { color: t.axisText, width: 130, overflow: 'truncate' },
    },
    series: [
      {
        type: 'bar',
        barWidth: 10,
        data: rows.map((r) => ({ value: r.importance, itemStyle: { color: C.primary } })),
      },
    ],
  }
})

const dependenceOption = computed<EChartsOption>(() => {
  const t = chartTheme()
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.tooltipText, fontSize: 11 },
      formatter: (p: unknown) => {
        const d = (p as { value?: [number, number] }).value
        return d ? `取值 ${fmtNum(d[0], 4)}<br/>SHAP ${fmtNum(d[1], 4)}` : ''
      },
    },
    grid: { left: 12, right: 24, top: 12, bottom: 12, containLabel: true },
    xAxis: { type: 'value', name: '特征取值', nameTextStyle: { color: t.axisText }, axisLabel: { color: t.axisText }, splitLine: { lineStyle: { color: t.splitLine } } },
    yAxis: { type: 'value', name: 'SHAP 值', nameTextStyle: { color: t.axisText }, axisLabel: { color: t.axisText }, splitLine: { lineStyle: { color: t.splitLine } } },
    series: [
      {
        type: 'scatter',
        symbolSize: 5,
        data: dependence.value.map((d) => [d.feature_value, d.shap_value]),
        itemStyle: { color: 'rgba(6,182,212,0.55)' },
      },
    ],
  }
})

async function loadBase() {
  loading.value = true
  error.value = ''
  try {
    const [imp, inter] = await Promise.all([api.globalImportance(20), api.interactions(8)])
    importance.value = imp.items
    interactions.value = inter.items
    if (!feature.value && imp.items.length) feature.value = imp.items[0].feature
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function loadDependence() {
  if (!feature.value) return
  try {
    dependence.value = (await api.dependence(feature.value)).items
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(loadBase)
watch(feature, loadDependence)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>模型解释</h2>
        <p class="page-sub">TreeSHAP 全局重要性 · 依赖效应 · 交互效应</p>
      </div>
      <button class="btn" :disabled="loading" @click="loadBase">{{ loading ? '加载中…' : '刷新' }}</button>
    </div>

    <p v-if="error" class="error-box">{{ error }}</p>

    <div class="card">
      <div class="card-title">全局特征重要性（mean|SHAP| TOP20）</div>
      <BaseChart v-if="importance.length" :option="importanceOption" height="420px" />
      <p v-else class="hint">暂无 SHAP 缓存，请先运行 python -m models.shap_analysis</p>
    </div>

    <div class="grid">
      <div class="card">
        <div class="card-title">
          特征依赖效应
          <select v-model="feature" class="toolbar-select" style="margin-left: 8px">
            <option v-for="r in importance" :key="r.feature" :value="r.feature">{{ r.中文名 }}</option>
          </select>
        </div>
        <BaseChart v-if="dependence.length" :option="dependenceOption" height="320px" />
        <p v-else class="hint">选择特征查看依赖效应（特征取值 vs SHAP 值）。</p>
      </div>

      <div class="card">
        <div class="card-title">特征交互强度（代理指标）</div>
        <table class="table">
          <thead>
            <tr>
              <th>特征 A</th>
              <th>特征 B</th>
              <th>交互强度</th>
              <th>相关系数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in interactions" :key="r.feature_a + r.feature_b">
              <td>{{ r.feature_a }}</td>
              <td>{{ r.feature_b }}</td>
              <td>{{ fmtNum(r.交互强度, 4) }}</td>
              <td>{{ fmtNum(r.相关系数, 3) }}</td>
            </tr>
            <tr v-if="!interactions.length">
              <td colspan="4" class="hint">暂无交互数据</td>
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
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  align-items: start;
}

@media (max-width: 1100px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
