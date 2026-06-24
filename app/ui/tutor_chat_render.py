"""Render helpers for tutor chat UI."""

from __future__ import annotations

import html
import re
from dataclasses import replace
from typing import Any

import streamlit as st

from app.ui.adaptive_plan_card import SmartStudyPrimaryNav, SmartStudyRecommendation
from app.ui.helpers import (
    build_tutor_action_items,
    build_tutor_orchestration_summary,
    esc_html,
)
from app.ui.tutor_chat_actions import handle_tutor_cta_click

SMART_STUDY_DEFER_SESSION_KEY = "smart_study_defer_pending"

# Splits inline numbering: "prefix: 1) A; 2) B" → ["prefix: ", "1", "A", "2", "B"]
_INLINE_NUM_SPLIT_RE = re.compile(r"\s*(?:;\s*)?(\d+)\)\s+")

# Inline markdown: **bold** and *italic*
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC_RE = re.compile(r"\*(.+?)\*")


def _md_inline(text: str) -> str:
    """Escape HTML entities then convert **bold** / *italic* to HTML."""
    text = html.escape(text)
    text = _MD_BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _MD_ITALIC_RE.sub(r"<em>\1</em>", text)
    return text


def _text_to_html(text: str) -> str:
    """Convert plain/markdown text to an HTML snippet for the styled block.

    Handles:
    - Inline numbering  "A: 1) x; 2) y; 3) z"  → <ol> items
    - Markdown lists    "1. x\\n2. y"  or  "- x\\n- y"  → <ol>/<ul> items
    - **bold**, *italic* inline markup
    - Plain paragraphs
    """
    # ── Step 1: convert legacy inline numbering to line-per-item format ──────
    parts = _INLINE_NUM_SPLIT_RE.split(text)
    if len(parts) >= 4:
        prefix = parts[0].rstrip(" :")
        items_md = "\n".join(
            f"{parts[i]}. {parts[i + 1].rstrip('; ')}"
            for i in range(1, len(parts) - 1, 2)
        )
        text = f"{prefix}:\n{items_md}"

    # ── Step 2: line-by-line → HTML ──────────────────────────────────────────
    lines = text.splitlines()
    html_parts: list[str] = []
    in_list: str | None = None  # "ol" or "ul"

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if in_list:
                html_parts.append(f"</{in_list}>")
                in_list = None
            continue

        ol_m = re.match(r"^(\d+)\.\s+(.*)", stripped)
        ul_m = re.match(r"^[-*]\s+(.*)", stripped)

        if ol_m:
            if in_list != "ol":
                if in_list:
                    html_parts.append(f"</{in_list}>")
                html_parts.append("<ol>")
                in_list = "ol"
            html_parts.append(f"<li>{_md_inline(ol_m.group(2))}</li>")
        elif ul_m:
            if in_list != "ul":
                if in_list:
                    html_parts.append(f"</{in_list}>")
                html_parts.append("<ul>")
                in_list = "ul"
            html_parts.append(f"<li>{_md_inline(ul_m.group(1))}</li>")
        else:
            if in_list:
                html_parts.append(f"</{in_list}>")
                in_list = None
            html_parts.append(f"<p>{_md_inline(stripped)}</p>")

    if in_list:
        html_parts.append(f"</{in_list}>")

    return "\n".join(html_parts)


def render_teaching_summary_block(text: str) -> None:
    """Render the tutor teaching summary in a richly styled contrasting card."""
    if not text:
        return
    inner = _text_to_html(text.strip())
    st.markdown(
        f'<div class="tutor-answer-block">{inner}</div>',
        unsafe_allow_html=True,
    )


def qa_sources_trust_low(last_answer: dict[str, Any] | None) -> bool:
    """True, если последний Q&A сигнализирует о слабой опоре на базу (локально, без сети)."""
    if not isinstance(last_answer, dict):
        return False
    conf = last_answer.get("confidence")
    level = ""
    if isinstance(conf, dict):
        level = str(conf.get("level") or conf.get("label") or "").strip().lower()
    if level in ("low", "very_low", "uncertain", "weak"):
        return True
    srcs = last_answer.get("sources")
    n = len(srcs) if isinstance(srcs, list) else 0
    if n == 0 and str(last_answer.get("answer") or "").strip():
        return True
    return False


def tutor_trust_signals_low(trust: dict[str, Any] | None) -> bool:
    """Низкая уверенность по trust_signals ответа тьютора."""
    if not isinstance(trust, dict):
        return False
    conf = str(trust.get("confidence") or "").strip().lower()
    if conf == "low":
        return True
    if int(trust.get("sources_used") or 0) <= 0 and str(trust.get("coverage_warning") or "").strip():
        return True
    return False


