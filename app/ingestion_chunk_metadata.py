"""Metadata-aware split helpers for ingestion chunks (split from ``app.ingestion``)."""

from llama_index.core import Document

# Поля, попадающие в metadata_str при SentenceSplitter; длинные строки урезаем, чтобы
# tokenizer(metadata_str) не превышал chunk_size (LlamaIndex metadata-aware split).
_METADATA_TRUNCATE_KEYS = frozenset(
    {
        "section_path",
        "structural_path",
        "section_title",
        "key_concepts",
        "concepts",
        "topic",
        "title",
        "html_title",
    }
)
_METADATA_TRUNCATE_MAX_LEN = 500

# Не учитывать в metadata_str при разбиении: иначе весь текст секции считается «метаданными».
_METADATA_EXCLUDE_FROM_SPLIT_STRING = frozenset({"original_text", "window"})


def _truncate_verbose_metadata_fields(metadata: dict) -> None:
    max_len = _METADATA_TRUNCATE_MAX_LEN
    for key in _METADATA_TRUNCATE_KEYS:
        val = metadata.get(key)
        if isinstance(val, str) and len(val) > max_len:
            metadata[key] = val[: max_len - 3] + "..."


def _configure_document_for_metadata_aware_split(doc: Document) -> None:
    """SentenceSplitter токенизирует get_metadata_str; исключаем тяжёлые ключи и урезаем длинные строки."""
    _truncate_verbose_metadata_fields(doc.metadata or {})
    extra = list(_METADATA_EXCLUDE_FROM_SPLIT_STRING)
    doc.excluded_embed_metadata_keys = list(
        dict.fromkeys(list(doc.excluded_embed_metadata_keys or []) + extra)
    )
    doc.excluded_llm_metadata_keys = list(
        dict.fromkeys(list(doc.excluded_llm_metadata_keys or []) + extra)
    )


# Summary-ноды: не копировать все поля чанка (file_path, длинные пути и т.д.) — иначе
# VectorStoreIndex.from_documents падает: len(tokenize(metadata_str)) > chunk_size.
_SUMMARY_METADATA_KEYS = (
    "doc_id",
    "relative_path",
    "file_name",
    "folder_rel",
    "folder_name",
    "folder",
    "file",
    "ext",
    "course",
    "module",
    "lecture",
    "doc_kind",
    "page_range",
    "title",
    "html_title",
    "topic",
    "doc_type",
    "difficulty",
    "source_extraction",
)


def _slim_metadata_for_summary(base_metadata: dict) -> dict:
    """Только поля для фильтрации и атрибуции; без file_path и прочего «тяжёлого» наследия чанков."""
    out: dict = {}
    for key in _SUMMARY_METADATA_KEYS:
        if key not in base_metadata:
            continue
        val = base_metadata[key]
        if isinstance(val, str) and len(val) > _METADATA_TRUNCATE_MAX_LEN:
            val = val[: _METADATA_TRUNCATE_MAX_LEN - 3] + "..."
        out[key] = val
    out["node_type"] = "document_summary"
    return out
