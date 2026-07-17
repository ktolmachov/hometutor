"""Interactive Knowledge Graph dashboard tab.

Primary view is a self-contained D3.js force-directed concept graph
(:mod:`app.ui.knowledge_graph_d3`) with learning-native encodings: difficulty
level as node colour, quiz mastery as a circular progress ring, foundational
reach as node size, and a pulsing "ready to learn" frontier.

A compact concept selector below the graph preserves the Streamlit-side
actions (open topic / collect synthesis / go to plan) and rich document cards.
The classic ``streamlit-agraph`` view remains available in a collapsed
expander as a fallback and for click-to-select interaction.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from app.knowledge_text import tokenize_filtered
from app.ui.answer_helpers import run_synthesis_for_paths as _run_synthesis_for_paths
from app.ui.helpers import format_request_error as _format_request_error
from app.ui.home_hub import (
    _find_topic_for_concept,
    _topic_documents_index,
)
from app.ui.knowledge_graph_d3 import (
    KG_3D_ACTION_KEY,
    KG_3D_ACTION_RESULT_KEY,
    KG_3D_QUERY_PARAM,
    _is_lesson_node as _is_lesson_concept,
    build_kg_3d_html,
    build_kg_html,
    collect_kg_learned_set,
    consume_kg_3d_query_param,
    ensure_kg_3d_session_nonce,
    mark_kg_3d_event,
    render_d3_knowledge_graph,
    render_kg_3d_hall,
)
from app.ui.topics_catalog import load_topics_catalog as _load_topics_catalog
from app.ui.tutor_mastery_forecast_panel import (
    render_tutor_orchestration_snapshot_expander as _render_tutor_orchestration_snapshot_expander,
)
from app.ui.widgets import (
    render_chip_row as _render_chip_row,
    render_panel_header as _render_panel_header,
)


_TUTOR_MODES = {
    "explain":  "🧠 Объяснение",
    "practice": "💪 Практика",
    "quiz":     "❓ Квиз",
    "compare":  "🔀 Сравнение",
}


def build_tutor_prompt_for_concept(
    concept_id: str,
    *,
    info: dict,
    mastery_pct: float,
    prereqs: list[str],
    related_docs_count: int,
    is_frontier: bool,
    mode: str = "explain",
) -> str:
    """Build a context-rich tutor prompt for a concept from the knowledge graph.

    Args:
        concept_id: concept name/ID from graph.
        info: raw concept dict (description, level, …).
        mastery_pct: current mastery 0–100.
        prereqs: list of prerequisite concept IDs.
        related_docs_count: number of linked documents.
        is_frontier: True if all prereqs mastered but concept not yet learned.
        mode: one of "explain" | "practice" | "quiz" | "compare".

    Returns:
        A prompt string ready for ``tutor_pending_prompt``.
    """
    level = str(info.get("level") or "—")
    desc = str(info.get("description") or "").strip()
    prereq_line = (
        "Пресреквизиты, которые я уже прошёл: " + ", ".join(f"«{p}»" for p in prereqs[:6]) + "."
        if prereqs else "Это стартовый концепт без пресреквизитов."
    )
    mastery_line = (
        f"Мой текущий уровень mastery по этому концепту: **{mastery_pct:.0f}%**."
    )
    frontier_line = " Я готов начать изучать его — все пресреквизиты освоены." if is_frontier else ""
    docs_line = f" Доступно {related_docs_count} связанных документов." if related_docs_count else ""

    context = (
        f"Концепт: **{concept_id}** (уровень: {level}).\n"
        f"{mastery_line}{frontier_line}{docs_line}\n"
        f"{prereq_line}"
    )
    if desc:
        context += f"\nКраткое описание: {desc[:300]}"

    if mode == "explain":
        return (
            f"{context}\n\n"
            "Пожалуйста, объясни этот концепт структурированно:\n"
            "1. Ключевая идея (1–2 предложения)\n"
            "2. Зачем это важно / где применяется\n"
            "3. Один конкретный практический пример\n"
            "Начни с самого важного, избегай лишней теории."
        )
    if mode == "practice":
        return (
            f"{context}\n\n"
            "Дай мне 2–3 практических задания по этому концепту нарастающей сложности. "
            "После каждого жди мой ответ и давай краткую обратную связь. "
            "Первое задание — самое простое."
        )
    if mode == "quiz":
        return (
            f"{context}\n\n"
            "Проверь мои знания по этому концепту. "
            "Задай 3–5 вопросов нарастающей сложности: "
            "сначала определение/понятие, затем применение, затем edge case. "
            "Жди мой ответ после каждого вопроса перед тем, как задать следующий."
        )
    if mode == "compare" and prereqs:
        prereq = prereqs[-1]
        return (
            f"{context}\n\n"
            f"Объясни разницу и связь между «{prereq}» (который я уже знаю) "
            f"и «{concept_id}» (mastery: {mastery_pct:.0f}%). "
            "Когда используется каждый? В чём главное отличие? "
            "Покажи на конкретном примере."
        )
    # fallback / compare without prereqs
    return (
        f"{context}\n\n"
        f"Расскажи мне всё самое важное про «{concept_id}», что нужно знать для практической работы."
    )


def _workbench_state_rows(state=None) -> list[dict]:
    from app import workbench_service

    source = st.session_state if state is None else state
    return workbench_service.normalize_runtime_rows(
        list(source.get(workbench_service.WORKBENCH_SECTIONS_KEY) or [])
    )


def _workbench_collected_concept_ids(state=None) -> list[str]:
    """Concept ids that already have at least one section in the workbench basket."""
    ids: list[str] = []
    seen: set[str] = set()
    for row in _workbench_state_rows(state):
        cid = str(row.get("concept") or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        ids.append(cid)
    return ids


def _query_param_first_str(name: str) -> str:
    raw = st.query_params.get(name)
    if raw is None:
        return ""
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    return str(raw or "").strip()


def _kg_3d_concept_label(knowledge_graph, concept_id: str) -> str:
    try:
        concepts = knowledge_graph.get_concepts() if knowledge_graph is not None else {}
    except Exception:  # noqa: BLE001 - label lookup must not block action execution
        concepts = {}
    raw = concepts.get(concept_id) if isinstance(concepts, dict) else {}
    info = raw if isinstance(raw, dict) else {}
    return str(info.get("label") or concept_id)


def _set_kg_3d_action_result(
    state,
    *,
    envelope: dict,
    status: str,
    label: str,
    message: str = "",
    added: int = 0,
    duplicates: int = 0,
) -> None:
    target = st.session_state if state is None else state
    target[KG_3D_ACTION_RESULT_KEY] = {
        "status": status,
        "action": str(envelope.get("action") or ""),
        "concept_id": str(envelope.get("concept_id") or ""),
        "event_id": str(envelope.get("event_id") or ""),
        "label": label,
        "message": message,
        "added": int(added or 0),
        "duplicates": int(duplicates or 0),
    }


def _prime_kg_3d_action_focus(
    target,
    *,
    action: str,
    concept_id: str,
    event_id: str,
    label: str,
) -> None:
    target[KG_3D_ACTION_KEY] = {
        "action": action,
        "concept_id": concept_id,
        "event_id": event_id,
    }
    target["kg_selected_concept"] = concept_id
    target["kg_action_concept"] = concept_id
    target["interactive_quiz_focus_concept"] = concept_id
    target["current_topic"] = label


def _run_kg_3d_start_action(
    *,
    target,
    envelope: dict,
    concept_id: str,
    event_id: str,
    label: str,
    state,
) -> None:
    from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

    for key in (
        "interactive_quiz_data",
        "interactive_quiz_gen_id",
        "interactive_quiz_saved_for_gen_id",
        "interactive_quiz_error",
    ):
        target.pop(key, None)
    target[PENDING_CURRENT_VIEW_KEY] = "Интерактивный Quiz"
    mark_kg_3d_event(target, event_id, "succeeded")
    # Toast is the user-facing ack for start. Do not leave a sticky hall
    # action_result — user navigates away; a stale «Quiz открыт» would surface
    # on the next visit to Knowledge Graph after st.rerun().
    target.pop(KG_3D_ACTION_RESULT_KEY, None)
    if state is None:
        st.toast(f"▶ Старт из 3D-зала: **{concept_id}** → Quiz", icon="🎮")
        # PENDING is applied at the start of a run; force another pass so the
        # view switch is not lost mid-tab render after the _kg3d reload.
        st.rerun()


def _run_kg_3d_collect_action(
    *,
    target,
    envelope: dict,
    knowledge_graph,
    doc_index: dict,
    concept_id: str,
    event_id: str,
    label: str,
    state,
) -> None:
    related_docs = list(knowledge_graph.get_related_documents(concept_id) or [])
    query_text = " ".join(part for part in [concept_id, label] if part)
    added, duplicates = _collect_concept_sections_to_workbench(
        concept=concept_id,
        related_docs=related_docs,
        doc_index=doc_index if isinstance(doc_index, dict) else {},
        base_query=query_text,
        state=state,
    )
    mark_kg_3d_event(target, event_id, "succeeded")
    _set_kg_3d_action_result(
        state,
        envelope=envelope,
        status="succeeded",
        label=label,
        added=added,
        duplicates=duplicates,
    )
    if state is None:
        if added or duplicates:
            suffix = f" (уже было: {duplicates})" if duplicates else ""
            st.toast(f"В рабочий конспект: +{added}{suffix}", icon="📚")
        else:
            st.toast(
                "Подходящих разделов не нашлось — возможно, конспекты ещё не созданы.",
                icon="ℹ️",
            )


def _execute_kg_3d_action(
    envelope: dict,
    *,
    knowledge_graph,
    doc_index: dict,
    state=None,
) -> None:
    """G1: apply start (nav only) or collect (workbench write) for a validated envelope."""
    target = st.session_state if state is None else state
    action = str(envelope.get("action") or "")
    concept_id = str(envelope.get("concept_id") or "").strip()
    event_id = str(envelope.get("event_id") or "").strip()
    label = _kg_3d_concept_label(knowledge_graph, concept_id)
    if not concept_id or action not in {"start", "collect"}:
        mark_kg_3d_event(target, event_id, "failed")
        _set_kg_3d_action_result(
            state,
            envelope=envelope,
            status="failed",
            label=label or concept_id,
            message="Некорректное действие",
        )
        return

    _prime_kg_3d_action_focus(
        target,
        action=action,
        concept_id=concept_id,
        event_id=event_id,
        label=label,
    )

    try:
        if action == "start":
            _run_kg_3d_start_action(
                target=target,
                envelope=envelope,
                concept_id=concept_id,
                event_id=event_id,
                label=label,
                state=state,
            )
        else:
            _run_kg_3d_collect_action(
                target=target,
                envelope=envelope,
                knowledge_graph=knowledge_graph,
                doc_index=doc_index,
                concept_id=concept_id,
                event_id=event_id,
                label=label,
                state=state,
            )
    except Exception as exc:  # noqa: BLE001 - action must fail closed without breaking the tab
        mark_kg_3d_event(target, event_id, "failed")
        _set_kg_3d_action_result(
            state=state,
            envelope=envelope,
            status="failed",
            label=label,
            message=_format_request_error(exc),
        )
        if state is None:
            st.error(f"3D-зал: не удалось выполнить «{action}»: {_format_request_error(exc)}")


def _consume_and_apply_kg_3d_query(
    *,
    node_ids: list[str],
    knowledge_graph,
    doc_index: dict,
) -> dict | None:
    """Host-side G0 pipeline for ``_kg3d``.

    Order (fixed, intentional — differs from the pure ``consume_kg_3d_query_param``
    docstring which covers only validate→reserve):

    1. **remove** ``_kg3d`` from the URL first — prevents infinite full-rerun loops
       on malformed/stale envelopes;
    2. **validate** envelope (via ``consume_kg_3d_query_param``);
    3. **reserve** ``event_id`` in the bounded dedup window;
    4. **execute** start/collect;
    5. **pop and return** one-shot ``action_result`` for the embedded hall on
       *this same render* (caller must pass it into ``render_kg_3d_hall``).

    Returns the action_result dict, or None if no/invalid/duplicate envelope.
    """
    raw = _query_param_first_str(KG_3D_QUERY_PARAM)
    # Always strip the param so a bad/stale URL cannot loop full reruns.
    if KG_3D_QUERY_PARAM in st.query_params or raw:
        try:
            st.query_params.pop(KG_3D_QUERY_PARAM, None)
        except Exception:  # noqa: BLE001 - query_params API may vary by Streamlit version
            pass
    if not raw:
        return None
    nonce = ensure_kg_3d_session_nonce(st.session_state)
    env = consume_kg_3d_query_param(
        raw=raw,
        session_nonce=nonce,
        node_ids=node_ids,
        state=st.session_state,
    )
    if env is None:
        return None
    _execute_kg_3d_action(
        env,
        knowledge_graph=knowledge_graph,
        doc_index=doc_index,
    )
    # Pop after execute so the hall on this render gets a fresh ack, and a later
    # unrelated rerun does not re-surface a stale result.
    result = st.session_state.pop(KG_3D_ACTION_RESULT_KEY, None)
    return result if isinstance(result, dict) else None


def _add_section_to_workbench_state(section, state=None) -> bool:
    from app import workbench_service

    rows = _workbench_state_rows(state)
    before = {str(row.get("row_key") or "") for row in rows}
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    new_rows = workbench_service.add_section(rows, section, storage=storage)
    target = st.session_state if state is None else state
    target[workbench_service.WORKBENCH_SECTIONS_KEY] = new_rows
    return any(str(row.get("row_key") or "") not in before for row in new_rows)


def _render_document_section_workbench_buttons(*, path: str, query_text: str, concept: str, key: str) -> None:
    """До 3 кнопок «➕ раздел «<heading>»» под документом — секции считаются server-side.

    Концепт часто разобран в нескольких местах конспекта (тема, антипаттерны, термины) —
    одна «лучшая» секция теряла остальные.
    """
    try:
        from dataclasses import replace as _dc_replace

        from app.section_index import build_section_index, top_sections_for

        sections = build_section_index(path)
        if not sections:
            return
        top_sections = top_sections_for(sections, query_text, k=3)
    except Exception:  # noqa: BLE001 - section lookup must not break the concept panel
        return
    for i, section in enumerate(top_sections):
        if st.button(f"➕ раздел «{section.heading_text}»", key=f"{key}_{i}", width="stretch"):
            added = _add_section_to_workbench_state(_dc_replace(section, concept=concept))
            st.toast(
                f"Добавлено в рабочий конспект: «{section.heading_text}»" if added else "Уже в рабочем конспекте",
                icon="📚",
            )


def _collect_concept_sections_to_workbench(
    *,
    concept: str,
    related_docs: list,
    doc_index: dict,
    base_query: str,
    state=None,
) -> tuple[int, int]:
    """Лучшая секция каждого related-документа → корзина. Возвращает (добавлено, уже было).

    ``state`` — DI для юнит-тестов; в UI — session_state.
    """
    from dataclasses import replace as _dc_replace

    from app.section_index import best_section_for, build_section_index

    added = duplicates = 0
    for rel_path in related_docs:
        meta = doc_index.get(str(rel_path), {}) if isinstance(doc_index, dict) else {}
        path = meta.get("relative_path") or meta.get("file_name") or str(rel_path)
        query = " ".join(
            part for part in [base_query, " ".join(meta.get("key_concepts") or [])] if part
        )
        try:
            sections = build_section_index(str(path))
            section = best_section_for(sections, query) if sections else None
        except Exception:  # noqa: BLE001 - один документ без конспекта не должен срывать сбор
            continue
        if section is None:
            continue
        if _add_section_to_workbench_state(_dc_replace(section, concept=concept), state):
            added += 1
        else:
            duplicates += 1
    return added, duplicates


def _workbench_basket_headings(basket_rows: list[dict]) -> set[tuple[str, str]]:
    """(concept, lowercased-heading) pairs already present in the workbench basket."""
    headings: set[tuple[str, str]] = set()
    for row in basket_rows:
        cid = str(row.get("concept") or "").strip()
        heading = str(row.get("heading_text") or row.get("heading") or "").strip().lower()
        if cid and heading:
            headings.add((cid, heading))
    return headings


def _concept_section_cards(
    *,
    concept: str,
    label: str,
    related_docs: list,
    doc_index: dict,
    basket_headings: set[tuple[str, str]],
) -> list[dict[str, object]]:
    """U2: best section per related document → door cards (heading + in_basket + obs uri)."""
    from app.obsidian_export import obsidian_uri
    from app.section_index import best_section_for, build_section_index

    cards: list[dict[str, object]] = []
    for rel_path in related_docs:
        meta = doc_index.get(str(rel_path), {}) if isinstance(doc_index, dict) else {}
        path = meta.get("relative_path") or meta.get("file_name") or str(rel_path)
        query = " ".join(
            part
            for part in [concept, label, " ".join(meta.get("key_concepts") or [])]
            if part
        )
        try:
            sections = build_section_index(str(path))
            section = best_section_for(sections, query) if sections else None
        except Exception:  # noqa: BLE001
            continue
        if section is None:
            continue
        heading = str(getattr(section, "heading_text", "") or "").strip()
        md_abs = getattr(section, "konspekt_md_abs", None)
        uri = ""
        try:
            if md_abs:
                uri = str(obsidian_uri(md_abs, heading_text=heading) or "")
        except Exception:  # noqa: BLE001
            uri = ""
        cards.append(
            {
                "heading": heading,
                "in_basket": (concept, heading.lower()) in basket_headings,
                "obsidian_uri": uri,
            }
        )
    return cards


def _concept_sections_view_model(
    *,
    concept_ids: list[str],
    knowledge_graph,
    doc_index: dict,
    state=None,
) -> dict[str, list[dict[str, object]]]:
    """U2: sections + Obsidian doors for hall card/interior (embedded view-model only).

    Same search path as ``_collect_concept_sections_to_workbench`` (best section per
    related document). Does not mutate the workbench; only reports ``in_basket``.
    Cached in ``st.session_state`` when ``state`` is None.
    """
    ids = [str(c).strip() for c in concept_ids if str(c or "").strip()]
    if not ids:
        return {}

    cache_key = "kg_3d_concept_sections_vm"
    cache_sig_key = "kg_3d_concept_sections_sig"
    basket_rows = _workbench_state_rows(state)
    basket_headings = _workbench_basket_headings(basket_rows)
    sig = (
        tuple(ids),
        tuple(sorted(f"{c}:{h}" for c, h in basket_headings)),
        len(basket_rows),
    )
    target = st.session_state if state is None else state
    if (
        isinstance(target, dict)
        and target.get(cache_sig_key) == sig
        and isinstance(target.get(cache_key), dict)
    ):
        return dict(target[cache_key])  # type: ignore[arg-type]
    # Streamlit SessionState is not a plain dict — still support cache.
    if state is None:
        try:
            if st.session_state.get(cache_sig_key) == sig and isinstance(
                st.session_state.get(cache_key), dict
            ):
                return dict(st.session_state[cache_key])
        except Exception:  # noqa: BLE001 - cache is best-effort
            pass

    try:
        concepts = knowledge_graph.get_concepts() if knowledge_graph is not None else {}
    except Exception:  # noqa: BLE001
        concepts = {}
    if not isinstance(concepts, dict):
        concepts = {}

    out: dict[str, list[dict[str, object]]] = {}
    for concept in ids:
        raw = concepts.get(concept) if isinstance(concepts, dict) else {}
        info = raw if isinstance(raw, dict) else {}
        label = str(info.get("label") or concept)
        try:
            related_docs = list(knowledge_graph.get_related_documents(concept) or [])
        except Exception:  # noqa: BLE001
            related_docs = []
        cards = _concept_section_cards(
            concept=concept,
            label=label,
            related_docs=related_docs,
            doc_index=doc_index,
            basket_headings=basket_headings,
        )
        if cards:
            out[concept] = cards

    if state is None:
        try:
            st.session_state[cache_key] = out
            st.session_state[cache_sig_key] = sig
        except Exception:  # noqa: BLE001
            pass
    elif isinstance(target, dict):
        target[cache_key] = out
        target[cache_sig_key] = sig
    return out


def _concept_terms(concept_id: str, info: dict) -> list[str]:
    """Human-visible names that can prove or duplicate a graph concept."""
    raw_terms = [
        concept_id,
        info.get("label"),
        info.get("normalized_label"),
        *(info.get("aliases") or []),
    ]
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_terms:
        term = str(raw or "").strip()
        key = " ".join(term.lower().split())
        if not term or key in seen:
            continue
        seen.add(key)
        out.append(term)
    return out


def _concept_term_tokens(value: str) -> frozenset[str]:
    return frozenset(tokenize_filtered(value))


def _alias_similarity(left: str, right: str) -> tuple[float, str] | None:
    left_key = " ".join(left.lower().split())
    right_key = " ".join(right.lower().split())
    if not left_key or not right_key:
        return None
    if left_key == right_key:
        return 1.0, "совпадает alias/label"

    left_tokens = _concept_term_tokens(left)
    right_tokens = _concept_term_tokens(right)
    if not left_tokens or not right_tokens:
        return None
    if left_tokens == right_tokens:
        return 0.96, "те же смысловые токены"

    overlap = left_tokens & right_tokens
    union = left_tokens | right_tokens
    jaccard = len(overlap) / max(1, len(union))
    if len(overlap) >= 2 and jaccard >= 0.74:
        return round(jaccard, 2), "сильное пересечение токенов"
    if len(overlap) >= 2 and (
        left_tokens.issubset(right_tokens) or right_tokens.issubset(left_tokens)
    ):
        return 0.82, "один термин вложен в другой"
    return None


def _alias_duplicate_suspects(
    selected: str,
    concepts: dict,
    *,
    limit: int = 5,
) -> list[dict[str, object]]:
    """Deterministic duplicate candidates for the selected concept.

    This is intentionally a *candidate* signal: it never mutates the graph and never
    claims equivalence, it only surfaces concepts worth merging or aliasing.
    """
    selected_info = concepts.get(selected)
    if not isinstance(selected_info, dict):
        return []
    selected_terms = _concept_terms(selected, selected_info)
    out: list[dict[str, object]] = []
    for cid, raw in concepts.items():
        if cid == selected or not isinstance(raw, dict):
            continue
        best: tuple[float, str, str, str] | None = None
        for left in selected_terms:
            for right in _concept_terms(str(cid), raw):
                match = _alias_similarity(left, right)
                if match is None:
                    continue
                score, reason = match
                candidate = (score, reason, left, right)
                if best is None or candidate[0] > best[0]:
                    best = candidate
        if best is None:
            continue
        score, reason, left, right = best
        out.append(
            {
                "concept_id": str(cid),
                "label": str(raw.get("label") or cid),
                "score": score,
                "reason": reason,
                "match": f"{left} ↔ {right}",
            }
        )
    out.sort(key=lambda item: (-float(item["score"]), str(item["concept_id"])))
    return out[:limit]


def _section_evidence_for_doc(
    path: str,
    query_text: str,
    *,
    limit: int = 2,
) -> list[dict[str, object]]:
    try:
        from app.obsidian_export import obsidian_uri, vscode_uri
        from app.section_index import build_section_index, top_sections_for

        sections = build_section_index(path)
        return [
            {
                "heading": section.heading_text,
                "line_start": section.line_start,
                "line_end": section.line_end,
                "obs_uri": obsidian_uri(section.konspekt_md_abs, heading_text=section.heading_text),
                "vscode_uri": vscode_uri(section.konspekt_md_abs, line=section.line_start),
            }
            for section in top_sections_for(sections, query_text, k=limit)
        ]
    except Exception:  # noqa: BLE001 - graph evidence must degrade with one bad document.
        return []


def _concept_evidence_ledger(
    selected: str,
    info: dict,
    prereqs: list[str],
    related_docs: list,
    doc_index: dict,
    *,
    max_docs: int = 3,
) -> list[dict[str, object]]:
    """Explain why a concept exists in the graph using local evidence."""
    ledger: list[dict[str, object]] = []
    desc = str(info.get("description") or "").strip()
    if desc:
        ledger.append(
            {
                "kind": "description",
                "title": "Описание узла",
                "detail": desc[:280],
            }
        )

    aliases = [term for term in _concept_terms(selected, info) if term != selected]
    if aliases:
        ledger.append(
            {
                "kind": "aliases",
                "title": "Aliases",
                "detail": ", ".join(aliases[:8]),
            }
        )

    if prereqs:
        ledger.append(
            {
                "kind": "prerequisites",
                "title": "Prerequisites",
                "detail": ", ".join(prereqs[:8]),
            }
        )

    query_text = " ".join(
        part for part in [selected, desc, " ".join(aliases)] if part
    )
    for rel_path in related_docs[:max_docs]:
        meta = doc_index.get(str(rel_path), {}) if isinstance(doc_index, dict) else {}
        path = str(meta.get("relative_path") or meta.get("file_name") or rel_path)
        title = path
        summary = str(meta.get("summary") or "").strip()
        sections = _section_evidence_for_doc(
            path,
            " ".join(
                part
                for part in [query_text, " ".join(meta.get("key_concepts") or [])]
                if part
            ),
        )
        ledger.append(
            {
                "kind": "document",
                "title": title,
                "detail": summary[:220] if summary else "Документ связан с этим концептом на карте знаний.",
                "sections": sections,
            }
        )
    return ledger


def _render_concept_evidence_ledger(ledger: list[dict[str, object]]) -> None:
    if not ledger:
        st.caption("Evidence пока нет: у узла нет описания, aliases или связанных документов.")
        return
    for item in ledger:
        st.markdown(f"**{item['title']}**")
        detail = str(item.get("detail") or "").strip()
        if detail:
            st.caption(detail)
        sections = item.get("sections")
        if isinstance(sections, list) and sections:
            for section in sections:
                if not isinstance(section, dict):
                    continue
                st.caption(
                    "📍 "
                    f"{section.get('heading')} "
                    f"· строки {section.get('line_start')}-{section.get('line_end')}"
                )
                link_cols = st.columns(2)
                with link_cols[0]:
                    obs_uri = str(section.get("obs_uri") or "")
                    if obs_uri:
                        st.link_button("📍 Открыть", obs_uri, width="stretch")
                with link_cols[1]:
                    vscode_uri = str(section.get("vscode_uri") or "")
                    if vscode_uri:
                        st.link_button("🖥 VS Code", vscode_uri, width="stretch")


def _render_alias_duplicate_suspects(suspects: list[dict[str, object]]) -> None:
    if not suspects:
        st.caption("Дубликатов по label/alias не найдено.")
        return
    for item in suspects:
        score = float(item.get("score") or 0.0)
        st.caption(
            f"⚠ {item.get('label')} (`{item.get('concept_id')}`) · "
            f"{score:.2f} · {item.get('reason')} · {item.get('match')}"
        )


def _concept_related_paths(concept_id: str, info: dict) -> list[str]:
    raw_paths = [
        *(info.get("related_documents") or []),
        *(info.get("documents") or []),
    ]
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_paths:
        path = str(raw or "").strip().replace("\\", "/")
        if path and path not in seen:
            seen.add(path)
            out.append(path)
    if not out and concept_id.startswith("lesson:"):
        out.append(concept_id.removeprefix("lesson:"))
    return out


def _is_test_artifact_path(path: str) -> bool:
    normalized = str(path or "").strip().replace("\\", "/").lower()
    if not normalized:
        return False
    first = normalized.split("/", 1)[0]
    return first.startswith("_test") or first.startswith("test-")


def _is_test_artifact_concept(concept_id: str, info: dict) -> bool:
    if concept_id.startswith("lesson:test-"):
        return True
    return any(_is_test_artifact_path(path) for path in _concept_related_paths(concept_id, info))


def _graph_duplicate_pairs(concepts: dict, *, limit: int = 12) -> list[dict[str, object]]:
    pairs: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for cid in sorted(concepts):
        raw = concepts.get(cid)
        if not isinstance(raw, dict):
            continue
        if _is_test_artifact_concept(str(cid), raw):
            continue
        for suspect in _alias_duplicate_suspects(str(cid), concepts, limit=3):
            other = str(suspect.get("concept_id") or "")
            other_raw = concepts.get(other)
            if not isinstance(other_raw, dict):
                continue
            if _is_test_artifact_concept(other, other_raw):
                continue
            if _is_lesson_concept(str(cid), raw) or _is_lesson_concept(other, other_raw):
                continue
            key = tuple(sorted((str(cid), other)))
            if not other or key in seen:
                continue
            seen.add(key)
            pairs.append(
                {
                    "source": str(cid),
                    "target": other,
                    "score": suspect.get("score"),
                    "reason": suspect.get("reason"),
                    "match": suspect.get("match"),
                }
            )
    pairs.sort(
        key=lambda item: (
            -float(item.get("score") or 0.0),
            str(item["source"]),
            str(item["target"]),
        )
    )
    return pairs[:limit]


def _relation_has_evidence(relation: dict) -> bool:
    doc_id = str(relation.get("evidence_doc_id") or "").strip()
    chunk_id = str(relation.get("evidence_chunk_id") or "").strip()
    if "evidence_doc_id" in relation or "evidence_chunk_id" in relation:
        return bool(doc_id and chunk_id)

    source_doc = str(relation.get("source_document") or "").strip()
    source_chunk = str(relation.get("source_chunk") or "").strip()
    if "source_document" in relation or "source_chunk" in relation:
        return bool(source_doc and source_chunk)

    return bool(str(relation.get("evidence") or "").strip())


def _graph_quality_audit(
    concepts: dict,
    payload: dict,
    typed_relations: list[dict] | None = None,
    *,
    finding_limit: int = 8,
) -> dict[str, object]:
    nodes = [n for n in payload.get("nodes", []) if isinstance(n, dict)]
    health = payload.get("health") if isinstance(payload.get("health"), dict) else {}
    duplicate_pairs = _graph_duplicate_pairs(concepts)
    test_artifacts = [
        str(n.get("id"))
        for n in nodes
        if _is_test_artifact_concept(str(n.get("id") or ""), concepts.get(str(n.get("id") or ""), {}))
    ]
    test_artifact_set = set(test_artifacts)
    auditable_nodes = [n for n in nodes if str(n.get("id")) not in test_artifact_set]
    no_docs = [str(n.get("id")) for n in auditable_nodes if not n.get("related")]
    no_sections = [
        str(n.get("id"))
        for n in auditable_nodes
        if n.get("related")
        and not any(
            isinstance(card, dict) and card.get("sections")
            for card in n.get("related") or []
        )
    ]
    no_description = [
        str(n.get("id"))
        for n in auditable_nodes
        if not str(n.get("desc") or "").strip()
    ]
    relation_evidence_missing = [
        relation
        for relation in (typed_relations or [])
        if isinstance(relation, dict) and not _relation_has_evidence(relation)
    ]
    orphan_nodes = [str(item) for item in (health.get("orphans") or [])]

    penalty = (
        len(no_docs) * 3
        + len(no_sections) * 4
        + len(duplicate_pairs) * 5
        + len(relation_evidence_missing) * 2
        + len(orphan_nodes) * 4
        + len(no_description)
        + len(test_artifacts) * 2
    )
    base_score = int(health.get("score") or 100)
    score = max(0, min(100, base_score - penalty))

    findings: list[dict[str, object]] = []
    if test_artifacts:
        findings.append(
            {
                "severity": "P1",
                "kind": "test_artifacts",
                "title": f"Тестовые артефакты попали в граф: {len(test_artifacts)}",
                "detail": ", ".join(test_artifacts[:5]),
            }
        )
    for pair in duplicate_pairs[:finding_limit]:
        findings.append(
            {
                "severity": "P1",
                "kind": "duplicate",
                "title": f"Возможный дубль: {pair['source']} ↔ {pair['target']}",
                "detail": f"{pair.get('reason')} · {pair.get('match')}",
            }
        )
    for cid in no_sections[: max(0, finding_limit - len(findings))]:
        findings.append(
            {
                "severity": "P2",
                "kind": "no_sections",
                "title": f"Нет точных разделов для {cid}",
                "detail": "Документы связаны, но section evidence не найден.",
            }
        )
    for cid in no_docs[: max(0, finding_limit - len(findings))]:
        findings.append(
            {
                "severity": "P2",
                "kind": "no_docs",
                "title": f"Нет связанных документов для {cid}",
                "detail": "Узел есть в графе, но не ведёт к учебному материалу.",
            }
        )
    for relation in relation_evidence_missing[: max(0, finding_limit - len(findings))]:
        src = relation.get("source_concept_id") or relation.get("source") or "?"
        tgt = relation.get("target_concept_id") or relation.get("target") or "?"
        findings.append(
            {
                "severity": "P2",
                "kind": "relation_evidence",
                "title": f"Связь без evidence: {src} → {tgt}",
                "detail": str(relation.get("relation_type") or "relation"),
            }
        )

    return {
        "score": score,
        "counters": {
            "concepts": len(nodes),
            "orphans": len(orphan_nodes),
            "duplicates": len(duplicate_pairs),
            "no_docs": len(no_docs),
            "no_sections": len(no_sections),
            "no_description": len(no_description),
            "test_artifacts": len(test_artifacts),
            "relations_without_evidence": len(relation_evidence_missing),
        },
        "findings": findings[:finding_limit],
    }


def _render_graph_quality_audit(audit: dict[str, object]) -> None:
    counters = audit.get("counters") if isinstance(audit.get("counters"), dict) else {}
    score = int(audit.get("score") or 0)
    cols = st.columns(4)
    with cols[0]:
        st.metric("Quality", f"{score}/100")
    with cols[1]:
        st.metric("Дубли", int(counters.get("duplicates") or 0))
    with cols[2]:
        st.metric("Без разделов", int(counters.get("no_sections") or 0))
    with cols[3]:
        st.metric("Без evidence", int(counters.get("relations_without_evidence") or 0))

    compact = (
        f"концептов {counters.get('concepts', 0)} · "
        f"orphan {counters.get('orphans', 0)} · "
        f"без документов {counters.get('no_docs', 0)} · "
        f"без описания {counters.get('no_description', 0)} · "
        f"test artifacts {counters.get('test_artifacts', 0)}"
    )
    st.caption(compact)

    findings = audit.get("findings")
    if not isinstance(findings, list) or not findings:
        st.success("Критичных findings не найдено.")
        return
    st.markdown("**Что чинить первым**")
    for item in findings:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        title = str(item.get("title") or "")
        detail = str(item.get("detail") or "")
        col1, col2 = st.columns([4, 1])
        with col1:
            st.caption(f"{item.get('severity')} · {title} — {detail}")
        with col2:
            if kind == "no_sections":
                cid = title.replace("Нет точных разделов для ", "").strip()
                if st.button("🔎", key=f"audit_fix_{kind}_{hash(title)}", help="Выбрать концепт для поиска разделов"):
                    st.session_state["kg_action_concept"] = cid
                    st.toast(f"Концепт **{cid}** выбран в панели действий ниже", icon="🎯")
                    st.rerun()


def _render_graph_publish_status() -> dict | None:
    try:
        from app.graph_publish_status import (
            build_learner_publish_status_view,
            get_graph_publish_status,
        )

        status = get_graph_publish_status()
    except Exception:  # noqa: BLE001 - diagnostics only; graph tab must still render.
        st.caption("Статус карты временно недоступен.")
        return None

    view = build_learner_publish_status_view(status)
    primary = str(view.get("primary") or "")
    tone = str(view.get("tone") or "info")
    if tone == "success":
        st.success(primary)
    elif tone == "warning":
        st.warning(primary, icon="⚠️")
    else:
        st.info(primary)
    for caption in view.get("captions") or []:
        st.caption(str(caption))

    failed_title = view.get("failed_title")
    if failed_title:
        with st.expander(str(failed_title), expanded=False):
            metrics = [str(m) for m in (view.get("failed_metrics") or []) if str(m).strip()]
            if metrics:
                st.caption(" · ".join(metrics))
            for reason in list(view.get("failed_reasons") or [])[:6]:
                st.caption(f"- {reason}")
            debug_lines = [str(x) for x in (view.get("debug_lines") or []) if str(x).strip()]
            if debug_lines:
                st.caption("Отладка: " + " · ".join(debug_lines[:4]))
    elif view.get("debug_lines"):
        with st.expander("Технические детали карты", expanded=False):
            for line in view["debug_lines"]:
                st.caption(str(line))
    return status


def _load_staging_preview_graph(status: dict | None):
    """Load latest failed staging graph for read-only UI preview, never for publish/runtime use."""
    if not isinstance(status, dict):
        return None, None
    failed = status.get("latest_failed_staging")
    if not isinstance(failed, dict) or not failed.get("exists"):
        return None, None
    raw_bundle_dir = str(failed.get("bundle_dir") or "").strip()
    if not raw_bundle_dir:
        return None, None
    bundle_dir = Path(raw_bundle_dir)
    try:
        from app.knowledge_graph import SqliteBundleKnowledgeGraph

        graph = SqliteBundleKnowledgeGraph(bundle_dir)
        if graph.get_concepts():
            return graph, failed
    except Exception:  # noqa: BLE001 - staging preview must not break the published graph tab.
        return None, None
    return None, None


def _render_concept_actions(
    sel: str,
    knowledge_graph,
    doc_index: dict,
    topics_catalog,
) -> None:
    """Action row + related-document cards for the selected concept."""
    concepts = knowledge_graph.get_concepts()
    raw = concepts.get(sel)
    info = raw if isinstance(raw, dict) else {}
    desc = str(info.get("description") or "")
    lvl = info.get("level") or "—"
    prereqs = knowledge_graph.get_prerequisites(sel)
    related_docs = knowledge_graph.get_related_documents(sel)
    topic_hit = _find_topic_for_concept(sel, topics_catalog)

    st.markdown(f"**{sel}**")
    meta_cols = st.columns(2)
    with meta_cols[0]:
        st.caption(f"Level: {lvl}")
    with meta_cols[1]:
        st.caption(f"Связанных документов: {len(related_docs)}")
    if desc:
        st.write(desc)
    if prereqs:
        st.markdown("**Prerequisites**")
        _render_chip_row(prereqs)

    evidence = _concept_evidence_ledger(sel, info, prereqs, related_docs, doc_index)
    with st.expander("🧾 Почему этот узел есть", expanded=False):
        _render_concept_evidence_ledger(evidence)

    duplicate_suspects = _alias_duplicate_suspects(sel, concepts)
    with st.expander("🧬 Возможные aliases / дубли", expanded=False):
        _render_alias_duplicate_suspects(duplicate_suspects)

    # ── 🎓 Tutor integration (primary CTA) ──────────────────────────────
    from app.ui.session_state import PENDING_CURRENT_VIEW_KEY
    try:
        from app.knowledge_service import get_mastery_vector as _gmv
        _mv = _gmv()
        _mastery_pct = round((_mv.get(sel) or 0.0) * 100.0, 1)
    except Exception:  # noqa: BLE001
        _mastery_pct = 0.0
    _is_frontier = bool(info.get("frontier")) or (
        _mastery_pct < 80.0
        and all(
            (knowledge_graph.get_mastery_vector().get(p, 0.0) if hasattr(knowledge_graph, "get_mastery_vector") else 0.0) >= 0.8
            for p in prereqs
        )
    )

    st.markdown("**🎓 Учить с тьютором**")
    mode_col, btn_col = st.columns([3, 1])
    with mode_col:
        tutor_mode = st.radio(
            "Режим",
            options=list(_TUTOR_MODES.keys()),
            format_func=lambda k: _TUTOR_MODES[k],
            horizontal=True,
            key=f"kg_tutor_mode_{sel}",
            label_visibility="collapsed",
        )
    with btn_col:
        if st.button("▶ Начать", key=f"kg_tutor_start_{sel}", type="primary", width="stretch"):
            prompt = build_tutor_prompt_for_concept(
                sel,
                info=info,
                mastery_pct=_mastery_pct,
                prereqs=prereqs,
                related_docs_count=len(related_docs),
                is_frontier=_is_frontier,
                mode=tutor_mode,
            )
            st.session_state["tutor_pending_prompt"] = prompt
            st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")
            st.session_state["tutor_cta_action"] = f"KG:{sel}:{tutor_mode}"
            st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
            st.rerun()

    st.divider()

    # ── Existing quick actions ────────────────────────────────────────
    action_cols = st.columns(3)
    with action_cols[0]:
        if st.button(
            "Открыть тему",
            key=f"kg_open_topic_{sel}",
            width="stretch",
            disabled=not isinstance(topic_hit, dict),
        ):
            if isinstance(topic_hit, dict):
                st.session_state["active_topic_id"] = topic_hit.get("topic_id")
                st.session_state["current_view"] = "Темы"
                st.rerun()
    with action_cols[1]:
        if st.button(
            "Собрать synthesis",
            key=f"kg_synth_{sel}",
            width="stretch",
            disabled=not related_docs,
        ):
            try:
                synthesis_result = _run_synthesis_for_paths(
                    [str(path) for path in related_docs],
                    topic_name=sel,
                )
                st.session_state["last_synthesis"] = synthesis_result
                st.session_state["current_view"] = "Темы"
                st.rerun()
            except Exception as e:  # noqa: BLE001 - robust UI fallback for synthesis assembly error
                st.error(f"Ошибка synthesis: {_format_request_error(e)}")
    with action_cols[2]:
        if st.button(
            "К плану",
            key=f"kg_plan_{sel}",
            width="stretch",
            disabled=not isinstance(topic_hit, dict),
        ):
            if isinstance(topic_hit, dict):
                st.session_state["active_topic_id"] = topic_hit.get("topic_id")
                st.session_state["current_view"] = "Темы"
                st.rerun()

    st.markdown("**Связанные документы**")
    if related_docs:
        query_text = " ".join(part for part in [sel, desc] if part)

        # ── «Живой конспект»: собрать всё по концепту + статус корзины ──
        wb_cols = st.columns([3, 2])
        with wb_cols[0]:
            if st.button("➕ Собрать всё по концепту", key=f"kg_wb_all_{sel}", width="stretch"):
                added, duplicates = _collect_concept_sections_to_workbench(
                    concept=sel,
                    related_docs=list(related_docs),
                    doc_index=doc_index,
                    base_query=query_text,
                )
                if added or duplicates:
                    st.toast(
                        f"В рабочий конспект: +{added}" + (f" (уже было: {duplicates})" if duplicates else ""),
                        icon="📚",
                    )
                else:
                    st.toast("Подходящих разделов не нашлось — возможно, конспекты ещё не созданы.", icon="ℹ️")
        with wb_cols[1]:
            try:
                from app import workbench_service

                if workbench_service.WORKBENCH_SECTIONS_KEY not in st.session_state:
                    st.session_state[workbench_service.WORKBENCH_SECTIONS_KEY] = workbench_service.load_rows()
                wb_count = len(_workbench_state_rows())
            except Exception:  # noqa: BLE001 - счётчик корзины не должен ломать панель
                wb_count = 0
            if st.button(f"📚 Живой конспект ({wb_count})", key=f"kg_wb_open_{sel}", width="stretch"):
                # PENDING_CURRENT_VIEW_KEY, не прямая запись: current_view — ключ уже
                # инстанцированного st.selectbox в main.py, прямая запись после него
                # кидает StreamlitAPIException (см. app/ui/session_state.py).
                from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

                st.session_state[PENDING_CURRENT_VIEW_KEY] = "Живой конспект"
                st.rerun()

        for doc_idx, rel_path in enumerate(related_docs):
            doc_meta = doc_index.get(str(rel_path), {})
            title = (
                doc_meta.get("relative_path")
                or doc_meta.get("file_name")
                or str(rel_path)
            )
            meta = " | ".join(
                part
                for part in [
                    str(doc_meta.get("doc_type") or "").strip(),
                    str(doc_meta.get("difficulty") or "").strip(),
                ]
                if part
            )
            summary = str(doc_meta.get("summary") or "Нет summary для документа.")
            st.markdown(
                f"""
                <div class="doc-card">
                    <div class="doc-path">{title}</div>
                    <div class="doc-meta">{meta or 'document'}</div>
                    <div>{summary[:260]}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            _render_document_section_workbench_buttons(
                path=str(title),
                query_text=" ".join(
                    part
                    for part in [query_text, " ".join(doc_meta.get("key_concepts") or [])]
                    if part
                ),
                concept=sel,
                key=f"kg_wb_{sel}_{doc_idx}",
            )
    else:
        st.caption("Для этой концепции пока нет привязанных документов.")


