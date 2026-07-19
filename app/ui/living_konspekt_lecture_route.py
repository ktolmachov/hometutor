"""Lecture route: clipped segments + gate quizzes (#19 P0-1 + P0-2).

Groups media sections into 8-12 min segments, plays clipped audio, then shows
a 1-2 question gate quiz from the sections' sidecar text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import streamlit as st

from app.media_sidecar import (
    MediaSidecar,
    load_media_sidecar_for_konspekt,
    sidecar_stale_reasons,
)


# ---------------------------------------------------------------------------
# Segment grouping (pure function, no LLM)
# ---------------------------------------------------------------------------


@dataclass
class LectureSegment:
    index: int
    title: str
    sections: list[dict[str, Any]]
    t_start: float
    t_end: float
    duration_min: float


def _section_times(section: dict[str, Any]) -> tuple[float | None, float | None]:
    ts = section.get("t_start")
    te = section.get("t_end")
    t_start = float(ts) if ts is not None else None
    t_end = float(te) if te is not None else None
    return t_start, t_end


def _segment_title(sections: list[dict[str, Any]]) -> str:
    labels = [
        str(s.get("label") or "").strip()
        for s in sections
        if str(s.get("label") or "").strip()
    ]
    if labels:
        return ", ".join(labels[:3]) + ("…" if len(labels) > 3 else "")
    return f"Раздел {sections[0].get('section_id', '?')}" if sections else ""


def group_sections_into_segments(
    sections: list[dict[str, Any]],
    target_min: float = 10.0,
) -> list[LectureSegment]:
    """Pure arithmetic: group timecoded sections into ~target_min segments.
    Adjacent sections (gap ≤ 5s) form a group; a new segment starts when
    cumulative duration reaches target or there's a significant gap."""
    timed = []
    for s in sections:
        ts, te = _section_times(s)
        if ts is not None and te is not None and te > ts:
            timed.append((ts, te, s))

    timed.sort(key=lambda x: x[0])

    # Pre-group: chain adjacent sections (gap ≤ 5s) then split by target duration
    groups: list[list[dict[str, Any]]] = []
    grp: list[dict[str, Any]] = []
    grp_start = 0.0
    grp_end = 0.0
    for ts, te, s in timed:
        if not grp:
            grp.append(s)
            grp_start = ts
            grp_end = te
        elif ts - grp_end <= 5.0:
            grp.append(s)
            grp_end = te
        else:
            groups.append(grp)
            grp = [s]
            grp_start = ts
            grp_end = te
    if grp:
        groups.append(grp)

    segments: list[LectureSegment] = []
    idx = 0
    buf: list[dict[str, Any]] = []
    buf_start: float | None = None
    buf_end: float = 0.0

    def _flush() -> None:
        nonlocal idx
        if buf and buf_start is not None:
            segments.append(LectureSegment(
                index=idx,
                title=_segment_title(buf),
                sections=list(buf),
                t_start=buf_start,
                t_end=buf_end,
                duration_min=round((buf_end - buf_start) / 60.0, 1),
            ))
            idx += 1

    for grp in groups:
        for s in grp:
            ts, te = _section_times(s)
            if ts is None or te is None:
                continue
            if buf_start is None:
                buf_start = ts
            buf.append(s)
            buf_end = max(buf_end, te)
            dur = (buf_end - buf_start) / 60.0
            if dur >= target_min:
                _flush()
                buf = []
                buf_start = None
                buf_end = 0.0
    _flush()

    return segments


# ---------------------------------------------------------------------------
# Content extraction for gate quiz
# ---------------------------------------------------------------------------


def _sidecar_text_for_section(
    sidecar: MediaSidecar,
    section_index: int,
) -> str:
    """Extract content text for one section from its sidecar, bounded to the section's line range."""
    lines = []
    section = sidecar.sections[section_index] if section_index < len(sidecar.sections) else None
    ls = int(section.line_start) if section and section.line_start is not None else None
    le = int(section.line_end) if section and section.line_end is not None else None
    if ls is not None and le is not None and sidecar.transcript_lines:
        for i, sl in enumerate(sidecar.transcript_lines):
            if i >= ls and i <= le:
                lines.append(sl.text)
    return " ".join(lines)


