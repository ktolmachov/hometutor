"""Keyboard shortcuts for the flashcard review loop.

Streamlit renders the rating buttons as real DOM ``<button>`` elements wrapped in
a ``st-key-<key>`` container (the stable keys ``fc_flip``, ``fc_rate_again`` … set
in the review view). A ``components.html`` iframe is same-origin with the host
page, so a tiny script in it can attach a ``keydown`` listener to
``window.parent.document`` and ``.click()`` the matching button.

Shortcuts (matched by physical ``KeyboardEvent.code`` so they work on any layout,
including ЙЦУКЕН):

* not flipped — ``Space`` / ``Enter`` → reveal the answer;
* flipped — ``1``/``2``/``3``/``4`` → Снова / Трудно / Хорошо / Легко,
  ``Space``/``Enter`` → Хорошо, ``E`` → «Не знаю — объясни».

The handler is stored on ``window.parent.__fcKeyHandler`` and removed before each
re-attach, so Streamlit reruns don't stack duplicate listeners.
"""

from __future__ import annotations

import json

# Physical key code → action button's st-key class (only meaningful when flipped).
_CODE_TO_RATE_CLASS: dict[str, str] = {
    "Digit1": "st-key-fc_rate_again",
    "Numpad1": "st-key-fc_rate_again",
    "Digit2": "st-key-fc_rate_hard",
    "Numpad2": "st-key-fc_rate_hard",
    "Digit3": "st-key-fc_rate_good",
    "Numpad3": "st-key-fc_rate_good",
    "Digit4": "st-key-fc_rate_easy",
    "Numpad4": "st-key-fc_rate_easy",
}


def build_review_keyboard_js(flipped: bool) -> str:
    """Return the ``<script>`` markup wiring review keyboard shortcuts."""
    flipped_js = "true" if flipped else "false"
    rate_map_js = json.dumps(_CODE_TO_RATE_CLASS)
    return f"""<script>
(function() {{
  var win = window.parent;
  if (!win || !win.document) {{ return; }}
  var doc = win.document;
  if (win.__fcKeyHandler) {{ doc.removeEventListener('keydown', win.__fcKeyHandler); }}
  var flipped = {flipped_js};
  var rateMap = {rate_map_js};
  function click(cls) {{
    var el = doc.querySelector('.' + cls + ' button');
    if (el) {{ el.click(); return true; }}
    return false;
  }}
  win.__fcKeyHandler = function(e) {{
    var t = e.target || {{}};
    var tag = (t.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || t.isContentEditable) {{ return; }}
    if (e.metaKey || e.ctrlKey || e.altKey) {{ return; }}
    var code = e.code;
    if (!flipped) {{
      if (code === 'Space' || code === 'Enter' || code === 'NumpadEnter') {{
        e.preventDefault(); click('st-key-fc_flip');
      }}
      return;
    }}
    if (rateMap[code]) {{ e.preventDefault(); click(rateMap[code]); return; }}
    if (code === 'Space' || code === 'Enter' || code === 'NumpadEnter') {{
      e.preventDefault(); click('st-key-fc_rate_good'); return;
    }}
    if (code === 'KeyE') {{ e.preventDefault(); click('st-key-fc_gap_to_tutor'); }}
  }};
  doc.addEventListener('keydown', win.__fcKeyHandler);
}})();
</script>"""
