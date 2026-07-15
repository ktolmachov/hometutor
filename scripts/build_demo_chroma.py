"""CLI: build the pre-computed demo Chroma index (demo_data/ -> demo_chroma_db/).

Used for the free-tier cloud deploy (deploy/hf-spaces/), where only cloud
embeddings are reachable (no local LM Studio/llama.cpp). Overrides data/index
paths and embedding provider via env vars *before* importing app.config, since
HOME_RAG_DATA_DIR/HOME_RAG_INDEX_DIR are resolved once at module import time.

EMBED_API_BASE/EMBED_MODEL/EMBED_DIMENSIONS here must match the values set as
HF Space secrets (see deploy/hf-spaces/README.md) — otherwise query-time
embeddings won't be comparable to the ones baked into this index.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_DEFAULTS = {
    "HOME_RAG_DATA_DIR": str(REPO_ROOT / "demo_data"),
    "HOME_RAG_INDEX_DIR": str(REPO_ROOT / "demo_chroma_db"),
    "INDEX_REGISTRY_PATH": str(REPO_ROOT / "demo_index_registry.json"),
    "INDEX_REGISTRY_LOCK_PATH": str(REPO_ROOT / "demo_index_registry.json.lock"),
    "EMBED_API_BASE": "https://openrouter.ai/api/v1",
    "EMBED_MODEL": "perplexity/pplx-embed-v1-0.6b",
    "EMBED_DIMENSIONS": "1024",
    # No LLM calls needed to build embeddings-only index; avoid depending on
    # a reachable cloud LLM_API_BASE during this offline build step.
    "ENABLE_METADATA_ENRICHMENT": "false",
    "ENABLE_DOCUMENT_SUMMARIES": "false",
}
for _key, _value in _DEFAULTS.items():
    os.environ[_key] = _value

from app.config import CHROMA_DIR, DATA_DIR  # noqa: E402  (env must be set first)
from app.ingestion import build_index  # noqa: E402


def main() -> None:
    argparse.ArgumentParser(
        description="Build demo_chroma_db/ from demo_data/ using cloud embeddings.",
    ).parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY не найден — нужен рабочий ключ OpenRouter в .env")

    print(f"data_dir={DATA_DIR}")
    print(f"index_dir={CHROMA_DIR}")
    print(f"registry={os.environ['INDEX_REGISTRY_PATH']}")
    print(f"embed_api_base={os.environ['EMBED_API_BASE']}")
    print(f"embed_model={os.environ['EMBED_MODEL']}")
    build_index(reset=True)
    print("done.")


if __name__ == "__main__":
    main()
