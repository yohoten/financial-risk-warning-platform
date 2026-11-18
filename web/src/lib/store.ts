import { reactive } from 'vue'

/** 跨页共享筛选状态（轻量响应式，替代 Pinia，延续旧项目 workspace/store 思路） */
export const globalFilter = reactive({
  /** 财务分析年份窗口（3/5/8 年），跨页切换时保持 */
  financeYears: 5,
  /** 行业筛选（预留，供看板/列表页复用） */
  industry: '',
})
