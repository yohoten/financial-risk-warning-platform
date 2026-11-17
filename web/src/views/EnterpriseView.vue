<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import type { EChartsOption } from 'echarts'

import BaseChart from '../components/BaseChart.vue'
import { api, type AnalyzeResp, type ExplainResp, type RulesVerdictResp, type ScoredRow } from '../api'
import { fmtPercent, fmtNum, gradeColor, riskColor, ruleLevelColor, ruleLevelLabel } from '../lib/levels'

const route = useRoute()
const code = computed(() => String(route.params.code || ''))
const loading = ref(false)
const error = ref('')
const score = ref<ScoredRow | null>(null)
const explain = ref<ExplainResp | null>(null)
const rules = ref<RulesVerdictResp | null>(null)
const analyzeResp = ref<AnalyzeResp | null>(null)
const analyzing = ref(false)

const radarOption = computed<EChartsOption>(() => {
  const dims = Object.entries(rules.value?.dimensions ?? {})
  return {
    tooltip: {},
    radar: {
      indicator: dims.map(([, v]) => ({ name: v.label, max: 100 })),
      radius: '62%',
      axisName: { color: '#94a3b8', fontSize: 12 },
      splitLine: { lineStyle: { color: '#24314f' } },
      splitArea: { areaStyle: { color: ['transparent'] } },
      axisLine: { lineStyle: { color: '#24314f' } },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: dims.map(([, v]) => v.score ?? 0),
            name: '规则六维评分',
            areaStyle: { color: 'rgba(37,99,235,0.25)' },
            lineStyle: { color: '#2563eb', width: 2 },
            itemStyle: { color: '#2563eb' },
          },
        ],
      },
    ],
  }
})

const shapOption = computed<EChartsOption>(() => {
  const rows = [...(explain.value?.contributions ?? [])].reverse()
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 8, right: 28, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: 'value', axisLabel: { color: '#94a3b8' } },
    yAxis: {
      type: 'category',
      data: rows.map((r) => r.中文名),
      axisLabel: { color: '#94a3b8', width: 130, overflow: 'truncate' },
    },
    series: [
      {
        type: 'bar',
        barWidth: 12,
        data: rows.map((r) => ({
          value: r.SHAP值,
          itemStyle: { color: r.SHAP值 >= 0 ? '#dc2626' : '#16a34a' },
        })),
      },
    ],
  }
})

const dimList = computed(() =>
  Object.entries(rules.value?.dimensions ?? {}).map(([key, d]) => ({ key, ...d })),
)

