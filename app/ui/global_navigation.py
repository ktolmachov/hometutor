"""W6 global navigation IA: four destinations + command access.

Pure routing helpers live here so tests do not need Streamlit. Rendering of
the primary rail uses Streamlit only in ``render_primary_destination_rail``.

``ALL_VIEWS`` in ``app.ui.constants`` remains the full routing contract —
this module only groups those views for discoverability.
"""

from __future__ import annotations

from typing import Any, Final, Iterable, Sequence

from app.ui.constants import ALL_VIEWS, HOME_VIEW
from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

# Destination ids (stable, not user-facing).
DEST_HOME: Final[str] = "home"
DEST_LEARN: Final[str] = "learn"
DEST_MEMORY: Final[str] = "memory"
DEST_LIBRARY: Final[str] = "library"
DEST_MORE: Final[str] = "more"

# Primary rail order (four stable destinations). «Ещё» is command access, not a 5th pill.
PRIMARY_DESTINATION_ORDER: Final[tuple[str, ...]] = (
    DEST_HOME,
    DEST_LEARN,
    DEST_MEMORY,
    DEST_LIBRARY,
)

DESTINATION_LABELS_RU: Final[dict[str, str]] = {
    DEST_HOME: "Главная",
    DEST_LEARN: "Учиться",
    DEST_MEMORY: "Память",
    DEST_LIBRARY: "Библиотека",
    DEST_MORE: "Ещё",
}

# Leaf views under each destination (order = secondary rail order).
DESTINATION_LEAVES: Final[dict[str, tuple[str, ...]]] = {
    DEST_HOME: (HOME_VIEW, "Прогресс обучения"),
    DEST_LEARN: (
        "Чат с тьютором",
        "Интерактивный Quiz",
        "Адаптивный план",
        "Курс",
    ),
    DEST_MEMORY: (
        "Knowledge Graph",
        "Живой конспект",
        "Flashcards",
    ),
    DEST_LIBRARY: (
        "Библиотека",
        "Темы",
        "Найти материалы",
        "Объяснить файл",
        "Быстрый ответ",
    ),
    DEST_MORE: (
        "История",
        "Метрики",
        "Чистый вид",
        "Собрать учебную сессию",
    ),
}

# Short leaf labels for secondary rail / titles.
LEAF_LABELS_RU: Final[dict[str, str]] = {
    HOME_VIEW: "Mission Control",
    "Прогресс обучения": "Прогресс",
    "Чат с тьютором": "Тьютор",
    "Интерактивный Quiz": "Quiz",
    "Адаптивный план": "План",
    "Курс": "Курс",
    "Knowledge Graph": "Мнемополис",
    "Живой конспект": "Конспект",
    "Flashcards": "Карточки",
    "Библиотека": "Каталог",
    "Темы": "Темы",
    "Найти материалы": "Поиск",
    "Объяснить файл": "Файл",
    "Быстрый ответ": "Ответ",
    "История": "История",
    "Метрики": "Метрики",
    "Чистый вид": "Печать",
    "Собрать учебную сессию": "Агент",
}

# Reverse map view → destination.
VIEW_DESTINATION: Final[dict[str, str]] = {
    view: dest
    for dest, leaves in DESTINATION_LEAVES.items()
    for view in leaves
}


def validate_navigation_contract() -> None:
    """Every ALL_VIEWS entry must map to exactly one destination leaf."""
    mapped = set(VIEW_DESTINATION)
    missing = [v for v in ALL_VIEWS if v not in mapped]
    extra = sorted(mapped - set(ALL_VIEWS))
    if missing:
        raise AssertionError(f"Views missing from DESTINATION_LEAVES: {missing}")
    if extra:
        raise AssertionError(f"Unknown views in DESTINATION_LEAVES: {extra}")
    for dest in PRIMARY_DESTINATION_ORDER:
        if dest not in DESTINATION_LEAVES:
            raise AssertionError(f"Primary destination has no leaves: {dest}")


def destination_for_view(view_name: str | None) -> str:
    view = str(view_name or "").strip()
    return VIEW_DESTINATION.get(view, DEST_MORE)


