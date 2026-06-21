"""Course Cockpit v2 — каркас single-pane UI (E30 A1, только layout).

Полная ротация активностей и Path Map — в следующих пакетах волны.
"""

from __future__ import annotations

import json
import re
import uuid
from types import SimpleNamespace
from typing import Any

import streamlit as st

from app.course_cache import (
    clear_recovery_catch_up_for_scope,
    load_next_session_promise_for_scope,
    load_recovery_catch_up_for_scope,
    save_next_session_promise,
    save_recovery_catch_up_for_scope,
)
from app.course_metrics import course_daily_runway_summary
from app.pace_engine import pace_mode_label
from app.ui.cockpit_rotator import current_slot, render_rotator_panel
from app.ui.mission_control import (
    clear_first_session_session_cache,
    load_first_session_artifact_cached_for_scope,
    render_first_session_block,
)
from app.ui.study_scope import get_active_scope
from app.warmup_planner import (
    confidence_dip_initial_state,
    confidence_dip_public_status,
    confidence_dip_reduce,
    remediation_mini_loop_plan,
)
from app.input_validation import InputGuardrailError, prepare_ask_request
from app.ui.helpers import format_request_error
from app.ui_client import fetch_json
from app.user_state import get_kv, set_kv

CONFIDENCE_DIP_SESSION_KEY = "course_confidence_dip_state_v1"
HOMEWORK_PLAYBOOK_KV_PREFIX = "course_hw_playbook_v1"


def playbook_kv_key(scope_id: str) -> str:
    sid = str(scope_id or "").strip()
    return f"{HOMEWORK_PLAYBOOK_KV_PREFIX}_{sid}" if sid else HOMEWORK_PLAYBOOK_KV_PREFIX


def _default_homework_bundle() -> dict[str, Any]:
    return {"version": 1, "items": []}


def load_homework_bundle(scope: dict[str, Any]) -> dict[str, Any]:
    sid = str(scope.get("id") or "").strip()
    if not sid:
        return _default_homework_bundle()
    raw = get_kv(playbook_kv_key(sid))
    if not raw:
        return _default_homework_bundle()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _default_homework_bundle()
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return _default_homework_bundle()
    return data


def save_homework_bundle(scope: dict[str, Any], bundle: dict[str, Any]) -> None:
    sid = str(scope.get("id") or "").strip()
    if not sid:
        return
    set_kv(playbook_kv_key(sid), json.dumps(bundle, ensure_ascii=False))


def parse_playbook_steps_from_answer(answer: str) -> list[dict[str, str]]:
    """Извлечь шаги ``{action, self_check}`` из ответа /ask (блок ```json ... ```)."""
    if not answer or not str(answer).strip():
        return []
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", str(answer), re.IGNORECASE)
    raw = m.group(1).strip() if m else str(answer).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict) and "steps" in data:
        data = data["steps"]
    if not isinstance(data, list):
        return []
    out: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        act = str(item.get("action") or item.get("действие") or "").strip()
        chk = str(
            item.get("self_check")
            or item.get("criterion")
            or item.get("критерий")
            or item.get("готовность")
            or ""
        ).strip()
        if act or chk:
            out.append({"action": act, "self_check": chk})
    return out


def _homework_find(bundle: dict[str, Any], hw_id: str) -> dict[str, Any] | None:
    for it in bundle.get("items", []):
        if isinstance(it, dict) and str(it.get("id")) == hw_id:
            return it
    return None


def build_playbook_ask_question(
    *,
    course_title: str,
    statement: str,
    topic_label: str,
    brief_mode: bool,
) -> str:
    """Текст вопроса для POST /ask: worked-example ladder + только JSON шагов (без финального решения)."""
    topic_line = f"\nТема/фокус: {topic_label.strip()}." if str(topic_label).strip() else ""
    brev = (
        "Режим «кратко»: сделай не больше 3 шагов, формулировки короткие."
        if brief_mode
        else "Дай достаточно шагов, чтобы пройти задание по частям (обычно 4–7 шагов)."
    )
    return (
        f"Курс: «{course_title}».{topic_line}\n\n"
        f"Домашнее задание:\n{statement.strip()}\n\n"
        "Построй пошаговый плейбук (worked-example ladder): на каждом шаге — что сделать и критерий "
        "самопроверки. Не приводи готового финального ответа на исходную задачу.\n"
        f"{brev}\n"
        "Опирайся на материалы выбранной области (retrieval уже ограничен курсом).\n\n"
        "Верни ровно один JSON-массив шагов в markdown-блоке ```json ... ```. Формат элементов:\n"
        '[{"action": "...", "self_check": "..."}, ...]\n'
        "Поля только латинские ключи action и self_check; текст значений на русском."
    )


