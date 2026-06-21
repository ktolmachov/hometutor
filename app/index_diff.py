import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.chroma_vector_backend import get_default_chroma_backend
from app.config import CHROMA_DIR, DATA_DIR, get_settings
from app.index_registry import get_index_version_public
from app.index_state import get_active_collection_names, load_active_index_state
from app.logging_config import setup_logging


logger = setup_logging()

# ---------------------------------------------------------------------------
# index_stats TTL cache — prevents repeated full Chroma metadata scans per bootstrap
# ---------------------------------------------------------------------------
_index_stats_cache: dict[str, Any] = {}
_index_stats_lock = threading.Lock()
_index_stats_compute_lock = threading.Lock()  # prevents thundering herd on cold cache
_INDEX_STATS_TTL = 1800  # seconds; 30 min — stats are semi-static, only change after reindex.
# Previously 600s (10 min), which caused /ui/bootstrap to hit a cold Chroma scan ~13 min
# into a session (Streamlit bootstrap cache is 300s, so it re-fetches every 5 min).


def _index_stats_cache_key() -> tuple[Any, ...]:
    """Fingerprint for cache hits: paths/collection must match get_index_stats() inputs."""
    collection_name = COLLECTION_NAME or get_active_collection_names()[0]
    return (str(CHROMA_DIR), str(INDEX_META_PATH), collection_name)


def _index_stats_cache_get() -> dict[str, Any] | None:
    key = _index_stats_cache_key()
    with _index_stats_lock:
        entry = _index_stats_cache.get("value")
        ts = _index_stats_cache.get("ts", 0.0)
        stored_key = _index_stats_cache.get("fingerprint")
        if (
            entry is not None
            and stored_key == key
            and (time.monotonic() - ts) < _INDEX_STATS_TTL
        ):
            return entry
    return None


def _index_stats_cache_set(value: dict[str, Any]) -> None:
    key = _index_stats_cache_key()
    with _index_stats_lock:
        _index_stats_cache["value"] = value
        _index_stats_cache["ts"] = time.monotonic()
        _index_stats_cache["fingerprint"] = key


def invalidate_index_stats_cache() -> None:
    with _index_stats_lock:
        _index_stats_cache.clear()

INDEX_META_PATH = Path(get_settings().index_meta_path)
COLLECTION_NAME: Optional[str] = None

SUPPORTED_EXTS = {".pdf", ".txt", ".md", ".docx", ".html"}


def _can_use_data_dir_stats(chroma_path: Path) -> bool:
    """Use data-dir stats only for the default local index, not injected stores."""
    import app.config as _cfg
    try:
        return chroma_path.resolve() == _cfg.CHROMA_DIR.resolve()
    except OSError:
        return chroma_path == _cfg.CHROMA_DIR


def _build_snapshot_from_fs() -> Dict[str, Dict[str, Any]]:
    snapshot: Dict[str, Dict[str, Any]] = {}
    data_dir = DATA_DIR

    if not data_dir.exists():
        return snapshot

    for path in data_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTS:
            continue

        try:
            rel = path.relative_to(data_dir).as_posix()
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            rel = path.name

        try:
            stat = path.stat()
        except OSError:
            continue

        snapshot[rel] = {
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        }

    return snapshot


