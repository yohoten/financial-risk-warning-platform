<script setup lang="ts">
/** 智能工作台：Agent 对话 + 财报表格 + MCP 服务 + Agent 预设 + 设置面板。 */
import { nextTick, onMounted, ref } from 'vue'
import { api } from '../api'

type Tab = 'chat' | 'tables' | 'mcp' | 'presets' | 'settings'
const tab = ref<Tab>('chat')
const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: 'chat', label: '对话', icon: '💬' }, { key: 'tables', label: '表格', icon: '🧾' },
  { key: 'mcp', label: 'MCP', icon: '🔌' }, { key: 'presets', label: '预设', icon: '🧩' }, { key: 'settings', label: '设置', icon: '⚙️' },
]

interface ToolCard { id: string; name: string; args: any; readOnly?: boolean; running: boolean; result?: any; approval?: any; latencyMs?: number }
interface ChatMsg { role: 'user' | 'assistant'; text: string; tools: ToolCard[]; streaming?: boolean; error?: string; notice?: string; reasoning?: string }
const messages = ref<ChatMsg[]>([])
const input = ref('')
const busy = ref(false)
const sessionId = ref<string | null>(null)
const listEl = ref<HTMLDivElement | null>(null)
const sessions = ref<any[]>([])
const presets = ref<any[]>([])
const presetId = ref<number | null>(null)
const usage = ref<any>(null)
const toast = ref('')
const historyOpen = ref(false)
let abort: AbortController | null = null
const SESSION_KEY = 'frw-chat-session'

const TOOL_LABEL: Record<string, string> = {
  search_enterprise: '搜索企业', get_score_profile: '获取评分画像', get_risk_facts: '获取风险事实',
  list_enterprises_by_level: '按等级筛选', get_platform_overview: '平台总览', run_risk_analysis: '触发研判',
  refresh_enterprise_data: '数据源刷新', resolve_stock_code: '解析代码', add_enterprise: '添加企业',
  list_alerts: '查询预警', handle_alert: '处置预警', get_alert_report: '预警报告',
  list_skills: '查看技能', load_skill: '载入技能', get_financial_analysis: '金融分析',
  compare_financials: '财务对比', screen_by_financial_metric: '指标筛选',
}

async function loadPresets() { try { presets.value = (await api.presets()).items.filter((p: any) => p.enabled) } catch { presets.value = [] } }
async function loadSessions() { try { sessions.value = (await api.chatSessions()).sessions } catch { sessions.value = [] } }
function scrollBottom() { nextTick(() => listEl.value?.scrollTo({ top: listEl.value.scrollHeight, behavior: 'smooth' })) }

function render(text: string) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^### (.+)$/gm, '<h4>$1</h4>').replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n{2,}/g, '<br/><br/>').replace(/\n/g, '<br/>')
}

async function decide(card: ToolCard, approved: boolean) {
  if (!card.approval || card.approval.status !== 'pending') return
  try { await api.chatApprove(card.approval.id, approved); card.approval.status = approved ? 'approved' : 'rejected' }
  catch (e) { card.approval.status = 'rejected'; card.result = { ok: false, error: (e as Error).message } }
}