def _content_for_segment(
    sidecar: MediaSidecar,
    sections: list[dict[str, Any]],
) -> str:
    texts = []
    for s in sections:
        idx = int(s.get("_section_index") or -1)
        if idx >= 0:
            texts.append(_sidecar_text_for_section(sidecar, idx))
    return " ".join(texts)


# ---------------------------------------------------------------------------
# Gate quiz
# ---------------------------------------------------------------------------


def _generate_gate_quiz(content: str, title: str) -> dict[str, Any] | None:
    """1-2 question scoped quiz for the segment content."""
    if len(content.strip()) < 120:
        return None
    from app.quiz_scoped import generate_scoped_quiz_from_content
    from app.quiz_adaptive import get_adaptive_difficulty

    level = get_adaptive_difficulty("adaptive", title)
    result = generate_scoped_quiz_from_content(
        scope="document",
        identifier=title,
        title=title,
        content=content,
        subgraph={"topic_name": title, "key_concepts": [], "documents": []},
        adaptive_level=level,
        num_questions=2,
    )
    return result if result.get("questions") else None


# ---------------------------------------------------------------------------
# UI: lecture route
# ---------------------------------------------------------------------------

_GS_KEY = "lk_lecture_route_gate_state_v1"


def _init_gate_state(n_segments: int) -> dict[str, Any]:
    if _GS_KEY not in st.session_state:
        st.session_state[_GS_KEY] = {
            "current": 0,
            "total": n_segments,
            "results": {},
            "show_gate": False,
            "gate_questions": None,
            "gate_last_content": "",
        }
    return st.session_state[_GS_KEY]


def render_lecture_route(
    konspekt_rows: list[dict[str, Any]],
    audio_path: Path | None = None,
) -> None:
    """Main entry: render the lecture route for Living Konspekt."""
    if not konspekt_rows:
        st.info("Нет разделов конспекта для построения маршрута.")
        return

    sections = _collect_timecoded_sections(konspekt_rows)
    if len(sections) < 2:
        st.info("Недостаточно разделов с таймкодами для маршрута (нужно ≥2).")
        return

    segments = group_sections_into_segments(sections)
    if not segments:
        st.info("Не удалось сгруппировать разделы в отрезки.")
        return

    gate = _init_gate_state(len(segments))

    st.markdown("### 🗺️ Маршрут лекции")
    st.caption(f"**{len(segments)} отрезков** по ~8–12 мин · нажмите на отрезок, чтобы начать")

    cols = st.columns(4)
    for i, seg in enumerate(segments):
        with cols[i % 4]:
            done = gate["results"].get(i, False)
            active = gate["current"] == i
            icon = "✅" if done else ("▶️" if active else f"{i+1}")
            label = f"{icon} {seg.title[:20]}" if seg.title else f"{icon} Отрезок {i+1}"
            if st.button(label, key=f"lk_seg_btn_{i}", width="stretch",
                         disabled=False if not done or active else False):
                gate["current"] = i
                gate["show_gate"] = False
                gate["gate_questions"] = None
                gate["gate_last_content"] = ""
                st.rerun()

    cur = gate["current"]
    seg = segments[cur]
    st.markdown(f"**Отрезок {cur+1}/{len(segments)}:** {seg.title or 'Без названия'} · {seg.duration_min} мин")

    if audio_path and audio_path.exists():
        st.audio(str(audio_path), start_time=int(seg.t_start),
                 end_time=int(seg.t_end), format="audio/mp4")
    else:
        st.caption("Аудио плеер недоступен")

    if not gate["show_gate"]:
        if st.button("✅ Я прослушал — проверить себя", key="lk_gate_show",
                     type="primary", width="stretch"):
            gate["show_gate"] = True
            st.rerun()
    else:
        _render_gate(seg, gate, konspekt_rows)