def leaf_label_ru(view_name: str | None) -> str:
    view = str(view_name or "").strip()
    return LEAF_LABELS_RU.get(view, view or "—")


def destination_label_ru(dest_id: str | None) -> str:
    return DESTINATION_LABELS_RU.get(str(dest_id or "").strip(), "Ещё")


def page_title_for_view(view_name: str | None) -> str:
    """Human page title: «Память · Карточки» (parent + leaf)."""
    view = str(view_name or "").strip()
    if not view:
        return "Главная"
    dest = destination_for_view(view)
    parent = destination_label_ru(dest)
    leaf = leaf_label_ru(view)
    if dest == DEST_HOME and view == HOME_VIEW:
        return parent
    if leaf == parent:
        return parent
    return f"{parent} · {leaf}"


def leaves_for_destination(dest_id: str) -> tuple[str, ...]:
    return DESTINATION_LEAVES.get(str(dest_id or "").strip(), ())


def visible_leaves_for_destination(
    dest_id: str,
    visible_views: Sequence[str] | Iterable[str],
) -> list[str]:
    visible = set(visible_views)
    return [v for v in leaves_for_destination(dest_id) if v in visible]


def default_leaf_for_destination(
    dest_id: str,
    visible_views: Sequence[str] | Iterable[str],
) -> str | None:
    leaves = visible_leaves_for_destination(dest_id, visible_views)
    return leaves[0] if leaves else None


def parent_destination_label_for_view(view_name: str | None) -> str:
    return destination_label_ru(destination_for_view(view_name))


def request_navigate(view_name: str, *, state: Any | None = None) -> None:
    """Queue navigation via PENDING (safe after current_view widget exists)."""
    view = str(view_name or "").strip()
    if view not in ALL_VIEWS:
        return
    target = state if state is not None else None
    if target is None:
        import streamlit as st

        target = st.session_state
    target[PENDING_CURRENT_VIEW_KEY] = view


def render_primary_destination_rail(
    *,
    current_view: str,
    visible_views: Sequence[str],
) -> None:
    """Four destination buttons + leaf strip for multi-leaf destinations.

    Does not replace ``key="current_view"`` selectbox (command access); only
    queues PENDING navigation and shows place/title.
    """
    import streamlit as st

    visible = list(visible_views)
    current = str(current_view or HOME_VIEW).strip()
    if current not in ALL_VIEWS:
        current = HOME_VIEW
    active_dest = destination_for_view(current)

    st.markdown(
        f'<div data-testid="e2e-nav-destination" data-value="{active_dest}"></div>',
        unsafe_allow_html=True,
    )
    cols = st.columns(len(PRIMARY_DESTINATION_ORDER), gap="small")
    for col, dest_id in zip(cols, PRIMARY_DESTINATION_ORDER):
        label = DESTINATION_LABELS_RU[dest_id]
        default_leaf = default_leaf_for_destination(dest_id, visible)
        disabled = default_leaf is None
        is_on = dest_id == active_dest
        with col:
            if st.button(
                label,
                key=f"nav_dest_{dest_id}",
                type="primary" if is_on else "secondary",
                width="stretch",
                disabled=disabled,
                help=f"Раздел «{label}»",
            ):
                if default_leaf and (not is_on or current != default_leaf):
                    request_navigate(default_leaf)
                    st.rerun()

    # Secondary leaf strip for the active destination (when more than one leaf visible).
    leaves = visible_leaves_for_destination(active_dest, visible)
    if len(leaves) > 1:
        leaf_cols = st.columns(len(leaves), gap="small")
        for col, leaf in zip(leaf_cols, leaves):
            leaf_on = leaf == current
            with col:
                if st.button(
                    leaf_label_ru(leaf),
                    key=f"nav_leaf_{leaf}",
                    type="primary" if leaf_on else "secondary",
                    width="stretch",
                ):
                    if leaf != current:
                        request_navigate(leaf)
                        st.rerun()

    title = page_title_for_view(current)
    st.caption(f"**{title}**")


# Validate at import: fail loud in tests/CI if ALL_VIEWS drifts.
validate_navigation_contract()
