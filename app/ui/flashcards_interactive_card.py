"""Interactive 3D flip flashcard — self-contained ``components.html`` iframe.

Same pattern already used for the D3 knowledge graph
(:mod:`app.ui.knowledge_graph_d3`) and the review keyboard
(:mod:`app.flashcards_review_keyboard`): a single ``<style>+<div>+<script>``
string rendered into an iframe. The flip and rating chips are fully
client-side (no Streamlit rerun); rating clicks bridge to the server by
``.click()``-ing the hidden native Streamlit buttons the review view renders
(``st-key-fc_rate_<q>`` / ``st-key-fc_gap_to_tutor``) — see
``app.ui.flashcards_review_view._render_review_rating_bridge``.

The iframe does not inherit host CSS, so its palette is passed as parameters
from the current theme preset and small derived colours are computed inside
``build_interactive_card_html`` instead of relying on ``app/ui_theme.css``.
"""

from __future__ import annotations

import html
import json
from typing import Any

from app.flashcards_rating_labels import RATING_BUTTONS, RATING_MEANINGS
from app.flashcards_scheduling import format_interval_ru
from app.flashcards_tag_display import escape_multiline, source_display, split_card_tags
from app.ui.flashcards_interactive_card_style import STYLE_TEMPLATE
from app.ui.flashcards_interactive_card_script import build_interactive_card_script

_INK = "#132019"
_MUTED = "#59685f"
_ACCENT = "#b95631"
# System mono stack (matches --font-mono in ui_theme.css; iframe has no host CSS vars).
_MONO = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace'

_DECK_SOURCE_ICONS: dict[str, str] = {
    "course": "🎓",
    "manual": "✍️",
    "quiz": "🧩",
}

_RING_RADIUS = 26
_RING_CIRCUMFERENCE = round(2 * 3.14159265358979 * _RING_RADIUS, 2)

_BASE_HEIGHT = 360
_MAX_HEIGHT = 900
_MIN_HEIGHT = 220


def _with_hex_alpha(color: str, alpha_hex: str) -> str:
    value = str(color or "").strip()
    if (
        len(value) == 7
        and value.startswith("#")
        and len(alpha_hex) == 2
        and all(ch in "0123456789abcdefABCDEF" for ch in value[1:] + alpha_hex)
    ):
        return f"{value}{alpha_hex}"
    return value


def estimate_interactive_card_height(card: dict[str, Any]) -> int:
    """Iframe height (px) for ``components.html``.

    This is the *only* number that actually controls the visible box: the
    iframe's own JS also measures its rendered content
    (``measureNaturalHeight`` in the builder's script) and resizes the
    *inner* ``.fc3-card`` div to match, but the ``streamlit:setFrameHeight``
    postMessage it sends to ask the host to resize the outer iframe itself
    is not received by anything — ``components.html()`` renders a plain
    ``st.iframe``-style element (verified against the installed Streamlit's
    frontend bundle), not a ``declare_component`` instance, and only the
    latter listens for that message. If this estimate undershoots the real
    rendered height, the extra content is cut off at the iframe boundary
    with nothing to scroll it into view (mitigated by ``scrolling=True`` at
    the call site, but that's a fallback, not a fix) — so this should stay a
    generous over-estimate, not a tight one.
    """
    front_len = len(str(card.get("front") or ""))
    back_len = len(str(card.get("back") or ""))
    text_extra = max(0, (front_len + back_len) - 200) // 3

    human_tags, system_tags = split_card_tags(card.get("tags"))
    # Tag chips wrap onto their own lines and aren't reflected in front/back
    # length at all — a card with many tags needs materially more height.
    tags_extra = 28 * max(0, len(human_tags) - 2)
    if source_display(system_tags) is not None:
        tags_extra += 18

    return min(_MAX_HEIGHT, _BASE_HEIGHT + text_extra + tags_extra)


def _deck_badge_html(card: dict[str, Any]) -> str:
    deck_name = str(card.get("deck_name") or "Колода").strip() or "Колода"
    source_type = str(card.get("deck_source_type") or "").strip().lower()
    icon = _DECK_SOURCE_ICONS.get(source_type, "🗂")
    return f'<div class="fc3-deck-badge">{html.escape(icon)} {html.escape(deck_name)}</div>'


