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
| RAG | 文档切片、BM25-style 召回、轻量向量相似度、RRF 融合、证据引用 |
| 记忆与状态 | Redis 优先，内存 fallback；用于 session state、任务状态、取消标记、限流和 checkpoint 指针 |
| 工具调用 | Tool registry、input schema、意图白名单、业务校验、结构化错误 |
| 前端 | Vue3, TypeScript, Vite |
| 测试 | pytest |

## 当前实现范围

| 能力 | 当前状态 |
| --- | --- |
| FastAPI 接入 | 已实现 health、ingest、chat、chat stream、memory API |
| SSE 流式事件 | 已实现 workflow 节点级事件输出 |
| RAG 检索 | 已实现文档切片、BM25-style 召回、轻量向量相似度、RRF 融合、检索诊断和 citation 返回 |
| 文档管理 | 已实现文档写入、文档列表、chunk 统计和用户文档清理 |
| 证据质量门控 | 已实现 evidence quality gate，证据不足时拒答，避免无证据生成 |
| 检索评测 | 已实现离线 retrieval eval，输出 Hit@K、MRR、失败 case |
| LLM 生成 | 默认模板 fallback，设置环境变量后可接 vLLM/Qwen OpenAI-compatible 接口 |
| Redis 记忆 | 已实现 Redis 优先、内存 fallback 的 session memory |
| 任务管理 | 已实现 task_id、状态查询、取消请求和节点事件记录 |
| 限流 | 已实现 Redis 优先、内存 fallback 的固定窗口限流 |
| 工具调用 | 已实现 ToolRegistry、input schema、意图白名单、结构化错误和演示工单工具 |
| Trace | 已实现任务事件记录和 trace summary 查询 |
| Vue3 前端 | 已实现 session、任务输入、文档管理、检索证据、诊断/评测、事件流、工具结果和 memory 读取 |
| Kafka / 队列 | 当前为架构预留，适合接入 Kafka 或 Redis Stream |
| 向量数据库 | 当前为接口预留，适合替换为 Milvus、pgvector 或 Chroma |
| 线上压测 | 当前未包含压测结果，后续可补 Locust / k6 |

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

```mermaid
flowchart TB
    U[Vue3 Client] --> API[FastAPI SSE API]
    API --> LIM[Rate Limit]
    API --> TS[Task Service]
    LIM --> WF[Agent Workflow]
    TS --> WF
    WF --> R[Retriever]
    WF --> RR[Reranker]
    WF --> T[Tool Registry]
    WF --> M[Memory Service]
    M --> Redis[(Redis)]
    R --> KB[(Document Store / Vector DB)]
    T --> EXT[Business APIs]
    WF --> SSE[SSE Event Stream]
    SSE --> U
```

## 高并发设计预留

当前仓库是可运行的平台骨架，没有把 Kafka、Redis Cluster、向量数据库集群全部强绑定进去；但接口按真实大模型应用系统的扩展方式设计，后续可以平滑演进为高并发服务。

| 压力点 | 典型问题 | 设计处理 |
| --- | --- | --- |
| 1 万级并发连接 | SSE / WebSocket 长连接占用 worker 和连接数 | API 层只维护轻量事件流，重任务下沉到 workflow / queue |
| 10 万级请求峰值 | 瞬时请求打爆模型服务和检索服务 | Kafka / Redis Stream 做削峰，按租户和优先级消费 |
| 模型推理慢 | LLM 是整体瓶颈，不能无限扩 FastAPI | vLLM / Triton / OpenAI-compatible endpoint 独立伸缩 |
| 检索压力大 | 向量召回和 rerank 会放大延迟 | BM25 + vector hybrid recall，reranker 批处理，热门 query 缓存 |
| 会话状态膨胀 | 多轮历史直接塞 prompt 成本高 | Redis 保存 session state、短期记忆、checkpoint 指针 |
| 任务取消 | 用户关闭页面后后端仍在跑 | cancel token / task id 贯穿 workflow，节点边界检查取消状态 |
| 重试与幂等 | 工具调用失败或重复提交可能产生副作用 | request id、tool call id、幂等 key 和结构化错误 |

