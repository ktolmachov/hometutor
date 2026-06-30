#!/usr/bin/env bash
set -euo pipefail

cleanup() {
  if [[ -n "${UVICORN_PID:-}" ]] && kill -0 "${UVICORN_PID}" 2>/dev/null; then
    kill "${UVICORN_PID}" 2>/dev/null || true
    wait "${UVICORN_PID}" 2>/dev/null || true
  fi
}

trap cleanup SIGTERM SIGINT EXIT

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
