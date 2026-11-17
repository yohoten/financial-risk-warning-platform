import { createRouter, createWebHistory } from 'vue-router'

/** 大屏看板路由（路由级懒加载，按页拆分 chunk） */
export const routes = [
  { path: '/', name: 'dashboard', component: () => import('./views/DashboardView.vue'), meta: { title: '数据看板' } },
  { path: '/enterprises', name: 'enterprises', component: () => import('./views/EnterprisesView.vue'), meta: { title: '企业列表' } },
  { path: '/enterprise/:code', name: 'enterprise', component: () => import('./views/EnterpriseView.vue'), meta: { title: '企业诊断' } },
  { path: '/alerts', name: 'alerts', component: () => import('./views/AlertsView.vue'), meta: { title: '预警中心' } },
  { path: '/explain', name: 'explain', component: () => import('./views/ExplainView.vue'), meta: { title: '模型解释' } },
  { path: '/finance/:code?', name: 'finance', component: () => import('./views/FinanceView.vue'), meta: { title: '财务分析' } },
  { path: '/report', name: 'report', component: () => import('./views/ReportView.vue'), meta: { title: '报告导出' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
