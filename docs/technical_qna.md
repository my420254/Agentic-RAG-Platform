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

## 4. Redis 在这里承担什么职责？

Redis 主要承担短期会话态、最近消息、限流计数、checkpoint 指针和异步工具回调。长期语义知识更适合向量库或关系库。这样可以避免把任务状态、用户偏好、知识文档混在一个存储里。

## 5. SSE 怎么接入？

后端使用 `StreamingResponse` 输出 `text/event-stream`。每个 Agent 节点产生一个事件，例如 `understand`、`retrieve`、`rerank`、`tool`、`answer`。前端用 `fetch` 和 `ReadableStream` 解析事件并实时渲染。

## 6. 用户取消任务如何设计？

取消命令可以写入任务控制通道，例如 CommandBus、Redis Stream 或 checkpoint 状态。runtime 在节点边界检查取消信号；如果当前工具是阻塞调用，则需要超时控制或异步任务取消机制。取消事件要写入 trace，避免恢复时拿到错误上下文。

## 7. 工具 schema 怎么设计？

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

## 8. LangChain 和 LangGraph 如何取舍？

线性单轮流程可以用 LangChain chain；如果系统存在状态、多分支、循环、人工确认、中断恢复和失败重试，就更适合 LangGraph。当前项目保留轻量 workflow，是为了把状态边界先做清楚，后续可以迁移到 LangGraph StateGraph。

## 9. 如何限制幻觉？

项目从四层控制幻觉：

- 检索层：清洗、切片、混合召回、rerank；
- 生成层：要求基于证据回答，证据不足拒答；
- 工具层：实时事实以工具或数据库返回为准；
- 审计层：citation、trace、答案校验和人工接管。

## 10. 生产化还需要补什么？

当前仓库是可扩展骨架，生产化可继续补充：

- Milvus / pgvector；
- bge-reranker；
- LangGraph checkpoint；
- Redis Cluster；
- OpenTelemetry / Langfuse；
- 鉴权和租户隔离；
- 评测集和自动回归；
- 灰度发布、限流和熔断。
