<script setup lang="ts">
import { useRoute } from 'vue-router'

// 财务分析：阶段 3 实现（复用旧项目 FinanceView，接入 /api/finance/*）
const route = useRoute()
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>财务分析</h2>
        <p class="page-sub">
          {{ route.params.code ? `证券代码：${route.params.code}` : 'KPI、趋势、杜邦分解与财务预警模型' }}（阶段 3 实现）
        </p>
      </div>
    </div>
    <div class="card">
      <p class="hint">该页面将在阶段 3 复用旧项目 FinanceView，接入 /api/finance/*。</p>
    </div>
  </div>
</template>
