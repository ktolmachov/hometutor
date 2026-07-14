from types import SimpleNamespace
import os
import subprocess
import sys

from app.config import CHROMA_DIR, DEFAULT_EMBED_API_BASE, DEFAULT_EMBED_MODEL, Settings
from app.llm_guards import HARD_TOKEN_LIMIT, RAG_CONTEXT_PROMPT_RESERVE_TOKENS, resolve_rag_context_token_budget
from app.ingestion_env_diag import _resolve_embed_api_base


def test_embedding_defaults_are_local_first() -> None:
    assert Settings.model_fields["embed_api_base"].default == DEFAULT_EMBED_API_BASE
    assert Settings.model_fields["embed_model"].default == DEFAULT_EMBED_MODEL
    assert Settings().embed_api_base_resolved == DEFAULT_EMBED_API_BASE


def test_rag_context_budget_auto_when_unset() -> None:
    assert Settings().rag_context_token_budget == 0
    assert resolve_rag_context_token_budget(0) == HARD_TOKEN_LIMIT - RAG_CONTEXT_PROMPT_RESERVE_TOKENS
    assert resolve_rag_context_token_budget(8000) == 8000


def test_index_meta_default_lives_next_to_runtime_index() -> None:
    assert Settings().index_meta_path == CHROMA_DIR.parent / "index_meta.json"


def test_empty_embed_api_base_does_not_fall_back_to_openai_api_base() -> None:
    settings = Settings(
        embed_api_base="",
        openai_api_base="https://openrouter.ai/api/v1",
    )

    assert settings.embed_api_base_resolved == DEFAULT_EMBED_API_BASE


def test_ingest_diag_embed_base_fallback_is_local_first_for_fake_settings() -> None:
    settings = SimpleNamespace(openai_api_base="https://openrouter.ai/api/v1")

    assert _resolve_embed_api_base(settings) == DEFAULT_EMBED_API_BASE


def test_process_env_overrides_dotenv_paths(tmp_path) -> None:
    env = dict(os.environ)
    env["HOME_RAG_HOME"] = str(tmp_path / "home")
    env["HOME_RAG_DATA_DIR"] = str(tmp_path / "home" / "data")
    code = "from app.config import HOME_RAG_HOME, DATA_DIR; print(HOME_RAG_HOME); print(DATA_DIR)"

    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        encoding="utf-8",
        env=env,
    )

    lines = [line.strip() for line in result.stdout.splitlines()]
    assert lines == [str(tmp_path / "home"), str(tmp_path / "home" / "data")]
