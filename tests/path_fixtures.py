"""Shared path/data-dir test helpers (gradual migration off bare DATA_DIR patches).

Prefer :func:`patch_data_dir` in new tests. It sets both ``path_safety.DATA_DIR``
(legacy monkeypatch surface) and ``get_data_dir`` so production helpers resolve
into the temp tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def patch_data_dir(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> Path:
    """Point path_safety (and library read-model) at ``data_dir`` for the test."""
    import app.path_safety as path_safety

    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(path_safety, "DATA_DIR", root)
    monkeypatch.setattr(path_safety, "get_data_dir", lambda: root.resolve())
    try:
        monkeypatch.setattr("app.library_catalog_read.get_data_dir", lambda: root.resolve())
    except Exception:  # noqa: BLE001 - module may be unused in this test
        pass
    return root


__all__ = ["patch_data_dir"]
