"""Мелкие хелперы UI: ошибки API, превью файлов, feedback."""
from __future__ import annotations

import html

import streamlit as st

from app.ui.constants import TEXT_PREVIEW_EXTENSIONS
from app.ui.continuity_bridge import GuidedPrimaryHomeCtaKind
from app.ui_client import fetch_json

_HOME_MODE_ROW1_SLOTS: tuple[str, ...] = ("tutor", "qa", "quiz")
_HOME_MODE_ROW2_SLOTS: tuple[str, ...] = ("flashcards", "topics", "progress")

_HOME_MODE_SLOT_TIE_INDEX: dict[str, int] = {
    **{s: i for i, s in enumerate(_HOME_MODE_ROW1_SLOTS)},
    **{s: i for i, s in enumerate(_HOME_MODE_ROW2_SLOTS)},
}

_RAG_PROFILE_LABELS: dict[str, str] = {
    "fast": "быстрый ответ",
    "quality": "точный ответ",
    "graph_aware": "ответ с учетом связей",
}

_ROUTE_REASON_LABELS: dict[str, str] = {
    "low_confidence": "система выбрала более надежный профиль",
    "graph_augmented_disabled": "режим со связями недоступен для этого запроса",
    "graph_no_uplift_below_delta": "графовый профиль временно отключён — нет подтверждённого uplift по качеству",
    "profile_deadline_exceeded": "превышен бюджет времени профиля — выбран более быстрый точный ответ",
    "uplift_gate_blocked": "графовый режим заблокирован gate качества — нужен успешный eval uplift",
    "graph_expansion_skipped": "расширение графа пропущено для этого типа запроса",
}

_DEMOTION_FALLBACK_REASONS: frozenset[str] = frozenset(
    {
        "graph_no_uplift_below_delta",
        "profile_deadline_exceeded",
        "uplift_gate_blocked",
    }
)

_GRAPH_EXPANSION_SKIP_LABELS: dict[str, str] = {
    "query_type": "тип запроса не требует расширения графа",
    "max_extra_zero": "лимит дополнительных фрагментов равен нулю",
    "empty_query": "пустой запрос",
    "empty_seed": "не найдены seed-концепты",
    "no_extra_docs": "граф не предложил дополнительные документы",
    "no_chunks_for_added_docs": "не удалось загрузить чанки для найденных документов",
}

_LLM_SOURCE_LABELS: dict[str, str] = {
    "local": "Local",
    "cloud": "Cloud",
    "cached": "Cache",
}


def esc_html(s: str) -> str:
    return html.escape(str(s or ""), quote=True)


def learner_rag_profile_label(profile: str | None) -> str | None:
    key = str(profile or "").strip().lower()
    if not key:
        return None
    return _RAG_PROFILE_LABELS.get(key, key.replace("_", " "))


def get_retrieval_routing_payload(debug: dict | None) -> dict[str, object]:
    if not isinstance(debug, dict):
        return {}
    payload = debug.get("retrieval_routing")
    if isinstance(payload, dict):
        return payload
    if "selected_profile" in debug or "effective_profile" in debug:
        return debug
    return {}


def retrieval_route_summary(debug: dict | None) -> dict[str, object]:
    routing = get_retrieval_routing_payload(debug)
    selected_profile = str(routing.get("selected_profile") or "").strip().lower()
    effective_profile = str(routing.get("effective_profile") or "").strip().lower()
    fallback_reason = str(routing.get("fallback_reason") or "").strip().lower()
    manual_override = bool(routing.get("manual_override"))
    profile_resolved_from = str(routing.get("profile_resolved_from") or "").strip().lower()

    selected_label = learner_rag_profile_label(selected_profile)
    effective_label = learner_rag_profile_label(effective_profile)
    fallback_label = _ROUTE_REASON_LABELS.get(fallback_reason, fallback_reason.replace("_", " ")) if fallback_reason else None

    return {
        "selected_profile": selected_profile or None,
        "effective_profile": effective_profile or None,
        "selected_label": selected_label,
        "effective_label": effective_label,
        "fallback_reason": fallback_reason or None,
        "fallback_label": fallback_label,
        "manual_override": manual_override,
        "profile_resolved_from": profile_resolved_from or None,
    }


