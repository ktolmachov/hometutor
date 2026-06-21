"""Learner-facing corpus readiness snapshot for files under ``data/`` (US-2.4).

Классы: text-ready / needs OCR / problematic + один primary next action.
Диагностика не запускает OCR-ingest (см. US-2.3).
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from app.config import Settings
from app.ingestion_content_state import build_file_manifest

# Синхронизировано с ``app.ingestion._DOC_IMAGE_EXTS``.
_CORPUS_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"})
_TEXT_LIKE_EXTS = frozenset({".txt", ".md", ".html"})


def _product_criteria() -> dict[str, str]:
    return {
        "text_ready": (
            "Достаточно извлекаемого текста для обычного индекса без отдельного OCR-шага."
        ),
        "needs_ocr": (
            "Мало текста или формат требует OCR/Docling (US-2.3); здесь только подсказка, ingest не запускается."
        ),
        "extraction_failed": (
            "Текст не извлечён: пустой/повреждённый файл, ошибка чтения или кодировки, сбой разбора PDF/DOCX."
        ),
        "unsupported_format": (
            "Расширение не покрыто явной диагностикой готовности; проверьте поддержку в пайплайне индексации."
        ),
        "problematic": (
            "Сводно: extraction_failed + unsupported_format (совместимость отображения US-2.4)."
        ),
    }


def _pdf_native_char_sample(path: Path, *, max_pages: int = 5) -> int | None:
    """Возвращает длину текста (первые страницы) или ``None`` если PDF не прочитан."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages[:max_pages]:
            parts.append(page.extract_text() or "")
        return len("".join(parts).strip())
    except Exception:  # noqa: BLE001 - PDF parse failure returns None char count
        return None


