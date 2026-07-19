"""Lecture route: clipped segments + gate quizzes (#19 P0-1 + P0-2).

Groups media sections into 8-12 min segments, plays clipped audio, then shows
a scoped gate quiz from the sections' konspekt text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

import streamlit as st

from app.media_sidecar import (
    MediaSection,
    MediaSidecar,
    load_media_sidecar_for_konspekt,
    sidecar_stale_reasons,
)
from app.ui.session_state import PENDING_CURRENT_VIEW_KEY


# ---------------------------------------------------------------------------
# Segment grouping (pure function, no LLM)
# ---------------------------------------------------------------------------


@dataclass
class LectureSegment:
    index: int
    title: str
    section_dicts: list[dict[str, Any]]
    t_start: float
    t_end: float
    duration_min: float
    audio_path: str | None


def group_sections_into_segments(
    sections: list[dict[str, Any]],
    target_min: float = 10.0,
) -> list[LectureSegment]:
    """Group timecoded sections into ~target_min segments.
    Adjacent sections (gap ≤ 5s) form a group; new segment when cumulative
    duration reaches target or a group boundary is crossed."""
    timed = []
    for s in sections:
        ts = s.get("t_start")
        te = s.get("t_end")
        if ts is not None and te is not None and float(te) > float(ts):
            timed.append((float(ts), float(te), s))

    timed.sort(key=lambda x: x[0])

    groups: list[list[dict[str, Any]]] = []
    grp: list[dict[str, Any]] = []
    grp_end = 0.0
    for ts, te, s in timed:
        if not grp:
            grp.append(s)
            grp_end = te
        elif ts - grp_end <= 5.0:
            grp.append(s)
            grp_end = te
        else:
            groups.append(grp)
            grp = [s]
            grp_end = te
    if grp:
        groups.append(grp)

    segments: list[LectureSegment] = []
    idx = 0

    for grp in groups:
        buf: list[dict[str, Any]] = []
        buf_start: float | None = None
        buf_end: float = 0.0

        for s in grp:
            ts = float(s.get("t_start", 0))
            te = float(s.get("t_end", 0))
            if buf_start is None:
                buf_start = ts
            buf.append(s)
            buf_end = max(buf_end, te)
            dur = (buf_end - buf_start) / 60.0
            if dur >= target_min:
                segments.append(_build_segment(idx, buf, buf_start, buf_end))
                idx += 1
                buf = []
                buf_start = None
                buf_end = 0.0
        if buf and buf_start is not None:
            segments.append(_build_segment(idx, buf, buf_start, buf_end))
            idx += 1

    return segments


def _build_segment(
    idx: int,
    buf: list[dict[str, Any]],
    buf_start: float,
    buf_end: float,
) -> LectureSegment:
    labels = [
        str(s.get("label") or "").strip()
        for s in buf
        if str(s.get("label") or "").strip()
    ]
    title = ", ".join(labels[:3]) + ("…" if len(labels) > 3 else "") or f"Отрезок {idx+1}"
    audio = str(buf[0].get("audio_path") or "") or None
    return LectureSegment(
        index=idx,
        title=title,
        section_dicts=list(buf),
        t_start=buf_start,
        t_end=buf_end,
        duration_min=round((buf_end - buf_start) / 60.0, 1),
        audio_path=audio,
    )


# ---------------------------------------------------------------------------
# Content extraction (from konspekt markdown by line_start/line_end)
# ---------------------------------------------------------------------------


def _sidecar_text_for_section(
    md_path: str,
    ms: MediaSection,
) -> str:
    """Extract content text from konspekt markdown. line_start is 1-indexed."""
    try:
        p = Path(md_path).resolve()
        if not p.exists():
            return ""
        lines = p.read_text(encoding="utf-8").splitlines()
        ls = max(0, int(ms.line_start) - 1)
        le = min(len(lines), int(ms.line_end))
        return " ".join(lines[ls:le])
    except Exception:  # noqa: BLE001 - best-effort content extraction; gate degrades gracefully
        return ""


def _content_for_segment(seg: LectureSegment) -> str:
    texts = []
    for sd in seg.section_dicts:
        mp = str(sd.get("media_path") or "")
        ms = sd.get("_ms")
        if mp and ms is not None:
            t = _sidecar_text_for_section(mp, ms)
            if t:
                texts.append(t)
    return " ".join(texts)


# ---------------------------------------------------------------------------
# Audio resolution
# ---------------------------------------------------------------------------


def _resolve_audio_for_sidecar(sidecar: MediaSidecar) -> str | None:
    """Find audio sibling for the sidecar's local video source."""
    try:
        from app.media_audio import audio_for_local_video
        from app.media_sidecar import LocalVideoSource

        if isinstance(sidecar.video, LocalVideoSource):
            audio_p = audio_for_local_video(sidecar.video)
            if audio_p is not None and audio_p.exists():
                return str(audio_p)
    except Exception:  # noqa: BLE001 - audio is optional, route works without it
        pass
    return None


