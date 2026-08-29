# 生产化部署拓扑与落地说明

这份文档把项目按真实公司里的大模型应用系统来解释：前端、业务后端、检索服务、状态层、任务队列、模型服务和可观测系统各自负责什么，为什么不能全部混在一个脚本里。

## 1. 当前演示拓扑

当前项目采用“应用服务”和“模型服务”分离的方式：

```text
浏览器 / Vue 工作台
  -> Agentic RAG FastAPI 后端
     -> 检索器 / 证据质量门控 / 工具 Registry / Redis 状态
     -> Qwen3.6-27B vLLM OpenAI-compatible API
```

当前端口规划：

| 服务 | 地址 | 职责 |
| --- | --- | --- |
| Vue 工作台 | `http://<应用服务器IP>:5173` | 展示任务输入、证据、工具结果、Trace |
| FastAPI 后端 | `http://<应用服务器IP>:18080` | 业务控制面，统一接收前端请求 |
| Qwen vLLM | `http://192.168.27.250:18003/v1` | Qwen3.6-27B 默认生成入口 |
| Qwen vLLM | `http://192.168.27.250:18004/v1` | Qwen3.6-27B 备用入口 |
| DeepSeek API | `https://api.deepseek.com` | 本地模型不可用时的云端 fallback |

模型服务地址通过 `LLM_API_BASE` 配置，不写死在业务逻辑中。

## 2. 为什么要分层

前端不能直接调用模型服务，原因包括：

- 浏览器不应该暴露模型 API key；
- 模型只会生成文本，不负责业务权限、证据质量和工具安全；
- 后续要做限流、缓存、降级、审计和多租户隔离，必须有业务后端；
- 模型服务需要独立扩容，不能和 Web 接入层耦合；
- 线上排障需要知道失败发生在检索、工具、模型还是前端。

FastAPI 在这里是控制面，vLLM 是算力面。控制面决定任务怎么走，算力面只负责推理。

## 3. 当前已实现的落地能力

| 能力 | 当前实现 | 面向生产的价值 |
| --- | --- | --- |
| 请求接入 | `POST /api/chat/stream` + SSE | 长任务可实时返回节点事件 |
| 请求追踪 | `x-request-id` 响应头 | 日志、Trace、排障可以按请求串联 |
| 模型状态 | `GET /api/llm/status` | 后端可探测 Qwen/vLLM 是否可达 |
| 运行态检查 | `GET /api/runtime/status` | 一次性查看环境、知识库、模型状态 |
| 检索诊断 | `POST /api/retrieve` | 暴露 BM25、vector、RRF 排名 |
| 检索评测 | `POST /api/eval/retrieval` | 输出 Hit@K、MRR、失败 case |
| 证据门控 | `quality` workflow 节点 | 证据不足时拒答，降低幻觉 |
| 工具边界 | `ToolRegistry` + schema 校验 | 模型不能直接执行任意函数 |
| 状态层 | Redis 优先，内存 fallback | 会话、任务、取消、限流可持久扩展 |
| 大模型接入 | OpenAI-compatible adapter | 可切换 Qwen3.6、Qwen3.5 或其他模型 |
| 模型降级 | primary/fallback endpoint | 本地 vLLM 不可用时自动切 DeepSeek |

## 4. 面向高并发的标准演进

当前仓库是单机可运行版本。大公司落地时建议演进为：

```text
Client / Vue
  -> Nginx / API Gateway
  -> FastAPI Ingress
  -> Redis Rate Limit
  -> Kafka / Redis Stream
  -> Agent Worker Pool
     -> Retriever / Reranker
     -> Tool Worker
     -> vLLM Serving Pool
  -> Event Store / Trace
  -> SSE Gateway
```

关键原则：

- Web 接入层只做鉴权、限流、创建任务和返回事件；
- 长耗时任务进入队列，由 worker 消费；
- Redis 保存低延迟状态、取消标记、幂等键和热点缓存；
- Kafka 或 Redis Stream 承担削峰、重试和事件解耦；
- vLLM 独立部署，依靠 batching 提升 GPU 吞吐；
- Trace、日志、评测结果进入独立存储，支持线上回放。

## 5. 一万或十万级请求如何回答

如果面试官问“一万条同时访问怎么办”，不能只说加机器。合理回答是：

1. API Gateway 做租户级限流和鉴权。
2. FastAPI 只创建任务，不同步等待模型完成。
3. 请求进入 Kafka/Redis Stream，按优先级和租户消费。
4. Agent Worker 从队列取任务，执行检索、工具和模型调用。
5. vLLM 模型池独立扩容，利用 continuous batching 承接推理负载。
6. 热门 query、检索结果、rerank 结果用 Redis 缓存。
7. 前端通过 SSE 或 WebSocket 订阅任务事件。
8. 通过 trace 监控 p50/p95 延迟、token 用量、失败率、拒答率。

这样讲的重点是“接入并发”和“模型计算并发”分离。

## 6. 失败处理策略

真实落地系统必须承认失败会发生。本项目对应的处理方式：

| 失败类型 | 当前处理 | 可扩展方向 |
| --- | --- | --- |
| 检索为空 | 证据门控拒答 | 触发补充文档、Query Rewrite、扩大召回 |
| 模型超时 | 模板 fallback 并记录 trace | 降级到小模型或备用 vLLM 实例 |
| 工具参数错误 | ToolRegistry 返回结构化错误 | 加入参数修复节点或人审 |
| 用户取消 | task cancel flag，节点边界停止 | worker 协作取消和队列撤销 |
| 高峰压测 | rate limit 返回 429 | 队列削峰、租户配额、熔断 |
| 结果不可信 | citation + quality 节点 | LLM-as-judge 或规则校验 |

## 7. 当前验证入口

启动真实 Qwen 后端：

```bash
./scripts/run_backend_with_qwen.sh
```

验证 vLLM：

```bash
./scripts/test_qwen_vllm.sh
```

查看运行态：

```bash
curl http://localhost:18080/api/runtime/status
```

跑端到端演示：

```bash
./scripts/demo_smoke.sh
```

跑检索评测：

```bash
python scripts/run_rag_eval.py --top-k 3
```

## 8. 项目可讲价值

这个项目不是“聊天机器人”，而是一个能接本地大模型的 RAG 应用控制面。它体现的能力是：

- 能把 RAG 从黑盒回答拆成可观测链路；
- 能把模型推理和业务控制解耦；
- 能用固定评测集管理检索质量；
- 能通过 Redis、SSE、Trace 支撑任务状态和用户体验；
- 能解释高并发下为什么需要队列、缓存、限流和模型池；
- 能真实接入本地 Qwen3.6-27B/vLLM，而不是只写接口假数据。
