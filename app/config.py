"""
Typed configuration loaded from .env.
Separates runtime settings from retrieval settings.
"""
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve env files from the repo root, not the caller's cwd (smoke/benchmark subprocesses).
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / "config.env")   # non-secret defaults (tracked in git)
load_dotenv(BASE_DIR / ".env", override=True)  # machine secrets override defaults

_CLOUD_MODEL_PREFIXES = ("gpt-4o", "gpt-4", "claude", "gemini")
_REMOTE_PROVIDER_PREFIXES = ("openai/", "google/", "anthropic/", "deepseek/", "meta-llama/")


def is_cloud_model(model_name: str) -> bool:
    """Detect cloud-hosted models by name prefix (not substring).

    Handles bare names ("gpt-4o", "claude-3-5-sonnet") and OpenRouter-style
    provider-prefixed ids ("openai/gpt-4o", "anthropic/claude-3-5-sonnet").
    Local models with cloud-name substrings ("qwen3.6-40b-claude-4.6") are
    correctly classified as local.
    """
    m = (model_name or "").lower()
    if m.startswith(_REMOTE_PROVIDER_PREFIXES):
        return True
    local_part = m.split("/", 1)[-1] if "/" in m else m
    return any(local_part.startswith(p) for p in _CLOUD_MODEL_PREFIXES)

logger = logging.getLogger(__name__)

# Runtime data roots. По умолчанию = репозиторий (поведение как раньше);
# переопределяются env для деплоя с внешними томами. См. migration/runtime_artifacts_and_deploy.md §D.
HOME_RAG_HOME = Path(os.getenv("HOME_RAG_HOME", str(BASE_DIR)))
DATA_DIR = Path(os.getenv("HOME_RAG_DATA_DIR", str(HOME_RAG_HOME / "data")))
CHROMA_DIR = Path(os.getenv("HOME_RAG_INDEX_DIR", str(HOME_RAG_HOME / "chroma_db")))
LOG_DIR = Path(os.getenv("HOME_RAG_LOG_DIR", str(HOME_RAG_HOME / "logs")))
PROJECT_ROOT_PATH = str(BASE_DIR)

KNOWN_PROFILES = frozenset({"fast", "quality", "graph_aware"})
KNOWN_RAG_PROFILES = KNOWN_PROFILES
RAG_PROFILE_DEFAULTS = {
    "fast": {
        "retrieval_mode": "vector_only",
        "graph_augmented": False,
        "description": "Low-latency profile with smaller top-k and reranker off.",
    },
    "quality": {
        "retrieval_mode": "hybrid",
        "graph_augmented": False,
        "description": "Higher-recall profile using hybrid retrieval.",
    },
    "graph_aware": {
        "retrieval_mode": "hybrid",
        "graph_augmented": True,
        "description": "Hybrid retrieval with bounded graph augmentation when enabled.",
    },
}
KNOWN_RETRIEVAL_MODES = frozenset({"vector_only", "hybrid", "bm25_only", "doc_then_chunk"})
KNOWN_SPLIT_STRATEGIES = frozenset({"sentence_window", "sentence_splitter"})


