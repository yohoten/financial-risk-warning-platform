<script setup lang="ts">
import { useRoute } from 'vue-router'

// 企业诊断：阶段 2 实现（聚合 /predict/codes + /explain/{code} + /risk/rules/{code}）
const route = useRoute()
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>企业诊断</h2>
        <p class="page-sub">证券代码：{{ route.params.code }}（阶段 2 实现）</p>
      </div>
    </div>
    <div class="card">
      <p class="hint">
        该页面将在阶段 2 聚合模型概率、SHAP 解释与规则六维评分，实现企业诊断画像。
      </p>
    </div>
  </div>
</template>
