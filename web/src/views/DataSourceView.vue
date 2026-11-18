<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api } from '../api'
import { hasPerm } from '../auth/store'

type Tab = 'config' | 'logs' | 'keys' | 'push'

const tab = ref<Tab>('config')
const loading = ref(false)
const notice = ref('')
const error = ref('')

const canManageSource = computed(() => hasPerm('datasource:manage'))
const canPushKey = computed(() => hasPerm('ingest:push'))
const canRefresh = computed(() => hasPerm('data:refresh'))

function flash(msg: string) {
  notice.value = msg
  window.setTimeout(() => {
    if (notice.value === msg) notice.value = ''
  }, 4000)
}

const DIMENSIONS = ['finance', 'news', 'legal', 'market']

// ---------------------------------------------------------------------------
// 数据源配置
// ---------------------------------------------------------------------------
const akshareAvailable = ref<boolean | null>(null)
const sources = ref<any[]>([])
const configs = ref<any[]>([])
const showConfigForm = ref(false)
const configForm = ref({
  dimension: 'finance', source_name: '', label: '', merge_mode: 'fallback', schedule_cron: '', enabled: true,
})

async function fetchConfig() {
  loading.value = true
  error.value = ''
  try {
    const [cfg, status] = await Promise.all([api.datasourceConfig(), api.datasources()])
    configs.value = cfg.items
    akshareAvailable.value = status.akshare_available
    sources.value = status.sources
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  if (!configForm.value.source_name.trim()) {
    error.value = '请填写数据源名称'
    return
  }
  try {
    await api.datasourceConfigUpsert(configForm.value)
    flash('数据源配置已保存')
    showConfigForm.value = false
    configForm.value = { dimension: 'finance', source_name: '', label: '', merge_mode: 'fallback', schedule_cron: '', enabled: true }
    await fetchConfig()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '保存失败'
  }
}

async function toggleConfig(cfg: any) {
  try {
    await api.datasourceConfigUpsert({ ...cfg, enabled: !cfg.enabled })
    await fetchConfig()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '操作失败'
  }
}

async function removeConfig(cfg: any) {
  if (!window.confirm(`删除数据源 ${cfg.source_name}？`)) return
  try {
    await api.datasourceConfigDelete(cfg.id)
    flash('已删除')
    await fetchConfig()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除失败'
  }
}

const pullLoading = ref(false)
async function triggerPull(dimension?: string) {
  pullLoading.value = true
  error.value = ''
  try {
    const r = await api.datasourcePull(dimension ? { dimension } : {})
    flash(`拉取完成：${r?.closed?.codes ?? r?.codes ?? 0} 家企业已处理`)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '拉取失败'
  } finally {
    pullLoading.value = false
    await fetchLogs()
  }
}

// ---------------------------------------------------------------------------
// 接入日志
// ---------------------------------------------------------------------------
const logs = ref<any[]>([])
const logTotal = ref(0)
const logPage = ref(1)
const logFilters = ref({ dimension: '', status: '', channel: '' })

async function fetchLogs() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.ingestLogs({ page: logPage.value, size: 50, ...logFilters.value })
    logs.value = data.items
    logTotal.value = data.total
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载失败'
  } finally {
    loading.value = false
  }
}

function statusTone(s: string): string {
  return s === 'success' ? 'on' : s === 'failed' ? 'off' : 'warn'
}
function statusLabel(s: string): string {
  return ({ success: '成功', partial: '部分成功', failed: '失败', running: '进行中', pending: '待执行' } as any)[s] || s
}

async function consumeStaging() {
  try {
    const r = await api.ingestConsume({})
    flash(`合并完成：入库 ${r.inserted} 条，更新 ${r.updated} 条，触发闭环 ${r.closed?.codes ?? 0} 家`)
    await fetchLogs()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '合并失败'
  }
}

// ---------------------------------------------------------------------------
// API Key
// ---------------------------------------------------------------------------
const keys = ref<any[]>([])
const keyForm = ref({ name: '', scopes: 'ingest:*' })
const newKey = ref<any>(null)

async function fetchKeys() {
  error.value = ''
  try {
    const data = await api.ingestKeys()
    keys.value = data.items
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载失败'
  }
}

