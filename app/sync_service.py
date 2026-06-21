"""
Локальный multi-device sync без облака: JSON-снимок ``user_state`` + ``quiz_ui_stats``.

QR-код: если сжатый payload помещается в лимит — полный импорт со скана; иначе QR
содержит только sha256 для сверки файла (основной перенос — скачанный JSON).

Фоновая «автосинхронизация» в облако/Telegram из этого модуля намеренно не реализована:
нужны отдельные endpoint, политика секретов и планировщик; используйте явный
``GET /sync/export`` / ``POST /sync/import`` или Telegram-бот на той же машине.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import logging
from typing import Any

from app.user_state import export_full_sync_bundle, import_full_sync_bundle

logger = logging.getLogger(__name__)

_QR_MAX_B64 = 1600


def bundle_json_bytes() -> bytes:
    return json.dumps(export_full_sync_bundle(), ensure_ascii=False).encode("utf-8")


def export_bundle_to_dict() -> dict[str, Any]:
    return export_full_sync_bundle()


def import_bundle_from_dict(data: dict[str, Any]) -> dict[str, Any]:
    return import_full_sync_bundle(data)


def qr_payload_for_bundle() -> tuple[str, bool]:
    """
    Возвращает (строка для QR, fits_full_import).
    Если False — импорт только из файла; QR для проверки целостности.
    """
    raw = bundle_json_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    compressed = gzip.compress(raw, compresslevel=9)
    b64 = base64.urlsafe_b64encode(compressed).decode("ascii")
    if len(b64) <= _QR_MAX_B64:
        return f"home-rag:v1:{b64}", True
    return f"home-rag:v1:sha256:{digest}", False


def import_from_qr_payload(payload: str) -> dict[str, Any]:
    """Разбор строки из QR (полный gzip+b64 или только sha256)."""
    p = (payload or "").strip()
    if p.startswith("home-rag:v1:sha256:"):
        raise ValueError(
            "QR содержит только отпечаток файла — импортируйте JSON через «Скачать снимок»."
        )
    if not p.startswith("home-rag:v1:"):
        raise ValueError("неизвестный формат QR")
    rest = p[len("home-rag:v1:") :]
    if rest.startswith("sha256:"):
        raise ValueError("используйте импорт файла")
    raw = gzip.decompress(base64.urlsafe_b64decode(rest.encode("ascii")))
    data = json.loads(raw.decode("utf-8"))
    return import_full_sync_bundle(data)


def qr_png_bytes(text: str) -> bytes:
    """PNG изображение QR (требуется ``qrcode``)."""
    import qrcode

    img = qrcode.make(text, box_size=3, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


__all__ = [
    "bundle_json_bytes",
    "export_bundle_to_dict",
    "import_bundle_from_dict",
    "import_from_qr_payload",
    "qr_payload_for_bundle",
    "qr_png_bytes",
]
