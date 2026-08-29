# Qwen vLLM 真实部署接入说明

这份文档说明本项目如何接入本机已经部署好的 Qwen vLLM 服务。项目本身不是只调用云 API 的演示，而是可以连接本地 GPU 上的 OpenAI-compatible 模型服务，形成“检索、质量门控、工具调用、Qwen 生成、Trace 记录”的完整链路。

## 1. 当前可用模型服务

截至 2026-08-29，当前正式接入目标如下：

| GPU | 端口 | 模型 | OpenAI-compatible Base URL | 说明 |
| --- | --- | --- | --- | --- |
| GPU 2 | `18003` | `Qwen3.6-27B` | `http://192.168.27.250:18003/v1` | 默认演示入口 |
| GPU 3 | `18004` | `Qwen3.6-27B` | `http://192.168.27.250:18004/v1` | 备用入口，可用于并行测试 |

统一鉴权：

```text
Authorization: Bearer qwen-local-key
```

项目默认使用 18003。如果要切换到 18004，只需要修改环境变量：

```bash
export LLM_API_BASE=http://192.168.27.250:18004/v1
```

## 2. 为什么 RAG 项目要接本地 vLLM

只写一个 RAG 原型很容易，但真实落地时一定会遇到模型服务层的问题：

- 模型部署地址、模型名、API key 需要独立于业务代码；
- 大模型输出成本、延迟和 token 用量要能记录；
- 检索证据不足时不能把问题直接丢给模型编答案；
- 本地 27B 模型要通过统一接口接入，方便之后切换 9B、27B 或多实例负载；
- 线上排障时要能区分是检索失败、工具失败，还是模型服务失败。

因此本项目把 Qwen/vLLM 放在 `backend/app/llm/client.py` 适配层里，后端 workflow 只调用统一的 `llm_client.answer(...)`。

## 3. 一键验证 vLLM

在仓库根目录运行：

```bash
./scripts/test_qwen_vllm.sh
```

脚本会依次验证：

```text
/health
/v1/models
/v1/chat/completions
```

如果要测试 18004：

```bash
LLM_API_BASE=http://192.168.27.250:18004/v1 ./scripts/test_qwen_vllm.sh
```

## 4. 启动真实 Qwen 后端

```bash
./scripts/run_backend_with_qwen.sh
```

默认等价于：

```bash
export RAG_USE_LLM=true
export LLM_API_BASE=http://192.168.27.250:18003/v1
export LLM_MODEL=Qwen3.6-27B
export LLM_API_KEY=qwen-local-key
export LLM_TIMEOUT_SECONDS=60
export LLM_MAX_TOKENS=512
export LLM_ENABLE_THINKING=false
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 18080
```

然后打开前端：

```bash
cd frontend
npm run dev -- --host 0.0.0.0
```

后端默认会自动加载 `data/demo_knowledge`。如果需要手动恢复演示知识，可以在另一个终端执行：

```bash
python scripts/load_demo_knowledge.py --api-base http://localhost:18080
```

也可以直接调用后端接口：

```bash
curl -X POST http://localhost:18080/api/demo/load
```

或者直接跑端到端 smoke：

```bash
./scripts/demo_smoke.sh
```

浏览器访问：

```text
http://localhost:5173
```

远程访问时使用服务器地址：

```text
http://<应用服务器IP>:5173
```

前端默认会用当前页面的主机名推断后端地址，也就是访问 `http://<应用服务器IP>:18080`。如果前后端部署在不同主机，可以显式设置：

```bash
export VITE_API_BASE=http://<应用服务器IP>:18080
```

## 5. 后端如何确认模型状态

后端提供：

```bash
curl http://localhost:18080/api/llm/status
```

典型返回字段：

```json
{
  "enabled": true,
  "api_base": "http://192.168.27.250:18003/v1",
  "model": "Qwen3.6-27B",
  "reachable": true,
  "models": ["Qwen3.6-27B"],
  "max_tokens": 512,
  "enable_thinking": false
}
```

这个接口用于说明项目不是黑盒 demo，而是能从业务后端直接探测模型服务是否在线。