高并发版本可以采用如下链路：

```mermaid
flowchart LR
    A[Nginx / API Gateway] --> B[FastAPI Ingress]
    B --> C[Redis Rate Limit]
    B --> D[Kafka Task Topic]
    D --> E[Agent Workers]
    E --> F[Retriever / Reranker]
    E --> G[LLM Serving Pool]
    E --> H[Tool Workers]
    E --> I[Kafka Event Topic]
    I --> J[SSE Gateway]
    J --> K[Vue Client]
```

这里 Kafka 负责任务削峰和事件解耦，Redis 负责低延迟状态、限流和 checkpoint 指针，FastAPI 只做接入与流式返回，模型服务独立扩容。这样可以把“连接并发”和“模型计算并发”拆开，不会让 Web API 直接承受所有重计算。

## 核心设计

### Agentic RAG

项目把一次问答拆成多个可观测节点，而不是一次检索后直接生成：

- `understand`：识别用户意图，提取查询和约束；
- `retrieve`：从知识库召回候选片段；
- `rerank`：融合 BM25-style 排名和轻量向量相似度排名，使用 RRF 保留证据；
- `tool`：需要实时信息或业务动作时进入工具 registry；
- `answer`：基于证据生成最终回答，同时返回引用片段。

这种拆法让系统可以定位问题来源，也方便后续接入 LangGraph checkpoint、评测集和线上 trace。

### 混合检索与 RRF

当前实现保留了一个不需要下载 embedding 模型的轻量混合检索器：

```text
query
  -> tokenize
  -> BM25-style lexical ranking
  -> sparse hash-vector cosine ranking
  -> RRF rank fusion
  -> top evidence with citation
```

这里的轻量向量相似度不是生产向量库，只用于让本仓库开箱可跑。生产版本可以把 `_vector_ranking` 替换为 `bge-m3`、`text-embedding-v3`、Milvus、pgvector 或 Chroma，RRF 融合接口保持不变。

### 分层记忆

项目没有把所有对话历史都塞进向量库，而是把记忆分成三类：

- 当前会话消息：适合 Redis list / hash；
- 长期偏好和语义知识：适合向量库或关系库；
- checkpoint 指针和任务状态：适合 Redis key-value。

这样可以避免长对话检索变慢、冲突记忆难删除、过期事实污染回答等问题。

Redis 在这个项目中的定位不是简单缓存，而是大模型应用运行时状态层：

| Redis 数据 | 典型结构 | 用途 |
| --- | --- | --- |
| 会话消息 | list / stream | 保留近期上下文 |
| 用户偏好 | hash | 保存轻量 profile |
| 限流计数 | string + TTL | tenant / user / api key 粒度限流 |
| checkpoint 指针 | string / hash | 记录长任务恢复位置 |
| cancel flag | string + TTL | 前端取消后让 workflow 节点及时停止 |
| 热门检索缓存 | string / hash | 降低重复 query 的检索和 rerank 成本 |

### SSE 流式事件

后端通过 SSE 输出每个节点的运行事件，包括理解、召回、重排、工具调用和最终回答。前端可以实时展示过程，后端也可以把同一套事件写入 trace 系统，用于调试和监控。

SSE 适合这个项目的原因是服务端持续推送、客户端轻量接收，符合 RAG 问答和 Agent trace 的单向流式输出模式。如果需要双向实时协作、多人编辑或持续控制信号，再替换为 WebSocket 更合适。

### 任务状态与取消

项目新增 `TaskService` 管理任务生命周期：

```text
pending -> running -> completed
pending/running -> cancel_requested -> cancelled
running -> failed
```

前端或外部系统可以先提交任务拿到 `task_id`，再通过 SSE 读取节点事件，必要时调用取消接口。workflow 会在节点边界检查取消标记；如果底层工具是阻塞调用，生产版本需要配合 timeout、异步 worker 或子进程隔离。

前端 Vue3 的核心职责不是做一个普通聊天框，而是展示 Agent 的中间过程：