def _load_snapshot() -> Dict[str, Dict[str, Any]]:
    if not INDEX_META_PATH.exists():
        return {}

    try:
        with open(INDEX_META_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        return {}


def _save_snapshot(snapshot: Dict[str, Dict[str, Any]]) -> None:
    try:
        INDEX_META_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(INDEX_META_PATH, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001 - snapshot save failure is logged and non-fatal
        logger.warning("Index diff: failed to save snapshot | path=%s | error=%s", INDEX_META_PATH, e)


def update_snapshot_after_index() -> None:
    """Обновить snapshot после успешной индексации.

    Помимо файловых метаданных сохраняем служебный блок __meta__
    с embed-моделью, использованной при построении индекса.
    """
    snapshot = _build_snapshot_from_fs()

    try:
        settings = get_settings()
        snapshot["__meta__"] = {
            "embed_model": settings.embed_model,
        }
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        # Валидация embed-модели при старте retrieval — best-effort.
        # Если по какой-то причине настройки не прочитались,
        # не блокируем обновление snapshot.
        pass

    _save_snapshot(snapshot)
    logger.info("Index diff: snapshot updated | files=%s", len(snapshot))


def get_index_diff() -> Dict[str, Any]:
    """Посмотреть изменения файлов с последней индексации."""
    old_snapshot = _load_snapshot()
    new_snapshot = _build_snapshot_from_fs()

    added = []
    modified = []
    deleted = []

    for path, meta in new_snapshot.items():
        old = old_snapshot.get(path)
        if old is None:
            added.append({"path": path, **meta})
        else:
            if old.get("size") != meta["size"] or abs(old.get("mtime", 0) - meta["mtime"]) > 1e-6:
                modified.append(
                    {
                        "path": path,
                        "old_size": old.get("size"),
                        "new_size": meta["size"],
                        "old_mtime": old.get("mtime"),
                        "new_mtime": meta["mtime"],
                    }
                )

    for path, meta in old_snapshot.items():
        if path not in new_snapshot:
            deleted.append({"path": path, **meta})

    return {
        "added": sorted(added, key=lambda x: x["path"]),
        "modified": sorted(modified, key=lambda x: x["path"]),
        "deleted": sorted(deleted, key=lambda x: x["path"]),
        "summary": {
            "added": len(added),
            "modified": len(modified),
            "deleted": len(deleted),
        },
    }


def _last_indexed_at() -> Optional[str]:
    """ISO-timestamp последней индексации на основе mtime index_meta.json."""
    if not INDEX_META_PATH.exists():
        return None
    try:
        mtime = INDEX_META_PATH.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


_METADATA_PAGE_SIZE = 1_000


def _extract_files_and_folders_from_chroma(
    collection,
) -> tuple[List[str], List[str]]:
    """Paginated metadata scan returning (sorted_files, sorted_folder_rels).

    Fetches _METADATA_PAGE_SIZE records at a time instead of the entire
    collection at once to avoid ChromaDB OOM on large corpora.
    """
    files: set[str] = set()
    folders: set[str] = set()
    offset = 0
    while True:
        try:
            result = collection.get(
                include=["metadatas"],
                limit=_METADATA_PAGE_SIZE,
                offset=offset,
            )
        except Exception as _exc:  # noqa: BLE001
            logger.debug("! caught exception: %s", _exc)
            break
        metadatas = result.get("metadatas") or []
        for meta in metadatas:
            if not meta:
                continue
            rel = meta.get("relative_path") or meta.get("file_name")
            if rel:
                files.add(rel)
            fr = meta.get("folder_rel")
            if fr:
                folders.add(str(fr).strip())
        if len(metadatas) < _METADATA_PAGE_SIZE:
            break
        offset += _METADATA_PAGE_SIZE
    return sorted(files), sorted(folders)


def get_index_stats() -> Dict[str, Any]:
    """Статистика индекса: количество документов, нод, файлов, timestamp."""
    cached = _index_stats_cache_get()
    if cached is not None:
        return cached

    with _index_stats_compute_lock:
        # Re-check under lock: another thread may have filled cache while we waited.
        cached = _index_stats_cache_get()
        if cached is not None:
            return cached
        return _compute_index_stats()


def _compute_index_stats() -> Dict[str, Any]:
    """Internal — must be called while _index_stats_compute_lock is held."""
    chroma_dir = CHROMA_DIR
    collection_name = COLLECTION_NAME or get_active_collection_names()[0]
    chroma_path = Path(str(chroma_dir))
    version_info = get_index_version_public()
    base_meta = {
        "generation_id": version_info.get("generation_id"),
        "index_version": version_info.get("index_version"),
        "registry_activated_at": version_info.get("activated_at"),
        "last_failed_activation": version_info.get("last_failed"),
    }
    if not chroma_path.exists():
        return {
            "status": "not_initialized",
            "collection_name": collection_name,
            "active_index_state": load_active_index_state(),
            "documents_count": 0,
            "nodes_count": 0,
            "files": [],
            "folder_rel_options": [],
            "last_indexed_at": None,
            **base_meta,
        }

    try:
        # Reuse the already-warmed cached Chroma client when available.
        from app.retrieval_cache import get_cached_client
        cached_client = get_cached_client()
        if cached_client is not None:
            try:
                collection = cached_client.get_collection(collection_name)
            except Exception:  # noqa: BLE001 - fallback to fresh Chroma client if cached client retrieval fails
                client = get_default_chroma_backend(chroma_path).get_client()
                collection = client.get_collection(collection_name)
        else:
            client = get_default_chroma_backend(chroma_path).get_client()
            collection = client.get_collection(collection_name)
    except Exception as _exc:  # noqa: BLE001
        logger.debug("! caught exception: %s", _exc)
        result = {
            "status": "no_collection",
            "collection_name": collection_name,
            "active_index_state": load_active_index_state(),
            "documents_count": 0,
            "nodes_count": 0,
            "files": [],
            "folder_rel_options": [],
            "last_indexed_at": _last_indexed_at(),
            **base_meta,
        }
        return result

    nodes_count = collection.count()

    # Fast path 1: index snapshot (JSON written at reindex time).
    # Fast path 2: data-directory filesystem walk (same source as the snapshot).
    # Slow fallback: paginated Chroma metadata scan — only when both above are empty
    # (first-ever index before snapshot was introduced, or corrupted state).
    # Avoiding the Chroma scan is critical: it can take 20+ seconds and cause OOM.
    snapshot = _load_snapshot()
    snapshot_files = sorted(k for k in snapshot if k != "__meta__")
    if snapshot_files:
        files = snapshot_files
        folder_rel_options = sorted({
            str(Path(f).parent)
            for f in files
            if Path(f).parent != Path(".")
        })
        logger.debug(
            "index_stats: used snapshot for files | files=%d folders=%d",
            len(files), len(folder_rel_options),
        )
    else:
        # No snapshot yet — scan the data directory (fast filesystem walk).
        fs_snapshot = _build_snapshot_from_fs() if _can_use_data_dir_stats(chroma_path) else {}
        fs_files = sorted(k for k in fs_snapshot if k != "__meta__")
        if fs_files:
            files = fs_files
            folder_rel_options = sorted({
                str(Path(f).parent)
                for f in files
                if Path(f).parent != Path(".")
            })
            logger.debug(
                "index_stats: used fs scan for files | files=%d folders=%d",
                len(files), len(folder_rel_options),
            )
        else:
            # Last resort: paginated Chroma metadata scan.
            logger.warning("index_stats: snapshot and data dir both empty — falling back to Chroma scan")
            files, folder_rel_options = _extract_files_and_folders_from_chroma(collection)

    result = {
        "status": "ok",
        "collection_name": collection_name,
        "active_index_state": load_active_index_state(),
        "documents_count": len(files),
        "nodes_count": nodes_count,
        "files": files,
        "folder_rel_options": folder_rel_options,
        "last_indexed_at": _last_indexed_at(),
        **base_meta,
    }
    _index_stats_cache_set(result)
    return result


def get_index_embed_model() -> Optional[str]:
    """Модель эмбеддингов, использованная при последней индексации (если сохранена)."""
    data = _load_snapshot()
    meta = data.get("__meta__")
    if not isinstance(meta, dict):
        return None
    value = meta.get("embed_model")
    if value is None:
        return None
    return str(value)
