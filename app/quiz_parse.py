"""Tutor/quiz JSON parsing helpers (split from ``app.quiz_service``)."""

from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from typing import Any

from app.prompts import SOCRATIC_TYPE_KEYS

logger = logging.getLogger(__name__)

_MAX_CONTEXT_CHARS = 14000
_SCOPED_DIFFICULTIES = frozenset({"recognition", "recall", "transfer"})
_INTERACTIVE_QUIZ_TYPES = frozenset(
    {"multiple_choice", "true_false", "fill_blank", "ordering"}
)
_INTERACTIVE_QUIZ_TYPES_BASE = frozenset(
    {"multiple_choice", "true_false", "fill_blank"}
)

# Tutor inline quiz (итерация 19.2): маркер в конце ответа LLM
TUTOR_INLINE_QUIZ_MARKER = "=== QUIZ ==="
# Типизированный Socratic follow-up (P1 #3) — перед QUIZ
TUTOR_SOCRATIC_MARKER = "=== SOCRATIC ==="


def _strip_thinking_tokens(text: str) -> str:
    """Remove <think>…</think> and similar reasoning blocks emitted by local models."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Unclosed <think> at start (model was cut off mid-thinking): drop everything up to first {
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _strip_code_fence(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    return raw


def _repair_json(text: str) -> str:
    """Best-effort cleanup of common local-model JSON mistakes.

    Only removes trailing commas before } or ] — a safe transformation that
    cannot corrupt valid JSON values.  A previous version also stripped
    ``//`` comments, but that regex is not string-aware and corrupts URLs
    inside string values (e.g. ``"https://example.com"`` → ``"https:"``).
    """
    # Remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def _extract_first_balanced_json_object(text: str) -> str | None:
    """Return the first complete {...} block by counting balanced braces.

    More reliable than rfind('}') when the text has multiple JSON-like
    fragments (e.g. a <think> block left orphan braces, or trailing commentary).
    """
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _strip_quiz_option_prefix(text: str) -> str:
    t = (text or "").strip()
    m = re.match(r"^(?:[A-Da-d]|\d+)[.)]\s*", t)
    if m:
        return t[m.end() :].strip()
    m = re.match(r"^[-*•]\s*", t)
    if m:
        return t[m.end() :].strip()
    return t


def _canonical_quiz_text(text: str) -> str:
    t = _strip_quiz_option_prefix(text).lower().replace("ё", "е")
    t = re.sub(r"[^\w\s]+", " ", t, flags=re.UNICODE)
    return " ".join(t.split())


def _canonical_token_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for token in _canonical_quiz_text(text).split():
        if len(token) >= 5:
            keys.add(token[:4])
        else:
            keys.add(token)
    return keys


def _best_ordering_option_match(
    value: str,
    opts: list[str],
    used_indices: set[int],
) -> int | None:
    needle = _canonical_quiz_text(value)
    if not needle:
        return None

    candidates: list[tuple[float, int]] = []
    needle_tokens = set(needle.split())
    for idx, opt in enumerate(opts):
        if idx in used_indices:
            continue
        haystack = _canonical_quiz_text(opt)
        if haystack == needle:
            return idx
        if needle in haystack or haystack in needle:
            candidates.append((0.95, idx))
            continue
        haystack_tokens = set(haystack.split())
        if needle_tokens and haystack_tokens:
            overlap = len(needle_tokens & haystack_tokens) / len(needle_tokens | haystack_tokens)
            if overlap >= 0.5:
                candidates.append((0.75 + overlap / 10, idx))
                continue
        needle_keys = _canonical_token_keys(needle)
        haystack_keys = _canonical_token_keys(haystack)
        if needle_keys and haystack_keys:
            stem_overlap = len(needle_keys & haystack_keys) / len(needle_keys | haystack_keys)
            if stem_overlap >= 0.5:
                candidates.append((0.72 + stem_overlap / 10, idx))
                continue
        ratio = SequenceMatcher(None, needle, haystack).ratio()
        if ratio >= 0.72:
            candidates.append((ratio, idx))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _parse_ordering_user(answer: str) -> list[str]:
    return [p.strip() for p in (answer or "").replace(";", ",").split(",") if p.strip()]


def _normalize_mc_options(opts: Any) -> list[str] | None:
    if isinstance(opts, list):
        out = [_strip_quiz_option_prefix(o) for o in opts if isinstance(o, str) and o.strip()]
        return out if len(out) == 4 else None
    if isinstance(opts, dict):
        out = []
        for letter in ("A", "B", "C", "D"):
            value = opts.get(letter) or opts.get(letter.lower())
            if not isinstance(value, str) or not value.strip():
                return None
            out.append(_strip_quiz_option_prefix(value))
        return out
    return None


def _normalize_ordering_correct(opts_raw: list[str], corr: Any) -> list[str] | None:
    opts = [
        _strip_quiz_option_prefix(o.strip())
        for o in opts_raw
        if isinstance(o, str) and o.strip()
    ]
    if len(opts) < 3 or len(opts) > 4:
        return None
    if not isinstance(corr, list) or len(corr) < 3:
        return None
    out: list[str] = []
    used_indices: set[int] = set()
    for x in corr:
        if isinstance(x, int):
            if 1 <= x <= len(opts):
                idx = x - 1
                if idx in used_indices:
                    return None
                used_indices.add(idx)
                out.append(opts[idx])
            else:
                return None
        elif isinstance(x, str):
            s = x.strip()
            if s.isdigit() and 1 <= int(s) <= len(opts):
                idx = int(s) - 1
                if idx in used_indices:
                    return None
                used_indices.add(idx)
                out.append(opts[idx])
            else:
                idx = _best_ordering_option_match(s, opts, used_indices)
                if idx is None:
                    return None
                used_indices.add(idx)
                out.append(opts[idx])
        else:
            return None
    if len(out) != len(opts):
        return None
    if used_indices != set(range(len(opts))):
        return None
    return out


def _parse_json_with_recovery(text: str) -> tuple[dict | None, str | None]:
    """Try to parse JSON, applying progressive recovery steps for local-model output."""
    # Step 1: strip thinking tokens, then code fence
    cleaned = _strip_code_fence(_strip_thinking_tokens(text))

    # Step 2: direct parse (fast path)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data, None
    except json.JSONDecodeError:
        pass

    # Step 3: balanced-brace extraction (handles preamble / trailing text)
    fragment = _extract_first_balanced_json_object(cleaned)
    if fragment:
        try:
            data = json.loads(fragment)
            if isinstance(data, dict):
                return data, None
        except json.JSONDecodeError:
            pass

        # Step 4: repair common mistakes (trailing commas, // comments)
        repaired = _repair_json(fragment)
        try:
            data = json.loads(repaired)
            if isinstance(data, dict):
                logger.debug("parse_json_with_recovery: repaired JSON successfully")
                return data, None
        except json.JSONDecodeError as e:
            return None, f"JSON: {e}"

    return None, "Ответ модели не похож на JSON-объект."


def parse_tutor_quiz_llm_json(text: str, *, n_questions: int = 3) -> tuple[dict[str, Any] | None, str | None]:
    """Parse interactive tutor quiz JSON v2.3; expects exactly n_questions questions."""
    data, err = _parse_json_with_recovery(text)
    if err or not isinstance(data, dict):
        return None, err or "Корень JSON должен быть объектом."
    title = (data.get("quiz_title") or "").strip() or "Quiz"
    raw_q = data.get("questions")
    if not isinstance(raw_q, list) or len(raw_q) != n_questions:
        return None, f"Ожидалось ровно {n_questions} вопросов в questions."
    norm: list[dict[str, Any]] = []
    for i, item in enumerate(raw_q):
        if not isinstance(item, dict):
            return None, f"Вопрос {i + 1}: ожидался объект."
        qtext = (item.get("q") or "").strip()
        expl = (item.get("explanation") or "").strip()
        concept = (item.get("concept") or "").strip()
        qtype = (item.get("type") or "").strip()
        if not qtext:
            return None, f"Вопрос {i + 1}: пустой текст q."
        if qtype not in _INTERACTIVE_QUIZ_TYPES:
            return None, f"Вопрос {i + 1}: неизвестный type: {qtype!r}."
        opts = item.get("options")
        corr = item.get("correct")

        if qtype == "multiple_choice":
            norm_opts = _normalize_mc_options(opts)
            if norm_opts is None:
                return None, f"Вопрос {i + 1}: multiple_choice — нужно 4 варианта."
            letter = str(corr).strip().upper() if corr is not None else ""
            if letter not in ("A", "B", "C", "D"):
                return None, f"Вопрос {i + 1}: correct — буква A-D."
            norm.append(
                {
                    "type": qtype,
                    "q": qtext,
                    "options": norm_opts,
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
                return None, (
                    f"Вопрос {i + 1}: fill_blank — options пустой или отсутствует."
                )
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
                return None, (
                    f"Вопрос {i + 1}: ordering — correct не согласован с options."
                )
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
    required = _INTERACTIVE_QUIZ_TYPES if n_questions >= 4 else _INTERACTIVE_QUIZ_TYPES_BASE
    missing = required - types_found
    if missing:
        missing_str = ", ".join(sorted(missing))
        return None, f"В квизе должны встретиться все типы вопросов; не хватает: {missing_str}."

    return {"quiz_title": title, "questions": norm}, None


def quiz_answer_correct(question: dict[str, Any], answer: Any) -> bool:
    qtype = question.get("type")
    correct = question.get("correct")
    if qtype == "multiple_choice":
        return str(answer or "").strip().upper() == str(correct or "").strip().upper()
    if qtype == "true_false":
        return str(answer or "").strip() == str(correct or "").strip()
    if qtype == "fill_blank":
        return str(answer or "").strip().lower() == str(correct or "").strip().lower()
    if qtype == "ordering":
        if not isinstance(correct, list):
            return False
        user_parts = _parse_ordering_user(str(answer or ""))
        if len(user_parts) != len(correct):
            return False
        user_norm = [_strip_quiz_option_prefix(part) for part in user_parts]
        correct_norm = [_strip_quiz_option_prefix(str(part)) for part in correct]
        return user_norm == correct_norm
    return False


def format_correct_for_export(question: dict[str, Any]) -> str:
    correct = question.get("correct")
    if isinstance(correct, list):
        return json.dumps(correct, ensure_ascii=False)
    return str(correct)


def build_flashcard_deck_request_from_interactive_quiz(
    quiz: dict[str, Any],
    questions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    Тело запроса POST /flashcards/decks для конвертации интерактивного квиза в колоду (US-15.6).
    Возвращает None, если не удалось собрать ни одной пары front/back.
    """
    cards: list[dict[str, Any]] = []
    for q in questions:
        front = (q.get("q") or q.get("question") or "").strip()
        correct_raw = format_correct_for_export(q)
        explanation = (q.get("explanation") or "").strip()
        back_parts = [correct_raw]
        if explanation:
            back_parts.append(explanation)
        back = "\n".join(back_parts).strip()
        concept = (q.get("concept") or "").strip()
        if front and back:
            cards.append({"front": front, "back": back, "tags": concept or None})
    if not cards:
        return None
    deck_name = f"Quiz: {quiz.get('quiz_title', 'Quiz')}"
    source_id = quiz.get("identifier") or quiz.get("quiz_title") or ""
    return {
        "name": deck_name,
        "source_type": "quiz",
        "source_identifier": source_id,
        "cards": cards,
    }


