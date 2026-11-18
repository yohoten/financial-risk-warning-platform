<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { auth, firstAllowedRoute, login } from '../auth/store'

const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const remember = ref(false)
const showPassword = ref(false)
const submitting = ref(false)
// 会话过期等场景下 store 会在跳转前写入 auth.error，进页面时带出提示
const error = ref(auth.error)
auth.error = ''
const lockedSeconds = ref(0)

let lockTimer: number | undefined

const canSubmit = computed(() => !!username.value.trim() && !!password.value && !submitting.value && lockedSeconds.value === 0)

function startLockCountdown(seconds: number) {
  lockedSeconds.value = Math.max(1, seconds)
  window.clearInterval(lockTimer)
  lockTimer = window.setInterval(() => {
    lockedSeconds.value -= 1
    if (lockedSeconds.value <= 0) {
      window.clearInterval(lockTimer)
      lockedSeconds.value = 0
    }
  }, 1000)
}

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  error.value = ''
  try {
    await login(username.value.trim(), password.value, remember.value)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
    await router.replace(redirect && redirect !== '/login' ? redirect : firstAllowedRoute())
  } catch (err) {
    const message = err instanceof Error ? err.message : '登录失败'
    error.value = message
    const status = (err as { status?: number }).status
    const retryAfter = Number.parseInt(String(message.match(/(\d+)\s*秒/)?.[1] ?? ''), 10)
    if (status === 423) startLockCountdown(Number.isFinite(retryAfter) ? retryAfter : 60)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <section class="brand-side">
      <div class="brand-top">
        <div class="brand-mark">风</div>
        <div>
          <div class="brand-name">财务风险智能预警平台</div>
          <div class="brand-sub">Financial Risk Early-Warning Platform</div>
        </div>
      </div>

      <div class="brand-copy">
        <h1>让每一个风险评分<br />都可拆解、可审计、可追溯</h1>
        <p>XGBoost + TreeSHAP · 36 维入选特征 · 十大维度风险画像</p>
        <ul>
          <li><b>四角色分权</b>：管理员 / 分析师 / 审计员 / 查看者</li>
          <li><b>全链路留痕</b>：登录、导出、处置操作均可回溯</li>
          <li><b>数据实时接入</b>：定时拉取 + 外部推送 + 事件流</li>
        </ul>
      </div>

      <div class="brand-foot">v1.0 · Asia/Shanghai</div>
    </section>

    <section class="form-side">
      <form class="login-card" @submit.prevent="submit">
        <h2>账号登录</h2>
        <p class="hint" v-if="!auth.enabled">当前为单机免登录形态，可直接使用。</p>

        <label class="field">
          <span>用户名</span>
          <input
            v-model="username"
            type="text"
            autocomplete="username"
            placeholder="请输入用户名"
            :disabled="submitting"
            autofocus
          />
        </label>

        <label class="field">
          <span>密码</span>
          <div class="pwd-wrap">
            <input
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              autocomplete="current-password"
              placeholder="请输入密码"
              :disabled="submitting"
            />
            <button type="button" class="eye" :title="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword">
              {{ showPassword ? '🙈' : '👁' }}
            </button>
          </div>
        </label>

        <label class="remember">
          <input v-model="remember" type="checkbox" />
          <span>7 天内免登录</span>
        </label>

        <p v-if="error" class="error">{{ error }}</p>
        <p v-if="lockedSeconds > 0" class="error">账号锁定中，{{ lockedSeconds }} 秒后可重试</p>

        <button class="submit" type="submit" :disabled="!canSubmit">
          {{ submitting ? '登录中…' : '登 录' }}
        </button>

        <p class="tip">忘记密码请联系管理员重置。连续 5 次输错将锁定 15 分钟。</p>
      </form>
    </section>
  </div>
</template>

<style scoped>
.login-page {
  display: grid;
  grid-template-columns: minmax(360px, 5fr) minmax(360px, 6fr);
  min-height: calc(100vh - 120px);
  border: 1px solid var(--border);
  border-radius: 16px;
  overflow: hidden;
  background: var(--bg-elev);
  box-shadow: var(--shadow);
}

.brand-side {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 24px;
  padding: 28px 30px;
  color: #e8eefc;
  background:
    radial-gradient(120% 90% at 0% 0%, rgba(6, 182, 212, 0.28), transparent 55%),
    radial-gradient(100% 80% at 100% 100%, rgba(37, 99, 235, 0.42), transparent 60%),
    linear-gradient(150deg, #0f1b3d, #16244a 55%, #0b1220);
}

.brand-top {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  width: 40px;
  height: 40px;
  border-radius: 11px;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 19px;
  color: #fff;
}

.brand-name {
  font-size: 15px;
  font-weight: 700;
}

.brand-sub {
  font-size: 10.5px;
  letter-spacing: 0.6px;
  color: #9db0d8;
}

.brand-copy h1 {
  font-size: 24px;
  line-height: 1.45;
  margin: 0 0 12px;
  font-weight: 700;
}

.brand-copy p {
  margin: 0 0 18px;
  color: #a8bade;
  font-size: 12.5px;
}

.brand-copy ul {
  margin: 0;
  padding-left: 18px;
  color: #c3d2ee;
  font-size: 12.5px;
  line-height: 2;
}

.brand-copy b {
  color: #fff;
}

.brand-foot {
  font-size: 11px;
  color: #7f92b8;
}

.form-side {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 24px;
}

.login-card {
  width: min(380px, 100%);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.login-card h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
}

.hint {
  margin: 0;
  font-size: 12px;
  color: var(--ok);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-sub);
}

.field input {
  height: 40px;
  padding: 0 12px;
  font-size: 13.5px;
  color: var(--text);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 9px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.field input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.13);
}

.pwd-wrap {
  position: relative;
  display: flex;
}

.pwd-wrap input {
  flex: 1;
}

.eye {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  width: 30px;
  height: 30px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  opacity: 0.75;
}

.remember {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12.5px;
  color: var(--text-sub);
  cursor: pointer;
}

.error {
  margin: 0;
  font-size: 12.5px;
  color: var(--danger);
}

.submit {
  height: 42px;
  border: none;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--primary), var(--primary-deep));
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 2px;
  cursor: pointer;
  transition: filter 0.15s, opacity 0.15s;
}

.submit:hover:not(:disabled) {
  filter: brightness(1.06);
}

.submit:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.tip {
  margin: 4px 0 0;
  font-size: 11.5px;
  color: var(--text-sub);
  line-height: 1.7;
}

@media (max-width: 900px) {
  .login-page {
    grid-template-columns: 1fr;
  }

  .brand-side {
    display: none;
  }
}
</style>