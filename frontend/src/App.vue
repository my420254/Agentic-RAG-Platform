<template>
  <el-container class="shell">
    <el-aside width="336px" class="sidebar">
      <div class="brand">
        <span>Agentic RAG Platform</span>
        <h1>运行工作台</h1>
        <p>知识检索、工具调用、任务状态和节点级 Trace 的精简控制台。</p>
      </div>

      <el-form label-position="top" class="task-form">
        <el-form-item label="Session">
          <el-input v-model="sessionId" />
        </el-form-item>
        <el-form-item label="任务输入">
          <el-input v-model="message" type="textarea" :rows="5" resize="none" />
        </el-form-item>
      </el-form>

      <el-space fill class="control-stack">
        <el-button type="primary" :icon="VideoPlay" :loading="loading" @click="send">
          运行
        </el-button>
        <el-button :icon="Search" @click="diagnoseRetrieval">
          检索诊断
        </el-button>
        <el-button :icon="DataAnalysis" @click="runRetrievalEval">
          运行评测
        </el-button>
        <el-button :icon="CloseBold" :disabled="!activeTaskId || !loading" @click="cancelTask">
          取消
        </el-button>
        <el-button :icon="Refresh" @click="loadMemory">
          读取记忆
        </el-button>
      </el-space>

      <el-descriptions :column="1" border size="small" class="status-box">
        <el-descriptions-item label="Task">
          <span class="mono">{{ activeTaskId || '-' }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="Status">
          <el-tag :type="statusType">{{ status || '-' }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="Events">
          {{ events.length }}
        </el-descriptions-item>
        <el-descriptions-item label="Docs">
          {{ docStats?.documents ?? '-' }} / {{ docStats?.chunks ?? '-' }} chunks
        </el-descriptions-item>
        <el-descriptions-item label="LLM">
          <el-tag :type="llmStatusType">{{ llmLabel }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="API">
          <span class="mono">{{ API_BASE }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="API状态">
          <el-tag :type="apiError ? 'danger' : 'success'">
            {{ apiError ? 'error' : 'ready' }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div>
          <h2>Agentic RAG Console</h2>
          <p>FastAPI / SSE / Redis / RRF / Tool Registry / vLLM-Qwen</p>
        </div>
        <el-tag effect="plain">{{ llmStatus?.model || 'Vue3 + Element Plus' }}</el-tag>
      </el-header>

      <el-main class="workspace">
        <el-card shadow="never" class="answer-card">
          <template #header>
            <div class="card-head">
              <span>最终回答</span>
              <el-tag v-if="citations.length" type="success" effect="plain">
                {{ citations.length }} citations
              </el-tag>
            </div>
          </template>
          <p class="answer">{{ answer || '等待任务执行结果。' }}</p>
          <el-space v-if="citations.length" wrap class="citation-row">
            <el-tag v-for="item in citations" :key="item" type="success">
              {{ item }}
            </el-tag>
          </el-space>
          <p v-if="apiError" class="error-text">{{ apiError }}</p>
        </el-card>

        <div class="grid">
          <el-card shadow="never">
            <template #header>
              <div class="card-head">
                <span>知识库文档</span>
                <el-space>
                  <el-button size="small" text @click="loadDemoKnowledge">演示知识</el-button>
                  <el-button size="small" text @click="loadDocuments">刷新</el-button>
                </el-space>
              </div>
            </template>
            <el-form label-position="top" class="ingest-form">
              <el-form-item label="文档 ID">
                <el-input v-model="ingestDocId" placeholder="例如 incident_playbook" />
              </el-form-item>
              <el-form-item label="文档内容">
                <el-input v-model="ingestText" type="textarea" :rows="3" resize="none" />
              </el-form-item>
              <el-button type="primary" plain :icon="Upload" @click="ingestDocument">
                写入知识库
              </el-button>
            </el-form>
            <el-scrollbar height="260px" class="doc-list">
              <el-empty v-if="!documents.length" description="暂无文档" />
              <section v-for="doc in documents" v-else :key="doc.doc_id" class="doc-item">
                <strong>{{ doc.doc_id }}</strong>
                <span>{{ doc.chunks }} chunks · {{ doc.source }}</span>
                <p>{{ doc.sample }}</p>
              </section>
            </el-scrollbar>
          </el-card>

          <el-card shadow="never">
            <template #header>
              <div class="card-head">
                <span>检索证据</span>
                <el-tag effect="plain">{{ evidence.length }}</el-tag>
              </div>
            </template>
            <el-scrollbar height="360px">
              <el-empty v-if="!evidence.length" description="暂无证据" />
              <div v-else class="evidence-list">
                <section v-for="item in evidence" :key="item.doc_id" class="evidence-item">
                  <div class="item-head">
                    <strong>{{ item.doc_id }}</strong>
                    <el-tag type="info" effect="plain">{{ item.score.toFixed(4) }}</el-tag>
                  </div>
                  <p>{{ item.text }}</p>
                  <el-space wrap>
                    <el-tag size="small">{{ item.source }}</el-tag>
                    <el-tag size="small" type="success">
                      {{ item.metadata?.fusion || 'ranking' }}
                    </el-tag>
                  </el-space>
                </section>
              </div>
            </el-scrollbar>
          </el-card>

          <el-card shadow="never">
            <template #header>
              <div class="card-head">
                <span>检索诊断 / 评测</span>
                <el-tag v-if="evalResult" type="success" effect="plain">
                  Hit@K {{ evalResult.hit_rate }}
                </el-tag>
              </div>
            </template>
            <pre>{{ diagnosticsText }}</pre>
          </el-card>

          <el-card shadow="never">
            <template #header>
              <div class="card-head">
                <span>节点事件</span>
                <el-tag effect="plain">{{ status || 'idle' }}</el-tag>
              </div>
            </template>
            <el-scrollbar height="360px">
              <el-empty v-if="!events.length" description="暂无事件" />
              <el-timeline v-else>
                <el-timeline-item
                  v-for="event in events"
                  :key="event.id"
                  :timestamp="event.type"
                  placement="top"
                >
                  <code>{{ compact(event.data) }}</code>
                </el-timeline-item>
              </el-timeline>
            </el-scrollbar>
          </el-card>

          <el-card shadow="never">
            <template #header>
              <div class="card-head">
                <span>工具结果</span>
                <el-icon><Tools /></el-icon>
              </div>
            </template>
            <pre>{{ toolResult ? JSON.stringify(toolResult, null, 2) : '暂无工具调用。' }}</pre>
          </el-card>

          <el-card shadow="never">
            <template #header>
              <div class="card-head">
                <span>会话记忆</span>
                <el-icon><Tickets /></el-icon>
              </div>
            </template>
            <pre>{{ memory || '点击“读取记忆”查看当前 session。' }}</pre>
          </el-card>
        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  CloseBold,
  DataAnalysis,
  Refresh,
  Search,
  Tickets,
  Tools,
  Upload,
  VideoPlay,
} from '@element-plus/icons-vue'

type Evidence = {
  doc_id: string
  text: string
  source: string
  score: number
  metadata?: Record<string, unknown>
}

type RuntimeEvent = {
  id: number
  type: string
  data: Record<string, unknown>
}

type DocumentItem = {
  doc_id: string
  source: string
  chunks: number
  tokens: number
  sample: string
}

type DocumentStats = {
  documents: number
  chunks: number
  tokens: number
  sources: string[]
}

type EvalResult = {
  total: number
  top_k: number
  hit_rate: number
  mrr: number
  failed_cases: unknown[]
}

type LlmStatus = {
  enabled: boolean
  endpoint?: string
  provider?: string
  api_base: string
  model: string
  reachable?: boolean
  skipped?: boolean
  error?: string
  models?: string[]
}

const configuredApiBase = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const API_BASE = configuredApiBase || `${window.location.protocol}//${window.location.hostname}:18080`

const sessionId = ref('demo')
const message = ref('如何限制 RAG 幻觉？')
const events = ref<RuntimeEvent[]>([])
const evidence = ref<Evidence[]>([])
const memory = ref('')
const answer = ref('')
const citations = ref<string[]>([])
const toolResult = ref<Record<string, unknown> | null>(null)
const activeTaskId = ref('')
const status = ref('')
const loading = ref(false)
const documents = ref<DocumentItem[]>([])
const docStats = ref<DocumentStats | null>(null)
const diagnostics = ref<Record<string, unknown> | null>(null)
const evalResult = ref<EvalResult | null>(null)
const llmStatus = ref<LlmStatus | null>(null)
const apiError = ref('')
const ingestDocId = ref('team_rag_notes')
const ingestText = ref('企业知识库回答必须带引用证据；证据不足时应该拒答，并提示补充文档。')

const diagnosticsText = computed(() => {
  if (evalResult.value) {
    return JSON.stringify(evalResult.value, null, 2)
  }
  if (diagnostics.value) {
    return JSON.stringify(diagnostics.value, null, 2)
  }
  return '点击“检索诊断”查看 BM25 / vector / RRF 排名，点击“运行评测”查看 hit_rate 与 MRR。'
})

const statusType = computed(() => {
  if (status.value === 'completed') return 'success'
  if (status.value === 'failed') return 'danger'
  if (status.value === 'cancelled' || status.value === 'cancel_requested') return 'warning'
  if (status.value === 'running') return 'primary'
  return 'info'
})

const llmStatusType = computed(() => {
  if (!llmStatus.value?.enabled) return 'info'
  if (llmStatus.value.reachable) return 'success'
  return 'warning'
})

const llmLabel = computed(() => {
  if (!llmStatus.value) return 'checking'
  if (!llmStatus.value.enabled) return 'template'
  if (llmStatus.value.reachable) {
    return `${llmStatus.value.provider || 'llm'} / ${llmStatus.value.model}`
  }
  return 'unreachable'
})

onMounted(() => {
  void loadDocuments()
  void loadLlmStatus()
})

async function send() {
  // 运行一次流式任务：POST 提交问题，后端用 SSE 持续返回节点事件。
  resetRun()
  loading.value = true
  status.value = 'submitting'

  try {
    const response = await fetch(`${API_BASE}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId.value, message: message.value }),
    })
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
    if (!response.body) {
      throw new Error('后端没有返回 SSE 流。')
    }
    apiError.value = ''

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() || ''
      for (const chunk of chunks) {
        handleSseChunk(chunk)
      }
    }
  } catch (error) {
    status.value = 'failed'
    answer.value = `请求失败：${errorMessage(error)}`
    apiError.value = answer.value
  } finally {
    loading.value = false
    if (!status.value || status.value === 'running' || status.value === 'submitting') {
      status.value = 'completed'
    }
  }
}

async function ingestDocument() {
  // 写入一份临时文档，便于演示 chunk、召回和文档统计。
  const result = await requestJson('/api/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      doc_id: ingestDocId.value,
      text: ingestText.value,
      source: 'frontend_manual',
    }),
  })
  if (result) {
    await loadDocuments()
  }
}

async function loadDemoKnowledge() {
  // 重启后端或清理临时文档后，可一键恢复仓库自带演示知识。
  const result = await requestJson('/api/demo/load', { method: 'POST' })
  if (result) {
    await loadDocuments()
  }
}

async function loadDocuments() {
  // 文档列表用于确认当前知识库规模，避免只看到黑盒回答。
  const result = await requestJson<{ documents?: DocumentItem[]; stats?: DocumentStats }>('/api/documents')
  if (!result) return
  documents.value = result.documents || []
  docStats.value = result.stats || null
}

async function loadLlmStatus() {
  // 读取后端探测到的真实模型状态，用来确认当前是否走本地 vLLM/Qwen。
  const result = await requestJson<LlmStatus>('/api/llm/status')
  if (result) {
    llmStatus.value = result
  }
}

async function diagnoseRetrieval() {
  // 检索诊断暴露 tokens、两路召回和融合结果，方便定位召回问题。
  const result = await requestJson<Record<string, unknown>>('/api/retrieve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: message.value, top_k: 5 }),
  })
  if (!result) return
  diagnostics.value = result
  evalResult.value = null
}

async function runRetrievalEval() {
  // 使用后端默认评测集跑 hit_rate 和 MRR。
  const result = await requestJson<EvalResult>('/api/eval/retrieval', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ top_k: 5 }),
  })
  if (!result) return
  evalResult.value = result
  diagnostics.value = null
}

async function cancelTask() {
  // 取消不会直接中断浏览器请求，而是把 cancel_requested 写到后端任务状态。
  // workflow 会在节点边界看到这个状态并停止后续节点。
  if (!activeTaskId.value) return
  const result = await requestJson<Record<string, unknown>>(`/api/tasks/${activeTaskId.value}/cancel`, {
    method: 'POST',
  })
  if (!result) return
  status.value = String(result.status || 'cancel_requested')
}

async function loadMemory() {
  // 读取当前 session 的最近对话，用来确认 Redis/内存记忆是否写入成功。
  const result = await requestJson<Record<string, unknown>>(`/api/sessions/${sessionId.value}/memory`)
  if (result) {
    memory.value = JSON.stringify(result, null, 2)
  }
}

async function requestJson<T>(path: string, options?: RequestInit): Promise<T | null> {
  try {
    const response = await fetch(`${API_BASE}${path}`, options)
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
    apiError.value = ''
    return await response.json()
  } catch (error) {
    apiError.value = `API 请求失败：${errorMessage(error)}`
    return null
  }
}

function resetRun() {
  // 每次新运行前清空旧的证据、事件和工具结果，避免前后两次任务混在一起。
  events.value = []
  evidence.value = []
  answer.value = ''
  citations.value = []
  toolResult.value = null
  status.value = ''
  activeTaskId.value = ''
}

function handleSseChunk(chunk: string) {
  // 后端返回的是标准 SSE 文本块：event 表示节点名，data 是 JSON 载荷。
  const type = chunk.match(/^event: (.+)$/m)?.[1] || 'message'
  const payload = chunk.match(/^data: (.+)$/m)?.[1] || '{}'
  const data = safeJson(payload)
  const taskId = data.task_id
  if (typeof taskId === 'string') {
    activeTaskId.value = taskId
  }

  status.value = statusFromEvent(type, data)
  if (type === 'rerank' && Array.isArray(data.evidence)) {
    evidence.value = data.evidence as Evidence[]
  }
  if (type === 'tool') {
    toolResult.value = data
  }
  if (type === 'answer') {
    answer.value = String(data.answer || '')
    citations.value = Array.isArray(data.citations) ? data.citations.map(String) : []
  }

  events.value.push({ id: events.value.length + 1, type, data })
}

function safeJson(payload: string): Record<string, unknown> {
  // SSE data 理论上都是 JSON；这里保留兜底，避免单条异常事件弄崩前端。
  try {
    return JSON.parse(payload)
  } catch {
    return { raw: payload }
  }
}

function statusFromEvent(type: string, data: Record<string, unknown>) {
  // 优先相信后端显式 status；没有 status 时根据节点事件推断 UI 状态。
  if (typeof data.status === 'string') {
    return data.status
  }
  if (type === 'answer') return 'completed'
  if (type === 'cancelled') return 'cancelled'
  if (type === 'error') return 'failed'
  return 'running'
}

function compact(data: Record<string, unknown>) {
  return JSON.stringify(data)
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}
</script>

<style scoped>
:global(body) {
  margin: 0;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #17212f;
  background: #f4f7fb;
}

.shell {
  min-height: 100vh;
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 18px;
  border-right: 1px solid #dbe3ef;
  background: #ffffff;
  padding: 28px;
}

.brand span {
  color: #0f766e;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
}

.brand h1,
.topbar h2 {
  margin: 6px 0;
  letter-spacing: 0;
}

.brand p,
.topbar p,
.answer {
  margin: 0;
  color: #5f6f82;
  line-height: 1.7;
}

.task-form {
  margin-top: 6px;
}

.control-stack {
  width: 100%;
}

.control-stack :deep(.el-space__item),
.control-stack :deep(.el-button) {
  width: 100%;
}

.status-box {
  margin-top: 2px;
}

.mono {
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 76px;
  border-bottom: 1px solid #dbe3ef;
  background: #ffffff;
  padding: 0 24px;
}

.workspace {
  display: grid;
  gap: 18px;
  padding: 24px;
}

.answer-card,
.grid :deep(.el-card) {
  border-radius: 8px;
}

.error-text {
  margin: 12px 0 0;
  color: #b42318;
  font-size: 13px;
  line-height: 1.5;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-weight: 700;
}

.citation-row {
  margin-top: 14px;
}

.grid {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
  gap: 18px;
}

.evidence-list {
  display: grid;
  gap: 12px;
}

.ingest-form {
  margin-bottom: 14px;
}

.doc-list {
  border-top: 1px solid #edf2f7;
  padding-top: 12px;
}

.doc-item,
.evidence-item {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fbfcfe;
  padding: 12px;
}

.doc-item + .doc-item {
  margin-top: 10px;
}

.doc-item strong,
.doc-item span {
  display: block;
}

.doc-item span {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.doc-item p {
  margin: 8px 0 0;
  color: #334155;
  line-height: 1.55;
}

.item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.evidence-item p {
  margin: 8px 0 10px;
  color: #334155;
  line-height: 1.6;
}

code,
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: #334155;
  font-size: 12px;
}

pre {
  margin: 0;
}

@media (max-width: 960px) {
  .shell,
  .grid {
    display: block;
  }

  .sidebar {
    width: auto;
    border-right: 0;
    border-bottom: 1px solid #dbe3ef;
  }

  .topbar {
    height: auto;
    align-items: flex-start;
    gap: 12px;
    padding: 18px;
  }

  .workspace {
    padding: 18px;
  }

  .grid {
    margin-top: 18px;
  }

  .grid > * + * {
    margin-top: 18px;
  }
}
</style>
