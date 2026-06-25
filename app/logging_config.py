from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

from app.config import LOG_DIR, PROJECT_ROOT_PATH, get_settings
from app.log_masking_policy import MaskingSink, redact_for_sink, redact_sink_payload

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

def _use_rotating_file_handler() -> bool:
    """
    RotatingFileHandler renames ``app.log`` on rollover; on Windows another open handle
    (IDE tail, second process, AV) often causes WinError 32.

    - ``HOME_RAG_NO_LOG_ROTATE`` / ``HOME_RAG_E2E_NO_LOG_ROTATE``: force plain FileHandler.
    - Windows: plain FileHandler by default; set ``HOME_RAG_LOG_ROTATE=true`` to enable rotation.
    - Other platforms: rotating handler (previous default).
    """
    settings = get_settings()
    if settings.home_rag_no_log_rotate or settings.home_rag_e2e_no_log_rotate:
        return False
    if sys.platform == "win32":
        return settings.home_rag_log_rotate
    return True


class SuppressStreamlitMediaMissingFilter(logging.Filter):
    """Drop noisy Streamlit media-cache miss tracebacks in e2e/CI logs."""

    _NOISE_MARKERS = (
        "MediaFileHandler: Missing file",
        "MediaFileStorageError: Bad filename",
        "No media file with id",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(marker in message for marker in self._NOISE_MARKERS)


class StructuredFormatter(logging.Formatter):
    """Serialize log records as JSON for easier filtering and correlation."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or _request_id_var.get(),
        }

        event = getattr(record, "event", None)
        if event:
            payload["event"] = event

        extra_fields = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        payload = redact_sink_payload(MaskingSink.STRUCTURED_LOG, payload)
        return json.dumps(payload, ensure_ascii=False)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = _request_id_var.get()
        return True


class StructuredLogMaskingFilter(logging.Filter):
    """Apply sink redaction before records reach structured handlers."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_for_sink(MaskingSink.STRUCTURED_LOG, "message", record.getMessage())
        record.args = ()
        extra_fields = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            record.extra_fields = redact_sink_payload(MaskingSink.STRUCTURED_LOG, extra_fields)
        return True


def set_request_id(request_id: str | None):
    return _request_id_var.set(request_id)


def reset_request_id(token) -> None:
    _request_id_var.reset(token)


def get_request_id() -> str | None:
    return _request_id_var.get()


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    extra = {"event": event, "extra_fields": fields}
    if hasattr(logger, "log"):
        logger.log(level, event, extra=extra)
        return

    payload = json.dumps(
        {
            "event": event,
            **fields,
        },
        ensure_ascii=False,
    )

    if level >= logging.ERROR and hasattr(logger, "error"):
        logger.error(payload)
    elif level >= logging.WARNING and hasattr(logger, "warning"):
        logger.warning(payload)
    else:
        logger.info(payload)


def setup_logging() -> logging.Logger:
    log_dir = LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(PROJECT_ROOT_PATH)
    logger.setLevel(logging.DEBUG)

    # Keep Streamlit media-cache miss noise out of CI/e2e logs while
    # preserving other Streamlit warnings/errors.
    streamlit_media_filter = SuppressStreamlitMediaMissingFilter()
    for third_party_logger_name in (
        "streamlit.web.server.media_file_handler",
        "streamlit.runtime.memory_media_file_storage",
    ):
        third_party_logger = logging.getLogger(third_party_logger_name)
        third_party_logger.addFilter(streamlit_media_filter)

    if logger.handlers:
        return logger

    formatter = StructuredFormatter()
    request_filter = RequestContextFilter()
    masking_filter = StructuredLogMaskingFilter()

    if _use_rotating_file_handler():
        file_handler = RotatingFileHandler(
            log_dir / "app.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    else:
        file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(masking_filter)
    file_handler.addFilter(request_filter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(masking_filter)
    console_handler.addFilter(request_filter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Модули проекта используют ``logging.getLogger(__name__)`` → ``app.<module>``.
    # Эти логгеры не дети ``PROJECT_ROOT_PATH``-логгера; без своих handler-ов они
    # попадают в ``logging.lastResort`` и теряют JSON-поля (event/extra_fields).
    # Навешиваем те же handler-ы на пространство ``app`` и отключаем propagate,
    # чтобы исключить дублирование через Python root.
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.DEBUG)
    if not app_logger.handlers:
        app_logger.addHandler(file_handler)
        app_logger.addHandler(console_handler)
    app_logger.propagate = False

    return logger
