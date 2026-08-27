# 架构设计说明

## 目标

本项目目标是把 Agentic RAG 的生产链路压缩成一个可读、可运行、可扩展的样板：

- 用户可以上传或写入知识；
- 后端可以做检索、重排、工具调用和答案生成；
- 前端可以看到每个节点的流式事件；
- Redis 可以接管短期记忆、限流和 checkpoint 指针；
- 后续可以平滑替换成真实 LangGraph、Milvus/pgvector 和线上 LLM。

## 模块划分

```text
backend/app/main.py
  FastAPI 入口，暴露 health / ingest / chat / chat_stream / memory。

backend/app/agent/
  AgentState 定义运行状态；AgentWorkflow 定义 understand -> retrieve -> rerank -> tool -> answer。

backend/app/rag/
  chunker 负责文档切片；retriever 负责轻量召回和 Evidence API。

backend/app/services/
  memory 负责 Redis 优先、内存 fallback 的会话记忆；events 负责 SSE 格式化。

backend/app/tools/
  registry 负责工具注册、意图白名单和业务校验。

frontend/
  Vue3 工作台，展示 session、SSE 事件和记忆。
```

## 请求链路

1. 前端发起 `POST /api/chat/stream`。
2. FastAPI 构造 `AgentState`。
3. workflow 执行 `understand` 节点，输出意图和改写 query。
4. `retrieve` 节点从知识库召回候选证据。
5. `rerank` 节点保留 top evidence。
6. `tool` 节点根据意图和关键词选择工具。
7. `answer` 节点生成带 citation 的回答。
8. 每个节点通过 SSE 推给前端。
9. MemoryService 把用户和 assistant 消息写入 Redis 或内存 fallback。

## 为什么这样拆

### RAG 不能只靠一次向量检索

真实业务里，答非所问通常不是模型本身的问题，而是检索链路的问题。必须拆出清洗、切片、召回、重排、生成和校验这些环节，才能定位问题。

### 记忆必须分层

短期会话态、长期偏好、工作状态和反思记忆不是同一种数据。全部塞进向量库会导致效率差、冲突多、难删除。Redis 更适合短期会话和 checkpoint 指针。

### SSE 是工程必需品

Agent 一次调用可能经过多个工具和多个检索步骤，如果前端一直等最终结果，用户体验和可观测性都很差。SSE 能把每个节点状态直接展示出来。

## 生产版扩展

| 当前骨架 | 生产替换 |
| --- | --- |
| 关键词召回 | Milvus / pgvector / Chroma + BM25 混合召回 |
| 轻量 rerank | bge-reranker / cross-encoder / LLM rerank |
| 自定义 workflow | LangGraph StateGraph + checkpoint |
| 内存 fallback | Redis Cluster / Postgres checkpoint |
| 简单工具 registry | MCP / Function Calling / 工具权限中心 |
| 本地事件流 | Kafka / OpenTelemetry / Langfuse |

## 和 OurAgent-he1 的关系

`OurAgent-he1` 解决的是具身任务 runtime：ROS 文本命令、任务中断、栈式恢复、反思重试。

`Agentic-RAG-Platform` 解决的是企业知识库服务化：RAG、Redis、SSE、多轮会话和工具调用。

两个项目合起来，可以覆盖智能体研发面试里的主要系统问题。
