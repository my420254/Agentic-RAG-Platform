# 面试讲解稿

## 一句话介绍

这是一个面向企业知识库问答的 Agentic RAG 平台骨架。我重点做的是链路工程化：FastAPI API、SSE 流式事件、RAG 召回与重排、Redis 会话记忆、工具 registry 和可扩展的 Agent workflow。

## 项目为什么有价值

普通 RAG demo 的问题是只展示最终回答，看不出工程能力。这个项目刻意把链路拆开，让面试官可以看到：

- 我知道 RAG 质量问题怎么定位；
- 我知道 Agent 状态怎么建模；
- 我知道 Redis 在系统里该存什么；
- 我知道前端如何接流式事件；
- 我知道工具调用不是只写 schema，还要做业务约束；
- 我知道后续如何替换成生产级组件。

## 架构怎么讲

> 前端通过 `/api/chat/stream` 发请求，后端 FastAPI 创建 AgentState，然后 workflow 依次执行 understand、retrieve、rerank、tool、answer。每个节点都通过 SSE 推一个事件给前端。会话消息进入 MemoryService，优先写 Redis，没有 Redis 时走内存 fallback。RAG 侧现在是轻量关键词召回，保留 Evidence API，后续可以替换成向量库和 reranker。

## 面试问题回答

### 1. 你这个项目和普通 RAG 有什么区别？

普通 RAG 是一次检索一次生成。这个项目是 Agentic RAG，先理解问题，再检索、重排、按需调用工具，最后生成带证据的答案。这样能处理多轮任务、证据冲突和工具补充信息。

### 2. chunk 怎么切？

我的原则是按语义结构优先，固定长度兜底。长规则页按标题和段落切，短 QA 按问答对切，chunk 之间保留 overlap，避免条件和结论被切断。chunk 太小会丢上下文，太大会引入噪声和浪费 token。

### 3. 向量检索不准怎么排查？

我不会先改 prompt，而是从数据和召回链路排：

- 文档清洗是否把关键信息删掉；
- chunk 是否切断实体和条件；
- embedding 是否适合中文和业务域；
- metadata filter 是否过严；
- top_k 是否合理；
- 是否缺 BM25 / SQL / 图谱召回；
- 是否需要 reranker；
- prompt 是否强制引用证据。

### 4. Redis 在这里干什么？

Redis 主要做短期会话态、最近消息、限流计数、checkpoint 指针和异步工具回调。长期语义知识不应该全放 Redis，也不应该把所有记忆都塞进向量库。生产上会把短期状态放 Redis，长期知识放向量库或关系库。

### 5. SSE 怎么做？

后端用 StreamingResponse 输出 `text/event-stream`。每个 Agent 节点产生一个事件，例如 understand、retrieve、rerank、tool、answer。前端用 fetch + ReadableStream 解析事件并实时渲染。

### 6. 用户点停止怎么办？

生产版会把停止命令写入任务控制通道，例如 CommandBus 或 Redis stream。runtime 在节点间隙检查取消信号。如果当前工具是阻塞调用，要么等待超时返回，要么用异步任务取消机制。取消必须写 trace，避免后续恢复错任务。

### 7. 工具 schema 怎么设计？

工具 schema 只解决参数类型问题，不解决业务合法性。我会给工具增加：

- name / description；
- allowed_intents；
- args schema；
- return schema；
- timeout；
- retry policy；
- permission check；
- structured error code。

比如参数里订单号格式正确，也要确认这个订单属于当前用户。

### 8. LangChain 和 LangGraph 怎么选？

线性单轮流程用 LangChain 即可；如果有状态、多分支、循环、人工确认、中断恢复和失败重试，就用 LangGraph。这个项目当前用轻量 workflow 展示节点边界，后续可以迁到 LangGraph StateGraph。

### 9. 如何限制幻觉？

我会从四层做：

- 检索层：清洗、切片、混合召回、rerank；
- 生成层：要求基于证据回答，证据不足拒答；
- 工具层：实时状态以工具/数据库为准；
- 审计层：citation、trace、答案校验和人工接管。

### 10. 这个项目线上化还缺什么？

当前是作品集骨架，生产化需要补：

- Milvus / pgvector；
- bge-reranker；
- LangGraph checkpoint；
- Redis Cluster；
- OpenTelemetry / Langfuse；
- 鉴权和租户隔离；
- 评测集和自动回归；
- 灰度发布和限流熔断。

## 和你其他项目如何联动

- 讲 Agent runtime：用 `OurAgent-he1`。
- 讲 RAG 服务化：用这个项目。
- 讲模型微调：用 `Hy-MoRA` 和 `HiPro-LoRA`。
- 讲 NLP 结构抽取：用 `SPEAR` 和 `FASTE`。
- 讲 benchmark 和公平评测：用 `OurAgent`。

## 最终总结话术

> 我补这个项目不是为了堆一个聊天机器人，而是为了展示我对大模型应用工程的完整理解：检索怎么做、记忆怎么分层、状态怎么流转、工具怎么校验、前端怎么接流式输出、线上怎么监控和恢复。它和我的 OurAgent-he1 结合起来，基本覆盖了智能体研发岗位最常问的系统能力。
