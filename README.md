# Agentic-RAG-Platform

面向企业知识库和多工具任务的 Agentic RAG 平台骨架。这个仓库用于展示大模型应用工程中的完整链路：文档接入、切片检索、重排、会话记忆、SSE 流式输出、工具调用、状态管理和可观测性。

## 为什么做这个项目

普通 RAG demo 往往只做“上传文档 -> 向量检索 -> 调模型回答”。真正面试和落地时，面试官更关心的是：

- chunk 怎么切，召回不准怎么排查；
- 检索结果过多时如何 rerank 和融合；
- 多轮会话、用户偏好、任务状态放哪里；
- FastAPI 怎么通过 SSE 把 Agent 中间过程流式推给前端；
- Redis 在 Agent 系统里到底存什么；
- 工具 schema 怎么设计，参数合法但业务非法怎么拦；
- 用户点停止、服务重启、工具超时、模型超时怎么处理；
- 如何做评测、监控、trace 和灰度。

所以这个项目不是聊天壳子，而是一个可扩展的 Agentic RAG 工程样板。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| API | FastAPI, Pydantic, SSE |
| Agent 编排 | LangGraph 风格状态机，后续可替换为真实 LangGraph StateGraph |
| RAG | 文档切片、关键词召回、轻量重排、证据引用 |
| 记忆 | Redis 优先，内存 fallback；用于 session state、短期记忆、限流和 checkpoint 指针 |
| 工具调用 | Tool registry、schema 校验、业务校验、结构化错误 |
| 前端 | Vue3 + TypeScript + Vite |
| 测试 | pytest |

## 架构

```text
Vue3 Frontend
  |
  | POST /api/chat/stream
  v
FastAPI SSE API
  |
  +-- MemoryService
  |     +-- Redis session state
  |     +-- in-memory fallback
  |
  +-- AgentWorkflow
        |
        +-- understand: 意图识别 / 查询改写
        +-- retrieve: 文档召回
        +-- rerank: 证据重排
        +-- tool: 工具调用与业务校验
        +-- answer: 带证据的最终回答
```

## 核心设计

### 1. Agentic RAG 而不是被动 RAG

被动 RAG 是一次检索一次回答。这里按 Agentic RAG 思路拆成多个节点：

- `understand`：识别用户意图，提取查询和约束。
- `retrieve`：从知识库召回候选片段。
- `rerank`：根据关键词覆盖、元数据和长度惩罚做轻量重排。
- `tool`：需要实时信息时走工具 registry。
- `answer`：输出答案，同时返回证据片段。

### 2. 记忆不全塞向量库

项目把记忆分成三类：

- 当前会话消息：适合 Redis list / hash。
- 长期偏好：适合后续接向量库或关系库。
- checkpoint 指针：适合 Redis key-value，指向持久化图状态。

这样可以避免长对话全部向量化导致的检索慢、冲突记忆难删除、过期事实污染回答。

### 3. SSE 流式输出

后端不是等整个回答生成完才返回，而是把每个 Agent 节点的状态事件逐步推给前端：

- `understand`：正在理解任务。
- `retrieve`：找到多少候选证据。
- `rerank`：保留哪些证据。
- `tool`：是否调用工具。
- `answer`：最终回答。

这类设计能让用户看到进度，也方便后续做 trace 和监控。

### 4. 工具调用的安全边界

工具层不只检查 JSON 类型，还要做业务校验：

- 订单、用户、租户是否匹配；
- 工具是否允许当前意图调用；
- 参数是否越权；
- 工具超时后是否可重试；
- 返回数据是否可信。

## 运行方式

### 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

### 快速测试

```bash
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","message":"如何限制 RAG 幻觉？"}'
```

## 面试可讲点

### 问：LangChain 和 LangGraph 什么时候用？

答：如果只是单轮 RAG，LangChain chain 足够；如果要做多节点状态、条件分支、工具调用、失败重试、人工反馈和恢复，就要上 LangGraph。这个项目当前用轻量 workflow 展示边界，后续可以直接替换成 StateGraph。

### 问：Redis 在 Agent 里存什么？

答：Redis 不只是缓存答案。它可以存 session state、短期记忆、限流计数、checkpoint 指针、异步工具回调和分布式锁。长期语义记忆再接向量库。

### 问：RAG 答非所问怎么排查？

答：按清洗、切片、embedding、metadata filter、top_k、rerank、prompt、模型生成依次排查。不要一上来就改 prompt。

### 问：SSE 断线重连怎么做？

答：事件要有 `event_id` 和 `trace_id`，后端把节点事件写入事件日志。前端重连带 last event id，后端从 checkpoint 或事件日志续发。

## 当前状态

这是一个作品集骨架，重点展示系统设计、接口边界和工程文档。它和 `OurAgent-he1` 互补：

- `OurAgent-he1` 强在具身任务、ROS 文本接入、中断恢复、反思。
- `Agentic-RAG-Platform` 强在企业知识库、RAG、SSE、Redis、多工具服务化。

## 许可

MIT License.
