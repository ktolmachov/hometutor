"""Client-side JS for interactive flashcard iframe (W4)."""

from __future__ import annotations

import json


def build_interactive_card_script(
    *,
    card_id: int,
    session_nonce: int,
    initial_flipped: bool,
    rate_class_map_json: str,
    min_height: int,
    max_height: int,
) -> str:
    """Return inner JS for the flip card script tag."""
    return f"""(function() {{
  var cardId = {json.dumps(card_id)};
  var queueNonce = {json.dumps(int(session_nonce))};
  var initialFlipped = {json.dumps(bool(initial_flipped))};
  var storageKey = 'fc_flip_' + queueNonce + '_' + cardId;
  var card3d = document.getElementById('fc3-card');
  var scene = document.getElementById('fc3-scene');
  var frontFace = document.getElementById('fc3-front') || document.querySelector('.fc3-front');
  var backFace = document.getElementById('fc3-back') || document.querySelector('.fc3-back');
  var flipSurface = document.getElementById('fc3-flip-surface');
  var flipStatus = document.getElementById('fc3-flip-status');
  var locked = false;
  var MIN_H = {min_height};
  var MAX_H = {max_height};

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

  function announceSide(v) {{
    if (!flipStatus) {{ return; }}
    flipStatus.textContent = v
      ? 'Ответ. Оцените, насколько хорошо вспомнили.'
      : 'Вопрос. Покажите ответ, когда будете готовы.';
  }}

  function applyFlipClass() {{
    if (flipped) {{ card3d.classList.add('is-flipped'); }}
    else {{ card3d.classList.remove('is-flipped'); }}
    card3d.setAttribute('data-side', flipped ? 'back' : 'front');
    // The face turned away from the viewer is still in normal document flow
    // (only `backface-visibility` hides it), so its buttons/summary stay
    // Tab-reachable — a keyboard user would land on invisible rating chips
    // while the question face is showing. `inert` removes the hidden face
    // from both focus and hit-testing; unsupported browsers just keep the
    // pre-existing (imperfect) tab order, so this is a safe no-op fallback.
    if (frontFace) {{ frontFace.inert = flipped; }}
    if (backFace) {{ backFace.inert = !flipped; }}
    if (flipSurface) {{
      flipSurface.setAttribute('aria-pressed', flipped ? 'true' : 'false');
      flipSurface.setAttribute(
        'aria-label',
        flipped
          ? 'Ответ показан. Вернитесь к вопросу кнопкой ниже.'
          : 'Показать ответ. Сейчас: вопрос.'
      );
    }}
    var flipBackBtn = document.getElementById('fc3-flip-back');
    if (flipBackBtn) {{
      flipBackBtn.setAttribute('aria-pressed', flipped ? 'true' : 'false');
    }}
  }}
  applyFlipClass();
  announceSide(flipped);

  function setFlipped(v) {{
    if (flipped === v) {{ return; }}
    flipped = v;
    applyFlipClass();
    writeSessionFlip(v);
    announceSide(v);
    resizeToContent();
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

  // Semantic flip surface (front→back). Scene click is no longer the only path.
  if (flipSurface) {{
    flipSurface.addEventListener('click', function(e) {{
      e.stopPropagation();
      setFlipped(true);
    }});
  }}

  // Convenience: click non-interactive front area still flips (not rating/details).
  scene.addEventListener('click', function(e) {{
    if (e.target.closest('.fc3-rate-chip') || e.target.closest('#fc3-explain') ||
        e.target.closest('#fc3-flip-back') || e.target.closest('#fc3-flip-surface') ||
        e.target.closest('.fc3-details')) {{
      return;
    }}
    if (!flipped) {{ setFlipped(true); }}
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

  // Inner card height from content; outer iframe via frameElement when same-origin
  // (components.html srcdoc). postMessage is best-effort for declare_component hosts.
  // Host call site keeps scrolling=True as degraded safety if resize fails (W4).

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
    clone.style.opacity = '1';
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

  function applyOuterHeight(px) {{
    var h = Math.max(MIN_H, Math.min(px, MAX_H));
    try {{
      var frame = window.frameElement;
      if (frame) {{
        frame.style.height = h + 'px';
        frame.setAttribute('data-fc3-resized', '1');
        frame.setAttribute('data-fc3-height', String(h));
      }}
    }} catch (e) {{}}
    sendFrameHeight(h);
  }}

  function resizeToContent() {{
    var contentH = Math.max(measureNaturalHeight(frontFace), measureNaturalHeight(backFace));
    contentH = Math.max(MIN_H, Math.min(contentH, MAX_H));
    card3d.style.height = contentH + 'px';
    applyOuterHeight(contentH + 16);
  }}
  resizeToContent();

  // ResizeObserver confirms height after layout / font load (W4).
  if (typeof ResizeObserver !== 'undefined') {{
    var ro = new ResizeObserver(function() {{ resizeToContent(); }});
    if (frontFace) {{ ro.observe(frontFace); }}
    if (backFace) {{ ro.observe(backFace); }}
    scene.setAttribute('data-fc3-resize-observer', '1');
  }} else {{
    scene.setAttribute('data-fc3-resize-observer', '0');
  }}
  window.addEventListener('resize', function() {{ resizeToContent(); }});

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
    // This listener is also attached to `window.parent.document` (see below),
    // so `e.target` may be a native Streamlit button/expander/link, not just
    // something inside this iframe. Space/Enter there must reach the
    // element's own activation (or toggle a <summary> disclosure) instead of
    // being hijacked into a card flip/rating.
    if (typeof t.closest === 'function' &&
        t.closest('button, summary, a, select, [role="button"], [contenteditable="true"]')) {{
      return;
    }}
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
"""
