"""Interactive 3D flip flashcard — self-contained ``components.html`` iframe.

Same pattern already used for the D3 knowledge graph
(:mod:`app.ui.knowledge_graph_d3`) and the review keyboard
(:mod:`app.flashcards_review_keyboard`): a single ``<style>+<div>+<script>``
string rendered into an iframe. The flip and rating chips are fully
client-side (no Streamlit rerun); rating clicks bridge to the server by
``.click()``-ing the hidden native Streamlit buttons the review view renders
(``st-key-fc_rate_<q>`` / ``st-key-fc_gap_to_tutor``) — see
``app.ui.flashcards_review_view._render_review_rating_bridge``.

The iframe does not inherit host CSS, so every colour/font used here is a
mirrored literal, not a CSS variable from ``app/ui_theme.css``.
"""

from __future__ import annotations

import html
import json
from typing import Any

from app.flashcards_rating_labels import RATING_BUTTONS, RATING_MEANINGS
from app.flashcards_scheduling import format_interval_ru
from app.flashcards_tag_display import escape_multiline, source_display, split_card_tags

_INK = "#132019"
_MUTED = "#59685f"
_ACCENT = "#b95631"
_MONO = "ui-monospace,'IBM Plex Mono',monospace"

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


def estimate_interactive_card_height(card: dict[str, Any]) -> int:
    """Initial iframe height (px) for ``components.html``, before the iframe's
    own JS measures its actual rendered content and asks Streamlit to resize
    it (``streamlit:setFrameHeight`` in the builder's script) — this is only
    the first-paint fallback, so it only needs to be a reasonable estimate,
    not exact.
    """
    front_len = len(str(card.get("front") or ""))
    back_len = len(str(card.get("back") or ""))
    extra = max(0, (front_len + back_len) - 200) // 3
    return min(_MAX_HEIGHT, _BASE_HEIGHT + extra)


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
    chips = []
    for label, q_label, _quality, color in RATING_BUTTONS:
        eta_days = int(interval_preview.get(q_label, 1))
        eta_ru = html.escape(format_interval_ru(eta_days))
        meaning = html.escape(RATING_MEANINGS.get(q_label, ""))
        chips.append(
            f'<button type="button" class="fc3-rate-chip" data-q="{q_label}" '
            f'style="--fc3-rate-color:{color}">'
            f'<span class="fc3-rate-label">{html.escape(label)}</span>'
            f'<span class="fc3-rate-meaning">{meaning}</span>'
            f'<span class="fc3-rate-eta">→ {eta_ru}</span>'
            f"</button>"
        )
    return "".join(chips)


