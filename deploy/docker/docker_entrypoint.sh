#!/usr/bin/env bash
set -euo pipefail

cleanup() {
  if [[ -n "${UVICORN_PID:-}" ]] && kill -0 "${UVICORN_PID}" 2>/dev/null; then
    kill "${UVICORN_PID}" 2>/dev/null || true
    wait "${UVICORN_PID}" 2>/dev/null || true
  fi
}

trap cleanup SIGTERM SIGINT EXIT

if [[ -n "${SPACE_ID:-}" || -n "${SPACE_HOST:-}" ]]; then
  if [[ -z "${HOME_RAG_HOME:-}" && -d "/data" && -w "/data" ]]; then
    export HOME_RAG_HOME="/data/hometutor"
  fi

  export HOME_RAG_DATA_MODE="${HOME_RAG_DATA_MODE:-demo}"
  export HOME_RAG_LOCAL_PROFILE="${HOME_RAG_LOCAL_PROFILE:-cloud_fast}"
  export HOME_RAG_LLM_CLOUD_CONSENT="${HOME_RAG_LLM_CLOUD_CONSENT:-true}"
  export HOME_RAG_LLM_FALLBACK_ENABLED="${HOME_RAG_LLM_FALLBACK_ENABLED:-true}"
  export OFFLINE_PROBE_LLM_ENDPOINT="${OFFLINE_PROBE_LLM_ENDPOINT:-false}"
  export LLM_LOCAL_WARMUP="${LLM_LOCAL_WARMUP:-false}"

  export OPENAI_API_BASE="${OPENAI_API_BASE:-https://openrouter.ai/api/v1}"
  export LLM_MODEL="${LLM_MODEL:-openai/gpt-4o-mini}"
  export QUIZ_LLM_MODEL="${QUIZ_LLM_MODEL:-${LLM_MODEL}}"
  export GRAPH_LLM_API_BASE="${GRAPH_LLM_API_BASE:-${OPENAI_API_BASE}}"
  export GRAPH_MODEL="${GRAPH_MODEL:-${LLM_MODEL}}"
  export SSR_LLM_API_BASE="${SSR_LLM_API_BASE:-${OPENAI_API_BASE}}"
  export SSR_LLM_MODEL="${SSR_LLM_MODEL:-${LLM_MODEL}}"
  export EMBED_API_BASE="${EMBED_API_BASE:-${OPENAI_API_BASE}}"
fi

# HF Spaces (Docker SDK) / demo: эфемерный FS контейнера — на каждом старте подкладываем
# demo_data/ + demo_chroma_db/, если data/ и chroma_db/ ещё пусты. На постоянном volume
# (docker-compose с HOME_RAG_HOME) это no-op после первого запуска. Путь относительно
# WORKDIR (/app в образе, см. Dockerfile), не относительно расположения этого скрипта —
# entrypoint копируется в /usr/local/bin отдельно от остального репозитория.
if [[ -f "deploy/hf-spaces/bootstrap_demo_paths.sh" ]]; then
  bash "deploy/hf-spaces/bootstrap_demo_paths.sh" || true
fi

uvicorn app.api:app --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!

streamlit run app/ui/main.py \
  --server.port 8501 \
  --server.address 0.0.0.0 \
  --server.headless true