async function issueKey() {
  if (!keyForm.value.name.trim()) {
    error.value = '请填写 Key 名称'
    return
  }
  try {
    newKey.value = await api.ingestKeyCreate({
      name: keyForm.value.name.trim(),
      scopes: keyForm.value.scopes.split(',').map((s) => s.trim()).filter(Boolean),
    })
    keyForm.value = { name: '', scopes: 'ingest:*' }
    await fetchKeys()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '签发失败'
  }
}

async function revokeKey(id: number) {
  if (!window.confirm('吊销该 API Key？吊销后立即失效。')) return
  try {
    await api.ingestKeyRevoke(id)
    flash('已吊销')
    await fetchKeys()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '吊销失败'
  }
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    flash('已复制到剪贴板')
  } catch {
    flash('复制失败，请手动选中')
  }
}

// ---------------------------------------------------------------------------
// 推送预览
// ---------------------------------------------------------------------------
const pushForm = ref({ dimension: 'finance', batch_id: '', api_key: '', items: '' })
const pushResult = ref<any>(null)

async function doPush() {
  error.value = ''
  pushResult.value = null
  let items: any[]
  try {
    items = JSON.parse(pushForm.value.items || '[]')
  } catch {
    error.value = 'items 不是合法 JSON 数组'
    return
  }
  if (!Array.isArray(items) || !items.length) {
    error.value = 'items 需为 JSON 数组且非空'
    return
  }
  if (!pushForm.value.api_key.trim()) {
    error.value = '请填写 API Key（可在「API Key」页签发）'
    return
  }
  try {
    pushResult.value = await api.ingestPush(
      pushForm.value.dimension, pushForm.value.batch_id, items, pushForm.value.api_key.trim(),
    )
  } catch (err) {
    error.value = err instanceof Error ? err.message : '推送失败'
  }
}

onMounted(async () => {
  await fetchConfig()
  await fetchLogs()
  if (canPushKey.value) await fetchKeys()
})
</script>

