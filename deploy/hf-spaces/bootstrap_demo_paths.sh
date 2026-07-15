#!/usr/bin/env bash
# Подготовка путей data/ и chroma_db/ из demo_* (HF Spaces / первый старт).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

DATA_TARGET="${HOME_RAG_DATA_DIR:-${HOME_RAG_HOME:-$ROOT}/data}"
INDEX_TARGET="${HOME_RAG_INDEX_DIR:-${HOME_RAG_HOME:-$ROOT}/chroma_db}"
HOME_TARGET="${HOME_RAG_HOME:-$ROOT}"
REGISTRY_TARGET="${INDEX_REGISTRY_PATH:-$HOME_TARGET/index_registry.json}"

mkdir -p "$DATA_TARGET" "$INDEX_TARGET" "$(dirname "$REGISTRY_TARGET")"
if [[ -d demo_data ]] && [[ -z "$(ls -A "$DATA_TARGET" 2>/dev/null || true)" ]]; then
  cp -rn demo_data/. "$DATA_TARGET"/ 2>/dev/null || cp -r demo_data/. "$DATA_TARGET"/
fi
if [[ -d demo_data/uploads/hometutor_101 && ! -f "$DATA_TARGET/uploads/hometutor_101/README.md" ]]; then
  mkdir -p "$DATA_TARGET/uploads"
  cp -rn demo_data/uploads/hometutor_101 "$DATA_TARGET/uploads"/ 2>/dev/null || cp -r demo_data/uploads/hometutor_101 "$DATA_TARGET/uploads"/
fi
if [[ -d demo_chroma_db ]] && [[ ! -f "$INDEX_TARGET/active_index.json" ]]; then
  cp -rn demo_chroma_db/. "$INDEX_TARGET"/ 2>/dev/null || cp -r demo_chroma_db/. "$INDEX_TARGET"/
fi
if [[ -f demo_index_registry.json && ! -f "$REGISTRY_TARGET" ]]; then
  cp demo_index_registry.json "$REGISTRY_TARGET"
fi
