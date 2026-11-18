import { createRouter, createWebHistory } from 'vue-router'

import { auth, ensureAuthReady, firstAllowedRoute, hasPerm } from './auth/store'

/** 大屏看板路由（路由级懒加载，按页拆分 chunk）
 *
 * meta.permission 与后端 api/auth/guards.py 的规则表使用同一组权限点字符串，
 * 前端守卫只是体验优化——真正的越权拦截在后端（403）。
 */
export const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('./views/LoginView.vue'),
    meta: { title: '登录', public: true },
  },
  { path: '/', name: 'dashboard', component: () => import('./views/DashboardView.vue'), meta: { title: '数据看板', permission: 'dashboard:view' } },
  { path: '/enterprises', name: 'enterprises', component: () => import('./views/EnterprisesView.vue'), meta: { title: '企业列表', permission: 'enterprise:view' } },
  { path: '/enterprise/:code', name: 'enterprise', component: () => import('./views/EnterpriseView.vue'), meta: { title: '企业诊断', permission: 'enterprise:view' } },
  { path: '/alerts', name: 'alerts', component: () => import('./views/AlertsView.vue'), meta: { title: '预警中心', permission: 'alert:view' } },
  { path: '/explain', name: 'explain', component: () => import('./views/ExplainView.vue'), meta: { title: '模型解释', permission: 'explain:view' } },
  { path: '/finance/:code?', name: 'finance', component: () => import('./views/FinanceView.vue'), meta: { title: '财务分析', permission: 'enterprise:view' } },
  { path: '/report', name: 'report', component: () => import('./views/ReportView.vue'), meta: { title: '报告导出', permission: 'report:export' } },
  { path: '/workspace', name: 'workspace', component: () => import('./views/WorkspaceView.vue'), meta: { title: '智能工作台', permission: 'chat:use' } },
  { path: '/datasources', name: 'datasources', component: () => import('./views/DataSourceView.vue'), meta: { title: '数据接入中心', permission: 'data:refresh' } },
  { path: '/admin/users', name: 'admin-users', component: () => import('./views/UsersView.vue'), meta: { title: '用户与角色', permission: 'user:manage' } },
  { path: '/forbidden', name: 'forbidden', component: () => import('./views/ForbiddenView.vue'), meta: { title: '无访问权限' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  await ensureAuthReady()

  // 免登录页：已登录访问 /login 时回到自己的首页
  if (to.meta.public) {
    if (to.name === 'login' && auth.user) return firstAllowedRoute()
    return true
  }

  if (!auth.user) {
    const redirect = to.fullPath && to.fullPath !== '/' ? { redirect: to.fullPath } : {}
    return { name: 'login', query: redirect }
  }

  const required = to.meta.permission as string | undefined
  if (required && !hasPerm(required)) return { name: 'forbidden', query: { from: to.fullPath } }
  return true
})

router.afterEach((to) => {
  const title = (to.meta.title as string) || '财务风险智能预警平台'
  document.title = `${title} · 财务风险智能预警平台`
})