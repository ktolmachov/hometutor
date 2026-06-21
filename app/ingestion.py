"""Document load, parse, and enrich path; index build orchestration lives in ``app.ingestion_loader``."""

import concurrent.futures
from pathlib import Path

from llama_index.core import Document, SimpleDirectoryReader

from app.config import CHROMA_DIR, DATA_DIR, get_settings
from app.ingestion_chunk_metadata import (
    _configure_document_for_metadata_aware_split,
    _slim_metadata_for_summary,
)
from app.ingestion_enrichment import _enrich_documents
from app.ingestion_extracted_cache import (
    _deserialize_document_from_cache,
    _document_cache_key,
    _load_extracted_document_cache,
    _save_extracted_document_cache,
)
from app.ingestion_metadata import (
    build_document_summary_with_cost,
    enrich_document_metadata_with_cost,
)
from app.ingestion_sections import FlatMarkdownReader, HTMLTextReader, _expand_structured_documents
from app.ingestion_support import (
    _ingestion_status,
    _print_ingest_progress,
    _print_ingest_run_summary,
    aggregate_page_range_for_doc_group,
    build_ingest_run_summary,
    format_ingest_progress_line,
    get_ingestion_status,
    normalize_page_range_string,
)
from app.logging_config import setup_logging

logger = setup_logging()
STAGING_COLLECTION_SEPARATOR = "__staging__"
INGEST_CACHE_PATH = CHROMA_DIR / "ingest_embed_cache.json"
_DOC_BASE_EXTS = frozenset({".pdf", ".txt", ".md", ".docx", ".html"})
# Растровые страницы / фото — только при INGEST_DOCLING_ENABLED (см. get_doc_supported_exts).
_DOC_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"})

# Обратная совместимость: базовые расширения без изображений.
_DOC_SUPPORTED_EXTS = _DOC_BASE_EXTS


def get_doc_supported_exts() -> frozenset[str]:
    settings = get_settings()
    exts = set(_DOC_BASE_EXTS)
    if settings.ingest_docling_enabled:
        exts |= set(_DOC_IMAGE_EXTS)
    return frozenset(exts)


def _stamp_source_extraction(docs: list[Document], route: str) -> None:
    for doc in docs:
        md = dict(doc.metadata or {})
        md["source_extraction"] = route
        doc.metadata = md


def _native_pdf_text_chars(docs: list[Document]) -> int:
    return sum(len((d.text or "").strip()) for d in docs)


def _load_via_docling(file_path: Path) -> list[Document]:
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise RuntimeError(
            "ingest_docling_enabled is True but docling is not installed; pip install docling"
        ) from exc
    converter = DocumentConverter()
    result = converter.convert(str(file_path.resolve()))
    text = result.document.export_to_markdown() or ""
    return [
        Document(
            text=text,
            metadata={
                "file_path": str(file_path.resolve()),
                "source_extraction": "docling_ocr",
            },
        )
    ]


def _load_one_file(file_path: Path) -> list[Document]:
    settings = get_settings()
    ext = file_path.suffix.lower()
    if settings.ingest_docling_enabled and ext in _DOC_IMAGE_EXTS:
        return _load_via_docling(file_path)
    reader = SimpleDirectoryReader(
        input_files=[str(file_path)],
        filename_as_id=True,
        file_extractor={
            ".html": HTMLTextReader(),
            ".md": FlatMarkdownReader(),
        },
    )
    docs = reader.load_data()
    if settings.ingest_docling_enabled and ext == ".pdf":
        if _native_pdf_text_chars(docs) < settings.ingest_docling_min_native_text_chars:
            return _load_via_docling(file_path)
        _stamp_source_extraction(docs, "native_text")
    return docs


def _infer_doc_kind(relative_path: Path) -> str:
    parts = [part.lower() for part in relative_path.parts]
    file_name = relative_path.name.lower()
    joined = " ".join(parts)
    if "homework" in joined or "assignment" in joined or "hw" in file_name:
        return "homework"
    if "seminar" in joined:
        return "seminar"
    if "lecture" in joined or "lectures" in joined:
        return "lecture"
    if "manual" in joined or "guide" in joined:
        return "manual"
    return "document"


