import { createRouter, createWebHistory } from 'vue-router'

import DashboardView from './views/DashboardView.vue'
import EnterpriseView from './views/EnterpriseView.vue'
import EnterprisesView from './views/EnterprisesView.vue'
import AlertsView from './views/AlertsView.vue'
import ExplainView from './views/ExplainView.vue'
import FinanceView from './views/FinanceView.vue'
import ReportView from './views/ReportView.vue'

/** 大屏看板路由（阶段 0 骨架） */
export const routes = [
  { path: '/', name: 'dashboard', component: DashboardView, meta: { title: '数据看板' } },
  { path: '/enterprises', name: 'enterprises', component: EnterprisesView, meta: { title: '企业列表' } },
  { path: '/enterprise/:code', name: 'enterprise', component: EnterpriseView, meta: { title: '企业诊断' } },
  { path: '/alerts', name: 'alerts', component: AlertsView, meta: { title: '预警中心' } },
  { path: '/explain', name: 'explain', component: ExplainView, meta: { title: '模型解释' } },
  { path: '/finance/:code?', name: 'finance', component: FinanceView, meta: { title: '财务分析' } },
  { path: '/report', name: 'report', component: ReportView, meta: { title: '报告导出' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
