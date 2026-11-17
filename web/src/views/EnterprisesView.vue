<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, type ScoredRow } from '../api'
import { fmtPercent, riskColor } from '../lib/levels'

const router = useRouter()
const loading = ref(false)
const error = ref('')
const items = ref<ScoredRow[]>([])
const search = ref('')
const unmatched = ref<string[]>([])

async function loadDefault() {
  loading.value = true
  error.value = ''
  try {
    items.value = (await api.topRisk({ limit: 100 })).items
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function doSearch() {
  const codes = search.value
    .split(/[\s,，;；]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  if (!codes.length) {
    await loadDefault()
    return
  }
  loading.value = true
  error.value = ''
  try {
    const resp = await api.predictCodes(codes)
    items.value = resp.items
    unmatched.value = resp.unmatched
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function open(code: string) {
  router.push(`/enterprise/${code}`)
}

onMounted(loadDefault)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>企业列表</h2>
        <p class="page-sub">默认展示 Top100 高风险；可输入证券代码批量查询</p>
      </div>
    </div>

    <div class="search-bar">
      <input
        v-model="search"
        placeholder="输入证券代码（空格/逗号分隔），如 000008 600519"
        @keyup.enter="doSearch"
      />
      <button class="btn primary" :disabled="loading" @click="doSearch">{{ loading ? '查询中…' : '查询' }}</button>
    </div>

    <p v-if="error" class="error-box">{{ error }}</p>
    <p v-if="unmatched.length" class="hint">未匹配：{{ unmatched.join('、') }}</p>

    <div class="card">
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
          <tr v-for="row in items" :key="row.stock_code" class="clickable" @click="open(row.stock_code)">
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
            <td colspan="6" class="hint">暂无数据</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