def _persist_hw_checkboxes(scope: dict[str, Any], hw_id: str, n_steps: int) -> None:
    bundle = load_homework_bundle(scope)
    item = _homework_find(bundle, hw_id)
    if not item or n_steps <= 0:
        return
    flags = [bool(st.session_state.get(f"hw_done_{hw_id}_{j}")) for j in range(n_steps)]
    item["step_done"] = flags
    save_homework_bundle(scope, bundle)


def render_homework_playbook_panel(scope: dict[str, Any], *, course_title: str) -> None:
    """Inline-панель ДЗ + генерация шагов через /ask с опорой на материалы курса; прогресс в KV."""
    st.divider()
    st.markdown("#### Домашние задания — плейбук шагов")
    st.caption(
        "Создайте формулировку ДЗ, привязанную к курсу; шаги генерируются без готового финального ответа. "
        "Источники из ответа — как цитаты по материалам папки."
    )

    bundle = load_homework_bundle(scope)
    items: list[dict[str, Any]] = [x for x in bundle.get("items", []) if isinstance(x, dict)]

    with st.expander("Добавить домашнее задание", expanded=not items):
        hw_title = st.text_input("Краткое название (необязательно)", key="hw_new_title")
        hw_topic = st.text_input("Тема модуля (необязательно)", key="hw_new_topic")
        hw_stmt = st.text_area("Формулировка задания", key="hw_new_statement", height=120)
        if st.button("Сохранить в список", key="hw_add_btn", type="primary"):
            if not str(hw_stmt).strip():
                st.warning("Введите текст задания.")
            else:
                new_id = uuid.uuid4().hex[:10]
                bundle = load_homework_bundle(scope)
                bundle.setdefault("items", []).append(
                    {
                        "id": new_id,
                        "title": str(hw_title).strip() or "Домашнее задание",
                        "topic_label": str(hw_topic).strip(),
                        "statement": str(hw_stmt).strip(),
                        "brief_mode": False,
                        "hints_only": True,
                        "steps": [],
                        "step_done": [],
                        "last_sources": [],
                    }
                )
                save_homework_bundle(scope, bundle)
                st.rerun()

    if not items:
        st.info("Пока нет сохранённых заданий — добавьте первое выше.")
        return

    opts = {f"{it.get('title', 'ДЗ')} ({it.get('id')})": str(it.get("id")) for it in items}
    sel_label = st.selectbox(
        "Активное задание",
        list(opts.keys()),
        key=f"hw_select_label_{scope.get('id') or 'global'}",
    )
    hw_id = opts[sel_label]
    item = _homework_find(load_homework_bundle(scope), hw_id)
    if not item:
        st.error("Запись задания не найдена.")
        return

    st.toggle(
        "Режим «кратко» (меньше шагов и текста)",
        value=bool(item.get("brief_mode")),
        key=f"hw_brief_{hw_id}",
    )
    st.toggle(
        "Только подсказки (assistance: hint; без развёрнутого решения)",
        value=bool(item.get("hints_only", True)),
        key=f"hw_hints_{hw_id}",
    )
    if st.button("Сохранить настройки режима", key=f"hw_save_modes_{hw_id}"):
        bundle = load_homework_bundle(scope)
        cur = _homework_find(bundle, hw_id)
        if cur:
            cur["brief_mode"] = bool(st.session_state.get(f"hw_brief_{hw_id}"))
            cur["hints_only"] = bool(st.session_state.get(f"hw_hints_{hw_id}"))
            save_homework_bundle(scope, bundle)
        st.success("Сохранено.")

    stmt_show = str(item.get("statement") or "")
    st.markdown("**Формулировка**")
    st.text(stmt_show[:4000] if stmt_show else "—")

    gen_col, _ = st.columns([1, 2])
    with gen_col:
        gen_clicked = st.button("Сгенерировать шаги", key=f"hw_gen_{hw_id}", type="primary")

    if gen_clicked:
        q = build_playbook_ask_question(
            course_title=course_title,
            statement=str(item.get("statement") or ""),
            topic_label=str(item.get("topic_label") or ""),
            brief_mode=bool(st.session_state.get(f"hw_brief_{hw_id}", item.get("brief_mode"))),
        )
        hints = bool(st.session_state.get(f"hw_hints_{hw_id}", item.get("hints_only", True)))
        try:
            prepared = prepare_ask_request(
                SimpleNamespace(
                    question=q,
                    folder_rel=str(scope.get("folder_rel") or "") or None,
                    topic=str(item.get("topic_label") or "").strip() or None,
                    homework_mode=True,
                    assistance_level="hint" if hints else "plan",
                )
            )
        except InputGuardrailError as exc:
            st.error(f"Текст не прошёл проверку [{exc.code}]: {exc}")
        else:
            try:
                with st.spinner("Генерация плейбука (retrieval + LLM)…"):
                    data = fetch_json(
                        "POST",
                        "/ask",
                        timeout=120,
                        json={
                            "question": prepared.question,
                            "folder": prepared.options.folder,
                            "folder_rel": prepared.options.folder_rel,
                            "file_name": prepared.options.file_name,
                            "relative_path": prepared.options.relative_path,
                            "topic": prepared.options.topic,
                            "homework_mode": prepared.options.homework_mode,
                            "assistance_level": prepared.options.assistance_level,
                            "study_mode": prepared.options.study_mode,
                            "followup_context": prepared.options.followup_context,
                        },
                    )
            except Exception as e:  # noqa: BLE001 - Streamlit scaffold shows API/load errors inline.
                st.error(f"Ошибка запроса: {format_request_error(e)}")
            else:
                ans = str(data.get("answer") or "")
                steps = parse_playbook_steps_from_answer(ans)
                bundle = load_homework_bundle(scope)
                cur = _homework_find(bundle, hw_id)
                if cur:
                    cur["steps"] = steps
                    cur["step_done"] = [False] * len(steps)
                    cur["brief_mode"] = bool(st.session_state.get(f"hw_brief_{hw_id}", cur.get("brief_mode")))
                    cur["hints_only"] = bool(st.session_state.get(f"hw_hints_{hw_id}", cur.get("hints_only", True)))
                    cur["last_sources"] = data.get("sources") or []
                    cur["last_answer_excerpt"] = ans[:2000]
                    save_homework_bundle(scope, bundle)
                    for j in range(len(steps)):
                        st.session_state.pop(f"hw_done_{hw_id}_{j}", None)
                if not steps:
                    st.warning("Не удалось разобрать шаги из ответа. Откройте «Сырой ответ» ниже или переформулируйте задание.")
                st.session_state[f"hw_raw_open_{hw_id}"] = True
                st.rerun()

    steps = item.get("steps") if isinstance(item.get("steps"), list) else []
    steps = [s for s in steps if isinstance(s, dict)]

    if steps:
        st.markdown("**Шаги**")
        n = len(steps)
        bundle = load_homework_bundle(scope)
        cur = _homework_find(bundle, hw_id)
        persisted = list(cur.get("step_done") or []) if cur else []
        if len(persisted) != n:
            persisted = [bool(persisted[i]) if i < len(persisted) else False for i in range(n)]
            if cur:
                cur["step_done"] = persisted
                save_homework_bundle(scope, bundle)
        for idx, step in enumerate(steps):
            key_cb = f"hw_done_{hw_id}_{idx}"
            if key_cb not in st.session_state:
                st.session_state[key_cb] = bool(persisted[idx]) if idx < len(persisted) else False

            st.checkbox(
                f"Шаг {idx + 1}",
                key=key_cb,
                on_change=_persist_hw_checkboxes,
                args=(scope, hw_id, n),
            )
            st.markdown(f"{step.get('action', '')}")
            st.caption(f"Критерий: {step.get('self_check', '—')}")

    srcs = item.get("last_sources") if isinstance(item.get("last_sources"), list) else []
    if srcs:
        with st.expander("Источники последнего ответа", expanded=False):
            for s in srcs[:12]:
                if not isinstance(s, dict):
                    continue
                fn = s.get("file_name") or s.get("relative_path") or s.get("path")
                st.caption(str(fn or s))

    with st.expander("Сырой ответ модели (фрагмент)", expanded=bool(st.session_state.get(f"hw_raw_open_{hw_id}"))):
        ex = str(item.get("last_answer_excerpt") or "")
        st.text(ex or "—")