| 前端区域 | 展示内容 |
| --- | --- |
| Chat Panel | 用户问题、最终回答、流式 token |
| Evidence Panel | 检索片段、来源、相关性分数 |
| Trace Timeline | understand / retrieve / rerank / tool / answer 节点事件 |
| Tool Result | 工具参数、返回值、错误信息 |
| Session State | 当前会话 id、记忆摘要、取消状态 |

### 工具安全边界

工具调用不只做 JSON schema 校验，还保留业务校验入口：

- 当前意图是否允许调用该工具；
- 参数类型合法后，业务对象是否属于当前用户或租户；
- 工具超时后是否允许重试；
- 返回数据是否可信；
- 异常是否能结构化返回给上层 workflow。

## 运行方式

### 端口规划

| 端口 | 服务 | 说明 |
| --- | --- | --- |
| `5173` | Vue 开发工作台 | 前端页面，浏览器入口 |
| `18080` | FastAPI 业务后端 | RAG、任务状态、工具调用、Trace、模型适配 |
| `18003` | Qwen vLLM | Qwen3.6-27B，默认模型入口 |
| `18004` | Qwen vLLM | Qwen3.6-27B，备用或并行测试入口 |

前端只访问 FastAPI；FastAPI 再访问 vLLM。这样模型端口、API key、工具权限和检索逻辑都不会暴露给浏览器。

### 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 18080
```

也可以使用仓库根目录的 Compose 一次启动 Redis、API 和 Vue 工作台：

```bash
docker compose up
```

打开：

```text
http://localhost:5173
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

### 快速测试

```bash
curl -N -X POST http://localhost:18080/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","message":"如何限制 RAG 幻觉？"}'
```

加载演示知识库：

```bash
python scripts/load_demo_knowledge.py --api-base http://localhost:18080
```

运行端到端冒烟演示：

```bash
scripts/demo_smoke.sh
```

运行离线检索评测：

```bash
python scripts/run_rag_eval.py --top-k 3
```

当前演示评测集覆盖 RAG 幻觉治理、Agent Harness、故障工单、向量库慢查询等场景。一次参考输出：

```text
total=5, top_k=3, hit_rate=1.0, mrr=1.0
```

这个指标只是演示评测，不等同于真实线上效果。它的价值是证明项目具备“固定评测集 + 指标 + 失败 case 回归”的工程闭环。

### 文档、检索和评测 API

```bash
curl http://localhost:18080/api/documents

curl -X POST http://localhost:18080/api/retrieve \
  -H 'Content-Type: application/json' \
  -d '{"query":"INC-1001 账单接口超时怎么处理","top_k":3}'

curl -X POST http://localhost:18080/api/eval/retrieval \
  -H 'Content-Type: application/json' \
  -d '{"top_k":3}'

curl http://localhost:18080/api/tasks/<task_id>/trace
```

### 接入真实 vLLM / Qwen

默认不调用大模型，保证测试和演示稳定。如果要接你的本地 Qwen/vLLM 服务：

```bash
export RAG_USE_LLM=true
export LLM_API_BASE=http://192.168.27.250:18003/v1
export LLM_MODEL=Qwen3.6-27B
export LLM_API_KEY=qwen-local-key
export LLM_ENABLE_THINKING=false
export LLM_MAX_TOKENS=512
cd backend && uvicorn app.main:app --reload --port 18080
```

仓库根目录支持 `.env` 本地配置，`./scripts/run_backend_with_qwen.sh` 会自动读取。DeepSeek 备用模型的 API Key 填这里：

```bash
LLM_FALLBACK_API_KEY=sk-你的DeepSeekKey
```

`.env` 已被 `.gitignore` 忽略，不会上传。公开仓库只提交 `.env.example`。

本地 Qwen 不可用时，后端会按顺序尝试：

```text
primary:  http://192.168.27.250:18003/v1  -> Qwen3.6-27B
fallback: https://api.deepseek.com         -> deepseek-v4-flash
```

验证 DeepSeek key：

```bash
./scripts/test_deepseek_api.sh
```

