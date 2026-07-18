"""W10 Playwright visual/DOM matrix on pure HTML fixtures (no Streamlit stack).

Covers critical *renderable* surfaces that ship as self-contained HTML or CSS
fragments: flashcard iframe, host chrome (SSR / library / mission tiles via
``ui_theme.css``), and D3 knowledge-graph template.

Opt-out: ``HT_SKIP_W10_VISUAL=1`` (or ``HT_SKIP_KG_3D_VISUAL=1`` for shared CI).
Does not replace a full-app Streamlit e2e harness — that remains open.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app.flashcards_memory_signals import compute_card_memory_signals
from app.ui.flashcards_interactive_card import build_interactive_card_html
from app.ui.knowledge_graph_d3 import build_kg_html
from app.ui.source_address import library_card_html

ROOT = Path(__file__).resolve().parents[1]

VIEWPORTS: tuple[dict[str, int], ...] = (
    {"width": 1366, "height": 768},
    {"width": 1920, "height": 1080},
    {"width": 390, "height": 844},
    {"width": 1440, "height": 900},
)

# Shared evaluate snippet: body horizontal overflow (+ optional zoom factor).
_OVERFLOW_JS = """
(zoom) => {
  if (zoom && zoom !== 1) {
    document.documentElement.style.zoom = String(zoom);
  }
  const de = document.documentElement;
  const body = document.body;
  const sw = Math.max(de.scrollWidth, body ? body.scrollWidth : 0);
  const cw = de.clientWidth;
  return {
    overflowX: sw > cw + 1,
    scrollWidth: sw,
    clientWidth: cw,
    zoom: zoom || 1,
  };
}
"""


def _skip_if_disabled() -> None:
    if os.environ.get("HT_SKIP_W10_VISUAL") == "1":
        pytest.skip("HT_SKIP_W10_VISUAL=1")
    if os.environ.get("HT_SKIP_KG_3D_VISUAL") == "1":
        pytest.skip("HT_SKIP_KG_3D_VISUAL=1 (shared visual opt-out)")


def _playwright():
    return pytest.importorskip("playwright.sync_api")


def _theme_css_offline() -> str:
    """Host CSS without external webfont @import (local-first gate)."""
    css = (ROOT / "app" / "ui_theme.css").read_text(encoding="utf-8")
    return re.sub(r"@import\s+url\([^)]+\);\s*", "", css, count=1)


def _wrap_document(*, title: str, body: str, head_extra: str = "") -> str:
    return (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{title}</title>{head_extra}</head>"
        f"<body>{body}</body></html>"
    )


def _flashcard_document() -> str:
    card = {
        "id": 7,
        "front": "Что такое hybrid retrieval?",
        "back": "Сочетание BM25 и vector search с последующим rerank.",
        "deck_name": "RAG",
        "deck_source_type": "course",
        "tags": "rag, retrieval",
        "easiness": 2.5,
        "interval_days": 3,
        "repetitions": 2,
    }
    html_frag = build_interactive_card_html(
        card=card,
        idx=0,
        total=3,
        interval_preview={"again": 1, "hard": 2, "good": 3, "easy": 5},
        memory=compute_card_memory_signals(card),
        initial_flipped=False,
        session_nonce=99,
    )
    # Fragment already includes <style>; wrap as standalone document.
    return _wrap_document(
        title="W10 flashcard",
        body=html_frag,
        head_extra="<style>html,body{margin:0;padding:8px;background:#f8f2e7;}</style>",
    )


def _host_chrome_document() -> str:
    css = _theme_css_offline()
    cards = "".join(
        library_card_html(
            title=title,
            address=addr,
            status=status,
            kind="course",
            quant=quant,
        )
        for title, addr, status, quant in (
            (
                "ИИ-агенты: цикл ответа",
                "ИИ-агенты · Урок 1 · RAG · 03:20",
                "активный курс",
                "12 разделов",
            ),
            (
                "Физика: импульс",
                "Физика · Урок 3 · Импульс",
                "нужен повтор",
                "4 due",
            ),
            (
                "Длинный заголовок карточки библиотеки для проверки переноса",
                "Курс с очень длинным именем · Урок 12 · Раздел про attention и multi-head",
                "без статуса",
                None,
            ),
        )
    )
    body = f"""
    <main class="w10-host" style="max-width:1200px;margin:0 auto;padding:12px;">
      <section class="ssr-banner" data-testid="w10-ssr">
        <div class="ssr-hero">
          <div class="ssr-kicker">СЛЕДУЮЩИЙ ШАГ</div>
          <h2>Повторить due-карточки</h2>
          <p class="ssr-why-inline">
            <span class="ssr-why-label">Почему:</span>
            4 карточки due и слабый retention по RAG.
          </p>
        </div>
        <details class="ssr-details">
          <summary class="ssr-details-toggle">Почему это подходит</summary>
          <div class="ssr-sections">
            <div class="ssr-section">Сигналы: due queue, weak concepts.</div>
          </div>
        </details>
      </section>

      <div class="home-dash-card" data-testid="w10-home-dash">
        <div class="home-dash-head home-dash-head-continue"><h3>Продолжить</h3></div>
        <div class="home-dash-body"><p>Вернуться к Living Konspekt · раздел Hybrid retrieval.</p></div>
      </div>

      <div class="hero-grid hero-grid--4-3" data-testid="w10-mission-grid"
           style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;">
        <div class="mode-card mission-tile"><div class="mode-icon">📚</div>
          <div class="mode-title">Библиотека</div>
          <div class="mode-desc">Каталог курсов и маршруты</div></div>
        <div class="mode-card mission-tile smart-recommended"><div class="mode-icon">🃏</div>
          <div class="mode-title">Карточки</div>
          <div class="mode-desc">Повтор due-очереди</div></div>
        <div class="mode-card mission-tile"><div class="mode-icon">🧭</div>
          <div class="mode-title">Мнемополис</div>
          <div class="mode-desc">Пространственный маршрут</div></div>
      </div>

      <div data-testid="stHorizontalBlock" style="display:flex;flex-wrap:wrap;gap:12px;">
        <div data-testid="stColumn">{cards}</div>
      </div>

      <div class="src-addr" role="text" aria-label="Адрес источника: Tutor · hybrid">
        <span class="src-addr-pin" aria-hidden="true">📍</span>
        <span class="src-addr-text">Tutor · hybrid retrieval · next action</span>
      </div>
    </main>
    """
    return _wrap_document(
        title="W10 host chrome",
        body=body,
        head_extra=f"<style>{css}</style>",
    )


def _d3_document() -> str:
    return build_kg_html(
        {
            "nodes": [
                {
                    "id": "rag",
                    "label": "RAG",
                    "level": "beginner",
                    "frontier": True,
                    "unlocks": ["bm25"],
                    "mastery": 42,
                },
                {
                    "id": "bm25",
                    "label": "BM25",
                    "level": "intermediate",
                    "frontier": False,
                    "unlocks": [],
                    "mastery": 18,
                },
            ],
            "edges": [{"source": "rag", "target": "bm25", "relation_type": "prereq"}],
            "levels": {"rag": "beginner", "bm25": "intermediate"},
            "stats": {"total": 2, "frontier": 1},
            "health": {},
            "cluster_labels": {},
            "decay_vector": {"rag": 0.4},
            "mastery_history": [{"date": "2026-07-18", "mastery": {"rag": 42}}],
            "compiler_health": None,
            "day_route": ["rag", "bm25"],
        }
    )


@pytest.fixture(scope="module")
def browser_factory():
    _skip_if_disabled()
    sync_api = _playwright()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


def _open(browser, html: str, *, viewport: dict[str, int], reduced_motion: bool = False):
    context = browser.new_context(
        viewport=viewport,
        reduced_motion="reduce" if reduced_motion else "no-preference",
    )
    page = context.new_page()
    page.set_content(html, wait_until="load")
    return context, page


# ── Flashcard matrix ─────────────────────────────────────────────────────────


def test_w10_flashcard_viewport_matrix_no_overflow_and_touch_targets(browser_factory, tmp_path):
    html = _flashcard_document()
    path = tmp_path / "fc.html"
    path.write_text(html, encoding="utf-8")

    for vp in VIEWPORTS:
        context, page = _open(browser_factory, html, viewport=vp)
        try:
            page.goto(path.as_uri())
            page.wait_for_timeout(120)
            overflow = page.evaluate(_OVERFLOW_JS, 1)
            assert overflow["overflowX"] is False, (vp, overflow)

            metrics = page.evaluate(
                """
                () => {
                  const flip = document.querySelector('#fc3-flip-surface');
                  const fr = flip ? flip.getBoundingClientRect() : null;
                  // Flip to show rating chips
                  if (flip) flip.click();
                  const chips = [...document.querySelectorAll('.fc3-rate-chip')].map(el => {
                    const r = el.getBoundingClientRect();
                    return {h: r.height, w: r.width};
                  });
                  return {
                    flipH: fr ? fr.height : 0,
                    flipW: fr ? fr.width : 0,
                    chips,
                    hasLive: !!document.querySelector('#fc3-flip-status[aria-live]'),
                  };
                }
                """
            )
            assert metrics["hasLive"] is True, vp
            assert metrics["flipH"] >= 40, (vp, metrics)
            # After flip, rating chips must meet touch floor on all viewports.
            assert len(metrics["chips"]) >= 4, (vp, metrics)
            for chip in metrics["chips"]:
                assert chip["h"] >= 40, (vp, chip)
                # Mobile: prefer 44px when layout allows (W4 contract uses 44).
                if vp["width"] >= 390:
                    assert chip["h"] >= 44, (vp, chip)
        finally:
            context.close()


def test_w10_flashcard_reduced_motion_disables_3d_flip_transform(browser_factory, tmp_path):
    html = _flashcard_document()
    path = tmp_path / "fc_rm.html"
    path.write_text(html, encoding="utf-8")
    context, page = _open(
        browser_factory, html, viewport={"width": 1366, "height": 768}, reduced_motion=True
    )
    try:
        page.goto(path.as_uri())
        page.wait_for_timeout(80)
        page.click("#fc3-flip-surface")
        page.wait_for_timeout(80)
        result = page.evaluate(
            """
            () => {
              const card = document.querySelector('#fc3-card');
              const style = getComputedStyle(card);
              const transform = style.transform || 'none';
              // Under reduced-motion CSS, 3D rotateY path is disabled.
              const hasRotateY = /matrix3d|rotateY/i.test(transform) && transform !== 'none';
              const media = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
              return { transform, hasRotateY, media, side: card.getAttribute('data-side') };
            }
            """
        )
        assert result["media"] is True
        assert result["hasRotateY"] is False, result
    finally:
        context.close()


def test_w10_flashcard_keyboard_flip_smoke(browser_factory, tmp_path):
    html = _flashcard_document()
    path = tmp_path / "fc_kb.html"
    path.write_text(html, encoding="utf-8")
    context, page = _open(browser_factory, html, viewport={"width": 1366, "height": 768})
    try:
        page.goto(path.as_uri())
        page.focus("#fc3-flip-surface")
        page.keyboard.press("Space")
        page.wait_for_timeout(80)
        side = page.evaluate(
            "() => document.querySelector('#fc3-card')?.getAttribute('data-side')"
        )
        # Card should expose back after keyboard flip (or aria-pressed true).
        pressed = page.evaluate(
            "() => document.querySelector('#fc3-flip-surface')?.getAttribute('aria-pressed')"
        )
        assert side == "back" or pressed == "true", (side, pressed)
    finally:
        context.close()


# ── Host chrome (SSR / library / mission) ────────────────────────────────────


def test_w10_host_chrome_viewport_matrix_overflow_and_ssr_contrast(browser_factory, tmp_path):
    html = _host_chrome_document()
    path = tmp_path / "host.html"
    path.write_text(html, encoding="utf-8")

    for vp in VIEWPORTS:
        context, page = _open(browser_factory, html, viewport=vp)
        try:
            page.goto(path.as_uri())
            page.wait_for_timeout(100)
            overflow = page.evaluate(_OVERFLOW_JS, 1)
            assert overflow["overflowX"] is False, (vp, overflow)

            metrics = page.evaluate(
                """
                () => {
                  const kicker = document.querySelector('.ssr-kicker');
                  const toggle = document.querySelector('.ssr-details-toggle');
                  const lib = document.querySelector('.lib-card');
                  const title = document.querySelector('.lib-card-title');
                  function sample(el) {
                    if (!el) return null;
                    const cs = getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return {
                      color: cs.color,
                      fontSize: parseFloat(cs.fontSize) || 0,
                      h: r.height,
                      w: r.width,
                    };
                  }
                  return {
                    kicker: sample(kicker),
                    toggle: sample(toggle),
                    lib: sample(lib),
                    title: sample(title),
                    libCount: document.querySelectorAll('.lib-card').length,
                  };
                }
                """
            )
            assert metrics["libCount"] >= 3, (vp, metrics)
            assert metrics["kicker"]["fontSize"] >= 12, (vp, metrics["kicker"])
            assert metrics["toggle"]["fontSize"] >= 12, (vp, metrics["toggle"])
            # Title readable
            assert metrics["title"]["fontSize"] >= 12, (vp, metrics["title"])

            # Contrast sampling via canvas (browser-computed RGB).
            contrast = page.evaluate(
                """
                () => {
                  function parseRgb(c) {
                    const m = c.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/i);
                    if (!m) return null;
                    return [Number(m[1]), Number(m[2]), Number(m[3])];
                  }
                  function lin(c) {
                    c = c / 255;
                    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
                  }
                  function lum(rgb) {
                    const [r,g,b] = rgb.map(lin);
                    return 0.2126*r + 0.7152*g + 0.0722*b;
                  }
                  function ratio(fg, bg) {
                    const L1 = lum(fg), L2 = lum(bg);
                    const lighter = Math.max(L1, L2), darker = Math.min(L1, L2);
                    return (lighter + 0.05) / (darker + 0.05);
                  }
                  function effectiveBg(el) {
                    let n = el;
                    while (n) {
                      const bg = getComputedStyle(n).backgroundColor;
                      const rgb = parseRgb(bg);
                      if (rgb && (rgb[0]+rgb[1]+rgb[2] > 0 || bg.includes('255'))) {
                        // allow near-white / opaque
                        if (!bg.includes('0)') || bg.startsWith('rgb(')) return rgb;
                      }
                      // solid enough
                      if (rgb && getComputedStyle(n).backgroundImage === 'none') {
                        const aMatch = bg.match(/rgba\\(\\d+,\\s*\\d+,\\s*\\d+,\\s*([0-9.]+)/);
                        if (!aMatch || Number(aMatch[1]) >= 0.9) return rgb;
                      }
                      n = n.parentElement;
                    }
                    return [235, 245, 255]; // sky fallback from SSR gradient stop
                  }
                  const kicker = document.querySelector('.ssr-kicker');
                  const fg = parseRgb(getComputedStyle(kicker).color);
                  const bg = effectiveBg(kicker);
                  return { ratio: ratio(fg, bg), fg, bg };
                }
                """
            )
            assert contrast["ratio"] >= 4.5, (vp, contrast)
        finally:
            context.close()


def test_w10_host_chrome_200pct_zoom_no_horizontal_overflow(browser_factory, tmp_path):
    html = _host_chrome_document()
    path = tmp_path / "host_zoom.html"
    path.write_text(html, encoding="utf-8")
    # 200% zoom on mid desktop — classic reflow stress.
    context, page = _open(browser_factory, html, viewport={"width": 1366, "height": 768})
    try:
        page.goto(path.as_uri())
        page.wait_for_timeout(80)
        overflow = page.evaluate(_OVERFLOW_JS, 2)
        assert overflow["overflowX"] is False, overflow
        # Controls still present and at least 40px tall after zoom layout.
        sizes = page.evaluate(
            """
            () => {
              const tiles = [...document.querySelectorAll('.mode-card')].map(el => {
                const r = el.getBoundingClientRect();
                return {h: r.height, w: r.width};
              });
              return { tiles, count: tiles.length };
            }
            """
        )
        assert sizes["count"] >= 3
        for t in sizes["tiles"]:
            assert t["h"] >= 40, t
    finally:
        context.close()


def test_w10_host_reduced_motion_kills_card_hover_transform(browser_factory, tmp_path):
    html = _host_chrome_document()
    path = tmp_path / "host_rm.html"
    path.write_text(html, encoding="utf-8")
    context, page = _open(
        browser_factory, html, viewport={"width": 1366, "height": 768}, reduced_motion=True
    )
    try:
        page.goto(path.as_uri())
        page.hover(".home-dash-card")
        page.wait_for_timeout(50)
        transform = page.evaluate(
            """
            () => {
              const el = document.querySelector('.home-dash-card');
              return getComputedStyle(el).transform;
            }
            """
        )
        # none or matrix(1,0,0,1,0,0) — no translateY lift
        assert transform in ("none", "matrix(1, 0, 0, 1, 0, 0)"), transform
    finally:
        context.close()


# ── D3 template reduced-motion / overflow ────────────────────────────────────


def test_w10_d3_template_reduced_motion_and_viewport_overflow(browser_factory, tmp_path):
    html = _d3_document()
    assert "__NODES__" not in html
    assert "__D3_TAG__" not in html
    assert "const prefersReducedMotion" in html
    assert "frontier-halo" in html
    path = tmp_path / "d3.html"
    path.write_text(html, encoding="utf-8")

    for vp in VIEWPORTS[:3]:  # core matrix
        context, page = _open(
            browser_factory, html, viewport=vp, reduced_motion=True
        )
        try:
            page.goto(path.as_uri())
            page.wait_for_timeout(100)
            overflow = page.evaluate(_OVERFLOW_JS, 1)
            # Template may set body overflow hidden; still no scrollWidth overflow.
            assert overflow["overflowX"] is False, (vp, overflow)
            anim = page.evaluate(
                """
                () => {
                  const el = document.querySelector('.frontier-halo');
                  if (!el) return {ok: false, reason: 'missing'};
                  const cs = getComputedStyle(el);
                  return {
                    ok: true,
                    animationName: cs.animationName,
                    animationDuration: cs.animationDuration,
                    media: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
                  };
                }
                """
            )
            assert anim["ok"] is True, anim
            assert anim["media"] is True
            # animation:none → name none; or near-zero duration from host patterns
            name = (anim["animationName"] or "").lower()
            assert name in ("none", "") or anim["animationDuration"] in (
                "0s",
                "0.001s",
                "0.01ms",
                "0s, 0s",
            ), anim
        finally:
            context.close()
