<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { api, type AlertRow, type AlertsSummaryResp } from '../api'
import { fmtNum, fmtTime, ruleLevelColor, ruleLevelLabel } from '../lib/levels'

const loading = ref(false)
const error = ref('')
const generating = ref(false)
const summary = ref<AlertsSummaryResp | null>(null)
const items = ref<AlertRow[]>([])
const statusFilter = ref('')
const levelFilter = ref('')
const selectedId = ref<number | null>(null)
const handler = ref('')
const note = ref('')

const selected = computed(() => items.value.find((i) => i.id === selectedId.value) ?? null)

const statusOptions = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '待处理' },
  { value: 'handling', label: '处理中' },
  { value: 'resolved', label: '已处置' },
  { value: 'ignored', label: '已忽略' },
]

const levelOptions = [
  { value: '', label: '全部等级' },
  { value: 'red', label: '高风险' },
  { value: 'orange', label: '较高风险' },
  { value: 'yellow', label: '关注' },
]

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [s, l] = await Promise.all([
      api.alertSummary(),
      api.alerts({ status: statusFilter.value || undefined, level: levelFilter.value || undefined }),
    ])
    summary.value = s
    items.value = l.items
    if (!l.items.find((i) => i.id === selectedId.value)) selectedId.value = l.items[0]?.id ?? null
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function generate() {
  generating.value = true
  try {
    await api.generateAlerts()
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    generating.value = false
  }
}

async function handle(action: string) {
  if (!selected.value) return
  try {
    await api.handleAlert(selected.value.id, action, handler.value, note.value)
    note.value = ''
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(load)
watch([statusFilter, levelFilter], load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>预警中心</h2>
        <p class="page-sub">规则评分触发预警 → 人工处置 → 流水留痕（闭环）</p>
      </div>
      <button class="btn primary" :disabled="generating" @click="generate">
        {{ generating ? '生成中…' : '生成预警' }}
      </button>
    </div>

    <p v-if="error" class="error-box">{{ error }}</p>

    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-icon">🔔</div>
        <div>
          <div class="stat-value">{{ summary?.total ?? 0 }}</div>
          <div class="stat-label">预警总数</div>
        </div>
      </div>
      <div class="stat-card tone-red">
        <div class="stat-icon">⏳</div>
        <div>
          <div class="stat-value">{{ summary?.pending ?? 0 }}</div>
          <div class="stat-label">待处理</div>
        </div>
      </div>
      <div class="stat-card tone-orange">
        <div class="stat-icon">🛠️</div>
        <div>
          <div class="stat-value">{{ summary?.handling ?? 0 }}</div>
          <div class="stat-label">处理中</div>
        </div>
      </div>
      <div class="stat-card tone-cyan">
        <div class="stat-icon">✅</div>
        <div>
          <div class="stat-value">{{ summary?.by_status?.resolved ?? 0 }}</div>
          <div class="stat-label">已处置</div>
        </div>
      </div>
    </div>

    <div class="toolbar">
      <div class="chips">
        <button
          v-for="o in statusOptions"
          :key="o.value"
          class="chip-btn"
          :class="{ active: statusFilter === o.value }"
          @click="statusFilter = o.value"
        >
          {{ o.label }}
        </button>
      </div>
      <div class="chips">
        <button
          v-for="o in levelOptions"
          :key="o.value"
          class="chip-btn"
          :class="{ active: levelFilter === o.value }"
          @click="levelFilter = o.value"
        >
          {{ o.label }}
        </button>
      </div>
    </div>

    <div class="split">
      <div class="card list">
        <table class="table">
          <thead>
            <tr>
              <th>企业</th>
              <th>等级</th>
              <th>维度</th>
              <th>状态</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in items"
              :key="row.id"
              class="clickable"
              :class="{ active: row.id === selectedId }"
              @click="selectedId = row.id"
            >
              <td class="name">{{ row.company_name }}<span class="hint">（{{ row.stock_code }}）</span></td>
              <td>
                <span class="chip" :style="{ background: ruleLevelColor(row.level) }">{{ ruleLevelLabel(row.level) }}</span>
              </td>
              <td>{{ row.dimension_label }}</td>
              <td>{{ row.status_label }}</td>
              <td class="hint">{{ fmtTime(row.created_at) }}</td>
            </tr>
            <tr v-if="!items.length">
              <td colspan="5" class="hint">暂无预警，点击「生成预警」基于规则评分批量生成。</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card detail" v-if="selected">
        <div class="card-title">
          {{ selected.title }}
          <span class="chip" :style="{ background: ruleLevelColor(selected.level) }" style="margin-left: 8px">
            {{ ruleLevelLabel(selected.level) }}
          </span>
        </div>
        <p class="meta">
          {{ selected.company_name }}（{{ selected.stock_code }}）· {{ selected.dimension_label }} ·
          评分 {{ fmtNum(selected.score, 1) }} · {{ selected.status_label }}
        </p>
        <p class="summary">{{ selected.summary }}</p>

        <h4 class="sec">证据链</h4>
        <ul v-if="selected.evidence.length" class="ev-list">
          <li v-for="(ev, i) in selected.evidence" :key="i">
            {{ ev.text ?? JSON.stringify(ev) }}
            <span v-if="ev.source" class="ev-src">（来源：{{ ev.source }}）</span>
          </li>
        </ul>
        <p v-else class="hint">暂无证据记录</p>

        <h4 class="sec">处置</h4>
        <div class="toolbar">
          <input v-model="handler" class="toolbar-input" placeholder="处理人" style="width: 120px" />
          <input v-model="note" class="toolbar-input" placeholder="处置备注" />
        </div>
        <div class="toolbar" style="margin-top: 8px">
          <button class="btn small" @click="handle('start')">开始处理</button>
          <button class="btn small primary" @click="handle('resolve')">已处置</button>
          <button class="btn small" @click="handle('ignore')">忽略</button>
          <button class="btn small ghost" @click="handle('reopen')">重新打开</button>
        </div>

        <h4 class="sec">处置流水</h4>
        <ul v-if="selected.notes.length" class="ev-list">
          <li v-for="(n, i) in selected.notes" :key="i">
            {{ fmtTime(n.ts) }} · {{ n.status_label ?? n.status }} · {{ n.handler ?? '—' }} · {{ n.note ?? '' }}
          </li>
        </ul>
        <p v-else class="hint">尚未处置</p>
      </div>

      <div class="card detail" v-else>
        <p class="hint">选择左侧预警查看详情并处置。</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.split {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 12px;
  align-items: start;
}

.list tr.active td {
  background: var(--hover);
}

.detail .meta {
  font-size: 12.5px;
  color: var(--text-sub);
  margin: 4px 0 8px;
}

.detail .summary {
  margin: 0;
  background: var(--hover);
  border-left: 3px solid var(--primary);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
}

.sec {
  font-size: 13px;
  margin: 14px 0 6px;
}

.ev-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12.5px;
}

.ev-list li {
  border-bottom: 1px dashed var(--border-soft);
  padding-bottom: 6px;
}

.ev-src {
  color: var(--text-sub);
  font-size: 11px;
}

@media (max-width: 1100px) {
  .split {
    grid-template-columns: 1fr;
  }
}
</style>
