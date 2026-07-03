"""Deterministic seed questions for first-run and empty Q&A states."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Callable

import streamlit as st


def _has_materials(index_stats: Any) -> bool:
    if not isinstance(index_stats, dict):
        return False
    try:
        if int(index_stats.get("documents_count") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    return bool(index_stats.get("files"))


def _basename(path: object) -> str:
    raw = str(path or "").replace("\\", "/").strip()
    return PurePosixPath(raw).name if raw else ""


def build_seed_questions(index_stats: Any, topics_catalog: Any, first_session_artifact: Any) -> list[dict[str, str]]:
    if not _has_materials(index_stats):
        return []

    artifact_seeds = first_session_artifact.get("seed_questions") if isinstance(first_session_artifact, dict) else []
    out: list[dict[str, str]] = []
    if isinstance(artifact_seeds, list):
        for seed in artifact_seeds:
            if not isinstance(seed, dict):
                continue
            question = str(seed.get("q") or "").strip()
            if not question:
                continue
            trace = seed.get("retrieval_trace") if isinstance(seed.get("retrieval_trace"), dict) else {}
            paths = trace.get("source_paths") if isinstance(trace.get("source_paths"), list) else []
            cite = _basename(paths[0]) if paths else "обзор курса"
            out.append({"q": question, "source_label": cite})
            if len(out) == 3:
                return out

    topics = topics_catalog.get("topics") if isinstance(topics_catalog, dict) else []
    templates = (
        "Что такое {topic} — коротко и с источниками?",
        "С чего начать изучение темы «{topic}»?",
        "Какие ключевые идеи в теме «{topic}»?",
    )
    if isinstance(topics, list):
        for index, topic in enumerate(topics[:3]):
            if not isinstance(topic, dict):
                continue
            name = str(topic.get("topic_name") or "").strip()
            if not name:
                continue
            out.append({"q": templates[index % len(templates)].format(topic=name), "source_label": f"тема: {name}"})
        if out:
            return out[:3]

    files = index_stats.get("files") if isinstance(index_stats, dict) else []
    if isinstance(files, list):
        for path in files[:3]:
            name = _basename(path)
            if name:
                out.append({"q": f"О чём файл {name}?", "source_label": name})
    return out[:3]


def render_seed_question_chips(
    *,
    key_prefix: str,
    navigate_to_question: Callable[[str], None],
    index_stats: dict | None = None,
    topics_catalog: dict | None = None,
    first_session_artifact: dict | None = None,
) -> bool:
    stats = index_stats if index_stats is not None else st.session_state.get("_ui_index_stats_tab")
    topics = topics_catalog if topics_catalog is not None else st.session_state.get("topics_catalog")
    artifact = first_session_artifact if first_session_artifact is not None else st.session_state.get("first_session_artifact_cache")
    questions = build_seed_questions(stats, topics, artifact)
    if not questions:
        return False
    st.markdown("#### Попробуйте спросить:")
    cols = st.columns(len(questions), gap="medium")
    for index, (col, item) in enumerate(zip(cols, questions, strict=True)):
        question = item["q"]
        with col:
            if st.button(question, key=f"{key_prefix}_seed_question_{index}", type="secondary", width="stretch"):
                try:
                    from app.ui_events import track_event

                    track_event("seed_question_clicked", {"rank": index + 1})
                except Exception:  # noqa: BLE001
                    pass
                navigate_to_question(question)
            st.caption(item["source_label"])
    return True
