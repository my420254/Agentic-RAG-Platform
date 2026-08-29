#!/usr/bin/env bash
set -euo pipefail

LLM_API_BASE="${LLM_API_BASE:-http://192.168.27.250:18003/v1}"
LLM_MODEL="${LLM_MODEL:-Qwen3.6-27B}"
LLM_API_KEY="${LLM_API_KEY:-qwen-local-key}"
SERVER_URL="${LLM_API_BASE%/v1}"

echo "[1/3] health: ${SERVER_URL}/health"
curl --noproxy '*' -i -sS -m 10 "${SERVER_URL}/health"
echo

echo "[2/3] models: ${LLM_API_BASE}/models"
curl --noproxy '*' -sS -m 20 "${LLM_API_BASE}/models" \
  -H "Authorization: Bearer ${LLM_API_KEY}"
echo

echo "[3/3] chat: ${LLM_MODEL}"
curl --noproxy '*' -sS -m 60 "${LLM_API_BASE}/chat/completions" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${LLM_API_KEY}" \
  -d "{
    \"model\": \"${LLM_MODEL}\",
    \"messages\": [
      {\"role\": \"user\", \"content\": \"用一句话说明 RAG 项目为什么要接本地 vLLM。\"}
    ],
    \"temperature\": 0.2,
    \"max_tokens\": 96,
    \"chat_template_kwargs\": {\"enable_thinking\": false}
  }"
echo
