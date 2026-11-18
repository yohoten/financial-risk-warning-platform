<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import { api } from './api'
import { auth, changePassword, logout, resetSession, visibleNav } from './auth/store'
import { initThemeWatcher } from './lib/theme'

const route = useRoute()
const router = useRouter()
const apiOk = ref<boolean | null>(null)
const theme = ref<'light' | 'dark'>('dark')

const nav = computed(() => visibleNav())
const isPublicPage = computed(() => !!route.meta.public)
const userMenuOpen = ref(false)
const pwdOpen = ref(false)
const pwdForm = ref({ oldPassword: '', newPassword: '', confirm: '' })
const pwdError = ref('')
const pwdMessage = ref('')
const pwdSubmitting = ref(false)

const roleTone = computed(() => {
  switch (auth.user?.role) {
    case 'admin':
      return 'danger'
    case 'analyst':
      return 'primary'
    case 'auditor':
      return 'warn'
    default:
      return 'muted'
  }
})

function applyTheme() {
  document.documentElement.dataset.theme = theme.value
  localStorage.setItem('frw-theme', theme.value)
}

function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
  applyTheme()
}

function toggleUserMenu() {
  userMenuOpen.value = !userMenuOpen.value
}

async function doLogout() {
  userMenuOpen.value = false
  await logout()
  await router.replace({ name: 'login' })
}

async function submitPassword() {
  pwdError.value = ''
  pwdMessage.value = ''
  if (pwdForm.value.newPassword !== pwdForm.value.confirm) {
    pwdError.value = '两次输入的新密码不一致'
    return
  }
  pwdSubmitting.value = true
  try {
    pwdMessage.value = await changePassword(pwdForm.value.oldPassword, pwdForm.value.newPassword)
    resetSession()
    window.setTimeout(async () => {
      pwdOpen.value = false
      await router.replace({ name: 'login' })
    }, 900)
  } catch (err) {
    pwdError.value = err instanceof Error ? err.message : '修改失败'
  } finally {
    pwdSubmitting.value = false
  }
}

/** 会话在页面停留期间失效（令牌过期且刷新失败）：统一兜底跳登录页。
 *  否则用户会停留在残缺页面上——导航消失、账号显示为空。 */
function handleUnauthorized() {
  if (route.meta.public) return
  auth.error = '登录状态已失效，请重新登录'
  const query = route.fullPath && route.fullPath !== '/' ? { redirect: route.fullPath } : {}
  void router.replace({ name: 'login', query })
}

onMounted(async () => {
  window.addEventListener('frw:unauthorized', handleUnauthorized)
  const saved = localStorage.getItem('frw-theme')
  if (saved === 'dark' || saved === 'light') theme.value = saved
  applyTheme()
  // 全局唯一的主题监听：data-theme 变化 → themeVersion 自增 → ECharts 实例重建
  initThemeWatcher()
  try {
    await api.health()
    apiOk.value = true
  } catch {
    apiOk.value = false
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('frw:unauthorized', handleUnauthorized)
})
</script>

<template>
  <div class="shell">
    <header v-if="!isPublicPage" class="topbar">
      <div class="brand">
        <div class="brand-mark">风</div>
        <div>
          <div class="brand-name">财务风险智能预警平台</div>
          <div class="brand-sub">Risk Warning · Big Screen</div>
        </div>
      </div>

      <nav class="nav">
        <RouterLink
          v-for="item in nav"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          :class="{ active: route.path === item.to || (item.to !== '/' && route.path.startsWith(item.to)) }"
        >
          {{ item.label }}
        </RouterLink>
      </nav>

      <div class="topbar-right">
        <span class="pill" :class="apiOk === false ? 'fail' : apiOk ? 'ok' : ''">
          <i class="dot"></i>
          API {{ apiOk === null ? '检测中' : apiOk ? '正常' : '未连接' }}
        </span>
        <button
          class="theme-btn"
          :title="theme === 'light' ? '切换深色' : '切换浅色'"
          @click="toggleTheme"
        >
          {{ theme === 'light' ? '🌙' : '☀️' }}
        </button>

        <div v-if="auth.user" class="user-wrap">
          <button class="user-btn" @click="toggleUserMenu">
            <span class="avatar">{{ auth.user.username?.slice(0, 1)?.toUpperCase() || '?' }}</span>
            <span class="user-name">{{ auth.user.username || '未知用户' }}</span>
            <span class="badge" :class="roleTone">{{ auth.user.role_label || auth.user.role || '未授权' }}</span>
            <span class="caret">▾</span>
          </button>
          <div v-if="userMenuOpen" class="user-menu" @mouseleave="userMenuOpen = false">
            <div class="menu-head">
              <div class="menu-name">{{ auth.user.username || '未知用户' }}</div>
              <div class="menu-sub">{{ auth.user.email || '未设置邮箱' }}</div>
              <div class="menu-sub">权限 {{ auth.user.permissions?.length ?? 0 }} 项 · 模式 {{ auth.mode }}</div>
            </div>
            <button class="menu-item" @click="pwdOpen = true; userMenuOpen = false">修改密码</button>
            <button class="menu-item danger" @click="doLogout">退出登录</button>
          </div>
        </div>
      </div>
    </header>

    <div v-if="auth.user?.must_change_password && !isPublicPage" class="banner warn">
      当前账号仍在使用初始/重置密码，请尽快
      <button class="banner-link" @click="pwdOpen = true">修改密码</button>
      。
    </div>

    <main class="content" :class="{ bare: isPublicPage }">
      <RouterView />
    </main>

    <div v-if="pwdOpen" class="modal-mask" @click.self="pwdOpen = false">
      <div class="modal card">
        <h3 class="card-title">修改密码</h3>
        <label class="field">原密码<input v-model="pwdForm.oldPassword" type="password" autocomplete="current-password" /></label>
        <label class="field">新密码<input v-model="pwdForm.newPassword" type="password" autocomplete="new-password" placeholder="≥8 位，含字母与数字" /></label>
        <label class="field">确认新密码<input v-model="pwdForm.confirm" type="password" autocomplete="new-password" /></label>
        <p v-if="pwdError" class="err">{{ pwdError }}</p>
        <p v-if="pwdMessage" class="ok-msg">{{ pwdMessage }}（即将跳转登录）</p>
        <div class="modal-actions">
          <button class="btn primary" :disabled="pwdSubmitting" @click="submitPassword">
            {{ pwdSubmitting ? '提交中…' : '确认修改' }}
          </button>
          <button class="btn" @click="pwdOpen = false">取消</button>
        </div>
        <p class="tip">修改成功后，该账号在所有设备上的登录都会失效。</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.topbar {
  height: 56px;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 20px;
  background: var(--bg-elev);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 20;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: none;
}

.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  color: #fff;
  font-weight: 700;
  font-size: 17px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.brand-name {
  font-size: 14px;
  font-weight: 700;
}

.brand-sub {
  font-size: 10.5px;
  color: var(--text-sub);
  letter-spacing: 0.4px;
}

.nav {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  overflow-x: auto;
}

.nav-link {
  color: var(--text-sub);
  font-size: 13px;
  padding: 6px 12px;
  border-radius: 8px;
  white-space: nowrap;
  transition: all 0.15s;
}

.nav-link:hover {
  color: var(--text);
  background: var(--hover);
}

.nav-link.active {
  color: var(--primary);
  background: rgba(37, 99, 235, 0.1);
  font-weight: 600;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: none;
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--text-sub);
  background: var(--border-soft);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 11px;
  white-space: nowrap;
}

