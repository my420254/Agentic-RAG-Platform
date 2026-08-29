# 评测与生产化说明

这份文档说明项目为什么要加入检索评测、证据质量门控、Trace 和高并发扩展边界。它的目标是让项目看起来像一个真实可落地的大模型应用，而不是只会调 API 的聊天 demo。

## 1. 为什么 RAG 项目必须有评测

RAG 的常见问题不是“模型不会回答”，而是：

- 没有召回到关键文档；
- 召回到了但排序靠后；
- chunk 把条件和结论切断；
- metadata filter 把正确文档过滤掉；
- reranker 没有把业务关键词排到前面；
- 证据不足时模型仍然编答案。

因此本项目加入 `scripts/run_rag_eval.py` 和 `backend/app/rag/evaluator.py`，用固定 case 输出：

- `hit_rate`：top_k 里是否命中期望文档；
- `mrr`：第一个正确文档排在第几位；
- `failed_cases`：未命中的 case，方便回归修复。

运行：

```bash
python scripts/run_rag_eval.py --top-k 3
```

当前 demo 评测集：

```text
data/eval/retrieval_cases.json
```

## 2. 为什么要做证据质量门控

普通 RAG demo 只要 top_k 有结果就进入生成，这在生产环境很危险。项目把质量判断独立成：

```text
backend/app/rag/quality.py
```

workflow 中新增 `quality` 节点：

```text
understand -> retrieve -> rerank -> quality -> tool -> answer
```

如果证据为空或分数低于阈值，系统会拒答，而不是把不可靠上下文交给模型编答案。生产版本可以把当前阈值替换为：

- reranker score 阈值；
- LLM-as-judge；
- 人工标注评测集调参；
- 按业务域设置不同阈值。

## 3. 为什么保留模板 fallback

项目默认不调用 LLM，因为公开仓库和面试演示需要稳定可跑。设置下面变量后才会调用 OpenAI-compatible 接口。当前项目已按本机真实部署接入 Qwen3.6-27B：

```bash
export RAG_USE_LLM=true
export LLM_API_BASE=http://192.168.27.250:18003/v1
export LLM_MODEL=Qwen3.6-27B
export LLM_API_KEY=qwen-local-key
export LLM_ENABLE_THINKING=false
```

这个设计体现一个重要工程原则：模型是生成组件，不是系统控制面。检索、权限、质量门控、任务状态、取消和 Trace 都必须由后端代码控制。

模型状态可以通过后端接口确认：

```bash
curl http://localhost:18080/api/llm/status
```

如果返回 `reachable=true` 且 `models` 包含 `Qwen3.6-27B`，说明问答链路的最终生成阶段已经接入本地 vLLM。

如果本地 Qwen 不可用，并且 `.env` 配置了 `LLM_FALLBACK_API_KEY`，后端会自动切到 DeepSeek。Trace 中会记录命中的 `endpoint`、`provider`、`model` 和前面失败的 attempts。

项目在 workflow 里通过线程执行 OpenAI-compatible 模型请求，避免阻塞 FastAPI 事件循环。`llm` trace 会记录：

- `model`：本次调用的模型名；
- `latency_ms`：模型请求耗时；
- `prompt_tokens` / `completion_tokens` / `total_tokens`：token 用量。

这几个字段可以直接用于解释成本、延迟和容量评估。

## 4. Trace 如何用于故障定位

每个任务会记录节点事件：

```text
task_created
understand
retrieve
rerank
quality
tool
answer
error / cancelled
```

查询：

```bash
curl http://localhost:18080/api/tasks/<task_id>/trace
```

每个 HTTP 响应都会带 `x-request-id`。如果调用方传入 `x-request-id`，后端会原样返回；否则后端自动生成。这样日志、Trace、前端报错和一次用户请求可以串起来排查。

Trace 可以回答：

- 是没有召回，还是 rerank 排错了；
- 是工具参数错误，还是意图不允许；
- 是证据不足拒答，还是模型生成失败；
- 用户取消发生在哪个节点之后；
- 某个版本修改是否导致失败 case 增加。

## 5. 高并发落地边界

当前项目是单机可运行骨架，真正生产化时要把“接入并发”和“模型计算并发”拆开。

推荐演进：

```text
Nginx/API Gateway
  -> FastAPI Ingress
  -> Redis Rate Limit
  -> Kafka / Redis Stream Task Queue
  -> Agent Workers
  -> Retriever / Reranker
  -> vLLM Serving Pool
  -> Tool Workers
  -> Event Topic
  -> SSE Gateway
```

关键点：

- FastAPI 负责接入和鉴权，不直接承载长耗时模型计算；
- Redis 负责限流、短期会话、取消标记和 checkpoint 指针；
- Kafka/Redis Stream 负责削峰和任务解耦；
- vLLM 独立扩缩容，利用 continuous batching 提升吞吐；
- 检索服务和 reranker 支持缓存与批处理；
- 事件流写入 Trace，方便线上排障和回归。

## 6. 项目可讲的真实难点

面试时不要只说“我做了 RAG”，而要讲这些工程问题：

- 文档切片如何影响召回；
- BM25 和向量召回为什么要融合；
- 证据不足为什么要拒答；
- 工具结果和知识库冲突时以谁为准；
- 多轮记忆为什么放 Redis，不全部塞向量库；
- SSE 为什么适合展示 Agent 中间过程；
- 任务取消为什么必须进入后端状态；
- 如何用固定评测集防止改代码后检索质量退化。
