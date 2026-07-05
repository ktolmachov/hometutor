"""Пользовательские overrides RAG/ingest поверх config.env (app_kv)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal

from app.config import (
    KNOWN_RAG_PROFILES,
    KNOWN_RETRIEVAL_MODES,
    KNOWN_SPLIT_STRATEGIES,
    RetrievalSettings,
    Settings,
    get_retrieval_settings,
    get_settings,
)
from app.models import PipelineOverrides
from app.user_state import get_kv, set_kv

logger = logging.getLogger(__name__)

RAG_RUNTIME_OVERRIDES_KEY = "rag_runtime_overrides"

SettingSource = Literal["settings", "retrieval"]
SettingKind = Literal["bool", "int", "float", "str", "select"]


@dataclass(frozen=True)
class RagSettingSpec:
    key: str
    env_key: str
    title_ru: str
    group_ru: str
    source: SettingSource
    kind: SettingKind
    advanced: bool = False
    requires_reindex: bool = False
    help_ru: str = ""
    options: tuple[str, ...] | None = None
    min_val: float | None = None
    max_val: float | None = None


RAG_SETTING_SPECS: tuple[RagSettingSpec, ...] = (
    # Retrieval — основное
    RagSettingSpec(
        "rag_profile",
        "RAG_PROFILE",
        "Профиль RAG",
        "Retrieval — основное",
        "retrieval",
        "select",
        options=tuple(sorted(KNOWN_RAG_PROFILES)),
        help_ru="fast — быстрее; quality — точнее; graph_aware — с расширением по графу.",
    ),
    RagSettingSpec(
        "retrieval_mode",
        "RETRIEVAL_MODE",
        "Режим подбора",
        "Retrieval — основное",
        "retrieval",
        "select",
        options=tuple(sorted(KNOWN_RETRIEVAL_MODES)),
    ),
    RagSettingSpec(
        "similarity_top_k",
        "SIMILARITY_TOP_K",
        "Top-K фрагментов",
        "Retrieval — основное",
        "retrieval",
        "int",
        min_val=1,
        max_val=128,
    ),
    RagSettingSpec(
        "enable_reranker",
        "ENABLE_RERANKER",
        "Reranker",
        "Retrieval — основное",
        "retrieval",
        "bool",
    ),
    RagSettingSpec(
        "rerank_top_n",
        "RERANK_TOP_N",
        "Rerank top-N",
        "Retrieval — основное",
        "retrieval",
        "int",
        min_val=0,
        max_val=64,
    ),
    RagSettingSpec(
        "doc_top_k",
        "DOC_TOP_K",
        "Top-K документов (doc_then_chunk)",
        "Retrieval — основное",
        "retrieval",
        "int",
        min_val=1,
        max_val=64,
    ),
    # Retrieval — расширенное
    RagSettingSpec(
        "rerank_model",
        "RERANK_MODEL",
        "Модель reranker",
        "Retrieval — расширенное",
        "retrieval",
        "str",
        advanced=True,
    ),
    RagSettingSpec(
        "enable_lost_in_middle_reorder",
        "ENABLE_LOST_IN_MIDDLE_REORDER",
        "Lost-in-the-middle reorder",
        "Retrieval — расширенное",
        "retrieval",
        "bool",
        advanced=True,
    ),
    RagSettingSpec(
        "enable_multi_query",
        "ENABLE_MULTI_QUERY",
        "Multi-query expansion",
        "Retrieval — расширенное",
        "retrieval",
        "bool",
        advanced=True,
    ),
    RagSettingSpec(
        "multi_query_count",
        "MULTI_QUERY_COUNT",
        "Число multi-query вариантов",
        "Retrieval — расширенное",
        "retrieval",
        "int",
        advanced=True,
        min_val=2,
        max_val=4,
    ),
    RagSettingSpec(
        "enable_rewrite",
        "ENABLE_REWRITE",
        "Rewrite запроса",
        "Retrieval — расширенное",
        "settings",
        "bool",
        advanced=True,
    ),
    RagSettingSpec(
        "enable_classifier",
        "ENABLE_CLASSIFIER",
        "Классификатор типа запроса",
        "Retrieval — расширенное",
        "settings",
        "bool",
        advanced=True,
    ),
    RagSettingSpec(
        "enable_self_correction",
        "ENABLE_SELF_CORRECTION",
        "Self-correction ответа",
        "Retrieval — расширенное",
        "settings",
        "bool",
        advanced=True,
    ),
    RagSettingSpec(
        "enable_graph_augmented_retrieval",
        "ENABLE_GRAPH_AUGMENTED_RETRIEVAL",
        "Graph-augmented retrieval",
        "Retrieval — расширенное",
        "settings",
        "bool",
        advanced=True,
    ),
    RagSettingSpec(
        "graph_augment_max_extra_docs",
        "GRAPH_AUGMENT_MAX_EXTRA_DOCS",
        "Graph: max extra docs",
        "Retrieval — расширенное",
        "settings",
        "int",
        advanced=True,
        min_val=0,
        max_val=64,
    ),
    RagSettingSpec(
        "graph_expand_max_hops",
        "GRAPH_EXPAND_MAX_HOPS",
        "Graph: max hops",
        "Retrieval — расширенное",
        "settings",
        "int",
        advanced=True,
        min_val=1,
        max_val=16,
    ),
    RagSettingSpec(
        "enable_retrieval_self_correction",
        "ENABLE_RETRIEVAL_SELF_CORRECTION",
        "Retrieval self-correction retry",
        "Retrieval — расширенное",
        "settings",
        "bool",
        advanced=True,
    ),
    RagSettingSpec(
        "retrieval_self_correction_min_score",
        "RETRIEVAL_SELF_CORRECTION_MIN_SCORE",
        "Порог score для retry",
        "Retrieval — расширенное",
        "settings",
        "float",
        advanced=True,
        min_val=0.0,
        max_val=1.0,
    ),
    RagSettingSpec(
        "rag_context_token_budget",
        "RAG_CONTEXT_TOKEN_BUDGET",
        "Бюджет токенов контекста (0 = auto)",
        "Retrieval — расширенное",
        "settings",
        "int",
        advanced=True,
        min_val=0,
        max_val=100_000,
    ),
    RagSettingSpec(
        "enable_two_stage_answer_path",
        "ENABLE_TWO_STAGE_ANSWER_PATH",
        "Two-stage answer path",
        "Retrieval — расширенное",
        "settings",
        "bool",
        advanced=True,
    ),
    RagSettingSpec(
        "two_stage_early_exit_min_score",
        "TWO_STAGE_EARLY_EXIT_MIN_SCORE",
        "Two-stage: min score для раннего выхода",
        "Retrieval — расширенное",
        "settings",
        "float",
        advanced=True,
        min_val=0.0,
        max_val=1.0,
    ),
    # Chunking и индекс
    RagSettingSpec(
        "chunk_size",
        "CHUNK_SIZE",
        "Размер чанка",
        "Chunking и индекс",
        "retrieval",
        "int",
        requires_reindex=True,
        min_val=100,
        max_val=8000,
    ),
    RagSettingSpec(
        "chunk_overlap",
        "CHUNK_OVERLAP",
        "Перекрытие чанков",
        "Chunking и индекс",
        "retrieval",
        "int",
        requires_reindex=True,
        min_val=0,
        max_val=2000,
    ),
    RagSettingSpec(
        "split_strategy",
        "SPLIT_STRATEGY",
        "Стратегия разбиения",
        "Chunking и индекс",
        "retrieval",
        "select",
        requires_reindex=True,
        options=tuple(sorted(KNOWN_SPLIT_STRATEGIES)),
    ),
    RagSettingSpec(
        "window_size",
        "WINDOW_SIZE",
        "Окно sentence_window",
        "Chunking и индекс",
        "retrieval",
        "int",
        requires_reindex=True,
        min_val=0,
        max_val=32,
    ),
    RagSettingSpec(
        "enable_partial_reindex",
        "ENABLE_PARTIAL_REINDEX",
        "Частичная переиндексация",
        "Chunking и индекс",
        "settings",
        "bool",
    ),
    # Embeddings
    RagSettingSpec(
        "embed_model",
        "EMBED_MODEL",
        "Модель embeddings",
        "Embeddings",
        "settings",
        "str",
        requires_reindex=True,
    ),
    RagSettingSpec(
        "embed_dimensions",
        "EMBED_DIMENSIONS",
        "Размерность embeddings",
        "Embeddings",
        "settings",
        "int",
        requires_reindex=True,
        min_val=0,
        max_val=65536,
    ),
    RagSettingSpec(
        "embed_batch_size",
        "EMBED_BATCH_SIZE",
        "Batch size embeddings",
        "Embeddings",
        "settings",
        "int",
        min_val=1,
        max_val=2048,
    ),
    RagSettingSpec(
        "embed_num_workers",
        "EMBED_NUM_WORKERS",
        "Workers embeddings",
        "Embeddings",
        "settings",
        "int",
        min_val=1,
        max_val=32,
    ),
    RagSettingSpec(
        "embed_request_timeout",
        "EMBED_REQUEST_TIMEOUT",
        "Таймаут embed (сек)",
        "Embeddings",
        "settings",
        "int",
        min_val=1,
        max_val=600,
    ),
    RagSettingSpec(
        "embed_connect_timeout_sec",
        "EMBED_CONNECT_TIMEOUT_SEC",
        "Connect timeout embed (сек)",
        "Embeddings",
        "settings",
        "float",
        min_val=1.0,
        max_val=120.0,
    ),
    RagSettingSpec(
        "embed_max_retries",
        "EMBED_MAX_RETRIES",
        "Retries embeddings",
        "Embeddings",
        "settings",
        "int",
        min_val=0,
        max_val=10,
    ),
    # Ingest
    RagSettingSpec(
        "ingest_embed_pipeline_batch_size",
        "INGEST_EMBED_PIPELINE_BATCH_SIZE",
        "Ingest: pipeline batch",
        "Ingest",
        "settings",
        "int",
        min_val=1,
        max_val=2048,
    ),
    RagSettingSpec(
        "ingest_store_batch_size",
        "INGEST_STORE_BATCH_SIZE",
        "Ingest: store batch",
        "Ingest",
        "settings",
        "int",
        min_val=1,
        max_val=8192,
    ),
    RagSettingSpec(
        "doc_load_num_workers",
        "DOC_LOAD_NUM_WORKERS",
        "Потоки загрузки файлов",
        "Ingest",
        "settings",
        "int",
        min_val=1,
        max_val=32,
    ),
    RagSettingSpec(
        "ingest_docling_enabled",
        "INGEST_DOCLING_ENABLED",
        "Docling для сканов/PDF",
        "Ingest",
        "settings",
        "bool",
        requires_reindex=True,
        help_ru="Нужен пакет docling; влияет на извлечение текста при индексации.",
    ),
    RagSettingSpec(
        "ingest_docling_min_native_text_chars",
        "INGEST_DOCLING_MIN_NATIVE_TEXT_CHARS",
        "Docling: порог нативного текста PDF",
        "Ingest",
        "settings",
        "int",
        requires_reindex=True,
        min_val=0,
        max_val=1_000_000,
    ),
    RagSettingSpec(
        "enable_metadata_enrichment",
        "ENABLE_METADATA_ENRICHMENT",
        "Обогащение metadata при ingest",
        "Ingest",
        "settings",
        "bool",
        requires_reindex=True,
    ),
    RagSettingSpec(
        "enable_document_summaries",
        "ENABLE_DOCUMENT_SUMMARIES",
        "Сводки документов при ingest",
        "Ingest",
        "settings",
        "bool",
        requires_reindex=True,
    ),
    RagSettingSpec(
        "ingestion_model",
        "INGESTION_MODEL",
        "LLM для ingest enrichment",
        "Ingest — расширенное",
        "settings",
        "str",
        advanced=True,
        help_ru="Пустая строка = основная LLM_MODEL.",
    ),
    RagSettingSpec(
        "enable_faq_cache",
        "ENABLE_FAQ_CACHE",
        "FAQ cache",
        "Ingest — расширенное",
        "settings",
        "bool",
        advanced=True,
    ),
    RagSettingSpec(
        "faq_min_score",
        "FAQ_MIN_SCORE",
        "FAQ min score",
        "Ingest — расширенное",
        "settings",
        "float",
        advanced=True,
        min_val=0.0,
        max_val=1.0,
    ),
)

_SPEC_BY_KEY: dict[str, RagSettingSpec] = {spec.key: spec for spec in RAG_SETTING_SPECS}
_PIPELINE_OVERRIDE_KEYS = frozenset(
    {
        "rag_profile",
        "similarity_top_k",
        "enable_reranker",
        "rerank_top_n",
        "rerank_model",
        "split_strategy",
        "window_size",
        "retrieval_mode",
    }
)


def _ensure_auth_context() -> None:
    try:
        from app.ui.auth_gate import ensure_streamlit_auth_context

        ensure_streamlit_auth_context()
    except Exception:  # noqa: BLE001 - API path may already have auth context
        return


def _read_raw_kv(key: str, default: str | None = None) -> str | None:
    try:
        return get_kv(key, default)
    except Exception:  # noqa: BLE001 - preferences must not break startup
        return default


def _write_raw_kv(key: str, value: str) -> None:
    try:
        set_kv(key, value)
    except Exception as exc:  # noqa: BLE001
        logger.warning("rag_runtime_preferences set_kv failed for %r: %s", key, exc)


def get_overrides() -> dict[str, Any]:
    _ensure_auth_context()
    raw = _read_raw_kv(RAG_RUNTIME_OVERRIDES_KEY, "{}") or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in data.items():
        spec = _SPEC_BY_KEY.get(str(key))
        if spec is None:
            continue
        coerced = _coerce_value(spec, value, strict=False)
        if coerced is not None:
            out[spec.key] = coerced
    return out


def set_override(key: str, value: Any) -> None:
    spec = _SPEC_BY_KEY.get(str(key or "").strip())
    if spec is None:
        return
    coerced = _coerce_value(spec, value, strict=True)
    overrides = get_overrides()
    base = _base_value(spec)
    if coerced == base:
        overrides.pop(spec.key, None)
    else:
        overrides[spec.key] = coerced
    _ensure_auth_context()
    _write_raw_kv(RAG_RUNTIME_OVERRIDES_KEY, json.dumps(overrides, ensure_ascii=False, sort_keys=True))


def clear_overrides() -> None:
    _ensure_auth_context()
    _write_raw_kv(RAG_RUNTIME_OVERRIDES_KEY, "{}")


def _coerce_value(spec: RagSettingSpec, value: Any, *, strict: bool) -> Any | None:
    if value is None:
        return None
    if spec.kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        if strict:
            raise ValueError(f"invalid bool for {spec.key}")
        return None
    if spec.kind == "int":
        try:
            num = int(value)
        except (TypeError, ValueError):
            if strict:
                raise ValueError(f"invalid int for {spec.key}") from None
            return None
        if spec.min_val is not None and num < spec.min_val:
            if strict:
                raise ValueError(f"{spec.key} below min")
            return None
        if spec.max_val is not None and num > spec.max_val:
            if strict:
                raise ValueError(f"{spec.key} above max")
            return None
        return num
    if spec.kind == "float":
        try:
            num = float(value)
        except (TypeError, ValueError):
            if strict:
                raise ValueError(f"invalid float for {spec.key}") from None
            return None
        if spec.min_val is not None and num < spec.min_val:
            if strict:
                raise ValueError(f"{spec.key} below min")
            return None
        if spec.max_val is not None and num > spec.max_val:
            if strict:
                raise ValueError(f"{spec.key} above max")
            return None
        return num
    if spec.kind == "select":
        text = str(value).strip().lower()
        options = tuple(str(o).lower() for o in (spec.options or ()))
        if text not in options:
            if strict:
                raise ValueError(f"invalid option for {spec.key}")
            return None
        return text
    text = str(value).strip()
    if spec.key == "ingestion_model" and not text:
        return None
    return text or None


def _base_value(spec: RagSettingSpec) -> Any:
    if spec.source == "retrieval":
        return getattr(get_retrieval_settings(), spec.key)
    return getattr(get_settings(), spec.key)


def effective_value(spec: RagSettingSpec, overrides: dict[str, Any] | None = None) -> Any:
    merged = overrides if overrides is not None else get_overrides()
    if spec.key in merged:
        return merged[spec.key]
    return _base_value(spec)


def effective_settings() -> Settings:
    overrides = get_overrides()
    if not overrides:
        return get_settings()
    patch = {k: v for k, v in overrides.items() if _SPEC_BY_KEY.get(k) and _SPEC_BY_KEY[k].source == "settings"}
    if not patch:
        return get_settings()
    return get_settings().model_copy(update=patch)


def effective_retrieval_settings() -> RetrievalSettings:
    overrides = get_overrides()
    if not overrides:
        return get_retrieval_settings()
    patch = {
        k: v for k, v in overrides.items() if _SPEC_BY_KEY.get(k) and _SPEC_BY_KEY[k].source == "retrieval"
    }
    if not patch:
        return get_retrieval_settings()
    return get_retrieval_settings().model_copy(update=patch)


def pipeline_overrides_from_prefs() -> PipelineOverrides | None:
    overrides = get_overrides()
    if not overrides:
        return None
    kwargs: dict[str, Any] = {}
    for key in _PIPELINE_OVERRIDE_KEYS:
        if key not in overrides:
            continue
        kwargs[key] = overrides[key]
    if not kwargs:
        return None
    return PipelineOverrides(**kwargs)


def grouped_specs(*, advanced: bool | None = None) -> dict[str, list[RagSettingSpec]]:
    groups: dict[str, list[RagSettingSpec]] = {}
    for spec in RAG_SETTING_SPECS:
        if advanced is not None and spec.advanced != advanced:
            continue
        groups.setdefault(spec.group_ru, []).append(spec)
    return groups
