# 技术问答与设计取舍

这份文档用问答形式说明 Agentic RAG 平台里的核心设计，便于读者快速理解项目边界和工程取舍。

## 1. 这个项目和普通 RAG 有什么区别？

普通 RAG 往往是一次检索、一次生成。这个项目按 Agentic RAG 思路拆成多节点 workflow：先理解任务，再检索、重排、按需调用工具，最后基于证据生成答案。这样可以处理多轮任务、证据冲突、工具补充信息和执行过程观测。

## 2. chunk 怎么切？

优先按语义结构切分，固定长度兜底。规则页按标题和段落切，短 QA 按问答对切，chunk 之间保留 overlap，避免条件和结论被切断。chunk 太小会丢上下文，太大会引入噪声并浪费 token。

## 3. 向量检索不准怎么排查？

优先从数据和召回链路排查：

- 文档清洗是否删掉了关键信息；
- chunk 是否切断实体和条件；
- embedding 是否适合中文和业务域；
- metadata filter 是否过严；
- top_k 是否合理；
- 是否缺少 BM25、SQL 或图谱召回；
- 是否需要 reranker；
- prompt 是否明确要求引用证据并在证据不足时拒答。

## 4. BM25 和向量结果怎么合并？

当前实现用 RRF（Reciprocal Rank Fusion）合并两路排名，而不是直接相加原始分数。原因是 BM25 分数、向量 cosine 分数和 reranker 分数分布不同，直接加权很容易受尺度影响。

流程：

```text
query
  -> BM25-style ranking
  -> sparse vector ranking
  -> RRF: score += 1 / (k + rank)
  -> top evidence
```

BM25 更适合错误码、接口名、专有名词等精确匹配；向量召回更适合同义表达和口语化问题。RRF 用排名融合，能减少不同召回器分数不可比的问题。

## 5. Redis 在这里承担什么职责？

Redis 主要承担短期会话态、最近消息、限流计数、checkpoint 指针和异步工具回调。长期语义知识更适合向量库或关系库。这样可以避免把任务状态、用户偏好、知识文档混在一个存储里。

## 6. SSE 怎么接入？

后端使用 `StreamingResponse` 输出 `text/event-stream`。每个 Agent 节点产生一个事件，例如 `understand`、`retrieve`、`rerank`、`tool`、`answer`。前端用 `fetch` 和 `ReadableStream` 解析事件并实时渲染。

## 7. 用户取消任务如何设计？

取消命令需要写入任务控制通道，而不是只改前端 UI。当前项目有 `TaskService`，任务状态包括 `pending`、`running`、`completed`、`cancel_requested`、`cancelled`、`failed`。

当前流程：

```text
POST /api/tasks
  -> 返回 task_id
GET /api/tasks/{task_id}/events
  -> SSE 推送节点事件
POST /api/tasks/{task_id}/cancel
  -> 写入 cancel_requested
workflow 节点边界检查取消状态
  -> cancelled
```

如果当前工具是阻塞调用，则需要 timeout、异步任务取消或子进程隔离。取消事件要写入 trace，避免恢复时拿到错误上下文。

## 8. 工具 schema 怎么设计？

工具 schema 不只描述参数类型，还应该包含运行约束：

- `name` 和 `description`；
- `allowed_intents`；
- 参数 schema；
- 返回 schema；
- timeout；
- retry policy；
- permission check；
- structured error code。

参数格式正确不代表业务合法，例如订单号存在但不属于当前用户，仍然必须拒绝。

当前项目通过 `/api/tools` 暴露工具描述，通过 `/api/tools/{tool_name}/call` 调用工具。它不是完整 MCP server，但已经保留了 MCP/function calling 需要的 `name`、`description`、`input_schema` 和结构化返回边界。

## 9. LangChain 和 LangGraph 如何取舍？

线性单轮流程可以用 LangChain chain；如果系统存在状态、多分支、循环、人工确认、中断恢复和失败重试，就更适合 LangGraph。当前项目保留轻量 workflow，是为了把状态边界先做清楚，后续可以迁移到 LangGraph StateGraph。

## 10. 如何限制幻觉？

项目从四层控制幻觉：

- 检索层：清洗、切片、混合召回、rerank；
- 生成层：要求基于证据回答，证据不足拒答；
- 工具层：实时事实以工具或数据库返回为准；
- 审计层：citation、trace、答案校验和人工接管。

## 11. RAG 如何做评测？

先从检索评测做起，因为检索没命中时，生成再强也没有依据。当前项目实现了：

```bash
python scripts/run_rag_eval.py --top-k 3
```

核心指标：

- `Hit@K`：期望文档是否进入前 K 个结果；
- `MRR`：第一个正确文档排得越靠前越好；
- `failed_cases`：失败样本必须保留下来，作为后续修复的回归集。

生产中还可以继续补：

- answer correctness；
- faithfulness；
- citation precision；
- 人工标注 golden set；
- 线上 badcase 回流。

## 12. 为什么要做证据质量门控？

因为 top_k 有结果不等于证据可靠。错误证据、弱相关证据、过期证据都会诱导模型编答案。

当前项目有独立 `quality` 节点：

```text
understand -> retrieve -> rerank -> quality -> tool -> answer
```

如果证据为空或分数低于阈值，answer 节点会拒答。这样可以回答面试里的“如何治理幻觉”问题：不是只改 prompt，而是在检索和生成之间加质量闸门。

## 13. 如何接 vLLM / Qwen？

默认关闭模型调用，保证开箱演示稳定。需要接本地 OpenAI-compatible 服务时：

```bash
export RAG_USE_LLM=true
export LLM_API_BASE=http://192.168.27.250:18003/v1
export LLM_MODEL=Qwen3.6-27B
export LLM_API_KEY=qwen-local-key
export LLM_ENABLE_THINKING=false
```

模型只负责最终语言生成；检索、rerank、工具权限、证据门控、任务取消和 Trace 都由后端控制。

远程打开前端时，不要把 API 地址写死成浏览器本机的 `localhost`。当前前端会自动根据页面主机推断后端地址：

```text
http://<应用服务器IP>:5173 -> http://<应用服务器IP>:18080
```

如果前后端分开部署，则通过 `VITE_API_BASE` 指定。

## 14. 一万并发或十万峰值怎么设计？

不能让 FastAPI 同步扛所有模型推理。合理拆法是：

```text
API Gateway
  -> FastAPI Ingress
  -> Redis 限流
  -> Kafka / Redis Stream 削峰
  -> Agent Worker
  -> Retriever / Reranker
  -> vLLM Serving Pool
  -> SSE Gateway
```

关键回答点：

- API 层只做接入、鉴权、限流和任务创建；
- 重任务进入队列，由 worker 消费；
- Redis 保存短期状态、取消标记、checkpoint 和热点缓存；
- vLLM 独立扩容，通过 batching 提升吞吐；
- reranker 要做批处理和缓存；
- 事件流和 Trace 独立，不阻塞主链路。

## 15. 生产化还需要补什么？

当前仓库是可扩展骨架，生产化可继续补充：

- Milvus / pgvector；
- bge-reranker；
- LangGraph checkpoint；
- Redis Cluster；
- OpenTelemetry / Langfuse；
- 鉴权和租户隔离；
- 评测集和自动回归；
- 灰度发布、限流和熔断。
