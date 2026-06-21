"""Лёгкие эвристики для ручного / полуавтоматического prompt smoke (без LLM-judge)."""

from __future__ import annotations

from typing import Any


def evaluate_prompt_smoke_expect(
    answer: str,
    expect: dict[str, Any] | None,
    *,
    sources: list[dict[str, Any]] | None = None,
    debug: dict[str, Any] | None = None,
    length_text: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Возвращает (overall_pass, details).

    ``length_text`` — необязательный текст для гейтов длины (``min/max_answer_chars``);
    нужен для tutor-ответов, где ``answer`` = teaching_summary + детерминированный
    markdown-скаффолд (``format_tutor_v2_markdown``), а лимиты длины калиброваны на
    модельный текст. Подстрочные проверки всегда идут по полному ``answer``.

    Поддержка в ``expect``:
    - ``min_answer_chars`` — минимальная длина ответа (после strip).
    - ``max_answer_chars`` — максимальная длина ответа (после strip).
    - ``forbidden_substrings`` — ни одна подстрока не должна встречаться (без учёта регистра).
    - ``any_of_substrings`` — хотя бы одна из подстрок должна быть в ответе (без учёта регистра).
    - ``min_source_count`` — минимальное число source cards в ответе.
    - ``required_debug_keys`` — верхнеуровневые ключи, которые должны быть в ``debug``.

    Debug-based gates (fail-closed: отсутствие обязательного debug-поля = FAIL):
    - ``require_no_fallback: true`` — ``debug["fallback_used"]`` должен быть ``false``.
    - ``require_model: "model-id" | ["model-id", ...]`` — ``debug["llm_model"]`` должен
      совпадать с одним из допустимых значений.
    - ``max_reasoning_tokens: N`` — ``debug["token_usage"]["reasoning_tokens"]`` ≤ N.
    - ``require_system_user: true`` — ``debug["prompt_role_contract"]["format"]`` must be
      ``system_user``; если в ``debug["chat_message_roles"]`` есть фактические роли
      generation-вызовов (с провода), каждый вызов обязан начинаться с ``system`` и
      содержать ``user``.
    - ``allow_user_only_stage: "<stage>"`` — stage должен быть в
      ``LLM_STAGE_USER_ONLY_ALLOWLIST`` (контракт берётся из ``debug`` или реестра).
    """
    text = (answer or "").strip()
    len_text = (length_text if length_text is not None else text).strip()
    checks: dict[str, Any] = {"length": len(len_text)}
    if length_text is not None:
        checks["answer_chars"] = len(text)
    if not expect:
        ok = len(text) >= 10
        checks["non_empty"] = ok
        return ok, checks

    ok = True

    mac = expect.get("min_answer_chars")
    if mac is not None:
        need = int(mac)
        c = len(len_text) >= need
        checks["min_answer_chars"] = c
        ok = ok and c

    max_chars = expect.get("max_answer_chars")
    if max_chars is not None:
        limit = int(max_chars)
        c = len(len_text) <= limit
        checks["max_answer_chars"] = c
        ok = ok and c

    for bad in expect.get("forbidden_substrings") or []:
        b = str(bad)
        if not b:
            continue
        present = b.lower() in text.lower()
        key = f"forbidden:{b[:32]}"
        checks[key] = not present
        ok = ok and (not present)

    any_of = expect.get("any_of_substrings") or []
    if any_of:
        low = text.lower()
        matched = any(str(s).lower() in low for s in any_of if str(s).strip())
        checks["any_of_substrings"] = matched
        ok = ok and matched

    min_sources = expect.get("min_source_count")
    if min_sources is not None:
        count = len(sources or [])
        c = count >= int(min_sources)
        checks["min_source_count"] = c
        checks["source_count"] = count
        ok = ok and c

    required_debug_keys = expect.get("required_debug_keys") or []
    if required_debug_keys:
        dbg = debug if isinstance(debug, dict) else {}
        present = {str(k): str(k) in dbg for k in required_debug_keys if str(k).strip()}
        checks["required_debug_keys"] = present
        ok = ok and all(present.values())

    dbg = debug if isinstance(debug, dict) else {}

    # Gate: require_no_fallback — debug["fallback_used"] must be present and false.
    if expect.get("require_no_fallback"):
        c = "fallback_used" in dbg and not dbg["fallback_used"]
        checks["require_no_fallback"] = c
        if "fallback_used" not in dbg:
            checks["require_no_fallback_missing"] = True
        ok = ok and c

    # Gate: require_model — debug["llm_model"] must equal one of the specified values.
    required_model = expect.get("require_model")
    if required_model is not None:
        actual_model = str(dbg.get("llm_model") or "").strip()
        if isinstance(required_model, (list, tuple, set)):
            allowed_models = [str(m).strip() for m in required_model if str(m).strip()]
        else:
            allowed_models = [str(required_model).strip()]
        c = bool(actual_model) and actual_model in allowed_models
        checks["require_model"] = c
        checks["llm_model_actual"] = actual_model or None
        checks["llm_model_allowed"] = allowed_models
        ok = ok and c

    # Gate: max_reasoning_tokens — guards against hidden thinking/reasoning leakage.
    # Requires a reasoning token counter; missing telemetry fails the gate.
    max_rt = expect.get("max_reasoning_tokens")
    if max_rt is not None:
        token_usage = dbg.get("token_usage") or {}
        rt_raw = token_usage.get("reasoning_tokens")
        if rt_raw is None and isinstance(token_usage.get("total"), dict):
            rt_raw = token_usage["total"].get("reasoning_tokens")
        if rt_raw is None:
            allow_missing = bool(expect.get("allow_missing_reasoning_tokens"))
            checks["max_reasoning_tokens"] = allow_missing
            checks["reasoning_tokens_missing"] = True
            checks["reasoning_tokens_missing_allowed"] = allow_missing
            ok = ok and allow_missing
        else:
            rt = int(rt_raw or 0)
            c = rt <= int(max_rt)
            checks["max_reasoning_tokens"] = c
            checks["reasoning_tokens_actual"] = rt
            ok = ok and c

    if expect.get("require_system_user"):
        contract = dbg.get("prompt_role_contract") if isinstance(dbg.get("prompt_role_contract"), dict) else {}
        fmt = str(contract.get("format") or "").strip().lower()
        c = fmt == "system_user"
        checks["require_system_user"] = c
        checks["prompt_role_contract"] = contract or None
        if not contract:
            checks["require_system_user_missing"] = True
        # Wire-level check: контракт реестра обязателен, но недостаточен — если
        # рантайм записал фактические роли generation chat-вызовов, проверяем их.
        roles_calls = dbg.get("chat_message_roles")
        if isinstance(roles_calls, list) and roles_calls:
            wire_ok = all(
                isinstance(call, (list, tuple))
                and len(call) >= 2
                and str(call[0]).strip().lower() == "system"
                and any(str(r).strip().lower() == "user" for r in call[1:])
                for call in roles_calls
            )
            checks["require_system_user_wire"] = wire_ok
            checks["chat_message_roles"] = [list(map(str, call)) for call in roles_calls]
            c = c and wire_ok
        ok = ok and c

    allowed_stage = expect.get("allow_user_only_stage")
    if allowed_stage is not None:
        stage = str(allowed_stage).strip()
        stage_contract = dbg.get("llm_stage_role_contract")
        if not isinstance(stage_contract, dict):
            # Контракт не пришёл из debug — резолвим из реестра allowlist'а.
            try:
                from app.prompts import get_llm_stage_role_contract

                stage_contract = dict(get_llm_stage_role_contract(stage))
                stage_contract["stage"] = stage
            except Exception:  # noqa: BLE001 - smoke checks report a failed contract instead of aborting the suite.
                stage_contract = {}
        fmt = str(stage_contract.get("format") or "").strip().lower()
        c = fmt == "user_only" and str(stage_contract.get("stage") or "") == stage
        checks["allow_user_only_stage"] = c
        checks["llm_stage_role_contract"] = stage_contract or None
        ok = ok and c

    checks["pass"] = ok
    return ok, checks