def _coerce_quiz_correct_index(raw: Any) -> int | None:
    """0..3 из int или целого float (JSON); bool не считаем индексом."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int) and 0 <= raw <= 3:
        return raw
    if isinstance(raw, float) and raw.is_integer():
        i = int(raw)
        if 0 <= i <= 3:
            return i
    return None


def _normalize_questions(raw: list[Any]) -> tuple[list[dict[str, Any]], str | None]:
    if len(raw) != 5:
        return [], f"Ожидалось 5 вопросов, получено {len(raw)}."
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            return [], f"Вопрос {i + 1}: ожидался объект JSON."
        q = (item.get("question") or "").strip()
        opts = item.get("options")
        ci = item.get("correct_index")
        if not q:
            return [], f"Вопрос {i + 1}: пустой текст."
        if not isinstance(opts, list) or len(opts) != 4:
            return [], f"Вопрос {i + 1}: нужно ровно 4 варианта."
        if not all(isinstance(o, str) and o.strip() for o in opts):
            return [], f"Вопрос {i + 1}: варианты должны быть непустыми строками."
        if not isinstance(ci, int) or ci < 0 or ci > 3:
            return [], f"Вопрос {i + 1}: correct_index должен быть 0..3."
        out.append({"question": q, "options": [o.strip() for o in opts], "correct_index": ci})
    return out, None


def parse_quiz_json(text: str) -> tuple[list[dict[str, Any]], str | None]:
    """Parse model output into validated question list (for tests)."""
    cleaned = _strip_code_fence(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", cleaned)
        if not m:
            return [], "Не удалось разобрать JSON с вопросами."
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            return [], f"JSON ошибка: {e}"
    if not isinstance(data, list):
        return [], "Корень JSON должен быть массивом."
    return _normalize_questions(data)


def _normalize_inline_questions(raw: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw[:2]:
        if not isinstance(item, dict):
            continue
        qtext = (item.get("question") or "").strip()
        if not qtext:
            continue
        qtype = (item.get("type") or "short_answer").strip().lower()
        if qtype not in ("short_answer", "multiple_choice", "free_recall"):
            qtype = "short_answer"
        concept = (item.get("concept") or "unknown").strip() or "unknown"
        diff = (item.get("difficulty") or "recall").strip().lower()
        if diff not in ("recognition", "recall", "transfer"):
            diff = "recall"
        entry: dict[str, Any] = {
            "type": qtype,
            "question": qtext,
            "concept": concept,
            "difficulty": diff,
        }
        if qtype == "multiple_choice":
            opts = item.get("options")
            if isinstance(opts, list) and len(opts) == 4 and all(isinstance(o, str) and o.strip() for o in opts):
                entry["options"] = [str(o).strip() for o in opts]
            ci = _coerce_quiz_correct_index(item.get("correct_index"))
            if ci is None:
                letter = str(item.get("correct_option") or item.get("correct") or "").strip().upper()[:1]
                if letter in ("A", "B", "C", "D"):
                    ci = ord(letter) - ord("A")
            if ci is not None:
                entry["correct_index"] = ci
        out.append(entry)
    return out


def _normalize_socratic_payload(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    t = str(data.get("type") or "").strip().lower()
    if t not in SOCRATIC_TYPE_KEYS:
        t = "probing"
    q = (data.get("question") or "").strip()
    if not q:
        return None
    return {"type": t, "question": q}


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    """Первый JSON-объект в строке (устойчиво к ```json и мусору до/после)."""
    cleaned = _strip_code_fence((text or "").strip())
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(cleaned)):
        if cleaned[i] == "{":
            depth += 1
        elif cleaned[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(cleaned[start : i + 1])
                    return data if isinstance(data, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def _is_tutor_v2_payload(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    return isinstance(data.get("teaching_summary"), str) and isinstance(
        data.get("understanding_state"), dict
    )


def format_tutor_v2_markdown(data: dict[str, Any]) -> str:
    """Человекочитаемый markdown из teaching JSON v2 (для чата и экспорта)."""
    lines: list[str] = []
    lines.append("### Кратко\n")
    lines.append(str(data.get("teaching_summary") or "").strip())
    us = data.get("understanding_state") or {}
    if isinstance(us, dict):
        lines.append("\n### Состояние понимания\n")
        lines.append(
            f"- **Что понял:** {str(us.get('what_you_understood') or '').strip()}"
        )
        lines.append(f"- **Где риск пробела:** {str(us.get('risk_gaps') or '').strip()}")
        lines.append(
            f"- **Что сделать сейчас:** {str(us.get('what_to_do_now') or '').strip()}"
        )
    sc = data.get("socratic_check")
    if sc is not None and str(sc).strip():
        lines.append(f"\n### Вопрос для размышления\n{str(sc).strip()}")
    na = str(data.get("next_action") or "").strip()
    nr = str(data.get("next_action_reason") or "").strip()
    if na or nr:
        lines.append("\n### Следующий шаг")
        if na:
            lines.append(f"**{na}**")
        if nr:
            lines.append(f"\n_{nr}_")
    ctas = data.get("suggested_ctas")
    if isinstance(ctas, list) and ctas:
        pretty = ", ".join(str(x).strip() for x in ctas if str(x).strip())
        if pretty:
            lines.append(f"\n**Подсказки для ответа:** {pretty}")
    depth = data.get("depth_level")
    ts = data.get("trust_signals") if isinstance(data.get("trust_signals"), dict) else {}
    lines.append("\n### Надёжность")
    lines.append(f"- **Глубина:** `{depth}`")
    if isinstance(ts, dict):
        su = ts.get("sources_used")
        cf = ts.get("confidence")
        lines.append(f"- **Источники (оценка):** {su} · **уверенность:** {cf}")
        cw = ts.get("coverage_warning")
        if cw:
            lines.append(f"- **Покрытие:** {cw}")
    return "\n".join(lines).strip()


def parse_tutor_rag_response(
    text: str,
) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]], dict[str, Any] | None]:
    """Текст для UI + Socratic + inline quiz + сырой teaching dict (v2) или None."""
    raw = (text or "").strip()
    socratic: dict[str, Any] | None = None
    quiz: list[dict[str, Any]] = []
    teaching: dict[str, Any] | None = None

    main_part = raw
    quiz_tail = ""
    if TUTOR_INLINE_QUIZ_MARKER in raw:
        main_part, quiz_tail = raw.split(TUTOR_INLINE_QUIZ_MARKER, 1)
    if quiz_tail:
        try:
            qdata = json.loads(_strip_code_fence(quiz_tail.strip()))
            qs = qdata.get("questions") if isinstance(qdata, dict) else None
            if isinstance(qs, list):
                quiz = _normalize_inline_questions(qs)
        except json.JSONDecodeError:
            logger.warning("tutor inline quiz JSON parse failed")

    main_part = main_part.strip()
    v2 = _extract_first_json_object(main_part)
    if v2 and _is_tutor_v2_payload(v2):
        teaching = v2
        display = format_tutor_v2_markdown(v2)
        sq = v2.get("socratic_check")
        if sq is not None and str(sq).strip():
            socratic = {"type": "probing", "question": str(sq).strip()}
        return display, socratic, quiz, teaching

    if TUTOR_SOCRATIC_MARKER in main_part:
        _, soc_rest = main_part.split(TUTOR_SOCRATIC_MARKER, 1)
        try:
            socratic = _normalize_socratic_payload(
                json.loads(_strip_code_fence(soc_rest.strip()))
            )
        except json.JSONDecodeError:
            logger.warning("tutor socratic JSON parse failed")

    return raw, socratic, quiz, teaching


def split_tutor_answer_and_quiz(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Разобрать ответ tutor+RAG: полный текст + вопросы quiz (совместимость)."""
    full, _, quiz, _ = parse_tutor_rag_response(text)
    return full, quiz
