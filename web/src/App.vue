<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

import { api } from './api'

const route = useRoute()
const apiOk = ref<boolean | null>(null)
const theme = ref<'light' | 'dark'>('dark')

const nav = [
  { to: '/', label: '数据看板' },
  { to: '/enterprises', label: '企业列表' },
  { to: '/alerts', label: '预警中心' },
  { to: '/explain', label: '模型解释' },
  { to: '/finance', label: '财务分析' },
  { to: '/report', label: '报告导出' },
]

function applyTheme() {
  document.documentElement.dataset.theme = theme.value
  localStorage.setItem('frw-theme', theme.value)
}

function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
  applyTheme()
}

onMounted(async () => {
  const saved = localStorage.getItem('frw-theme')
  if (saved === 'dark' || saved === 'light') theme.value = saved
  applyTheme()
  try {
    await api.health()
    apiOk.value = true
  } catch {
    apiOk.value = false
  }
})
</script>

<template>
  <div class="shell">
    <header class="topbar">
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
          :class="{ active: route.path === item.to }"
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
      </div>
    </header>

    <main class="content">
      <RouterView />
    </main>
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

.content {
  flex: 1;
  min-height: 0;
  padding: 16px 20px 48px;
  max-width: 1720px;
  width: 100%;
  margin: 0 auto;
}

@media (max-width: 900px) {
  .brand-sub,
  .topbar-right .pill {
    display: none;
  }
}
</style>
