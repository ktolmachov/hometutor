"""
Backup / restore индексных артефактов (итерация 16 tail).

Формат: ZIP с manifest.json и деревом путей относительно корня проекта (BASE_DIR).
Не заменяет остановку API при restore — см. doc/index_lifecycle.md.
"""

from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from app.config import BASE_DIR, CHROMA_DIR, DATA_DIR, get_settings
from app.index_diff import INDEX_META_PATH
from app.index_registry import REGISTRY_PATH
from app.logging_config import setup_logging

logger = setup_logging()

MANIFEST_NAME = "manifest.json"
BACKUP_SCHEMA_VERSION = 1

# Файлы блокировок не включаем — при восстановлении не нужны.
_SKIP_SUFFIXES = (".lock",)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def iter_files_under(root: Path) -> list[Path]:
    if not root.exists():
        return []
    out: list[Path] = []
    if root.is_file():
        if not any(str(root).endswith(s) for s in _SKIP_SUFFIXES):
            return [root]
        return []
    for dirpath, _dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        for name in filenames:
            p = dp / name
            if any(str(p).endswith(s) for s in _SKIP_SUFFIXES):
                continue
            if name.endswith(".lock"):
                continue
            out.append(p)
    return sorted(out)


def collect_backup_entries(
    *,
    base_dir: Path | None = None,
    include_concept_graph: bool = True,
    include_faq_memory: bool = False,
) -> list[tuple[str, Path]]:
    """
    Список (относительный_путь_в_архиве, абсолютный_путь).
    Только существующие пути.
    """
    base = base_dir or BASE_DIR
    entries: list[tuple[str, Path]] = []

    reg = REGISTRY_PATH.resolve()
    if reg.exists():
        entries.append((str(reg.relative_to(base)), reg))

    meta = INDEX_META_PATH.resolve()
    if meta.exists():
        entries.append((str(meta.relative_to(base)), meta))

    chroma = CHROMA_DIR.resolve()
    if chroma.exists():
        for f in iter_files_under(chroma):
            try:
                rel = f.relative_to(base)
            except ValueError:
                rel = Path("chroma_db") / f.relative_to(chroma)
            entries.append((str(rel).replace("\\", "/"), f))

    cg = (DATA_DIR / "concept_graph.json").resolve()
    if include_concept_graph and cg.exists():
        try:
            entries.append((str(cg.relative_to(base)).replace("\\", "/"), cg))
        except ValueError:
            entries.append((f"data/concept_graph.json", cg))

    graph_gen = (DATA_DIR / "graph_generations").resolve()
    if include_concept_graph and graph_gen.exists():
        for f in iter_files_under(graph_gen):
            try:
                rel = f.relative_to(base)
            except ValueError:
                rel = Path("data/graph_generations") / f.relative_to(graph_gen)
            entries.append((str(rel).replace("\\", "/"), f))

    faq = Path(get_settings().faq_memory_path).resolve()
    if include_faq_memory and faq.exists():
        try:
            entries.append((str(faq.relative_to(base)).replace("\\", "/"), faq))
        except ValueError:
            entries.append(("faq_memory.jsonl", faq))

    # Уникальность по arcname
    seen: set[str] = set()
    unique: list[tuple[str, Path]] = []
    for arc, p in entries:
        if arc in seen:
            continue
        seen.add(arc)
        unique.append((arc, p))
    return unique


def create_backup_zip(
    archive_path: Path,
    *,
    base_dir: Path | None = None,
    include_concept_graph: bool = True,
    include_faq_memory: bool = False,
) -> dict[str, Any]:
    """Создать ZIP с индексными артефактами. Вернуть manifest как dict."""
    base = base_dir or BASE_DIR
    entries = collect_backup_entries(
        base_dir=base,
        include_concept_graph=include_concept_graph,
        include_faq_memory=include_faq_memory,
    )
    if not entries:
        raise FileNotFoundError("Нет файлов для резервной копии (индекс не создан?)")

    manifest: dict[str, Any] = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "created_at": _utc_iso(),
        "base_dir": str(base),
        "entries": [{"path": arc, "size": p.stat().st_size} for arc, p in entries],
    }

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        for arc, p in entries:
            zf.write(p, arcname=arc)

    logger.info("Index backup written | path=%s | files=%s", archive_path, len(entries))
    return manifest


def read_manifest_from_zip(archive_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(archive_path, "r") as zf:
        with zf.open(MANIFEST_NAME) as fh:
            return json.load(fh)


def _restore_target_for_member(base: Path, member_name: str) -> Path:
    name = member_name.replace("\\", "/")
    member = PurePosixPath(name)
    if (
        not name
        or member.is_absolute()
        or any(part in ("", ".", "..") for part in member.parts)
        or any(":" in part for part in member.parts)
    ):
        raise ValueError(f"Unsafe backup member path: {member_name!r}")

    target = (base / Path(*member.parts)).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Backup member escapes restore base: {member_name!r}") from exc
    return target


def restore_backup_zip(
    archive_path: Path,
    *,
    base_dir: Path | None = None,
    overwrite: bool = True,
) -> dict[str, Any]:
    """
    Распаковать ZIP в base_dir. Существующие файлы перезаписываются при overwrite=True.
    """
    base = (base_dir or BASE_DIR).resolve()
    if not overwrite:
        raise ValueError("restore с overwrite=False не поддержан (итерация 16 tail)")

    with zipfile.ZipFile(archive_path, "r") as zf:
        manifest_raw = zf.read(MANIFEST_NAME).decode("utf-8")
        manifest = json.loads(manifest_raw)
        ver = manifest.get("schema_version")
        if ver is not None and int(ver) > BACKUP_SCHEMA_VERSION:
            raise ValueError(f"Неподдерживаемая версия backup manifest: {ver}")

        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name == MANIFEST_NAME or name.endswith("/"):
                continue
            target = _restore_target_for_member(base, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())

    logger.warning(
        "Index backup restored into %s — перезапустите API и выполните clear retrieval cache при необходимости",
        base,
    )
    return manifest
