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

import streamlit as st

from app.knowledge_text import tokenize_filtered
from app.ui.answer_helpers import run_synthesis_for_paths as _run_synthesis_for_paths
from app.ui.helpers import format_request_error as _format_request_error
from app.ui.home_hub import (
    _find_topic_for_concept,
    _topic_documents_index,
)
from app.ui.knowledge_graph_d3 import render_d3_knowledge_graph
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


def _collect_learned_set(concepts: dict) -> set[str]:
    learned_set = set(st.session_state.get("tutor_learned_concepts") or [])
    for name, data in concepts.items():
        if isinstance(data, dict) and data.get("learned"):
            learned_set.add(name)
    return learned_set


def _workbench_state_rows(state=None) -> list[dict]:
    from app import workbench_service

    source = st.session_state if state is None else state
    return workbench_service.normalize_runtime_rows(
        list(source.get(workbench_service.WORKBENCH_SECTIONS_KEY) or [])
    )


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
                "detail": summary[:220] if summary else "Документ связан с концептом в graph bundle.",
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
    from app.knowledge_service import knowledge_graph

    st.markdown('<div class="panel">', unsafe_allow_html=True)
    _render_panel_header(
        "Knowledge Graph",
        "Заливка — уровень • кольцо — mastery % • пульсация — готово учить • "
        "клик по узлу — детали, prerequisites и документы",
    )

    _render_tutor_orchestration_snapshot_expander(key_prefix="kg", show_focus_concept=True)

    if "tutor_learned_concepts" not in st.session_state:
        st.session_state["tutor_learned_concepts"] = []

    concepts = knowledge_graph.get_concepts()
    typed_relations = knowledge_graph.get_typed_relations()
    learned_set = _collect_learned_set(concepts)

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

    payload = render_d3_knowledge_graph(
        concepts,
        mastery_vector=mastery_vector,
        learned_set=learned_set,
        doc_index=doc_index,
        typed_relations=typed_relations,
        source_paths=source_paths,
        height=740,
    )

    # ── Concept action selector (preserves Streamlit-side actions) ──
    stats = payload.get("stats", {})
    st.caption(
        f"📊 {stats.get('total', 0)} концептов · {stats.get('avg_mastery', 0)}% ср. mastery · "
        f"{stats.get('learned', 0)} освоено · {stats.get('frontier', 0)} готово учить · "
        f"{stats.get('clusters', 0)} кластеров"
    )

    node_ids = [n["id"] for n in payload.get("nodes", [])]

    # ── D3 → Streamlit concept bridge ──────────────────────────────────
    # The D3 graph is rendered as a Streamlit custom component. On node click,
    # the component returns the selected concept id to Python; `_kgc` remains as
    # a legacy URL fallback for older single-iframe rendering.
    component_concept = str(payload.get("selected_concept") or "").strip()
    _kgc_param = str(st.query_params.get("_kgc") or "").strip()
    bridged_concept = component_concept if component_concept in node_ids else _kgc_param

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
