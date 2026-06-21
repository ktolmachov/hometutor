"""Explainability ledger builders for Smart Study Router."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.smart_study_recommendation import _quiz_feedback_failed, _ru_flashcard_due_word, _STEERING_PREFS


@dataclass(frozen=True)
class EvidenceItem:
    """Один локальный сигнал SSR для explainability ledger."""

    key: str
    label_ru: str
    value: str
    influenced: bool

    def as_line_ru(self) -> str:
        return f"{self.label_ru}: {self.value}"


def build_smart_study_evidence_items(
    *,
    flashcard_due_n: int = 0,
    sm2_due_n: int = 0,
    quiz_feedback_status: str | None = None,
    has_last_answer_qa: bool = False,
    last_answer: dict[str, Any] | None = None,
    tutor_trust: dict[str, Any] | None = None,
    defer_applied: bool = False,
    trust_branch_applied: bool = False,
    steering_local: str | None = None,
) -> tuple[EvidenceItem, ...]:
    """US-20.8: typed локальные сигналы; ``influenced`` отделяет причину от debug-шумов."""
    fc = max(0, int(flashcard_due_n))
    sm2 = max(0, int(sm2_due_n))
    items: list[EvidenceItem] = []

    if fc > 0:
        w = _ru_flashcard_due_word(fc)
        items.append(
            EvidenceItem("cards_due", "Очередь flashcards (локально)", f"{fc} {w} к повтору", True)
        )
    else:
        items.append(EvidenceItem("cards_due", "Очередь flashcards (локально)", "нет срочных (0)", False))

    if sm2 > 0:
        items.append(
            EvidenceItem("sm2_due", "Очередь концептов SM-2 (локально)", f"{sm2} к повтору", True)
        )
    else:
        items.append(EvidenceItem("sm2_due", "Очередь концептов SM-2 (локально)", "нет срочных (0)", False))

    qs = str(quiz_feedback_status or "").strip()
    if qs:
        qlow = qs.lower()
        if _quiz_feedback_failed(qs):
            items.append(
                EvidenceItem("quiz_feedback", "Мини-quiz (tutor, локально)", f"сигнал провала ({qs})", True)
            )
        elif qlow in ("pass", "passed", "ok", "correct", "good"):
            items.append(
                EvidenceItem("quiz_feedback", "Мини-quiz (tutor, локально)", f"последний статус «{qs}»", False)
            )
        else:
            items.append(
                EvidenceItem("quiz_feedback", "Мини-quiz (tutor, локально)", f"последний статус «{qs}»", False)
            )
    else:
        items.append(EvidenceItem("quiz_feedback", "Мини-quiz (tutor, локально)", "нет сохранённого статуса", False))

    items.append(
        EvidenceItem(
            "qa_ready",
            "Быстрый ответ (готовность Q&A)",
            "да" if has_last_answer_qa else "нет",
            bool(has_last_answer_qa),
        )
    )

    qa_conf_line: str | None = None
    qa_conf_influenced = False
    if isinstance(last_answer, dict):
        conf_obj = last_answer.get("confidence")
        if isinstance(conf_obj, dict):
            lvl = str(conf_obj.get("level") or conf_obj.get("label") or "").strip()
            score = conf_obj.get("score")
            if lvl:
                qa_conf_line = f"уровень confidence.level: «{lvl}» (локально из ответа Q&A)"
                qa_conf_influenced = lvl.lower() in {"low", "medium", "weak"}
            elif score is not None:
                try:
                    score_f = float(score)
                    qa_conf_line = f"confidence.score: {score_f:.3g} (локально из ответа Q&A)"
                    qa_conf_influenced = score_f < 0.7
                except (TypeError, ValueError):
                    qa_conf_line = "поле confidence есть, числовой score недоступен"
            else:
                qa_conf_line = "поле confidence есть без уровня — сверьте источники вручную"
        elif conf_obj is not None:
            qa_conf_line = "неструктурированное confidence (сигнал без стандартного уровня)"
    items.append(
        EvidenceItem(
            "qa_confidence",
            "Локальная опора retrieval (быстрый ответ / индекс)",
            qa_conf_line or "недоступна (нет поля confidence)",
            qa_conf_influenced,
        )
    )

    if isinstance(tutor_trust, dict) and tutor_trust:
        tconf = str(tutor_trust.get("confidence") or "").strip() or "—"
        nsrc = int(tutor_trust.get("sources_used") or 0)
        low_trust = tconf.lower() in {"low", "weak"} or nsrc < 2 or bool(tutor_trust.get("coverage_warning"))
        items.append(
            EvidenceItem(
                "tutor_trust",
                "Сигналы тьютора (локально, последний ответ)",
                f"confidence={tconf}, источников: {nsrc}",
                low_trust,
            )
        )
    else:
        items.append(
            EvidenceItem("tutor_trust", "Сигналы тьютора (доверие к выдержкам)", "недоступны в этом снимке", False)
        )

    items.append(
        EvidenceItem(
            "defer",
            "Память «не сейчас» (отложение)",
            "активен мягкий альтернативный шаг" if defer_applied else "не активна",
            bool(defer_applied),
        )
    )
    items.append(
        EvidenceItem(
            "source_trust",
            "Коррекция по опоре на базу (source-trust)",
            "да" if trust_branch_applied else "нет",
            bool(trust_branch_applied),
        )
    )
    sl = (steering_local or "").strip().lower()
    steering_value = {
        "review_first": "сначала повтор",
        "new_topic": "новая тема",
        "gentle": "мягкий режим",
    }.get(sl, "нет (базовая политика)")
    items.append(
        EvidenceItem("steering", "Локальный руль SSR (сохранено)", steering_value, sl in _STEERING_PREFS)
    )
    return tuple(items)


def finalize_smart_study_confidence_ledger_lines(
    ledger_lines: list[str] | None,
    *,
    hint_kind: str,
    primary_nav: str,
    weak_concept: str | None = None,
) -> list[str]:
    """US-20 confidence ledger: добавить проверяемый reason-trace и топ-пробел без дублей.

    Используется в Explainable Next Step Card там, где финальный ``rec`` уже известен,
    а строки леджера собраны из снимка сессии отдельно.
    """
    lines = list(ledger_lines or [])
    prefix: list[str] = []

    wc = str(weak_concept or "").strip()
    if wc and not any(wc in row for row in lines):
        prefix.append(f"Пробел мастерства / тема повторения (локально): {wc}")

    hk = str(hint_kind or "").strip()
    pn = str(primary_nav or "").strip()
    trace = f"Детерминированный след маршрута (локально): hint_kind={hk}; primary_nav={pn}"
    if hk and pn:
        has_trace = any("hint_kind=" in row and "primary_nav=" in row for row in lines)
        if not has_trace:
            prefix.append(trace)

    return prefix + lines


def build_smart_study_evidence_ledger_lines(
    *,
    flashcard_due_n: int = 0,
    sm2_due_n: int = 0,
    quiz_feedback_status: str | None = None,
    has_last_answer_qa: bool = False,
    last_answer: dict[str, Any] | None = None,
    tutor_trust: dict[str, Any] | None = None,
    defer_applied: bool = False,
    trust_branch_applied: bool = False,
    steering_local: str | None = None,
    include_all: bool = True,
) -> list[str]:
    """US-20.8: компактные локальные сигналы без выдуманной «уверенности» и без облачного профилирования."""
    items = build_smart_study_evidence_items(
        flashcard_due_n=flashcard_due_n,
        sm2_due_n=sm2_due_n,
        quiz_feedback_status=quiz_feedback_status,
        has_last_answer_qa=has_last_answer_qa,
        last_answer=last_answer,
        tutor_trust=tutor_trust,
        defer_applied=defer_applied,
        trust_branch_applied=trust_branch_applied,
        steering_local=steering_local,
    )
    visible = items if include_all else tuple(item for item in items if item.influenced)
    return [item.as_line_ru() for item in visible]
