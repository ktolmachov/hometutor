"""Конвертация исходных документов (txt/md) в красивый Obsidian-ready Markdown-конспект.

Ленивая, по запросу из UI (кнопка «Подготовить для Obsidian»). Результат пишется в
``DATA_DIR/"vault"`` зеркаля структуру папок источника, с расширением ``.md``.

Кэш по ``sha256`` содержимого источника (хранится в YAML-frontmatter готового файла):
неизменённый файл повторно через LLM не прогоняется.

LLM — локальная (LM Studio через :func:`app.provider.get_obsidian_export_llm`); сетевых
вызовов в облако нет. Для большого транскрипта применяется map → reduce → compose,
чтобы каждый вызов оставался в пределах контекста локальной модели.

Стиль итогового конспекта повторяет эталон ``summary_01-ai-driven-design.md``:
H1 с эмодзи, курсивный интро, оглавление с якорями, «Главная мысль», «Ключевые темы»
с подсекциями ``### 🔹``, «Важные термины», «Итоги и выводы».
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from app.config import DATA_DIR, get_settings
from app.llm_resilience import complete_with_resilience
from app.prompts import (
    OBSIDIAN_EXPORT_COMPOSE_PROMPT,
    OBSIDIAN_EXPORT_MAP_PROMPT,
    OBSIDIAN_EXPORT_MERGE_PROMPT,
)
from app.provider import get_obsidian_export_llm

logger = logging.getLogger(__name__)

# Константы-fallback (переопределяются через config при первом обращении к _export_settings())
MAP_CHUNK_CHARS = 6000
MAP_OVERLAP_CHARS = 300
REDUCE_GROUP_CHARS = 9000
COMPOSE_INPUT_LIMIT = 12000


def _export_settings() -> tuple[int, int, int, int]:
    """Вернуть (map_chunk, map_overlap, compose_limit, compose_max_tokens) из настроек."""
    try:
        s = get_settings()
        return (
            s.obsidian_export_map_chunk_chars,
            s.obsidian_export_map_overlap_chars,
            s.obsidian_export_compose_input_limit,
            s.obsidian_export_compose_max_tokens,
        )
    except Exception:  # noqa: BLE001 - invalid settings degrade to conservative export limits.
        return MAP_CHUNK_CHARS, MAP_OVERLAP_CHARS, COMPOSE_INPUT_LIMIT, 4096


def _get_llm() -> Any:
    """Выбрать LLM для экспорта с увеличенным таймаутом."""
    return get_obsidian_export_llm()

ProgressFn = Callable[[str, int, int], None]


@dataclass(frozen=True)
class ObsidianExportResult:
    """Итог конвертации одного документа."""

    source_rel: str
    source_abs: Path
    target_abs: Path
    vault_rel: str
    action: str  # "converted" | "copied" | "cached" | "skipped-empty"


# ── Пути / vault ───────────────────────────────────────────────────────
def vault_root() -> Path:
    """Папка назначения для сгенерированных конспектов.

    По умолчанию ``data/`` (= ``DATA_DIR``) — конспект ложится рядом с источником
    и автоматически попадает в ингест/RAG/KG.
    Переопределяется через ``OBSIDIAN_VAULT_SUBDIR`` в .env.
    """
    try:
        subdir = get_settings().obsidian_vault_subdir
    except Exception:  # noqa: BLE001 - export remains usable with the default vault subdirectory.
        subdir = "data"
    return (DATA_DIR.parent / subdir).resolve()


def corpus_root() -> Path:
    """Корень исходного корпуса, относительно которого заданы ``relative_path``."""
    return DATA_DIR


def resolve_source(rel_or_abs: str | Path) -> Path | None:
    """Найти абсолютный путь к источнику по относительному (или абсолютному) пути.

    Пробуем несколько корней, т.к. ``relative_path`` в индексе может быть задан
    относительно ``DATA_DIR`` или ``DATA_DIR/"docs"``.
    """
    raw = Path(str(rel_or_abs))
    if raw.is_absolute() and raw.exists():
        return raw
    rel = str(rel_or_abs).replace("\\", "/").lstrip("/")
    for base in (corpus_root(), corpus_root() / "docs"):
        cand = (base / rel).resolve()
        if cand.exists():
            return cand
    return None


def vault_target(source_abs: Path) -> Path:
    """Путь к ``.md`` внутри vault, зеркалящий положение источника в корпусе."""
    source_abs = source_abs.resolve()
    for base in (corpus_root() / "docs", corpus_root()):
        try:
            rel = source_abs.relative_to(base.resolve())
            break
        except ValueError:
            continue
    else:
        rel = Path(source_abs.name)
    return (vault_root() / rel).with_suffix(".md")


def vault_obsidian_root() -> Path:
    """Корень зарегистрированного Obsidian-vault (содержит .obsidian/).

    vault_root() — папка конспектов внутри vault.
    vault_obsidian_root() — родительский vault, относительно которого строится file= URI.
    """
    vr = vault_root()
    # Ищем .obsidian/ вверх по дереву от vault_root
    for parent in [vr, *vr.parents]:
        if (parent / ".obsidian").is_dir():
            return parent
    return vr  # fallback: считаем что vault_root и есть корень


def vault_rel_str(target_abs: Path) -> str:
    """Путь ``.md`` относительно корня Obsidian-vault (для ``file=`` в URI)."""
    try:
        return str(target_abs.resolve().relative_to(vault_obsidian_root().resolve())).replace("\\", "/")
    except ValueError:
        return target_abs.name


def obsidian_uri(target_abs: Path) -> str:
    """Сформировать ``obsidian://`` URI для открытия файла.

    Предпочитает ``vault=<name>&file=<rel>`` (работает без регистрации пути),
    падает обратно на ``path=<abs>`` если ``OBSIDIAN_VAULT_NAME`` не задан.
    """
    try:
        vault_name = get_settings().obsidian_vault_name
    except Exception:  # noqa: BLE001 - URI generation can fall back when vault metadata is unavailable.
        vault_name = None

    if vault_name:
        # file= требует прямые слеши (стандарт Obsidian URI)
        rel = vault_rel_str(target_abs)  # уже содержит "/"
        return (
            "obsidian://open?vault="
            + _pct_encode(vault_name)
            + "&file="
            + _pct_encode(rel)
        )
    # path= требует обратные слеши на Windows
    abs_str = str(target_abs).replace("/", "\\")
    return "obsidian://open?path=" + _pct_encode(abs_str)


def _pct_encode(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")


# ── Хеш / кэш ──────────────────────────────────────────────────────────
def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_FRONTMATTER_HASH_RE = re.compile(r"^source_sha256:\s*([0-9a-f]{64})\s*$", re.MULTILINE)


def _existing_source_hash(target_abs: Path) -> str | None:
    """Прочитать ``source_sha256`` из frontmatter уже сгенерированного файла."""
    if not target_abs.exists():
        return None
    try:
        head = target_abs.read_text(encoding="utf-8")[:2048]
    except OSError:
        return None
    m = _FRONTMATTER_HASH_RE.search(head)
    return m.group(1) if m else None


def _notes_cache_path(target_abs: Path) -> Path:
    """Путь к промежуточному reduce-кэшу рядом с итоговым Markdown."""
    return target_abs.with_suffix(".notes_cache.yaml")


def _load_notes_cache(target_abs: Path, source_hash: str) -> str | None:
    """Вернуть сохранённый ``consolidated``, если он соответствует текущему source hash."""
    cache_path = _notes_cache_path(target_abs)
    if not cache_path.exists():
        return None
    try:
        raw = yaml.safe_load(cache_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("source_sha256") != source_hash:
        return None
    consolidated = raw.get("consolidated")
    return consolidated if isinstance(consolidated, str) else None


def _save_notes_cache(target_abs: Path, source_hash: str, consolidated: str) -> None:
    """Сохранить reduce-результат для retry после падения compose."""
    cache_path = _notes_cache_path(target_abs)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_sha256": source_hash,
        "consolidated": consolidated,
    }
    cache_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _delete_notes_cache(target_abs: Path) -> None:
    """Удалить промежуточный кэш после успешной записи итогового файла."""
    try:
        _notes_cache_path(target_abs).unlink(missing_ok=True)
    except OSError:
        logger.debug("Не удалось удалить Obsidian notes cache: %s", _notes_cache_path(target_abs))


# ── Промпты ────────────────────────────────────────────────────────────
_MAP_PROMPT = OBSIDIAN_EXPORT_MAP_PROMPT
_MERGE_PROMPT = OBSIDIAN_EXPORT_MERGE_PROMPT
_COMPOSE_PROMPT = OBSIDIAN_EXPORT_COMPOSE_PROMPT


# ── LLM-вызов ──────────────────────────────────────────────────────────
def _complete(llm: Any, prompt: str, *, stage: str, **kwargs: Any) -> str:
    response = complete_with_resilience(llm, prompt, stage=stage, **kwargs)
    text = getattr(response, "text", None)
    return (text if text is not None else str(response)).strip()


def _strip_md_fence(text: str) -> str:
    """Снять обрамляющий ```markdown ... ``` если модель его всё же добавила."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n", "", t)
        if t.endswith("```"):
            t = t[: -3]
    return t.strip()


