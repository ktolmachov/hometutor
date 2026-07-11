from typing import Any

import streamlit as st


def flashcard_handoff_source_actions(source: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Return visible source actions for a flashcard-to-Tutor handoff."""
    if not isinstance(source, dict):
        return []

    raw_actions = source.get("source_actions")
    actions: list[tuple[str, str]] = []
    if isinstance(raw_actions, list):
        for raw_action in raw_actions:
            if not isinstance(raw_action, dict):
                continue
            label = str(raw_action.get("label") or "").strip()
            url = str(raw_action.get("url") or "").strip()
            if label and url:
                actions.append((label, url))
        if actions:
            return actions

    heading = str(source.get("section_heading") or "").strip()
    obsidian = str(source.get("obsidian_uri") or source.get("source_obsidian_uri") or "").strip()
    vscode = str(source.get("vscode_uri") or source.get("source_vscode_uri") or "").strip()
    video_url = str(source.get("video_url") or "").strip()
    video_label = str(source.get("video_label") or "").strip() or "Видео"
    if obsidian:
        label = f"Открыть раздел «{heading}» в Obsidian" if heading else "Открыть конспект в Obsidian"
        actions.append((label, obsidian))
    if vscode:
        label = f"Открыть раздел «{heading}» в VS Code" if heading else "Открыть источник в VS Code"
        actions.append((label, vscode))
    if video_url:
        actions.append((video_label, video_url))
    return actions


def first_flashcard_handoff_source_url(source: dict[str, Any] | None) -> str:
    """Pick the first actionable source URL for inline linkification."""
    actions = flashcard_handoff_source_actions(source)
    return actions[0][1] if actions else ""


def render_flashcard_handoff_source_actions(source: dict[str, Any] | None) -> None:
    """Render source actions consistently in Tutor and inline Flashcards."""
    actions = flashcard_handoff_source_actions(source)
    note = str((source or {}).get("source_action_note") or "").strip() if isinstance(source, dict) else ""
    if not actions:
        if note:
            st.caption(note)
        return

    st.caption("Источник объяснения")
    cols = st.columns(len(actions))
    for col, (label, url) in zip(cols, actions):
        with col:
            st.link_button(label, url, width="stretch")
    if note:
        st.caption(note)
