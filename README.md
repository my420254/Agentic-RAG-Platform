# Agentic-RAG-Platform

面向企业知识库、多轮问答和多工具任务的 Agentic RAG 平台骨架。项目重点不是做一个简单聊天界面，而是把大模型应用中的关键工程链路拆清楚：文档接入、切片检索、重排、会话记忆、SSE 流式输出、工具调用、状态管理和可观测性。

## 项目定位

传统 RAG demo 通常只覆盖“上传文档、检索片段、调用模型回答”。真实系统还需要处理更多工程问题：

- 文档清洗和 chunk 策略如何影响召回质量；
- 检索结果过多时如何 rerank 和证据融合；
- 多轮会话、用户偏好、任务状态应该放在哪里；
- 后端如何把 Agent 中间过程流式推给前端；
- Redis 在 Agent 系统里如何承担短期记忆、限流和 checkpoint 指针；
- 工具 schema 如何结合业务权限、参数校验和结构化错误；
- 用户取消、服务重启、工具超时、模型超时如何落到运行时设计；
- 如何为评测、监控、trace 和灰度扩展预留接口。

因此这个仓库按 Agentic RAG 的工程样板组织，强调链路可控、状态可追踪、模块可替换。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| API | FastAPI, Pydantic, SSE |
| Agent 编排 | 轻量状态机设计，接口可迁移到 LangGraph StateGraph |
| RAG | 文档切片、关键词召回、轻量重排、证据引用 |
| 记忆 | Redis 优先，内存 fallback；用于 session state、短期记忆、限流和 checkpoint 指针 |
| 工具调用 | Tool registry、schema 校验、业务校验、结构化错误 |
| 前端 | Vue3, TypeScript, Vite |
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

### Agentic RAG

项目把一次问答拆成多个可观测节点，而不是一次检索后直接生成：

- `understand`：识别用户意图，提取查询和约束；
- `retrieve`：从知识库召回候选片段；
- `rerank`：根据关键词覆盖、元数据和长度惩罚保留证据；
- `tool`：需要实时信息或业务动作时进入工具 registry；
- `answer`：基于证据生成最终回答，同时返回引用片段。

这种拆法让系统可以定位问题来源，也方便后续接入 LangGraph checkpoint、评测集和线上 trace。

### 分层记忆

项目没有把所有对话历史都塞进向量库，而是把记忆分成三类：

- 当前会话消息：适合 Redis list / hash；
- 长期偏好和语义知识：适合向量库或关系库；
- checkpoint 指针和任务状态：适合 Redis key-value。

这样可以避免长对话检索变慢、冲突记忆难删除、过期事实污染回答等问题。

### SSE 流式事件

后端通过 SSE 输出每个节点的运行事件，包括理解、召回、重排、工具调用和最终回答。前端可以实时展示过程，后端也可以把同一套事件写入 trace 系统，用于调试和监控。

### 工具安全边界

工具调用不只做 JSON schema 校验，还保留业务校验入口：

- 当前意图是否允许调用该工具；
- 参数类型合法后，业务对象是否属于当前用户或租户；
- 工具超时后是否允许重试；
- 返回数据是否可信；
- 异常是否能结构化返回给上层 workflow。

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

## 扩展方向

| 当前实现 | 可替换为 |
| --- | --- |
| 关键词召回 | Milvus / pgvector / Chroma + BM25 混合召回 |
| 轻量 rerank | bge-reranker / cross-encoder / LLM rerank |
| 自定义 workflow | LangGraph StateGraph + checkpoint |
| 内存 fallback | Redis Cluster / Postgres checkpoint |
| 简单工具 registry | MCP / Function Calling / 工具权限中心 |
| 本地事件流 | OpenTelemetry / Langfuse / Kafka 事件日志 |

## 与其他项目的关系

`Agentic-RAG-Platform` 聚焦企业知识库、RAG 服务化、流式交互和多工具调用。

[`Embodied-Agent-Runtime`](https://github.com/my420254/Embodied-Agent-Runtime) 聚焦具身任务运行时，包括 ROS 文本接入、任务中断、栈式恢复、反思重试和 benchmark 对齐。

两个项目分别覆盖大模型应用中的“知识服务”和“任务执行”两类核心场景。

## 许可

MIT License.