# ---------------------------------------------------------------------------
# Gate quiz
# ---------------------------------------------------------------------------


def _generate_gate_quiz(content: str, title: str) -> dict[str, Any] | None:
    if len(content.strip()) < 120:
        return None
    from app.quiz_scoped import generate_scoped_quiz_from_content
    from app.quiz_adaptive import get_adaptive_difficulty

    level = get_adaptive_difficulty("adaptive", title)
    return generate_scoped_quiz_from_content(
        scope="document",
        identifier=title,
        title=title,
        content=content,
        subgraph={"topic_name": title, "key_concepts": [], "documents": []},
        adaptive_level=level,
        num_questions=5,
    )


def _read_gate_results(source_key: str, n_questions: int) -> dict[str, Any]:
    total = 0
    correct = 0
    for i in range(n_questions):
        r = st.session_state.get(f"{source_key}_result_{i}")
        if r is None:
            continue
        total += 1
        if isinstance(r, dict) and r.get("status") == "correct":
            correct += 1
    return {"total": total, "correct": correct, "answered": total}


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

_GS_KEY = "lk_lecture_route_gate_state_v1"


def _row_set_id(rows: list[dict[str, Any]]) -> str:
    seed = "|".join(
        f"{r.get('konspekt_md_abs') or ''}/{r.get('slug') or ''}/"
        f"{r.get('line_start') or ''}/{r.get('konspekt_section_title') or ''}/"
        f"{r.get('heading_text') or ''}/{r.get('row_key') or ''}/{r.get('title') or ''}"
        for r in rows[:50]
    )
    return sha256(seed.encode()).hexdigest()[:8]


def _init_gate_state(segments: list[LectureSegment], rows: list[dict[str, Any]]) -> dict[str, Any]:
    rsid = _row_set_id(rows)
    current = st.session_state.get(_GS_KEY, {})
    if current.get("_row_set_id") != rsid:
        st.session_state[_GS_KEY] = {
            "_row_set_id": rsid,
            "current": 0,
            "total": len(segments),
            "results": {},
            "show_gate": False,
            "gate_questions": None,
            "gate_last_content": "",
        }
    return st.session_state[_GS_KEY]


# ---------------------------------------------------------------------------
# UI: lecture route
# ---------------------------------------------------------------------------


def render_lecture_route(
    konspekt_rows: list[dict[str, Any]],
) -> None:
    """Main entry: render the lecture route tab in Living Konspekt."""
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

    gate = _init_gate_state(segments, konspekt_rows)
    cur = gate["current"]
    if cur >= gate["total"]:
        gate["current"] = 0
        cur = 0

    st.markdown("### 🗺️ Маршрут лекции")
    st.caption(f"**{len(segments)} отрезков** по ~8–12 мин · слушайте и проверяйте себя")

    cols = st.columns(4)
    for i, seg in enumerate(segments):
        with cols[i % 4]:
            done = gate["results"].get(i, False)
            active = gate["current"] == i
            disabled = not active and not done and i > gate["current"]
            icon = "✅" if done else ("▶️" if active else f"{i+1}")
            label = f"{icon} {seg.title[:20]}" if seg.title else f"{icon} Отрезок {i+1}"
            if st.button(label, key=f"lk_seg_btn_{i}", width="stretch",
                         disabled=disabled):
                gate["current"] = i
                gate["show_gate"] = False
                gate["gate_questions"] = None
                gate["gate_last_content"] = ""
                st.rerun()

    seg = segments[cur]
    st.markdown(f"**Отрезок {cur+1}/{len(segments)}:** {seg.title or 'Без названия'} · {seg.duration_min} мин")

    if seg.audio_path and Path(seg.audio_path).exists():
        st.audio(str(seg.audio_path), start_time=int(seg.t_start),
                 end_time=int(seg.t_end), format="audio/mp4")
    else:
        st.caption("🎧 Аудио недоступно для этого отрезка")

    if not gate["show_gate"]:
        if st.button("✅ Я прослушал — проверить себя", key="lk_gate_show",
                     type="primary", width="stretch"):
            gate["show_gate"] = True
            st.rerun()
    else:
        _render_gate(seg, gate)