def _render_classic_agraph(knowledge_graph, learned_set: set[str]) -> None:
    """Legacy streamlit-agraph view (fallback + click-to-select)."""
    from app.visualization_service import vis_service

    try:
        from streamlit_agraph import Config, agraph
    except ImportError:
        st.caption("`streamlit-agraph` не установлен — классический вид недоступен.")
        return

    filter_level = st.selectbox(
        "Уровень",
        ["all", "beginner", "intermediate", "advanced"],
        index=0,
        key="kg_filter_level",
    )
    nodes, edges = vis_service.get_knowledge_graph_nodes_edges(
        knowledge_graph,
        filter_level,
        learned_set,
    )
    if not nodes:
        st.info("Нет узлов для выбранного уровня фильтра.")
        return
    config = Config(
        width=1200,
        height=620,
        directed=True,
        physics=False,
        hierarchical=True,
        nodeHighlightBehavior=True,
        highlightColor="#FF5722",
        collapsible=True,
        labelProperty="label",
    )
    visible_ids = {n.id for n in nodes}
    picked = agraph(nodes=nodes, edges=edges, config=config)
    if picked is not None and picked != "":
        pid = picked.get("id") or picked.get("label") if isinstance(picked, dict) else picked
        if pid is not None and str(pid) in visible_ids:
            st.session_state["kg_selected_concept"] = str(pid)
            st.session_state["kg_action_concept"] = str(pid)
            st.rerun()


