"""W3a: Мнемополис Keeper infra — budget, cache, degrade, no domain writes."""

from __future__ import annotations

from pathlib import Path

import app.mnemo_keeper as keeper
from app.prompts import mnemo_keeper as prompts


def test_prompts_package_has_scenarios_and_silent_copy():
    assert prompts.SCENARIO_GUIDE in prompts.KEEPER_SCENARIOS
    assert prompts.SCENARIO_THREATS in prompts.KEEPER_SCENARIOS
    assert "Хранитель молчит" in prompts.KEEPER_SILENT_COPY
    assert "GUIDE_SYSTEM" in dir(prompts)


def test_module_does_not_import_domain_writers():
    src = Path(keeper.__file__).read_text(encoding="utf-8")
    for marker in (
        "user_state.",
        "workbench_service.",
        "gamification_service.",
        "from app.user_state",
        "from app.workbench_service",
        "from app.gamification_service",
    ):
        assert marker not in src, f"domain writer leak: {marker}"


def test_route_fingerprint_stable():
    a = keeper.route_fingerprint(["rag", "tutor"])
    b = keeper.route_fingerprint(["rag", "tutor"])
    c = keeper.route_fingerprint(["tutor", "rag"])
    assert a == b
    assert a != c
    assert len(a) == 16


def test_build_threats_from_decay_deterministic():
    threats = keeper.build_threats_from_decay(
        decay_vector={"rag": 0.2, "ok": 0.95, "weak": 0.4},
        labels={"rag": "RAG", "weak": "Weak"},
        due_map={"rag": 3},
        forget_min=0.28,
    )
    ids = [t["id"] for t in threats]
    assert "rag" in ids
    assert "weak" in ids
    assert "ok" not in ids
    rag = next(t for t in threats if t["id"] == "rag")
    assert rag["forget_pct"] == 80
    assert rag["due"] == 3
    # sorted by forget desc
    assert threats[0]["forget_pct"] >= threats[-1]["forget_pct"]


def test_request_keeper_degrade_default_no_llm():
    stops = [
        {"id": "rag", "label": "RAG", "worth_reason": "пора повторить"},
        {"id": "agent", "label": "Agent", "worth_reason": "новое"},
    ]
    state: dict = {}
    r = keeper.request_keeper(
        prompts.SCENARIO_GUIDE,
        snapshot_date="2026-07-18",
        day_route=["rag", "agent"],
        stops=stops,
        allow_llm=False,
        session_state=state,
    )
    assert r.source == "degrade"
    assert r.used_llm is False
    assert "RAG" in r.text
    assert "пора повторить" in r.text
    assert r.budget_snapshot["calls"] == 0


def test_cache_hit_second_call_zero_extra_work():
    stops = [{"id": "rag", "label": "RAG", "worth_reason": "x"}]
    state: dict = {}
    r1 = keeper.request_keeper(
        prompts.SCENARIO_GUIDE,
        snapshot_date="2026-07-18",
        stops=stops,
        day_route=["rag"],
        allow_llm=False,
        session_state=state,
    )
    r2 = keeper.request_keeper(
        prompts.SCENARIO_GUIDE,
        snapshot_date="2026-07-18",
        stops=stops,
        day_route=["rag"],
        allow_llm=False,
        session_state=state,
    )
    assert r1.source == "degrade"
    assert r2.source == "cache"
    assert r2.text == r1.text
    assert r2.budget_snapshot["calls"] == 0


def test_budget_blocks_llm_and_degrades():
    stops = [{"id": "rag", "label": "RAG", "worth_reason": "x"}]
    state: dict = {}
    budget = keeper.KeeperBudget(calls=keeper.MAX_CALLS_PER_SESSION)
    state[keeper.KEEPER_BUDGET_SESSION_KEY] = budget
    calls = {"n": 0}

    def boom(system: str, user: str) -> str:
        calls["n"] += 1
        return "should-not-run"

    r = keeper.request_keeper(
        prompts.SCENARIO_GUIDE,
        snapshot_date="2026-07-18",
        stops=stops,
        day_route=["rag"],
        allow_llm=True,
        session_state=state,
        llm_complete=boom,
    )
    assert calls["n"] == 0
    assert r.source == "degrade"
    assert r.reason == "budget_exceeded"
    assert "RAG" in r.text


def test_llm_path_records_budget_and_caches():
    stops = [{"id": "rag", "label": "RAG", "worth_reason": "x"}]
    state: dict = {}
    calls = {"n": 0}

    def fake(system: str, user: str) -> str:
        calls["n"] += 1
        assert "Хранитель" in system or "экскурсовод" in system.lower() or "Memory" in system
        return "1. RAG: короткий рассказ."

    r1 = keeper.request_keeper(
        prompts.SCENARIO_GUIDE,
        snapshot_date="2026-07-18",
        stops=stops,
        day_route=["rag"],
        allow_llm=True,
        session_state=state,
        llm_complete=fake,
    )
    assert r1.source == "llm"
    assert r1.used_llm is True
    assert calls["n"] == 1
    assert r1.budget_snapshot["calls"] == 1
    assert "короткий рассказ" in r1.text

    r2 = keeper.request_keeper(
        prompts.SCENARIO_GUIDE,
        snapshot_date="2026-07-18",
        stops=stops,
        day_route=["rag"],
        allow_llm=True,
        session_state=state,
        llm_complete=fake,
    )
    assert r2.source == "cache"
    assert calls["n"] == 1  # no second LLM call
    assert r2.budget_snapshot["calls"] == 1