def retrieval_route_summary_text(debug: dict | None) -> str | None:
    route = retrieval_route_summary(debug)
    selected = str(route.get("selected_label") or "").strip()
    effective = str(route.get("effective_label") or "").strip()
    fallback = str(route.get("fallback_label") or "").strip()
    manual_override = bool(route.get("manual_override"))

    if not selected and not effective:
        return None
    if fallback and selected and effective and selected != effective:
        return f"Почему этот маршрут: выбран профиль «{selected}», затем система перешла на «{effective}», потому что {fallback}."
    if manual_override and effective:
        return f"Почему этот маршрут: используется профиль «{effective}» по вашему выбору."
    if effective:
        return f"Почему этот маршрут: используется профиль «{effective}»."
    return f"Почему этот маршрут: используется профиль «{selected}»."


def graph_expansion_skip_reason_label(reason: str | None) -> str | None:
    key = str(reason or "").strip().lower()
    if not key:
        return None
    return _GRAPH_EXPANSION_SKIP_LABELS.get(key, key.replace("_", " "))


def retrieval_route_demotion_badge(debug: dict | None) -> str | None:
    """Compact operator chip when graph_aware was demoted to quality."""
    route = retrieval_route_summary(debug)
    selected = str(route.get("selected_profile") or "").strip().lower()
    effective = str(route.get("effective_profile") or "").strip().lower()
    fallback = str(route.get("fallback_reason") or "").strip().lower()
    if selected != "graph_aware" or effective != "quality" or fallback not in _DEMOTION_FALLBACK_REASONS:
        return None
    if fallback == "graph_no_uplift_below_delta":
        return "демotion: нет uplift"
    if fallback == "profile_deadline_exceeded":
        return "демotion: бюджет времени"
    if fallback == "uplift_gate_blocked":
        return "демotion: gate качества"
    label = str(route.get("fallback_label") or fallback).strip()
    return f"демotion: {label}" if label else None


def retrieval_route_debug_rows(debug: dict | None) -> list[tuple[str, str]]:
    route = retrieval_route_summary(debug)
    rows: list[tuple[str, str]] = []
    selected = str(route.get("selected_profile") or "").strip()
    effective = str(route.get("effective_profile") or "").strip()
    fallback = str(route.get("fallback_label") or "").strip()
    source = str(route.get("profile_resolved_from") or "").strip()

    if selected:
        rows.append(("Выбранный профиль", selected))
    if effective:
        rows.append(("Эффективный профиль", effective))
    if fallback:
        rows.append(("Причина маршрута", fallback))
    if source:
        rows.append(("Источник решения", source.replace("_", " ")))
    return rows


def _llm_source_stage(debug: dict | None) -> dict[str, object]:
    if not isinstance(debug, dict):
        return {}
    pt = debug.get("pipeline_trace") if isinstance(debug.get("pipeline_trace"), dict) else {}
    stage = pt.get("generate_stage") if isinstance(pt.get("generate_stage"), dict) else {}
    return stage


def _llm_source_pick(debug: dict | None, stage: dict[str, object], key: str) -> object:
    if isinstance(debug, dict) and debug.get(key) is not None:
        return debug.get(key)
    return stage.get(key)


def llm_source_summary(debug: dict | None) -> dict[str, object]:
    """Normalized user-facing summary of the LLM source used for an answer."""
    stage = _llm_source_stage(debug)
    source = str(_llm_source_pick(debug, stage, "llm_source") or "").strip().lower()
    if not source:
        return {
            "source": None,
            "label": None,
            "model": None,
            "api_base": None,
            "fallback_used": False,
            "profile": None,
            "latency_ms": None,
        }
    latency_raw = _llm_source_pick(debug, stage, "llm_latency_ms")
    latency_ms: float | None
    try:
        latency_ms = float(latency_raw) if latency_raw is not None else None
    except (TypeError, ValueError):
        latency_ms = None

    return {
        "source": source,
        "label": _LLM_SOURCE_LABELS.get(source, source.replace("_", " ").title()),
        "model": str(_llm_source_pick(debug, stage, "llm_model") or "").strip() or None,
        "api_base": str(_llm_source_pick(debug, stage, "llm_api_base") or "").strip() or None,
        "fallback_used": bool(_llm_source_pick(debug, stage, "fallback_used")),
        "profile": str(_llm_source_pick(debug, stage, "llm_profile") or "").strip() or None,
        "latency_ms": latency_ms,
    }