def effective_tutor_trust_signals(
    trust: dict[str, Any] | None,
    message_sources: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Prefer actual persisted sources when compact/legacy trust omits source count."""
    effective = dict(trust) if isinstance(trust, dict) else {}
    source_count = len(message_sources) if isinstance(message_sources, list) else 0
    try:
        trust_sources = int(effective.get("sources_used") or 0)
    except (TypeError, ValueError):
        trust_sources = 0
    if source_count > trust_sources:
        effective["sources_used"] = source_count
        effective.setdefault("confidence", "medium")
        if effective.get("coverage_warning") and source_count > 0:
            effective["coverage_warning"] = None
    return effective


def apply_source_trust_smart_study_overlay(
    rec: SmartStudyRecommendation,
    *,
    last_answer: dict[str, Any] | None = None,
    tutor_trust: dict[str, Any] | None = None,
) -> tuple[SmartStudyRecommendation, bool]:
    """Ветка source-trust: не перебивает очереди SM-2 / карточек / провала квиза / план."""
    if rec.hint_kind in ("cards_due", "sm2_due", "quiz_failed", "adaptive_plan"):
        return rec, False
    if not (
        qa_sources_trust_low(last_answer if isinstance(last_answer, dict) else None)
        or tutor_trust_signals_low(tutor_trust if isinstance(tutor_trust, dict) else None)
    ):
        return rec, False
    nav = rec.primary_nav
    if nav in ("flashcards_review", "sm2_tutor"):
        return rec, False
    if nav == "qa_continue":
        return (
            replace(
                rec,
                primary_label_ru="Сначала проверить источники",
                why_now_ru=(
                    "Низкая уверенность или слабое покрытие базы — откройте фрагменты и уточните формулировку, "
                    "прежде чем уходить в drill или квиз."
                ),
                primary_nav="qa_continue",
            ),
            True,
        )
    return (
        replace(
            rec,
            primary_label_ru="Сначала свериться с источниками (Q&A)",
            why_now_ru=(
                "Сигнал доверия слабый — безопаснее увидеть цитаты из индекса и переформулировать вопрос, "
                "чем сразу углубляться в сессию."
            ),
            primary_nav="qa_continue",
        ),
        True,
    )


_DEFER_ALTERNATE: dict[str, tuple[SmartStudyPrimaryNav, str, str]] = {
    "flashcards_review": (
        "safe_tutor_5min",
        "Мягкая сессия вместо повтора карточек",
        "Вы отложили повтор — можно коротко разобрать тему в чате и вернуться к карточкам позже.",
    ),
    "sm2_tutor": (
        "qa_continue",
        "Сверить факты в быстром ответе",
        "Отложили повтор темы — сначала посмотрите выдержки из базы, затем продолжайте повторение.",
    ),
    "quiz_recovery_tutor": (
        "qa_continue",
        "Проверить формулировку в Q&A",
        "Перед разбором ошибки квиза полезно убедиться в формулировке и источниках.",
    ),
    "tutor_resume": (
        "safe_tutor_5min",
        "Короткий чат без навязчивого продолжения",
        "Вы отложили возврат к диалогу — мягкий пятиминутный шаг без давления на контекст.",
    ),
    "qa_continue": (
        "safe_tutor_5min",
        "Короткий чат без давления",
        "Вы отложили шаг с быстрым ответом — можно мягко продолжить одним мини-шагом в тьюторе.",
    ),
    "tutor_weak_gap": (
        "qa_continue",
        "Сначала опереться на источники",
        "Альтернатива: уточните формулировку в Q&A, затем возвращайтесь к пробелу.",
    ),
    "plan_block_tutor": (
        "qa_continue",
        "Сверить материал перед шагом плана",
        "Отложили шаг плана — коротко откройте выдержки по теме, затем продолжите план.",
    ),
    "safe_tutor_5min": (
        "qa_continue",
        "Вернуться к источникам в Q&A",
        "Альтернатива к чату: проверьте фрагменты базы и вопрос в быстром ответе.",
    ),
}


def apply_smart_study_defer_alternate(rec: SmartStudyRecommendation) -> SmartStudyRecommendation:
    """Один мягкий альтернативный primary при «не сейчас» (session state хранит запрос отдельно)."""
    alt = _DEFER_ALTERNATE.get(rec.primary_nav)
    if not alt:
        nav3, label, why = _DEFER_ALTERNATE["safe_tutor_5min"]
        return replace(rec, primary_label_ru=label, why_now_ru=why, primary_nav=nav3)
    nav2, label2, why2 = alt
    return replace(rec, primary_label_ru=label2, why_now_ru=why2, primary_nav=nav2)


def resolve_smart_study_defer_for_session(
    rec: SmartStudyRecommendation,
    pending: dict[str, Any] | None,
) -> tuple[SmartStudyRecommendation, bool]:
    """Сопоставить отложенный «не сейчас» с текущей рекомендацией и один раз смягчить primary."""
    if not isinstance(pending, dict):
        return rec, False
    if pending.get("hint_kind") != rec.hint_kind or pending.get("primary_nav") != rec.primary_nav:
        return rec, False
    return apply_smart_study_defer_alternate(rec), True


def apply_smart_study_defer_from_session(rec: SmartStudyRecommendation) -> tuple[SmartStudyRecommendation, bool]:
    """Прочитать defer из session_state, применить при совпадении или сбросить устаревший запрос."""
    pending = st.session_state.get(SMART_STUDY_DEFER_SESSION_KEY)
    pend_dict = pending if isinstance(pending, dict) else None
    rec2, ok = resolve_smart_study_defer_for_session(rec, pend_dict)
    if ok or (pend_dict is not None and not ok):
        st.session_state.pop(SMART_STUDY_DEFER_SESSION_KEY, None)
    return rec2, ok


def compact_smart_study_router_trace_lines(
    rec: SmartStudyRecommendation,
    *,
    trust_branch_applied: bool,
    defer_applied: bool,
) -> list[str]:
    """Компактный reason-trace для explainability (без LLM)."""
    lines = [
        f"signal={rec.hint_kind}",
        f"primary_nav={rec.primary_nav}",
    ]
    if trust_branch_applied:
        lines.append("policy=source_trust_branch")
    if defer_applied:
        lines.append("policy=skip_with_memory_alternate")
    lines.append(f"secondaries={'|'.join(s.action_id for s in rec.secondaries)}")
    return lines


def render_smart_study_trust_controls(
    rec: SmartStudyRecommendation,
    *,
    key_prefix: str,
    trust_branch_applied: bool,
    defer_applied: bool,
) -> None:
    """Краткий след решения + «не сейчас» (память на один смягчённый шаг)."""
    trace = compact_smart_study_router_trace_lines(
        rec,
        trust_branch_applied=trust_branch_applied,
        defer_applied=defer_applied,
    )
    safe_pre = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in key_prefix)[:40] or "ssr"
    with st.expander("Как выбрана подсказка", expanded=False):
        st.caption(" · ".join(trace))
    if st.button(
        "Не сейчас — предложить мягкий вариант",
        key=f"{safe_pre}_ssr_defer",
        width="stretch",
    ):
        st.session_state[SMART_STUDY_DEFER_SESSION_KEY] = {
            "hint_kind": rec.hint_kind,
            "primary_nav": rec.primary_nav,
        }
        st.rerun()


def render_tutor_action_panel(
    ctas: list[Any],
    *,
    msg_idx: int,
    session_id: str,
    next_action: str | None = None,
) -> None:
    """Render action panel with CTA buttons."""
    from app.spaced_repetition import count_due_reviews

    due_n = count_due_reviews()
    action_items = build_tutor_action_items(
        [str(x).strip() for x in (ctas or []) if str(x).strip()],
        next_action=next_action,
        due_reviews_count=due_n,
    )
    st.markdown(
        """
<div style="
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 16px 20px;
    border-radius: 16px;
    margin: 12px 0 8px 0;
    box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
    text-align: center;
">
    <h4 style="margin:0; font-size:1.1rem; font-weight:700;">Что делаем дальше?</h4>
</div>
""",
        unsafe_allow_html=True,
    )

    icon_map = {
        "Понял": "✅",
        "Нужен пример": "💡",
        "Объясни проще": "📉",
        "Дай пример": "💡",
        "Проверь меня": "🧠",
        "Углубить по источникам": "🔎",
        "Следующий шаг": "🚀",
        "Пора повторить": "🔥",
        "Повтори позже": "🔄",
        "Дай задачу на применение": "📝",
        "Покажи связь с практикой": "🔗",
    }
    primary_labels = frozenset({"Понял", "Проверь меня", "Следующий шаг"})
    if due_n > 0:
        primary_labels = frozenset({"Понял", "Проверь меня", "Следующий шаг", "Пора повторить"})

    sid_key = session_id[:12] if session_id else "sess"
    cap = min(len(action_items), 8)
    for row_start in range(0, cap, 4):
        cols = st.columns(4, gap="small")
        for j in range(4):
            i = row_start + j
            if i >= cap:
                break
            action_item = action_items[i]
            text = action_item["label"]
            prompt = action_item["prompt"]
            icon = icon_map.get(text, "🔹")
            btn_type = "primary" if text in primary_labels else "secondary"
            label = f"{icon} {text}"
            with cols[j]:
                if st.button(
                    label,
                    key=f"tutor_ap_{sid_key}_{msg_idx}_{i}",
                    type=btn_type,
                    width='stretch',
                    help=f"Отправить тьютору: {prompt}",
                ):
                    handle_tutor_cta_click(prompt, session_id, msg_idx)


def render_tutor_visibility_badge(meta: dict[str, Any]) -> None:
    """US-4.2: orchestration transparency badge."""
    agent = str(meta.get("selected_agent") or "").strip()
    phase = str(meta.get("orchestration_phase") or "").strip()
    clamped = bool(meta.get("policy_clamped"))
    reasons_raw = meta.get("policy_clamp_reasons")
    reasons = [str(r).strip() for r in (reasons_raw if isinstance(reasons_raw, list) else []) if str(r).strip()]

    if not agent and not phase and not (clamped and reasons):
        return

    parts: list[str] = []
    if agent:
        parts.append(
            "<span style=\"background:#3949ab;color:#fff;padding:0.28rem 0.65rem;border-radius:8px;"
            'font-size:0.82rem;font-weight:700;display:inline-block;">'
            f"🎓 {html.escape(agent)}</span>"
        )
    if phase:
        parts.append(
            "<span style=\"background:#546e7a;color:#fff;padding:0.25rem 0.55rem;border-radius:8px;"
            'font-size:0.78rem;display:inline-block;">'
            f"{html.escape(phase)}</span>"
        )
    if clamped and reasons:
        rs = html.escape(", ".join(reasons[:5])[:220])
        parts.append(
            "<span style=\"background:#5d4037;color:#fff;padding:0.25rem 0.55rem;border-radius:8px;"
            'font-size:0.76rem;display:inline-block;">'
            f"policy: {rs}</span>"
        )
    elif clamped:
        parts.append(
            "<span style=\"background:#6d4c41;color:#fff;padding:0.25rem 0.55rem;border-radius:8px;"
            'font-size:0.76rem;display:inline-block;">policy clamp</span>'
        )

    st.markdown(
        "<div style=\"display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:4px 0 10px 0;\">"
        + "".join(parts)
        + "</div>",
        unsafe_allow_html=True,
    )


def render_tutor_trust_panel(
    trust: dict[str, Any],
    payload: dict[str, Any],
    *,
    key_suffix: str = "",
    message_sources: list[dict[str, Any]] | None = None,
) -> None:
    """Trust signals: source count, confidence and coverage warning."""
    trust = effective_tutor_trust_signals(trust, message_sources)
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        st.metric("Источники", int(trust.get("sources_used") or 0))
    with col2:
        conf = str(trust.get("confidence") or "medium")
        icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(conf, "⚪")
        st.metric("Уверенность", f"{icon} {conf}")
    with col3:
        cw = trust.get("coverage_warning")
        if cw:
            st.warning(f"⚠️ {cw}")
        else:
            st.success("Покрытие базы достаточное для ответа")
    st.caption(
        f"Глубина (JSON): **{payload.get('depth_level', '—')}** · "
        f"глубина UI: **{st.session_state.get('tutor_answer_depth', '—')}**"
    )
    ks = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in (key_suffix or "default"))[:48] or "default"
    with st.expander("Подробнее об источниках", expanded=False):
        if message_sources:
            from app.ui.source_cards import render_source_cards

            render_source_cards(message_sources, prefix=f"tutor_trust_{ks}"[:64])
        elif int(trust.get("sources_used") or 0) > 0:
            st.caption(
                "Список фрагментов для этого сообщения недоступен (старый ответ). "
                "Новые ответы сохраняют источники в истории сессии."
            )
        else:
            st.info(
                "К ответу не приложены фрагменты из индекса: возможен вывод без retrieval "
                "или сработали ограничения guardrails."
            )


def render_tutor_structured_response(
    data: dict[str, Any],
    *,
    msg_idx: int,
    session_id: str,
    tutor_meta: dict[str, Any] | None = None,
    message_sources: list[dict[str, Any]] | None = None,
) -> None:
    from app.ui.tutor_chat_response_render import render_tutor_structured_response as _impl

    _impl(
        data,
        msg_idx=msg_idx,
        session_id=session_id,
        tutor_meta=tutor_meta,
        message_sources=message_sources,
    )

def nba_from_tutor_decision(decision: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(decision, dict):
        return None
    action = decision.get("action") if isinstance(decision.get("action"), dict) else {}
    focus = str(decision.get("focus_topic") or "").strip()
    next_action = str(action.get("next_action") or "").strip()
    reason = str(action.get("next_action_reason") or "").strip()
    route = str(decision.get("route") or "").strip()
    if not (focus or next_action or reason or route):
        return None
    return {
        "concept": focus,
        "reason": reason,
        "action": next_action or route,
        "route": route,
    }