def _collect_timecoded_sections(
    konspekt_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    from app.ui.living_konspekt_media import _media_section_for_row

    sections = []
    for row in konspekt_rows:
        md_abs = str(row.get("konspekt_md_abs") or "")
        if not md_abs:
            continue
        try:
            sidecar = load_media_sidecar_for_konspekt(Path(md_abs))
        except Exception:  # noqa: BLE001 - best-effort sidecar load per row
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
            "label": str(row.get("konspekt_section_title") or row.get("title") or ms.heading or "").strip(),
            "t_start": ms.t_start,
            "t_end": ms.t_end if ms.t_end is not None else ms.t_start + 60.0,
            "media_path": md_abs,
            "audio_path": _resolve_audio_for_sidecar(sidecar),
            "_ms": ms,
            "_row": row,
        })
    return sections


def _render_gate(
    seg: LectureSegment,
    gate: dict[str, Any],
) -> None:
    st.markdown("---")
    st.subheader("🔐 Ворота: проверка понимания")

    source_key = "lk_lecture_gate"

    if gate.get("gate_questions") is None:
        with st.spinner("Готовлю вопросы…"):
            content = _content_for_segment(seg)
            gate["gate_last_content"] = content
            gate["gate_questions"] = _generate_gate_quiz(content, seg.title or f"segment-{seg.index}")
        st.rerun()

    quiz = gate.get("gate_questions")
    if quiz is None or not isinstance(quiz, dict) or not quiz.get("questions"):
        st.warning("Не удалось сгенерировать вопросы (мало текста в отрезке).")
        if st.button("Пропустить ворота", key="lk_gate_skip"):
            _advance_segment(gate, seg, correct=False)
            st.rerun()
        return

    n_questions = len(quiz["questions"])
    from app.ui.scoped_quiz import render_scoped_self_check_quiz

    st.caption(f"Вопросы по отрезку «{seg.title}» ({n_questions} вопросов)")
    render_scoped_self_check_quiz(quiz["questions"], source_key=source_key, quiz_meta=quiz)

    results = _read_gate_results(source_key, n_questions)
    all_answered = results["total"] >= n_questions
    if all_answered:
        c = results["correct"]
        t = n_questions
        _clear_gate_scoped_state(source_key, n_questions)
        if t > 0 and c / t >= 0.6:
            st.success(f"✅ Правильно! {c}/{t} — следующий отрезок открыт")
            _advance_segment(gate, seg, correct=True)
        else:
            st.error(f"Нужно больше правильных. Ваш результат: {c}/{t}")
            _render_gate_fallback(seg, gate)
        if st.button("Продолжить", key="lk_gate_continue", type="primary"):
            st.rerun()
    else:
        st.info(f"Ответьте на все {n_questions} вопросов ({results['answered']}/{n_questions})")


def _clear_gate_scoped_state(source_key: str, n: int) -> None:
    for i in range(n):
        st.session_state.pop(f"{source_key}_result_{i}", None)
        st.session_state.pop(f"{source_key}_scoped_{i}", None)
        st.session_state.pop(f"{source_key}_hint_{i}", None)
    st.session_state.pop(f"{source_key}_completion_metric_emitted", None)
    st.session_state.pop(f"{source_key}_next_cta_route", None)


def _advance_segment(
    gate: dict[str, Any],
    seg: LectureSegment,
    *,
    correct: bool,
) -> None:
    gate["results"][seg.index] = correct
    gate["show_gate"] = False
    gate["gate_questions"] = None
    gate["gate_last_content"] = ""
    if correct and seg.index + 1 < gate["total"]:
        gate["current"] = seg.index + 1


def _render_gate_fallback(seg: LectureSegment, gate: dict[str, Any]) -> None:
    st.markdown("**Что можно сделать:**")
    c1, c2 = st.columns(2)
    text = str(gate.get("gate_last_content") or "")[:2000]
    with c1:
        if st.button("💡 Объясни проще", key="lk_gate_simpler", width="stretch"):
            st.session_state["tutor_pending_prompt"] = (
                f"Объясни тему отрезка «{seg.title}» проще и на интуитивном уровне. "
                f"Вот текст отрезка:\n\n{text}"
            )
            st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")
            st.session_state["tutor_cta_action"] = "lecture_gate_simpler"
            st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
            st.session_state["current_topic"] = seg.title
            st.rerun()
    with c2:
        if st.button("🔁 Переслушать отрезок", key="lk_gate_replay", width="stretch"):
            gate["show_gate"] = False
            gate["gate_questions"] = None
            st.rerun()