class Settings(BaseSettings):
    """Runtime settings for providers, indexing and cache."""

    model_config = SettingsConfigDict(
        env_file=("config.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str | None = None
    home_rag_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("HOME_RAG_API_KEY", "API_KEY"),
        description="Optional API key required for protected REST endpoints when configured.",
    )
    lmstudio_api_base: str = Field(
        default="http://127.0.0.1:1234/v1",
        validation_alias=AliasChoices("LMSTUDIO_API_BASE", "LLM_API_BASE"),
    )
    openai_api_base: str = "https://openrouter.ai/api/v1"
    embed_api_base: str | None = "http://127.0.0.1:1234/v1"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def llm_api_base(self) -> str:
        """Тот же URL, что ``LMSTUDIO_API_BASE`` / ``LLM_API_BASE`` (алиас для кода и тестов)."""
        return self.lmstudio_api_base

    llm_model: str = "gpt-4o-mini"
    llamaindex_metadata_fallback_model: str = "gpt-4o-mini"
    embed_model: str = "text-embedding-qwen3-embedding-0.6b"
    embed_dimensions: int = Field(default=1024, ge=0, le=65536)
    eval_judge_llm: str | None = None
    enable_async_quality_judge: bool = False
    enable_ragas_metrics: bool = False
    async_quality_judge_sample_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    rewrite_model: str | None = None
    classifier_model: str | None = None
    # Local graph/concept LLM: concept extraction, prerequisite chains and graph summaries.
    graph_llm_api_base: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GRAPH_LLM_API_BASE"),
    )
    graph_model: str | None = Field(default=None, validation_alias=AliasChoices("GRAPH_MODEL"))
    # Генерация вопросов квиза (scoped / micro-quiz, суб-агент MicroQuizGenerator); не задана → LLM_MODEL
    quiz_llm_model: str | None = None
    # API base для quiz LLM; не задан → автоматический выбор: cloud-модель → OPENAI_API_BASE,
    # локальная → LMSTUDIO_API_BASE. Задайте явно для принудительного переопределения маршрута.
    quiz_llm_api_base: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def quiz_interactive_question_count(self) -> int:
        """5 для cloud-моделей (gpt-4o/claude/gemini) или когда QUIZ_LLM_API_BASE задан явно, иначе 3."""
        explicit = (self.quiz_llm_api_base or "").strip()
        effective = self.quiz_llm_model or self.llm_model or ""
        return 5 if bool(explicit) or is_cloud_model(effective) else 3

    # Ingestion: обогащение metadata / LLM-fallback извлечения текста; не задана → LLM_MODEL
    ingestion_model: str | None = None
    # Оценка free-form ответов inline-quiz; не задана → LLM_MODEL
    evaluate_model: str | None = None

    # ── Obsidian Export (конвертация txt → красивый Markdown конспект) ──
    # Модель для конвертации; не задана → LLM_MODEL (основная локальная).
    obsidian_export_model: str | None = None
    # Размер одного чанка текста (символы) при map-фазе обработки транскрипта.
    obsidian_export_map_chunk_chars: int = Field(default=6000, ge=500, le=32000)
    # Перекрытие между соседними чанками (символы), чтобы не рвать мысли.
    obsidian_export_map_overlap_chars: int = Field(default=300, ge=0, le=2000)
    # Порог (символы) для reduce-фазы: если общий объём тезисов ниже — пропускаем merge.
    obsidian_export_compose_input_limit: int = Field(default=12000, ge=2000, le=64000)
    # Лимит токенов для compose-вызова (финальный конспект). 4096 ≈ 6-8 страниц, достаточно.
    obsidian_export_compose_max_tokens: int = Field(default=4096, ge=1024, le=65536)
    # Таймаут одного LLM-вызова при конвертации (секунды). Compose@4096 на 15 tok/s ≈ 270s.
    # Должен быть больше HOME_RAG_LLM_LOCAL_HARD_TIMEOUT_SEC.
    obsidian_export_llm_timeout_sec: int = Field(default=600, ge=30, le=3600)
    # Universal smart-konspekt generation inputs and budgets.
    obsidian_export_prompt_path: str = "doc/prompts/smart_lecture_konspekt_universal.md"
    obsidian_export_materials_dir: str = "materials"
    smart_konspekt_transcript_budget: int = Field(default=12000, ge=1000, le=64000)
    smart_konspekt_draft_budget: int = Field(default=8000, ge=0, le=64000)
    smart_konspekt_html_budget: int = Field(default=4000, ge=0, le=64000)
    smart_konspekt_pdf_budget: int = Field(default=4000, ge=0, le=64000)
    # Имя зарегистрированного Obsidian-vault (отображается в заголовке окна Obsidian).
    # Используется для генерации obsidian://open?vault=<name>&file=<rel> ссылок.
    # Если не задано — ссылки формируются через ?path= (требует vault с тем же корнем).
    obsidian_vault_name: str | None = None
    # Подпапка внутри vault, куда пишутся сгенерированные конспекты.
    # Путь относительно BASE_DIR. По умолчанию: data (= DATA_DIR, конспект рядом с источником).
    obsidian_vault_subdir: str = "data"
    # SSR / подсказка учебного маршрута: персонализация короткой причины (отдельный endpoint и модель).
    # По умолчанию — LM Studio (OpenAI-compatible); пустая строка SSR_LLM_API_BASE → LMSTUDIO_API_BASE.
    ssr_llm_api_base: str = Field(default="")  # empty → falls through to LMSTUDIO_API_BASE
    ssr_llm_api_key: str | None = None
    # Не задано → LLM_MODEL (задайте id модели, загруженной в LM Studio)
    ssr_llm_model: str | None = None
    # Allow SSR LLM to fall back to the primary chat get_llm() when the SSR loopback endpoint
    # is unreachable. Default false: fail explicitly rather than silently routing SSR personal
    # data through primary chat (which may use cloud fallback via balanced/circuit-breaker path).
    ssr_allow_main_llm_fallback: bool = Field(
        default=False,
        validation_alias=AliasChoices("SSR_ALLOW_MAIN_LLM_FALLBACK"),
    )
    # Probe local SSR endpoint at startup (GET /v1/models) to surface "model missing"
    # warnings early and pre-warm the circuit-breaker state.
    # Set to false to skip the probe (e.g., in e2e offline mode).
    llm_local_warmup: bool = True

    # Logging infrastructure toggles. Keep these in Settings so even low-level
    # logging behavior follows the project-wide configuration contract.
    home_rag_no_log_rotate: bool = False
    home_rag_log_rotate: bool = False
    home_rag_e2e_no_log_rotate: bool = False

    llm_max_retries: int = 2
    # Таймаут чтения ответа LLM (сек.); legacy имя — общий «request» timeout для OpenAI-совместимого API.
    # Снижен с 60 до 30: без tenacity-ретраев (удалены) один тайм-аут = одна потеря, не ×3.
    # При необходимости увеличить через LLM_REQUEST_TIMEOUT=60 в .env.
    llm_request_timeout: int = 30
    # LRU-кэш LLM-запросов (дедуп flashcards/quiz и др.); переживает рестарт при persist=True.
    llm_request_cache_maxsize: int = Field(default=200, ge=10, le=2000)
    llm_request_cache_ttl_sec: int = Field(default=86400, ge=60, le=604800)
    llm_request_cache_persist: bool = Field(default=True)
    llm_request_cache_db_path: Path = Field(
        default_factory=lambda: DATA_DIR / "llm_request_cache.db",
    )
    # Параллельная генерация flashcards по документам курса (API scope=course).
    flashcard_course_parallel_workers: int = Field(default=3, ge=1, le=8)
    # UI-предупреждение при генерации по курсу с большим числом документов.
    flashcard_course_warn_documents: int = Field(default=15, ge=5, le=50)
    # Таймаут установки соединения к API (18 Core); read/write = llm_request_timeout.
    llm_connect_timeout_sec: float = Field(default=10.0, ge=1.0, le=120.0)
    # Embedding API (18 Core tail): httpx connect/read отдельно от LLM (`app/provider.get_embed_model`)
    embed_max_retries: int = 2
    embed_request_timeout: int = Field(default=60, ge=1, le=600)
    embed_connect_timeout_sec: float = Field(default=10.0, ge=1.0, le=120.0)
    # Размер батча при генерации эмбеддингов (EMBED_BATCH_SIZE).
    # Ollama CPU: 32–64; облачные API (OpenAI/OpenRouter): 256–512.
    embed_batch_size: int = Field(default=64, ge=1, le=2048)
    # Параллельные потоки для embed-запросов (EMBED_NUM_WORKERS).
    # Ollama CPU: 1–4 (ограничено CPU); облачные API: 8–16.
    embed_num_workers: int = Field(default=4, ge=1, le=32)
    # Ingest: nodes per pipeline.run() pass (INGEST_EMBED_PIPELINE_BATCH_SIZE).
    ingest_embed_pipeline_batch_size: int = Field(default=500, ge=1, le=2048)
    # Ingest: nodes per vector_store.add() flush (INGEST_STORE_BATCH_SIZE).
    # На машинах с малым RAM уменьшайте (128–256); раньше было жёстко 2000.
    ingest_store_batch_size: int = Field(default=500, ge=1, le=8192)

    # Параллельная загрузка файлов при индексации (PDF/HTML в пуле потоков).
    doc_load_num_workers: int = Field(default=8, ge=1, le=32)
    # US-2.3 phase1: сканы/изображения через Docling в общий индекс (нужен пакет docling).
    ingest_docling_enabled: bool = False
    # Если нативное извлечение PDF даёт меньше символов — считаем сканом и гоняем Docling.
    ingest_docling_min_native_text_chars: int = Field(default=48, ge=0, le=1_000_000)

    # После исчерпания retries основной модели — один вызов запасной (тот же api_base/key).
    enable_llm_fallback: bool = False
    llm_fallback_model: str | None = None
    # Лимит запросов в минуту на IP (0 = выключено). Только HTTP API, in-memory.
    api_rate_limit_per_minute: int = Field(default=0, ge=0, le=100_000)

    enable_rewrite: bool = False
    enable_classifier: bool = False
    enable_self_correction: bool = False
    # Итерация 17 Core: расширение retrieval через активный KG (synthesis / learning_plan)
    enable_graph_augmented_retrieval: bool = False
    graph_augment_max_extra_docs: int = Field(default=4, ge=0, le=64)
    # E4: сколько волн обхода prerequisites/related_concepts (multi-hop в графе концептов)
    graph_expand_max_hops: int = Field(default=3, ge=1, le=16)
    # ADR-021 Phase 2: композитный gating и качество graph evidence
    graph_augment_min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    graph_augment_baseline_thin_k: int = Field(
        default=3,
        ge=1,
        le=128,
        description="Если после dedupe узлов базового retrieval их меньше этого числа — разрешено graph expansion (quality path).",
    )
    graph_evidence_weak_threshold: float = Field(
        default=0.60,
        ge=0.0,
        le=1.0,
        description="Порог слабой evidence: ниже → weak_evidence / inferred rendering.",
    )
    graph_route_demotion_state_relative: str = Field(
        default="graph_route_demotion_state.json",
        description="Относительно DATA_DIR: persisted demotion latch для offline uplift rule (ADR-021 §9.2).",
    )
    graph_uplift_min_delta: float = Field(default=0.05, ge=0.0, le=1.0)
    graph_uplift_consecutive_runs: int = Field(default=3, ge=1, le=100)
    # Итерация 17 Core: один retry запроса при низком score источников (не tutor path)
    enable_retrieval_self_correction: bool = False
    retrieval_self_correction_min_score: float = Field(default=0.22, ge=0.0, le=1.0)
    retrieval_weak_context_disclaimer: str = (
        "Контекст по базе знаний для этого вопроса выглядит ограниченным; ниже — лучший доступный ответ "
        "на основе найденных фрагментов. Проверьте формулировку вопроса или уточните тему."
    )

    summary_collection_name: str = "home_rag_summaries"
    enable_metadata_enrichment: bool = True
    enable_document_summaries: bool = True
    # Итерация 16 tail: инкрементальная переиндексация (хэш контента + копирование векторов из active)
    enable_partial_reindex: bool = True
    # После активации новой generation (reindex/reset): очистить faq_memory.jsonl (FAQ может ссылаться на старые чанки)
    clear_faq_on_index_activation: bool = False
    # Optional ingest tail: precompute first-session artifacts after index activation.
    # Disabled by default because it can trigger several slow local LLM calls after
    # the vector index is already successfully built.
    enable_first_session_precompute: bool = False
    # Итерация 16 tail: FAQ-хранилище в Chroma (отдельная коллекция в chroma_db), не линейный скан JSONL
    faq_memory_collection_name: str = "home_rag_faq"
    # При сохранении: если ближайший сосед в FAQ ≥ порога — не добавлять дубликат (косинусная близость)
    faq_dedup_min_score: float = Field(default=0.92, ge=0.0, le=1.0)

    enable_faq_cache: bool = False
    faq_min_score: float = 0.9

    # US-3.6 / MoT#2 First Answer: двухступенчатый путь (ранний extractive vs полная генерация).
    # Критерии раннего выхода: см. `ctx.trace["answer_path"]` и описания полей ниже.
    enable_two_stage_answer_path: bool = False
    two_stage_early_exit_min_score: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Минимум max(score) по retrieved nodes для раннего выхода; иначе полный LLM-путь.",
    )
    two_stage_early_exit_min_nodes: int = Field(
        default=2,
        ge=1,
        le=32,
        description="Минимум узлов с непустым текстом для раннего выхода.",
    )
    two_stage_extractive_max_chars: int = Field(
        default=2400,
        ge=200,
        le=50_000,
        description="Верхняя граница длины склеенного extractive-ответа.",
    )
    request_context_token_budget_soft: int = Field(
        default=1_000_000,
        ge=1_000,
        le=50_000_000,
        description="Мягкий продуктовый бюджет контекста на один пользовательский запрос (документация/наблюдаемость; не жёсткий guard).",
    )

    collection_name: str = "home_rag"
    cors_origins: str = "http://127.0.0.1:8501,http://localhost:8501"
    cors_methods: str = "GET,POST,DELETE,OPTIONS"
    cors_headers: str = "Content-Type,Authorization,X-Request-ID"
    query_engine_cache_size: int = 32
    query_engine_ttl_sec: int = 1800
    guardrails_max_question_length: int = 2000
    guardrails_block_on_prompt_injection: bool = True
    guardrails_require_sources: bool = True
    guardrails_fallback_on_empty_answer: bool = True
    guardrails_fallback_on_missing_sources: bool = True
    guardrails_fallback_on_suspicious_output: bool = True
    guardrails_fallback_on_pii_detected: bool = True

    grounded_answer_contract_enabled: bool = True
    grounded_answer_strict_qa: bool = True
    grounded_answer_strict_tutor: bool = False

    fact_source_binding_enabled: bool = True

    # SLO / alerting (итерация 14): None = порог не задан (проверка отключена)
    slo_max_fallback_rate: float | None = None
    slo_min_source_coverage: float | None = None
    slo_max_p95_latency_ms: float | None = None
    # Per query_mode p95 latency thresholds in ms.
    # Example .env: SLO_LATENCY_BY_MODE='{"qa":4000,"tutor":10000}'
    slo_latency_by_mode: dict[str, float] | None = None
    slo_max_avg_cost_usd: float | None = None
    slo_min_judge_score: float | None = None
    # E5 learner migration health: допустимая доля rehydrated snapshots в окне history.
    slo_max_learner_rehydrated_rate: float | None = None
    # E5 spaced repetition discipline: cap SM-2 growth and optionally clamp low quality.
    sr_max_interval_days: int = Field(default=3650, ge=1, le=36500)
    sr_min_quality: int = Field(default=0, ge=0, le=5)
    slo_anomaly_recent_window: int = 50
    slo_anomaly_sigma: float = 2.0
    alert_webhook_url: str | None = None

    enable_otel_tracing: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    otel_exporter_otlp_headers: str | None = None
    otel_service_name: str = "home-rag"
    langfuse_trace_export_enabled: bool = False
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None

    # Observability (E14): JSONL metrics store, cost logs and dashboard SQLite.
    # Env: METRICS_STORE_PATH / METRICS_DASHBOARD_DB_PATH / LLM_COST_LOG_DIR
    metrics_store_path: Path = Field(default_factory=lambda: LOG_DIR / "metrics_store.jsonl")
    metrics_dashboard_db_path: Path = Field(default_factory=lambda: LOG_DIR / "metrics_dashboard.db")
    llm_cost_log_dir: Path = Field(default_factory=lambda: LOG_DIR / "cost_logs")
    # Профили SSR (короткая причина): JSONL для сравнения с основным LLM и отладки latency/tokens.
    ssr_llm_profile_log_dir: Path = Field(default_factory=lambda: LOG_DIR / "ssr_llm_profiles")
    enable_ssr_llm_profiling: bool = True
    feedback_path: Path = Field(default_factory=lambda: LOG_DIR / "feedback.jsonl")
    history_path: Path = Field(default_factory=lambda: LOG_DIR / "history.jsonl")
    faq_memory_path: Path = Field(default_factory=lambda: BASE_DIR / "faq_memory.jsonl")
    index_meta_path: Path = Field(default_factory=lambda: BASE_DIR / "index_meta.json")
    # Реестр поколений следует HOME_RAG_HOME (вместе с data/chroma), не корню code-репо.
    index_registry_path: Path = Field(default_factory=lambda: HOME_RAG_HOME / "index_registry.json")
    index_registry_lock_path: Path = Field(
        default_factory=lambda: HOME_RAG_HOME / "index_registry.json.lock"
    )
    active_index_state_path: Path = Field(default_factory=lambda: CHROMA_DIR / "active_index.json")

    # Локальное состояние обучения: прогресс чтения, закладки, заметки (итерация 17 ч.1)
    user_state_db: str = str(DATA_DIR / "user_state.db")

    # Квизы (scoped / self-check / micro): режим шаблона по умолчанию, если не задан явно и нет цели тьютора
    quiz_learning_mode_default: str = "default"
    home_rag_micro_quiz_offline: bool = False
    home_rag_e2e_offline: bool = False
    session_tape_debug_replay_enabled: bool = False
    session_tape_full_events_enabled: bool = False
    # E30: single-pane course cockpit в Streamlit; выкл. по умолчанию — классический tab-flow без изменений
    rag_course_cockpit_v2: bool = False

    # Offline eval / regression artifacts.
    eval_max_workers: str = "1"
    eval_baseline_json: str | None = None
    eval_output_json: str | None = None
    eval_tutor_baseline_json: str | None = None
    eval_tutor_output_json: str | None = None

    # Tutor (ит. 19.2): один ответ LLM с проверочными вопросами после маркера === QUIZ ===
    enable_tutor_inline_quiz: bool = True
    # True: основной ответ без суффикса QUIZ в промпте; блок 1–2 вопросов — второй вызов get_quiz_llm()
    tutor_inline_quiz_separate_llm_call: bool = True
    # Unified Auto-Loop: после ответа тьютора — 1–2 micro-quiz на сервере (если inline QUIZ пуст)
    enable_tutor_auto_quiz_loop: bool = True
    # Pedagogical Orchestrator 19.4: дополнительный вызов LLM до generation (JSON), влияет на socratic/quiz hints
    enable_tutor_pedagogical_orchestrator: bool = False

    # SSR Level 1 — локальный ML rerank (forgetting-curve hybrid, пакет ml-ssr-forgetting-curve-v1)
    ssr_ml_rerank_enabled: bool = False
    ssr_ml_rerank_confidence_min: float = Field(default=0.35, ge=0.0, le=1.0)
    ssr_ml_rerank_latency_budget_ms: float = Field(default=50.0, ge=0.5, le=10_000.0)
    ssr_ml_auto_enable_threshold: int = Field(default=1000, ge=0)  # 0 = bypass cold-start (always auto-enable)

    # SSR L5 — offline misroute policy tie-break (default off, ADR-005)
    ssr_misroute_policy_learning_enabled: bool = False
    ssr_misroute_policy_decay_days: int = Field(default=7, ge=1, le=90)

    # Multi-turn condense: сколько последних сообщений учитывать в промпте (анализ §4.3)
    enable_condense: bool = True
    condense_history_window: int = Field(default=8, ge=1, le=512)
    condense_history_window_tutor: int = Field(default=16, ge=1, le=512)
    # Итерация 19: верхняя граница хранимых сообщений в session store (0 = без обрезки)
    session_history_max_messages: int = Field(default=256, ge=0, le=50_000)

    # Telegram (опционально): `python telegram_bot.py` — тот же `user_state.db`, один локальный пользователь
    telegram_bot_token: str | None = None
    telegram_daily_reminder_chat_id: str | None = None
    telegram_daily_reminder_hour: int = Field(default=9, ge=0, le=23)

    # Офлайн / автономность: явный флаг UX; полный локальный LLM — задача provider.py (см. offline_service)
    offline_mode: bool = False
    offline_probe_llm_endpoint: bool = True

    # Localhost balance (primary chat LLM routing): см. doc/next/localhost_balance_course_delight_plan.md §Phase 1–2.
    home_rag_local_profile: str = Field(
        default="balanced",
        validation_alias=AliasChoices("HOME_RAG_LOCAL_PROFILE"),
        description="local_strict | balanced | cloud_fast",
    )
    home_rag_data_mode: str = Field(
        default="real",
        validation_alias=AliasChoices("HOME_RAG_DATA_MODE"),
        description="real | demo — ось источников (ортогонально LLM-профилю)",
    )
    home_rag_llm_fallback_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("HOME_RAG_LLM_FALLBACK_ENABLED"),
        description="В balanced при открытом CB на локальном endpoint — переходить на fallback primary chat.",
    )
    home_rag_llm_cloud_consent: bool = Field(
        default=False,
        validation_alias=AliasChoices("HOME_RAG_LLM_CLOUD_CONSENT"),
        description="Explicit consent to send real-data primary chat prompts to cloud fallback.",
    )
    home_rag_llm_fallback_api_base: str | None = Field(
        default=None,
        validation_alias=AliasChoices("HOME_RAG_LLM_FALLBACK_API_BASE"),
        description="OpenAI-compatible fallback base; если пусто — OPENAI_API_BASE.",
    )
    home_rag_llm_fallback_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("HOME_RAG_LLM_FALLBACK_MODEL"),
        description="Fallback model id; если пусто — LLM_FALLBACK_MODEL (при enable) или LLM_MODEL.",
    )
    home_rag_llm_local_soft_timeout_sec: float = Field(
        default=8.0,
        ge=0.5,
        le=900.0,
        validation_alias=AliasChoices("HOME_RAG_LLM_LOCAL_SOFT_TIMEOUT_SEC"),
        description="Latency banner / observability soft budget (политика latency, дополняет LLM_LOCAL_CB_*).",
    )
    home_rag_llm_local_hard_timeout_sec: float = Field(
        default=20.0,
        ge=0.5,
        le=900.0,
        validation_alias=AliasChoices("HOME_RAG_LLM_LOCAL_HARD_TIMEOUT_SEC"),
        description="Жёсткий read-timeout для локального primary chat клиента при local_strict/balanced (если уже на локале).",
    )

    # Streamlit UI: базовый URL HTTP API (тот же хост/порт, что и `uvicorn app.api:app`)
    ui_api_base_url: str = "http://127.0.0.1:8000"
    # Streamlit «Чат с тьютором»: сырой шаблон QUIZ_PROMPT и кнопка превью (только для разработки)
    show_tutor_dev_tools: bool = False

    @field_validator(
        "query_engine_cache_size",
        "query_engine_ttl_sec",
        "guardrails_max_question_length",
    )
    @classmethod
    def positive_int(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be >= 1")
        return value

    @field_validator("home_rag_local_profile", mode="before")
    @classmethod
    def normalize_home_rag_local_profile(cls, value: object) -> str:
        raw = str(value or "balanced").strip().lower().replace("-", "_")
        allowed = frozenset({"local_strict", "balanced", "cloud_fast"})
        if raw == "localhost_strict":
            raw = "local_strict"
        if raw not in allowed:
            logger.warning(
                "HOME_RAG_LOCAL_PROFILE=%r неизвестен (ожидается %s), используется balanced",
                value,
                sorted(allowed),
            )
            return "balanced"
        return raw

    @field_validator("home_rag_data_mode", mode="before")
    @classmethod
    def normalize_home_rag_data_mode(cls, value: object) -> str:
        raw = str(value or "real").strip().lower()
        allowed = frozenset({"real", "demo"})
        if raw == "sandbox":
            return "demo"
        if raw not in allowed:
            logger.warning(
                "HOME_RAG_DATA_MODE=%r неизвестен (ожидается real|demo), используется real",
                value,
            )
            return "real"
        return raw

    @field_validator("slo_latency_by_mode", mode="before")
    @classmethod
    def parse_slo_latency_by_mode(cls, value: object) -> dict[str, float] | None:
        if value is None or value == "":
            return None
        raw = json.loads(value) if isinstance(value, str) else value
        if not isinstance(raw, dict):
            raise ValueError("slo_latency_by_mode must be a JSON object")
        out: dict[str, float] = {}
        for key, threshold in raw.items():
            mode = str(key or "").strip().lower()
            if not mode:
                continue
            try:
                ms = float(threshold)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid latency SLO for query_mode={mode!r}") from exc
            if ms <= 0:
                raise ValueError("latency SLO thresholds must be > 0")
            out[mode] = ms
        return out or None

    @model_validator(mode="after")
    def guard_real_data_fallback(self) -> "Settings":
        """Block cloud primary-chat routing for real data unless explicit consent is given."""
        if (
            self.home_rag_data_mode == "real"
            and self.home_rag_llm_fallback_enabled
            and not self.home_rag_llm_cloud_consent
        ):
            raise ValueError(
                "HOME_RAG_LLM_FALLBACK_ENABLED=true with HOME_RAG_DATA_MODE=real "
                "would send private documents to a cloud provider. "
                "Set HOME_RAG_LLM_CLOUD_CONSENT=true to acknowledge this, "
                "or keep HOME_RAG_LLM_FALLBACK_ENABLED=false (recommended for real data)."
            )
        if (
            self.home_rag_data_mode == "real"
            and self.home_rag_local_profile == "cloud_fast"
            and not self.home_rag_llm_cloud_consent
        ):
            raise ValueError(
                "HOME_RAG_LOCAL_PROFILE=cloud_fast with HOME_RAG_DATA_MODE=real "
                "would send private documents to a cloud provider. "
                "Set HOME_RAG_LLM_CLOUD_CONSENT=true to acknowledge this, "
                "or use HOME_RAG_LOCAL_PROFILE=balanced/local_strict for local-first mode."
            )
        return self

    @property
    def embed_api_base_resolved(self) -> str:
        return self.embed_api_base or self.openai_api_base


class RetrievalSettings(BaseSettings):
    """Retrieval and chunking settings."""

    model_config = SettingsConfigDict(
        env_file=("config.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    rag_profile: str = "fast"
    retrieval_mode: str = "vector_only"
    similarity_top_k: int = 10
    enable_reranker: bool = True
    rerank_top_n: int = 4
    rerank_model: str = "BAAI/bge-reranker-base"
    enable_lost_in_middle_reorder: bool = True
    enable_multi_query: bool = False
    multi_query_count: int = 3
    doc_top_k: int = 5
    chunk_size: int = 700
    chunk_overlap: int = 50
    split_strategy: str = "sentence_splitter"
    window_size: int = 2

    @field_validator("chunk_size", "similarity_top_k")
    @classmethod
    def positive_int(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be >= 1")
        return value

    @field_validator("chunk_overlap", "rerank_top_n", "window_size")
    @classmethod
    def non_negative_int(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must be >= 0")
        return value

    @field_validator("multi_query_count")
    @classmethod
    def multi_query_count_in_range(cls, value: int) -> int:
        if value < 2 or value > 4:
            raise ValueError("must be between 2 and 4")
        return value

    @field_validator("rag_profile", mode="before")
    @classmethod
    def normalize_rag_profile(cls, value: str) -> str:
        raw = (value or "fast").strip().lower()
        if raw not in KNOWN_RAG_PROFILES:
            logger.warning(
                "RAG_PROFILE=%r unknown (expected %s), using fallback 'quality'",
                raw,
                sorted(KNOWN_RAG_PROFILES),
            )
            return "quality"
        return raw

    @field_validator("retrieval_mode", mode="before")
    @classmethod
    def normalize_retrieval_mode(cls, value: str) -> str:
        raw = (value or "vector_only").strip().lower()
        if raw not in KNOWN_RETRIEVAL_MODES:
            logger.warning(
                "RETRIEVAL_MODE=%r unknown (expected %s), using fallback 'vector_only'",
                raw,
                sorted(KNOWN_RETRIEVAL_MODES),
            )
            return "vector_only"
        return raw

    @field_validator("split_strategy", mode="before")
    @classmethod
    def normalize_split_strategy(cls, value: str) -> str:
        raw = (value or "sentence_splitter").strip().lower()
        if raw not in KNOWN_SPLIT_STRATEGIES:
            logger.warning(
                "SPLIT_STRATEGY=%r unknown (expected %s), using fallback 'sentence_splitter'",
                raw,
                sorted(KNOWN_SPLIT_STRATEGIES),
            )
            return "sentence_splitter"
        return raw


_settings: Settings | None = None
_retrieval_settings: RetrievalSettings | None = None


def get_settings() -> Settings:
    """Runtime settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get_retrieval_settings() -> RetrievalSettings:
    """Retrieval settings singleton."""
    global _retrieval_settings
    if _retrieval_settings is None:
        _retrieval_settings = RetrievalSettings()
    return _retrieval_settings


def reset_settings_cache() -> None:
    """Clear cached settings instances so tests can pick up fresh env overrides."""
    global _settings, _retrieval_settings
    _settings = None
    _retrieval_settings = None