def _render_knowledge_graph_tab() -> None:
    """Beautiful D3 knowledge graph + concept actions + classic fallback."""
    from app.knowledge_service import get_mastery_vector
    from app.knowledge_service import knowledge_graph as active_knowledge_graph

    st.markdown('<div class="panel">', unsafe_allow_html=True)
    _render_panel_header(
        "Knowledge Graph",
        "Заливка — уровень • кольцо — mastery % • пульсация — доступно • "
        "клик по узлу — детали, prerequisites и документы",
    )

    _render_tutor_orchestration_snapshot_expander(key_prefix="kg", show_focus_concept=True)
    publish_status = _render_graph_publish_status()

    if "tutor_learned_concepts" not in st.session_state:
        st.session_state["tutor_learned_concepts"] = []

    knowledge_graph = active_knowledge_graph
    concepts = knowledge_graph.get_concepts()
    typed_relations = knowledge_graph.get_typed_relations()
    preview_graph, preview_info = _load_staging_preview_graph(publish_status)
    if not concepts and preview_graph is not None:
        knowledge_graph = preview_graph
        concepts = knowledge_graph.get_concepts()
        typed_relations = knowledge_graph.get_typed_relations()
        from app.graph_publish_status import LEARNER_MAP_PREVIEW_WARNING

        st.warning(LEARNER_MAP_PREVIEW_WARNING, icon="⚠️")
    learned_set = collect_kg_learned_set(concepts)

    if not concepts:
        st.info(
            "Нет данных для графа: пустой или отсутствующий `data/concept_graph.json` "
            "и нет строк в **quiz_mastery**. Создайте граф с полем `concepts` "
            "(и `prerequisites`) или пройдите квизы — концепты подтянутся из прогресса."
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # Mastery + document index for rich, learning-native rendering.
    try:
        mastery_vector = get_mastery_vector()
    except Exception:  # noqa: BLE001 - mastery is optional enrichment
        mastery_vector = {}
    topics_catalog = _load_topics_catalog(force=False)
    doc_index = _topic_documents_index(topics_catalog)

    source_paths: list[str] = []
    try:
        from app.ui.study_scope import get_active_scope

        scope = get_active_scope()
        if isinstance(scope, dict):
            source_paths = [
                str(path).strip()
                for path in (scope.get("source_paths") or [])
                if str(path).strip()
            ]
    except Exception:  # noqa: BLE001 - scope optional for graph render
        source_paths = []

    # P1: use scoped due with high scan (5000) so that due for nodes in this graph
    # are not missed when there are many due outside the active bundle.
    due_reviews: list[dict] = []
    try:
        from app.learner_state_scope import filter_due_reviews_for_kg
        due_reviews = filter_due_reviews_for_kg(
            knowledge_graph, limit=200, scan_limit=5000
        )
    except Exception:  # noqa: BLE001
        pass

    payload = render_d3_knowledge_graph(
        concepts,
        mastery_vector=mastery_vector,
        learned_set=learned_set,
        doc_index=doc_index,
        typed_relations=typed_relations,
        source_paths=source_paths,
        due_reviews=due_reviews,
        height=740,
    )

    # ── Concept action selector (preserves Streamlit-side actions) ──
    stats = payload.get("stats", {})
    # B1: "концептов" uses total_concepts (excludes lesson nodes) — same value the Mission
    # Control KG card shows, both sourced from compute_kg_counters / build_kg_payload.
    st.caption(
        f"📊 {stats.get('total_concepts', stats.get('total', 0))} концептов · {stats.get('avg_mastery', 0)}% ср. mastery · "
        f"{stats.get('learned', 0)} освоено · {stats.get('frontier', 0)} доступно · "
        f"{stats.get('clusters', 0)} кластеров"
    )
    st.download_button(
        "⬇ Скачать живую карту (HTML)",
        data=build_kg_html(payload),
        file_name="knowledge_graph.html",
        mime="text/html",
        key="kg_download_live_html",
        help="Самодостаточная интерактивная карта курса для локального открытия без приложения.",
    )

    # 3D hall export: same payload; first frame = day route; worth = rank/reason (not height).
    st.download_button(
        "⬇ Скачать 3D-зал (HTML)",
        data=build_kg_3d_html(payload),
        file_name="knowledge_graph_3d.html",
        mime="text/html",
        key="kg_download_3d_html",
        help=(
            "Офлайн 3D-зал: первый кадр — маршрут дня (не весь граф); "
            "этажи по урокам (precedes); worth — ранг и причина, не высота; "
            "управляемый тур по остановкам. Export read-only (без действий)."
        ),
    )

    with st.expander("🔬 Качество графа", expanded=False):
        _render_graph_quality_audit(
            _graph_quality_audit(concepts, payload, list(typed_relations or []))
        )

    node_ids = [n["id"] for n in payload.get("nodes", [])]

    # ── 3D hall action bridge (G0/G1): _kg3d query-param only ──────────
    # Must run before embedding so collect updates inventory view-model args
    # and the one-shot action_result is available on this same render.
    action_result = _consume_and_apply_kg_3d_query(
        node_ids=node_ids,
        knowledge_graph=knowledge_graph,
        doc_index=doc_index,
    )
    if action_result is None:
        pending_result = st.session_state.pop(KG_3D_ACTION_RESULT_KEY, None)
        action_result = pending_result if isinstance(pending_result, dict) else None

    # Embedded 3D hall (C1): live payload + action bridge. Export remains download above.
    try:
        from app import workbench_service

        if workbench_service.WORKBENCH_SECTIONS_KEY not in st.session_state:
            st.session_state[workbench_service.WORKBENCH_SECTIONS_KEY] = (
                workbench_service.load_rows()
            )
    except Exception:  # noqa: BLE001 - workbench optional for hall render
        pass
    collected_ids = _workbench_collected_concept_ids()
    try:
        wb_count = len(_workbench_state_rows())
    except Exception:  # noqa: BLE001
        wb_count = 0
    nonce = ensure_kg_3d_session_nonce(st.session_state)
    # U2 doors: sections for day_route (+ focused concept) only — keep index work bounded.
    route_for_vm = list(payload.get("day_route") or [])
    focus_for_vm = str(
        st.session_state.get("kg_selected_concept")
        or st.session_state.get("kg_action_concept")
        or ""
    ).strip()
    vm_ids = [str(x) for x in route_for_vm if str(x or "").strip()]
    if focus_for_vm and focus_for_vm not in vm_ids:
        vm_ids.append(focus_for_vm)
    concept_sections = _concept_sections_view_model(
        concept_ids=vm_ids,
        knowledge_graph=knowledge_graph,
        doc_index=doc_index if isinstance(doc_index, dict) else {},
    )
    show_onboarding = not bool(st.session_state.get("kg_3d_onboard_shown"))
    if show_onboarding:
        st.session_state["kg_3d_onboard_shown"] = True
    st.markdown("##### 🏛 3D-зал (embedded)")
    st.caption(
        "Memory Run · ▶ Начать (Quiz) · В конспект · Открыть раздел (Obsidian) · "
        "✓ = был в квизе · ◆ = в Живом конспекте · «?» — правила зала."
    )
    # Selection only from component value (string concept id). Actions arrive solely
    # via _kg3d query-param above — never dual-delivered through setComponentValue.
    hall_selected = render_kg_3d_hall(
        payload,
        session_nonce=nonce,
        collected_concept_ids=collected_ids,
        workbench_count=wb_count,
        action_result=action_result,
        concept_sections=concept_sections,
        show_onboarding=show_onboarding,
        height=720,
        key="kg_3d_hall_component",
    )
    if hall_selected and hall_selected in node_ids:
        st.session_state["kg_selected_concept"] = hall_selected
        st.session_state["kg_action_concept"] = hall_selected

    # ── D3 → Streamlit concept bridge ──────────────────────────────────
    # The D3 graph is rendered as a Streamlit custom component. On node click,
    # the component returns the selected concept id to Python; `_kgc` remains as
    # a legacy URL fallback for older single-iframe rendering.
    component_concept = str(payload.get("selected_concept") or "").strip()
    _kgc_param = _query_param_first_str("_kgc")
    bridged_concept = component_concept if component_concept in node_ids else _kgc_param
    if hall_selected and hall_selected in node_ids:
        bridged_concept = hall_selected

    # Default to a "frontier" (ready-to-learn) concept when available.
    default_sel = next(
        (n["id"] for n in payload.get("nodes", []) if n.get("frontier")),
        node_ids[0] if node_ids else None,
    )
    prev = st.session_state.get("kg_selected_concept")
    if prev in node_ids:
        default_sel = prev
    if st.session_state.get("kg_action_concept") not in node_ids and default_sel in node_ids:
        st.session_state.setdefault("kg_action_concept", default_sel)

    if bridged_concept and bridged_concept in node_ids:
        st.session_state["kg_selected_concept"] = bridged_concept
        st.session_state["kg_action_concept"] = bridged_concept
        if _kgc_param or component_concept:
            st.toast(f"📍 Концепт из графа: **{bridged_concept}**", icon="🕸")
        if _kgc_param:
            st.query_params.pop("_kgc", None)

    with st.expander("⚡ Действия с концептом", expanded=True):
        if node_ids:
            sel = st.selectbox(
                "Концепт",
                node_ids,
                key="kg_action_concept",
            )
            st.session_state["kg_selected_concept"] = sel
            _render_concept_actions(sel, knowledge_graph, doc_index, topics_catalog)

    with st.expander("🔀 Классический вид (agraph)", expanded=False):
        _render_classic_agraph(knowledge_graph, learned_set)

    st.markdown("</div>", unsafe_allow_html=True)
