"""Product scenarios layered on top of the generic read-only agent loop.

Wave 1A ships the first scenario: a short study session coach. The scenario
does not call services directly and does not write state; it only supplies a
specialized system prompt and a final-answer contract over the runner trace.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.contracts import AgentStep
from app.prompts._impl import (
    AGENT_GRAPH_GAP_FINDER_SYSTEM_PROMPT,
    AGENT_LIVING_KONSPEKT_COACH_SYSTEM_PROMPT,
    AGENT_STUDY_SESSION_SYSTEM_PROMPT,
)


_STUDY_SESSION_HEADINGS = (
    "## Диагностика",
    "## Что изучать сейчас",
    "## План на 10–20 минут",
    "## Проверочные вопросы",
    "## Следующие шаги",
)

_GRAPH_GAP_HEADINGS = (
    "## Карта пробелов",
    "## Цепочка prerequisites",
    "## Почему это мешает",
    "## Рекомендуемый порядок",
    "## Практическая проверка",
)

_GRAPH_GAP_INTENT_MARKERS = (
    "graph gap",
    "gap finder",
    "prerequisite",
    "prerequisites",
    "knowledge graph",
    "граф",
    "пробел",
    "пробелы",
    "что мешает",
    "что учить дальше",
    "что подтянуть",
    "предпосыл",
)

_KONSPEKT_HEADINGS = (
    "## Состояние конспекта",
    "## Что добавить или уточнить",
    "## Что повторить",
    "## Проверка понимания",
    "## Draft-карточки",
    "## Следующий шаг",
)

_KONSPEKT_INTENT_MARKERS = (
    "living konspekt",
    "konspekt",
    "workbench",
    "конспект",
    "живой конспект",
    "корзин",
    "заметки",
    "что добавить",
    "что повторить",
)


@dataclass(frozen=True)
class StudySessionResult:
    """Normalized study-session draft returned by the scenario finalizer."""

    answer: str
    has_sources: bool
    weak_data: bool


@dataclass(frozen=True)
class GraphGapReport:
    """Normalized graph-gap draft returned by the scenario finalizer."""

    answer: str
    has_sources: bool
    weak_data: bool


@dataclass(frozen=True)
class KonspektCoachDraft:
    """Normalized Living Konspekt coach draft returned by the finalizer."""

    answer: str
    has_sources: bool
    weak_data: bool


@dataclass(frozen=True)
class AgentScenario:
    """Small scenario contract consumed by :class:`app.agent.runner.AgentRunner`."""

    scenario_id: str
    system_prompt: str
    finalize_answer: Any


def detect_konspekt_coach_intent(question: str) -> bool:
    """Detect requests about Living Konspekt / workbench coaching."""
    text = (question or "").strip().lower()
    return any(marker in text for marker in _KONSPEKT_INTENT_MARKERS)


def detect_graph_gap_intent(question: str) -> bool:
    """Detect requests that ask for graph/prerequisite gap navigation."""
    text = (question or "").strip().lower()
    return any(marker in text for marker in _GRAPH_GAP_INTENT_MARKERS)


def detect_study_session_intent(question: str) -> bool:
    """Wave 1A routes every non-empty agent request to the study session.

    Later waves can split this into multiple scenario detectors. For now,
    agent mode is intentionally productized as "study session coach" rather
    than exposed as a generic autonomous agent.
    """
    return bool((question or "").strip())


def get_agent_scenario(question: str) -> AgentScenario | None:
    """Return the scenario for an agent request, if any."""
    if detect_konspekt_coach_intent(question):
        return LIVING_KONSPEKT_COACH_SCENARIO
    if detect_graph_gap_intent(question):
        return GRAPH_GAP_FINDER_SCENARIO
    if detect_study_session_intent(question):
        return STUDY_SESSION_SCENARIO
    return None


def finalize_study_session_answer(
    answer: str,
    sources: list[dict[str, Any]],
    steps: list[AgentStep],
) -> str:
    """Return only the normalized answer text for runner integration."""
    return build_study_session_answer(answer, sources, steps).answer


def finalize_graph_gap_answer(
    answer: str,
    sources: list[dict[str, Any]],
    steps: list[AgentStep],
) -> str:
    """Return only the normalized graph-gap report for runner integration."""
    return build_graph_gap_report(answer, sources, steps).answer


def finalize_konspekt_coach_answer(
    answer: str,
    sources: list[dict[str, Any]],
    steps: list[AgentStep],
) -> str:
    """Return only the normalized konspekt-coach draft for runner integration."""
    return build_konspekt_coach_draft(answer, sources, steps).answer


def build_study_session_answer(
    answer: str,
    sources: list[dict[str, Any]],
    steps: list[AgentStep],
) -> StudySessionResult:
    """Normalize a final answer to the Wave 1A study-session structure.

    This is deliberately conservative: if the LLM already followed the
    scenario contract, keep its text and only append a sources section when RAG
    was used. If it did not, compose a useful fallback from tool results.
    """
    text = (answer or "").strip()
    source_labels = _source_labels(sources)
    rag_was_used = _rag_was_used(steps)

    if _has_required_study_sections(text):
        normalized = _ensure_study_extensions(
            text,
            source_labels=source_labels,
            rag_was_used=rag_was_used,
            steps=steps,
        )
        return StudySessionResult(
            answer=normalized,
            has_sources=bool(source_labels),
            weak_data=rag_was_used and not source_labels,
        )

    fallback = _compose_study_session_fallback(
        answer=text,
        source_labels=source_labels,
        rag_was_used=rag_was_used,
        steps=steps,
    )
    return StudySessionResult(
        answer=fallback,
        has_sources=bool(source_labels),
        weak_data=rag_was_used and not source_labels,
    )


def build_graph_gap_report(
    answer: str,
    sources: list[dict[str, Any]],
    steps: list[AgentStep],
) -> GraphGapReport:
    """Normalize a final answer to the Wave 1B graph-gap structure."""
    text = (answer or "").strip()
    source_labels = _source_labels(sources)
    rag_was_used = _rag_was_used(steps)
    weak_data = not _graph_was_used(steps)

    if _has_required_graph_sections(text):
        normalized = _ensure_sources_section(text, source_labels, rag_was_used)
        return GraphGapReport(
            answer=normalized,
            has_sources=bool(source_labels),
            weak_data=weak_data,
        )

    fallback = _compose_graph_gap_fallback(
        answer=text,
        source_labels=source_labels,
        rag_was_used=rag_was_used,
        steps=steps,
    )
    return GraphGapReport(
        answer=fallback,
        has_sources=bool(source_labels),
        weak_data=weak_data,
    )


def build_konspekt_coach_draft(
    answer: str,
    sources: list[dict[str, Any]],
    steps: list[AgentStep],
) -> KonspektCoachDraft:
    """Normalize a final answer to the Wave 1C Living Konspekt structure."""
    text = (answer or "").strip()
    source_labels = _source_labels(sources)
    rag_was_used = _rag_was_used(steps)
    weak_data = not _konspekt_was_used(steps) or _konspekt_is_empty(steps)

    if _has_required_konspekt_sections(text):
        normalized = _ensure_sources_section(text, source_labels, rag_was_used)
        return KonspektCoachDraft(
            answer=normalized,
            has_sources=bool(source_labels),
            weak_data=weak_data,
        )

    fallback = _compose_konspekt_coach_fallback(
        answer=text,
        source_labels=source_labels,
        rag_was_used=rag_was_used,
        steps=steps,
    )
    return KonspektCoachDraft(
        answer=fallback,
        has_sources=bool(source_labels),
        weak_data=weak_data,
    )


def _has_required_study_sections(answer: str) -> bool:
    return all(heading in answer for heading in _STUDY_SESSION_HEADINGS)


def _has_required_graph_sections(answer: str) -> bool:
    return all(heading in answer for heading in _GRAPH_GAP_HEADINGS)


def _has_required_konspekt_sections(answer: str) -> bool:
    return all(heading in answer for heading in _KONSPEKT_HEADINGS)


def _ensure_study_extensions(
    answer: str,
    *,
    source_labels: list[str],
    rag_was_used: bool,
    steps: list[AgentStep],
) -> str:
    out = answer
    if "## Карточки-кандидаты" not in out:
        candidates = _card_candidates(steps)
        if candidates:
            out = f"{out.rstrip()}\n\n## Карточки-кандидаты\n" + "\n".join(
                f"- {candidate}" for candidate in candidates[:7]
            )
    return _ensure_sources_section(out, source_labels, rag_was_used)


def _ensure_sources_section(
    answer: str,
    source_labels: list[str],
    rag_was_used: bool,
) -> str:
    if not rag_was_used or "## Источники" in answer:
        return answer
    if source_labels:
        return f"{answer.rstrip()}\n\n## Источники\n" + "\n".join(
            f"- [{label}]" for label in source_labels
        )
    return (
        f"{answer.rstrip()}\n\n## Источники\n"
        "- Источники не найдены в доступной базе знаний."
    )


def _compose_study_session_fallback(
    *,
    answer: str,
    source_labels: list[str],
    rag_was_used: bool,
    steps: list[AgentStep],
) -> str:
    topic = _topic_from_steps(steps)
    material = _best_material_summary(answer, steps)
    profile_hint = _profile_hint(steps)
    mastery_hint = _mastery_hint(steps)
    quiz_questions = _quiz_questions(steps)
    card_candidates = _card_candidates(steps)

    if material:
        diagnosis = (
            f"Есть рабочий материал по теме{_topic_suffix(topic)}. "
            f"{profile_hint or 'Профиль ученика учтен, если он был доступен.'} "
            f"{mastery_hint or 'Явных данных о пробелах может быть недостаточно.'}"
        )
        focus = material
    else:
        diagnosis = (
            f"Данных по теме{_topic_suffix(topic)} пока недостаточно: "
            "инструменты не вернули надежный материал для объяснения."
        )
        focus = (
            "Уточните тему одним предложением или добавьте материалы в базу знаний. "
            "Пока можно начать с формулировки цели: что именно нужно понять, "
            "решить или повторить."
        )

    lines = [
        "## Диагностика",
        diagnosis.strip(),
        "",
        "## Что изучать сейчас",
        f"- {focus.strip()}",
        "",
        "## План на 10–20 минут",
        "1. За 3–5 минут сформулируйте тему своими словами.",
        "2. За 7–10 минут разберите найденный материал и выпишите 2–3 ключевых тезиса.",
        "3. За 3–5 минут проверьте себя вопросами ниже.",
        "",
        "## Проверочные вопросы",
        *_numbered_or_default(
            quiz_questions,
            [
                f"Как бы вы объяснили тему{_topic_suffix(topic)} своими словами?",
                "Какой главный тезис или правило стоит запомнить?",
                "Где можно применить это знание на коротком примере?",
            ],
        ),
        "",
        "## Карточки-кандидаты",
        *_bulleted_or_default(
            card_candidates,
            [
                f"Draft: ключевое определение по теме{_topic_suffix(topic)}",
                "Draft: главный пример или правило из найденного материала",
                "Draft: типичная ошибка, которую стоит не повторить",
            ],
        ),
        "",
        "## Следующие шаги",
        "Повторите слабые места, затем попросите агента собрать более узкую сессию "
        "по одному непонятному подпункту.",
    ]

    if rag_was_used:
        lines.extend(["", "## Источники"])
        if source_labels:
            lines.extend(f"- [{label}]" for label in source_labels)
        else:
            lines.append("- Источники не найдены в доступной базе знаний.")

    return "\n".join(lines).strip()


def _compose_graph_gap_fallback(
    *,
    answer: str,
    source_labels: list[str],
    rag_was_used: bool,
    steps: list[AgentStep],
) -> str:
    topic = _topic_from_steps(steps)
    graph_summary = _graph_summary(steps)
    prereqs = _graph_prerequisites(steps)
    weak = _weak_concepts(steps)
    material = _best_material_summary(answer, steps)

    gaps = weak or prereqs or ([topic] if topic else [])
    if not gaps:
        gaps = ["Недостаточно данных графа, чтобы надежно выделить пробелы"]

    lines = [
        "## Карта пробелов",
        *_bulleted_or_default(gaps[:5], ["Недостаточно данных графа"]),
        "",
        "## Цепочка prerequisites",
        _chain_text(prereqs, topic),
        "",
        "## Почему это мешает",
        (
            graph_summary
            or material
            or "Связь между пробелами и текущей темой пока видна неполно: "
            "нужно уточнить тему или наполнить граф/прогресс данными."
        ),
        "",
        "## Рекомендуемый порядок",
        *_numbered_or_default(
            prereqs or gaps,
            [
                "Уточнить текущую тему и найти ее узел в графе.",
                "Закрыть ближайший prerequisite.",
                "Вернуться к теме и пройти короткую проверку.",
            ],
        ),
        "",
        "## Практическая проверка",
        "1. Какой prerequisite сильнее всего мешает текущей теме?",
        "2. Как понять, что этот пробел закрыт?",
        "3. Какой следующий узел графа станет доступнее после повторения?",
    ]

    if rag_was_used:
        lines.extend(["", "## Источники"])
        if source_labels:
            lines.extend(f"- [{label}]" for label in source_labels)
        else:
            lines.append("- Источники не найдены в доступной базе знаний.")

    return "\n".join(lines).strip()


def _compose_konspekt_coach_fallback(
    *,
    answer: str,
    source_labels: list[str],
    rag_was_used: bool,
    steps: list[AgentStep],
) -> str:
    topic = _topic_from_steps(steps)
    rows = _konspekt_rows(steps)
    total_rows = _konspekt_total_rows(steps)
    material = _best_material_summary(answer, steps)
    quiz_questions = _quiz_questions(steps)
    card_candidates = _card_candidates(steps)
    graph_summary = _graph_summary(steps)

    if total_rows is None:
        state = (
            "Данных о текущем конспекте пока нет: konspekt.inspect не вернул "
            "надежное состояние."
        )
    elif total_rows == 0:
        state = "Текущий конспект пуст: выбранных rows или разделов пока нет."
    else:
        titles = [row for row in rows[:5]]
        title_text = ", ".join(titles) if titles else "названия разделов не указаны"
        state = f"В конспекте найдено rows: {total_rows}. Видимые разделы: {title_text}."

    add_or_refine = material or graph_summary or (
        "Добавьте 1–2 коротких тезиса к каждому выбранному разделу и отметьте, "
        "какой источник подтверждает ключевую мысль."
    )

    repeat_items = rows[:4] or ([topic] if topic else [])
    if not repeat_items:
        repeat_items = ["Цель конспекта", "Первый ключевой термин", "Связь с источником"]

    lines = [
        "## Состояние конспекта",
        state,
        "",
        "## Что добавить или уточнить",
        f"- Draft: {add_or_refine}",
        "- Draft: проверьте, есть ли у каждого важного тезиса источник.",
        "",
        "## Что повторить",
        *_bulleted_or_default(repeat_items[:4], ["Цель конспекта"]),
        "",
        "## Проверка понимания",
        *_numbered_or_default(
            quiz_questions,
            [
                "Какой главный тезис уже есть в конспекте?",
                "Какого источника или примера сейчас не хватает?",
                "Что вы сможете объяснить по конспекту за одну минуту?",
            ],
        ),
        "",
        "## Draft-карточки",
        *_bulleted_or_default(
            card_candidates,
            [
                "Draft: главный термин из конспекта",
                "Draft: связь тезиса с источником",
                "Draft: пример применения ключевой идеи",
            ],
        ),
        "",
        "## Следующий шаг",
        "За 5–15 минут выберите один раздел конспекта, добавьте к нему короткий "
        "тезис и один проверочный вопрос. Ничего не сохраняется автоматически.",
    ]

    if rag_was_used:
        lines.extend(["", "## Источники"])
        if source_labels:
            lines.extend(f"- [{label}]" for label in source_labels)
        else:
            lines.append("- Источники не найдены в доступной базе знаний.")

    return "\n".join(lines).strip()


def _topic_from_steps(steps: list[AgentStep]) -> str:
    for step in steps:
        args = step.tool_args or {}
        for key in ("query", "topic"):
            value = str(args.get(key) or "").strip()
            if value:
                return value
    return ""


def _topic_suffix(topic: str) -> str:
    return f" «{topic}»" if topic else ""


def _best_material_summary(answer: str, steps: list[AgentStep]) -> str:
    if answer:
        return _truncate(answer, 700)

    for step in reversed(steps):
        result = step.tool_result
        if not result or not result.ok:
            continue
        data = result.data if isinstance(result.data, dict) else {}
        if step.tool_name == "rag.answer":
            rag_answer = str(data.get("answer") or "").strip()
            if rag_answer:
                return _truncate(rag_answer, 700)
        if step.tool_name == "rag.search":
            chunks = data.get("chunks") or []
            for chunk in chunks:
                if isinstance(chunk, dict):
                    text = str(chunk.get("text") or "").strip()
                    if text:
                        return _truncate(text, 700)
    return ""


def _quiz_questions(steps: list[AgentStep]) -> list[str]:
    questions: list[str] = []
    for step in steps:
        if step.tool_name != "quiz.generate":
            continue
        result = step.tool_result
        data = result.data if result and isinstance(result.data, dict) else {}
        for item in data.get("questions") or []:
            if isinstance(item, dict):
                text = str(
                    item.get("question")
                    or item.get("text")
                    or item.get("prompt")
                    or ""
                ).strip()
            else:
                text = str(item or "").strip()
            if text:
                questions.append(text)
    return questions[:4]


def _card_candidates(steps: list[AgentStep]) -> list[str]:
    candidates: list[str] = []
    for step in steps:
        if step.tool_name != "cards.propose":
            continue
        result = step.tool_result
        data = result.data if result and isinstance(result.data, dict) else {}
        for item in data.get("candidates") or []:
            if isinstance(item, dict):
                text = str(
                    item.get("front")
                    or item.get("question")
                    or item.get("text")
                    or ""
                ).strip()
            else:
                text = str(item or "").strip()
            if text:
                candidates.append(f"Draft: {text}")
    return candidates[:7]


def _graph_summary(steps: list[AgentStep]) -> str:
    for step in steps:
        if step.tool_name != "graph.inspect":
            continue
        result = step.tool_result
        data = result.data if result and isinstance(result.data, dict) else {}
        if "total_concepts" in data:
            return f"В графе найдено концептов: {data.get('total_concepts')}."
        if data.get("found"):
            concept = str(data.get("concept") or "").strip()
            return f"Узел графа для темы{_topic_suffix(concept)} найден."
    return ""


def _graph_prerequisites(steps: list[AgentStep]) -> list[str]:
    prereqs: list[str] = []
    for step in steps:
        if step.tool_name != "graph.inspect":
            continue
        result = step.tool_result
        data = result.data if result and isinstance(result.data, dict) else {}
        raw = data.get("prerequisites") or []
        for item in raw:
            text = str(item or "").strip()
            if text:
                prereqs.append(text)
    return prereqs[:5]


def _weak_concepts(steps: list[AgentStep]) -> list[str]:
    weak: list[str] = []
    for step in steps:
        if step.tool_name != "progress.get_mastery":
            continue
        result = step.tool_result
        data = result.data if result and isinstance(result.data, dict) else {}
        for item in data.get("weak_concepts") or []:
            text = str(item or "").strip()
            if text:
                weak.append(text)
    return weak[:5]


def _chain_text(prereqs: list[str], topic: str) -> str:
    if prereqs:
        chain = " → ".join(prereqs)
        if topic:
            return f"{chain} → {topic}"
        return chain
    if topic:
        return f"Prerequisites для темы{_topic_suffix(topic)} не найдены явно."
    return "Цепочка prerequisites не восстановлена из доступных данных."


def _konspekt_rows(steps: list[AgentStep]) -> list[str]:
    rows: list[str] = []
    for step in steps:
        if step.tool_name != "konspekt.inspect":
            continue
        result = step.tool_result
        data = result.data if result and isinstance(result.data, dict) else {}
        for row in data.get("rows") or []:
            if isinstance(row, dict):
                text = str(
                    row.get("title")
                    or row.get("section")
                    or row.get("id")
                    or ""
                ).strip()
            else:
                text = str(row or "").strip()
            if text:
                rows.append(text)
    return rows[:8]


def _konspekt_total_rows(steps: list[AgentStep]) -> int | None:
    for step in steps:
        if step.tool_name != "konspekt.inspect":
            continue
        result = step.tool_result
        data = result.data if result and isinstance(result.data, dict) else {}
        raw = data.get("total_rows")
        if isinstance(raw, int):
            return raw
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    return None


def _profile_hint(steps: list[AgentStep]) -> str:
    for step in steps:
        if step.tool_name != "learner.get_profile":
            continue
        result = step.tool_result
        if result and result.ok:
            return "Профиль ученика получен и использован для выбора темпа."
    return ""


def _mastery_hint(steps: list[AgentStep]) -> str:
    for step in steps:
        if step.tool_name != "progress.get_mastery":
            continue
        result = step.tool_result
        data = result.data if result and isinstance(result.data, dict) else {}
        weak = data.get("weak_concepts") or []
        if weak:
            return "В прогрессе есть слабые места, поэтому сессию лучше вести короткими шагами."
        if result and result.ok:
            return "Данные о прогрессе получены, явные слабые места не выделены."
    return ""


def _rag_was_used(steps: list[AgentStep]) -> bool:
    return any(step.tool_name in ("rag.search", "rag.answer") for step in steps)


def _graph_was_used(steps: list[AgentStep]) -> bool:
    return any(step.tool_name == "graph.inspect" for step in steps)


def _konspekt_was_used(steps: list[AgentStep]) -> bool:
    return any(step.tool_name == "konspekt.inspect" for step in steps)


def _konspekt_is_empty(steps: list[AgentStep]) -> bool:
    total_rows = _konspekt_total_rows(steps)
    return total_rows == 0


def _numbered_or_default(items: list[str], defaults: list[str]) -> list[str]:
    selected = items or defaults
    return [f"{index}. {item}" for index, item in enumerate(selected, start=1)]


def _bulleted_or_default(items: list[str], defaults: list[str]) -> list[str]:
    selected = items or defaults
    return [f"- {item}" for item in selected]


def _source_labels(sources: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for source in sources:
        label = str(
            source.get("file")
            or source.get("file_name")
            or source.get("source")
            or source.get("title")
            or source.get("node_id")
            or ""
        ).strip()
        if label and label not in seen:
            labels.append(label)
            seen.add(label)
    return labels[:6]


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


STUDY_SESSION_SCENARIO = AgentScenario(
    scenario_id="study_session",
    system_prompt=AGENT_STUDY_SESSION_SYSTEM_PROMPT,
    finalize_answer=finalize_study_session_answer,
)

GRAPH_GAP_FINDER_SCENARIO = AgentScenario(
    scenario_id="graph_gap_finder",
    system_prompt=AGENT_GRAPH_GAP_FINDER_SYSTEM_PROMPT,
    finalize_answer=finalize_graph_gap_answer,
)

LIVING_KONSPEKT_COACH_SCENARIO = AgentScenario(
    scenario_id="living_konspekt_coach",
    system_prompt=AGENT_LIVING_KONSPEKT_COACH_SYSTEM_PROMPT,
    finalize_answer=finalize_konspekt_coach_answer,
)


__all__ = [
    "AgentScenario",
    "GRAPH_GAP_FINDER_SCENARIO",
    "GraphGapReport",
    "KonspektCoachDraft",
    "LIVING_KONSPEKT_COACH_SCENARIO",
    "STUDY_SESSION_SCENARIO",
    "StudySessionResult",
    "build_graph_gap_report",
    "build_konspekt_coach_draft",
    "build_study_session_answer",
    "detect_graph_gap_intent",
    "detect_konspekt_coach_intent",
    "detect_study_session_intent",
    "finalize_graph_gap_answer",
    "finalize_konspekt_coach_answer",
    "finalize_study_session_answer",
    "get_agent_scenario",
]
