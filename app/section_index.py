"""Section Anchor Index: разбор konspekt-``.md`` на адресуемые разделы.

Два уровня контракта:

* :class:`ParsedSection` — результат разбора ОДНОГО md-файла, без провенанса
  (файл мог быть передан без исходника — например, живой конспект).
* :class:`IndexedSection` — тот же раздел, обогащённый путями исходника и
  vault-конспекта (см. :func:`build_section_index`).

Индексируем и открываем **konspekt-md** (не исходник) — см. обоснование в
``app/obsidian_export.py`` (frontmatter сдвигает строки для ``.md``-источников
без front-matter) и в ``app/ingestion_sections.py`` (``FlatMarkdownReader``
читает именно конспект как единый документ).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from app.ingestion_sections import _MARKDOWN_HEADING_RE, _parse_md_frontmatter
from app.knowledge_text import tokenize_filtered as _tokenize_ru_en

# ── Regex / нормализация заголовков ────────────────────────────────────
_SLUG_STRIP_RE = re.compile(r"[^\w\s-]+", re.UNICODE)
_SLUG_WS_RE = re.compile(r"[\s_]+")
_CODE_FENCE_RE = re.compile(r"^(```|~~~)")

_SKIP_HEADING_NORMALIZED = {"оглавление", "содержание", "toc", "table of contents"}
_MAIN_IDEA_HEADING_NORMALIZED = {"главная мысль", "main idea", "key idea", "основная мысль"}

_MIN_SECTION_CHARS = 15
_HEADING_MATCH_WEIGHT = 3.0
_BODY_MATCH_WEIGHT = 1.0


@dataclass(frozen=True)
class ParsedSection:
    """Раздел, разобранный из ОДНОГО md-файла — без провенанса исходника."""

    heading_text: str  # текст ПОСЛЕ '#', с эмодзи → Obsidian anchor
    slug: str  # github-slug → внутренний id/дедуп, НЕ Obsidian anchor
    level: int
    line_start: int  # 1-indexed в konspekt_md_abs → VS Code
    line_end: int
    text: str  # дословное тело раздела ИЗ КОНСПЕКТА (не из оригинала)
    # Текст ДО первого дочернего заголовка (интро секции). Скоринг идёт по own_text:
    # полный text родителя включает тела всех детей, поэтому родитель («📌 Ключевые темы»)
    # набирал скор ≥ любого своего H3 и deep-link вёл в пол-документа вместо точной подтемы.
    # kw_only: наследник IndexedSection добавляет обязательные позиционные поля.
    own_text: str = field(default="", kw_only=True)


@dataclass(frozen=True)
class IndexedSection(ParsedSection):
    """:class:`ParsedSection` + провенанс (исходник и vault-конспект)."""

    source_abs: Path  # исходник — ТОЛЬКО провенанс + CTA «подготовить конспект»
    konspekt_md_abs: Path  # vault .md — единственный файл, который и индексируем, и открываем
    concept: str | None = None


# ── Разбор заголовков / slug ────────────────────────────────────────────
def _github_slug(heading_text: str) -> str:
    s = heading_text.strip().lower()
    s = _SLUG_STRIP_RE.sub("", s)
    s = _SLUG_WS_RE.sub("-", s).strip("-")
    return s or "section"


def _normalize_heading(heading_text: str) -> str:
    s = heading_text.strip().lower()
    s = _SLUG_STRIP_RE.sub("", s)
    return _SLUG_WS_RE.sub(" ", s).strip()


def _is_ranking_noise(section: ParsedSection) -> bool:
    """H1-титул и «Оглавление» не участвуют в скоринге/поиске главной мысли."""
    if section.level == 1:
        return True
    return _normalize_heading(section.heading_text) in _SKIP_HEADING_NORMALIZED


# ── Разбор тела документа ────────────────────────────────────────────────
def _parse_body_sections(body: str, offset_lines: int) -> list[ParsedSection]:
    lines = body.splitlines()
    headings: list[tuple[int, str, int]] = []  # (level, heading_text, line_idx 0-based в body)
    in_fence = False
    for i, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        # ``` / ~~~ code-fence: строки вида "# комментарий" внутри примера кода — не заголовки
        # (иначе они обрезают тело содержащей секции, см. Findings — конспекты по программированию).
        if _CODE_FENCE_RE.match(stripped):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _MARKDOWN_HEADING_RE.match(stripped)
        if match:
            headings.append((len(match.group(1)), match.group(2).strip(), i))

    sections: list[ParsedSection] = []
    seen_slugs: dict[str, int] = {}
    for idx, (level, heading_text, line_idx) in enumerate(headings):
        # Тело секции = до заголовка того же/старшего уровня (H2 включает свои H3).
        boundary = len(lines)
        for next_level, _next_text, next_line_idx in headings[idx + 1 :]:
            if next_level <= level:
                boundary = next_line_idx
                break
        text = "\n".join(lines[line_idx + 1 : boundary]).strip()
        # own_text = интро до ПЕРВОГО заголовка любого уровня (дочернего) внутри секции.
        own_boundary = boundary
        if idx + 1 < len(headings) and headings[idx + 1][2] < boundary:
            own_boundary = headings[idx + 1][2]
        own_text = text if own_boundary == boundary else "\n".join(lines[line_idx + 1 : own_boundary]).strip()

        slug_base = _github_slug(heading_text)
        dup_count = seen_slugs.get(slug_base, 0)
        seen_slugs[slug_base] = dup_count + 1
        slug = slug_base if dup_count == 0 else f"{slug_base}-{dup_count}"

        sections.append(
            ParsedSection(
                heading_text=heading_text,
                slug=slug,
                level=level,
                line_start=offset_lines + line_idx + 1,
                line_end=offset_lines + boundary,
                text=text,
                own_text=own_text,
            )
        )
    return sections


def _parse_sections_from_text(raw: str) -> list[ParsedSection]:
    _, body = _parse_md_frontmatter(raw)
    offset_lines = raw[: len(raw) - len(body)].count("\n")
    return _parse_body_sections(body, offset_lines)


def parse_sections(md_abs: Path) -> list[ParsedSection]:
    """Разобрать konspekt-md на разделы (без провенанса исходника).

    Срезает YAML-frontmatter (как ``FlatMarkdownReader``), но запоминает
    строковый offset, чтобы ``line_start``/``line_end`` указывали на реальные
    строки файла (важно для VS Code deep-link).
    """
    raw = md_abs.read_text(encoding="utf-8", errors="replace")
    return _parse_sections_from_text(raw)


# ── build_section_index: провенанс + кэш ────────────────────────────────
_FRONTMATTER_SOURCE_RE = re.compile(r'^source:\s*"?(.*?)"?\s*$', re.MULTILINE)

# Кэш по (md-path -> (sha256 контента, [ParsedSection, ...])) — content-hash, а не (mtime, size):
# восстановление/копирование файла с сохранённым timestamp и тем же размером не должно отдавать
# устаревшие line_start/текст секции. Файл всё равно читаем один раз (для хэша), поэтому кэш
# экономит именно повторный regex-разбор при межрендерных повторах на один md-path.
_INDEX_CACHE: dict[Path, tuple[str, list[ParsedSection]]] = {}


def _content_signature(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _cached_parse_sections(md_abs: Path) -> list[ParsedSection]:
    raw = md_abs.read_text(encoding="utf-8", errors="replace")
    signature = _content_signature(raw)
    cached = _INDEX_CACHE.get(md_abs)
    if cached is not None and cached[0] == signature:
        return cached[1]
    parsed = _parse_sections_from_text(raw)
    _INDEX_CACHE[md_abs] = (signature, parsed)
    return parsed


def _source_from_frontmatter(md_abs: Path) -> Path | None:
    """Fallback: если ``rel_or_abs`` — это уже сам vault-md, достать исходник из frontmatter."""
    from app.obsidian_export import resolve_source

    try:
        head = md_abs.read_text(encoding="utf-8", errors="replace")[:2048]
    except OSError:
        return None
    match = _FRONTMATTER_SOURCE_RE.search(head)
    if not match:
        return None
    return resolve_source(match.group(1).strip())


def build_section_index(rel_or_abs: str | Path) -> list[IndexedSection]:
    """Построить индекс разделов для документа по его пути (относительному/абсолютному).

    Резолвит источник через ``resolve_source`` → ``vault_target``; если конспект ещё не
    создан (``.exists()`` ложно) — возвращает ``[]``. Если ``rel_or_abs`` сам оказался
    путём к vault-md (не резолвится как источник), пробуем достать исходник из
    frontmatter-поля ``source:`` этого конспекта.
    """
    from app.obsidian_export import resolve_source, vault_target

    source_abs = resolve_source(rel_or_abs)
    md_abs: Path | None = None
    if source_abs is not None:
        md_abs = vault_target(source_abs)
    else:
        candidate = Path(str(rel_or_abs))
        if candidate.exists() and candidate.suffix.lower() == ".md":
            resolved_source = _source_from_frontmatter(candidate)
            if resolved_source is not None:
                source_abs = resolved_source
                md_abs = candidate

    if source_abs is None or md_abs is None or not md_abs.exists():
        return []

    parsed_sections = _cached_parse_sections(md_abs)
    return [
        IndexedSection(
            heading_text=p.heading_text,
            slug=p.slug,
            level=p.level,
            line_start=p.line_start,
            line_end=p.line_end,
            text=p.text,
            own_text=p.own_text,
            source_abs=source_abs,
            konspekt_md_abs=md_abs,
        )
        for p in parsed_sections
    ]


# ── Скоринг / выбор раздела ──────────────────────────────────────────────
def _ranking_candidates(
    sections: list[ParsedSection] | list[IndexedSection],
) -> list[ParsedSection] | list[IndexedSection]:
    candidates = [s for s in sections if not _is_ranking_noise(s)] or list(sections)
    non_trivial = [s for s in candidates if len(s.text.strip()) >= _MIN_SECTION_CHARS]
    return non_trivial if non_trivial else candidates


def _ranked_by_overlap(
    candidates: list[ParsedSection] | list[IndexedSection],
    query_tokens: set[str],
) -> list[tuple[ParsedSection | IndexedSection, float]]:
    """``[(section, score), ...]`` по убыванию, только ``score > 0``.

    Тело скорится по ``own_text`` (интро секции, без тел детей) — иначе обзорный
    родитель всегда набирает ≥ любого своего подраздела и «съедает» точный H3.
    При равном скоре предпочитаем более глубокий уровень (лист точнее обзора),
    затем порядок в документе.
    """
    scored: list[tuple[ParsedSection | IndexedSection, float]] = []
    for section in candidates:
        heading_tokens = _tokenize_ru_en(section.heading_text)
        body_tokens = _tokenize_ru_en(section.own_text or section.text)
        score = (
            len(query_tokens & heading_tokens) * _HEADING_MATCH_WEIGHT
            + len(query_tokens & body_tokens) * _BODY_MATCH_WEIGHT
        )
        if score > 0:
            scored.append((section, score))
    scored.sort(key=lambda pair: (-pair[1], -pair[0].level, pair[0].line_start))
    return scored


def top_sections_for(
    sections: list[ParsedSection] | list[IndexedSection],
    query_text: str,
    *,
    k: int = 3,
) -> list[ParsedSection] | list[IndexedSection]:
    """До ``k`` самых релевантных разделов для ``query_text`` (score > 0, по убыванию).

    Концепт часто разобран в нескольких местах конспекта (тема, антипаттерны, термины) —
    одна «лучшая» секция теряет остальные. Пустой запрос → ``[]`` (нет сигнала для ранга).
    """
    if not sections or k <= 0:
        return []
    query_tokens = _tokenize_ru_en(query_text)
    if not query_tokens:
        return []
    ranked = _ranked_by_overlap(_ranking_candidates(sections), query_tokens)
    return [section for section, _score in ranked[:k]]


def best_section_for(
    sections: list[ParsedSection] | list[IndexedSection],
    query_text: str,
) -> ParsedSection | IndexedSection | None:
    """Найти наиболее релевантный раздел для ``query_text`` (весь контекст — одна строка).

    Скорит token-overlap с ``heading_text`` (вес выше) + ``own_text`` (интро секции,
    не полное тело — см. :func:`_ranked_by_overlap`), со стоп-листом RU+EN.
    Пропускает TOC/H1-титул и почти-пустые секции (если есть непустая альтернатива).

    При **пустом** запросе — фолбэк на первый непустой кандидат (нет сигнала для выбора).
    При **непустом** запросе, но нулевом overlap со всеми кандидатами — ``None`` (см. Findings):
    случайная первая секция без реального совпадения хуже честного whole-doc фолбэка у вызывающей
    стороны (``obs_uri``/``needs_konspekt`` в графе, whole-card в карточке).
    """
    if not sections:
        return None
    candidates = _ranking_candidates(sections)
    query_tokens = _tokenize_ru_en(query_text)
    if not query_tokens:
        return candidates[0]
    ranked = _ranked_by_overlap(candidates, query_tokens)
    return ranked[0][0] if ranked else None


# ── Роли разделов (опциональное обогащение) ─────────────────────────────
# Локальный шаблон конспекта (prompts/_impl.py) гарантирует только main_idea/terms/summary;
# богатые роли (pitfalls, check_questions, external_links, cheatsheet) есть у конспектов из
# внешнего pipeline (hometutor-studio). Поэтому роль — выводимая функция заголовка с честной
# деградацией (None), а НЕ поле контракта: row/payload не раздуваем.
_ROLE_BY_NORMALIZED_HEADING: dict[str, str] = {
    **{h: "main_idea" for h in _MAIN_IDEA_HEADING_NORMALIZED},
    "итоги и выводы": "summary",
    "итоги": "summary",
    "выводы": "summary",
    "summary": "summary",
    "conclusions": "summary",
    "важные термины и концепции": "terms",
    "термины": "terms",
    "глоссарий": "terms",
    "glossary": "terms",
    "key terms": "terms",
    "ошибки риски и антипаттерны": "pitfalls",
    "ошибки и антипаттерны": "pitfalls",
    "ошибки и риски": "pitfalls",
    "антипаттерны": "pitfalls",
    "pitfalls": "pitfalls",
    "antipatterns": "pitfalls",
    "common mistakes": "pitfalls",
    "контрольные вопросы": "check_questions",
    "вопросы для самопроверки": "check_questions",
    "check questions": "check_questions",
    "review questions": "check_questions",
    "self-check questions": "check_questions",
    "дополнительные материалы для глубокого изучения": "external_links",
    "дополнительные материалы": "external_links",
    "полезные ссылки": "external_links",
    "further reading": "external_links",
    "additional materials": "external_links",
    "resources": "external_links",
    "мини-шпаргалка": "cheatsheet",
    "шпаргалка": "cheatsheet",
    "cheat sheet": "cheatsheet",
    "cheatsheet": "cheatsheet",
    # A1 (konspekt_quality_plan): качество конспекта из cloud pipeline
    "рубрика качества конспекта": "quality_rubric",
    "рубрика качества": "quality_rubric",
    "quality rubric": "quality_rubric",
    # C3 / A1: for visual distinction of accuracy check in rubric
    "проверка точности": "accuracy_check",
}


def section_role(section: ParsedSection) -> str | None:
    """Роль раздела по нормализованному заголовку (эмодзи/пунктуация уже срезаны) или ``None``."""
    return _ROLE_BY_NORMALIZED_HEADING.get(_normalize_heading(section.heading_text))


def sections_by_role(
    sections: list[ParsedSection] | list[IndexedSection],
) -> dict[str, ParsedSection | IndexedSection]:
    """``{role: первая секция этой роли}`` — вход для deep-study промпта и сшивки."""
    out: dict[str, ParsedSection | IndexedSection] = {}
    for section in sections:
        role = section_role(section)
        if role is not None and role not in out:
            out[role] = section
    return out


# C1: грейд фабрики по фактическим ролям (derived, не frontmatter)
_BASE_ROLES = {"main_idea", "terms", "summary"}


def get_konspekt_grade(sections: list[ParsedSection] | list[IndexedSection]) -> str:
    """'базовый' / 'богатый' / 'богатый + рубрика' по наличию ролей."""
    roles = set(sections_by_role(sections).keys())
    if not roles:
        return "базовый"
    has_rubric = "quality_rubric" in roles
    is_rich = len(roles - _BASE_ROLES) > 0
    if has_rubric:
        return "богатый + рубрика"
    if is_rich:
        return "богатый"
    return "базовый"


def heading_repeats_in_document(md_abs: Path, heading_text: str) -> bool:
    """``True``, если заголовок встречается в документе более одного раза.

    Obsidian-якорь открывает **первый** одноимённый heading — при дублях UI честно
    подписывает «VS Code точнее». Смотрим весь документ (не только собранные rows):
    дубль опасен, даже когда в корзине лежит лишь одна из копий.
    """
    try:
        sections = _cached_parse_sections(md_abs)
    except OSError:
        return False
    return sum(1 for s in sections if s.heading_text == heading_text) > 1


def main_idea_section(
    sections: list[ParsedSection] | list[IndexedSection],
) -> ParsedSection | IndexedSection | None:
    """Найти H2 «Главная мысль»; иначе — первую содержательную H2 после title/TOC."""
    for section in sections:
        if section.level == 2 and _normalize_heading(section.heading_text) in _MAIN_IDEA_HEADING_NORMALIZED:
            return section
    for section in sections:
        if section.level == 2 and not _is_ranking_noise(section) and section.text.strip():
            return section
    return sections[0] if sections else None


# ── JSON-safe корзина («Живой конспект») ────────────────────────────────
def section_to_row(section: IndexedSection) -> dict[str, Any]:
    """``IndexedSection`` → dict из строк, безопасный для ``json.dumps``."""
    return {
        "source_abs": str(section.source_abs),
        "konspekt_md_abs": str(section.konspekt_md_abs),
        "heading_text": section.heading_text,
        "slug": section.slug,
        "level": section.level,
        "line_start": section.line_start,
        "line_end": section.line_end,
        "text": section.text,
        "own_text": section.own_text,
        "concept": section.concept,
    }


def row_to_section(row: Mapping[str, Any]) -> IndexedSection:
    """Обратное преобразование к :func:`section_to_row`."""
    return IndexedSection(
        heading_text=str(row.get("heading_text") or ""),
        slug=str(row.get("slug") or ""),
        level=int(row.get("level") or 0),
        line_start=int(row.get("line_start") or 0),
        line_end=int(row.get("line_end") or 0),
        text=str(row.get("text") or ""),
        # Ряды, сохранённые до появления own_text, отдают "" — скоринг падает на text.
        own_text=str(row.get("own_text") or ""),
        source_abs=Path(str(row.get("source_abs") or "")),
        konspekt_md_abs=Path(str(row.get("konspekt_md_abs") or "")),
        concept=row.get("concept"),
    )
