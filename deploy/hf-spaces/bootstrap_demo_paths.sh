#!/usr/bin/env bash
# Подготовка путей data/ и chroma_db/ из demo_* (HF Spaces / первый старт).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

DATA_TARGET="${HOME_RAG_DATA_DIR:-${HOME_RAG_HOME:-$ROOT}/data}"
INDEX_TARGET="${HOME_RAG_INDEX_DIR:-${HOME_RAG_HOME:-$ROOT}/chroma_db}"

mkdir -p "$DATA_TARGET" "$INDEX_TARGET"
if [[ -d demo_data ]] && [[ -z "$(ls -A "$DATA_TARGET" 2>/dev/null || true)" ]]; then
  cp -rn demo_data/. "$DATA_TARGET"/ 2>/dev/null || cp -r demo_data/. "$DATA_TARGET"/
fi
if [[ -d demo_chroma_db ]] && [[ ! -f "$INDEX_TARGET/active_index.json" ]]; then
  cp -rn demo_chroma_db/. "$INDEX_TARGET"/ 2>/dev/null || cp -r demo_chroma_db/. "$INDEX_TARGET"/
fi
