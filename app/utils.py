"""Общие утилиты (preview для логов и т.п.)."""
from typing import Any


def safe_preview(text: Any, limit: int = 300) -> str:
    """Краткий превью текста для логов: одна строка, обрезка по limit."""
    if text is None:
        return ""
    text = str(text).replace("\n", " ").replace("\r", " ")
    return text[:limit] + ("..." if len(text) > limit else "")
