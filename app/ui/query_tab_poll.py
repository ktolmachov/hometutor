"""Back-compat wrapper for the shared reindex poller."""

from __future__ import annotations

from app.ui.reindex_poll import poll_reindex_status


def poll_reindex_status_for_query_tab() -> None:
    poll_reindex_status()
