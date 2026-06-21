#!/usr/bin/env bash
set -euo pipefail

cleanup() {
  if [[ -n "${UVICORN_PID:-}" ]] && kill -0 "${UVICORN_PID}" 2>/dev/null; then
    kill "${UVICORN_PID}" 2>/dev/null || true
    wait "${UVICORN_PID}" 2>/dev/null || true
  fi
}

trap cleanup SIGTERM SIGINT EXIT

uvicorn app.api:app --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!

streamlit run app/ui/main.py \
  --server.port 8501 \
  --server.address 0.0.0.0 \
  --server.headless true
