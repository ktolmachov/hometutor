"""Строковые метки для сравнения версии индекса (research sessions, resume)."""


def index_version_label(stats: dict | None) -> str:
    if not stats:
        return ""
    iv = stats.get("index_version")
    gid = stats.get("generation_id")
    if iv is not None and gid:
        return f"v{int(iv)}:{gid}"
    c = stats.get("collection_name") or ""
    ts = stats.get("last_indexed_at") or ""
    if not c and not ts:
        return ""
    return f"{c}:{ts}"
