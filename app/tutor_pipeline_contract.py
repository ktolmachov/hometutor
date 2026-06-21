"""E6.0: явный контракт оркестрации tutor-пайплайна (metadata + trace).

``QueryContext.metadata["tutor_orchestration_pipeline"]`` — стабильные поля для UI/debug.
``QueryContext.trace["tutor_pipeline"]`` — упорядоченные итоги шагов ``build_tutor_pipeline``.

US-19.2 (MoT #3): опциональный снимок QA→Tutor кладётся в
``tutor_orchestration_pipeline["qa_handoff_context"]``, если в ``ctx.metadata`` перед
оркестратором есть ``qa_handoff_context`` (нормализованный dict).
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 1


def ensure_tutor_pipeline_trace(ctx: Any) -> list[dict[str, Any]]:
    t = getattr(ctx, "trace", None)
    if not isinstance(t, dict):
        return []
    cur = t.get("tutor_pipeline")
    if not isinstance(cur, list):
        cur = []
        t["tutor_pipeline"] = cur
    return cur


def record_tutor_pipeline_step(
    ctx: Any,
    step: str,
    status: str,
    *,
    detail: str | None = None,
) -> None:
    row: dict[str, Any] = {"step": step, "status": status}
    if detail:
        row["detail"] = detail
    ensure_tutor_pipeline_trace(ctx).append(row)


def merge_orchestration_pipeline_contract(md: dict[str, Any], **kwargs: Any) -> None:
    """Обновить только переданные поля; ``schema_version`` всегда актуален."""
    cur = md.get("tutor_orchestration_pipeline")
    if not isinstance(cur, dict):
        cur = {}
    else:
        cur = dict(cur)
    for k, v in kwargs.items():
        cur[k] = v
    cur["schema_version"] = SCHEMA_VERSION
    md["tutor_orchestration_pipeline"] = cur


def qa_handoff_orchestration_snapshot(handoff: dict[str, Any] | None) -> dict[str, Any]:
    """Компактный снимок handoff для ``tutor_orchestration_pipeline`` (без PII в длину)."""
    if not isinstance(handoff, dict) or not handoff:
        return {}
    topic = str(handoff.get("topic") or "").strip()
    lq = str(handoff.get("last_question") or "").strip()
    summary = str(handoff.get("answer_summary") or "").strip()
    conf = handoff.get("confidence")
    conf_level = ""
    conf_label = ""
    if isinstance(conf, dict):
        conf_level = str(conf.get("level") or "").strip()
        conf_label = str(conf.get("label") or "").strip()
    sources = handoff.get("sources")
    n_sources = len(sources) if isinstance(sources, list) else 0
    return {
        "topic_head": topic[:120] if topic else "",
        "has_last_question": bool(lq),
        "last_question_len": len(lq),
        "answer_summary_len": len(summary),
        "confidence_level": conf_level or None,
        "confidence_label": conf_label or None,
        "source_count": n_sources,
    }


def merge_qa_handoff_into_pipeline_metadata(
    md: dict[str, Any], handoff: dict[str, Any] | None
) -> None:
    snap = qa_handoff_orchestration_snapshot(handoff)
    if not snap:
        return
    merge_orchestration_pipeline_contract(md, qa_handoff_context=snap)


def qa_handoff_context_lines_for_preview(
    handoff: dict[str, Any] | None,
    *,
    last_answer: dict[str, Any] | None,
) -> list[str]:
    """Короткие строки превью для карточки handoff в UI тьютора (чистые функции, для тестов)."""
    lines: list[str] = []
    if isinstance(handoff, dict):
        t = str(handoff.get("topic") or "").strip()
        if t:
            lines.append(f"Тема: {t}")
        q = str(handoff.get("last_question") or "").strip()
        if q:
            lines.append(f"Исходный вопрос: {q}")
        s = str(handoff.get("answer_summary") or "").strip()
        if s:
            lines.append(f"Резюме ответа (Quick Answer): {s}")
    if isinstance(last_answer, dict):
        conf = last_answer.get("confidence")
        if isinstance(conf, dict):
            label = str(conf.get("label") or "").strip()
            level = str(conf.get("level") or "").strip()
            if label or level:
                tail = label or level
                lines.append(f"Уверенность ответа: {tail}")
        srcs = last_answer.get("sources")
        if isinstance(srcs, list) and srcs:
            lines.append(f"Источников в последнем ответе: {len(srcs)}")
    return lines


__all__ = [
    "SCHEMA_VERSION",
    "ensure_tutor_pipeline_trace",
    "merge_orchestration_pipeline_contract",
    "merge_qa_handoff_into_pipeline_metadata",
    "qa_handoff_context_lines_for_preview",
    "qa_handoff_orchestration_snapshot",
    "record_tutor_pipeline_step",
]
