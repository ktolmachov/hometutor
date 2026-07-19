"""Interactive quiz tab: generation, parsing, scoring, Anki export."""

import json
import re
import uuid
from typing import Any

import streamlit as st

from app.export_utils import (
    format_interactive_quiz_correct_for_export,
    interactive_quiz_apkg_bytes,
    interactive_quiz_csv_bytes,
)
from app.config import get_settings
from app.ui.continuity_bridge import quiz_expert_controls_intro_ru
from app.ui.expert_controls import render_expert_controls, summarize_question_types
from app.ui.flashcards_sections import FC_MAIN_SECTION_DECKS
from app.ui.helpers import format_request_error as _format_request_error
from app.ui.session_state import PENDING_CURRENT_VIEW_KEY
from app.ui.widgets import render_panel_header as _render_panel_header


def build_redacted_interactive_quiz_generation_debug(
    *,
    learning_mode_ui: str,
    effective_learning_mode: str,
    topic_guess: str,
    concepts_count: int,
    learned_count: int,
    recent_history_chars: int,
    n_questions: int,
    gen_id: str | None,
) -> dict[str, Any]:
    tg = (topic_guess or "").strip()
    return {
        "n_questions_requested": int(n_questions),
        "learning_mode_ui": learning_mode_ui,
        "effective_learning_mode": effective_learning_mode,
        "topic_guess_redacted": (tg[:48] + ("…" if len(tg) > 48 else "")) if tg else "",
        "concepts_in_graph": int(concepts_count),
        "learned_concepts_union": int(learned_count),
        "recent_history_chars": int(recent_history_chars),
        "gen_id_prefix": ((gen_id or "").strip()[:8] or None),
    }


def format_quiz_question_type_distribution(counts: dict[str, int], total: int) -> str:
    if total <= 0:
        return "нет вопросов"
    parts = [f"{name} {100 * c / total:.0f}%" for name, c in sorted(counts.items())]
    return ", ".join(parts) if parts else "нет вопросов"


def _strip_llm_json_fence(text: str) -> str:
    raw = (text or "").strip()
    if not raw.startswith("```"):
        return raw
    lines = raw.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


_QUIZ_TYPES = frozenset({"multiple_choice", "true_false", "fill_blank", "ordering"})


def _strip_quiz_option_prefix(text: str) -> str:
    """Убирает префикс «A.» из варианта, чтобы не дублировать букву в UI."""
    t = (text or "").strip()
    m = re.match(r"^[A-Da-d]\.\s*", t)
    if m:
        return t[m.end() :].strip()
    return t


def _parse_ordering_user(s: str) -> list[str]:
    return [p.strip() for p in (s or "").replace(";", ",").split(",") if p.strip()]


def _normalize_ordering_correct(opts_raw: list[str], corr: Any) -> list[str] | None:
    opts = [_strip_quiz_option_prefix(o.strip()) for o in opts_raw if isinstance(o, str) and o.strip()]
    if len(opts) < 3 or len(opts) > 4:
        return None
    if not isinstance(corr, list) or len(corr) < 3:
        return None
    out: list[str] = []
    for x in corr:
        if isinstance(x, int):
            if 1 <= x <= len(opts):
                out.append(opts[x - 1])
            else:
                return None
        elif isinstance(x, str):
            s = x.strip()
            if s.isdigit() and 1 <= int(s) <= len(opts):
                out.append(opts[int(s) - 1])
            else:
                matched = None
                sl = s.lower()
                for o in opts:
                    if o.lower() == sl or (sl in o.lower()):
                        matched = o
                        break
                if matched is None:
                    return None
                out.append(matched)
        else:
            return None
    if len(out) != len(opts):
        return None
    if set(out) != set(opts):
        return None
    return out


