from __future__ import annotations

from pathlib import Path, PureWindowsPath

# Re-export: many tests monkeypatch ``path_safety.DATA_DIR``. Production code
# should call :func:`get_data_dir` (settings-backed); the module attribute remains
# for patch compatibility and is honored when it diverges from config.DATA_DIR.
from app.config import DATA_DIR as DATA_DIR  # noqa: PLC0414


def get_data_dir() -> Path:
    """Canonical ``data/`` root via :func:`app.config.get_settings`.

    Allowed path helper for runtime modules (AGENTS / conventions). Honors a
    monkeypatched ``path_safety.DATA_DIR`` so existing tests keep working.
    """
    from app import config as config_mod

    # Tests: monkeypatch.setattr(path_safety, "DATA_DIR", tmp_path)
    module_root = Path(DATA_DIR).resolve()
    config_root = Path(config_mod.DATA_DIR).resolve()
    if module_root != config_root:
        return module_root
    return Path(config_mod.get_settings().data_dir).resolve()


def _looks_absolute_or_drive_path(raw: str) -> bool:
    path = Path(raw)
    windows_path = PureWindowsPath(raw)
    return path.is_absolute() or windows_path.is_absolute() or bool(windows_path.drive)


def resolve_data_relative_path(relative_path: str, *, data_dir: Path | None = None) -> Path:
    """Resolve a user-supplied path and require it to stay inside data/."""
    raw = str(relative_path or "").strip()
    if not raw:
        raise ValueError("Relative path is required")
    if _looks_absolute_or_drive_path(raw):
        raise ValueError("Path must be relative to the data directory")

    root = (data_dir if data_dir is not None else get_data_dir()).resolve()
    path = (root / raw).resolve()

    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Path must stay inside the data directory") from exc

    return path


def validate_data_relative_path(relative_path: str, *, data_dir: Path | None = None) -> str:
    path = resolve_data_relative_path(relative_path, data_dir=data_dir)
    root = (data_dir if data_dir is not None else get_data_dir()).resolve()
    return path.relative_to(root).as_posix()


def data_relative_from_path(path: str | Path, *, data_dir: Path | None = None) -> str:
    """Return a canonical POSIX path relative to data/ for an absolute path."""
    raw = Path(path) if isinstance(path, Path) else Path(str(path or "").strip())
    if not str(raw):
        raise ValueError("Path is required")
    if not raw.is_absolute() and not PureWindowsPath(str(raw)).is_absolute():
        raise ValueError("Path must be absolute")

    root = (data_dir if data_dir is not None else get_data_dir()).resolve()
    resolved = raw.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("Path must stay inside the data directory") from exc


__all__ = [
    "DATA_DIR",
    "data_relative_from_path",
    "get_data_dir",
    "resolve_data_relative_path",
    "validate_data_relative_path",
]
