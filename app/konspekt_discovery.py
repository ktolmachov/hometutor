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


@dataclass(frozen=True)
class CoverageSummary:
    covered: int
    total: int

    @property
    def pct(self) -> float:
        return self.covered / self.total if self.total else 0.0


def _parse_frontmatter(text: str) -> dict[str, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    return dict(_FIELD_RE.findall(m.group(1)))


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