def format_next_session_promise_text(
    *,
    title: str,
    runway_goal: str,
    micro_target: int,
    due_today: int,
    active_slot: str,
    pace_label: str,
) -> str:
    """Одна строка «обещания» для сохранения и показа при следующем возврате."""
    parts = [
        f"Курс «{title}»: вернуться и продолжить.",
        f"Pace: {pace_label}.",
    ]
    if runway_goal:
        parts.append(str(runway_goal))
    if due_today:
        parts.append(f"Due сегодня: {due_today}.")
    if micro_target:
        parts.append(f"Микро-цель: {micro_target} шаг(ов).")
    if active_slot:
        parts.append(f"Старт с активности «{active_slot}».")
    return " ".join(parts)


def cockpit_feature_enabled(settings: Any) -> bool:
    """True если в настройках включён флаг RAG_COURSE_COCKPIT_V2."""
    return bool(getattr(settings, "rag_course_cockpit_v2", False))


def cockpit_scope_ready(scope: dict[str, Any] | None) -> bool:
    """True если в сессии есть активный StudyScope."""
    return isinstance(scope, dict) and bool(scope.get("active"))


def current_pace_mode_label(scope: dict[str, Any] | None) -> str:
    """Extract and format current pace mode from plan.v2 payload."""
    if not isinstance(scope, dict):
        return pace_mode_label(None)
    learning_plan = scope.get("learning_plan")
    if not isinstance(learning_plan, dict):
        return pace_mode_label(None)
    plan = learning_plan.get("plan")
    if isinstance(plan, dict):
        plan_v2 = plan.get("v2")
    else:
        # Backward-compatible shape for legacy payloads.
        plan_v2 = learning_plan.get("v2")
    if not isinstance(plan_v2, dict):
        return pace_mode_label(None)
    return pace_mode_label(plan_v2.get("pace_mode"))


