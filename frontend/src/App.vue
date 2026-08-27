<template>
  <main class="layout">
    <aside class="sidebar">
      <h1>Agentic RAG</h1>
      <p>企业知识库、多轮记忆、SSE 流式输出和工具调用的工程样板。</p>
      <label>
        Session
        <input v-model="sessionId" />
      </label>
      <button @click="loadMemory">读取记忆</button>
      <pre>{{ memory }}</pre>
    </aside>

    <section class="workspace">
      <div class="toolbar">
        <textarea v-model="message" rows="3" />
        <button @click="send">发送</button>
      </div>

      <div class="events">
        <article v-for="event in events" :key="event.id" class="event">
          <strong>{{ event.type }}</strong>
          <pre>{{ event.payload }}</pre>
        </article>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const sessionId = ref('demo')
const message = ref('如何限制 RAG 幻觉？')
const events = ref<Array<{ id: number; type: string; payload: string }>>([])
const memory = ref('')

async function send() {
  events.value = []
  const response = await fetch('http://localhost:8000/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId.value, message: message.value }),
  })
  if (!response.body) return

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let index = 0

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''
    for (const chunk of chunks) {
      const type = chunk.match(/^event: (.+)$/m)?.[1] || 'message'
      const payload = chunk.match(/^data: (.+)$/m)?.[1] || '{}'
      events.value.push({ id: ++index, type, payload })
    }
  }
}

async function loadMemory() {
  const response = await fetch(`http://localhost:8000/api/sessions/${sessionId.value}/memory`)
  memory.value = JSON.stringify(await response.json(), null, 2)
}
</script>

<style scoped>
:global(body) {
  margin: 0;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #15202b;
  background: #f5f7fa;
}

.layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  min-height: 100vh;
}

.sidebar {
  background: #ffffff;
  border-right: 1px solid #d9e0e8;
  padding: 24px;
}

h1 {
  margin: 0 0 8px;
  font-size: 24px;
}

p {
  line-height: 1.6;
}

label {
  display: grid;
  gap: 8px;
  margin-top: 24px;
  font-size: 14px;
}

input,
textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #c9d3df;
  border-radius: 6px;
  padding: 10px 12px;
  font: inherit;
}

button {
  margin-top: 12px;
  border: 0;
  border-radius: 6px;
  background: #1664d9;
  color: white;
  padding: 10px 14px;
  font-weight: 600;
  cursor: pointer;
}

.workspace {
  padding: 24px;
}

.toolbar {
  display: grid;
  gap: 12px;
  background: #ffffff;
  border: 1px solid #d9e0e8;
  border-radius: 8px;
  padding: 16px;
}

.events {
  display: grid;
  gap: 12px;
  margin-top: 16px;
}

.event {
  background: #ffffff;
  border: 1px solid #d9e0e8;
  border-radius: 8px;
  padding: 14px;
}

pre {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
}

@media (max-width: 800px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .sidebar {
    border-right: 0;
    border-bottom: 1px solid #d9e0e8;
  }
}
</style>
