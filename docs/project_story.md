# 项目说明：为什么这是一个 Agentic RAG 平台

## 项目背景

企业知识库问答不是简单的“上传文档 + 调模型”。真实使用中会遇到：

- 文档内容多、格式杂，清洗和切片会直接影响召回；
- 用户问题经常混合业务词、错误码、制度条款和上下文省略；
- 向量召回对错误码、接口名、字段名等精确词不稳定；
- 检索到弱相关证据时，大模型容易生成看似合理但没有依据的回答；
- 多轮对话需要短期记忆，但不能把所有历史都塞进 prompt；
- 工具返回的实时状态可能和知识库历史文档冲突；
- 用户取消任务、服务超时、工具失败都需要在后端有状态记录；
- 系统上线后必须有 trace 和评测，否则无法判断改动是否导致质量退化。

因此本项目把 RAG 做成一个可观测、可评测、可扩展的 Agentic RAG 平台骨架。

## 核心能力

### 1. 多阶段 Agentic RAG Workflow

一次请求不会直接进入模型，而是经过：

```text
understand -> retrieve -> rerank -> quality -> tool -> answer
```

每个阶段都会输出事件，前端通过 SSE 实时展示。

### 2. 混合检索与 RRF 融合

项目同时做：

- BM25-style 关键词召回；
- sparse hash-vector 相似度召回；
- RRF 排名融合。

BM25 适合错误码、接口名、字段名等精确匹配；向量召回适合同义表达；RRF 可以避免不同分数体系直接相加带来的尺度问题。

### 3. 证据质量门控

检索结果进入生成前先经过 `quality` 节点。证据为空或分数太低时，系统拒答并提示补充文档，避免模型在无依据场景下编造答案。

### 4. 工具调用与实时事实

项目内置策略查询和工单查询工具，用来说明一个关键原则：

> 静态知识放知识库，实时状态走工具或数据库。

例如工单状态、订单状态、库存、账户余额等，不应该只依赖知识库历史文本。

### 5. Redis 状态层

Redis 在项目中的职责包括：

- session 近期消息；
- task 状态；
- cancel flag；
- rate limit；
- checkpoint 指针；
- 后续可扩展热门 query 缓存。

没有 Redis 时自动走内存 fallback，保证本地演示能跑。

### 6. 检索评测闭环

项目内置 `data/eval/retrieval_cases.json` 和 `scripts/run_rag_eval.py`，可以快速输出 Hit@K、MRR 和失败样本。这样每次改 chunk、tokenizer、召回或重排，都能用固定 case 检查是否退化。

## 技术栈

- 后端：Python、FastAPI、Pydantic、SSE；
- 检索：chunking、BM25-style ranking、sparse vector、RRF；
- 状态：Redis 优先、内存 fallback；
- 模型：OpenAI-compatible API，已适配本地 vLLM/Qwen3.6-27B；
- 前端：Vue3、TypeScript、Element Plus；
- 测试：pytest；
- 部署：Docker Compose。

## 可继续演进

这个项目刻意没有把所有外部服务都强绑定，而是保留清晰替换口：

- `retriever.py` 可以替换为 Milvus / pgvector / Elasticsearch；
- `_vector_ranking` 可以替换为 bge-m3 或 text-embedding 模型；
- `_rerank` 可以替换为 bge-reranker / cross-encoder；
- `AgentWorkflow` 可以迁移到 LangGraph StateGraph；
- `TaskService` 可以接 Kafka / Redis Stream；
- Trace 可以接 OpenTelemetry / Langfuse。

## 项目价值

这个项目展示的是大模型应用落地中的工程能力：

- 能把 RAG 问答拆成可定位的链路；
- 能用评测指标验证检索质量；
- 能处理证据不足、工具冲突、任务取消和多轮记忆；
- 能接本地 Qwen3.6-27B/vLLM 服务，又不把系统控制权交给模型；
- 能用前端工作台展示运行过程，而不是只给一个黑盒答案。

## 本地大模型部署结合点

项目当前可以直接连接本机已经部署好的 Qwen vLLM：

```text
192.168.27.250:18003 -> Qwen3.6-27B
192.168.27.250:18004 -> Qwen3.6-27B
```

这让项目从“RAG 代码样例”变成真实可演示的本地大模型应用：FastAPI 负责业务编排，vLLM 负责高吞吐生成，前端负责展示检索证据、工具结果、节点 Trace 和最终答案。