def llm_source_badge_text(debug: dict | None) -> str | None:
    summary = llm_source_summary(debug)
    label = str(summary.get("label") or "").strip()
    if not label:
        return None
    parts = [f"Источник ответа: {label}"]
    model = str(summary.get("model") or "").strip()
    profile = str(summary.get("profile") or "").strip()
    latency_ms = summary.get("latency_ms")
    if model:
        parts.append(model)
    if summary.get("fallback_used"):
        parts.append("fallback")
    if profile:
        parts.append(f"profile: {profile}")
    if latency_ms is not None:
        parts.append(f"{float(latency_ms):.1f} ms")
    return " · ".join(parts)


def llm_source_privacy_notice(debug: dict | None) -> str | None:
    summary = llm_source_summary(debug)
    if summary.get("source") != "cloud":
        return None
    return (
        "Ответ использовал cloud-модель. Для real data это допустимо только при явном "
        "HOME_RAG_LLM_CLOUD_CONSENT=true."
    )


def llm_source_debug_rows(debug: dict | None) -> list[tuple[str, str]]:
    summary = llm_source_summary(debug)
    if not summary.get("source"):
        return []
    rows: list[tuple[str, str]] = [("Источник LLM", str(summary.get("label") or "n/a"))]
    if summary.get("model"):
        rows.append(("Модель", str(summary["model"])))
    if summary.get("api_base"):
        rows.append(("API base", str(summary["api_base"])))
    if summary.get("fallback_used"):
        rows.append(("Fallback", "yes"))
    if summary.get("profile"):
        rows.append(("Профиль", str(summary["profile"])))
    if summary.get("latency_ms") is not None:
        rows.append(("Latency LLM", f"{float(summary['latency_ms']):.1f} ms"))
    return rows


_HOME_MODE_BEST_FOR: dict[str, str] = {
    "tutor": "Лучше для диалога, объяснений и пошагового плана",
    "qa": "Лучше для одного точного вопроса по вашим документам",
    "quiz": "Лучше, чтобы проверить понимание темы коротким тестом",
    "flashcards": "Лучше для интервальных повторений и закрепления фактов",
    "topics": "Лучше выбрать тему, синтез и учебный маршрут",
    "progress": "Лучше видеть mastery, streak и ближайшие цели",
}

_HOME_MODE_PREVIEW: dict[str, list[str]] = {
    "tutor": [
        "Вы попадёте в диалог с тьютором: объяснения, микро-квиз и подсказки по вашим документам.",
        "Маршрут: вкладка «Чат с тьютором».",
    ],
    "qa": [
        "Быстрый ответ по базе знаний с указанием источников в материалах.",
        "Маршрут: вкладка «Быстрый ответ».",
    ],
    "quiz": [
        "Короткая проверка знаний по выбранной теме или документу.",
        "Маршрут: вкладка «Интерактивный Quiz».",
    ],
    "flashcards": [
        "Режим интервальных повторений по вашим колодам.",
        "Маршрут: вкладка «Flashcards». Текущее состояние очереди см. строками под карточкой.",
    ],
    "topics": [
        "Каталог тем, синтез и связка с учебным маршрутом.",
        "Маршрут: вкладка «Темы».",
    ],
    "progress": [
        "Mastery, цели, streak и граф прогресса по материалам.",
        "Маршрут: вкладка «Прогресс обучения».",
    ],
}


def home_mode_best_for_line(slot: str) -> str:
    """Короткий intent-сублайн под карточкой режима (MoT #13 Home mode selection)."""
    return _HOME_MODE_BEST_FOR.get(str(slot or "").strip(), "")


def home_mode_preview_lines(slot: str) -> list[str]:
    """Текст для блока предпросмотра (MoT #13 preview drawer / disclosure)."""
    key = str(slot or "").strip()
    return list(_HOME_MODE_PREVIEW.get(key, []))


