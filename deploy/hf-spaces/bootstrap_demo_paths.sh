#!/usr/bin/env bash
# Подготовка путей data/ и chroma_db/ из demo_* (HF Spaces / первый старт).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

mkdir -p data chroma_db
if [[ -d demo_data ]] && [[ -z "$(ls -A data 2>/dev/null || true)" ]]; then
  cp -rn demo_data/. data/ 2>/dev/null || cp -r demo_data/. data/
fi
if [[ -d demo_chroma_db ]] && [[ ! -f chroma_db/active_index.json ]]; then
  cp -rn demo_chroma_db/. chroma_db/ 2>/dev/null || cp -r demo_chroma_db/. chroma_db/
fi