async function load() {
  if (!code.value) return
  loading.value = true
  error.value = ''
  score.value = null
  explain.value = null
  rules.value = null
  analyzeResp.value = null
  try {
    const [p, e, r] = await Promise.all([
      api.predictCodes([code.value]),
      api.explain(code.value),
      api.riskRules(code.value),
    ])
    score.value = p.items[0] ?? null
    explain.value = e
    rules.value = r
    if (!p.items.length) error.value = `证券代码 ${code.value} 未在评分结果中`
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function runAnalyze() {
  if (!code.value) return
  analyzing.value = true
  try {
    analyzeResp.value = await api.analyze(code.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    analyzing.value = false
  }
}

onMounted(load)
watch(code, load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>企业诊断</h2>
        <p class="page-sub">
          <template v-if="score">
            {{ score.company_name }}（{{ score.stock_code }}）· {{ score.industry }} · 特征年 {{ score.year }}
          </template>
          <template v-else>证券代码：{{ code }}</template>
        </p>
      </div>
      <button class="btn" :disabled="loading" @click="load">{{ loading ? '加载中…' : '刷新' }}</button>
      <button class="btn" :disabled="analyzing" @click="runAnalyze">{{ analyzing ? '研判中…' : '智能研判' }}</button>
    </div>

    <p v-if="error" class="error-box">{{ error }}</p>

    <template v-if="score">
      <div class="stat-grid">
        <div class="stat-card">
          <div class="stat-icon">🎯</div>
          <div>
            <div class="stat-value">{{ fmtPercent(score.st_prob) }}</div>
            <div class="stat-label">ST 风险概率（校准后）</div>
          </div>
        </div>
        <div class="stat-card" :style="{ borderLeftColor: riskColor(score.risk_level) }">
          <div class="stat-icon">🚨</div>
          <div>
            <div class="stat-value" :style="{ color: riskColor(score.risk_level) }">{{ score.risk_level }}</div>
            <div class="stat-label">模型风险等级</div>
          </div>
        </div>
        <div class="stat-card" :style="{ borderLeftColor: riskColor(score.risk_level) }">
          <div class="stat-icon">📊</div>
          <div>
            <div class="stat-value">{{ score.risk_percentile != null ? (score.risk_percentile * 100).toFixed(1) + '%' : '—' }}</div>
            <div class="stat-label">全市场风险分位</div>
          </div>
        </div>
        <div class="stat-card" v-if="rules" :style="{ borderLeftColor: gradeColor(rules.grade) }">
          <div class="stat-icon">🏅</div>
          <div>
            <div class="stat-value" :style="{ color: gradeColor(rules.grade) }">{{ rules.grade }}</div>
            <div class="stat-label">规则评级 · {{ rules.grade_label }}（{{ fmtNum(rules.score, 1) }} 分）</div>
          </div>
        </div>
      </div>

      <div class="grid">
        <div class="card">
          <div class="card-title">规则六维评分雷达</div>
          <BaseChart :option="radarOption" height="340px" />
        </div>

        <div class="card">
          <div class="card-title">SHAP 特征贡献（推高风险为正）</div>
          <BaseChart v-if="explain?.contributions.length" :option="shapOption" height="340px" />
          <p v-else class="hint">暂无 SHAP 解释（需先运行 python -m models.shap_analysis）</p>
        </div>
      </div>

      <div class="card" v-if="rules">
        <div class="card-title">规则维度明细</div>
        <div v-for="d in dimList" :key="d.key" class="dim-row">
          <div class="dim-head">
            <span>{{ d.label }}</span>
            <span :style="{ color: ruleLevelColor(d.level) }">
              {{ fmtNum(d.score, 1) }} 分 · {{ ruleLevelLabel(d.level) }}
            </span>
          </div>
          <div class="dim-bar">
            <div
              class="dim-fill"
              :style="{ width: (d.score ?? 0) + '%', background: ruleLevelColor(d.level) }"
            ></div>
          </div>
          <p class="dim-note">{{ d.note }}</p>
        </div>
      </div>

      <div class="card" v-if="analyzeResp">
        <div class="card-title">
          智能研判
          <span
            class="chip"
            :style="{ background: analyzeResp.verdict.cross_check_ok ? '#16a34a' : '#d97706' }"
            style="margin-left: 8px"
          >
            {{ analyzeResp.verdict.cross_check_ok ? 'LLM 与规则一致' : '以规则为准' }}
          </span>
        </div>
        <p class="summary">{{ analyzeResp.verdict.summary }}</p>
        <p v-if="analyzeResp.llm_error" class="hint">LLM：{{ analyzeResp.llm_error }}</p>
        <ul v-if="analyzeResp.verdict.evidence.length" class="ev-list">
          <li v-for="(ev, i) in analyzeResp.verdict.evidence" :key="i">
            <span class="ev-dim">{{ ev.dimension }}</span>
            <span class="ev-text">{{ ev.text }}</span>
            <span v-if="ev.source" class="ev-src">{{ ev.source }}</span>
          </li>
        </ul>
      </div>
    </template>

    <p v-else-if="!loading" class="hint">请输入有效的证券代码或从数据看板进入。</p>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  align-items: start;
}

.dim-row {
  padding: 10px 0;
  border-bottom: 1px dashed var(--border);
}

.dim-row:last-child {
  border-bottom: none;
}

.dim-head {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}

.dim-bar {
  height: 6px;
  border-radius: 999px;
  background: var(--border-soft);
  overflow: hidden;
}

.dim-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.5s ease;
}

.dim-note {
  font-size: 12px;
  color: var(--text-sub);
  margin: 6px 0 0;
}

.summary {
  margin: 0 0 10px;
  background: var(--hover);
  border-left: 3px solid var(--primary);
  padding: 10px 14px;
  border-radius: 6px;
  font-size: 13.5px;
}

.ev-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ev-list li {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 13px;
  border-bottom: 1px dashed var(--border-soft);
  padding-bottom: 8px;
}

.ev-list li:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.ev-dim {
  flex: none;
  font-size: 11px;
  color: var(--primary);
  border: 1px solid currentColor;
  border-radius: 4px;
  padding: 0 6px;
}

.ev-text {
  flex: 1;
}

.ev-src {
  flex: none;
  font-size: 11px;
  color: var(--text-sub);
}

@media (max-width: 1100px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
