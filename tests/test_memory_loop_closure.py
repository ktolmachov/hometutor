from types import SimpleNamespace

import pytest

import app.flashcard_service as flashcard_service
import app.learner_model_service as learner_model_service
import app.llm_resilience as llm_resilience
import app.query_rag_assembly as query_rag_assembly
import app.query_response_postprocessing as qrp
import app.query_session_persistence as query_session_persistence
import app.query_tutor_context as query_tutor_context
import app.ui.tutor_chat_response_render as tutor_chat_response_render


def test_tutor_postprocessing_sends_non_empty_learner_outcome(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr("app.knowledge_graph.get_graph_prerequisites_health", lambda: {})
    monkeypatch.setattr(
        "app.tutor_orchestrator.apply_tutor_self_correction",
        lambda teaching, **_kwargs: teaching,
    )
    monkeypatch.setattr(
        "app.tutor_orchestrator.decide_tutor_next_action",
        lambda **_kwargs: {"next_action": "continue"},
    )
    monkeypatch.setattr(
        "app.user_state.update_tutor_learner_profile_from_session",
        lambda metadata: {"ok": True},
    )
    monkeypatch.setattr(
        "app.quiz_service.format_tutor_v2_markdown",
        lambda teaching: "formatted",
    )
    monkeypatch.setattr(
        qrp,
        "get_settings",
        lambda: SimpleNamespace(
            enable_tutor_inline_quiz=False,
            tutor_inline_quiz_separate_llm_call=False,
        ),
    )

    def fake_update(user_id, interaction_type, outcome, *, session_id=None):
        captured["user_id"] = user_id
        captured["interaction_type"] = interaction_type
        captured["outcome"] = outcome
        captured["session_id"] = session_id
        return {
            "mastery_updated": True,
            "profile_saved": True,
            "updated_concepts": {"cid:state-machines": 0.48},
        }

    monkeypatch.setattr(
        "app.learner_model_service.update_learner_model_after_interaction",
        fake_update,
    )
    ctx = SimpleNamespace(
        metadata={"current_topic": "state machines"},
        effective_query="Explain state machines",
    )
    options = SimpleNamespace(session_id="sid-1")

    qrp._apply_tutor_teaching_postprocessing(
        response=SimpleNamespace(),
        ctx=ctx,
        options=options,
        sources=[{"relative_path": "lesson.md"}],
        tutor_teaching={"key_idea": "x"},
        inline_quiz=[],
        original_question="Explain state machines",
        logger=SimpleNamespace(warning=lambda *_args, **_kwargs: None),
    )

    outcome = captured["outcome"]
    assert captured["interaction_type"] == "tutor"
    assert isinstance(outcome, dict)
    assert outcome["concept_gains"] == {"state machines": 0.48}
    assert outcome["source_count"] == 1
    assert outcome["session_id"] == "sid-1"
    assert ctx.metadata["learner_trace"]["canonical_concept_id"] == "cid:state-machines"


def test_tutor_postprocessing_does_not_show_trace_when_concept_unresolved(monkeypatch) -> None:
    monkeypatch.setattr("app.knowledge_graph.get_graph_prerequisites_health", lambda: {})
    monkeypatch.setattr(
        "app.tutor_orchestrator.apply_tutor_self_correction",
        lambda teaching, **_kwargs: teaching,
    )
    monkeypatch.setattr(
        "app.tutor_orchestrator.decide_tutor_next_action",
        lambda **_kwargs: {"next_action": "continue"},
    )
    monkeypatch.setattr(
        "app.user_state.update_tutor_learner_profile_from_session",
        lambda metadata: {"ok": True},
    )
    monkeypatch.setattr("app.quiz_service.format_tutor_v2_markdown", lambda teaching: "formatted")
    monkeypatch.setattr(
        qrp,
        "get_settings",
        lambda: SimpleNamespace(
            enable_tutor_inline_quiz=False,
            tutor_inline_quiz_separate_llm_call=False,
        ),
    )
    monkeypatch.setattr(
        "app.learner_model_service.update_learner_model_after_interaction",
        lambda *_args, **_kwargs: {
            "mastery_updated": False,
            "profile_saved": True,
            "updated_concepts": {},
        },
    )

    ctx = SimpleNamespace(metadata={"current_topic": "general"}, effective_query="Explain")

    qrp._apply_tutor_teaching_postprocessing(
        response=SimpleNamespace(),
        ctx=ctx,
        options=SimpleNamespace(session_id="sid-1"),
        sources=[],
        tutor_teaching={"key_idea": "x"},
        inline_quiz=[],
        original_question="Explain",
        logger=SimpleNamespace(warning=lambda *_args, **_kwargs: None),
    )

    assert "learner_trace" not in ctx.metadata


def test_learner_trace_roundtrips_to_history_metadata_and_renderer(monkeypatch) -> None:
    trace = {
        "concept": "State Machine",
        "canonical_concept_id": "cid:state-machine",
        "mastery_score": 0.48,
        "source_count": 2,
    }
    ctx = SimpleNamespace(
        metadata={
            "learner_trace": trace,
            "tutor_decision": {"next_action": "continue"},
            "persisted_learner_profile": {"ok": True},
        },
        trace={},
    )
    proc_result = {
        "tutor_teaching": {"teaching_summary": "summary"},
        "inline_quiz": [],
        "socratic_followup": None,
        "auto_quiz_payload": None,
    }

    _tutor_answer, _tutor_payload, assistant_meta = query_rag_assembly.build_tutor_payloads(
        options=SimpleNamespace(query_mode="tutor", homework_mode=False, session_id="sid-1"),
        ctx=ctx,
        proc_result=proc_result,
        answer_text="answer",
        logger=SimpleNamespace(warning=lambda *_args, **_kwargs: None),
    )
    assert assistant_meta is not None
    assert assistant_meta["tutor"]["learner_trace"] == trace

    saved_history = {}

    class FakeSessionStore:
        def get(self, _sid):
            return []

        def save(self, sid, history):
            saved_history["sid"] = sid
            saved_history["history"] = history
            return {"ok": True}

    monkeypatch.setattr(
        query_session_persistence.importlib,
        "import_module",
        lambda _name: SimpleNamespace(session_store=FakeSessionStore()),
    )
    query_session_persistence.persist_chat_session(
        session_id="sid-1",
        user_question="question",
        assistant_answer="answer",
        confidence=0.9,
        assistant_metadata=assistant_meta,
        sources=[],
    )
    assistant_msg = saved_history["history"][-1]
    assert assistant_msg.metadata["tutor"]["learner_trace"] == trace

    captions: list[str] = []

    class DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(tutor_chat_response_render.st, "caption", captions.append)
    monkeypatch.setattr(tutor_chat_response_render.st, "columns", lambda _n: [DummyColumn()] * 3)
    monkeypatch.setattr(tutor_chat_response_render.st, "success", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tutor_chat_response_render.st, "warning", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tutor_chat_response_render.st, "info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tutor_chat_response_render.st, "markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tutor_chat_response_render,
        "render_tutor_visibility_badge",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        tutor_chat_response_render,
        "render_teaching_summary_block",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        tutor_chat_response_render,
        "render_tutor_trust_panel",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        tutor_chat_response_render,
        "render_tutor_action_panel",
        lambda *_args, **_kwargs: None,
    )

    tutor_chat_response_render.render_tutor_structured_response(
        {"teaching_summary": "summary"},
        msg_idx=1,
        session_id="sid-1",
        tutor_meta=assistant_msg.metadata["tutor"],
    )

    assert any("След записан" in caption for caption in captions)
    assert any("State Machine" in caption for caption in captions)


def test_tutor_payload_can_contain_only_learner_trace() -> None:
    trace = {
        "concept": "State Machine",
        "canonical_concept_id": "cid:state-machine",
        "mastery_score": 0.48,
        "source_count": 2,
    }

    payload = query_tutor_context._build_tutor_payload(
        tutor_teaching=None,
        tutor_decision=None,
        auto_quiz_payload=None,
        inline_quiz=None,
        socratic_followup=None,
        learner_profile=None,
        learner_trace=trace,
    )

    assert payload is not None
    assert payload["learner_trace"] == trace


def test_canonical_concept_resolver_matches_graph_fields(monkeypatch) -> None:
    concepts = {
        "cid:state-machine": {
            "label": "State Machine",
            "aliases": ["finite automaton", "машина состояний"],
            "documents": ["course/lesson.md"],
            "related_documents": ["course/extra.md"],
        },
        "cid:idempotency": {
            "label": "Idempotency keys",
            "aliases": ["идемпотентность"],
            "documents": ["course/tools.md"],
        },
    }
    monkeypatch.setattr(
        learner_model_service,
        "get_active_knowledge_graph",
        lambda: SimpleNamespace(get_concepts=lambda: concepts),
    )

    resolve = learner_model_service.resolve_canonical_concept_id_for_learner_signal

    assert resolve("state machine") == "cid:state-machine"
    assert resolve("машина состояний") == "cid:state-machine"
    assert resolve("Why finite automaton helps") == "cid:state-machine"
    assert resolve("unrelated", source_path="course/tools.md") == "cid:idempotency"
    assert resolve("unrelated", source_path="notes/course/extra.md") == "cid:state-machine"
    assert resolve("totally unrelated") is None


def test_learner_model_flashcard_outcome_updates_profile(monkeypatch) -> None:
    profile = learner_model_service.PersonalizedLearnerModel(
        user_id="local",
        mastery_vector={"existing": 0.2, "avg": 0.2},
        learning_velocity=0.1,
        sessions_completed=1,
        confidence_indicator=0.5,
        cognitive_load=0.5,
    )
    saved: dict[str, object] = {}

    monkeypatch.setattr(
        learner_model_service,
        "get_personalized_learner_profile",
        lambda user_id, session_id=None: profile,
    )
    monkeypatch.setattr(
        learner_model_service,
        "save_learner_profile",
        lambda user_id, data: saved.update(data),
    )
    monkeypatch.setattr(learner_model_service, "save_emotional_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        learner_model_service,
        "AdaptiveDailyPlan",
        lambda *_args, **_kwargs: SimpleNamespace(build_adaptive_daily_plan=lambda: {}),
    )
    monkeypatch.setattr(
        learner_model_service,
        "resolve_canonical_concept_id_for_learner_signal",
        lambda *_args, **_kwargs: "concept:state-machines",
    )

    result = learner_model_service.update_learner_model_after_interaction(
        "local",
        "flashcard",
        {
            "mastery_gain": 0.8,
            "concept_gains": {"state machines": 0.8},
            "concept": "state machines",
        },
    )

    assert saved["mastery_vector"]["concept:state-machines"] == 0.8
    assert saved["sessions_completed"] == 1
    assert saved["state_migration"]["learning_interactions_total"] == 1
    assert saved["state_migration"]["learning_interactions_by_type"] == {"flashcard": 1}
    assert saved["learning_velocity"] > 0.1
    assert saved["confidence_indicator"] > 0.5
    assert saved["cognitive_load"] < 0.5
    assert result["mastery_updated"] is True
    assert result["updated_concepts"] == {"concept:state-machines": 0.8}


def test_learner_model_quiz_outcome_preserves_session_semantics(monkeypatch) -> None:
    profile = learner_model_service.PersonalizedLearnerModel(
        user_id="local",
        mastery_vector={"cid:state-machines": 0.8, "avg": 0.8},
        learning_velocity=0.4,
        sessions_completed=1,
        confidence_indicator=0.5,
        cognitive_load=0.5,
    )
    saved: dict[str, object] = {}

    monkeypatch.setattr(
        learner_model_service,
        "get_personalized_learner_profile",
        lambda user_id, session_id=None: profile,
    )
    monkeypatch.setattr(
        learner_model_service,
        "save_learner_profile",
        lambda user_id, data: saved.update(data),
    )
    monkeypatch.setattr(learner_model_service, "save_emotional_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        learner_model_service,
        "AdaptiveDailyPlan",
        lambda *_args, **_kwargs: SimpleNamespace(build_adaptive_daily_plan=lambda: {}),
    )

    result = learner_model_service.update_learner_model_after_interaction(
        "local",
        "quiz",
        {
            "mastery_gain": 0.2,
            "concept_gains": {"cid:state-machines": 0.2},
            "concept": "cid:state-machines",
        },
    )

    assert saved["mastery_vector"]["cid:state-machines"] == 0.2
    assert saved["sessions_completed"] == 2
    assert "learning_interactions_total" not in saved["state_migration"]
    assert result["mastery_updated"] is True
    assert result["updated_concepts"] == {"cid:state-machines": 0.2}


def test_flashcard_review_writes_user_action_learner_state(monkeypatch) -> None:
    card = {
        "id": 7,
        "deck_id": 3,
        "easiness": 2.5,
        "interval_days": 1,
        "repetitions": 0,
        "tags": "state machine, source:course/lesson.md",
    }
    learner_state_calls: list[dict[str, object]] = []
    learner_model_calls: list[dict[str, object]] = []

    monkeypatch.setattr(flashcard_service, "get_flashcard_by_id", lambda card_id: card)
    monkeypatch.setattr(flashcard_service, "update_flashcard_sr", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(flashcard_service, "record_flashcard_review_log", lambda **_kwargs: 1)
    monkeypatch.setattr(flashcard_service, "append_flashcard_rating_history", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.user_state.increment_weekly_progress", lambda *_args, **_kwargs: None)

    def fake_apply_user_action(**kwargs):
        learner_state_calls.append(kwargs)
        return {"provenance": {"source_type": "user_action"}}

    def fake_update_learner_model(user_id, interaction_type, outcome, *, session_id=None):
        learner_model_calls.append(
            {
                "user_id": user_id,
                "interaction_type": interaction_type,
                "outcome": outcome,
                "session_id": session_id,
            }
        )

    monkeypatch.setattr(
        "app.fact_source_binding.apply_user_action_outcome_to_learner_state",
        fake_apply_user_action,
    )
    monkeypatch.setattr(
        "app.learner_model_service.resolve_canonical_concept_id_for_learner_signal",
        lambda *_args, **_kwargs: "cid:state-machine",
    )
    monkeypatch.setattr(
        "app.learner_model_service.update_learner_model_after_interaction",
        fake_update_learner_model,
    )

    result = flashcard_service.review_flashcard(7, 4)

    assert learner_state_calls[0]["concept"] == "cid:state-machine"
    assert learner_state_calls[0]["score"] == 0.8
    assert learner_state_calls[0]["action"] == "flashcard_review"
    assert learner_model_calls[0]["interaction_type"] == "flashcard"
    assert learner_model_calls[0]["outcome"]["concept_gains"] == {"cid:state-machine": 0.8}
    assert result["learner_state"] == {"provenance": {"source_type": "user_action"}}


def test_llm_resilience_skips_call_when_local_circuit_open(monkeypatch) -> None:
    class FakeLlm:
        home_rag_llm_api_base = "http://127.0.0.1:1234/v1"

        def complete(self, *_args, **_kwargs):
            raise AssertionError("complete must not be called when circuit is open")

    monkeypatch.setattr(llm_resilience, "_circuit_open", lambda base_url: True)

    with pytest.raises(RuntimeError, match="circuit is open"):
        llm_resilience.complete_with_resilience(
            FakeLlm(),
            "prompt",
            stage="unit",
            allow_provider_fallback=False,
        )


def test_llm_resilience_soft_timeout_fires_for_local_llm(monkeypatch) -> None:
    import time as _time

    class FakeLlm:
        home_rag_llm_api_base = "http://127.0.0.1:1234/v1"

        def complete(self, *_args, **_kwargs):
            _time.sleep(10)  # much longer than the soft timeout we set

    failures: list[tuple[str, str]] = []
    monkeypatch.setattr(llm_resilience, "_circuit_open", lambda base_url: False)
    monkeypatch.setattr(llm_resilience, "_record_circuit_success", lambda base_url: None)
    monkeypatch.setattr(
        llm_resilience,
        "_record_circuit_failure",
        lambda base_url, exc: failures.append((base_url, type(exc).__name__)),
    )
    monkeypatch.setattr(
        llm_resilience,
        "_local_soft_timeout_sec",
        lambda settings: 0.001,
    )

    with pytest.raises(TimeoutError):
        llm_resilience.complete_with_resilience(
            FakeLlm(),
            "prompt",
            stage="unit_soft_timeout",
            allow_provider_fallback=False,
        )

    assert any("TimeoutError" in str(exc) for _, exc in failures), (
        f"expected TimeoutError in failures: {failures}"
    )


def test_llm_resilience_records_connection_failure(monkeypatch) -> None:
    class APIConnectionError(Exception):
        pass

    class FakeLlm:
        home_rag_llm_api_base = "http://127.0.0.1:1234/v1"

        def complete(self, *_args, **_kwargs):
            raise APIConnectionError("offline")

    failures: list[tuple[str, str]] = []
    monkeypatch.setattr(llm_resilience, "_circuit_open", lambda base_url: False)
    monkeypatch.setattr(llm_resilience, "_record_circuit_success", lambda base_url: None)
    monkeypatch.setattr(
        llm_resilience,
        "_record_circuit_failure",
        lambda base_url, exc: failures.append((base_url, type(exc).__name__)),
    )

    with pytest.raises(APIConnectionError):
        llm_resilience.complete_with_resilience(
            FakeLlm(),
            "prompt",
            stage="unit",
            allow_provider_fallback=False,
        )

    assert failures == [("http://127.0.0.1:1234/v1", "APIConnectionError")]