def _build_contextualized_text(doc: Document) -> str:
    metadata = doc.metadata or {}
    original_text = (doc.text or "").strip()
    if not original_text:
        return original_text

    title = metadata.get("title") or metadata.get("html_title") or metadata.get("file_name") or "Untitled"
    section_path = metadata.get("section_path") or metadata.get("structural_path") or title
    doc_kind = metadata.get("doc_type") or metadata.get("doc_kind") or "document"
    difficulty = metadata.get("difficulty") or "unknown"
    topic = metadata.get("topic") or ""

    header_lines = [
        f"Document: {title}",
        f"Section: {section_path}",
        f"Type: {doc_kind}",
        f"Difficulty: {difficulty}",
    ]
    if topic:
        header_lines.append(f"Topic: {topic}")
    page_range = metadata.get("page_range")
    if page_range:
        header_lines.append(f"Pages: {page_range}")

    return "\n".join(header_lines) + "\n\nChunk:\n" + original_text


def _apply_contextualized_chunks(documents: list[Document]) -> list[Document]:
    contextualized: list[Document] = []
    for doc in documents:
        metadata = dict(doc.metadata or {})
        contextualized.append(
            Document(
                text=_build_contextualized_text(doc),
                metadata=metadata,
            )
        )
    return contextualized


def _add_metadata(documents):
    data_dir = DATA_DIR
    for doc in documents:
        file_path_raw = doc.metadata.get("file_path", "")
        file_path = Path(file_path_raw)

        try:
            relative_path = file_path.relative_to(data_dir)
        except Exception:  # noqa: BLE001 - non-data paths fall back to filename grouping.
            relative_path = Path(file_path.name)

        folder_rel = (
            relative_path.parent.as_posix()
            if relative_path.parent != Path(".")
            else ""
        )
        folder_name = file_path.parent.name if file_path.parent else ""

        doc_id = relative_path.as_posix()

        doc.metadata["file_name"] = file_path.name
        doc.metadata["ext"] = file_path.suffix.lower()
        doc.metadata["folder_name"] = folder_name
        doc.metadata["folder_rel"] = folder_rel
        doc.metadata["relative_path"] = relative_path.as_posix()
        # Новые унифицированные поля под фильтры Итерации 11
        doc.metadata["doc_id"] = doc_id
        doc.metadata["folder"] = folder_rel
        doc.metadata["file"] = file_path.name
        path_parts = list(relative_path.parts[:-1])
        doc.metadata["course"] = path_parts[0] if len(path_parts) >= 1 else ""
        doc.metadata["module"] = path_parts[1] if len(path_parts) >= 2 else ""
        doc.metadata["lecture"] = path_parts[2] if len(path_parts) >= 3 else file_path.stem
        doc.metadata["doc_kind"] = _infer_doc_kind(relative_path)
        # Override doc_kind from YAML front-matter for konspekt files.
        # FlatMarkdownReader stores front-matter as md_<key> in metadata.
        _md_type = str(doc.metadata.get("md_type", "")).strip()
        if _md_type == "konspekt":
            _md_tags_raw = str(doc.metadata.get("md_tags", ""))
            _md_tags = [t.strip() for t in _md_tags_raw.split(",") if t.strip()]
            _kind_map = {"lecture": "lecture", "seminar": "seminar",
                         "homework": "homework", "manual": "manual"}
            doc.metadata["doc_kind"] = next(
                (_kind_map[t] for t in _md_tags if t in _kind_map),
                "lecture",  # default for konspekt
            )
        if "section_path" not in doc.metadata:
            fallback_section = doc.metadata.get("html_title") or doc.metadata.get("title") or file_path.stem
            doc.metadata["section_title"] = doc.metadata.get("section_title") or fallback_section
            doc.metadata["section_level"] = doc.metadata.get("section_level", 0)
            doc.metadata["section_path"] = doc.metadata.get("section_path") or str(fallback_section)
            doc.metadata["structural_path"] = doc.metadata.get("structural_path") or str(fallback_section)

        pr = normalize_page_range_string(doc.metadata.get("page_label"))
        if pr:
            doc.metadata["page_range"] = pr

    return documents


