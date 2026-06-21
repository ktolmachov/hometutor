"""Вспомогательные функции вкладки «Быстрый ответ» (P5c split)."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence


def first_answer_examples(suggestions: Sequence[str], *, has_index_content: bool) -> list[str]:
    """US-3.3: choose up to 3 clickable examples for the first-answer hero."""
    if not has_index_content:
        return []
    unique: list[str] = []
    seen: set[str] = set()
    for raw in suggestions:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
        if len(unique) == 3:
            break
    return unique


def answer_latency_caption(debug: dict) -> str | None:
    """E9.5 / US-3.1: подпись латентности последнего ответа без разбора JSON."""
    ms = debug.get("total_answer_ms")
    if ms is None:
        return None
    try:
        m = float(ms)
    except (TypeError, ValueError):
        return None
    if m < 2000.0:
        bucket = "быстро"
    elif m < 8000.0:
        bucket = "нормально"
    else:
        bucket = "долго"
    return f"Время ответа: ~{int(round(m))} ms ({bucket})"


def infer_topic_label_from_last_answer(last: dict) -> str:
    """Тема для CTA «Учить эту тему»: topic из метаданных, иначе имя файла/вопрос."""
    sources = last.get("sources") or []
    for s in sources:
        if not isinstance(s, dict):
            continue
        meta = s.get("metadata") if isinstance(s.get("metadata"), dict) else {}
        t = (s.get("topic") or meta.get("topic") or "").strip()
        if t:
            return t[:120]
    for s in sources:
        if not isinstance(s, dict):
            continue
        fp = (s.get("file_name") or s.get("relative_path") or "").strip()
        if fp:
            stem = Path(fp).stem.replace("_", " ").replace("-", " ")
            if stem:
                return stem[:120]
    q = (last.get("question") or "").strip()
    if len(q) > 8:
        return q[:120]
    return ""


def summarize_answer_for_handoff(last: dict) -> str:
    answer = (last.get("answer") or "").strip()
    if not answer:
        return ""
    if len(answer) <= 280:
        return answer
    return answer[:279].rstrip() + "…"
