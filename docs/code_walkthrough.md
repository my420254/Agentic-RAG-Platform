# 代码导读

这份文档按“请求如何流过系统”的顺序解释代码。它适合第一次阅读项目时使用，也适合快速回忆每个模块的职责。

## 一句话理解

`Agentic-RAG-Platform` 把一次知识问答拆成可观察的多阶段任务：

```text
HTTP Request
  -> TaskService 创建 task_id
  -> RateLimiter 检查请求频率
  -> AgentWorkflow 执行多节点流程
  -> Retriever 做混合检索和 RRF 融合
  -> ToolRegistry 按需调用工具
  -> MemoryService 保存会话
  -> SSE 把节点事件推给前端
```

## 目录结构

```text
backend/app/main.py
  FastAPI 入口，定义所有 HTTP API。

backend/app/agent/state.py
  AgentState 和 Evidence，保存一次任务执行过程中的状态。

backend/app/agent/workflow.py
  AgentWorkflow，串起 understand / retrieve / rerank / tool / answer。

backend/app/rag/chunker.py
  文档清洗与切片。

backend/app/rag/retriever.py
  轻量混合检索：BM25-style ranking + sparse hash-vector ranking + RRF。

backend/app/services/memory.py
  会话记忆，Redis 优先，内存 fallback。

backend/app/services/tasks.py
  任务状态、任务事件、取消标记，Redis 优先，内存 fallback。

backend/app/services/rate_limit.py
  固定窗口限流，Redis 优先，内存 fallback。

backend/app/services/events.py
  把 Python dict 转成 SSE 文本格式。

backend/app/tools/registry.py
  工具注册、input schema、意图白名单、结构化错误。

frontend/src/App.vue
  Vue3 + Element Plus 工作台，展示任务、证据、Trace、工具结果和记忆。
```

## `main.py`：API 层

`main.py` 是后端入口，负责三件事：

1. 定义请求体模型，例如 `ChatRequest`、`IngestRequest`、`TaskSubmitRequest`。
2. 暴露 API，例如 `/api/chat/stream`、`/api/tasks/{task_id}/cancel`。
3. 把 HTTP 请求转给 workflow、retriever、memory、task service 等内部模块。

关键 API：

| API | 作用 |
| --- | --- |
| `GET /api/health` | 健康检查 |
| `POST /api/ingest` | 写入一份文档，切片后进入检索器 |
| `POST /api/chat` | 同步执行一次 Agentic RAG |
| `POST /api/chat/stream` | SSE 流式执行一次 Agentic RAG |
| `POST /api/tasks` | 创建任务，返回 `task_id` |
| `GET /api/tasks/{task_id}` | 查询任务状态和事件 |
| `POST /api/tasks/{task_id}/cancel` | 请求取消任务 |
| `GET /api/tools` | 查看工具 schema |
| `POST /api/tools/{tool_name}/call` | 直接调用工具 |

阅读重点：

- `enforce_rate_limit()` 在进入核心逻辑前做限流。
- `/api/chat/stream` 会先创建任务，再在 SSE 中输出 `task_created` 和 workflow 节点事件。
- `/api/tasks/{task_id}/events` 展示“先提交任务，再订阅事件”的工程模式，后续接 Kafka/Redis Stream 时可以沿用这个 API。

## `AgentState`：任务运行状态

`AgentState` 是一次任务在 workflow 内部流转的状态对象。它不是数据库模型，而是运行时上下文。

主要字段：

| 字段 | 含义 |
| --- | --- |
| `session_id` | 会话 id，用于记忆和限流 |
| `task_id` | 任务 id，用于状态查询、取消和事件关联 |
| `message` | 用户原始问题 |
| `intent` | 理解阶段识别出来的意图 |
| `rewritten_query` | 改写后的检索 query |
| `evidence` | 检索证据列表 |
| `selected_tool` | 当前调用的工具名 |
| `tool_result` | 工具返回结果 |
| `answer` | 最终回答 |
| `cancelled` | 是否被取消 |
| `error` | 失败信息 |
| `trace` | 节点级 trace |

`add_trace()` 用于在每个节点结束后写入结构化 trace，方便排查问题。

## `AgentWorkflow`：多节点执行流

workflow 不是把 prompt 一次性丢给模型，而是拆成几个节点：

```text
understand -> retrieve -> rerank -> tool -> answer
```

每个节点做完后都会 `yield` 一个事件。这样 API 层可以把事件转成 SSE，前端就能实时看到执行进度。

节点职责：

| 节点 | 作用 |
| --- | --- |
| `_understand` | 清洗用户输入，识别 `qa` 或 `policy` 意图 |
| `_retrieve` | 调用 retriever 找候选证据 |
| `_rerank` | 对证据排序并保留 top 3 |
| `_maybe_call_tool` | 根据意图和关键词决定是否调用工具 |
| `_answer` | 生成最终回答并写入会话记忆 |

取消逻辑：

```text
每个节点完成后
  -> task_service.is_cancelled(task_id)
  -> True: 写入 cancelled 状态并停止 workflow
  -> False: 继续下一个节点
```

这个设计适合大模型应用，因为大模型和工具调用通常不能随便强杀；更稳的方式是在节点边界检查取消状态，并给工具调用设置 timeout。

失败逻辑：

```text
try:
  run workflow
except Exception:
  state.error = str(exc)
  task.status = failed
  yield error event
```

真实生产系统还可以把失败类型拆成 retrieval_error、tool_error、model_error、permission_error，然后分别进入 retry、fallback 或人工处理。

## `Retriever`：混合检索与 RRF

`retriever.py` 的目标是让仓库开箱可跑，同时展示真实 RAG 的检索分层。

当前实现：

