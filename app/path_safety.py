from __future__ import annotations

from pathlib import Path, PureWindowsPath

from app.config import DATA_DIR


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

    root = (data_dir or DATA_DIR).resolve()
    path = (root / raw).resolve()

    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Path must stay inside the data directory") from exc

    return path


def validate_data_relative_path(relative_path: str, *, data_dir: Path | None = None) -> str:
    path = resolve_data_relative_path(relative_path, data_dir=data_dir)
    root = (data_dir or DATA_DIR).resolve()
    return path.relative_to(root).as_posix()


def data_relative_from_path(path: str | Path, *, data_dir: Path | None = None) -> str:
    """Return a canonical POSIX path relative to data/ for an absolute path."""
    raw = Path(path) if isinstance(path, Path) else Path(str(path or "").strip())
    if not str(raw):
        raise ValueError("Path is required")
    if not raw.is_absolute() and not PureWindowsPath(str(raw)).is_absolute():
        raise ValueError("Path must be absolute")

    root = (data_dir or DATA_DIR).resolve()
    resolved = raw.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("Path must stay inside the data directory") from exc


__all__ = [
    "data_relative_from_path",
    "resolve_data_relative_path",
    "validate_data_relative_path",
]
