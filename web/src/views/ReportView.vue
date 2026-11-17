<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api, type AlertRow } from '../api'
import { fmtTime, ruleLevelColor, ruleLevelLabel } from '../lib/levels'

const loading = ref(false)
const error = ref('')
const alerts = ref<AlertRow[]>([])
const inputCode = ref('')
const financeCode = ref('')

const financeReportUrl = computed(() =>
  financeCode.value ? api.financeReportUrl(financeCode.value) : '',
)

async function loadAlerts() {
  loading.value = true
  error.value = ''
  try {
    alerts.value = (await api.alerts({})).items
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function resolveFinance() {
  const c = inputCode.value.trim().replace(/\.0$/, '').padStart(6, '0')
  if (/^\d{6}$/.test(c)) financeCode.value = c
}

onMounted(loadAlerts)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>报告导出</h2>
        <p class="page-sub">财务分析报告（Markdown）与预警报告下载</p>
      </div>
      <button class="btn" :disabled="loading" @click="loadAlerts">{{ loading ? '加载中…' : '刷新预警' }}</button>
    </div>

    <p v-if="error" class="error-box">{{ error }}</p>

    <div class="grid">
      <div class="card">
        <div class="card-title">财务分析报告</div>
        <div class="search-bar">
          <input v-model="inputCode" placeholder="输入证券代码，如 000008" @keyup.enter="resolveFinance" />
          <button class="btn primary" @click="resolveFinance">生成链接</button>
        </div>
        <a v-if="financeReportUrl" class="btn primary" :href="financeReportUrl" target="_blank" style="margin-top: 12px">
          下载财务分析报告
        </a>
        <p v-else class="hint">报告由 /finance/{code}/report 生成，内容含 KPI、财务预警模型与异常勾稽信号。</p>
      </div>

      <div class="card">
        <div class="card-title">预警报告</div>
        <table class="table">
          <thead>
            <tr><th>企业</th><th>等级</th><th>生成时间</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="a in alerts" :key="a.id">
              <td class="name">{{ a.company_name }}</td>
              <td>
                <span class="chip" :style="{ background: ruleLevelColor(a.level) }">{{ ruleLevelLabel(a.level) }}</span>
              </td>
              <td class="hint">{{ fmtTime(a.created_at) }}</td>
              <td>
                <a class="btn small" :href="api.alertReportUrl(a.id)" target="_blank">下载</a>
              </td>
            </tr>
            <tr v-if="!alerts.length">
              <td colspan="4" class="hint">暂无预警，请先在「预警中心」生成。</td>
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