def _tags_html(card: dict[str, Any]) -> str:
    human_tags, system_tags = split_card_tags(card.get("tags"))
    chips = "".join(f'<span class="fc3-tag-chip">{html.escape(tag)}</span>' for tag in human_tags)
    chips_html = f'<div class="fc3-tag-chips">{chips}</div>' if chips else ""
    src = source_display(system_tags)
    source_html = ""
    if src is not None:
        icon, label = src
        source_html = f'<div class="fc3-source">{html.escape(icon)} {html.escape(label)}</div>'
    if not chips_html and not source_html:
        return ""
    return f'<div class="fc3-tags">{chips_html}{source_html}</div>'


def _strength_ring_html(strength_pct: int) -> str:
    pct = max(0, min(100, int(strength_pct)))
    offset = round(_RING_CIRCUMFERENCE * (1 - pct / 100.0), 2)
    return f"""<div class="fc3-ring">
  <svg viewBox="0 0 64 64" width="64" height="64">
    <circle class="fc3-ring-track" cx="32" cy="32" r="{_RING_RADIUS}"></circle>
    <circle id="fc3-ring-fill" class="fc3-ring-fill" cx="32" cy="32" r="{_RING_RADIUS}"
      stroke-dasharray="{_RING_CIRCUMFERENCE}" stroke-dashoffset="{_RING_CIRCUMFERENCE}"
      data-offset="{offset}"></circle>
  </svg>
  <div class="fc3-ring-label">{pct}%</div>
</div>"""


def _details_html(*, memory: dict[str, Any], card: dict[str, Any]) -> str:
    interval_days = int(memory.get("interval_days", card.get("interval_days") or 0))
    repetitions = int(memory.get("repetitions", card.get("repetitions") or 0))
    ease_label = html.escape(str(memory.get("ease_label_ru") or ""))
    last_review = str(card.get("last_review") or "").strip()
    last_review_ru = html.escape(last_review[:10]) if last_review else "—"
    return f"""<details class="fc3-details">
  <summary>Детали памяти</summary>
  <div class="fc3-details-grid">
    <div><span class="fc3-details-k">Интервал</span><span class="fc3-details-v">{interval_days} дн.</span></div>
    <div><span class="fc3-details-k">Повторений</span><span class="fc3-details-v">{repetitions}</span></div>
    <div><span class="fc3-details-k">Лёгкость</span><span class="fc3-details-v">{ease_label}</span></div>
    <div><span class="fc3-details-k">Последний повтор</span><span class="fc3-details-v">{last_review_ru}</span></div>
  </div>
</details>"""


def _rating_chips_html(interval_preview: dict[str, int]) -> str:
    """Rating chips: mnemonic meaning primary, interval secondary (W4)."""
    chips = []
    for label, q_label, _quality, color in RATING_BUTTONS:
        eta_days = int(interval_preview.get(q_label, 1))
        eta_ru = html.escape(format_interval_ru(eta_days))
        meaning = html.escape(RATING_MEANINGS.get(q_label, ""))
        label_esc = html.escape(label)
        # Accessible name: mnemonic judgement first, then grade label + interval.
        aria = html.escape(f"{meaning}. {label}. Интервал: {format_interval_ru(eta_days)}")
        chips.append(
            f'<button type="button" class="fc3-rate-chip" data-q="{q_label}" '
            f'style="--fc3-rate-color:{color}" aria-label="{aria}">'
            f'<span class="fc3-rate-meaning" aria-hidden="true">{meaning}</span>'
            f'<span class="fc3-rate-label" aria-hidden="true">{label_esc}</span>'
            f'<span class="fc3-rate-eta" aria-hidden="true">→ {eta_ru}</span>'
            f"</button>"
        )
    return "".join(chips)


