"""Кэш каталога тем в session_state."""
from __future__ import annotations

import streamlit as st

from app.ui_client import fetch_json


def _inject_team_workflow_prompt_topics(catalog: dict) -> dict:
    if not isinstance(catalog, dict):
        return catalog
    topics = catalog.get("topics")
    if not isinstance(topics, list):
        return catalog

    doc_rel = "doc/team_workflow/generate_audit_closed_packages_prompt.md"
    topic_id = "team-workflow-audit-closed-packages"
    if any(isinstance(t, dict) and t.get("topic_id") == topic_id for t in topics):
        return catalog

    prompt_text = "\n".join(
        [
            "Прочитай doc/team_workflow/generate_audit_closed_packages_prompt.md",
            "и выполни инструкции.",
            "TARGET_AGENT: claude_code",
            "MONTH: 2026-04",
            "DEPTH: index_only",
        ]
    )

    topics.append(
        {
            "topic_id": topic_id,
            "topic_name": "Team workflow: audit закрытых пакетов (monthly)",
            "document_count": 1,
            "key_concepts": [
                "team_workflow",
                "audit",
                "closed packages",
                "ssot",
                "dod",
                "backlog_registry",
            ],
            "documents": [
                {
                    "doc_id": "team_workflow_audit_closed_packages_prompt",
                    "relative_path": doc_rel,
                    "file_name": "generate_audit_closed_packages_prompt.md",
                    "folder_name": "doc/team_workflow",
                    "summary": (
                        "Генератор промпта периодического аудита закрытых пакетов (SSoT ↔ индексы ↔ DoD).\n\n"
                        f"Файл: `{doc_rel}`\n\n"
                        "Минимальный запуск:\n"
                        f"{prompt_text}"
                    ),
                    "doc_type": "markdown",
                    "difficulty": "advanced",
                    "key_concepts": ["audit", "DoD", "registry", "indexes", "workflow"],
                }
            ],
        }
    )

    catalog["total_topics"] = int(catalog.get("total_topics") or len(topics))
    catalog["total_topics"] = max(int(catalog["total_topics"]), len(topics))
    return catalog


def load_topics_catalog(force: bool = False):
    if st.session_state["topics_catalog"] is not None and not force:
        return st.session_state["topics_catalog"]
    try:
        st.session_state["topics_catalog"] = _inject_team_workflow_prompt_topics(
            fetch_json("GET", "/topics", timeout=20)
        )
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        st.session_state["topics_catalog"] = None
    return st.session_state["topics_catalog"]
