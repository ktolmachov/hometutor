"""Regression: navigation helpers must not write ``session_state["current_view"]``
directly while the ``key="current_view"`` selectbox widget is already instantiated in
the same script run.

Findings: clicking a Mission Control seed-question chip crashed with
``StreamlitAPIException: st.session_state.current_view cannot be modified after the
widget with key current_view is instantiated`` — ``_navigate_to``/``_set_navigation_state``
wrote directly to ``current_view`` from inside a synchronous button body, AFTER
``main.py``'s ``st.selectbox(..., key="current_view")`` had already run earlier in the
same script. The only safe path is ``PENDING_CURRENT_VIEW_KEY`` (see
``app/ui/session_state.py``): ``main.py`` applies it BEFORE the selectbox on the next run.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _app_with_selectbox_then_navigate_button() -> None:
    """Minimal repro of main.py's shape: selectbox(key="current_view") THEN a view body
    with a synchronous navigation button — exactly the seed-question-chip call chain."""
    import streamlit as st

    from app.ui.mission_control import _navigate_to

    st.selectbox("Раздел", ["Mission Control", "Быстрый ответ"], key="current_view")
    if st.button("Перейти", key="go"):
        _navigate_to("Быстрый ответ")


class TestNavigateToAfterSelectboxInstantiated:
    def test_click_does_not_raise_streamlit_api_exception(self):
        at = AppTest.from_function(_app_with_selectbox_then_navigate_button)
        at.run()
        at.button(key="go").click().run()
        assert not at.exception

    def test_writes_pending_key_not_current_view_directly(self):
        at = AppTest.from_function(_app_with_selectbox_then_navigate_button)
        at.run()
        at.button(key="go").click().run()
        assert at.session_state["_pending_current_view"] == "Быстрый ответ"


def _app_with_on_click_navigation() -> None:
    """on_click= usage (mission tiles, KG card) — must keep working after the fix."""
    import streamlit as st

    from app.ui.mission_control import _set_navigation_state

    st.selectbox("Раздел", ["Mission Control", "Живой конспект"], key="current_view")
    st.button("Живой конспект", key="go_on_click", on_click=_set_navigation_state, args=("Живой конспект",))


class TestSetNavigationStateOnClick:
    def test_on_click_callback_does_not_raise(self):
        at = AppTest.from_function(_app_with_on_click_navigation)
        at.run()
        at.button(key="go_on_click").click().run()
        assert not at.exception
        assert at.session_state["_pending_current_view"] == "Живой конспект"