def _parse_tutor_quiz_llm_json(text: str, *, n_questions: int | None = None) -> tuple[dict | None, str | None]:
    """Разбор JSON квиза v2.3: количество вопросов по quiz_interactive_question_count."""
    if n_questions is None:
        from app.config import get_settings
        n_questions = get_settings().quiz_interactive_question_count
    cleaned = _strip_llm_json_fence(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as e:
                return None, f"JSON: {e}"
        else:
            return None, "Ответ модели не похож на JSON-объект."
    if not isinstance(data, dict):
        return None, "Корень JSON должен быть объектом."
    title = (data.get("quiz_title") or "").strip() or "Quiz"
    raw_q = data.get("questions")
    if not isinstance(raw_q, list) or len(raw_q) != n_questions:
        return None, f"Ожидалось ровно {n_questions} вопросов в questions."
    norm: list[dict] = []
    for i, item in enumerate(raw_q):
        if not isinstance(item, dict):
            return None, f"Вопрос {i + 1}: ожидался объект."
        qtext = (item.get("q") or "").strip()
        expl = (item.get("explanation") or "").strip()
        concept = (item.get("concept") or "").strip()
        qtype = (item.get("type") or "").strip()
        if not qtext:
            return None, f"Вопрос {i + 1}: пустой текст q."
        if qtype not in _QUIZ_TYPES:
            return None, f"Вопрос {i + 1}: неизвестный type: {qtype!r}."
        opts = item.get("options")
        corr = item.get("correct")

        if qtype == "multiple_choice":
            if not isinstance(opts, list) or len(opts) != 4:
                return None, f"Вопрос {i + 1}: multiple_choice — нужно 4 варианта."
            if not all(isinstance(o, str) and o.strip() for o in opts):
                return None, f"Вопрос {i + 1}: варианты должны быть непустыми строками."
            letter = str(corr).strip().upper() if corr is not None else ""
            if letter not in ("A", "B", "C", "D"):
                return None, f"Вопрос {i + 1}: correct — буква A-D."
            norm.append(
                {
                    "type": qtype,
                    "q": qtext,
                    "options": [_strip_quiz_option_prefix(o) for o in opts],
                    "correct": letter,
                    "explanation": expl,
                    "concept": concept,
                }
            )
        elif qtype == "true_false":
            raw = str(corr).strip() if corr is not None else ""
            low = raw.lower()
            if low in ("true", "1", "yes"):
                letter = "True"
            elif low in ("false", "0", "no"):
                letter = "False"
            else:
                return None, f"Вопрос {i + 1}: correct — True или False."
            norm.append(
                {
                    "type": qtype,
                    "q": qtext,
                    "options": ["True", "False"],
                    "correct": letter,
                    "explanation": expl,
                    "concept": concept,
                }
            )
        elif qtype == "fill_blank":
            if opts is not None and opts != []:
                return None, f"Вопрос {i + 1}: fill_blank — options пустой или отсутствует."
            if not isinstance(corr, str) or not corr.strip():
                return None, f"Вопрос {i + 1}: fill_blank — непустой correct."
            norm.append(
                {
                    "type": qtype,
                    "q": qtext,
                    "options": [],
                    "correct": corr.strip(),
                    "explanation": expl,
                    "concept": concept,
                }
            )
        else:
            if not isinstance(opts, list) or len(opts) not in (3, 4):
                return None, f"Вопрос {i + 1}: ordering — 3 или 4 пункта в options."
            if not all(isinstance(o, str) and o.strip() for o in opts):
                return None, f"Вопрос {i + 1}: options — непустые строки."
            oc = _normalize_ordering_correct(opts, corr)
            if oc is None:
                return None, f"Вопрос {i + 1}: ordering — correct не согласован с options."
            norm.append(
                {
                    "type": qtype,
                    "q": qtext,
                    "options": [_strip_quiz_option_prefix(o) for o in opts],
                    "correct": oc,
                    "explanation": expl,
                    "concept": concept,
                }
            )

    types_found = {q["type"] for q in norm}
    required = _QUIZ_TYPES if (n_questions or 3) >= 4 else frozenset({"multiple_choice", "true_false", "fill_blank"})
    missing = required - types_found
    if missing:
        missing_str = ", ".join(sorted(missing))
        return None, f"В квизе должны встретиться все типы вопросов; не хватает: {missing_str}."

    return {"quiz_title": title, "questions": norm}, None


_TYPE_LABELS_RU = {
    "multiple_choice": "Выбор варианта",
    "true_false": "Верно / Неверно",
    "fill_blank": "Пропуск",
    "ordering": "Порядок",
}
_TF_LABELS = ("Верно", "Неверно")
_CELEBRATE_MIN_PCT = 80.0


def quiz_type_label_ru(qtype: str | None) -> str:
    return _TYPE_LABELS_RU.get(str(qtype or "").strip(), str(qtype or "вопрос"))


def normalize_true_false_answer(answer: Any) -> str:
    """Map UI/LLM variants to canonical True/False strings."""
    a = str(answer or "").strip()
    if a in ("Верно", "True", "true", "1", "yes", "да", "Да"):
        return "True"
    if a in ("Неверно", "False", "false", "0", "no", "нет", "Нет"):
        return "False"
    return a


def _quiz_answer_correct(q: dict, answer: Any) -> bool:
    qt = q.get("type")
    corr = q.get("correct")
    if qt == "multiple_choice":
        return str(answer or "").strip().upper() == str(corr or "").strip().upper()
    if qt == "true_false":
        return normalize_true_false_answer(answer) == normalize_true_false_answer(corr)
    if qt == "fill_blank":
        return str(answer or "").strip().lower() == str(corr or "").strip().lower()
    if qt == "ordering":
        if not isinstance(corr, list):
            return False
        user_parts = _parse_ordering_user(str(answer or ""))
        if len(user_parts) != len(corr):
            return False
        un = [_strip_quiz_option_prefix(u) for u in user_parts]
        cn = [_strip_quiz_option_prefix(str(c)) for c in corr]
        return un == cn
    return False


def _quiz_widget_key(i: int, gen_id: str, qtype: str) -> str:
    if qtype == "multiple_choice":
        return f"interactive_quiz_q_{i}_{gen_id}"
    if qtype == "true_false":
        return f"interactive_quiz_tf_{i}_{gen_id}"
    if qtype == "fill_blank":
        return f"interactive_quiz_fb_{i}_{gen_id}"
    if qtype == "ordering":
        return f"interactive_quiz_ord_{i}_{gen_id}"
    return f"interactive_quiz_q_{i}_{gen_id}"


def _quiz_result_key(i: int, gen_id: str) -> str:
    return f"interactive_quiz_result_{i}_{gen_id}"


def _answer_is_ready(qtype: str, answer: Any) -> bool:
    if answer is None:
        return False
    if qtype == "multiple_choice":
        return str(answer).strip() != ""
    if qtype == "true_false":
        return str(answer).strip() in _TF_LABELS or normalize_true_false_answer(answer) in {
            "True",
            "False",
        }
    if qtype == "fill_blank":
        return bool(str(answer).strip())
    if qtype == "ordering":
        return bool(_parse_ordering_user(str(answer or "")))
    return bool(str(answer).strip())


def presentation_leaks_answer_before_submit(html_or_text: str) -> bool:
    """Regression helper: pre-submit UI must not reveal correctness copy."""
    blob = str(html_or_text or "").casefold()
    leak_markers = (
        "правильно:",
        "верный ответ",
        "correct answer",
        "неверно. правильно",
    )
    return any(m in blob for m in leak_markers)


def _save_quiz_as_flashcards(quiz: dict, questions: list[dict]) -> None:
    """Convert quiz Q&A pairs → flashcard deck via API (US-15.6); payload собирается в quiz_service."""
    from app.quiz_service import build_flashcard_deck_request_from_interactive_quiz
    from app.ui_client import fetch_json

    payload = build_flashcard_deck_request_from_interactive_quiz(quiz, questions)
    if not payload:
        st.warning("Не удалось извлечь карточки из quiz.")
        return

    try:
        result = fetch_json(
            "POST",
            "/flashcards/decks",
            timeout=30,
            json=payload,
        )
        from app.ui.flashcards_read_cache import invalidate_flashcards_read_cache

        invalidate_flashcards_read_cache()
        st.success(
            f"✅ Создано **{result['card_count']}** flashcards из quiz. "
            "Откройте раздел **Flashcards** для повторения."
        )
        if st.button("→ Перейти к Flashcards", key="goto_fc_from_quiz"):
            st.session_state[PENDING_CURRENT_VIEW_KEY] = "Flashcards"
            st.session_state["flashcards_subview"] = "decks"
            st.session_state["flashcards_section_pending"] = FC_MAIN_SECTION_DECKS
            st.rerun()
    except Exception as e:
        st.error(f"Ошибка сохранения: {e}")


def _render_quiz_expert_layer(
    *,
    quiz: dict,
    questions: list[dict],
    sid: str,
    concepts_count: int,
    learned_count: int,
    user_level: str,
    graph_summary: str,
    topic_guess: str,
    recent_history_chars: int,
) -> None:
    qtype_counts = summarize_question_types(questions)
    qtype_signal = ", ".join(f"{name}: {count}" for name, count in sorted(qtype_counts.items())) or "нет вопросов"
    dist_line = format_quiz_question_type_distribution(qtype_counts, len(questions))
    score_pct = float(st.session_state.get("interactive_quiz_score_pct") or 0.0)
    learning_mode = str(st.session_state.get("interactive_quiz_learning_mode") or "auto")
    saved = st.session_state.get("interactive_quiz_saved_for_gen_id") == st.session_state.get("interactive_quiz_gen_id")
    concepts_in_quiz = sorted(
        {
            str(question.get("concept")).strip()
            for question in questions
            if str(question.get("concept") or "").strip()
        }
    )
    lm_ui = str(learning_mode or "auto").strip().lower() or "auto"
    if lm_ui in ("auto", ""):
        eff_lm = str(st.session_state.get("learning_goal") or "auto").strip().lower() or "auto"
    else:
        eff_lm = lm_ui
    n_q = int(get_settings().quiz_interactive_question_count)
    gen_id = str(st.session_state.get("interactive_quiz_gen_id") or "").strip() or None
    gen_debug = build_redacted_interactive_quiz_generation_debug(
        learning_mode_ui=lm_ui,
        effective_learning_mode=eff_lm,
        topic_guess=topic_guess,
        concepts_count=concepts_count,
        learned_count=learned_count,
        recent_history_chars=recent_history_chars,
        n_questions=n_q,
        gen_id=gen_id,
    )
    signals = [
        f"режим: {learning_mode}→{eff_lm}",
        f"уровень: {user_level}",
        f"типы: {qtype_signal}",
        f"доли типов: {dist_line}",
        f"граф: {graph_summary[:120]}",
    ]
    if concepts_in_quiz:
        signals.append("концепты quiz: " + ", ".join(concepts_in_quiz[:6]))
    render_expert_controls(
        intro=quiz_expert_controls_intro_ru(),
        metrics=(
            ("Сессия", f"{sid[:8]}…", "контекст tutor"),
            ("Вопросов", str(len(questions)), "в текущем quiz"),
            ("Лимит генерации", str(n_q), "из настроек"),
            ("Score", f"{score_pct:.0f}%", "текущая попытка"),
            ("Изучено", str(learned_count), f"из {concepts_count} концептов"),
        ),
        signals=signals,
        safe_actions=(
            "Экспорт в Anki CSV/APKG не меняет прогресс.",
            "Сохранение quiz обновляет граф только после явного завершения.",
            "Создание flashcards превращает вопросы в колоду для интервального повторения.",
            "Результат уже сохранён в историю." if saved else "Результат ещё не сохранён в историю.",
        ),
        raw_debug_label="Quiz JSON + параметры генерации (redacted)",
        raw_debug_payload={"quiz": quiz, "generation_redacted": gen_debug},
    )


def _render_ordering_controls(wkey: str, options: list[str]) -> None:
    """Reorder via up/down (no drag required). Syncs comma-joined value into ``wkey``."""
    list_key = f"{wkey}_list"
    opts = [str(o).strip() for o in options if str(o).strip()]
    if list_key not in st.session_state or not isinstance(st.session_state.get(list_key), list):
        st.session_state[list_key] = list(opts)
    items: list[str] = list(st.session_state[list_key])
    # Repair if option set changed after regen
    if set(items) != set(opts) or len(items) != len(opts):
        items = list(opts)
        st.session_state[list_key] = items
    st.caption("Расставьте пункты кнопками ↑/↓ (без перетаскивания).")
    for j, line in enumerate(items):
        c0, c1, c2, c3 = st.columns([0.12, 0.64, 0.12, 0.12])
        with c0:
            st.caption(str(j + 1))
        with c1:
            st.text(line)
        with c2:
            if st.button("↑", key=f"{wkey}_up_{j}", disabled=j == 0, help="Выше"):
                items[j - 1], items[j] = items[j], items[j - 1]
                st.session_state[list_key] = items
                st.rerun()
        with c3:
            if st.button(
                "↓",
                key=f"{wkey}_dn_{j}",
                disabled=j >= len(items) - 1,
                help="Ниже",
            ):
                items[j + 1], items[j] = items[j], items[j + 1]
                st.session_state[list_key] = items
                st.rerun()
    st.session_state[wkey] = ", ".join(items)


def _render_question_input(i: int, q: dict, gen_id: str, letters: list[str]) -> str:
    """Render input widgets; return widget key. Does not reveal correct answer."""
    qt = q.get("type")
    wkey = _quiz_widget_key(i, gen_id, str(qt or ""))
    if qt == "multiple_choice":
        opts = q.get("options") or []

        def _fmt_letter(L: str, o=opts) -> str:
            idx = ord(L) - ord("A")
            if 0 <= idx < len(o):
                return f"{L}. {o[idx]}"
            return L

        st.radio(
            "Выберите ответ",
            letters[: max(1, min(4, len(opts)))],
            index=None,
            format_func=_fmt_letter,
            key=wkey,
            horizontal=True,
        )
    elif qt == "true_false":
        st.radio(
            "Верно или неверно",
            list(_TF_LABELS),
            index=None,
            key=wkey,
            horizontal=True,
        )
    elif qt == "fill_blank":
        st.text_input("Введите ответ (пропуск):", key=wkey)
    elif qt == "ordering":
        _render_ordering_controls(wkey, list(q.get("options") or []))
    else:
        st.warning("Неизвестный тип вопроса.")
    return wkey


def _render_question_feedback(q: dict, result: dict) -> None:
    """Show correctness only after submit (no pre-submit leak)."""
    if result.get("is_correct"):
        st.success("Верно.")
    else:
        st.error(
            "Неверно. Правильно: "
            f"{format_interactive_quiz_correct_for_export(q)}"
        )
    expl = str(q.get("explanation") or "").strip()
    if expl:
        st.info(f"**Объяснение:** {expl}")


def _score_submitted_questions(questions: list, gen_id: str) -> tuple[int, int, list[str]]:
    """Return (correct, submitted, concept_ids_correct) for submitted items only."""
    correct_n = 0
    submitted_n = 0
    concepts: list[str] = []
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            continue
        result = st.session_state.get(_quiz_result_key(i, gen_id))
        if not isinstance(result, dict):
            continue
        submitted_n += 1
        if result.get("is_correct"):
            correct_n += 1
            c = str(q.get("concept") or "").strip()
            if c:
                concepts.append(c)
    return correct_n, submitted_n, concepts


def _render_interactive_quiz_tab() -> None:
    """Персонализированный квиз: submit-gated feedback, Anki, граф."""
    from app.knowledge_service import knowledge_graph
    from app.models import Message
    from app.quiz_service import generate_interactive_quiz
    from app.quiz_stats import record_quiz_session_completed
    from app.session_store import session_store

    st.markdown('<div class="panel">', unsafe_allow_html=True)
    _render_panel_header(
        "Интерактивный Quiz",
        "Ответьте на вопросы, затем «Ответить» — разбор только после фиксации. "
        "Типы: выбор, верно/неверно, пропуск, порядок.",
    )

    if "tutor_session_id" not in st.session_state:
        st.session_state["tutor_session_id"] = str(uuid.uuid4())
    if "tutor_learned_concepts" not in st.session_state:
        st.session_state["tutor_learned_concepts"] = []

    sid = st.session_state["tutor_session_id"]
    concepts = knowledge_graph.get_concepts()
    learned_session = list(st.session_state.get("tutor_learned_concepts") or [])
    learned_from_graph = [n for n, d in concepts.items() if isinstance(d, dict) and d.get("learned")]
    learned_union = sorted(set(learned_session) | set(learned_from_graph))
    graph_summary = knowledge_graph.get_graph_summary(learned_union)
    focus_concept = str(
        st.session_state.get("interactive_quiz_focus_concept")
        or st.session_state.get("kg_action_concept")
        or ""
    ).strip()
    focus_label = ""
    if focus_concept and focus_concept in concepts:
        raw_focus = concepts.get(focus_concept)
        focus_info = raw_focus if isinstance(raw_focus, dict) else {}
        focus_label = str(focus_info.get("label") or focus_concept).strip()
    sorted_concepts = sorted(concepts.keys())
    if focus_concept and focus_concept in sorted_concepts:
        sorted_concepts = [focus_concept] + [c for c in sorted_concepts if c != focus_concept]
    topic_guess = (
        st.session_state.pop("quiz_topic_hint", "").strip()
        or focus_label
        or (", ".join(sorted_concepts[:12]) if concepts else "общая тема RAG и базы знаний")
    )
    concept_names = (
        ", ".join(sorted_concepts[:80])
        if concepts
        else "(граф концептов пуст — опирайся на тему)"
    )

    hist_msgs = session_store.get(sid)
    recent_parts: list[str] = []
    for m in hist_msgs[-6:]:
        c = (m.content or "").strip().replace("\n", " ")
        if c:
            recent_parts.append(c[:100])
    recent_history = " · ".join(recent_parts) if recent_parts else "(пока нет сообщений в сессии)"

    n_learned = len(learned_union)
    user_level = "intermediate" if n_learned > 5 else "beginner"
    learned_concepts_str = (", ".join(learned_union) if learned_union else "нет")[:1500]

    if "interactive_quiz_data" not in st.session_state:
        st.session_state["interactive_quiz_data"] = None
    if "interactive_quiz_gen_id" not in st.session_state:
        st.session_state["interactive_quiz_gen_id"] = None
    if "interactive_quiz_saved_for_gen_id" not in st.session_state:
        st.session_state["interactive_quiz_saved_for_gen_id"] = None
    if "interactive_quiz_error" not in st.session_state:
        st.session_state["interactive_quiz_error"] = None

    st.caption(
        f"Концептов в графе: {len(concepts)} · отмечено изученными: {n_learned}. "
        "Разбор ответа — только после «Ответить»."
    )

    _iq_labels = {
        "auto": "Как цель обучения (авто)",
        "default": "Нейтральный шаблон",
        "understand_topic": "Освоение темы",
        "exam_prep": "Экзамен",
        "solve_homework": "Домашка и задачи",
    }
    st.selectbox(
        "Шаблон промпта персонального квиза",
        options=list(_iq_labels.keys()),
        format_func=lambda k: _iq_labels[k],
        key="interactive_quiz_learning_mode",
        help="Авто подставляет акцент по текущей цели сессии (если задана на главной).",
    )

    if st.button("Сгенерировать персональный quiz", type="primary", key="interactive_quiz_generate"):
        _im = st.session_state.get("interactive_quiz_learning_mode", "auto")
        _eff_iq = (
            st.session_state.get("learning_goal")
            if str(_im).strip().lower() in ("auto", "")
            else str(_im).strip().lower()
        )
        try:
            quiz_obj, err = generate_interactive_quiz(
                topic=topic_guess,
                user_level=user_level,
                learned_concepts=learned_concepts_str,
                recent_history=recent_history,
                concept_names=concept_names,
                learning_mode=_eff_iq,
            )
            if err or not quiz_obj:
                st.session_state["interactive_quiz_error"] = err or "Не удалось разобрать квиз"
            else:
                st.session_state["interactive_quiz_data"] = quiz_obj
                st.session_state["interactive_quiz_gen_id"] = str(uuid.uuid4())
                st.session_state["interactive_quiz_saved_for_gen_id"] = None
                st.session_state["interactive_quiz_score_pct"] = 0.0
                st.session_state["interactive_quiz_error"] = None
        except Exception as e:
            st.session_state["interactive_quiz_error"] = _format_request_error(e)
        st.rerun()

    quiz = st.session_state["interactive_quiz_data"]
    if not quiz:
        if st.session_state.get("interactive_quiz_error"):
            st.error(st.session_state["interactive_quiz_error"])
        st.info(
            "Нажмите «Сгенерировать персональный quiz» — учитываются последние реплики сессии и список концептов графа."
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if not st.session_state.get("interactive_quiz_gen_id"):
        st.session_state["interactive_quiz_gen_id"] = str(uuid.uuid4())

    st.subheader(quiz.get("quiz_title", "Quiz"))
    letters = ["A", "B", "C", "D"]
    questions = quiz.get("questions", [])
    gen_id = str(st.session_state["interactive_quiz_gen_id"] or "")
    _render_quiz_expert_layer(
        quiz=quiz,
        questions=questions,
        sid=sid,
        concepts_count=len(concepts),
        learned_count=n_learned,
        user_level=user_level,
        graph_summary=graph_summary,
        topic_guess=topic_guess,
        recent_history_chars=len(recent_history),
    )

    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            continue
        qt = str(q.get("type") or "")
        st.markdown(f"**Вопрос {i + 1}** ({quiz_type_label_ru(qt)}) · {q.get('q', '')}")
        if q.get("concept"):
            st.caption(f"Концепт: {q['concept']}")
        wkey = _render_question_input(i, q, gen_id, letters)
        result_key = _quiz_result_key(i, gen_id)
        result = st.session_state.get(result_key)
        submitted = isinstance(result, dict)

        if not submitted:
            if st.button("Ответить", key=f"interactive_quiz_submit_{i}_{gen_id}", type="secondary"):
                ans = st.session_state.get(wkey)
                if not _answer_is_ready(qt, ans):
                    st.warning("Сначала выберите или введите ответ.")
                else:
                    st.session_state[result_key] = {
                        "status": "submitted",
                        "is_correct": _quiz_answer_correct(q, ans),
                        "answer": ans,
                    }
                    try:
                        from app.ui.tutorial_guide import note_activation_checkpoint

                        note_activation_checkpoint("micro_quiz_submitted")
                    except Exception:  # noqa: BLE001 - coach must not break quiz
                        pass
                    st.rerun()
        else:
            _render_question_feedback(q, result)

    total = len([x for x in questions if isinstance(x, dict)])
    correct_n, submitted_n, _ = _score_submitted_questions(questions, gen_id)
    pct = (correct_n / submitted_n * 100.0) if submitted_n else 0.0
    st.session_state["interactive_quiz_score_pct"] = pct
    if submitted_n:
        st.caption(f"Зафиксировано ответов: {submitted_n}/{total} · текущий score: {pct:.0f}%")
    else:
        st.caption("Ответьте на вопросы кнопкой «Ответить» — разбор откроется только после фиксации.")

    ex1, ex2 = st.columns(2)
    safe_title = re.sub(r"[^\w\-]+", "_", quiz.get("quiz_title", "quiz")[:40])
    with ex1:
        st.download_button(
            label="Экспорт в Anki (.csv)",
            data=interactive_quiz_csv_bytes(quiz),
            file_name=f"quiz_{safe_title}.csv",
            mime="text/csv",
            key="interactive_quiz_csv_dl",
            width="stretch",
        )
    with ex2:
        apkg, apkg_err = interactive_quiz_apkg_bytes(quiz)
        if apkg is not None:
            st.download_button(
                label="Скачать колоду (.apkg)",
                data=apkg,
                file_name=f"quiz_{safe_title}.apkg",
                mime="application/apkg",
                key="interactive_quiz_apkg_dl",
                width="stretch",
            )
        else:
            st.caption(apkg_err or "Не удалось собрать .apkg")

    finish_disabled = submitted_n <= 0
    if st.button(
        "Завершить quiz, обновить граф и сохранить в историю",
        key="interactive_quiz_finish",
        disabled=finish_disabled,
        help="Доступно после хотя бы одного зафиксированного ответа.",
    ):
        ok, done_n, concepts_to_mark = _score_submitted_questions(questions, gen_id)
        seen: set[str] = set()
        concepts_dedup = []
        for c in concepts_to_mark:
            if c not in seen:
                seen.add(c)
                concepts_dedup.append(c)

        n_marked = knowledge_graph.mark_concepts_as_learned(concepts_dedup)
        tl = list(st.session_state.get("tutor_learned_concepts") or [])
        for c in concepts_dedup:
            if c in concepts and c not in tl:
                tl.append(c)
        st.session_state["tutor_learned_concepts"] = tl

        pct_done = (ok / done_n * 100.0) if done_n else 0.0
        if gen_id and st.session_state.get("interactive_quiz_saved_for_gen_id") != gen_id:
            lines = [
                f"**Интерактивный quiz:** {quiz.get('quiz_title', 'Quiz')}",
                f"**Результат:** {pct_done:.0f}% ({ok}/{done_n} зафиксированных)",
                f"**Обновление графа:** помечено концептов: {n_marked}",
                f"**Контекст графа (кратко):** {graph_summary}",
            ]
            msg = Message(
                role="assistant",
                content="\n\n".join(lines),
                metadata={
                    "source": "interactive_quiz",
                    "score_percent": round(pct_done, 1),
                    "marked_concepts": concepts_dedup,
                },
            )
            cur = session_store.get(sid)
            cur.append(msg)
            session_store.save(sid, cur)
            st.session_state["interactive_quiz_saved_for_gen_id"] = gen_id
            record_quiz_session_completed(total_questions=done_n, correct=ok)

        if pct_done >= _CELEBRATE_MIN_PCT:
            st.balloons()
            st.success(
                f"Результат: **{pct_done:.0f}%** ({ok}/{done_n}). "
                f"Граф: обновлено **{n_marked}** концепт(ов)."
            )
            next_cta = "mnemo"
        elif pct_done >= 50:
            st.warning(
                f"Результат: **{pct_done:.0f}%** ({ok}/{done_n}). "
                f"Есть прогресс; граф: **{n_marked}** концепт(ов)."
            )
            next_cta = "retry"
        else:
            st.info(
                f"Результат: **{pct_done:.0f}%** ({ok}/{done_n}). "
                "Спокойный шаг: повторите слабые места или вернитесь к материалам."
            )
            next_cta = "retry"

        # One dominant next action after finish.
        if next_cta == "mnemo":
            try:
                from app.ui.mnemo_nav import render_return_to_mnemo_cta

                if render_return_to_mnemo_cta(
                    key="interactive_quiz_return_mnemo",
                    return_from="quiz",
                    caption=(
                        "Мир покажет quiz-след: ✓ на остановках и небо/фонари "
                        "(не SR/туман и не ◆ — у них свои каналы)."
                    ),
                ):
                    st.rerun()
            except Exception:  # noqa: BLE001 - return CTA must not break finish path
                if st.button("→ К прогрессу", key="interactive_quiz_goto_progress"):
                    st.session_state[PENDING_CURRENT_VIEW_KEY] = "Прогресс обучения"
                    st.rerun()
        else:
            if st.button(
                "🃏 Создать flashcards из этих вопросов",
                key="quiz_to_flashcards_after_finish",
                type="primary",
                width="stretch",
                help="Единый следующий шаг после слабого/среднего результата.",
            ):
                _save_quiz_as_flashcards(quiz, questions)

    if st.session_state.get("interactive_quiz_data") and questions and submitted_n <= 0:
        st.caption("После ответов можно завершить quiz и обновить граф.")

    st.markdown("</div>", unsafe_allow_html=True)