# ── Чанкинг ────────────────────────────────────────────────────────────
def _split_chunks(text: str, size: int = MAP_CHUNK_CHARS, overlap: int = MAP_OVERLAP_CHARS) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        # стараемся резать по границе предложения, чтобы не рвать мысль
        if end < n:
            window = text.rfind(". ", start + size // 2, end)
            if window != -1:
                end = window + 1
        chunks.append(text[start:end].strip())
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def _group_by_chars(items: Iterable[str], limit: int) -> list[list[str]]:
    groups: list[list[str]] = []
    cur: list[str] = []
    cur_len = 0
    for it in items:
        if cur and cur_len + len(it) > limit:
            groups.append(cur)
            cur, cur_len = [], 0
        cur.append(it)
        cur_len += len(it)
    if cur:
        groups.append(cur)
    return groups


# ── Reduce тезисов до объёма, влезающего в compose ─────────────────────
def _reduce_notes(llm: Any, notes: list[str], progress: ProgressFn | None, compose_limit: int | None = None) -> str:
    """Иерархически слить заметки фрагментов, пока не влезут в один compose-вызов."""
    limit = compose_limit if compose_limit is not None else COMPOSE_INPUT_LIMIT
    level = 0
    while True:
        combined = "\n\n".join(notes)
        if len(notes) == 1 or len(combined) <= limit:
            return combined
        groups = _group_by_chars(notes, REDUCE_GROUP_CHARS)
        if len(groups) >= len(notes):  # защита от бесконечного цикла
            return combined[:limit]
        merged: list[str] = []
        for i, group in enumerate(groups):
            if progress:
                progress("merge", i + 1, len(groups))
            merged.append(
                _complete(
                    llm,
                    _MERGE_PROMPT.format(notes="\n\n".join(group)),
                    stage=f"obsidian.export.merge.l{level}",
                )
            )
        notes = merged
        level += 1


# ── Заголовок из имени файла ───────────────────────────────────────────
def _title_from_name(source_abs: Path) -> str:
    stem = source_abs.stem
    # частый артефакт исходников: хвост "ts" перед .txt («…агентовts»)
    stem = re.sub(r"ts$", "", stem).strip()
    return stem or source_abs.stem


def _frontmatter(source_rel: str, source_hash: str) -> str:
    return (
        "---\n"
        f'source: "{source_rel}"\n'
        f"source_sha256: {source_hash}\n"
        f"generated: {date.today().isoformat()}\n"
        "type: konspekt\n"
        "tags: [конспект, lecture]\n"
        "---\n\n"
    )


# ── Главный публичный API ──────────────────────────────────────────────
def to_obsidian_markdown(
    rel_or_abs: str | Path,
    *,
    force: bool = False,
    progress: ProgressFn | None = None,
) -> ObsidianExportResult:
    """Сконвертировать документ в Obsidian-ready ``.md`` (или вернуть из кэша).

    :param rel_or_abs: путь к источнику (относительный к корпусу или абсолютный).
    :param force: пересоздать, даже если содержимое не менялось.
    :param progress: колбэк ``(stage, current, total)`` для прогресс-бара UI.
    """
    source_abs = resolve_source(rel_or_abs)
    if source_abs is None:
        raise FileNotFoundError(f"Источник не найден: {rel_or_abs}")

    target_abs = vault_target(source_abs)
    source_rel = str(rel_or_abs).replace("\\", "/")
    suffix = source_abs.suffix.lower()

    raw = source_abs.read_text(encoding="utf-8", errors="replace")
    source_hash = _sha256(raw)

    if not force and _existing_source_hash(target_abs) == source_hash:
        return ObsidianExportResult(
            source_rel, source_abs, target_abs, vault_rel_str(target_abs), "cached"
        )

    target_abs.parent.mkdir(parents=True, exist_ok=True)

    if not raw.strip():
        target_abs.write_text(_frontmatter(source_rel, source_hash) + "*Пустой документ.*\n", encoding="utf-8")
        _delete_notes_cache(target_abs)
        return ObsidianExportResult(
            source_rel, source_abs, target_abs, vault_rel_str(target_abs), "skipped-empty"
        )

    if suffix in (".md", ".markdown"):
        # уже markdown — кладём как есть, только добавляем frontmatter с хешем
        body = raw if raw.lstrip().startswith("---") else _frontmatter(source_rel, source_hash) + raw
        target_abs.write_text(body, encoding="utf-8")
        _delete_notes_cache(target_abs)
        return ObsidianExportResult(
            source_rel, source_abs, target_abs, vault_rel_str(target_abs), "copied"
        )

    # .txt и прочий plain text → map → reduce → compose
    map_chunk, map_overlap, compose_limit, compose_max_tokens = _export_settings()
    llm = _get_llm()
    consolidated = _load_notes_cache(target_abs, source_hash)
    if consolidated is None:
        chunks = _split_chunks(raw, size=map_chunk, overlap=map_overlap)
        notes: list[str] = []
        for i, chunk in enumerate(chunks):
            if progress:
                progress("map", i + 1, len(chunks))
            notes.append(
                _complete(
                    llm,
                    _MAP_PROMPT.format(idx=i + 1, total=len(chunks), chunk=chunk),
                    stage="obsidian.export.map",
                )
            )

        consolidated = _reduce_notes(llm, notes, progress, compose_limit=compose_limit)
        _save_notes_cache(target_abs, source_hash, consolidated)

    if progress:
        progress("compose", 1, 1)
    body = _strip_md_fence(
        _complete(
            llm,
            _COMPOSE_PROMPT.format(title=_title_from_name(source_abs), notes=consolidated),
            stage="obsidian.export.compose",
            max_tokens=compose_max_tokens,
        )
    )

    target_abs.write_text(_frontmatter(source_rel, source_hash) + body + "\n", encoding="utf-8")
    _delete_notes_cache(target_abs)
    return ObsidianExportResult(
        source_rel, source_abs, target_abs, vault_rel_str(target_abs), "converted"
    )