def _classify_plain_text(path: Path, *, ext: str) -> tuple[str, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return "extraction_failed", f"Не удалось прочитать файл: {exc}"
    if not raw.strip():
        return "extraction_failed", "Файл пустой или содержит только пробелы."
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-1")
        except UnicodeDecodeError:
            return "extraction_failed", "Не удалось декодировать текст (повреждённая кодировка)."
    snippet = text.strip()
    if len(snippet) < 8:
        return "extraction_failed", "Слишком мало текста для надёжной индексации."
    if ext in _TEXT_LIKE_EXTS:
        return "text_ready", "Текстовый формат с достаточным содержимым."
    return "text_ready", "Файл успешно прочитан как текст."


def _classify_docx(path: Path) -> tuple[str, str]:
    if not zipfile.is_zipfile(path):
        return "extraction_failed", "DOCX не является корректным ZIP-архивом."
    try:
        if path.stat().st_size <= 0:
            return "extraction_failed", "Пустой DOCX."
    except OSError as exc:
        return "extraction_failed", f"Не удалось прочитать файл: {exc}"
    return "text_ready", "DOCX структурно валиден (извлечение текста при индексации)."


def _file_next_action(*, bucket: str, docling_enabled: bool) -> str:
    if bucket == "text_ready":
        return ""
    if bucket == "needs_ocr":
        if docling_enabled:
            return "Запустите переиндексацию с включённым Docling/OCR (US-2.3)."
        return (
            "Включите Docling/OCR в настройках или дайте текстовую копию, затем переиндексируйте."
        )
    if bucket == "extraction_failed":
        return "Удалите или замените файл; проверьте целостность и кодировку перед индексацией."
    if bucket == "unsupported_format":
        return "Конвертируйте в .pdf/.txt/.md/.docx/.html или удалите файл из data/."
    return ""


def _pick_primary_action(
    *,
    counts: dict[str, int],
    docling_enabled: bool,
    supported_total: int,
) -> str:
    if supported_total <= 0:
        return (
            "Добавьте поддерживаемые документы в папку data/, затем выполните переиндексацию."
        )
    if counts["problematic"] > 0:
        return (
            "Удалите или замените проблемные файлы в data/, затем переиндексируйте базу."
        )
    if counts["needs_ocr"] > 0 and not docling_enabled:
        return (
            "Включите Docling/OCR в настройках (или замените сканы текстовыми версиями), "
            "затем переиндексируйте — см. US-2.3."
        )
    if counts["needs_ocr"] > 0 and docling_enabled:
        return (
            "Запустите переиндексацию: файлы с малым текстом и изображения пройдут через OCR/Docling (US-2.3)."
        )
    return "Запустите переиндексацию и после её завершения задайте первый вопрос."


def build_source_readiness_summary(
    data_dir: Path,
    settings: Settings,
) -> dict[str, Any]:
    """Сводка по поддерживаемым файлам в ``data_dir`` без записи в индекс."""
    from app import ingestion as ing

    if settings.home_rag_e2e_offline:
        return {
            "criteria": _product_criteria(),
            "counts": {
                "text_ready": 1,
                "needs_ocr": 0,
                "extraction_failed": 0,
                "unsupported_format": 0,
                "problematic": 0,
            },
            "readiness_score": 1.0,
            "files": [
                {
                    "path": "e2e-offline-stub.md",
                    "bucket": "text_ready",
                    "reason": "Режим E2E offline — заглушка диагностики.",
                    "next_action": "",
                }
            ],
            "primary_next_action": "Продолжите сценарий E2E — диагностика корпуса отключена.",
            "ingest_docling_enabled": bool(settings.ingest_docling_enabled),
            "us_2_3_note": "Диагностика не заменяет OCR-ingest; связка с US-2.3.",
            "supported_files_total": 1,
        }

    # Диагностика показывает и изображения даже при выключенном Docling — они попадут в индекс только после OCR-пути.
    exts = set(ing._DOC_BASE_EXTS) | set(ing._DOC_IMAGE_EXTS)
    supported = frozenset(exts)
    manifest = build_file_manifest(data_dir, supported)
    files_meta = manifest.get("files") or {}
    min_pdf_chars = int(getattr(settings, "ingest_docling_min_native_text_chars", 80) or 80)

    rows: list[dict[str, str]] = []
    docling_on = bool(settings.ingest_docling_enabled)
    counts = {"text_ready": 0, "needs_ocr": 0, "extraction_failed": 0, "unsupported_format": 0}

    for rel in sorted(files_meta.keys()):
        info = files_meta.get(rel) or {}
        ext = str(info.get("ext") or Path(rel).suffix.lower())
        path = (data_dir / rel).resolve()
        try:
            size = int(info.get("size") or path.stat().st_size)
        except OSError:
            row = {
                "path": rel,
                "bucket": "extraction_failed",
                "reason": "Файл недоступен для чтения.",
                "next_action": _file_next_action(bucket="extraction_failed", docling_enabled=docling_on),
            }
            rows.append(row)
            counts["extraction_failed"] += 1
            continue

        if size <= 0:
            row = {
                "path": rel,
                "bucket": "extraction_failed",
                "reason": "Нулевой размер файла.",
                "next_action": _file_next_action(bucket="extraction_failed", docling_enabled=docling_on),
            }
            rows.append(row)
            counts["extraction_failed"] += 1
            continue

        bucket: str
        reason: str

        if ext in _CORPUS_IMAGE_EXTS:
            bucket, reason = (
                "needs_ocr",
                "Растровое изображение: для попадания в индекс нужен OCR/Docling-путь (US-2.3).",
            )
        elif ext == ".pdf":
            pdf_chars = _pdf_native_char_sample(path)
            if pdf_chars is None:
                bucket, reason = (
                    "extraction_failed",
                    "PDF не удалось прочитать (повреждён или нет поддержки pypdf).",
                )
            elif pdf_chars < min_pdf_chars:
                bucket, reason = (
                    "needs_ocr",
                    f"Мало извлекаемого текста ({pdf_chars} символов < порога {min_pdf_chars}); "
                    "ожидается OCR/Docling.",
                )
            else:
                bucket, reason = "text_ready", "PDF с достаточным текстовым слоем."
        elif ext == ".docx":
            bucket, reason = _classify_docx(path)
        elif ext in _TEXT_LIKE_EXTS:
            bucket, reason = _classify_plain_text(path, ext=ext)
        else:
            bucket, reason = (
                "unsupported_format",
                f"Формат {ext} не разбит на отдельные правила диагностики; убедитесь, что индексатор его поддерживает.",
            )

        rows.append(
            {
                "path": rel,
                "bucket": bucket,
                "reason": reason,
                "next_action": _file_next_action(bucket=bucket, docling_enabled=docling_on),
            }
        )
        counts[bucket] += 1

    counts["problematic"] = counts["extraction_failed"] + counts["unsupported_format"]
    total_files = len(rows)
    readiness_score = float(counts["text_ready"] / total_files) if total_files else 0.0

    primary = _pick_primary_action(
        counts=counts,
        docling_enabled=bool(settings.ingest_docling_enabled),
        supported_total=len(rows),
    )

    return {
        "criteria": _product_criteria(),
        "counts": counts,
        "readiness_score": readiness_score,
        "files": rows,
        "primary_next_action": primary,
        "ingest_docling_enabled": bool(settings.ingest_docling_enabled),
        "us_2_3_note": (
            "Диагностика указывает, где нужен OCR/Docling, но сама индексацию не выполняет (US-2.3)."
        ),
        "supported_files_total": len(rows),
    }
