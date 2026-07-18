"""Shared fixtures for live Streamlit e2e (W10.F1).

External-stack mode: the harness connects to an already-running local stack.
Set ``HT_E2E_STREAMLIT_URL`` to override the default ``http://127.0.0.1:8501``.
If the stack is unreachable the suite is skipped (not failed) so the bundle
remains green in environments without a live stack (CI can opt-in by starting
``scripts/run_local_stack.ps1`` first).

Opt-out: ``HT_SKIP_E2E_LIVE=1``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = ROOT / "tests" / "e2e" / "_artifacts"
DEFAULT_STREAMLIT_URL = "http://127.0.0.1:8501"
_E2E_HEALTH_TIMEOUT = 3.0


def _skip_if_disabled() -> None:
    if os.environ.get("HT_SKIP_E2E_LIVE") == "1":
        pytest.skip("HT_SKIP_E2E_LIVE=1")


def _streamlit_url() -> str:
    return os.environ.get("HT_E2E_STREAMLIT_URL", DEFAULT_STREAMLIT_URL).rstrip("/")


def _stack_is_live(url: str) -> tuple[bool, str]:
    """Probe Streamlit ``/_stcore/health`` and root; return (ok, reason)."""
    try:
        import requests  # local import: requests is a runtime dep
    except Exception as exc:  # noqa: BLE001 - guard for stripped envs
        return False, f"requests import failed: {exc}"
    try:
        h = requests.get(f"{url}/_stcore/health", timeout=_E2E_HEALTH_TIMEOUT)
        if h.status_code != 200 or h.text.strip() != "ok":
            return False, f"/_stcore/health → {h.status_code} {h.text[:40]!r}"
    except Exception as exc:  # noqa: BLE001 - any transport failure → skip
        return False, f"/_stcore/health unreachable: {exc}"
    try:
        r = requests.get(url, timeout=_E2E_HEALTH_TIMEOUT)
        if r.status_code != 200:
            return False, f"root → {r.status_code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"root unreachable: {exc}"
    return True, "ok"


@pytest.fixture(scope="session")
def e2e_streamlit_url() -> str:
    """Resolved + health-checked Streamlit base URL; skips the suite if down."""
    _skip_if_disabled()
    url = _streamlit_url()
    ok, reason = _stack_is_live(url)
    if not ok:
        pytest.skip(
            f"live Streamlit stack not reachable at {url} ({reason}). "
            "Start scripts/run_local_stack.ps1 or set HT_E2E_STREAMLIT_URL, "
            "or HT_SKIP_E2E_LIVE=1 to skip."
        )
    return url


@pytest.fixture(scope="session")
def e2e_artifacts_dir() -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS_DIR


@pytest.fixture(scope="session")
def e2e_browser():
    """Session-scoped Chromium browser (Playwright); importorskip if absent."""
    _skip_if_disabled()
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


def open_streamlit_page(
    browser,
    url: str,
    *,
    viewport: dict[str, int],
    wait_ms: int = 5000,
) -> tuple[Any, Any]:
    """Open a fresh context/page at ``url``; returns (context, page).

    Collects pageerrors on the page for later assertion. Caller closes context.
    """
    import time

    context = browser.new_context(viewport=viewport)
    page = context.new_page()
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    setattr(page, "_e2e_errors", page_errors)  # type: ignore[attr-defined]
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    # Streamlit renders via websocket after the initial shell; give it room.
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            page.wait_for_selector('section[data-testid="stMain"]', timeout=1000)
            break
        except Exception:  # noqa: BLE001 - retry until deadline
            page.wait_for_timeout(300)
    page.wait_for_timeout(wait_ms)
    return context, page


# JS snippet reused across live tests; mirrors tests/test_w10_visual_matrix.py.
OVERFLOW_JS = """
() => {
  const de = document.documentElement;
  const body = document.body;
  const sw = Math.max(de.scrollWidth, body ? body.scrollWidth : 0);
  const cw = de.clientWidth;
  return { overflowX: sw > cw + 1, scrollWidth: sw, clientWidth: cw };
}
"""