_STYLE = f"""<style>
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0; padding: 0; background: transparent; font-family: {_MONO};
    height: 100%; width: 100%;
  }}
  .fc3-scene {{
    width: 100%; height: 100%; perspective: 1600px; cursor: pointer;
    padding: 6px;
  }}
  .fc3-card {{
    position: relative; width: 100%; height: 100%;
    transition: transform 0.5s cubic-bezier(0.4, 0.2, 0.2, 1);
    transform-style: preserve-3d;
  }}
  .fc3-card.is-flipped {{ transform: rotateY(180deg); }}
  .fc3-face {{
    position: absolute; inset: 0; backface-visibility: hidden;
    border-radius: 20px; border: 1px solid rgba(19, 32, 25, 0.12);
    box-shadow: 0 18px 40px rgba(19, 32, 25, 0.12);
    padding: 1.6rem 1.6rem 1.2rem; display: flex; flex-direction: column;
    overflow-y: auto; color: {_INK};
  }}
  .fc3-face.fc3-front {{
    background: linear-gradient(160deg, rgba(36,59,44,0.05) 0%, rgba(185,86,49,0.05) 100%);
  }}
  .fc3-face.fc3-back {{
    background: linear-gradient(160deg, rgba(185,86,49,0.08) 0%, rgba(36,59,44,0.06) 100%);
    border-left: 4px solid {_ACCENT};
    transform: rotateY(180deg);
  }}
  .fc3-top-row {{ display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }}
  .fc3-deck-badge {{
    font-size: 0.72rem; color: {_MUTED}; text-transform: uppercase; letter-spacing: 0.05em;
  }}
  .fc3-counter {{ font-size: 0.72rem; color: {_MUTED}; }}
  .fc3-label {{
    font-size: 0.72rem; color: {_MUTED}; text-transform: uppercase; letter-spacing: 0.08em;
    margin: 0.9rem 0 0.6rem; font-weight: 600;
  }}
  .fc3-text {{ font-size: 1.15rem; font-weight: 600; line-height: 1.55; flex: 0 0 auto; }}
  .fc3-tags {{ margin-top: 0.9rem; }}
  .fc3-tag-chips {{ display: flex; flex-wrap: wrap; gap: 0.35rem; }}
  .fc3-tag-chip {{
    font-size: 0.7rem; color: {_ACCENT}; background: rgba(185,86,49,0.10);
    border: 1px solid rgba(185,86,49,0.22); border-radius: 999px; padding: 2px 9px;
  }}
  .fc3-source {{ font-size: 0.68rem; color: {_MUTED}; margin-top: 0.4rem; }}
  .fc3-memory-row {{ display: flex; align-items: center; gap: 0.8rem; margin-top: 1rem; }}
  .fc3-ring {{ position: relative; width: 64px; height: 64px; flex: 0 0 auto; }}
  .fc3-ring svg {{ transform: rotate(-90deg); }}
  .fc3-ring-track {{ fill: none; stroke: rgba(19,32,25,0.10); stroke-width: 6; }}
  .fc3-ring-fill {{
    fill: none; stroke: {_ACCENT}; stroke-width: 6; stroke-linecap: round;
    transition: stroke-dashoffset 0.9s ease;
  }}
  .fc3-ring-label {{
    position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
    font-size: 0.78rem; font-weight: 700; transform: none;
  }}
  .fc3-memory-meta {{ flex: 1 1 auto; min-width: 0; }}
  .fc3-status-chip {{
    display: inline-block; font-size: 0.68rem; font-weight: 700; padding: 2px 9px;
    border-radius: 999px; color: #fff;
  }}
  .fc3-forecast {{ font-size: 0.72rem; color: {_MUTED}; margin-top: 0.3rem; }}
  .fc3-details {{ margin-top: 0.9rem; font-size: 0.75rem; color: {_MUTED}; }}
  .fc3-details summary {{ cursor: pointer; color: {_ACCENT}; font-weight: 600; }}
  .fc3-details-grid {{
    display: grid; grid-template-columns: 1fr 1fr; gap: 0.4rem 0.8rem; margin-top: 0.5rem;
  }}
  .fc3-details-grid > div {{ display: flex; flex-direction: column; }}
  .fc3-details-k {{ font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.04em; }}
  .fc3-details-v {{ font-size: 0.85rem; color: {_INK}; font-weight: 600; }}
  .fc3-hint {{ margin-top: auto; padding-top: 0.8rem; font-size: 0.68rem; color: {_MUTED}; text-align: center; }}
  .fc3-rate-row {{ display: flex; gap: 0.5rem; margin-top: 0.9rem; flex-wrap: wrap; }}
  .fc3-rate-chip {{
    flex: 1 1 0; min-width: 90px; display: flex; flex-direction: column; align-items: center;
    gap: 0.15rem; padding: 0.55rem 0.4rem; border-radius: 14px; border: none; cursor: pointer;
    background: var(--fc3-rate-color, {_ACCENT}); color: #fff; font-family: {_MONO};
    transition: transform 0.12s ease, box-shadow 0.12s ease;
  }}
  .fc3-rate-chip:hover {{ transform: translateY(-2px); box-shadow: 0 8px 18px rgba(19,32,25,0.22); }}
  .fc3-rate-chip:active {{ transform: scale(0.94); }}
  .fc3-rate-chip.fc3-pop {{ animation: fc3-pop 0.22s ease; }}
  @keyframes fc3-pop {{ 0% {{ transform: scale(1); }} 50% {{ transform: scale(0.88); }} 100% {{ transform: scale(1); }} }}
  .fc3-rate-label {{ font-size: 0.85rem; font-weight: 700; }}
  .fc3-rate-meaning {{ font-size: 0.65rem; opacity: 0.9; }}
  .fc3-rate-eta {{ font-size: 0.68rem; font-weight: 700; opacity: 0.95; }}
  .fc3-explain-chip {{
    margin-top: 0.6rem; width: 100%; padding: 0.5rem; border-radius: 12px; border: 1px solid rgba(19,32,25,0.18);
    background: transparent; color: {_MUTED}; font-family: {_MONO}; font-size: 0.78rem; cursor: pointer;
  }}
  .fc3-explain-chip:hover {{ color: {_ACCENT}; border-color: {_ACCENT}; }}
  .fc3-flip-back {{
    margin-top: 0.5rem; align-self: flex-start; background: none; border: none; cursor: pointer;
    color: {_MUTED}; font-family: {_MONO}; font-size: 0.72rem; padding: 0;
  }}
  .fc3-flip-back:hover {{ color: {_ACCENT}; }}
</style>"""


