import logging
import time
from typing import Optional

from llama_index.core.postprocessor import MetadataReplacementPostProcessor
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters

from app.config import get_retrieval_settings
from app.config import RetrievalSettings
from app.logging_config import log_event, setup_logging
from app.models import PipelineOverrides, QueryOptions
from app.prompts import KEYWORD_PROMPT, QA_PROMPT

logger = setup_logging()


def build_filters(options: QueryOptions):
    filters = []

    # Существующие файловые фильтры (обратная совместимость)
    if options.folder:
        filters.append(MetadataFilter(key="folder_name", value=options.folder))

    if options.folder_rel:
        filters.append(MetadataFilter(key="folder_rel", value=options.folder_rel))

    if options.file_name:
        filters.append(MetadataFilter(key="file_name", value=options.file_name))

    if options.relative_path:
        filters.append(MetadataFilter(key="relative_path", value=options.relative_path))

    # Новые семантические фильтры Итерации 11
    if options.topic:
        filters.append(MetadataFilter(key="topic", value=options.topic))

    if options.logical_folder:
        filters.append(MetadataFilter(key="folder", value=options.logical_folder))

    if options.file:
        filters.append(MetadataFilter(key="file", value=options.file))

    if not filters:
        return None

    return MetadataFilters(filters=filters)


def resolve_pipeline_params(
    overrides: Optional[PipelineOverrides] = None,
    retrieval_settings: Optional[RetrievalSettings] = None,
) -> dict:
    """Собрать параметры пайплайна из retrieval-настроек и опциональных overrides."""
    r = retrieval_settings if retrieval_settings is not None else get_retrieval_settings()
    profile = (r.rag_profile or "fast").strip().lower() or "fast"
    if overrides is not None and overrides.rag_profile is not None:
        profile = overrides.rag_profile

    retrieval_mode = getattr(r, "retrieval_mode", "vector_only") or "vector_only"

    if profile == "fast":
        params = {
            "profile": profile,
            "retrieval_mode": retrieval_mode,
            "similarity_top_k": min(r.similarity_top_k, 2),
            "enable_reranker": False,
            "rerank_top_n": r.rerank_top_n,
            "rerank_model": r.rerank_model,
            "split_strategy": "sentence_window",
            "window_size": r.window_size,
        }
    else:
        params = {
            "profile": profile,
            "retrieval_mode": retrieval_mode,
            "similarity_top_k": r.similarity_top_k,
            "enable_reranker": r.enable_reranker,
            "rerank_top_n": r.rerank_top_n,
            "rerank_model": r.rerank_model,
            "split_strategy": r.split_strategy,
            "window_size": r.window_size,
            "doc_top_k": getattr(r, "doc_top_k", 5),
        }

    if overrides is None:
        return params

    if overrides.similarity_top_k is not None:
        params["similarity_top_k"] = overrides.similarity_top_k
    if overrides.enable_reranker is not None:
        params["enable_reranker"] = overrides.enable_reranker
    if overrides.rerank_top_n is not None:
        params["rerank_top_n"] = overrides.rerank_top_n
    if overrides.rerank_model is not None:
        params["rerank_model"] = overrides.rerank_model
    if overrides.split_strategy is not None:
        params["split_strategy"] = overrides.split_strategy
    if overrides.window_size is not None:
        params["window_size"] = overrides.window_size
    if overrides.retrieval_mode is not None:
        params["retrieval_mode"] = overrides.retrieval_mode

    return params


def build_postprocessors(params: dict):
    postprocessors = []

    if params["split_strategy"] == "sentence_window":
        postprocessors.append(
            MetadataReplacementPostProcessor(target_metadata_key="window")
        )

    if not params["enable_reranker"]:
        logger.info("FlagEmbeddingReranker disabled by resolved pipeline config")
        return postprocessors

    try:
        from llama_index.postprocessor.flag_embedding_reranker import FlagEmbeddingReranker

        init_started = time.perf_counter()
        reranker = FlagEmbeddingReranker(
            top_n=params["rerank_top_n"],
            model=params["rerank_model"],
        )
        reranker_init_ms = round((time.perf_counter() - init_started) * 1000, 3)
        postprocessors.append(reranker)
        log_event(
            logger,
            logging.INFO,
            "reranker_init_completed",
            reranker_init_ms=reranker_init_ms,
            rerank_model=params["rerank_model"],
            rerank_top_n=params["rerank_top_n"],
        )
        logger.info(
            "FlagEmbeddingReranker enabled | model=%s | rerank_top_n=%s | reranker_init_ms=%s",
            params["rerank_model"],
            params["rerank_top_n"],
            reranker_init_ms,
        )
    except Exception as e:
        logger.warning("FlagEmbeddingReranker disabled due to error: %s", e)

    return postprocessors


def build_tutor_pipeline():
    """Список шагов tutor 19.4 после ``build_tutor_session_state`` в ``query_service``.

    Каждый шаг: ``QueryContext -> QueryContext`` (совместимо с ``run_step_safe``).
    Не включает classify/condense/rewrite (они в ``pipeline_runner.run_pipeline``)
    и не включает retrieval/generation (``build_query_engine`` + ``engine.query``).
    """
    from app.pipeline_steps import (
        execute_specialized_agent_step,
        orchestrate_pedagogical_action_step,
        self_correction_and_compose_step,
    )

    return [
        orchestrate_pedagogical_action_step,
        execute_specialized_agent_step,
        self_correction_and_compose_step,
    ]


# ``app.orchestrator_router.PedagogicalRouter`` — отдельный dict/state API (graph-augmented
# + опциональные LLM-агенты). Не подставлять вместо списка выше без замены RAG: см. документацию
# класса и ``invoke_pedagogical_orchestrator_llm`` в ``tutor_orchestrator``.
