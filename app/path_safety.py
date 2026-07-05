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


__all__ = ["resolve_data_relative_path", "validate_data_relative_path"]