## 6. DeepSeek 备用模型

为了避免本地 GPU、vLLM 容器或局域网偶发不可用导致演示中断，后端支持 fallback provider。默认顺序是：

```text
primary  -> local_qwen_vllm / Qwen3.6-27B / http://192.168.27.250:18003/v1
fallback -> deepseek / deepseek-v4-flash / https://api.deepseek.com
```

你只需要在仓库根目录 `.env` 里填写：

```bash
LLM_FALLBACK_API_KEY=sk-你的DeepSeekKey
```

也可以用别名：

```bash
DEEPSEEK_API_KEY=sk-你的DeepSeekKey
```

`.env` 不会提交到 Git。公开仓库保留 `.env.example`，用于说明需要哪些变量。

DeepSeek fallback 的请求不会携带 Qwen 专用的 `chat_template_kwargs`，而是使用 DeepSeek 的 thinking 参数：

```json
{"thinking": {"type": "disabled"}}
```

验证 DeepSeek API Key：

```bash
./scripts/test_deepseek_api.sh
```

模拟本地 Qwen 不可用：

```bash
LLM_API_BASE=http://127.0.0.1:9/v1 LLM_TIMEOUT_SECONDS=1 ./scripts/run_backend_with_qwen.sh
```

此时再调用 `/api/chat/stream`，如果 `.env` 里配置了 DeepSeek key，`llm` 事件会显示：

```json
{
  "endpoint": "fallback",
  "provider": "deepseek",
  "model": "deepseek-v4-flash"
}
```

真实问答完成后，SSE 事件里会出现 `llm` 节点，例如：

```json
{
  "mode": "openai_compatible",
  "model": "Qwen3.6-27B",
  "latency_ms": 950.3,
  "usage": {
    "prompt_tokens": 498,
    "completion_tokens": 143,
    "total_tokens": 641
  }
}
```

这说明最终答案不是模板拼接，而是经过本地 vLLM/Qwen 生成，同时保留了延迟和 token 成本信息。

## 7. 请求链路

一次真实问答的链路是：

```text
Vue 前端
  -> FastAPI /api/chat/stream
  -> understand 意图识别
  -> retrieve 混合召回
  -> rerank 证据重排
  -> quality 证据质量门控
  -> tool 可选工具查询
  -> Qwen3.6-27B/vLLM 生成最终回答
  -> SSE 返回节点事件和最终答案
```

模型只负责最后的自然语言生成；系统是否允许调用工具、是否拒答、是否取消任务、是否记录 Trace，都由后端代码控制。

## 8. Qwen 参数说明

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `RAG_USE_LLM` | `false` | 是否启用真实模型调用 |
| `LLM_API_BASE` | `http://192.168.27.250:18003/v1` | OpenAI-compatible 入口 |
| `LLM_MODEL` | `Qwen3.6-27B` | 请求里的模型名 |
| `LLM_API_KEY` | `qwen-local-key` | Bearer token |
| `LLM_TIMEOUT_SECONDS` | `30` | 模型请求超时时间 |
| `LLM_MAX_TOKENS` | `512` | 单次回答最大生成 token |
| `LLM_ENABLE_THINKING` | `false` | 关闭 Qwen thinking 输出，保证前端答案干净 |

## 9. 常见问题

### 后端回答仍然像模板

检查：

```bash
curl http://localhost:18080/api/llm/status
```

如果 `enabled=false`，说明启动后端时没有设置：

```bash
export RAG_USE_LLM=true
```

### 18003 不通

先验证模型服务：

```bash
curl --noproxy '*' http://192.168.27.250:18003/v1/models \
  -H 'Authorization: Bearer qwen-local-key'
```

如果 18003 不通，可以切 18004：

```bash
LLM_API_BASE=http://192.168.27.250:18004/v1 ./scripts/run_backend_with_qwen.sh
```

### 输出里出现思考过程

确认：

```bash
export LLM_ENABLE_THINKING=false
```

项目会把它传入：

```json
{"chat_template_kwargs": {"enable_thinking": false}}
```

这样更适合产品演示和面试展示。