def _scene_markup(
    *,
    style: str,
    card: dict,
    counter: str,
    front_html: str,
    back_html: str,
    strength_pct: int,
    status_label: str,
    status_color: str,
    forecast_ru: str,
    memory: dict,
    interval_preview: dict,
) -> str:
    """Front/back DOM for the flip card (style + faces, no script)."""
    return f"""{style}
<div class="fc3-scene" id="fc3-scene" data-fc3-scroll-fallback="host-scrolling">
  <div class="fc3-sr-only" id="fc3-flip-status" aria-live="polite" aria-atomic="true"></div>
  <div class="fc3-card" id="fc3-card" data-side="front">
    <div class="fc3-face fc3-front" id="fc3-front">
      <div class="fc3-top-row">
        {_deck_badge_html(card)}
        <div class="fc3-counter">{html.escape(counter)}</div>
      </div>
      <div class="fc3-label" id="fc3-front-label">Вопрос</div>
      <div class="fc3-text">{front_html}</div>
      {_tags_html(card)}
      <div class="fc3-memory-row">
        {_strength_ring_html(strength_pct)}
        <div class="fc3-memory-meta">
          <span class="fc3-status-chip" style="background:{status_color}">{status_label}</span>
          <div class="fc3-forecast">{forecast_ru}</div>
        </div>
      </div>
      {_details_html(memory=memory, card=card)}
      <button type="button" class="fc3-flip-surface" id="fc3-flip-surface"
        aria-pressed="false"
        aria-controls="fc3-card"
        aria-describedby="fc3-flip-status"
        aria-label="Показать ответ. Сейчас: вопрос.">
        Показать ответ
      </button>
      <div class="fc3-hint">Space / Enter — перевернуть · 1–4 — оценка после ответа</div>
    </div>
    <div class="fc3-face fc3-back" id="fc3-back">
      <div class="fc3-label" id="fc3-back-label">Ответ</div>
      <div class="fc3-text">{back_html}</div>
      <div class="fc3-rate-row" role="group" aria-label="Оценка припоминания">{_rating_chips_html(interval_preview)}</div>
      <button type="button" class="fc3-explain-chip" id="fc3-explain">🤔 Не знаю — объясни</button>
      <button type="button" class="fc3-flip-back" id="fc3-flip-back"
        aria-pressed="true"
        aria-controls="fc3-card"
        aria-label="Вернуться к вопросу. Сейчас: ответ.">↩ к вопросу</button>
    </div>
  </div>
</div>
"""

def build_interactive_card_html(
    *,
    card: dict[str, Any],
    idx: int,
    total: int,
    interval_preview: dict[str, int],
    memory: dict[str, Any],
    initial_flipped: bool,
    session_nonce: int,
    ink: str = "#132019",
    muted: str = "#59685f",
    accent: str = "#b95631",
    mono: str = _MONO,
    front_bg: str = "linear-gradient(160deg, rgba(36,59,44,0.04) 0%, rgba(185,86,49,0.04) 100%)",
    back_bg: str = "linear-gradient(160deg, rgba(185,86,49,0.07) 0%, rgba(36,59,44,0.05) 100%)",
) -> str:
    """Self-contained iframe markup: style + faces + client script.

    ``session_nonce`` namespaces the client-side flip flag in sessionStorage.
    Theme colours come from the caller (theme presets); defaults are forest.
    """
    card_id = int(card.get("id") or 0)
    front_html = escape_multiline(card.get("front"))
    back_html = escape_multiline(card.get("back"))
    counter = f"{idx + 1} / {max(total, idx + 1)}"
    strength_pct = int(memory.get("strength_pct", 0))
    status_label = html.escape(str(memory.get("status_label_ru") or ""))
    status_color = html.escape(str(memory.get("status_color") or muted))
    forecast_ru = html.escape(str(memory.get("forecast_ru") or ""))
    # Literal st-key-fc_rate_<q> bridge selectors from RATING_BUTTONS.
    rate_class_map_json = json.dumps(
        {q_label: f"st-key-fc_rate_{q_label}" for _label, q_label, _quality, _color in RATING_BUTTONS}
    )
    style = STYLE_TEMPLATE.format(
        MONO=mono,
        INK=ink,
        INK_SOFT=_with_hex_alpha(ink, "22"),
        MUTED=muted,
        ACCENT=accent,
        FRONT_BG=front_bg,
        BACK_BG=back_bg,
    )
    scene = _scene_markup(
        style=style,
        card=card,
        counter=counter,
        front_html=front_html,
        back_html=back_html,
        strength_pct=strength_pct,
        status_label=status_label,
        status_color=status_color,
        forecast_ru=forecast_ru,
        memory=memory,
        interval_preview=interval_preview,
    )
    script = build_interactive_card_script(
        card_id=card_id,
        session_nonce=int(session_nonce),
        initial_flipped=bool(initial_flipped),
        rate_class_map_json=rate_class_map_json,
        min_height=_MIN_HEIGHT,
        max_height=_MAX_HEIGHT,
    )
    return f"{scene}<script>\n{script}</script>"

