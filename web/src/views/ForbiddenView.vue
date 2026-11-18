<script setup lang="ts">
import { computed, watchEffect } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { auth, firstAllowedRoute } from '../auth/store'

const route = useRoute()
const router = useRouter()
const from = computed(() => (typeof route.query.from === 'string' ? route.query.from : ''))

/** 会话失效（用户信息被清空）时不再渲染残缺的 403 页，转去登录。 */
watchEffect(() => {
  if (auth.ready && !auth.user) {
    const query = from.value ? { redirect: from.value } : {}
    void router.replace({ name: 'login', query })
  }
})

/** 防止没有任何可见菜单时"返回首页"指向 /forbidden 自身形成死循环。 */
const backTo = computed(() => {
  const target = firstAllowedRoute()
  return target === '/forbidden' ? '/' : target
})
</script>

<template>
  <div v-if="auth.user" class="forbidden card">
    <div class="code">403</div>
    <h2>没有访问该页面的权限</h2>
    <p class="sub">
      当前账号：<b>{{ auth.user.username }}</b>
      （{{ auth.user.role_label || auth.user.role }}）<span v-if="from">，请求路径 {{ from }}</span>
    </p>
    <p class="sub">如确需访问，请联系管理员在「用户与角色」中调整权限。</p>
    <div class="actions">
      <RouterLink class="btn primary" :to="backTo">返回我可访问的首页</RouterLink>
    </div>
  </div>
</template>

<style scoped>
.forbidden {
  max-width: 520px;
  margin: 64px auto;
  text-align: center;
  padding: 36px 28px;
}

.code {
  font-size: 44px;
  font-weight: 800;
  color: var(--danger);
  letter-spacing: 2px;
}

h2 {
  margin: 6px 0 10px;
  font-size: 17px;
}

.sub {
  margin: 4px 0;
  font-size: 13px;
  color: var(--text-sub);
}

.actions {
  margin-top: 20px;
}

.btn {
  display: inline-block;
  padding: 9px 18px;
  border-radius: 9px;
  font-size: 13px;
}

.btn.primary {
  background: linear-gradient(135deg, var(--primary), var(--primary-deep));
  color: #fff;
}
</style>