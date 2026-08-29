# 模型降级与备用 Provider 说明

这份文档说明本项目如何在本地 Qwen/vLLM 不可用时自动切换到 DeepSeek。这个设计对应真实大模型应用里的模型网关思想：业务代码不直接绑定单一模型实例，而是通过可观测的 endpoint 列表完成探活、调用和降级。

## 1. 当前策略

默认调用顺序：

```text
primary  -> local_qwen_vllm / Qwen3.6-27B / http://192.168.27.250:18003/v1
fallback -> deepseek / deepseek-v4-flash / https://api.deepseek.com
```

只有设置 `RAG_USE_LLM=true` 后，后端才会调用真实模型。否则使用模板 fallback，保证公开仓库在没有模型和 API key 的情况下仍能跑测试。

## 2. API Key 填在哪里

本地私有配置文件：

```text
/data/zmy/portfolio_workspace/github/Agentic-RAG-Platform/.env
```

需要填这一行：

```bash
LLM_FALLBACK_API_KEY=sk-你的DeepSeekKey
```

也可以填：

```bash
DEEPSEEK_API_KEY=sk-你的DeepSeekKey
```

`.env` 已经在 `.gitignore` 里，不会上传到 GitHub/Gitee。公开仓库提交的是 `.env.example`，只用于说明变量结构。

## 3. 什么时候会切到 DeepSeek

后端调用模型时按 endpoint 顺序尝试：

1. primary 未配置：跳过；
2. primary 连接失败、超时、HTTP 错误或返回空答案：记录失败 attempt；
3. fallback 已配置：继续调用 DeepSeek；
4. fallback 成功：最终 answer 使用 DeepSeek 返回；
5. fallback 也失败：workflow 退回模板回答，并把失败原因写入 trace。

切换逻辑在：

```text
backend/app/llm/client.py
```

workflow 的 `llm` 事件会记录：

```json
{
  "endpoint": "fallback",
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "attempts": [
    {
      "endpoint": "primary",
      "provider": "local_qwen_vllm",
      "ok": false
    },
    {
      "endpoint": "fallback",
      "provider": "deepseek",
      "ok": true
    }
  ]
}
```

这可以证明降级不是口头说的，而是业务后端真实执行了 provider 切换。

## 4. 如何验证 DeepSeek Key

```bash
./scripts/test_deepseek_api.sh
```

如果没有配置 key，脚本会直接提示你填 `.env`。

## 5. 如何模拟本地 Qwen 故障

先停止当前后端，再用一个不可达的 primary 地址启动：

```bash
LLM_API_BASE=http://127.0.0.1:9/v1 LLM_TIMEOUT_SECONDS=1 ./scripts/run_backend_with_qwen.sh
```

`scripts/run_backend_with_qwen.sh` 会读取仓库根目录 `.env`，但命令行显式传入的变量优先级更高，所以这个命令可以临时覆盖 primary 地址，不会改动你的真实配置文件。

然后调用：

```bash
curl -N -X POST http://localhost:18080/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"fallback-demo","message":"如何限制 RAG 幻觉？"}'
```

如果 `.env` 里有 DeepSeek key，`llm` 事件会显示 `provider=deepseek`。如果没有 key，则 fallback 会被标记为 `endpoint not configured`。

## 6. 为什么这是生产化设计

真实线上服务不能假设某个模型永远可用。模型实例可能因为 GPU OOM、容器重启、网络抖动、限流或版本切换而失败。业务后端必须能：

- 记录 primary 失败原因；
- 切换到备用 provider；
- 保留每次 attempt 的 endpoint、provider、model、latency 和 token usage；
- 不把 API key 暴露给前端；
- 允许后续把 DeepSeek 替换成其他 OpenAI-compatible 模型。

这也是大模型应用落地里比“会调用一个模型接口”更重要的工程能力。
