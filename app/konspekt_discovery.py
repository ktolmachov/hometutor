"""Поиск готовых cloud-конспектов в data/<course>/ по YAML-frontmatter type=konspekt."""
from __future__ import annotations

import re
from dataclasses import dataclass
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


def scan_konspekts(course_dir: Path) -> list[KonspektMeta]:
    """Вернуть все .md-файлы в course_dir с type: konspekt в frontmatter."""
    results: list[KonspektMeta] = []
    if not course_dir.is_dir():
        return results
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
