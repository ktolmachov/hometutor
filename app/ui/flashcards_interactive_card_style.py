"""CSS template for interactive flashcard iframe (W4)."""

from __future__ import annotations

STYLE_TEMPLATE = """<style>
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0; padding: 0; background: transparent; font-family: {MONO};
    height: 100%; width: 100%;
  }}
  .fc3-sr-only {{
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
    overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
  }}
  .fc3-scene {{
    width: 100%; height: 100%; perspective: 1600px;
    padding: 6px;
  }}
  .fc3-card {{
    position: relative; width: 100%; height: 100%;
    transition: transform 0.5s cubic-bezier(0.2, 0.8, 0.2, 1);
    transform-style: preserve-3d;
  }}
  .fc3-card.is-flipped {{ transform: rotateY(180deg); }}
  .fc3-face {{
    position: absolute; inset: 0; backface-visibility: hidden;
    border-radius: 20px; border: 1px solid {INK_SOFT};
    box-shadow: 0 18px 40px {INK_SOFT};
    padding: 1.6rem 1.6rem 1.2rem; display: flex; flex-direction: column;
    overflow-y: auto; color: {INK};
  }}
  .fc3-face.fc3-front {{
    background: {FRONT_BG};
  }}
  .fc3-face.fc3-back {{
    background: {BACK_BG};
    border-left: 4px solid {ACCENT};
    transform: rotateY(180deg);
  }}
  .fc3-top-row {{ display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }}
  .fc3-deck-badge {{
    font-size: 12px; color: {MUTED}; text-transform: uppercase; letter-spacing: 0.05em;
  }}
  .fc3-counter {{ font-size: 12px; color: {MUTED}; }}
  .fc3-label {{
    font-size: 12px; color: {MUTED}; text-transform: uppercase; letter-spacing: 0.08em;
    margin: 0.9rem 0 0.6rem; font-weight: 600;
  }}
  .fc3-text {{ font-size: 1.15rem; font-weight: 600; line-height: 1.55; flex: 0 0 auto; }}
  .fc3-tags {{ margin-top: 0.9rem; }}
  .fc3-tag-chips {{ display: flex; flex-wrap: wrap; gap: 0.35rem; }}
  .fc3-tag-chip {{
    font-size: 12px; color: {ACCENT}; background: transparent;
    border: 1px solid {ACCENT}; border-radius: 999px; padding: 2px 9px;
  }}
  .fc3-source {{ font-size: 12px; color: {MUTED}; margin-top: 0.4rem; }}
  .fc3-memory-row {{ display: flex; align-items: center; gap: 0.8rem; margin-top: 1rem; }}
  .fc3-ring {{ position: relative; width: 64px; height: 64px; flex: 0 0 auto; }}
  .fc3-ring svg {{ transform: rotate(-90deg); }}
  .fc3-ring-track {{ fill: none; stroke: {INK}; stroke-width: 6; opacity: 0.12; }}
  .fc3-ring-fill {{
    fill: none; stroke: {ACCENT}; stroke-width: 6; stroke-linecap: round;
    transition: stroke-dashoffset 0.9s ease;
  }}
  .fc3-ring-label {{
    position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
    font-size: 12px; font-weight: 700; transform: none;
  }}
  .fc3-memory-meta {{ flex: 1 1 auto; min-width: 0; }}
  .fc3-status-chip {{
    display: inline-block; font-size: 12px; font-weight: 700; padding: 2px 9px;
    border-radius: 999px; color: #fff;
  }}
  .fc3-forecast {{ font-size: 12px; color: {MUTED}; margin-top: 0.3rem; }}
  .fc3-details {{ margin-top: 0.9rem; font-size: 12px; color: {MUTED}; }}
  .fc3-details summary {{ cursor: pointer; color: {ACCENT}; font-weight: 600; min-height: 44px;
    display: flex; align-items: center; }}
  .fc3-details-grid {{
    display: grid; grid-template-columns: 1fr 1fr; gap: 0.4rem 0.8rem; margin-top: 0.5rem;
  }}
  .fc3-details-grid > div {{ display: flex; flex-direction: column; }}
  .fc3-details-k {{ font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }}
  .fc3-details-v {{ font-size: 0.85rem; color: {INK}; font-weight: 600; }}
  .fc3-hint {{ margin-top: 0.4rem; padding-top: 0.4rem; font-size: 12px; color: {MUTED}; text-align: center; }}
  /* Semantic flip surface — front→back (W4); not a wrapper around rating buttons. */
  .fc3-flip-surface {{
    margin-top: auto; width: 100%; min-height: 44px; padding: 0.65rem 0.75rem;
    border-radius: 12px; border: 1px solid {ACCENT}; cursor: pointer;
    background: transparent; color: {ACCENT}; font-family: {MONO};
    font-size: 0.9rem; font-weight: 700; text-align: center;
  }}
  .fc3-flip-surface:hover {{ background: {INK_SOFT}; }}
  .fc3-flip-surface:focus {{ outline: none; }}
  .fc3-flip-surface:focus-visible {{
    outline: 2px solid {ACCENT}; outline-offset: 2px;
    box-shadow: 0 0 0 4px {INK_SOFT};
  }}
  .fc3-rate-row {{ display: flex; gap: 0.5rem; margin-top: 0.9rem; flex-wrap: wrap; }}
  .fc3-rate-chip {{
    flex: 1 1 0; min-width: 90px; min-height: 44px;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 0.12rem; padding: 0.45rem 0.35rem; border-radius: 14px; border: none; cursor: pointer;
    background: var(--fc3-rate-color, {ACCENT}); color: #fff; font-family: {MONO};
    transition: transform 0.12s ease, box-shadow 0.12s ease;
  }}
  .fc3-rate-chip:hover {{ transform: translateY(-2px); box-shadow: 0 8px 18px {INK}; }}
  .fc3-rate-chip:active {{ transform: scale(0.94); }}
  .fc3-rate-chip:focus {{ outline: none; }}
  .fc3-rate-chip:focus-visible {{
    outline: 2px solid #fff; outline-offset: 2px;
    box-shadow: 0 0 0 4px {INK};
  }}
  .fc3-rate-chip.fc3-pop {{ animation: fc3-pop 0.22s ease; }}
  @keyframes fc3-pop {{ 0% {{ transform: scale(1); }} 50% {{ transform: scale(0.88); }} 100% {{ transform: scale(1); }} }}
  /* Mnemonic meaning primary; grade label secondary; interval tertiary (W4). */
  .fc3-rate-meaning {{ font-size: 0.85rem; font-weight: 700; line-height: 1.2; }}
  .fc3-rate-label {{ font-size: 12px; font-weight: 600; opacity: 0.92; }}
  .fc3-rate-eta {{ font-size: 12px; font-weight: 500; opacity: 0.78; }}
  .fc3-explain-chip {{
    margin-top: 0.6rem; width: 100%; min-height: 44px; padding: 0.5rem; border-radius: 12px;
    border: 1px solid {INK}; background: transparent; color: {MUTED}; font-family: {MONO};
    font-size: 0.85rem; cursor: pointer;
  }}
  .fc3-explain-chip:hover {{ color: {ACCENT}; border-color: {ACCENT}; }}
  .fc3-explain-chip:focus {{ outline: none; }}
  .fc3-explain-chip:focus-visible {{
    outline: 2px solid {ACCENT}; outline-offset: 2px;
  }}
  .fc3-flip-back {{
    margin-top: 0.5rem; align-self: flex-start; background: none; border: none; cursor: pointer;
    color: {MUTED}; font-family: {MONO}; font-size: 12px; min-height: 44px; padding: 0.35rem 0.25rem;
  }}
  .fc3-flip-back:hover {{ color: {ACCENT}; }}
  .fc3-flip-back:focus {{ outline: none; }}
  .fc3-flip-back:focus-visible {{
    outline: 2px solid {ACCENT}; outline-offset: 2px; border-radius: 4px;
  }}
  /* Reduced-motion: content swap/fade instead of 3D rotation (W4). */
  @media (prefers-reduced-motion: reduce) {{
    .fc3-scene {{ perspective: none; }}
    .fc3-card {{
      transition: opacity 0.15s ease;
      transform-style: flat;
      transform: none !important;
    }}
    .fc3-card.is-flipped {{ transform: none !important; }}
    .fc3-face {{
      backface-visibility: visible;
      transition: opacity 0.15s ease;
    }}
    .fc3-face.fc3-back {{ transform: none; }}
    .fc3-card:not(.is-flipped) .fc3-back {{
      opacity: 0; pointer-events: none; visibility: hidden;
    }}
    .fc3-card.is-flipped .fc3-front {{
      opacity: 0; pointer-events: none; visibility: hidden;
    }}
    .fc3-card.is-flipped .fc3-back {{
      opacity: 1; pointer-events: auto; visibility: visible;
    }}
    .fc3-ring-fill {{ transition: none; }}
    .fc3-rate-chip {{ transition: none; }}
    .fc3-rate-chip:hover {{ transform: none; box-shadow: none; }}
    .fc3-rate-chip:active {{ transform: none; }}
    .fc3-rate-chip.fc3-pop {{ animation: none; }}
  }}
</style>"""