```text
tokenize(query)
  -> BM25-style lexical ranking
  -> sparse hash-vector cosine ranking
  -> RRF fusion
  -> Evidence[]
```

为什么不用真正 embedding：

- 公开仓库不需要下载大模型也能跑；
- CI 或普通电脑上可以快速测试；
- 上层 workflow 只依赖 `Evidence` API，后续替换向量库不影响接口。

几个核心函数：

| 函数 | 作用 |
| --- | --- |
| `tokenize()` | 英文按词切，中文按单字和 bigram 切 |
| `sparse_hash_vector()` | 把 token 映射成固定维度 sparse vector |
| `cosine_sparse()` | 计算轻量向量相似度 |
| `_bm25_ranking()` | 做 BM25-style 关键词排名 |
| `_vector_ranking()` | 做 sparse vector 相似度排名 |
| `_rrf_fuse()` | 用 RRF 合并多路排名 |

RRF 公式直觉：

```text
final_score += 1 / (k + rank)
```

它不直接相加 BM25 分数和向量分数，而是按排名融合。这样可以避免不同检索器分数尺度不一致的问题。

## `MemoryService`：会话记忆

`memory.py` 使用 Redis 优先、内存 fallback 的模式。

如果设置了：

```bash
export REDIS_URL=redis://localhost:6379/0
```

消息会写到 Redis list：

```text
agent:session:{session_id}:messages
```

如果没有 Redis，代码自动写到本地内存。这样本地 demo 不会因为缺 Redis 跑不起来。

这个模块只保存最近消息，不保存长期知识。长期语义知识应该放向量库或关系库，任务状态应该放 `TaskService`。

## `TaskService`：任务状态与取消

`tasks.py` 负责管理任务生命周期。

任务状态：

```text
pending
running
completed
cancel_requested
cancelled
failed
```

它同样采用 Redis 优先、内存 fallback。

Redis key 设计：

```text
agent:task:{task_id}:state
agent:task:{task_id}:events
agent:task:{task_id}:cancel
```

为什么要单独有 `TaskService`：

- 前端需要查询任务状态；
- SSE 断开后仍然能看到已发生事件；
- 取消命令需要落到后端状态；
- 后续接 Kafka 或 Redis Stream 时，task_id 是事件关联的主键。

## `RateLimiter`：限流

`rate_limit.py` 是固定窗口限流。

当前逻辑：

```text
subject = session:{session_id}
window = 当前分钟
count += 1
count <= limit -> allowed
count > limit -> HTTP 429
```

Redis 版本用 `INCR + EXPIRE`；没有 Redis 时用内存 deque 兜底。

这不是最精确的限流算法，但足够展示工程边界。生产系统可以替换成滑动窗口、漏桶、令牌桶，或者放到 API Gateway。

## `ToolRegistry`：工具调用边界

`registry.py` 把工具定义和工具执行分开。

一个工具包含：

```text
name
description
allowed_intents
input_schema
handler
```

当前示例工具是 `policy_lookup`。它用于展示：

- 工具入参必须结构化；
- 工具是否允许调用要看 intent；
- 返回值要有 `ok`、`error_code` 等结构化字段；
- 后续可以映射到 MCP 的 tools/list 和 tools/call。

这个模块不是完整 MCP server，但已经把 MCP/function calling 需要的核心边界抽出来了。

## `events.py`：SSE 格式化

SSE 的格式是纯文本：

```text
id: 1
event: retrieve
data: {"evidence_count": 3}

```

`sse_event()` 负责把 dict 转成这种格式。`stream_events()` 给事件编号并持续 yield 字符串。

## `frontend/src/App.vue`：前端工作台

前端使用 Vue3 + Element Plus，而不是自己从零写所有 UI 控件。

页面分区：

| 区域 | 作用 |
| --- | --- |
| 左侧 Sidebar | session、任务输入、运行/取消/读取记忆、任务状态 |
| Answer | 最终回答和 citation |
| Evidence | 检索片段、分数、来源、融合方式 |
| Trace | understand / retrieve / rerank / tool / answer 节点事件 |
| Tool | 工具调用返回 |
| Memory | 当前 session 的最近消息 |

前端通过 `fetch()` 读取 SSE，而不是 `EventSource`，原因是当前接口用 POST 提交 JSON。`EventSource` 原生只适合 GET，如果要用它，可以改成 `POST /api/tasks` 创建任务，再 `GET /api/tasks/{task_id}/events` 订阅事件。

## 推荐阅读顺序

第一次看代码建议按这个顺序：

1. `README.md`：先看项目要解决什么问题。
2. `backend/app/main.py`：看 API 怎么进系统。
3. `backend/app/agent/state.py`：看状态字段。
4. `backend/app/agent/workflow.py`：看任务怎么流转。
5. `backend/app/rag/retriever.py`：看 RAG 检索怎么做。
6. `backend/app/services/tasks.py`：看任务状态和取消。
7. `backend/app/tools/registry.py`：看工具 schema。
8. `frontend/src/App.vue`：看前端如何消费 SSE。
9. `tests/`：看哪些行为被测试覆盖。

## 当前边界

当前项目已经可以讲：

- FastAPI 接入；
- SSE 流式输出；
- Vue3 + Element Plus 工作台；
- Redis 优先的会话记忆、任务状态、限流；
- 轻量混合检索和 RRF；
- 工具 schema 和意图白名单；
- 任务取消和事件记录；
- pytest/API 测试。

当前项目还不能讲成：

- 已完成 10 万 QPS 压测；
- 已部署 Kafka 生产队列；
- 已接入 Milvus/pgvector 真实向量库；
- 已实现完整 MCP server；
- 已上线多租户权限和审计系统。