<template>
  <div class="ds-view">
    <div class="tabs card">
      <button v-for="t in (['config', 'logs', 'keys', 'push'] as Tab[])"
              v-show="t !== 'keys' || canPushKey"
              :key="t" class="tab" :class="{ active: tab === t }" @click="tab = t">
        {{ { config: '数据源配置', logs: '接入日志', keys: 'API Key', push: '推送预览' }[t] }}
      </button>
      <span class="grow"></span>
      <button v-if="canRefresh" class="btn primary small" :disabled="pullLoading" @click="triggerPull()">
        {{ pullLoading ? '拉取中…' : '▶ 立即拉取全量' }}
      </button>
      <button v-if="canRefresh" class="btn small" @click="consumeStaging">合并暂存入库</button>
    </div>

    <p v-if="notice" class="toast ok">{{ notice }}</p>
    <p v-if="error" class="toast fail">{{ error }}</p>

    <!-- 数据源配置 -->
    <section v-if="tab === 'config'" class="card">
      <div class="sec-head">
        <h3 class="card-title">数据源配置</h3>
        <div class="sub">
          AkShare
          <span class="status" :class="akshareAvailable ? 'on' : 'off'">{{ akshareAvailable ? '可用' : '不可用' }}</span>
        </div>
      </div>

      <div v-if="canManageSource" class="toolbar">
        <button class="btn" @click="showConfigForm = !showConfigForm">{{ showConfigForm ? '收起' : '+ 新增数据源' }}</button>
      </div>

      <div v-if="showConfigForm" class="form-grid">
        <label>维度
          <select v-model="configForm.dimension">
            <option v-for="d in DIMENSIONS" :key="d" :value="d">{{ d }}</option>
          </select>
        </label>
        <label>数据源名<input v-model="configForm.source_name" placeholder="如 akshare_eastmoney" /></label>
        <label>标签<input v-model="configForm.label" placeholder="如 东方财富财务摘要" /></label>
        <label>合并模式
          <select v-model="configForm.merge_mode">
            <option value="merge">merge（多源合并）</option>
            <option value="fallback">fallback（降级优先）</option>
          </select>
        </label>
        <label>调度 cron<input v-model="configForm.schedule_cron" placeholder="空=不自动；如 0 * * * *" /></label>
        <div class="actions">
          <button class="btn primary" @click="saveConfig">保存</button>
          <button class="btn" @click="showConfigForm = false">取消</button>
        </div>
      </div>

      <table class="table">
        <thead>
          <tr>
            <th>维度</th><th>数据源</th><th>标签</th><th>模式</th><th>调度</th><th>开关</th>
            <th class="right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!configs.length"><td colspan="7" class="empty">暂无配置（默认数据源已从注册表播种，可在此覆盖）</td></tr>
          <tr v-for="c in configs" :key="c.id">
            <td><span class="badge muted">{{ c.dimension }}</span></td>
            <td class="name">{{ c.source_name }}</td>
            <td class="sub">{{ c.label || '—' }}</td>
            <td class="sub">{{ c.merge_mode }}</td>
            <td class="sub"><code>{{ c.schedule_cron || '手动' }}</code></td>
            <td>
              <button class="link" :disabled="!canManageSource" @click="toggleConfig(c)">
                <span class="status" :class="c.enabled ? 'on' : 'off'">{{ c.enabled ? '启用' : '停用' }}</span>
              </button>
            </td>
            <td class="right">
              <button v-if="canRefresh" class="link" @click="triggerPull(c.dimension)">立即拉取</button>
              <button v-if="canManageSource" class="link danger" @click="removeConfig(c)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 接入日志 -->
    <section v-else-if="tab === 'logs'" class="card table-card">
      <div class="toolbar pad">
        <select v-model="logFilters.dimension" class="select small" @change="logPage = 1; fetchLogs()">
          <option value="">全部维度</option>
          <option v-for="d in DIMENSIONS" :key="d" :value="d">{{ d }}</option>
        </select>
        <select v-model="logFilters.status" class="select small" @change="logPage = 1; fetchLogs()">
          <option value="">全部状态</option>
          <option value="success">成功</option><option value="partial">部分成功</option><option value="failed">失败</option>
        </select>
        <select v-model="logFilters.channel" class="select small" @change="logPage = 1; fetchLogs()">
          <option value="">全部通道</option><option value="push">推送</option><option value="pull">拉取</option><option value="manual">手动</option>
        </select>
        <span class="sub">共 {{ logTotal }} 条</span>
      </div>
      <table class="table">
        <thead>
          <tr><th>任务</th><th>通道</th><th>维度</th><th>状态</th><th>插入/更新</th><th>开始时间</th></tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="6" class="empty">加载中…</td></tr>
          <tr v-else-if="!logs.length"><td colspan="6" class="empty">暂无接入日志</td></tr>
          <tr v-for="l in logs" :key="l.id">
            <td class="name">{{ l.task }}</td>
            <td><span class="badge muted">{{ l.channel }}</span></td>
            <td class="sub">{{ l.dimension || '—' }}</td>
            <td><span class="status" :class="statusTone(l.status)">{{ statusLabel(l.status) }}</span></td>
            <td class="sub">{{ l.inserted }} / {{ l.updated }}</td>
            <td class="sub">{{ l.started_at }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- API Key -->
    <section v-else-if="tab === 'keys'" class="card">
      <h3 class="card-title">API Key 管理</h3>
      <div class="toolbar">
        <label class="inline">名称<input v-model="keyForm.name" placeholder="如 东财实时推送" /></label>
        <label class="inline">scopes<input v-model="keyForm.scopes" placeholder="ingest:finance,ingest:news" /></label>
        <button class="btn primary" @click="issueKey">签发 Key</button>
        <span class="sub">明文仅签发时展示一次；scopes 支持 ingest:* 通配</span>
      </div>

      <div v-if="newKey" class="reset-card">
        <div>已签发 <b>{{ newKey.name }}</b>，请立即保存明文：<code>{{ newKey.plaintext }}</code></div>
        <div class="actions">
          <button class="btn primary" @click="copyText(newKey.plaintext)">复制</button>
          <button class="btn" @click="newKey = null">关闭</button>
        </div>
      </div>

      <table class="table">
        <thead><tr><th>名称</th><th>掩码</th><th>scopes</th><th>最近使用</th><th class="right">操作</th></tr></thead>
        <tbody>
          <tr v-if="!keys.length"><td colspan="5" class="empty">暂无 API Key</td></tr>
          <tr v-for="k in keys" :key="k.id">
            <td class="name">{{ k.name }}</td>
            <td class="sub"><code>{{ k.masked }}</code></td>
            <td class="sub">{{ (k.scopes || []).join(', ') }}</td>
            <td class="sub">{{ k.last_used_at || '—' }}</td>
            <td class="right">
              <button class="link danger" :disabled="k.revoked" @click="revokeKey(k.id)">吊销</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 推送预览 -->
    <section v-else-if="tab === 'push'" class="card">
      <h3 class="card-title">推送预览（机器通道模拟）</h3>
      <div class="form-grid">
        <label>维度
          <select v-model="pushForm.dimension"><option v-for="d in DIMENSIONS" :key="d" :value="d">{{ d }}</option></select>
        </label>
        <label>batch_id<input v-model="pushForm.batch_id" placeholder="≥8 位，幂等键" /></label>
        <label>API Key<input v-model="pushForm.api_key" placeholder="risk_…" /></label>
      </div>
      <label class="block">items（JSON 数组）
        <textarea v-model="pushForm.items" rows="6" placeholder='[{"stock_code":"000001","year":2023,"revenue":1000}]'></textarea>
      </label>
      <div class="actions">
        <button class="btn primary" @click="doPush">推送</button>
        <span class="sub">示例：finance 需 stock_code + year；news 需 stock_code + title；legal 需 title 或 case_no</span>
      </div>

      <div v-if="pushResult" class="result-card">
        <div class="sec-head">
          <span class="badge" :class="pushResult.status === 'success' ? 'primary' : 'warn'">{{ pushResult.status }}</span>
          <span class="sub">batch: {{ pushResult.batch_id }} · 受理 {{ pushResult.accepted }} · 重复 {{ pushResult.duplicated }}</span>
        </div>
        <ul v-if="pushResult.rejected?.length" class="reject-list">
          <li v-for="r in pushResult.rejected" :key="r.index">
            #{{ r.index }} <span v-if="r.stock_code">{{ r.stock_code }}</span>：{{ r.reason }}
          </li>
        </ul>
      </div>
    </section>
  </div>
</template>

<style scoped>
.ds-view {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tabs {
  display: flex;
  align-items: center;
  gap: 4px;
}

.tab {
  border: none;
  background: transparent;
  padding: 9px 14px;
  font-size: 13px;
  color: var(--text-sub);
  border-radius: 8px;
  cursor: pointer;
}

.tab:hover {
  color: var(--text);
  background: var(--hover);
}

.tab.active {
  color: var(--primary);
  background: rgba(37, 99, 235, 0.1);
  font-weight: 600;
}

.grow {
  flex: 1;
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

.btn.small {
  height: 30px;
  font-size: 12.5px;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.sec-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.card-title {
  margin: 0;
  font-size: 15px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 10px 0;
}

.toolbar.pad {
  padding: 8px 0;
}

.sub {
  font-size: 12px;
  color: var(--text-sub);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}

.form-grid label,
.inline,
.block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-sub);
}

.inline {
  flex-direction: row;
  align-items: center;
}

.inline input {
  width: 160px;
}

.block textarea {
  resize: vertical;
  font-family: ui-monospace, 'SF Mono', Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px;
  outline: none;
}

.form-grid input,
.form-grid select,
.inline input,
.search {
  height: 34px;
  padding: 0 10px;
  font-size: 13px;
  color: var(--text);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  outline: none;
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
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

.status.on {
  color: var(--ok);
  font-weight: 600;
}

.status.off {
  color: var(--danger);
  font-weight: 600;
}

.status.warn {
  color: var(--warn);
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

.badge.muted {
  color: var(--text-sub);
  background: var(--border-soft);
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

.link:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

code {
  padding: 1px 7px;
  background: var(--border-soft);
  border-radius: 6px;
  font-size: 12px;
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

.reset-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid var(--warn);
  border-radius: 10px;
  padding: 12px;
  margin: 10px 0;
}

.result-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px;
  margin-top: 12px;
}

.reject-list {
  margin: 8px 0 0;
  padding-left: 18px;
  font-size: 12.5px;
  color: var(--danger);
  line-height: 1.9;
}
</style>