async function send(text?: string) {
  const content = (text ?? input.value).trim()
  if (!content || busy.value) return
  input.value = ''
  busy.value = true
  messages.value.push({ role: 'user', text: content, tools: [] })
  const reply: ChatMsg = { role: 'assistant', text: '', tools: [], streaming: true }
  messages.value.push(reply)
  await scrollBottom()
  abort = new AbortController()
  try {
    const resp = await fetch(api.chatStreamUrl, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: content, session_id: sessionId.value, preset_id: presetId.value }),
      signal: abort.signal,
    })
    if (!resp.body) throw new Error('服务端未返回流')
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const blocks = buf.split('\n\n')
      buf = blocks.pop() ?? ''
      for (const block of blocks) {
        const ev = block.split('\n').find((l) => l.startsWith('event: '))
        const dl = block.split('\n').find((l) => l.startsWith('data: '))
        if (!ev || !dl) continue
        let data: any = {}
        try { data = JSON.parse(dl.slice(6)) } catch { continue }
        const e = ev.slice(7).trim()
        if (e === 'session') { sessionId.value = data.session_id; localStorage.setItem(SESSION_KEY, data.session_id) }
        else if (e === 'token') reply.text += data.text ?? ''
        else if (e === 'reasoning') reply.reasoning = (reply.reasoning ?? '') + (data.text ?? '')
        else if (e === 'tool') reply.tools.push({ id: data.id, name: data.name, args: data.args ?? {}, readOnly: data.read_only, running: true })
        else if (e === 'tool_result') { const c = reply.tools.find((t) => t.id === data.id); if (c) { c.running = false; c.result = data.result; c.latencyMs = data.latency_ms } }
        else if (e === 'approval') { const c = reply.tools.find((t) => t.id === data.id); if (c) c.approval = { id: data.approval_id, description: data.description, status: 'pending' } }
        else if (e === 'usage') usage.value = data
        else if (e === 'compaction') reply.notice = data.phase === 'done' ? `已压缩 ${data.folded} 条历史消息为摘要` : ''
        else if (e === 'error') reply.error = data.message
        else if (e === 'done') { reply.streaming = false; if (data.usage) usage.value = data.usage; loadSessions() }
      }
    }
  } catch (err) { if ((err as Error).name !== 'AbortError') reply.error = (err as Error).message }
  finally { reply.streaming = false; busy.value = false; abort = null; await scrollBottom() }
}

async function openSession(id: string) {
  try {
    const r = await api.chatSession(id)
    sessionId.value = r.session_id; localStorage.setItem(SESSION_KEY, r.session_id)
    messages.value = (r.messages ?? []).map((m: any) => m.role === 'user'
      ? { role: 'user', text: m.content, tools: [] }
      : { role: 'assistant', text: m.content, tools: (m.tool_calls ?? []).map((tc: any) => ({ id: tc.id, name: tc.function?.name ?? '', args: {}, running: false })) })
    usage.value = r.usage ?? null
  } catch { /* 会话不存在则忽略 */ }
}
function newChat() { abort?.abort(); busy.value = false; messages.value = []; sessionId.value = null; localStorage.removeItem(SESSION_KEY) }
async function shareSession() { if (!sessionId.value) return; const r = await api.chatShare(sessionId.value); flash(`分享链接：${location.origin}${r.url}`) }
function flash(msg: string, ms = 4000) { toast.value = msg; setTimeout(() => (toast.value = ''), ms) }

// ---------------- 表格 ----------------
const tables = ref<any[]>([])
const templates = ref<any[]>([])
const openTable = ref<any>(null)
const validation = ref<any>(null)
async function loadTables() { try { tables.value = (await api.tables()).items } catch { tables.value = [] } }
async function loadTemplates() { try { templates.value = (await api.tablesTemplates()).templates } catch { templates.value = [] } }
async function createTable(kind: string) { const r = await api.tableCreate({ kind, title: '', periods: ['2025', '2024'] }); await openTableDoc(r.table_id) }
async function openTableDoc(id: number) { openTable.value = await api.tableGet(id); validation.value = null }
async function writeCell(row: string, col: string, value: string) {
  await api.tableWriteCells(openTable.value.id, { row, col, value: parseFloat(value) || value })
  await openTableDoc(openTable.value.id)
}
async function validateTable() { validation.value = await api.tableValidate(openTable.value.id) }
async function ingestTable() { const r = await api.tableIngest(openTable.value.id); toast.value = r.error ? `入库失败：${r.error}` : '入库成功'; setTimeout(() => (toast.value = ''), 5000); await loadTables() }

// ---------------- MCP ----------------
const mcpServers = ref<any[]>([])
const mcpForm = ref({ name: '', url: '' })
async function loadMcp() { try { mcpServers.value = (await api.mcpServers()).items } catch { mcpServers.value = [] } }
async function addMcp() { await api.mcpAddServer(mcpForm.value); mcpForm.value = { name: '', url: '' }; loadMcp() }
async function syncMcp(id: number) { await api.mcpSyncServer(id); loadMcp() }