强制模拟本地 Qwen 不可用并验证 fallback：

```bash
LLM_API_BASE=http://127.0.0.1:9/v1 LLM_TIMEOUT_SECONDS=1 ./scripts/run_backend_with_qwen.sh
curl -N -X POST http://localhost:18080/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"fallback-demo","message":"如何限制 RAG 幻觉？"}'
```

也可以直接使用脚本：

```bash
./scripts/test_qwen_vllm.sh
./scripts/run_backend_with_qwen.sh
```

启动后在另一个终端加载演示知识：

```bash
python scripts/load_demo_knowledge.py --api-base http://localhost:18080
```

后端也会默认自动加载 `data/demo_knowledge`。如果你清理过临时文档，或想手动恢复演示知识，可以调用：

```bash
curl -X POST http://localhost:18080/api/demo/load
```

前端 API 地址默认按当前页面主机推断。例如从 `http://<应用服务器IP>:5173` 打开页面时，前端会自动请求 `http://<应用服务器IP>:18080`。如果前后端分开部署，可以设置：

```bash
export VITE_API_BASE=http://<应用服务器IP>:18080
```

当前实测可用的本地模型服务：

| 地址 | 模型 | 用途 |
| --- | --- | --- |
| `http://192.168.27.250:18003/v1` | `Qwen3.6-27B` | 默认演示入口 |
| `http://192.168.27.250:18004/v1` | `Qwen3.6-27B` | 备用入口 / 并行压测入口 |
| `https://api.deepseek.com` | `deepseek-v4-flash` | 本地模型不可用时的云端 fallback |

后端提供模型状态检查：

```bash
curl http://localhost:18080/api/llm/status
```

后端也提供整体运行态检查：

```bash
curl http://localhost:18080/api/runtime/status
```

LLM 只负责基于证据生成最终回答；检索、质量门控、工具权限、任务状态和 Trace 都由后端代码控制，不交给模型自由发挥。

### 任务 API

```bash
curl -X POST http://localhost:18080/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","message":"如何限制 RAG 幻觉？"}'

curl http://localhost:18080/api/tasks/<task_id>

curl -N http://localhost:18080/api/tasks/<task_id>/events

curl -X POST http://localhost:18080/api/tasks/<task_id>/cancel
```

### 工具 API

```bash
curl http://localhost:18080/api/tools

curl -X POST http://localhost:18080/api/tools/policy_lookup/call \
  -H 'Content-Type: application/json' \
  -d '{"intent":"qa","payload":{"topic":"RAG 幻觉控制"}}'
```

### 单元测试

```bash
python -m pytest tests
```

## 延伸文档

| 文档 | 内容 |
| --- | --- |
| [`docs/architecture.md`](docs/architecture.md) | 后端模块、请求链路、任务状态和生产化扩展 |
| [`docs/code_walkthrough.md`](docs/code_walkthrough.md) | 按代码路径解释每个模块怎么读 |
| [`docs/evaluation_and_production.md`](docs/evaluation_and_production.md) | 检索评测、证据门控、压测和生产化演进 |
| [`docs/project_story.md`](docs/project_story.md) | 项目背景、核心能力、技术价值和后续演进 |
| [`docs/production_topology.md`](docs/production_topology.md) | 面向大模型应用落地的分层部署、并发扩容和可观测方案 |
| [`docs/model_failover.md`](docs/model_failover.md) | 本地 Qwen/vLLM 与 DeepSeek 备用模型的降级策略 |
| [`docs/qwen_vllm_integration.md`](docs/qwen_vllm_integration.md) | 接入本地 Qwen3.6-27B / vLLM 的端口、配置和验证方式 |
| [`docs/package_choices.md`](docs/package_choices.md) | FastAPI、redis-py、Element Plus 等依赖的选型边界 |
| [`docs/technical_qna.md`](docs/technical_qna.md) | RAG、RRF、Redis、SSE、工具 schema 等技术问答 |
| [`docs/development_journal.md`](docs/development_journal.md) | 开发过程中的设计演进和取舍 |

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
