"""Pytest collection policy for runtime and live e2e suites.

Isolates user-state from production DB: ``HOME_RAG_DATA_DIR`` is redirected
to a per-session temporary directory so that no test run can read or write
``user_state.db`` in the production data tree.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any


_TESTS_ROOT = Path(__file__).resolve().parent
_E2E_ROOT = _TESTS_ROOT / "e2e"

_SESSION_TMP: str | None = None


def _under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _explicit_e2e_arg(config: Any) -> bool:
    invocation_dir = Path(str(config.invocation_params.dir)).resolve()
    for raw in config.args:
        candidate = Path(str(raw))
        if not candidate.is_absolute():
            candidate = invocation_dir / candidate
        if _under(candidate, _E2E_ROOT) or candidate.resolve() == _E2E_ROOT.resolve():
            return True
    return False


def pytest_configure(config: Any) -> None:
    global _SESSION_TMP
    _SESSION_TMP = tempfile.mkdtemp(prefix="hometutor_test_")
    os.environ["HOME_RAG_DATA_DIR"] = _SESSION_TMP
    os.environ["HOME_RAG_HOME"] = _SESSION_TMP
    try:
        import app.config

        app.config._settings = None
        app.config._retrieval_settings = None
    except ImportError:
        pass


def pytest_ignore_collect(collection_path: Path, config: Any) -> bool:
    """Keep live Playwright e2e out of the default pytest suite.

    ``pytest tests/e2e`` remains an explicit opt-in and is not ignored.
    """
    path = Path(str(collection_path))
    if not _under(path, _E2E_ROOT):
        return False
    return not _explicit_e2e_arg(config)
