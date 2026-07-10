"""Product scenarios layered on top of the generic read-only agent loop.

Wave 1A ships the first scenario: a short study session coach. The scenario
does not call services directly and does not write state; it only supplies a
specialized system prompt and a final-answer contract over the runner trace.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.contracts import AgentStep
from app.prompts._impl import AGENT_STUDY_SESSION_SYSTEM_PROMPT


_STUDY_SESSION_HEADINGS = (
    "## Диагностика",
    "## Что изучать сейчас",
    "## План на 10–20 минут",
    "## Проверочные вопросы",
    "## Следующие шаги",
)


@dataclass(frozen=True)
class StudySessionResult:
    """Normalized study-session draft returned by the scenario finalizer."""

    answer: str
    has_sources: bool
    weak_data: bool


@dataclass(frozen=True)
class AgentScenario:
    """Small scenario contract consumed by :class:`app.agent.runner.AgentRunner`."""

    scenario_id: str
    system_prompt: str
    finalize_answer: Any


def detect_study_session_intent(question: str) -> bool:
    """Wave 1A routes every non-empty agent request to the study session.

    Later waves can split this into multiple scenario detectors. For now,
    agent mode is intentionally productized as "study session coach" rather
    than exposed as a generic autonomous agent.
    """
    return bool((question or "").strip())


def get_agent_scenario(question: str) -> AgentScenario | None:
    """Return the scenario for an agent request, if any."""
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
        normalized = _ensure_sources_section(text, source_labels, rag_was_used)
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


def _has_required_study_sections(answer: str) -> bool:
    return all(heading in answer for heading in _STUDY_SESSION_HEADINGS)


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
        f"1. Как бы вы объяснили тему{_topic_suffix(topic)} своими словами?",
        "2. Какой главный тезис или правило стоит запомнить?",
        "3. Где можно применить это знание на коротком примере?",
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


__all__ = [
    "AgentScenario",
    "STUDY_SESSION_SCENARIO",
    "StudySessionResult",
    "build_study_session_answer",
    "detect_study_session_intent",
    "finalize_study_session_answer",
    "get_agent_scenario",
]
