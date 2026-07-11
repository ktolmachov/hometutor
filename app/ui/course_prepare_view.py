"""Course preparation pipeline UI for active StudyScope."""
from __future__ import annotations

import html
from typing import Any

import streamlit as st

from app import user_state
from app.course_cache import (
    GraphStatusView,
    course_scope_hash,
    detect_stale_graph_binding,
    load_course_artifact,
    normalize_source_paths,
    resolve_graph_status,
    save_course_artifact,
)
from app.ui.study_scope import get_active_scope
from app.ui_client import fetch_json

_INDEXED_CHIP_RU: dict[bool, tuple[str, str]] = {
    True: ("Документы: проиндексированы", "course-indexed-status-ready"),
    False: ("Документы: нужна индексация", "course-indexed-status-pending"),
}

_GRAPH_BADGE_TONE: dict[str, str] = {
    "ready": "success",
    "pending": "info",
    "unavailable": "warning",
}

_QUALITY_GATE_LABELS_RU: dict[str, str] = {
    "normalized_concepts": "Нормализованные концепты",
    "semantic_relations": "Семантические связи",
    "cross_doc_relations": "Междокументные связи",
    "concept_evidence": "Покрытие evidence (концепты)",
    "relation_evidence": "Покрытие evidence (связи)",
    "orphan_rate": "Доля сирот",
    "dangling_refs": "Висячие ссылки",
    "prerequisite_cycles": "Циклы prerequisites",
    "filename_fallback": "Узлы filename-fallback",
    "docs_participating": "Участие документов",
    "min_documents": "Минимум документов",
}


def _learning_plan_payload(
    *,
    topic_name: str,
    documents: list[str],
    goal: str,
    level: str,
    time_budget_hours: float,
    known_topics: list[str],
    user_progress: bool,
) -> dict[str, Any]:
    return {
        "topic": topic_name,
        "documents": documents,
        "goal": goal,
        "level": level,
        "time_budget_hours": time_budget_hours,
        "known_topics": known_topics,
        "user_progress": user_progress,
    }


def _indexed_chip_html(*, indexed: bool) -> str:
    label, testid = _INDEXED_CHIP_RU[indexed]
    return (
        f'<span data-testid="{html.escape(testid)}" class="course-indexed-chip">'
        f"{html.escape(label)}</span>"
    )


def _graph_badge_html(view: GraphStatusView) -> str:
    tone = _GRAPH_BADGE_TONE.get(view.status, "warning")
    return (
        f'<span data-testid="{html.escape(view.testid)}" '
        f'class="graph-status-badge graph-status-{html.escape(tone)}">'
        f"{html.escape(view.caption_ru)}</span>"
    )


def _activation_status_row_html(view: GraphStatusView) -> str:
    return f'<div class="course-activation-status-row">{_indexed_chip_html(indexed=view.indexed)}{_graph_badge_html(view)}</div>'


def _get_index_stats() -> dict | None:
    stats = st.session_state.get("_ui_index_stats_tab")
    return stats if isinstance(stats, dict) else None


def _get_active_generation_id() -> str:
    cached = st.session_state.get("active_generation_id")
    if isinstance(cached, str) and cached.strip():
        return cached.strip()
    try:
        from app.index_registry import get_active_generation_view

        generation_id = str(get_active_generation_view().generation_id or "").strip()
        if generation_id:
            st.session_state["active_generation_id"] = generation_id
        return generation_id
    except Exception:  # noqa: BLE001 - UI boundary: stale banner skipped when registry unavailable.
        return ""