def _load_documents_parallel(data_dir: Path) -> list[Document]:
    """Load documents using a thread pool — faster PDF/HTML parsing on multi-core."""
    num_workers = get_settings().doc_load_num_workers
    exts = get_doc_supported_exts()
    files = sorted(p for p in data_dir.rglob("*") if p.suffix.lower() in exts)
    if not files:
        return []

    documents: list[Document] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as pool:
        futures = {pool.submit(_load_one_file, f): f for f in files}
        for future in concurrent.futures.as_completed(futures):
            try:
                documents.extend(future.result())
            except Exception as exc:  # noqa: BLE001 - loader plugins may raise parser-specific failures.
                logger.warning("doc_load_failed | file=%s | error=%s", futures[future].name, exc)
    return documents


def _load_document_files_parallel(files: list[Path]) -> list[Document]:
    """Load selected documents using a thread pool - faster PDF/HTML parsing on multi-core."""
    if not files:
        return []

    documents: list[Document] = []
    num_workers = get_settings().doc_load_num_workers
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as pool:
        futures = {pool.submit(_load_one_file, f): f for f in files}
        for future in concurrent.futures.as_completed(futures):
            try:
                documents.extend(future.result())
            except Exception as exc:  # noqa: BLE001 - loader plugins may raise parser-specific failures.
                logger.warning("doc_load_failed | file=%s | error=%s", futures[future].name, exc)
    return documents


def _load_documents_with_extraction_cache(
    *,
    data_dir: Path,
    chroma_dir: Path,
    file_manifest: dict[str, object],
    started_monotonic: float | None = None,
) -> list[Document]:
    cache = _load_extracted_document_cache(chroma_dir)
    cached_manifest_files = ((cache or {}).get("file_manifest") or {}).get("files") or {}
    cached_docs_raw = (cache or {}).get("documents_by_file") or {}
    current_files = file_manifest.get("files") or {}
    if not isinstance(cached_manifest_files, dict) or not isinstance(cached_docs_raw, dict) or not isinstance(current_files, dict):
        cached_manifest_files = {}
        cached_docs_raw = {}

    documents_by_file: dict[str, list[Document]] = {}
    dirty_files: list[Path] = []
    for rel, current_entry in current_files.items():
        raw_docs = cached_docs_raw.get(rel)
        if cached_manifest_files.get(rel) == current_entry and isinstance(raw_docs, list):
            docs = [
                doc
                for item in raw_docs
                if isinstance(item, dict)
                for doc in [_deserialize_document_from_cache(item)]
                if doc is not None
            ]
            if docs:
                documents_by_file[str(rel)] = docs
                continue
        dirty_files.append(data_dir / str(rel))

    dirty_documents = _load_document_files_parallel(dirty_files)
    dirty_documents = _expand_structured_documents(dirty_documents)
    dirty_documents = _add_metadata(dirty_documents)
    for doc in dirty_documents:
        key = _document_cache_key(doc)
        if key:
            documents_by_file.setdefault(key, []).append(doc)

    documents: list[Document] = []
    for rel in current_files:
        documents.extend(documents_by_file.get(str(rel), []))

    reused = len(current_files) - len(dirty_files)
    if reused or dirty_files:
        logger.info(
            "Extracted document cache | reused_files=%s | dirty_files=%s | documents=%s",
            reused,
            len(dirty_files),
            len(documents),
        )
    if started_monotonic is not None:
        _print_ingest_progress(
            phase="documents_extraction_cache",
            processed=reused,
            total=len(current_files),
            current="",
            started_monotonic=started_monotonic,
            extra=f"reused_files={reused} dirty_files={len(dirty_files)}",
        )
    _save_extracted_document_cache(chroma_dir, file_manifest=file_manifest, documents=documents)
    return documents


def build_index(reset: bool = False) -> None:
    """Delegate to ingestion_loader (index build orchestration)."""
    from app.ingestion_loader import build_index as _run

    return _run(reset)