def build_interactive_card_html(
    *,
    card: dict[str, Any],
    idx: int,
    total: int,
    interval_preview: dict[str, int],
    memory: dict[str, Any],
    initial_flipped: bool,
    session_nonce: int,
) -> str:
    """Self-contained iframe markup for the review card's flip scene.

    ``session_nonce`` namespaces the client-side flip flag in
    ``sessionStorage`` so a stale flip from a previous queue load never
    leaks onto a card that reappears after a filter change / "Начать снова"
    (see the review view's ``flashcards_review_queue_nonce``).
    """
    card_id = int(card.get("id") or 0)
    front_html = escape_multiline(card.get("front"))
    back_html = escape_multiline(card.get("back"))
    counter = f"{idx + 1} / {max(total, idx + 1)}"

    strength_pct = int(memory.get("strength_pct", 0))
    status_label = html.escape(str(memory.get("status_label_ru") or ""))
    status_color = html.escape(str(memory.get("status_color") or _MUTED))
    forecast_ru = html.escape(str(memory.get("forecast_ru") or ""))

    # Full literal `st-key-fc_rate_<q>` class names, derived from the single
    # source of truth (RATING_BUTTONS) rather than string-concatenated in JS
    # at click time — keeps the bridge selectors visible/greppable in the
    # rendered markup.
    rate_class_map_json = json.dumps(
        {q_label: f"st-key-fc_rate_{q_label}" for _label, q_label, _quality, _color in RATING_BUTTONS}
    )

    body = f"""{_STYLE}
<div class="fc3-scene" id="fc3-scene">
  <div class="fc3-card" id="fc3-card">
    <div class="fc3-face fc3-front">
      <div class="fc3-top-row">
        {_deck_badge_html(card)}
        <div class="fc3-counter">{html.escape(counter)}</div>
      </div>
      <div class="fc3-label">Вопрос</div>
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
      <div class="fc3-hint">нажми карточку или Space, чтобы перевернуть</div>
    </div>
    <div class="fc3-face fc3-back">
      <div class="fc3-label">Ответ</div>
      <div class="fc3-text">{back_html}</div>
      <div class="fc3-rate-row">{_rating_chips_html(interval_preview)}</div>
      <button type="button" class="fc3-explain-chip" id="fc3-explain">🤔 Не знаю — объясни</button>
      <button type="button" class="fc3-flip-back" id="fc3-flip-back">↩ к вопросу</button>
    </div>
  </div>
</div>
<script>
(function() {{
  var cardId = {json.dumps(card_id)};
  var queueNonce = {json.dumps(int(session_nonce))};
  var initialFlipped = {json.dumps(bool(initial_flipped))};
  var storageKey = 'fc_flip_' + queueNonce + '_' + cardId;
  var card3d = document.getElementById('fc3-card');
  var scene = document.getElementById('fc3-scene');
  var locked = false;

  function readSessionFlip() {{
    try {{ return window.parent.sessionStorage.getItem(storageKey) === '1'; }}
    catch (e) {{ return false; }}
  }}
  function writeSessionFlip(v) {{
    try {{
      if (v) {{ window.parent.sessionStorage.setItem(storageKey, '1'); }}
      else {{ window.parent.sessionStorage.removeItem(storageKey); }}
    }} catch (e) {{}}
  }}

  var flipped = initialFlipped || readSessionFlip();
  function applyFlipClass() {{
    if (flipped) {{ card3d.classList.add('is-flipped'); }}
    else {{ card3d.classList.remove('is-flipped'); }}
  }}
  applyFlipClass();

  function setFlipped(v) {{
    flipped = v;
    applyFlipClass();
    writeSessionFlip(v);
  }}

  function clickParent(cls) {{
    try {{
      var doc = window.parent.document;
      var el = doc.querySelector('.' + cls + ' button');
      if (el) {{ el.click(); return true; }}
    }} catch (e) {{}}
    return false;
  }}

  var rateClassMap = {rate_class_map_json};

  function rate(q) {{
    if (locked) {{ return; }}
    locked = true;
    writeSessionFlip(false);
    clickParent(rateClassMap[q] || ('st-key-fc_rate_' + q));
  }}

  function explain() {{
    if (locked) {{ return; }}
    locked = true;
    clickParent('st-key-fc_gap_to_tutor');
  }}

  scene.addEventListener('click', function(e) {{
    if (e.target.closest('.fc3-rate-chip') || e.target.closest('#fc3-explain') ||
        e.target.closest('#fc3-flip-back') || e.target.closest('.fc3-details')) {{
      return;
    }}
    setFlipped(!flipped);
  }});

  var rateButtons = document.querySelectorAll('.fc3-rate-chip');
  for (var i = 0; i < rateButtons.length; i++) {{
    (function(btn) {{
      btn.addEventListener('click', function(e) {{
        e.stopPropagation();
        btn.classList.add('fc3-pop');
        rate(btn.getAttribute('data-q'));
      }});
    }})(rateButtons[i]);
  }}
  var explainBtn = document.getElementById('fc3-explain');
  if (explainBtn) {{
    explainBtn.addEventListener('click', function(e) {{ e.stopPropagation(); explain(); }});
  }}
  var flipBackBtn = document.getElementById('fc3-flip-back');
  if (flipBackBtn) {{
    flipBackBtn.addEventListener('click', function(e) {{ e.stopPropagation(); setFlipped(false); }});
  }}

  var ring = document.getElementById('fc3-ring-fill');
  if (ring) {{
    var targetOffset = ring.getAttribute('data-offset');
    window.setTimeout(function() {{ ring.style.strokeDashoffset = targetOffset; }}, 40);
  }}

  // Shrink the card (and ask Streamlit to shrink the iframe itself) to the
  // face's *actual* content height instead of the fixed Python-side
  // estimate — otherwise short cards leave a large empty box below the
  // content. Measured off-DOM (hidden clone) so faces keep their normal
  // `position:absolute` sizing (needed for the flip transform) undisturbed.
  var frontFace = document.querySelector('.fc3-front');
  var backFace = document.querySelector('.fc3-back');

  function measureNaturalHeight(faceEl) {{
    if (!faceEl) {{ return 0; }}
    var clone = faceEl.cloneNode(true);
    clone.removeAttribute('id');
    var idEls = clone.querySelectorAll('[id]');
    for (var i = 0; i < idEls.length; i++) {{ idEls[i].removeAttribute('id'); }}
    clone.style.position = 'absolute';
    clone.style.visibility = 'hidden';
    clone.style.pointerEvents = 'none';
    clone.style.left = '-99999px';
    clone.style.top = '0';
    clone.style.height = 'auto';
    clone.style.maxHeight = 'none';
    clone.style.transform = 'none';
    clone.style.width = card3d.clientWidth + 'px';
    document.body.appendChild(clone);
    var h = clone.scrollHeight;
    document.body.removeChild(clone);
    return h;
  }}

  function sendFrameHeight(px) {{
    try {{
      window.parent.postMessage({{isStreamlitMessage: true, type: 'streamlit:setFrameHeight', height: px}}, '*');
    }} catch (e) {{}}
  }}

  function resizeToContent() {{
    var contentH = Math.max(measureNaturalHeight(frontFace), measureNaturalHeight(backFace));
    contentH = Math.max({_MIN_HEIGHT}, Math.min(contentH, {_MAX_HEIGHT}));
    card3d.style.height = contentH + 'px';
    sendFrameHeight(contentH + 16);
  }}
  resizeToContent();

  var rateMap = {{
    'Digit1': 'again', 'Numpad1': 'again',
    'Digit2': 'hard', 'Numpad2': 'hard',
    'Digit3': 'good', 'Numpad3': 'good',
    'Digit4': 'easy', 'Numpad4': 'easy'
  }};

  function handleKey(e) {{
    var t = e.target || {{}};
    var tag = (t.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || t.isContentEditable) {{ return; }}
    if (e.metaKey || e.ctrlKey || e.altKey) {{ return; }}
    var code = e.code;
    if (!flipped) {{
      if (code === 'Space' || code === 'Enter' || code === 'NumpadEnter') {{
        e.preventDefault(); setFlipped(true);
      }}
      return;
    }}
    if (rateMap[code]) {{ e.preventDefault(); rate(rateMap[code]); return; }}
    if (code === 'Space' || code === 'Enter' || code === 'NumpadEnter') {{
      e.preventDefault(); rate('good'); return;
    }}
    if (code === 'KeyE') {{ e.preventDefault(); explain(); }}
  }}

  // Focus lives in *this* iframe once the learner clicks the card (it's
  // visible/clickable, unlike the old height=0 keyboard iframe), so keydown
  // fires on this document, not window.parent.document — keyboard events
  // don't cross the iframe boundary. Attach to both so shortcuts keep
  // working right after a rerun (focus still in parent) and after a click
  // into the card (focus moved here).
  if (window.__fcCardKeyHandler) {{
    document.removeEventListener('keydown', window.__fcCardKeyHandler);
  }}
  window.__fcCardKeyHandler = handleKey;
  document.addEventListener('keydown', window.__fcCardKeyHandler);

  try {{
    var pwin = window.parent;
    if (pwin && pwin.document) {{
      if (pwin.__fcKeyHandler) {{
        pwin.document.removeEventListener('keydown', pwin.__fcKeyHandler);
        pwin.__fcKeyHandler = null;
      }}
      if (pwin.__fcCardKeyHandler) {{
        pwin.document.removeEventListener('keydown', pwin.__fcCardKeyHandler);
      }}
      pwin.__fcCardKeyHandler = handleKey;
      pwin.document.addEventListener('keydown', pwin.__fcCardKeyHandler);
    }}
  }} catch (e) {{}}
}})();
</script>"""
    return body
