"""Shared SourceAddress presentation (W8).

North star: ``курс · урок · раздел · 03:20`` — same grammar as Memory Run /
concept_address, for Library cards and later Tutor/Konspekt/Plan.

Pure helpers (no Streamlit) so unit tests stay light.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

# Separator matches concept_address / schedule tiles (" · ").
ADDRESS_SEP = " · "


def join_address_parts(*parts: str | None) -> str:
    """Join non-empty parts with the product address separator."""
    cleaned = [str(p).strip() for p in parts if str(p or "").strip()]
    return ADDRESS_SEP.join(cleaned)


def normalize_source_address(raw: str | None) -> str:
    """Collapse whitespace; keep middle dots as separators."""
    text = " ".join(str(raw or "").split()).strip()
    if not text:
        return "—"
    # Normalize alternate separators to product form.
    for sep in (" / ", " | ", " — ", " – "):
        if sep in text:
            text = ADDRESS_SEP.join(p.strip() for p in text.split(sep) if p.strip())
    return text or "—"


def format_source_address(
    *,
    course: str | None = None,
    lesson: str | None = None,
    section: str | None = None,
    time_code: str | None = None,
    fallback: str | None = None,
) -> str:
    """Build a stable address line; fallback when all parts empty."""
    built = join_address_parts(course, lesson, section, time_code)
    if built:
        return built
    return normalize_source_address(fallback)


def address_from_mapping(data: Mapping[str, Any] | None) -> str:
    """Prefer ``address`` key; else compose from common field names."""
    if not isinstance(data, Mapping):
        return "—"
    direct = str(data.get("address") or "").strip()
    if direct:
        return normalize_source_address(direct)
    return format_source_address(
        course=str(data.get("course") or data.get("folder_rel") or "") or None,
        lesson=str(data.get("lesson") or data.get("label") or "") or None,
        section=str(data.get("section") or data.get("heading_text") or "") or None,
        time_code=str(data.get("time_code") or data.get("timecode") or "") or None,
        fallback=str(data.get("title") or data.get("path") or "") or None,
    )


def status_with_icon(status: str | None, *, kind: str = "") -> str:
    """Always include icon/text — never color-only status (W8)."""
    text = str(status or "").strip() or "без статуса"
    # Already prefixed with an emoji / symbol → keep.
    if text[:1].isascii() is False and not text[0].isalnum():
        # Heuristic: starts with non-alnum (often emoji)
        if ord(text[0]) > 127:
            return text
    kind_l = str(kind or "").strip().lower()
    icon = "•"
    if kind_l in {"summary", "area"}:
        icon = "📊"
    elif kind_l in {"transfer", "пересадка"}:
        icon = "🔀"
    elif kind_l in {"route", "маршрут", "stop"}:
        icon = "🛤"
    elif kind_l in {"course", "catalog", "курс"}:
        icon = "📚"
    elif "переиндекс" in text.lower() or "устарел" in text.lower():
        icon = "⚠️"
    elif "повтор" in text.lower() or "due" in text.lower():
        icon = "🔁"
    elif "актив" in text.lower():
        icon = "🎯"
    return f"{icon} {text}"


def address_aria_label(address: str | None) -> str:
    """Screen-reader label for address chip."""
    addr = normalize_source_address(address)
    if addr == "—":
        return "Адрес источника не указан"
    return f"Адрес источника: {addr}"


def esc_html(value: str | None) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def source_address_html(address: str | None, *, quant: str | None = None) -> str:
    """Accessible address chip markup (tokens via CSS classes)."""
    addr = normalize_source_address(address)
    quant_s = str(quant or "").strip()
    quant_bit = (
        f'<span class="src-addr-quant">{esc_html(quant_s)}</span>' if quant_s else ""
    )
    return (
        f'<div class="src-addr" role="text" aria-label="{esc_html(address_aria_label(addr))}">'
        f'<span class="src-addr-pin" aria-hidden="true">📍</span>'
        f'<span class="src-addr-text">{esc_html(addr)}</span>'
        f"{quant_bit}"
        f"</div>"
    )


def library_card_html(
    *,
    title: str,
    address: str,
    status: str,
    kind: str = "course",
    quant: str | None = None,
    thumb_uri: str | None = None,
) -> str:
    """Unified card body: address → title → status (W8 anatomy)."""
    status_line = status_with_icon(status, kind=kind)
    thumb = ""
    if thumb_uri:
        thumb = (
            f'<img class="lib-card-thumb" src="{esc_html(thumb_uri)}" alt="" '
            f'aria-hidden="true">'
        )
    return (
        f'<div class="lib-card" data-kind="{esc_html(kind)}">'
        f"{thumb}"
        f'<div class="lib-card-body">'
        f"{source_address_html(address, quant=quant)}"
        f'<div class="lib-card-title">{esc_html(title)}</div>'
        f'<div class="lib-card-status">{esc_html(status_line)}</div>'
        f"</div></div>"
    )


__all__ = [
    "ADDRESS_SEP",
    "address_aria_label",
    "address_from_mapping",
    "esc_html",
    "format_source_address",
    "join_address_parts",
    "library_card_html",
    "normalize_source_address",
    "source_address_html",
    "status_with_icon",
]