def render_course_cockpit_scaffold() -> None:
    """Трёхколоночный каркас + заголовок + выход из кабины (без бизнес-логики)."""
    scope = get_active_scope()
    if not cockpit_scope_ready(scope):
        st.session_state.pop("course_cockpit_active", None)
        st.warning("Нет активного курса — кабина недоступна.")
        st.stop()

    if CONFIDENCE_DIP_SESSION_KEY not in st.session_state:
        st.session_state[CONFIDENCE_DIP_SESSION_KEY] = confidence_dip_initial_state()
    dip_state = st.session_state[CONFIDENCE_DIP_SESSION_KEY]
    if not isinstance(dip_state, dict):
        dip_state = confidence_dip_initial_state()
        st.session_state[CONFIDENCE_DIP_SESSION_KEY] = dip_state

    title = str(scope.get("title") or scope.get("folder_rel") or "Курс")
    st.markdown(f"### Course Cockpit — **{title}**")
    st.caption("Режим v2 (черновой каркас): Path Map | активность | прогресс.")
    st.caption(f"Pace mode: **{current_pace_mode_label(scope)}**")

    saved_promise = load_next_session_promise_for_scope(scope)
    if isinstance(saved_promise, dict) and str(saved_promise.get("promise_text") or "").strip():
        st.success(f"**Следующая сессия (сохранено ранее):** {saved_promise['promise_text']}")

    left, center, right = st.columns([1, 2, 1], gap="medium")
    with left:
        st.markdown("#### Path Map")
        st.info("Заглушка: список концептов курса появится в следующих итерациях.")
    with center:
        st.markdown("#### Активность")
        scope_folder = str(scope.get("folder_rel") or "course")
        with st.spinner("Загружаем первый обзор курса…"):
            cockpit_artifact, cockpit_status = load_first_session_artifact_cached_for_scope(scope)
        if cockpit_status == "ok" and isinstance(cockpit_artifact, dict):
            render_first_session_block(
                cockpit_artifact,
                key_prefix="cockpit_first_session",
                folder_rel=scope_folder,
                compact=True,
            )
        elif cockpit_status == "error":
            st.warning("Не удалось прочитать сохранённый обзор курса.")
            st.caption("Показан обычный режим")
        else:
            st.info("Заглушка: список концептов курса появится в следующих итерациях.")
        render_rotator_panel()
        dip_pub = confidence_dip_public_status(dip_state)
        if dip_pub.get("in_remediation"):
            loop = remediation_mini_loop_plan(dip_state)
            st.info(loop.message)
        with st.expander("Retrieval gate / уверенность (локальная отметка)", expanded=False):
            conf = st.slider(
                "Оценка уверенности (0–1)",
                min_value=0.0,
                max_value=1.0,
                value=0.72,
                step=0.01,
                key="course_confidence_dip_slider",
            )
            ok_miss = st.columns(2)
            with ok_miss[0]:
                if st.button("Проверка пройдена", key="course_conf_gate_ok", type="primary"):
                    st.session_state[CONFIDENCE_DIP_SESSION_KEY] = confidence_dip_reduce(
                        dip_state,
                        gate_passed=True,
                        confidence_0_1=conf,
                    )
                    st.rerun()
            with ok_miss[1]:
                if st.button("Провал gate", key="course_conf_gate_miss"):
                    st.session_state[CONFIDENCE_DIP_SESSION_KEY] = confidence_dip_reduce(
                        dip_state,
                        gate_passed=False,
                        confidence_0_1=conf,
                    )
                    st.rerun()
            if st.button("Выйти из repair-loop вручную", key="course_conf_dip_manual_exit"):
                manual = dict(dip_state)
                manual["in_remediation"] = False
                manual["remediation_success_streak"] = 0
                st.session_state[CONFIDENCE_DIP_SESSION_KEY] = manual
                st.rerun()
    with right:
        st.markdown("#### Прогресс")
        saved_budget = load_recovery_catch_up_for_scope(scope)
        runway = course_daily_runway_summary(scope, recovery_catch_up_today=saved_budget)
        if not runway.get("active"):
            st.caption("Нет сводки прогресса для текущего курса.")
        else:
            st.caption("Дневной runway")
            st.markdown(str(runway.get("goal_line") or ""))
            rb_cap = str(runway.get("recovery_backlog_caption") or "").strip()
            if rb_cap:
                st.caption(rb_cap)
            streak_txt = str(runway.get("streak_caption") or "Стрик: **0** дн.").strip()
            st.caption("🔥 " + streak_txt)

            sid = str(scope.get("id") or "").strip()
            due_now = int(runway.get("due_today") or 0)
            rec_mic = int(runway.get("recommended_micro_target") or 0)
            if sid and due_now > 0:
                bud_key = f"course_recovery_budget_steps_{sid}"
                start_val = saved_budget if saved_budget is not None else rec_mic
                start_val = max(1, min(int(start_val), due_now))

                def _persist_recovery_budget_cb() -> None:
                    picked = max(1, min(int(st.session_state[bud_key]), due_now))
                    save_recovery_catch_up_for_scope(scope, catch_up_steps=picked)

                st.slider(
                    "Catch-up на сегодня (recovery budget)",
                    min_value=1,
                    max_value=due_now,
                    value=start_val,
                    step=1,
                    help=(
                        "Системная подсказка остаётся по умолчанию; здесь можно выбрать "
                        "реалистичный объём. Полный счётчик due сохранён в строках выше и в описании ниже."
                    ),
                    key=bud_key,
                    on_change=_persist_recovery_budget_cb,
                )
                st.caption(
                    "Рекомендация сейчас: **{}** из **{}** due (можно временно смягчить или чуть добавить)".format(
                        rec_mic,
                        due_now,
                    )
                )
                if saved_budget is not None and st.button(
                    "Вернуть рекомендацию системы",
                    key=f"{bud_key}_reset",
                    type="secondary",
                ):
                    clear_recovery_catch_up_for_scope(scope)
                    st.rerun()

    render_homework_playbook_panel(scope, course_title=title)

    if st.button("Выйти из кабины", type="secondary", key="course_cockpit_exit_btn"):
        persisted = load_recovery_catch_up_for_scope(scope)
        runway = course_daily_runway_summary(scope, recovery_catch_up_today=persisted)
        pace_l = current_pace_mode_label(scope)
        slot = current_slot()
        promise_body = format_next_session_promise_text(
            title=title,
            runway_goal=str(runway.get("goal_line") or ""),
            micro_target=int(runway.get("micro_target") or 0),
            due_today=int(runway.get("due_today") or 0),
            active_slot=slot,
            pace_label=pace_l,
        )
        save_next_session_promise(
            scope,
            promise_text=promise_body,
            runway_goal_line=str(runway.get("goal_line") or ""),
            micro_target=int(runway.get("micro_target") or 0),
            due_today=int(runway.get("due_today") or 0),
            active_slot=slot,
        )
        clear_first_session_session_cache()
        st.session_state["course_cockpit_active"] = False
        st.rerun()


__all__ = [
    "CONFIDENCE_DIP_SESSION_KEY",
    "HOMEWORK_PLAYBOOK_KV_PREFIX",
    "build_playbook_ask_question",
    "cockpit_feature_enabled",
    "cockpit_scope_ready",
    "current_pace_mode_label",
    "format_next_session_promise_text",
    "load_homework_bundle",
    "parse_playbook_steps_from_answer",
    "playbook_kv_key",
    "render_course_cockpit_scaffold",
    "render_homework_playbook_panel",
    "save_homework_bundle",
]
