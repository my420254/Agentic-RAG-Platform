#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:18080}"

echo "[1/6] health"
curl -s "${API_BASE}/api/health"
echo

echo "[2/6] runtime status"
curl -s "${API_BASE}/api/runtime/status"
echo

echo "[3/6] llm status"
curl -s "${API_BASE}/api/llm/status"
echo

echo "[4/6] load demo knowledge"
python scripts/load_demo_knowledge.py --api-base "${API_BASE}"

echo "[5/6] retrieval diagnose"
curl -s -X POST "${API_BASE}/api/retrieve" \
  -H 'Content-Type: application/json' \
  -d '{"query":"INC-1001 账单接口超时怎么处理","top_k":3}'
echo

echo "[6/6] streaming chat"
curl -N -X POST "${API_BASE}/api/chat/stream" \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","message":"INC-1001 账单接口超时怎么处理？"}'
