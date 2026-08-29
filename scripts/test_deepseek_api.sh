#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${ROOT_DIR}/.env"
  set +a
fi

LLM_FALLBACK_API_BASE="${LLM_FALLBACK_API_BASE:-https://api.deepseek.com}"
LLM_FALLBACK_MODEL="${LLM_FALLBACK_MODEL:-deepseek-v4-flash}"
LLM_FALLBACK_API_KEY="${LLM_FALLBACK_API_KEY:-${DEEPSEEK_API_KEY:-}}"

if [[ -z "${LLM_FALLBACK_API_KEY}" ]]; then
  echo "未配置 DeepSeek API Key。请在仓库根目录 .env 中填写 LLM_FALLBACK_API_KEY 或 DEEPSEEK_API_KEY。"
  exit 2
fi

curl --noproxy '*' -sS -m 60 "${LLM_FALLBACK_API_BASE%/}/chat/completions" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${LLM_FALLBACK_API_KEY}" \
  -d "{
    \"model\": \"${LLM_FALLBACK_MODEL}\",
    \"messages\": [
      {\"role\": \"user\", \"content\": \"用一句话说明 DeepSeek 作为备用模型的价值。\"}
    ],
    \"temperature\": 0.2,
    \"max_tokens\": 96,
    \"thinking\": {\"type\": \"disabled\"}
  }"
echo
