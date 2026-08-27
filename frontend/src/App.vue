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
      </el-descriptions>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div>
          <h2>Agentic RAG Console</h2>
          <p>FastAPI / SSE / Redis / RRF / Tool Registry</p>
        </div>
        <el-tag effect="plain">Vue3 + Element Plus</el-tag>
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
        </el-card>

        <div class="grid">
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
import { computed, ref } from 'vue'
import { CloseBold, Refresh, Tickets, Tools, VideoPlay } from '@element-plus/icons-vue'

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

const API_BASE = 'http://localhost:8000'

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

const statusType = computed(() => {
  if (status.value === 'completed') return 'success'
  if (status.value === 'failed') return 'danger'
  if (status.value === 'cancelled' || status.value === 'cancel_requested') return 'warning'
  if (status.value === 'running') return 'primary'
  return 'info'
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
    if (!response.body) return

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
  } finally {
    loading.value = false
    if (!status.value || status.value === 'running') {
      status.value = 'completed'
    }
  }
}

async function cancelTask() {
  // 取消不会直接中断浏览器请求，而是把 cancel_requested 写到后端任务状态。
  // workflow 会在节点边界看到这个状态并停止后续节点。
  if (!activeTaskId.value) return
  const response = await fetch(`${API_BASE}/api/tasks/${activeTaskId.value}/cancel`, {
    method: 'POST',
  })
  const result = await response.json()
  status.value = String(result.status || 'cancel_requested')
}

async function loadMemory() {
  // 读取当前 session 的最近对话，用来确认 Redis/内存记忆是否写入成功。
  const response = await fetch(`${API_BASE}/api/sessions/${sessionId.value}/memory`)
  memory.value = JSON.stringify(await response.json(), null, 2)
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

.evidence-item {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fbfcfe;
  padding: 12px;
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
