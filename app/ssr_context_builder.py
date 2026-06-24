"""Build SSR explanation learning context — no LLM or embedding imports.

Extracted from adaptive_plan_llm_enrichment so this can be imported by the
Streamlit process without triggering the llama_index / provider import chain.
"""
from __future__ import annotations

import re
from typing import Any

_LEDGER_FC_RE = re.compile(r"Очередь flashcards \(локально\):\s*(\d+)")
_LEDGER_SM2_RE = re.compile(r"Очередь повторений по темам \(локально\):\s*(\d+)")


def _parse_ssr_ledger_queue_counts(lines: list[str] | None) -> tuple[int, int]:
    """Extract flashcard / SM-2 queue counts from evidence-ledger lines."""
    if not lines:
        return 0, 0
    fc = 0
    sm2 = 0
    for line in lines:
        m_fc = _LEDGER_FC_RE.search(line)
        if m_fc:
            fc = int(m_fc.group(1))
        m_sm2 = _LEDGER_SM2_RE.search(line)
        if m_sm2:
            sm2 = int(m_sm2.group(1))
    return fc, sm2


def build_ssr_llm_learning_context(
    rec: Any,  # SmartStudyRecommendation — accepted but not read; kept for call-site compat
    *,
    evidence_ledger: list[str] | None,
    tutor_topic: str | None,
    weak_concept: str | None,
    primary_topic_hint: str | None,
) -> dict[str, Any]:
    """Build the context dict for the SSR LLM explanation prompt.

    Pure computation + one lazy SQLite read (user_state). No LLM/embedding imports.
    """
    fc_n, sm2_n = _parse_ssr_ledger_queue_counts(evidence_ledger)
    topic_slot = str(primary_topic_hint or tutor_topic or weak_concept or "").strip()
    last_topic = topic_slot or "нет данных"
    last_date = "нет данных"
    try:
        from app import user_state as _uss

        snap = _uss.get_tutor_learning_resume()
        if isinstance(snap, dict):
            snap_topic = str(snap.get("topic") or "").strip()
            if snap_topic:
                last_topic = (
                    f"{snap_topic} (фокус карточки: {topic_slot})"
                    if topic_slot and topic_slot != snap_topic
                    else snap_topic
                )
            upd = snap.get("updated_at")
            if upd is not None:
                last_date = str(upd)
    except Exception:  # noqa: BLE001
        pass

    weak_list = str(weak_concept or "").strip() or "нет данных"
    local_evidence = (
        "\n".join(evidence_ledger) if evidence_ledger else "нет дополнительных локальных сигналов"
    )
    return {
        "last_session_topic": last_topic,
        "last_session_date": last_date,
        "quiz_score_last_3": "нет данных",
        "cards_due_count": fc_n,
        "sm2_due_count": sm2_n,
        "weak_concepts_list": weak_list,
        "local_evidence": local_evidence,
        "flashcard_due_n": fc_n,
        "sm2_due_n": sm2_n,
    }