.pill .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #9ca3af;
}

.pill.ok .dot {
  background: var(--ok);
}

.pill.fail .dot {
  background: var(--danger);
}

.theme-btn {
  border: 1px solid var(--border);
  background: var(--bg-elev);
  border-radius: 8px;
  width: 34px;
  height: 30px;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}

.theme-btn:hover {
  border-color: var(--primary);
}

.user-wrap {
  position: relative;
}

.user-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 34px;
  padding: 0 10px 0 4px;
  border: 1px solid var(--border);
  background: var(--bg-elev);
  border-radius: 999px;
  cursor: pointer;
  color: var(--text);
}

.user-btn:hover {
  border-color: var(--primary);
}

.avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.user-name {
  font-size: 12.5px;
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.caret {
  font-size: 10px;
  color: var(--text-sub);
}

.badge {
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  border: 1px solid transparent;
}

.badge.primary {
  color: var(--primary);
  background: rgba(37, 99, 235, 0.12);
}

.badge.warn {
  color: var(--warn);
  background: rgba(217, 119, 6, 0.12);
}

.badge.danger {
  color: var(--danger);
  background: rgba(220, 38, 38, 0.12);
}

.badge.muted {
  color: var(--text-sub);
  background: var(--border-soft);
}

.user-menu {
  position: absolute;
  right: 0;
  top: 42px;
  width: 220px;
  padding: 6px;
  background: var(--bg-elev);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow);
  z-index: 40;
}

.menu-head {
  padding: 8px 10px 10px;
  border-bottom: 1px solid var(--border-soft);
  margin-bottom: 6px;
}

.menu-name {
  font-size: 13px;
  font-weight: 700;
}

.menu-sub {
  font-size: 11.5px;
  color: var(--text-sub);
}

.menu-item {
  width: 100%;
  text-align: left;
  padding: 8px 10px;
  border: none;
  background: transparent;
  border-radius: 8px;
  font-size: 13px;
  color: var(--text);
  cursor: pointer;
}

.menu-item:hover {
  background: var(--hover);
}

.menu-item.danger {
  color: var(--danger);
}

.banner {
  padding: 8px 20px;
  font-size: 12.5px;
  border-bottom: 1px solid var(--border);
}

.banner.warn {
  color: #92400e;
  background: rgba(217, 119, 6, 0.12);
}

.banner-link {
  border: none;
  background: transparent;
  color: var(--primary);
  font: inherit;
  font-weight: 600;
  text-decoration: underline;
  cursor: pointer;
}

.content {
  flex: 1;
  min-height: 0;
  padding: 16px 20px 48px;
  max-width: 1720px;
  width: 100%;
  margin: 0 auto;
}

.content.bare {
  display: flex;
  align-items: stretch;
  padding: 24px;
}

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(8, 14, 28, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 60;
}

.modal {
  width: min(400px, 92vw);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-sub);
}

.field input {
  height: 38px;
  padding: 0 12px;
  font-size: 13.5px;
  color: var(--text);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 9px;
  outline: none;
}

.field input:focus {
  border-color: var(--primary);
}

.err {
  margin: 0;
  font-size: 12.5px;
  color: var(--danger);
}

.ok-msg {
  margin: 0;
  font-size: 12.5px;
  color: var(--ok);
}

.modal-actions {
  display: flex;
  gap: 10px;
  margin-top: 4px;
}

.btn {
  height: 36px;
  padding: 0 16px;
  border-radius: 9px;
  border: 1px solid var(--border);
  background: var(--card);
  color: var(--text);
  font-size: 13px;
  cursor: pointer;
}

.btn.primary {
  border-color: transparent;
  background: linear-gradient(135deg, var(--primary), var(--primary-deep));
  color: #fff;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.tip {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-sub);
}

@media (max-width: 900px) {
  .brand-sub,
  .topbar-right .pill,
  .user-name {
    display: none;
  }
}
</style>