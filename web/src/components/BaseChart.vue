<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import type { EChartsOption } from 'echarts'
import { BarChart, LineChart, PieChart, RadarChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  RadarComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import { themeVersion } from '../lib/theme'

// 按需注册：仅打包用到的图表与组件，显著减小体积（原全量引入 ~1.2MB）
echarts.use([
  BarChart,
  LineChart,
  PieChart,
  RadarChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  RadarComponent,
  CanvasRenderer,
])

const props = defineProps<{ option: EChartsOption; height?: string }>()
const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

function render() {
  if (!el.value) return
  if (!chart) chart = echarts.init(el.value)
  chart.setOption(props.option, true)
}

function resize() {
  chart?.resize()
}

/**
 * 主题切换时重建实例：
 * ECharts 初始化时会固化部分主题默认值（tooltip 背景、图例底色等），
 * 仅 setOption 无法覆盖，必须 dispose 后重新 init 才能拿到新的 CSS 变量色。
 */
function rebuild() {
  chart?.dispose()
  chart = null
  render()
}

onMounted(() => {
  render()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})

watch(() => props.option, render, { deep: true })
// 主题切换 → option 重算 + 实例重建
watch(themeVersion, rebuild)
</script>

<template>
  <div ref="el" class="chart" :style="{ height: height ?? '260px' }"></div>
</template>

<style scoped>
.chart {
  width: 100%;
}
</style>