// ---------------- 预设 ----------------
const skills = ref<any[]>([])
async function loadSkills() { try { skills.value = (await api.skills()).items } catch { skills.value = [] } }

// ---------------- 设置 ----------------
const settingsView = ref<any>(null)
const settingsForm = ref<Record<string, any>>({})
async function loadSettings() {
  settingsView.value = await api.settings()
  for (const g of settingsView.value.groups) for (const f of g.items) if (f.type !== 'password') settingsForm.value[f.key] = f.value
}
async function saveSettings() { await api.settingsUpdate(settingsForm.value); toast.value = '已保存并生效'; setTimeout(() => (toast.value = ''), 3000) }

function fmtMs(ms?: number) { return ms === undefined ? '' : ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s` }

onMounted(async () => { loadPresets(); loadSessions(); const s = localStorage.getItem(SESSION_KEY); if (s) await openSession(s) })
</script>
<template>
  <div class="ws">
    <aside class="ws-rail">
      <button v-for="t in TABS" :key="t.key" class="ws-rail-btn" :class="{ on: tab === t.key }" :title="t.label" @click="tab = t.key">{{ t.icon }}</button>
    </aside>

    <main class="ws-main">
      <section v-if="tab === 'chat'" class="ws-panel chat">
        <div class="ws-toolbar">
          <button class="btn ghost small" @click="historyOpen = !historyOpen">🕘 历史</button>
          <span v-if="sessionId" class="muted small">会话 {{ sessionId }}</span>
          <span v-if="usage?.llm_calls" class="muted small">缓存命中 {{ Math.round((usage.cache_hit_rate ?? 0) * 100) }}%</span>
          <div class="spacer"></div>
          <select v-model="presetId" class="sel small">
            <option :value="null">通用（默认）</option>
            <option v-for="p in presets" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
          <button class="btn ghost small" :disabled="!sessionId" @click="shareSession">🔗 分享</button>
          <button class="btn ghost small" @click="newChat">＋ 新对话</button>
        </div>

        <div v-if="historyOpen" class="history">
          <div v-if="!sessions.length" class="muted small">暂无会话</div>
          <div v-for="s in sessions" :key="s.id" class="history-item" :class="{ cur: s.id === sessionId }" @click="openSession(s.id)">
            <span class="small">{{ s.title }}</span>
            <span class="muted small">{{ s.message_count }} 条</span>
            <button class="btn ghost small" @click.stop="api.chatDelete(s.id).then(loadSessions)">✕</button>
          </div>
        </div>

        <div ref="listEl" class="chat-list">
          <div v-if="!messages.length" class="welcome">
            <p class="ws-title">你好，我是险小e</p>
            <p class="muted small">问我企业风险，我会自动取数、评分、找证据。</p>
            <div class="suggests">
              <button v-for="s in ['康美药业现在风险怎么样？', '600519 的财务分析给我看看', '平台里哪些企业是高风险？']" :key="s" class="suggest" @click="send(s)">{{ s }}</button>
            </div>
          </div>
          <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
            <div class="bubble" :class="{ user: m.role === 'user' }">
              <div v-if="m.reasoning" class="muted small">🧠 {{ m.reasoning }}</div>
              <div v-for="t in m.tools" :key="t.id" class="tool-card" :class="{ running: t.running }">
                <div class="tool-head">
                  <span>{{ t.running ? '⏳' : '🔧' }}</span>
                  <b class="small">{{ TOOL_LABEL[t.name] ?? t.name }}</b>
                  <code class="small muted">{{ JSON.stringify(t.args) }}</code>
                  <span v-if="t.readOnly === false" class="tag-warn">动作</span>
                  <span v-if="t.latencyMs" class="muted small">{{ fmtMs(t.latencyMs) }}</span>
                </div>
                <div v-if="t.result" class="muted small">
                  <template v-if="t.result.ok === false">{{ t.result.error }}</template>
                  <template v-else>
                    <span v-if="t.result.count !== undefined">{{ t.result.count }} 条</span>
                    <span v-if="t.result.score !== undefined"> · {{ t.result.score }} 分（{{ t.result.grade }}）</span>
                    <span v-if="t.result.enterprise_total !== undefined"> · {{ t.result.enterprise_total }} 家企业</span>
                  </template>
                </div>
                <div v-if="t.approval" class="approval">
                  <b class="small">需要授权：</b><span class="small">{{ t.approval.description }}</span>
                  <div v-if="t.approval.status === 'pending'" class="ap-actions">
                    <button class="btn primary small" @click="decide(t, true)">允许</button>
                    <button class="btn ghost small" @click="decide(t, false)">拒绝</button>
                  </div>
                  <div v-else class="small">{{ t.approval.status === 'approved' ? '✅ 已授权' : '🚫 已拒绝' }}</div>
                </div>
              </div>
              <div v-if="m.text" v-html="render(m.text)"></div>
              <div v-else-if="m.streaming" class="typing"><i></i><i></i><i></i></div>
              <div v-if="m.notice" class="notice small">🗜️ {{ m.notice }}</div>
              <div v-if="m.error" class="err small">{{ m.error }}</div>
            </div>
          </div>
        </div>

        <div class="composer">
          <textarea v-model="input" rows="2" placeholder="提问…（Enter 发送）" @keydown.enter.exact.prevent="send()"></textarea>
          <button v-if="busy" class="btn ghost" @click="abort?.abort()">停止</button>
          <button v-else class="btn primary" :disabled="!input.trim()" @click="send()">发送</button>
        </div>
      </section>

      <section v-else-if="tab === 'tables'" class="ws-panel">
        <div class="ws-toolbar">
          <button class="btn ghost small" @click="loadTables(); loadTemplates()">🔄 刷新</button>
          <button v-for="tp in templates" :key="tp.kind" class="btn ghost small" @click="createTable(tp.kind)">＋{{ tp.title }}</button>
        </div>
        <div v-if="!openTable" class="table-list">
          <div v-for="t in tables" :key="t.id" class="row-card" @click="openTableDoc(t.id)">
            <b class="small">{{ t.title }}</b>
            <span class="muted small">{{ t.enterprise ?? t.stock_code }} · {{ t.unit }} · {{ t.status }}</span>
          </div>
          <div v-if="!tables.length" class="muted small">暂无表格，点击上方模板新建</div>
        </div>
        <div v-else class="table-editor">
          <div class="ws-toolbar">
            <b class="small">{{ openTable.title }}</b>
            <button class="btn ghost small" @click="openTable = null">返回</button>
            <button class="btn ghost small" @click="validateTable">勾稽校验</button>
            <button class="btn primary small" @click="ingestTable">入库</button>
          </div>
          <div class="muted small">绑定企业代码：
            <input v-model="openTable.stock_code" class="input" placeholder="如 600519" @change="api.tableUpdate(openTable.id, { stock_code: openTable.stock_code })" />
          </div>
          <table class="grid">
            <thead><tr><th>科目</th><th v-for="c in openTable.sheet.columns" :key="c.key">{{ c.label || c.period }}</th></tr></thead>
            <tbody>
              <tr v-for="r in openTable.sheet.rows" :key="r.key">
                <td class="small">{{ r.label }}</td>
                <td v-for="c in openTable.sheet.columns" :key="c.key">
                  <input class="cell" :value="r.cells?.[c.key]?.value ?? ''" @change="writeCell(r.key, c.key, ($event.target as HTMLInputElement).value)" />
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="validation" class="small" :class="validation.ok ? 'ok' : 'err'">
            {{ validation.ok ? '✅ 勾稽通过' : `❌ ${validation.errors} 个错误、${validation.warnings} 个警告` }}
            <div v-for="(iss, idx) in validation.issues.filter((x: any) => x.level === 'error')" :key="idx" class="err small">{{ iss.message }}</div>
          </div>
        </div>
      </section>

      <section v-else-if="tab === 'mcp'" class="ws-panel">
        <div class="ws-toolbar">
          <button class="btn ghost small" @click="loadMcp">🔄 刷新</button>
          <input v-model="mcpForm.name" class="input" placeholder="名称" />
          <input v-model="mcpForm.url" class="input" placeholder="http://…" />
          <button class="btn primary small" @click="addMcp">添加</button>
        </div>
        <div v-for="s in mcpServers" :key="s.id" class="row-card">
          <div><b class="small">{{ s.name }}</b> <span class="tag" :class="s.status === 'ok' ? 'ok' : 'err'">{{ s.status }}</span></div>
          <div class="muted small">{{ s.url }} · {{ s.tool_count }} 个工具</div>
          <div>
            <button class="btn ghost small" @click="syncMcp(s.id)">同步</button>
            <button class="btn ghost small" @click="api.mcpTestServer(s.id).then((r) => flash(r.ok ? '连通成功' : `失败：${r.error}`))">测试</button>
            <button class="btn ghost small" @click="api.mcpDeleteServer(s.id).then(loadMcp)">删除</button>
          </div>
        </div>
      </section>

      <section v-else-if="tab === 'presets'" class="ws-panel">
        <div class="ws-toolbar"><button class="btn ghost small" @click="loadPresets(); loadSkills()">🔄 刷新</button></div>
        <div v-for="p in presets" :key="p.id" class="row-card">
          <b class="small">{{ p.name }}</b> <span v-if="p.builtin" class="tag">内置</span>
          <div class="muted small">{{ p.description }}</div>
        </div>
        <h4 class="small">技能库</h4>
        <div v-for="s in skills" :key="s.id" class="row-card">
          <b class="small">{{ s.name }}</b>
          <div class="muted small">{{ s.description }}</div>
        </div>
      </section>

      <section v-else class="ws-panel">
        <div v-if="settingsView">
          <div v-for="g in settingsView.groups" :key="g.group" class="settings-group">
            <h4 class="small">{{ g.group }}</h4>
            <div v-for="f in g.items" :key="f.key" class="settings-row">
              <label class="small">{{ f.label }}</label>
              <input v-if="f.type === 'bool'" v-model="settingsForm[f.key]" type="checkbox" />
              <input v-else-if="f.type === 'int' || f.type === 'float'" v-model.number="settingsForm[f.key]" type="number" class="input" />
              <input v-else-if="f.type === 'password'" :value="f.value" type="password" class="input" @change="settingsForm[f.key] = ($event.target as HTMLInputElement).value" />
              <input v-else v-model="settingsForm[f.key]" class="input" />
              <div class="muted small">{{ f.desc }}</div>
            </div>
          </div>
          <button class="btn primary" @click="saveSettings">保存并生效</button>
        </div>
        <button v-else class="btn primary" @click="loadSettings">加载设置</button>
      </section>

      <div v-if="toast" class="toast">{{ toast }}</div>
    </main>
  </div>
</template>

<style scoped>
.ws { display: flex; gap: 10px; height: calc(100vh - 152px); min-height: 520px; }
.ws-rail { width: 52px; flex: none; display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 8px 0; background: var(--card); border: 1px solid var(--border); border-radius: 12px; }
.ws-rail-btn { width: 36px; height: 36px; border: 1px solid transparent; background: transparent; border-radius: 9px; font-size: 17px; cursor: pointer; color: var(--text); }
.ws-rail-btn:hover, .ws-rail-btn.on { background: var(--hover); border-color: var(--primary); }
.ws-main { flex: 1; min-width: 0; position: relative; display: flex; flex-direction: column; }
.ws-panel { flex: 1; min-height: 0; background: var(--card); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow); padding: 12px 14px; overflow-y: auto; }
.chat { display: flex; flex-direction: column; }
.ws-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding-bottom: 8px; border-bottom: 1px dashed var(--border); margin-bottom: 8px; }
.spacer { flex: 1; }
.ws-title { font-weight: 700; margin: 0 0 4px; font-size: 14px; }
.muted { color: var(--text-sub); }
.small { font-size: 12px; }
.chat-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; padding-right: 4px; }
.welcome { margin: auto; text-align: center; max-width: 420px; }
.suggests { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 10px; }
.suggest { border: 1px solid var(--border); background: var(--bg-elev); color: var(--text); border-radius: 999px; padding: 6px 12px; font-size: 12px; cursor: pointer; font-family: inherit; }
.suggest:hover { border-color: var(--primary); color: var(--primary); }
.msg { display: flex; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 86%; background: var(--hover); border-radius: 12px; padding: 10px 13px; font-size: 13px; line-height: 1.7; word-break: break-word; }
.bubble.user { background: linear-gradient(135deg, var(--primary), var(--primary-deep)); color: #fff; }
.tool-card { border: 1px solid var(--border); border-left: 3px solid var(--accent); background: var(--bg-elev); border-radius: 8px; padding: 7px 10px; margin: 6px 0; font-size: 11.5px; }
.tool-card.running { border-left-color: var(--warn); }
.tool-head { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.tag-warn { font-size: 10px; color: var(--warn); border: 1px solid currentColor; border-radius: 4px; padding: 0 5px; }
.approval { margin-top: 6px; border: 1px solid rgba(217, 119, 6, 0.45); background: rgba(217, 119, 6, 0.08); border-radius: 8px; padding: 8px 10px; }
.ap-actions { display: flex; gap: 6px; margin-top: 6px; }
.typing { display: inline-flex; gap: 5px; padding: 12px 14px; }
.typing i { width: 6px; height: 6px; border-radius: 50%; background: var(--text-sub); animation: blink 1.2s infinite; }
.typing i:nth-child(2) { animation-delay: 0.2s; }
.typing i:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink { 0%, 60%, 100% { opacity: 0.25; } 30% { opacity: 1; } }
.notice { font-size: 11.5px; color: var(--warn); }
.err { color: var(--danger); }
.ok { color: var(--ok); }
.composer { display: flex; gap: 8px; align-items: flex-end; padding-top: 10px; border-top: 1px solid var(--border); margin-top: 10px; }
.composer textarea { flex: 1; resize: none; border: 1px solid var(--border); border-radius: 10px; padding: 9px 11px; font-family: inherit; font-size: 13px; background: var(--bg-elev); color: var(--text); outline: none; }
.composer textarea:focus { border-color: var(--primary); }
.history { border: 1px solid var(--border); border-radius: 10px; max-height: 200px; overflow-y: auto; margin-bottom: 8px; padding: 4px; }
.history-item { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 8px; cursor: pointer; }
.history-item:hover { background: var(--hover); }
.history-item.cur { background: rgba(37, 99, 235, 0.08); }
.row-card { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin-bottom: 8px; background: var(--bg-elev); cursor: pointer; }
.row-card:hover { border-color: var(--primary); }
.tag { font-size: 10px; border-radius: 4px; padding: 0 5px; margin-left: 6px; border: 1px solid currentColor; }
.input { border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; font-size: 12px; background: var(--bg-elev); color: var(--text); outline: none; }
.input:focus { border-color: var(--primary); }
.grid { width: 100%; border-collapse: collapse; margin-top: 8px; }
.grid th, .grid td { border: 1px solid var(--border-soft); padding: 4px 6px; font-size: 12px; text-align: left; }
.cell { width: 90px; border: none; background: transparent; color: var(--text); font-size: 12px; outline: none; }
.settings-group { margin-bottom: 14px; }
.settings-row { margin-bottom: 10px; }
.settings-row label { display: inline-block; min-width: 130px; }
.toast { position: fixed; bottom: 24px; right: 24px; background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 10px 14px; box-shadow: var(--shadow); z-index: 60; font-size: 13px; }
</style>
