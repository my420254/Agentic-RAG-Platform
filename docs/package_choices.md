# 包选型说明

本项目的原则是：已经在代码中承担职责的包写入正式依赖；还只是生产化扩展方向的包先写入路线图，不提前塞进 requirements。

## 当前已使用

| 包 | 用途 | 为什么选它 |
| --- | --- | --- |
| `fastapi` | HTTP API、任务提交、工具接口、SSE 接入 | Python 大模型应用常用，和 Pydantic、Uvicorn 配合成熟 |
| `uvicorn[standard]` | ASGI 服务运行 | 适合 FastAPI，本地调试和容器部署都简单 |
| `pydantic` | 请求体校验、结构化数据 | 让 API 输入有类型边界，减少手写参数检查 |
| `redis` | Redis client，也就是常说的 `redis-py` | 用于 session memory、task state、cancel flag、rate limit 的生产替换路径 |
| `pytest` | 后端单元测试和 API 测试 | 覆盖 chunk、retriever、workflow、task、tool 和 API 行为 |
| `httpx2` | FastAPI/Starlette TestClient 测试依赖 | 用于隔离环境下跑 API smoke test |
| `vue` | 前端框架 | 适合快速构建状态驱动的 Agent 工作台 |
| `element-plus` | Vue3 组件库 | 比手写 UI 更稳定，适合后台工作台和企业级界面 |
| `@element-plus/icons-vue` | 前端图标 | 配合 Element Plus 按钮和面板 |
| `vite` | 前端构建工具 | Vue3 项目标准选择，开发和构建速度快 |
| `vue-tsc` | Vue + TypeScript 类型检查 | 避免 Vue 单文件组件类型问题 |

## 暂时不加入正式依赖

| 包 | 暂不加入原因 | 什么时候加入 |
| --- | --- | --- |
| `kafka-python` | 当前没有真实 Kafka producer/consumer，提前加入会显得依赖虚胖 | 实现 `backend/app/queue/kafka_bus.py` 后加入 |
| `SQLAlchemy` | 当前 task state 使用 Redis/内存，没有 Postgres 持久化模型 | 实现任务表、审计表、用户表后加入 |
| `loguru` | 当前项目日志量很小，直接加不如先保证功能闭环 | 加入 worker、模型网关、队列消费后用于结构化日志 |
| `poetry` | 当前项目结构简单，`requirements.txt` 更容易被普通读者直接运行 | 当后端拆成正式 Python package、有 dev/prod extras 时再切 |
| `langgraph` | 当前 workflow 是轻量自实现，为了开箱可跑 | 下一阶段把 AgentWorkflow 替换为 LangGraph StateGraph 时加入 |
| `chromadb` / `pymilvus` / `pgvector` | 当前没有真实向量库索引和 embedding pipeline | 实现生产级 hybrid retrieval 后加入 |

## 对外项目介绍中的说法

可以这样讲：

```text
我没有为了堆技术栈把 Kafka、SQLAlchemy、LangGraph 全部写进依赖，而是按模块成熟度逐步引入。当前版本先实现了 FastAPI、SSE、Redis 状态层、RRF 混合检索、任务取消和 Vue3 工作台；后续如果做生产化，会把本地 TaskService 替换成 Kafka/Redis Stream，把轻量检索替换成 Milvus/pgvector + BM25，把自定义 workflow 替换成 LangGraph checkpoint。
```

不要这样讲：

```text
项目用了 Kafka、SQLAlchemy、LangGraph、Milvus、MCP、分布式高并发全套技术。
```

除非这些模块真的已经有代码、测试和运行文档。

## 下一阶段建议引入顺序

1. `langgraph`：把 workflow 改成 StateGraph，支持 checkpoint 和条件边。
2. `rank-bm25` 或 Elasticsearch：把当前 BM25-style 替换成标准 BM25。
3. `chromadb` 或 `pgvector`：补真实向量召回。
4. `sentence-transformers` 或 OpenAI-compatible embedding：补 embedding pipeline。
5. `redis` 扩展：补 rate limit、cancel flag、task event replay 的真实 Redis 测试。
6. `kafka-python` 或 `redis-stream`：补异步任务队列。
7. `SQLAlchemy`：补 Postgres durable task store 和 audit log。
8. `loguru`：补 worker 结构化日志。
9. `locust` 或 `k6`：补压测脚本和性能报告。
