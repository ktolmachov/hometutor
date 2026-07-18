from types import SimpleNamespace
import os
import subprocess
import sys

from pathlib import Path

from app.config import (
    CHROMA_DIR,
    DATA_DIR,
    DEFAULT_EMBED_API_BASE,
    DEFAULT_EMBED_MODEL,
    Settings,
    get_settings,
    reset_settings_cache,
)
from app.llm_guards import HARD_TOKEN_LIMIT, RAG_CONTEXT_PROMPT_RESERVE_TOKENS, resolve_rag_context_token_budget
from app.ingestion_env_diag import _resolve_embed_api_base
from app.path_safety import get_data_dir


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


def test_data_dir_on_settings_and_get_data_dir_helper(tmp_path, monkeypatch) -> None:
    """Settings.data_dir + path_safety.get_data_dir are the allowed data-root accessors."""
    custom = tmp_path / "materials"
    custom.mkdir()
    reset_settings_cache()
    try:
        monkeypatch.setenv("HOME_RAG_DATA_DIR", str(custom))
        # Rebuild settings so Field alias picks env (module DATA_DIR may stay old).
        settings = Settings(data_dir=custom)
        assert Path(settings.data_dir) == custom
        monkeypatch.setattr("app.config.get_settings", lambda: settings)
        assert get_data_dir() == custom.resolve()
    finally:
        reset_settings_cache()


def test_settings_data_dir_defaults_align_with_module_constant() -> None:
    s = Settings()
    assert Path(s.data_dir).resolve() == Path(DATA_DIR).resolve()


def test_env_data_dir_realigns_user_data_paths(tmp_path, monkeypatch) -> None:
    """HOME_RAG_DATA_DIR must re-root cache / user_state / auth under data_dir.

    Does not pass data_dir= into the constructor — env-driven load only.
    """
    custom = (tmp_path / "home" / "data").resolve()
    custom.mkdir(parents=True)
    reset_settings_cache()
    try:
        monkeypatch.setenv("HOME_RAG_DATA_DIR", str(custom))
        s = Settings()
        assert Path(s.data_dir).resolve() == custom
        assert Path(s.llm_request_cache_db_path).resolve() == custom / "llm_request_cache.db"
        assert Path(s.user_state_db).resolve() == custom / "user_state.db"
        assert Path(s.auth_db).resolve() == custom / "auth.db"
        # get_settings() cache should see the same after rebuild
        reset_settings_cache()
        monkeypatch.setenv("HOME_RAG_DATA_DIR", str(custom))
        g = get_settings()
        assert Path(g.data_dir).resolve() == custom
        assert Path(g.user_state_db).resolve() == custom / "user_state.db"
    finally:
        reset_settings_cache()


def test_path_safety_data_dir_monkeypatch_still_honored(tmp_path, monkeypatch) -> None:
    """Legacy fixtures that patch path_safety.DATA_DIR must keep working."""
    import app.path_safety as path_safety

    custom = tmp_path / "patched_data"
    custom.mkdir()
    monkeypatch.setattr(path_safety, "DATA_DIR", custom)
    assert path_safety.get_data_dir() == custom.resolve()
    # Relative resolve stays inside patched root
    target = custom / "course" / "a.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    resolved = path_safety.resolve_data_relative_path("course/a.md")
    assert resolved == target.resolve()
