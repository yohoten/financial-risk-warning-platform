<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { authApi, type AuthUser, type RoleInfo } from '../auth/client'
import { auth, hasPerm, loadRoles } from '../auth/store'

const loading = ref(false)
const error = ref('')
const notice = ref('')
const users = ref<AuthUser[]>([])
const roles = ref<RoleInfo[]>([])
const keyword = ref('')
const roleFilter = ref('')

const creating = ref(false)
const createForm = ref({ username: '', password: '', email: '', role: 'viewer', note: '' })
const createError = ref('')

const resetResult = ref<{ username: string; password: string } | null>(null)

const canAssignRole = computed(() => hasPerm('role:assign'))
const roleOptions = computed(() => (roles.value.length ? roles.value : auth.roles))

function roleLabel(role: string): string {
  return roleOptions.value.find((r) => r.role === role)?.label || role
}

function roleTone(role: string): string {
  return role === 'admin' ? 'danger' : role === 'analyst' ? 'primary' : role === 'auditor' ? 'warn' : 'muted'
}

function flash(message: string) {
  notice.value = message
  window.setTimeout(() => {
    if (notice.value === message) notice.value = ''
  }, 4000)
}

async function fetchUsers() {
  loading.value = true
  error.value = ''
  try {
    const data = await authApi.users({ keyword: keyword.value.trim(), role: roleFilter.value })
    users.value = data.items
    if (data.roles?.length) roles.value = data.roles
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function changeRole(user: AuthUser, role: string) {
  if (user.role === role) return
  try {
    await authApi.updateUser(user.id, { role })
    flash(`已将 ${user.username} 的角色改为 ${roleLabel(role)}`)
    await fetchUsers()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '角色修改失败'
    await fetchUsers()
  }
}

async function toggleActive(user: AuthUser) {
  const next = !(user.is_active ?? true)
  if (!window.confirm(`${next ? '启用' : '停用'}账号 ${user.username}？`)) return
  try {
    if (next) await authApi.updateUser(user.id, { is_active: true })
    else await authApi.deactivateUser(user.id)
    flash(`${user.username} 已${next ? '启用' : '停用'}`)
    await fetchUsers()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '操作失败'
  }
}

async function resetPassword(user: AuthUser) {
  if (!window.confirm(`重置 ${user.username} 的密码？该用户当前所有登录状态将立即失效。`)) return
  try {
    const data = await authApi.resetPassword(user.id)
    if (data.password) resetResult.value = { username: user.username, password: data.password }
    else flash('密码已重置')
    await fetchUsers()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '重置失败'
  }
}

async function copyPassword() {
  if (!resetResult.value) return
  try {
    await navigator.clipboard.writeText(resetResult.value.password)
    flash('初始密码已复制到剪贴板')
  } catch {
    flash('复制失败，请手动选中复制')
  }
}

async function submitCreate() {
  createError.value = ''
  if (!createForm.value.username.trim() || !createForm.value.password) {
    createError.value = '用户名与初始密码为必填项'
    return
  }
  try {
    creating.value = true
    await authApi.createUser({
      username: createForm.value.username.trim(),
      password: createForm.value.password,
      email: createForm.value.email.trim(),
      role: createForm.value.role,
      note: createForm.value.note.trim(),
    })
    flash(`用户 ${createForm.value.username} 已创建`)
    createForm.value = { username: '', password: '', email: '', role: 'viewer', note: '' }
    showCreate.value = false
    await fetchUsers()
  } catch (err) {
    createError.value = err instanceof Error ? err.message : '创建失败'
  } finally {
    creating.value = false
  }
}

const showCreate = ref(false)

onMounted(async () => {
  await loadRoles()
  await fetchUsers()
})
</script>

<template>
  <div class="users-view">
    <div class="toolbar card">
      <div class="toolbar-left">
        <input v-model="keyword" class="search" placeholder="搜索用户名 / 邮箱" @keyup.enter="fetchUsers" />
        <select v-model="roleFilter" class="select" @change="fetchUsers">
          <option value="">全部角色</option>
          <option v-for="r in roleOptions" :key="r.role" :value="r.role">{{ r.label }}</option>
        </select>
        <button class="btn" @click="fetchUsers">查询</button>
      </div>
      <button class="btn primary" @click="showCreate = !showCreate">
        {{ showCreate ? '收起' : '+ 新建用户' }}
      </button>
    </div>

    <p v-if="notice" class="toast ok">{{ notice }}</p>
    <p v-if="error" class="toast fail">{{ error }}</p>

    <div v-if="showCreate" class="card create-card">
      <h3 class="card-title">新建用户</h3>
      <div class="create-grid">
        <label>用户名<input v-model="createForm.username" placeholder="3-32 位字母/数字/_ . -" /></label>
        <label>初始密码<input v-model="createForm.password" type="text" placeholder="≥8 位，含字母与数字" /></label>
        <label>邮箱<input v-model="createForm.email" placeholder="选填" /></label>
        <label>
          角色
          <select v-model="createForm.role" :disabled="!canAssignRole">
            <option v-for="r in roleOptions" :key="r.role" :value="r.role">{{ r.label }}</option>
          </select>
        </label>
        <label class="wide">备注<input v-model="createForm.note" placeholder="选填，如所属部门" /></label>
      </div>
      <p v-if="createError" class="toast fail">{{ createError }}</p>
      <div class="actions">
        <button class="btn primary" :disabled="creating" @click="submitCreate">
          {{ creating ? '创建中…' : '创建' }}
        </button>
        <button class="btn" @click="showCreate = false">取消</button>
        <span class="hint">新用户首次登录后需修改密码。</span>
      </div>
    </div>

    <div v-if="resetResult" class="card reset-card">
      <div>
        已重置 <b>{{ resetResult.username }}</b> 的密码，初始密码：
        <code>{{ resetResult.password }}</code>（仅展示一次）
      </div>
      <div class="actions">
        <button class="btn primary" @click="copyPassword">复制</button>
        <button class="btn" @click="resetResult = null">关闭</button>
      </div>
    </div>

    <div class="card table-card">
      <table class="table">
        <thead>
          <tr>
            <th>用户名</th>
            <th>邮箱</th>
            <th>角色</th>
            <th>状态</th>
            <th>最近登录</th>
            <th class="right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="6" class="empty">加载中…</td>
          </tr>
          <tr v-else-if="!users.length">
            <td colspan="6" class="empty">暂无用户</td>
          </tr>
          <tr v-for="user in users" :key="user.id">
            <td>
              <div class="name">{{ user.username }}</div>
              <div v-if="user.note" class="sub">{{ user.note }}</div>
            </td>
            <td class="sub">{{ user.email || '—' }}</td>
            <td>
              <select
                v-if="canAssignRole"
                class="select small"
                :value="user.role"
                @change="changeRole(user, ($event.target as HTMLSelectElement).value)"
              >
                <option v-for="r in roleOptions" :key="r.role" :value="r.role">{{ r.label }}</option>
              </select>
              <span v-else class="badge" :class="roleTone(user.role)">{{ roleLabel(user.role) }}</span>
            </td>
            <td>
              <span class="status" :class="user.is_active === false ? 'off' : 'on'">
                {{ user.is_active === false ? '已停用' : '启用' }}
              </span>
              <span v-if="user.must_change_password" class="badge warn ml">待改密</span>
            </td>
            <td class="sub">{{ user.last_login_at || '—' }}</td>
            <td class="right">
              <button class="link" @click="resetPassword(user)">重置密码</button>
              <button class="link danger" @click="toggleActive(user)">
                {{ user.is_active === false ? '启用' : '停用' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card roles-card">
      <h3 class="card-title">角色与权限</h3>
      <div class="role-grid">
        <div v-for="r in roleOptions" :key="r.role" class="role-box">
          <div class="role-head">
            <span class="badge" :class="r.role === 'admin' ? 'danger' : r.role === 'analyst' ? 'primary' : r.role === 'auditor' ? 'warn' : 'muted'">
              {{ r.label }}
            </span>
            <span class="sub">{{ r.permissions.length }} 项权限</span>
          </div>
          <ul class="perm-list">
            <li v-for="label in r.permission_labels" :key="label">{{ label }}</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.users-view {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.search,
.select,
.create-grid input,
.create-grid select {
  height: 34px;
  padding: 0 10px;
  font-size: 13px;
  color: var(--text);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  outline: none;
}

.search {
  width: 220px;
}

.select.small {
  height: 30px;
  font-size: 12.5px;
}

.btn {
  height: 34px;
  padding: 0 14px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--card);
  color: var(--text);
  font-size: 13px;
  cursor: pointer;
}

.btn:hover {
  border-color: var(--primary);
  color: var(--primary);
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

.create-card .create-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}

.create-grid label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-sub);
}

.create-grid label.wide {
  grid-column: 1 / -1;
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
}

.hint {
  font-size: 12px;
  color: var(--text-sub);
}

.reset-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-color: var(--warn);
}

.reset-card code {
  padding: 2px 8px;
  background: var(--border-soft);
  border-radius: 6px;
  font-size: 13px;
  letter-spacing: 0.5px;
}

.table-card {
  padding: 0;
  overflow: hidden;
}

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.table th,
.table td {
  padding: 11px 14px;
  text-align: left;
  border-bottom: 1px solid var(--border-soft);
  vertical-align: middle;
}

.table th {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-sub);
  background: var(--hover);
}

.table tbody tr:last-child td {
  border-bottom: none;
}

.table .right {
  text-align: right;
}

.empty {
  text-align: center;
  color: var(--text-sub);
  padding: 28px;
}

.name {
  font-weight: 600;
}

.sub {
  font-size: 12px;
  color: var(--text-sub);
}

.status.on {
  color: var(--ok);
  font-weight: 600;
}

.status.off {
  color: var(--danger);
  font-weight: 600;
}

.badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11.5px;
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

.ml {
  margin-left: 6px;
}

.link {
  border: none;
  background: transparent;
  color: var(--primary);
  font-size: 12.5px;
  cursor: pointer;
  padding: 2px 6px;
}

.link.danger {
  color: var(--danger);
}

.toast {
  margin: 0;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 12.5px;
}

.toast.ok {
  color: var(--ok);
  background: rgba(22, 163, 74, 0.1);
}

.toast.fail {
  color: var(--danger);
  background: rgba(220, 38, 38, 0.1);
}

.role-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.role-box {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px;
}

.role-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.perm-list {
  margin: 0;
  padding-left: 16px;
  font-size: 12px;
  color: var(--text-sub);
  line-height: 1.9;
}
</style>