"""Shared fixtures for live Streamlit e2e (W10.F1/W10.F2).

Default mode: the harness spawns a self-contained local FastAPI + Streamlit
stack on free ports, backed by a temporary seeded HOME_RAG_HOME.

External-stack mode: set ``HT_E2E_STREAMLIT_URL`` to connect to an
already-running Streamlit URL instead.

Opt-out: ``HT_SKIP_E2E_LIVE=1``.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = ROOT / "tests" / "e2e" / "_artifacts"
DEFAULT_STREAMLIT_URL = "http://127.0.0.1:8501"
_E2E_HEALTH_TIMEOUT = 3.0
_E2E_START_TIMEOUT = 90.0
_E2E_CHUNKS_COLLECTION = "home_rag_e2e_chunks"
_E2E_SUMMARY_COLLECTION = "home_rag_e2e_summaries"


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


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_http_ok(url: str, *, label: str, expected_text: str | None = None) -> tuple[bool, str]:
    try:
        import requests  # local import: requests is a runtime dep
    except Exception as exc:  # noqa: BLE001 - guard for stripped envs
        return False, f"requests import failed: {exc}"

    deadline = time.time() + _E2E_START_TIMEOUT
    last = "not attempted"
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=_E2E_HEALTH_TIMEOUT)
            if r.status_code == 200 and (expected_text is None or r.text.strip() == expected_text):
                return True, "ok"
            last = f"{label} -> {r.status_code} {r.text[:80]!r}"
        except Exception as exc:  # noqa: BLE001 - process may still be starting
            last = f"{label} unreachable: {exc}"
        time.sleep(0.5)
    return False, last


def _seed_returning_home(home: Path) -> None:
    """Create a tiny indexed HomeTutor home so Mission Control is non-cold."""
    data_dir = home / "data"
    chroma_dir = home / "chroma_db"
    data_dir.mkdir(parents=True, exist_ok=True)
    chroma_dir.mkdir(parents=True, exist_ok=True)

    rel = "e2e/course_intro.md"
    source = data_dir / rel
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "# E2E returning course\n\n"
        "This tiny local source exists only for live Mission Control returning-state smoke.\n",
        encoding="utf-8",
    )
    (home / "index_meta.json").write_text(
        json.dumps(
            {
                rel: {"size": source.stat().st_size, "mtime": source.stat().st_mtime},
                "__meta__": {"embed_model": "e2e-dummy"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (home / "index_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "index_version": 1,
                "active_generation": {
                    "generation_id": "e2e_returning_seed",
                    "chunks_collection": _E2E_CHUNKS_COLLECTION,
                    "summaries_collection": _E2E_SUMMARY_COLLECTION,
                    "activated_at": "2026-07-18T00:00:00+00:00",
                    "embed_model": "e2e-dummy",
                    "documents_count": 1,
                    "nodes_count": 1,
                    "summary_documents_count": 0,
                },
                "previous_generation": None,
                "staging_generation": None,
                "last_failed_generation": None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    import chromadb

    client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = client.get_or_create_collection(_E2E_CHUNKS_COLLECTION)
    collection.add(
        ids=["e2e-returning-node-1"],
        documents=["Returning learner indexed material for Mission Control live smoke."],
        embeddings=[[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]],
        metadatas=[{"relative_path": rel, "file_name": rel, "folder_rel": "e2e"}],
    )
    client.get_or_create_collection(_E2E_SUMMARY_COLLECTION)


def _spawn_env(home: Path, api_port: int, ui_port: int) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "PYTHONHOME": "",
            "PYTHONPATH": "",
            "HOME_RAG_HOME": str(home),
            "HOME_RAG_DATA_DIR": str(home / "data"),
            "HOME_RAG_INDEX_DIR": str(home / "chroma_db"),
            "HOME_RAG_LOG_DIR": str(home / "logs"),
            "COLLECTION_NAME": _E2E_CHUNKS_COLLECTION,
            "SUMMARY_COLLECTION_NAME": _E2E_SUMMARY_COLLECTION,
            "UI_API_BASE_URL": f"http://127.0.0.1:{api_port}",
            "STREAMLIT_UI_URL": f"http://127.0.0.1:{ui_port}",
            "AUTH_ENABLED": "false",
            "HOME_RAG_API_KEY": "",
            "HOME_RAG_E2E_OFFLINE": "1",
            "HOME_RAG_E2E_NO_LOG_ROTATE": "1",
            "OFFLINE_PROBE_LLM_ENDPOINT": "false",
            "LLM_LOCAL_WARMUP": "false",
            "ENABLE_SSR_LLM_PROFILING": "false",
            "LLM_REQUEST_CACHE_PERSIST": "false",
        }
    )
    return env


def _terminate_process(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=8)


@pytest.fixture(scope="session")
def e2e_artifacts_dir() -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS_DIR


@pytest.fixture(scope="session")
def e2e_streamlit_url(e2e_artifacts_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> str:
    """Resolved + health-checked Streamlit base URL.

    ``HT_E2E_STREAMLIT_URL`` keeps the previous external-stack mode. Without it
    the fixture spawns a deterministic temporary stack and tears it down after
    the session.
    """
    _skip_if_disabled()
    if os.environ.get("HT_E2E_STREAMLIT_URL"):
        url = _streamlit_url()
        ok, reason = _stack_is_live(url)
        if not ok:
            pytest.skip(
                f"live Streamlit stack not reachable at {url} ({reason}). "
                "Unset HT_E2E_STREAMLIT_URL to use spawned-stack mode, "
                "or HT_SKIP_E2E_LIVE=1 to skip."
            )
        return url

    home = tmp_path_factory.mktemp("hometutor_e2e_home")
    _seed_returning_home(home)
    api_port = _find_free_port()
    ui_port = _find_free_port()
    env = _spawn_env(home, api_port, ui_port)
    backend_log = (e2e_artifacts_dir / "spawned_fastapi.log").open("w", encoding="utf-8")
    streamlit_log = (e2e_artifacts_dir / "spawned_streamlit.log").open("w", encoding="utf-8")
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    backend = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=backend_log,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    try:
        ok, reason = _wait_for_http_ok(
            f"http://127.0.0.1:{api_port}/health",
            label="FastAPI /health",
        )
        if not ok or backend.poll() is not None:
            pytest.fail(
                "spawned FastAPI stack did not become healthy. "
                f"reason={reason}; log={backend_log.name}"
            )

        streamlit = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(ROOT / "app" / "ui" / "main.py"),
                "--server.address",
                "127.0.0.1",
                "--server.port",
                str(ui_port),
                "--browser.gatherUsageStats",
                "false",
                "--server.headless",
                "true",
            ],
            cwd=str(ROOT),
            env=env,
            stdout=streamlit_log,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    except BaseException:
        _terminate_process(backend)
        backend_log.close()
        streamlit_log.close()
        raise

    try:
        url = f"http://127.0.0.1:{ui_port}"
        ok, reason = _wait_for_http_ok(
            f"{url}/_stcore/health",
            label="Streamlit health",
            expected_text="ok",
        )
        if not ok or streamlit.poll() is not None:
            pytest.fail(
                "spawned Streamlit stack did not become healthy. "
                f"reason={reason}; log={streamlit_log.name}"
            )
        ok, reason = _stack_is_live(url)
        if not ok:
            pytest.fail(f"spawned Streamlit stack failed readiness probe: {reason}")
        yield url
    finally:
        _terminate_process(streamlit)
        _terminate_process(backend)
        backend_log.close()
        streamlit_log.close()


@pytest.fixture(scope="session")
def e2e_external_streamlit_url() -> str:
    """Previous external-stack URL, kept for opt-in local debugging."""
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
    console_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    page.on(
        "console",
        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
    )
    setattr(page, "_e2e_errors", page_errors)  # type: ignore[attr-defined]
    setattr(page, "_e2e_console_errors", console_errors)  # type: ignore[attr-defined]
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