def _artifact_binding(artifact: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(artifact, dict):
        return {}
    return {
        "generation_id": artifact.get("generation_id"),
        "scope_hash": artifact.get("scope_hash"),
        "graph_quality_summary": artifact.get("graph_quality_summary"),
    }


def resolve_graph_refresh_payload(
    *,
    session_refresh: dict[str, Any] | None,
    artifact: dict[str, Any] | None,
    active_generation_id: str,
) -> dict[str, Any] | None:
    """Pure resolver: session ingest refresh when generation matches, else artifact binding."""
    active_gen = str(active_generation_id or "").strip()
    if isinstance(session_refresh, dict) and session_refresh:
        refresh_gen = str(session_refresh.get("generation_id") or "").strip()
        if refresh_gen and (not active_gen or refresh_gen == active_gen):
            return session_refresh
    if not isinstance(artifact, dict):
        return None
    summary = artifact.get("graph_quality_summary")
    if not isinstance(summary, dict) or not summary:
        return None
    return {
        "ok": True,
        "gate_passed": bool(summary.get("gate_passed")),
        "published": bool(summary.get("published")),
        "generation_id": str(artifact.get("generation_id") or summary.get("generation_id") or ""),
        "scope_hash": str(artifact.get("scope_hash") or summary.get("scope_hash") or ""),
        "quality_report": summary,
    }


def resolve_quality_report_payload(
    *,
    session_refresh: dict[str, Any] | None,
    artifact: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return compact quality summary dict for UI rendering."""
    if isinstance(session_refresh, dict):
        report = session_refresh.get("quality_report")
        if isinstance(report, dict) and report.get("gates") is not None:
            return report
    if isinstance(artifact, dict):
        summary = artifact.get("graph_quality_summary")
        if isinstance(summary, dict) and summary.get("gates") is not None:
            return summary
    if isinstance(session_refresh, dict):
        report = session_refresh.get("quality_report")
        if isinstance(report, dict) and report:
            return report
    if isinstance(artifact, dict):
        summary = artifact.get("graph_quality_summary")
        if isinstance(summary, dict) and summary:
            return summary
    return None


def is_stale_graph_binding_visible(
    *,
    artifact: dict[str, Any] | None,
    active_generation_id: str,
    current_scope_hash: str,
) -> bool:
    if not isinstance(artifact, dict):
        return False
    return detect_stale_graph_binding(
        artifact_generation_id=str(artifact.get("generation_id") or ""),
        active_generation_id=active_generation_id,
        artifact_scope_hash=str(artifact.get("scope_hash") or ""),
        current_scope_hash=current_scope_hash,
    )


def build_graph_quality_report_html(report: dict[str, Any]) -> str:
    """Compact HTML table with gate metrics (data-testid for UI contract tests)."""
    gates = report.get("gates")
    if not isinstance(gates, list):
        raise ValueError("quality report missing gates list")

    rows: list[str] = []
    for gate in gates[:10]:
        if not isinstance(gate, dict):
            continue
        name = str(gate.get("name") or "")
        label = _QUALITY_GATE_LABELS_RU.get(name, name)
        required = html.escape(str(gate.get("required") or ""))
        actual = html.escape(str(gate.get("actual") or ""))
        passed = bool(gate.get("passed"))
        status = "✓" if passed else "✗"
        rows.append(
            f"<tr><td>{html.escape(label)}</td><td>{actual}</td>"
            f"<td>{required}</td><td>{status}</td></tr>"
        )

    fail_reasons = [str(r) for r in (report.get("fail_reasons") or []) if str(r).strip()]
    fail_html = ""
    if fail_reasons:
        visible = fail_reasons[:5]
        bullets = "".join(f"<li>{html.escape(line)}</li>" for line in visible)
        overflow = max(0, len(fail_reasons) - len(visible))
        extra = f"<li>ещё {overflow}</li>" if overflow else ""
        fail_html = f"<ul class=\"graph-quality-fail-reasons\">{bullets}{extra}</ul>"

    return (
        f'<div data-testid="graph-quality-report" class="graph-quality-report">'
        f'<table class="graph-quality-report-table"><thead><tr>'
        f"<th>Метрика</th><th>Факт</th><th>Порог</th><th>Статус</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        f"{fail_html}</div>"
    )


def _graph_status_cache_key(
    scope: dict[str, Any],
    documents: list[str],
    *,
    generation_id: str,
) -> tuple[str, str, str]:
    scope_id = str(scope.get("id") or scope.get("folder_rel") or "")
    return scope_id, course_scope_hash(documents), generation_id


def _quality_cache_key(
    scope: dict[str, Any],
    documents: list[str],
    *,
    generation_id: str,
) -> tuple[str, str, str]:
    return _graph_status_cache_key(scope, documents, generation_id=generation_id)


def _clear_graph_caches() -> None:
    for key in ("course_graph_status_cache", "course_graph_quality_cache"):
        if key in st.session_state:
            del st.session_state[key]


def _resolve_graph_refresh_for_scope(
    *,
    scope: dict[str, Any],
    documents: list[str],
    artifact: dict[str, Any] | None,
) -> dict[str, Any] | None:
    session_refresh = st.session_state.get("last_ingest_graph_refresh")
    refresh = session_refresh if isinstance(session_refresh, dict) else None
    return resolve_graph_refresh_payload(
        session_refresh=refresh,
        artifact=artifact,
        active_generation_id=_get_active_generation_id(),
    )


def _resolve_quality_report_for_scope(
    *,
    scope: dict[str, Any],
    documents: list[str],
    artifact: dict[str, Any] | None,
) -> dict[str, Any] | None:
    generation_id = _get_active_generation_id()
    cache_key = _quality_cache_key(scope, documents, generation_id=generation_id)
    cache = st.session_state.get("course_graph_quality_cache")
    if isinstance(cache, dict):
        if (
            cache.get("scope_id") == cache_key[0]
            and cache.get("path_hash") == cache_key[1]
            and cache.get("generation_id") == cache_key[2]
            and isinstance(cache.get("report"), dict)
        ):
            return cache["report"]

    session_refresh = st.session_state.get("last_ingest_graph_refresh")
    refresh = session_refresh if isinstance(session_refresh, dict) else None
    report = resolve_quality_report_payload(session_refresh=refresh, artifact=artifact)
    if isinstance(report, dict):
        st.session_state["course_graph_quality_cache"] = {
            "scope_id": cache_key[0],
            "path_hash": cache_key[1],
            "generation_id": cache_key[2],
            "report": report,
        }
    return report


def _resolve_graph_status_for_scope(
    *,
    scope: dict[str, Any],
    documents: list[str],
    index_stats: dict | None,
    artifact: dict[str, Any] | None,
) -> GraphStatusView:
    generation_id = _get_active_generation_id()
    scope_id, path_hash, gen_key = _graph_status_cache_key(
        scope,
        documents,
        generation_id=generation_id,
    )
    cache = st.session_state.get("course_graph_status_cache")
    if isinstance(cache, dict):
        if (
            cache.get("scope_id") == scope_id
            and cache.get("path_hash") == path_hash
            and cache.get("generation_id") == gen_key
        ):
            return GraphStatusView(
                status=cache["status"],
                indexed=bool(cache.get("indexed")),
                prerequisite_labels=list(cache.get("prerequisite_labels") or []),
                caption_ru=str(cache.get("caption_ru") or ""),
                detail_ru=str(cache.get("detail_ru") or ""),
                testid=str(cache.get("testid") or "graph-status-badge-pending"),
                has_prerequisite_cycles=bool(cache.get("has_prerequisite_cycles")),
            )

    graph_refresh = _resolve_graph_refresh_for_scope(
        scope=scope,
        documents=documents,
        artifact=artifact,
    )
    view = resolve_graph_status(
        source_paths=documents,
        index_stats=index_stats,
        graph_refresh=graph_refresh,
        artifact_binding=_artifact_binding(artifact),
        active_generation_id=generation_id,
    )
    st.session_state["course_graph_status_cache"] = {
        "scope_id": scope_id,
        "path_hash": path_hash,
        "generation_id": gen_key,
        "status": view.status,
        "indexed": view.indexed,
        "prerequisite_labels": list(view.prerequisite_labels),
        "caption_ru": view.caption_ru,
        "detail_ru": view.detail_ru,
        "testid": view.testid,
        "has_prerequisite_cycles": view.has_prerequisite_cycles,
    }
    return view


def _render_graph_publish_status(*, key_prefix: str) -> None:
    """Show which graph bundle is actually published/read and why staging may be blocked."""
    try:
        from app.graph_publish_status import get_graph_publish_status

        status = get_graph_publish_status()
    except Exception:  # noqa: BLE001 - UI diagnostics must degrade, not block course prep.
        st.caption("Статус публикации graph bundle временно недоступен.")
        return

    active = status.get("active") if isinstance(status.get("active"), dict) else {}
    previous = status.get("previous") if isinstance(status.get("previous"), dict) else {}
    reader_source = str(status.get("reader_source") or "legacy")
    reader_generation = str(status.get("reader_generation_id") or "")

    if reader_source == "active":
        st.success(f"Graph read-path: опубликованный bundle active generation `{reader_generation}`.")
    elif reader_source == "previous":
        st.warning(
            "Graph read-path использует previous published bundle: "
            f"`{reader_generation}`. Для active generation "
            f"`{active.get('generation_id') or 'unknown'}` promoted bundle не найден.",
            icon="⚠️",
        )
    else:
        st.warning(
            "Graph read-path сейчас в legacy/empty режиме: promoted bundle для active generation не найден.",
            icon="⚠️",
        )

    active_report = active.get("report") if isinstance(active.get("report"), dict) else None
    if active.get("generation_id"):
        state = "есть" if active.get("exists") else "нет"
        st.caption(f"Active generation: `{active.get('generation_id')}` · promoted bundle: {state}")
    if previous.get("generation_id") and reader_source != "active":
        state = "есть" if previous.get("exists") else "нет"
        st.caption(f"Previous generation: `{previous.get('generation_id')}` · promoted bundle: {state}")
    if active_report:
        st.caption(
            "Active quality: "
            f"gate={'pass' if active_report.get('gate_passed') else 'fail'} · "
            f"published={bool(active_report.get('published'))}"
        )

    failed = status.get("latest_failed_staging")
    if not isinstance(failed, dict):
        return
    report = failed.get("report") if isinstance(failed.get("report"), dict) else {}
    fail_reasons = [str(item) for item in (report.get("fail_reasons") or []) if str(item).strip()]
    with st.expander("Почему последний staging graph не опубликован", expanded=False):
        st.caption(f"Staging bundle: `{failed.get('label')}`")
        metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
        if metrics:
            cols = st.columns(4)
            with cols[0]:
                st.metric("Concepts", int(metrics.get("concept_count") or 0))
            with cols[1]:
                st.metric("Relations", int(metrics.get("semantic_relation_count") or 0))
            with cols[2]:
                st.metric("Docs %", round(float(metrics.get("docs_participating_pct") or 0), 1))
            with cols[3]:
                st.metric("Evidence %", round(float(metrics.get("relations_with_evidence_pct") or 0), 1))
        if fail_reasons:
            st.markdown("**Блокеры publish**")
            for reason in fail_reasons[:6]:
                st.caption(f"- {reason}")
            overflow = max(0, len(fail_reasons) - 6)
            if overflow:
                st.caption(f"И ещё {overflow}")
        if st.button("Обновить статус публикации графа", key=f"{key_prefix}_refresh_publish_status"):
            _clear_graph_caches()
            st.rerun()


def _render_graph_quality_report(
    *,
    scope: dict[str, Any],
    documents: list[str],
    artifact: dict[str, Any] | None,
    key_prefix: str,
    graph_view: GraphStatusView | None,
) -> None:
    """Quality report section — loading / empty / error / populated states."""
    st.markdown("##### Отчёт качества графа")
    _render_graph_publish_status(key_prefix=key_prefix)
    current_scope_hash = course_scope_hash(documents)
    active_gen = _get_active_generation_id()

    if is_stale_graph_binding_visible(
        artifact=artifact,
        active_generation_id=active_gen,
        current_scope_hash=current_scope_hash,
    ):
        st.warning(
            "Привязка графа устарела — требуется повторная индексация с graph LLM.",
            icon="⚠️",
        )
        st.markdown(
            '<div data-testid="graph-binding-stale-banner"></div>',
            unsafe_allow_html=True,
        )

    report_error = st.session_state.pop("_course_graph_quality_report_error", None)
    if report_error:
        st.error("Не удалось загрузить отчёт качества")
        if st.button("Повторить", key=f"{key_prefix}_retry_graph_report"):
            _clear_graph_caches()
            st.session_state.pop("_course_graph_quality_report_error", None)
            st.rerun()
        return

    try:
        with st.spinner("Загружаем отчёт качества графа…"):
            report = _resolve_quality_report_for_scope(
                scope=scope,
                documents=documents,
                artifact=artifact,
            )
    except Exception:  # noqa: BLE001 - UI boundary: degrade to error state with retry.
        st.session_state["_course_graph_quality_report_error"] = True
        st.error("Не удалось загрузить отчёт качества")
        if st.button("Повторить", key=f"{key_prefix}_retry_graph_report"):
            _clear_graph_caches()
            st.session_state.pop("_course_graph_quality_report_error", None)
            st.rerun()
        return

    if not isinstance(report, dict):
        st.info("Отчёт качества графа появится после индексации с graph LLM.")
        return

    try:
        report_html = build_graph_quality_report_html(report)
    except ValueError:
        st.session_state["_course_graph_quality_report_error"] = True
        st.error("Не удалось загрузить отчёт качества")
        if st.button("Повторить", key=f"{key_prefix}_retry_graph_report"):
            _clear_graph_caches()
            st.session_state.pop("_course_graph_quality_report_error", None)
            st.rerun()
        return

    st.markdown(report_html, unsafe_allow_html=True)
    published = bool(report.get("published"))
    pub_label = "Опубликован" if published else "Не опубликован (только диагностика)"
    st.caption(pub_label)

    if bool(report.get("gate_passed")):
        st.success("Граф прошёл проверку качества и опубликован.")
    elif graph_view is not None and graph_view.status == "pending":
        st.caption(graph_view.detail_ru or "Граф не прошёл проверку качества")


def _render_course_activation_status(
    *,
    scope: dict[str, Any],
    documents: list[str],
    index_stats: dict | None,
    artifact: dict[str, Any] | None,
) -> GraphStatusView | None:
    """Indexed chip, graph badge, prerequisites — above prepare CTA."""
    try:
        with st.spinner("Проверяем индекс и граф знаний…"):
            view = _resolve_graph_status_for_scope(
                scope=scope,
                documents=documents,
                index_stats=index_stats,
                artifact=artifact,
            )
    except Exception:  # noqa: BLE001 - UI boundary: degrade to indexed-only badge.
        view = GraphStatusView(
            status="unavailable",
            indexed=False,
            prerequisite_labels=[],
            caption_ru="Граф знаний: недоступен",
            detail_ru="Курс остаётся в indexed-only",
            testid="graph-status-badge-unavailable",
        )
        st.error("Не удалось определить статус графа")
        st.caption("Курс остаётся в indexed-only")

    st.markdown(_activation_status_row_html(view), unsafe_allow_html=True)
    st.caption(view.detail_ru)

    labels = list(view.prerequisite_labels or [])
    st.markdown("**Prerequisites**")
    if labels:
        bullets = "\n".join(f"- {html.escape(line)}" for line in labels[:8])
        st.markdown(bullets, unsafe_allow_html=True)
        overflow = max(0, len(labels) - 8)
        if overflow:
            st.caption(f"И ещё {overflow} концептов")
    elif view.status == "ready":
        st.markdown("Список prerequisites пока пуст")
    if view.status == "ready" and view.has_prerequisite_cycles:
        st.caption("В графе есть циклы prerequisites — порядок шагов может отличаться от строгой цепочки.")
    return view


def _prepare_complete_label(view: GraphStatusView | None) -> str:
    if view is None:
        return "Курс подготовлен"
    indexed_ru = "документы проиндексированы" if view.indexed else "нужна индексация"
    return f"Курс подготовлен · {indexed_ru} · {view.caption_ru}"


def _show_cached_artifact(artifact: dict[str, Any]) -> None:
    plan = artifact.get("learning_plan") if isinstance(artifact, dict) else None
    if not isinstance(plan, dict):
        return
    st.session_state["last_learning_plan"] = plan
    st.success("Готовый план курса загружен из кэша.")


def render_course_prepare_view(
    *,
    topic: dict[str, Any],
    goal: str,
    level: str,
    time_budget_hours: float,
    known_topics: list[str],
    user_progress: bool,
    key_prefix: str,
) -> None:
    """Render one-click course preparation for the active course scope."""
    scope = get_active_scope()
    if not scope:
        return

    documents = normalize_source_paths(list(scope.get("source_paths") or []))
    if not documents:
        st.info("Активный курс есть, но в нём нет списка документов для построения плана.")
        return

    topic_name = str(topic.get("topic_name") or scope.get("title") or "Активный курс")
    course_title = str(scope.get("title") or scope.get("folder_rel") or topic_name)
    st.markdown("##### Подготовить активный курс")
    st.caption(
        f"{course_title}: {len(documents)} документ(ов). "
        "Пайплайн покажет состав курса, соберёт обзор и построит план только по этим источникам."
    )

    cached = load_course_artifact(documents)
    graph_view = _render_course_activation_status(
        scope=scope,
        documents=documents,
        index_stats=_get_index_stats(),
        artifact=cached,
    )

    _render_graph_quality_report(
        scope=scope,
        documents=documents,
        artifact=cached,
        key_prefix=key_prefix,
        graph_view=graph_view,
    )

    cache_cols = st.columns([2, 1])
    with cache_cols[0]:
        if st.button("Подготовить курс", key=f"{key_prefix}_prepare_course", width="stretch", type="primary"):
            if cached:
                _show_cached_artifact(cached)
                return

            try:
                with st.status("Готовлю курс", expanded=True) as status:
                    st.write(f"Шаг 1/4: найдено документов курса: {len(documents)}")
                    st.write("Шаг 2/4: собираю краткий обзор по активному scope")
                    synthesis = fetch_json(
                        "POST",
                        "/synthesize",
                        timeout=120,
                        json={"topic": topic_name, "documents": documents},
                    )
                    st.write("Шаг 3/4: строю учебный план только по документам курса")
                    payload = _learning_plan_payload(
                        topic_name=topic_name,
                        documents=documents,
                        goal=goal,
                        level=level,
                        time_budget_hours=time_budget_hours,
                        known_topics=known_topics,
                        user_progress=user_progress,
                    )
                    learning_plan = fetch_json("POST", "/learning-plan", timeout=120, json=payload)
                    learning_plan["selection_mode"] = "course_scope"
                    learning_plan["selected_documents"] = documents
                    st.write("Шаг 4/4: подготовил превью карточек для следующего шага")
                    artifact = save_course_artifact(
                        documents,
                        {
                            "course_title": course_title,
                            "topic_name": topic_name,
                            "synthesis": synthesis,
                            "learning_plan": learning_plan,
                            "flashcards_preview": _preview_cards_from_plan(learning_plan),
                        },
                    )
                    st.session_state["last_course_prepare"] = artifact
                    st.session_state["last_learning_plan"] = learning_plan
                    status.update(label=_prepare_complete_label(graph_view), state="complete")
                    st.success("План курса готов. Ниже открылся маршрут по активному курсу.")
            except Exception as exc:  # noqa: BLE001 - UI boundary: show API/persistence error without crashing Streamlit.
                st.error(f"Не удалось подготовить курс: {exc}")
    with cache_cols[1]:
        if cached and st.button("Открыть кэш", key=f"{key_prefix}_open_cached_course", width="stretch", type="secondary"):
            _show_cached_artifact(cached)

    preview = (cached or st.session_state.get("last_course_prepare") or {}).get("flashcards_preview") or []
    if preview:
        with st.expander("Превью карточек по плану", expanded=False):
            for idx, item in enumerate(preview[:5], 1):
                st.markdown(f"{idx}. **{item}**")


def _preview_cards_from_plan(learning_plan: dict[str, Any]) -> list[str]:
    plan_text = str(learning_plan.get("plan") or "")
    parsed_steps = user_state.learning_plan_steps_from_markdown(plan_text)
    if parsed_steps:
        return parsed_steps[:7]
    lines = [line.strip(" -0123456789.").strip() for line in plan_text.splitlines()]
    return [line for line in lines if len(line) >= 8][:7]


__all__ = [
    "build_graph_quality_report_html",
    "is_stale_graph_binding_visible",
    "render_course_prepare_view",
    "resolve_graph_refresh_payload",
    "resolve_quality_report_payload",
]
