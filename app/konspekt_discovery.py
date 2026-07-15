"""Поиск готовых cloud-конспектов в data/<course>/ по YAML-frontmatter type=konspekt."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import DATA_DIR

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_FIELD_RE = re.compile(r"^(\w+):\s*(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class KonspektMeta:
    path: Path
    source: str
    presentation: str | None
    generated: str | None
    tags: tuple[str, ...]
    source_sha256: str | None = None


@dataclass(frozen=True)
class CoverageSummary:
    covered: int
    total: int

    @property
    def pct(self) -> float:
        return self.covered / self.total if self.total else 0.0


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _parse_frontmatter(text: str) -> dict[str, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    return dict(_FIELD_RE.findall(m.group(1)))


def _parse_source_sha256(fm: dict[str, str]) -> str | None:
    raw = str(fm.get("source_sha256") or "").strip().strip('"').strip("'")
    if not _SHA256_RE.fullmatch(raw):
        return None
    return raw.lower()


def _normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Полноценный перф-кеш для scan_konspekts (pre-existing perf issue noted in review)
# Signature по файлам .md в курсе (mtime + size) — как _cached_parse_sections по контенту.
_KONSPEKT_SCAN_CACHE: dict[Path, tuple[str, list[KonspektMeta]]] = {}


def _konspekt_scan_signature(course_dir: Path) -> str:
    if not course_dir.is_dir():
        return ""
    parts: list[str] = []
    for md in sorted(course_dir.glob("*.md")):
        try:
            st = md.stat()
            parts.append(f"{md.name}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{md.name}:err")
    raw = "|".join(parts).encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def scan_konspekts(course_dir: Path) -> list[KonspektMeta]:
    """Вернуть все .md-файлы в course_dir с type: konspekt в frontmatter.

    Полноценный кэш по сигнатуре содержимого dir (pre-existing perf fix).
    """
    if not course_dir.is_dir():
        return []
    sig = _konspekt_scan_signature(course_dir)
    cached = _KONSPEKT_SCAN_CACHE.get(course_dir)
    if cached is not None and cached[0] == sig:
        return cached[1]

    results: list[KonspektMeta] = []
    for md in course_dir.glob("*.md"):
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        if fm.get("type", "").strip().strip('"').strip("'") != "konspekt":
            continue
        raw_tags = fm.get("tags", "")
        tags = tuple(t.strip().strip("[]").strip() for t in re.split(r"[,\s]+", raw_tags) if t.strip().strip("[]"))
        results.append(KonspektMeta(
            path=md,
            source=fm.get("source", "").strip().strip('"').strip("'"),
            presentation=fm.get("presentation", "").strip().strip('"').strip("'") or None,
            generated=fm.get("generated", "").strip().strip('"').strip("'") or None,
            tags=tags,
            source_sha256=_parse_source_sha256(fm),
        ))

    _KONSPEKT_SCAN_CACHE[course_dir] = (sig, results)
    return results


def find_konspekt_for_source(source_rel: str, course_dir: Path) -> KonspektMeta | None:
    """Найти конспект для документа по имени source-файла.

    Матчинг: normalize(basename(source_rel)) == normalize(konspekt.source).
    Неверный матч хуже отсутствия матча — требуем точное совпадение после нормализации.
    """
    needle = _normalize(Path(source_rel).name)
    if not needle:
        return None
    for km in scan_konspekts(course_dir):
        if _normalize(km.source) == needle:
            return km
    return None


def find_konspekt_for_source_in_data(source_rel: str) -> KonspektMeta | None:
    """Найти конспект, определяя course_dir из первого сегмента source_rel."""
    parts = Path(source_rel).parts
    if len(parts) < 2:
        return None
    course_dir = DATA_DIR / parts[0]
    return find_konspekt_for_source(source_rel, course_dir)


def coverage_summary(doc_paths: list[str]) -> CoverageSummary:
    """Подсчитать, сколько из doc_paths имеют готовый конспект."""
    covered = sum(1 for p in doc_paths if find_konspekt_for_source_in_data(p) is not None)
    return CoverageSummary(covered=covered, total=len(doc_paths))


# ── C1: staleness of konspekt vs source (cheap, no LLM) ────────────────────
# Frontmatter ``source_sha256`` is written by Obsidian export / smart_konspekt.
# Hash styles differ (utf-8 text vs smart name+bytes). We accept any primary-
# source variant as fresh; if none match and the source file is newer than the
# konspekt → stale; otherwise unknown (e.g. multi-input smart hash).


def resolve_konspekt_source_path(
    km: KonspektMeta,
    *,
    source_rel: str | None = None,
    data_dir: Path | str | None = None,
) -> Path | None:
    """Resolve the lecture/source file that this konspekt claims to cover."""
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    candidates: list[Path] = []
    if source_rel:
        rel = str(source_rel).replace("\\", "/").strip()
        if rel:
            candidates.append(root / rel)
    src = str(km.source or "").replace("\\", "/").strip()
    if src:
        candidates.append(root / src)
        candidates.append(km.path.parent / src)
        candidates.append(km.path.parent / Path(src).name)
        # Parent course folder + basename (common for course/a.md ↔ course/konspekt)
        parts = Path(src).parts
        if len(parts) >= 1:
            candidates.append(km.path.parent / parts[-1])
    seen: set[str] = set()
    for cand in candidates:
        try:
            key = str(cand.resolve())
        except OSError:
            key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        if cand.is_file():
            return cand
    return None


def _source_hash_variants(source_path: Path) -> set[str]:
    """Hashes that Obsidian export / single-file smart_konspekt may have stored."""
    out: set[str] = set()
    try:
        raw_bytes = source_path.read_bytes()
    except OSError:
        return out
    out.add(hashlib.sha256(raw_bytes).hexdigest())
    try:
        text = raw_bytes.decode("utf-8", errors="replace")
        out.add(hashlib.sha256(text.encode("utf-8")).hexdigest())
    except Exception:  # noqa: BLE001 - decode edge cases skip text variant
        pass
    # smart_konspekt single-file style: name + NUL + bytes + NUL
    h = hashlib.sha256()
    h.update(source_path.name.encode("utf-8"))
    h.update(b"\0")
    h.update(raw_bytes)
    h.update(b"\0")
    out.add(h.hexdigest())
    return out


@lru_cache(maxsize=128)
def _cached_staleness_state(
    konspekt_key: str,
    k_mtime_ns: int,
    k_size: int,
    source_key: str,
    s_mtime_ns: int,
    s_size: int,
    stored_hash: str,
) -> str:
    """Return 'fresh' | 'stale' | 'unknown' (cached on path mtimes/sizes)."""
    source_path = Path(source_key)
    variants = _source_hash_variants(source_path)
    if stored_hash in variants:
        return "fresh"
    # Multi-input smart hash (or other style) cannot be recomputed from primary alone:
    # only flag stale when the source file is strictly newer than the konspekt.
    if s_mtime_ns > k_mtime_ns:
        return "stale"
    return "unknown"


def konspekt_source_staleness(
    km: KonspektMeta,
    *,
    source_rel: str | None = None,
    data_dir: Path | str | None = None,
) -> str | None:
    """Whether the konspekt is out of date relative to its source lecture.

    Returns:
      - ``"stale"`` — source changed after konspekt (or hash mismatch + newer source)
      - ``"fresh"`` — stored hash matches a known single-source style
      - ``None`` — no ``source_sha256``, missing source, or ambiguous hash style
    """
    stored = (km.source_sha256 or "").strip().lower()
    if not stored or not _SHA256_RE.fullmatch(stored):
        return None
    src = resolve_konspekt_source_path(km, source_rel=source_rel, data_dir=data_dir)
    if src is None:
        return None
    try:
        k_stat = km.path.stat()
        s_stat = src.stat()
    except OSError:
        return None
    state = _cached_staleness_state(
        str(km.path.resolve()),
        int(k_stat.st_mtime_ns),
        int(k_stat.st_size),
        str(src.resolve()),
        int(s_stat.st_mtime_ns),
        int(s_stat.st_size),
        stored,
    )
    if state == "unknown":
        return None
    return state


def konspekt_stale_badge_label(
    km: KonspektMeta,
    *,
    source_rel: str | None = None,
    data_dir: Path | str | None = None,
) -> str | None:
    """Learner-facing fragment when stale, else None."""
    if konspekt_source_staleness(km, source_rel=source_rel, data_dir=data_dir) == "stale":
        return "🕰 устарел"
    return None


# ── A1: парсер рубрики качества конспекта (детерминированный, без LLM) ─────
# Ищет таблицу после «## ✅ Рубрика качества конспекта» (или вариации).
# Формат: | Критерий | Оценка | Макс | Комментарий |
# Кривая таблица → None (graceful degradation).

_RUBRIC_HEADING_RE = re.compile(
    r"^##\s*✅?\s*Рубрика качества(?:\s+конспекта)?", re.IGNORECASE | re.MULTILINE
)
_TABLE_ROW_RE = re.compile(r"^\s*\|\s*(.+?)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(.*?)\s*\|", re.MULTILINE)


def parse_konspekt_quality_rubric(md_path: Path | str) -> dict | None:
    """Parse quality rubric table from a konspekt .md.

    Returns {'items': [(criterion, score, max_score, comment), ...], 'average': float | None}
    or None if heading/table not found or malformed.
    """
    try:
        p = Path(md_path)
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    # Find rubric section start
    match = _RUBRIC_HEADING_RE.search(text)
    if not match:
        return None

    start = match.end()
    # Look for table rows after the heading (take first plausible table)
    rows = _TABLE_ROW_RE.findall(text[start : start + 4000])  # limit scan window
    if not rows:
        return None

    items: list[tuple[str, int, int, str]] = []
    for crit, score_s, max_s, comment in rows:
        try:
            score = int(score_s)
            max_score = int(max_s)
            if score < 0 or max_score <= 0:
                continue
            items.append((crit.strip(), score, max_score, comment.strip()))
        except ValueError:
            continue

    if not items:
        return None

    avg = round(sum(s for _, s, _, _ in items) / len(items), 1)
    return {"items": items, "average": avg, "count": len(items)}


@lru_cache(maxsize=64)
def _cached_quality_rubric(path_str: str, mtime_ns: int) -> dict | None:
    """LRU cache by (path, mtime) per plan guidance (A1)."""
    return parse_konspekt_quality_rubric(path_str)


def get_konspekt_quality_rubric(md_path: Path | str) -> dict | None:
    """Cached entry point for UI (A1). Uses mtime for invalidation (cheap)."""
    try:
        p = Path(md_path)
        mtime = p.stat().st_mtime_ns if p.exists() else 0
        return _cached_quality_rubric(str(p), mtime)
    except Exception:
        return None