def test_llm_error_degrades_fail_closed():
    state: dict = {}

    def boom(system: str, user: str) -> str:
        raise RuntimeError("offline")

    r = keeper.request_keeper(
        prompts.SCENARIO_THREATS,
        threats=[{"id": "rag", "label": "RAG", "forget_pct": 70, "due": 2}],
        allow_llm=True,
        session_state=state,
        llm_complete=boom,
    )
    assert r.source == "degrade"
    assert "llm_error" in r.reason
    assert "RAG" in r.text


def test_threats_static_and_voices():
    r = keeper.request_keeper(
        prompts.SCENARIO_THREATS,
        threats=[{"id": "rag", "label": "RAG", "forget_pct": 60}],
        allow_llm=False,
    )
    assert "детерминированно" in r.text.lower() or "Сводка" in r.text
    v = keeper.request_keeper(prompts.SCENARIO_VOICES, allow_llm=False)
    assert "Туман" in v.text
    assert "забил" not in v.text.lower()


def test_unknown_scenario_silent():
    r = keeper.request_keeper("nope", allow_llm=False)
    assert r.source == "degrade"
    assert r.reason == "unknown_scenario"
    assert "Хранитель молчит" in r.text


def test_estimate_tokens_and_budget_can_afford():
    assert keeper.estimate_tokens("") == 0
    assert keeper.estimate_tokens("abcd") >= 1
    b = keeper.KeeperBudget(calls=0, input_tokens=0, output_tokens=0)
    assert b.can_afford(est_input=100, est_output=50)
    b.calls = b.max_calls
    assert not b.can_afford(est_input=10, est_output=10)


def test_build_guide_view_model_w3b():
    payload = {
        "nodes": [
            {"id": "rag", "label": "RAG", "worth_reason": "пора повторить"},
            {"id": "agent", "label": "Agent", "worth_reason": "новое"},
        ],
        "day_route": ["rag", "agent"],
        "mastery_history": [{"date": "2026-07-18", "mastery": {}}],
    }
    state: dict = {}
    vm = keeper.build_guide_view_model(payload, session_state=state, allow_llm=False)
    assert vm["source"] == "degrade"
    assert vm["used_llm"] is False
    assert "rag" in vm["by_stop"]
    assert "agent" in vm["by_stop"]
    assert "пора повторить" in vm["by_stop"]["rag"] or "RAG" in vm["text"]

    # LLM path with mock — separate cache mode
    def fake(system: str, user: str) -> str:
        return "1. RAG: рассказ.\n2. Agent: дальше."

    vm2 = keeper.build_guide_view_model(
        payload, session_state=state, allow_llm=True, llm_complete=fake
    )
    assert vm2["source"] == "llm"
    assert vm2["used_llm"] is True
    assert "рассказ" in vm2["by_stop"].get("rag", "") or "рассказ" in vm2["text"]


def test_guide_html_bakes_keeper_placeholder():
    from app.ui.knowledge_graph_d3 import build_kg_3d_html

    payload = {
        "nodes": [{"id": "rag", "label": "RAG", "worth_reason": "x", "worth": 1}],
        "edges": [],
        "stats": {},
        "day_route": ["rag"],
    }
    guide = keeper.build_guide_view_model(payload, allow_llm=False)
    html = build_kg_3d_html(payload, keeper_guide=guide)
    assert "keeperbox" in html
    assert "updateKeeperLine" in html
    assert "__KEEPER_GUIDE__" not in html  # replaced
    assert "пора" in html or "маршруте" in html or "RAG" in html
    assert "function updateKeeperLine" in html


def test_build_threats_view_model_w3c():
    payload = {
        "nodes": [
            {"id": "rag", "label": "RAG", "due": 2, "worth": 1},
            {"id": "ok", "label": "OK", "due": 0, "worth": 1},
            {"id": "weak", "label": "Weak", "due": 1, "worth": 1},
        ],
        "day_route": ["rag", "ok"],
        "decay_vector": {"rag": 0.2, "ok": 0.95, "weak": 0.35},
        "mastery_history": [{"date": "2026-07-18", "mastery": {}}],
    }
    state: dict = {}
    vm = keeper.build_threats_view_model(payload, session_state=state, allow_llm=False)
    assert vm["count"] >= 2
    ids = {t["id"] for t in vm["items"]}
    assert "rag" in ids
    assert "ok" not in ids
    assert vm["source"] == "degrade"
    assert vm["review_action"] == "review"
    assert "RAG" in vm["text"] or "угроз" in vm["text"].lower() or "Сводка" in vm["text"]

    def fake(system: str, user: str) -> str:
        return "Сфокусируйся на RAG — повторение займёт пару минут."

    vm2 = keeper.build_threats_view_model(
        payload, session_state=state, allow_llm=True, llm_complete=fake
    )
    assert vm2["source"] == "llm"
    assert "RAG" in vm2["text"] or "пару минут" in vm2["text"]
    # items still deterministic
    assert vm2["count"] == vm["count"]


def test_threats_html_bakes_panel():
    from app.ui.knowledge_graph_d3 import build_kg_3d_html

    payload = {
        "nodes": [{"id": "rag", "label": "RAG", "due": 1, "worth": 1}],
        "edges": [],
        "stats": {},
        "day_route": ["rag"],
        "decay_vector": {"rag": 0.25},
    }
    threats = keeper.build_threats_view_model(payload, allow_llm=False)
    html = build_kg_3d_html(payload, keeper_threats=threats)
    assert "threatsbox" in html
    assert "updateThreatsPanel" in html
    assert "__KEEPER_THREATS__" not in html
    assert "RAG" in html
    assert "forget_pct" in html or "80" in html or "75" in html