def _collect_timecoded_sections(
    konspekt_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract sections with t_start/t_end from konspekt rows via sidecar."""
    from app.ui.living_konspekt_media import _media_section_for_row

    sections = []
    for row in konspekt_rows:
        md_abs = str(row.get("konspekt_md_abs") or "")
        if not md_abs:
            continue
        try:
            sidecar = load_media_sidecar_for_konspekt(Path(md_abs))
        except Exception:
            continue
        if sidecar is None or not sidecar.sections:
            continue
        stale = sidecar_stale_reasons(sidecar, md_abs)
        if stale:
            continue
        ms = _media_section_for_row(sidecar, row)
        if ms is None or ms.t_start is None or ms.low_confidence:
            continue
        sections.append({
            "label": str(row.get("konspekt_section_title") or row.get("title") or "").strip(),
            "t_start": ms.t_start,
            "t_end": ms.t_end if ms.t_end is not None else ms.t_start + 60.0,
            "media_path": md_abs,
            "_section_index": ms.section_index,
            "_row": row,
        })
    return sections


def _render_gate(
    seg: LectureSegment,
    gate: dict[str, Any],
    konspekt_rows: list[dict[str, Any]],
) -> None:
    st.markdown("---")
    st.subheader("🔐 Ворота: проверка понимания")

    if gate.get("gate_questions") is None:
        with st.spinner("Готовлю вопрос…"):
            content = ""
            for s in seg.sections:
                md_abs = str(s.get("media_path") or "")
                idx = int(s.get("_section_index") or -1)
                if md_abs and idx >= 0:
                    try:
                        sidecar = load_media_sidecar_for_konspekt(Path(md_abs))
                    except Exception:
                        continue
                    if sidecar:
                        content += " " + _sidecar_text_for_section(sidecar, idx)
            gate["gate_last_content"] = content
            quiz = _generate_gate_quiz(content, seg.title or f"segment-{seg.index}")
            gate["gate_questions"] = quiz
        st.rerun()

    quiz = gate.get("gate_questions")
    if quiz is None or not isinstance(quiz, dict) or not quiz.get("questions"):
        st.warning("Не удалось сгенерировать вопрос (слишком мало текста в отрезке).")
        if st.button("Пропустить ворота", key="lk_gate_skip"):
            _advance_segment(gate, seg, correct=False)
            st.rerun()
        return

    from app.ui.scoped_quiz import render_scoped_self_check_quiz

    st.caption(f"Вопрос по отрезку «{seg.title}» ({len(quiz['questions'])} вопросов)")
    render_scoped_self_check_quiz(
        quiz["questions"],
        source_key="lk_lecture_gate",
        quiz_meta=quiz,
    )

    # After quiz self-check renders, check results
    gate_key = "scoped_self_check_lk_lecture_gate_results"
    results = st.session_state.get(gate_key, {})
    if results.get("answered", 0) > 0:
        c = results.get("correct", 0)
        t = results.get("total", 0)
        st.session_state.pop(gate_key, None)
        if t > 0 and c / t >= 0.5:
            from app.quiz_scoped import scoped_quiz_xp_reward

            xp = scoped_quiz_xp_reward(c, t)
            st.success(f"✅ Правильно! +{xp} XP")
            _advance_segment(gate, seg, correct=True, xp=xp)
        else:
            st.error(f"Нужно больше правильных. Ваш результат: {c}/{t}")
            _render_gate_fallback(seg)
        if st.button("Продолжить", key="lk_gate_continue", type="primary"):
            st.rerun()


def _advance_segment(
    gate: dict[str, Any],
    seg: LectureSegment,
    *,
    correct: bool,
    xp: int = 0,
) -> None:
    gate["results"][seg.index] = correct
    gate["show_gate"] = False
    gate["gate_questions"] = None
    gate["gate_last_content"] = ""
    if correct and seg.index + 1 < gate["total"]:
        gate["current"] = seg.index + 1


def _render_gate_fallback(seg: LectureSegment) -> None:
    st.markdown("**Что можно сделать:**")
    c1, c2 = st.columns(2)
    text = st.session_state.get("lk_lecture_route_gate_state_v1", {}).get("gate_last_content", "")
    with c1:
        if st.button("💡 Объясни проще", key="lk_gate_simpler", width="stretch"):
            st.session_state["tutor_pending_prompt"] = (
                f"Объясни тему отрезка «{seg.title}» проще и на интуитивном уровне. "
                f"Вот текст отрезка:\n\n{text[:2000]}"
            )
            st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")
            st.session_state["tutor_cta_action"] = "lecture_gate_simpler"
            st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
            st.session_state["current_topic"] = seg.title
            st.rerun()
    with c2:
        if st.button("🔁 Переслушать отрезок", key="lk_gate_replay", width="stretch"):
            st.session_state["lk_lecture_route_gate_state_v1"]["show_gate"] = False
            st.session_state["lk_lecture_route_gate_state_v1"]["gate_questions"] = None
            st.rerun()


from app.ui.session_state import PENDING_CURRENT_VIEW_KEY
