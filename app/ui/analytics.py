"""Яндекс.Метрика для Streamlit UI (P2): инъекция счётчика в served index.html.

Streamlit не даёт штатно вставить тег в <head>, а ``st.components.v1.html`` рисует
изолированный iframe (просмотры родительской страницы не считаются корректно).
Надёжный путь — один раз при старте процесса пропатчить index.html, который
Streamlit раздаёт статически (``streamlit.__file__/static/index.html``).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

_MARKER = "<!-- yandex-metrika-injected -->"


def _metrika_snippet(counter_id: str) -> str:
    return f"""{_MARKER}
<script type="text/javascript">
   (function(m,e,t,r,i,k,a){{m[i]=m[i]||function(){{(m[i].a=m[i].a||[]).push(arguments)}};
   m[i].l=1*new Date();
   for (var j = 0; j < document.scripts.length; j++) {{if (document.scripts[j].src === r) {{ return; }}}}
   k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)}})
   (window, document, "script", "https://mc.yandex.ru/metrika/tag.js", "ym");

   ym({counter_id}, "init", {{
        clickmap:true,
        trackLinks:true,
        accurateTrackBounce:true,
        webvisor:true
   }});
</script>
<noscript><div><img src="https://mc.yandex.ru/watch/{counter_id}" style="position:absolute; left:-9999px;" alt="" /></div></noscript>
"""


def inject_yandex_metrika() -> None:
    """Идемпотентная инъекция тега в index.html Streamlit; no-op без YANDEX_METRIKA_ID."""
    counter_id = (get_settings().yandex_metrika_id or "").strip()
    if not counter_id:
        return
    try:
        import streamlit

        index_path = Path(streamlit.__file__).resolve().parent / "static" / "index.html"
        html = index_path.read_text(encoding="utf-8")
        if _MARKER in html:
            return
        patched = re.sub(r"</head>", _metrika_snippet(counter_id) + "</head>", html, count=1)
        if patched == html:
            logger.warning("yandex_metrika_inject_failed: </head> not found in %s", index_path)
            return
        index_path.write_text(patched, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - read-only FS на проде/повторный запуск не должны валить UI
        logger.warning("yandex_metrika_inject_skipped: %s", exc)
