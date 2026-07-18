"""Pytest collection policy for runtime and live e2e suites."""

from __future__ import annotations

from pathlib import Path
from typing import Any


_TESTS_ROOT = Path(__file__).resolve().parent
_E2E_ROOT = _TESTS_ROOT / "e2e"


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


def pytest_ignore_collect(collection_path: Path, config: Any) -> bool:
    """Keep live Playwright e2e out of the default pytest suite.

    ``pytest tests/e2e`` remains an explicit opt-in and is not ignored.
    """
    path = Path(str(collection_path))
    if not _under(path, _E2E_ROOT):
        return False
    return not _explicit_e2e_arg(config)