def home_mode_intent_row_orders(
    *,
    cta_kind: GuidedPrimaryHomeCtaKind,
    flashcard_due_n: int = 0,
    due_n: int = 0,
    has_tutor_resume: bool = False,
    has_mastery_gap: bool = False,
    has_handoff_topic: bool = False,
    last_primary_slot: str | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Детерминированный порядок слотов по строкам сетки 2×3 (MoT #13 intent ordering).

    Primary CTA (US-14.1) остаётся отдельным виджетом выше сетки; здесь только
    переупорядочивание шести карточек по контексту (due, resume, mastery gap,
    последний выбранный режим).
    """
    scores: dict[str, int] = {s: 0 for s in _HOME_MODE_SLOT_TIE_INDEX}

    if cta_kind == "flashcard_due":
        scores["flashcards"] += 180
    elif cta_kind == "due_review":
        scores["progress"] += 180
    elif cta_kind == "resume":
        scores["tutor"] += 180
    elif cta_kind == "mastery_gap":
        scores["topics"] += 180
    else:
        scores["tutor"] += 70
        scores["qa"] += 55
        scores["quiz"] += 40

    if flashcard_due_n > 0:
        scores["flashcards"] += 35 + min(25, flashcard_due_n * 2)
    if due_n > 0:
        scores["progress"] += 30
        if cta_kind != "due_review":
            scores["progress"] += 12
    if has_tutor_resume:
        scores["tutor"] += 28
        if cta_kind != "resume":
            scores["tutor"] += 14
    if has_mastery_gap:
        scores["topics"] += 28
        if cta_kind != "mastery_gap":
            scores["topics"] += 12
    if has_handoff_topic:
        scores["tutor"] += 18
        scores["qa"] += 14

    last = str(last_primary_slot or "").strip()
    if last in scores:
        scores[last] += 20

    def _sort_row(slots: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            sorted(
                slots,
                key=lambda s: (-scores.get(s, 0), _HOME_MODE_SLOT_TIE_INDEX[s]),
            )
        )

    return _sort_row(_HOME_MODE_ROW1_SLOTS), _sort_row(_HOME_MODE_ROW2_SLOTS)


def format_request_error(error: Exception) -> str:
    response = getattr(error, "response", None)
    if response is None:
        return str(error)
    try:
        data = response.json()
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        return str(error)
    detail = data.get("detail")
    if detail:
        return str(detail)
    return str(error)


def ask_failure_recovery_hint_from_exception(error: Exception) -> str:
    """E9.7 / US-1.3: одна строка «что сделать» после сбоя запроса к API."""
    from app.ui.continuity_bridge import ask_failure_recovery_hint_ru

    return ask_failure_recovery_hint_ru(format_request_error(error))


def show_file_error(prefix: str, error: Exception) -> None:
    message = format_request_error(error)
    st.error(f"{prefix}: {message}")
    if "переиндексац" in message.lower() or "устарел" in message.lower():
        st.info("Путь к файлу мог устареть после изменений в `data/`. При необходимости выполните переиндексацию.")


def supports_text_preview(relative_path: str) -> bool:
    return relative_path.lower().endswith(TEXT_PREVIEW_EXTENSIONS)


def preview_code_language(relative_path: str) -> str | None:
    low = relative_path.lower()
    if low.endswith(".md"):
        return "markdown"
    if low.endswith(".html"):
        return "html"
    if low.endswith(".txt"):
        return "text"
    if low.endswith(".pdf"):
        return "text"
    if low.endswith(".docx"):
        return "text"
    return None


def post_feedback(
    *,
    helpful: bool,
    request_id: str | None,
    question_preview: str | None,
) -> bool:
    try:
        fetch_json(
            "POST",
            "/feedback",
            timeout=5,
            json={
                "helpful": helpful,
                "request_id": request_id,
                "question_preview": (question_preview or "")[:240],
                "source": "ui",
            },
        )
        return True
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        return False


def build_tutor_action_items(
    ctas: list[str] | None,
    *,
    next_action: str | None = None,
    due_reviews_count: int = 0,
) -> list[dict[str, str]]:
    """Prepare user-facing Tutor CTA buttons from backend actions."""
    prompt_aliases = {
        "Нужен пример": "Дай пример",
        "Понял": (next_action or "").strip() or "Следующий шаг",
    }
    label_aliases = {
        "Дай пример": "Нужен пример",
    }
    default_prompts = [
        "Объясни проще",
        "Дай пример",
        "Проверь меня",
        "Следующий шаг",
    ]
    prompts = [str(item).strip() for item in (ctas or []) if str(item).strip()]
    resolved_next_action = str(next_action or "").strip()
    if resolved_next_action and resolved_next_action not in prompts:
        prompts.insert(0, resolved_next_action)
    if not prompts:
        prompts = list(default_prompts)
    if due_reviews_count > 0 and "Пора повторить" not in prompts:
        prompts = ["Пора повторить"] + prompts[:7]

    items: list[dict[str, str]] = []
    seen_labels: set[str] = set()

    def _push(label: str, prompt: str) -> None:
        clean_label = str(label or "").strip()
        clean_prompt = str(prompt or "").strip()
        if not clean_label or not clean_prompt or clean_label in seen_labels:
            return
        items.append({"label": clean_label, "prompt": clean_prompt})
        seen_labels.add(clean_label)

    if resolved_next_action and resolved_next_action not in {"Проверь меня", "Пора повторить"}:
        _push("Понял", resolved_next_action)

    for prompt in prompts[:8]:
        label = label_aliases.get(prompt, prompt)
        _push(label, prompt_aliases.get(label, prompt))

    return items


def build_tutor_orchestration_summary(
    *,
    orchestration_state: dict | None,
    decision: dict | None = None,
    socratic: dict | None = None,
    tutor_orchestration_pipeline: dict | None = None,
    orchestration_phase: str | None = None,
    orchestration_decision_source: str | None = None,
    selected_agent: str | None = None,
    should_trigger_microquiz: bool | None = None,
    policy_clamped: bool | None = None,
    policy_clamp_reasons: list[str] | None = None,
) -> list[dict[str, str]]:
    """Prepare a compact user-facing tutor orchestration summary for UI surfaces."""
    state = orchestration_state if isinstance(orchestration_state, dict) else {}
    route_decision = decision if isinstance(decision, dict) else {}
    soc = socratic if isinstance(socratic, dict) else {}
    pipe = tutor_orchestration_pipeline if isinstance(tutor_orchestration_pipeline, dict) else {}

    route = str(route_decision.get("route") or "").strip().replace("_", " ")
    focus = str(state.get("current_concept") or route_decision.get("focus_topic") or "").strip()
    mastery = str(state.get("mastery_estimate") or "").strip()
    recommended = str(state.get("recommended_action") or "").strip()
    prerequisite_gap = str(state.get("prerequisite_gap") or "").strip()
    socratic_type = str(soc.get("question_type") or "").strip().replace("_", " ")
    needs_review = bool(state.get("needs_review"))

    out: list[dict[str, str]] = []
    if route:
        out.append({"label": "Маршрут", "value": route})
    if focus:
        out.append({"label": "Фокус", "value": focus})
    if mastery:
        out.append({"label": "Mastery", "value": mastery})
    if recommended:
        out.append({"label": "Рекомендация", "value": recommended})
    if prerequisite_gap:
        out.append({"label": "Пробел", "value": prerequisite_gap})
    if needs_review:
        out.append({"label": "Повторение", "value": "есть due review"})
    if socratic_type:
        out.append({"label": "Socratic", "value": socratic_type})

    phase = str(
        orchestration_phase
        or pipe.get("phase")
        or state.get("orchestration_phase")
        or ""
    ).strip()
    if phase:
        out.append({"label": "Фаза пайплайна", "value": phase.replace("_", " ")})
    ds = str(
        orchestration_decision_source
        or pipe.get("decision_source")
        or state.get("orchestration_decision_source")
        or ""
    ).strip()
    if ds:
        out.append({"label": "Источник решения", "value": ds.replace("_", " ")})
    agent = str(
        selected_agent
        or pipe.get("selected_agent")
        or state.get("selected_agent")
        or ""
    ).strip()
    if agent:
        out.append({"label": "Агент", "value": agent.replace("_", " ")})
    if should_trigger_microquiz is not None:
        out.append(
            {
                "label": "Micro-quiz",
                "value": "да" if should_trigger_microquiz else "нет",
            }
        )
    elif "should_trigger_microquiz" in pipe:
        out.append(
            {
                "label": "Micro-quiz",
                "value": "да" if bool(pipe.get("should_trigger_microquiz")) else "нет",
            }
        )
    elif "should_trigger_microquiz" in state:
        out.append(
            {
                "label": "Micro-quiz",
                "value": "да" if bool(state.get("should_trigger_microquiz")) else "нет",
            }
        )

    clamped = (
        policy_clamped
        if policy_clamped is not None
        else pipe.get("policy_clamped")
        if "policy_clamped" in pipe
        else state.get("policy_clamped")
    )
    if clamped:
        pr = policy_clamp_reasons
        if pr is None:
            pr_raw = pipe.get("policy_clamp_reasons")
            if not isinstance(pr_raw, list):
                pr_raw = state.get("policy_clamp_reasons")
            pr = pr_raw if isinstance(pr_raw, list) else None
        rs = (
            ", ".join(str(x) for x in pr if str(x).strip())
            if pr
            else "да"
        )
        out.append({"label": "Policy clamp", "value": rs})

    return out
