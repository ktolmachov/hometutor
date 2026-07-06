# Architecture Review — hometutor (Incremental)

**Date:** 2026-06-25
**Reviewed pair:** `CODE_ROOT@e385cf5 + DOCS_ROOT@e385cf5`
*(Single working tree — `pip show hometutor` editable location = cwd.)*

**Pre-scan status:** First incremental run. `doc/archive/arch_review_baseline.yaml` was absent; full scope scanned for all phases. Baseline created from this output.

**Path note:** Runtime docs live in `docs/` (not `doc/`). `doc/` holds `assets/` and now `archive/`.

**Correction note (2026-07-06):** metadata/counting errors were corrected after a follow-up audit
against the reviewed commit. Code findings remain historical to `e385cf5`; corrections affect baseline
status, file/test counts, router-count wording, and AR-011 dependency wording.

---

## Executive Summary

The codebase is **architecturally disciplined at its boundaries but structurally heavy in the large**. Hard convention boundaries are clean: every LLM/embedding client is created through `app/provider.py`, every router is registered through `app/api.py`, no backend module imports the UI layer, no UI/router opens SQLite directly, prompts are centralized in `app/prompts/`, and SQL identifiers are allowlist-quoted (no injection vector). The pipeline-step contract `process(QueryContext) -> QueryContext` holds.

Top 3 most impactful findings:
1. `app/log_masking_policy.py` ships a complete PII-redaction API that **nothing imports** — log masking is not wired in (dead code + security-surface gap).
2. ~17 backend modules are defined but never referenced anywhere (dead-code cluster).
3. Pervasive size decay — 23 files exceed 600 lines (peak 1651) and 137 functions exceed 80 lines (peak `render_review` at 440).

---

## Findings Table

| # | ID | Phase | Severity | Status | Finding | File(s) | Evidence (cmd → expected) | Suggested Action |
|---|----|-------|----------|--------|---------|---------|---------------------------|------------------|
| 1 | AR-2026-06-25-001 | 1 | warning | new | Circuit-breaker tuning read via `os.getenv` at import, bypassing `get_settings()` | app/llm_local_circuit.py:48-50 | `rg -n "getenv\(\"LLM_LOCAL_CB" app/llm_local_circuit.py` → 3 matches | Promote `LLM_LOCAL_CB_*` to Settings fields; read via settings object |
| 2 | AR-2026-06-25-002 | 1 | warning | new | E2E offline flag read via `os.getenv` in a service module | app/flashcard_service.py:120 | `rg -n "os.getenv" app/flashcard_service.py` → L120 | Move `HOME_RAG_E2E_OFFLINE` to Settings |
| 3 | AR-2026-06-25-003 | 2 | warning | new | Dead-code cluster: ~17 backend modules plus `app/dummy.py` never imported/called | app/log_masking_policy.py, app/smart_konspekt.py, app/router_eval.py, app/eval_uplift.py, app/eval_ragas_backend.py, app/eval_retrieval_comparison.py, app/ssr_pregeneration.py, app/ssr_weekly_planner.py, app/ssr_graph_routing.py, app/ssr_llm_profile_summary.py, app/session_analytics_parser.py, app/adversarial_test_runner.py, app/answer_parser.py, app/tutor_context_parser.py, app/prompt_smoke_checks.py, app/langfuse_dataset.py, app/index_backup.py, app/dummy.py | `rg -l "\bsmart_konspekt\b" app tests scripts main.py ingest.py telegram_bot.py --type py` → only own file | Confirm per module; delete or wire in |
| 4 | AR-2026-06-25-004 | 4 | warning | new | PII log-masking API fully dead → logs not masked | app/log_masking_policy.py; app/logging_config.py, app/middleware.py (no masking) | `rg -ln "log_masking_policy" --type py` → no matches outside own file | Wire `redact_for_sink` into logging, or remove module |
| 5 | AR-2026-06-25-005 | 2 | info | new | 23 modules > 600 lines (KISS convention; decay-budget, not DoD blocker) | app/ui/knowledge_graph_d3.py:1651 … | size count script → 23 | Track as decay budget; split highest-traffic on next edit |
| 6 | AR-2026-06-25-006 | 2 | info | new | 137 functions > 80 lines (decay-budget, not DoD blocker) | app/ui/flashcards_review_view.py:262 `render_review` (440) … | AST scan → 137 | Extract sub-renders from top offenders |
| 7 | AR-2026-06-25-007 | 5 | warning | new | `pyyaml` imported module-level but absent from requirements.txt | app/ingestion_sections.py:6, app/obsidian_export.py:28 | `rg -in "pyyaml" requirements.txt` → no match | Add `pyyaml` to requirements.txt |
| 8 | AR-2026-06-25-008 | 2 | warning | new | Critical paths untested (pipeline_runner, guardrails, tutor_orchestrator) | tests/ | `rg -l "pipeline_runner\|guardrails" tests/` → no matches | Add invariant tests |
| 9 | AR-2026-06-25-009 | 3 | info | new | No ADR log; architectural choices implicit | docs/ | `find docs -iname "*adr*"` → none | Optional: add `docs/adr.md` |
| 10 | AR-2026-06-25-010 | 4 | info | new | Silent `except Exception: pass` | app/ask_cli.py:75-76 | `rg -nU "except Exception:\s*\n\s*pass" app/ask_cli.py` → L75 | Add rationale comment or log line |
| 11 | AR-2026-06-25-011 | 5 | info | new | Direct dependency ownership unclear: `openai` is a hard undeclared import; `tiktoken` / `python-docx` imports are guarded fallbacks, not hard-fragile failures | app/routers/core.py:8 (openai), app/token_utils.py:10 (tiktoken, guarded), app/explain_service.py:83 (python-docx, guarded), app/ssr_semantic_cache.py:43 | `rg -i "^openai\|tiktoken\|python-docx" requirements.txt` → no direct match | Declare hard deps directly; document or extra-pin guarded optional deps |

---

## Verified-clean (no finding)

- **Provider boundary (1.2):** all OpenAI/Embedding instantiations in provider.py/provider_openai.py only.
- **Prompt centralization (1.3):** 0 hardcoded prompts outside `app/prompts/` + `tutor_prompts.py`.
- **Pipeline contract (1.4):** all steps follow `(ctx: QueryContext) -> QueryContext`.
- **Router structure (1.5):** 16 router implementation files = 16 `include_router` calls; `routers/` has 17 Python files when `__init__.py` is included. No route decorators outside routers.
- **Coupling (1.7 / 2.3):** 0 backend→UI imports; only api.py imports routers; no UI/router opens SQLite.
- **Guardrails at entrypoints (1.10):** query, ask_cli, telegram, quiz, flashcards all reference guardrails/input_validation.
- **SQL injection (4.2):** identifiers pass through `_quote_allowed_identifier` against frozenset allowlists.
- **CORS (4.2):** localhost-only with specific origins, `allow_credentials=True` — appropriate for local service.
- **SM-2 duplication (2.2):** `flashcards_scheduling.py` reuses `apply_sm2` from `spaced_repetition.py` — not duplicate.
- **Doc-code drift (3.2):** sampled API endpoints and architecture entrypoints all match reality.

---

## Metrics Snapshot

- **Total `app/` Python files (recursive):** 335 (top-level 209, routers 17 including `__init__.py`, ui 96, ui/pages 3, prompts 4, other subdirs 6)
- **Total project test files:** 6
- **Modules > 600 lines:** 23 — top: ui/knowledge_graph_d3.py (1651), prompts/_impl.py (1533), knowledge_graph.py (1108), course_cache.py (1053), query_service.py (960), flashcard_service.py (914), course_graph_compiler.py (846), ui/mission_control.py (825), ui/flashcards_review_view.py (702), tutor_orchestrator.py (696), config.py (694), provider.py (683), ui/home_hub.py (670), learner_model_service.py (664), quiz_parse.py (662), ui/resume_cards_tutor.py (658), ui/interactive_quiz.py (644), ui/tutor_chat_session.py (639), graph_retrieval.py (623), ui/tutor_chat_quiz.py (617), user_state_db.py (613), ui/helpers.py (607), ui/course_prepare_view.py (607)
- **Functions > 80 lines:** 137 (top 10): render_review (440), render_tutor_chat_tab (337), _ensure_schema (306), render_topics_plan_subtab (306), _render_learning_progress_tab (295), render_query_answer_section (269), _render_interactive_quiz_tab (267), render_scoped_self_check_quiz (255), execute_rag_query (246), render_generate (245)
- **Convention violations:** 2 warning (config access)
- **ADR drift instances:** 0 (no ADR log exists)
- **Doc-code drift instances:** 0 confirmed
- **Dead-code candidates:** 17 backend modules + `app/dummy.py` (tracked under AR-2026-06-25-003)
- **Duplication clusters:** 0 confirmed

---

## Recommended Actions (prioritized)

1. **Wire in or remove `log_masking_policy.py`** — false security assurance + real leak risk. Scope: S. Epoch: `obs-log-masking`.
2. **Triage dead-code cluster** — 17 unreferenced modules inflate every future review. Scope: M. Epoch: `cleanup-dead-modules`.
3. **Move `LLM_LOCAL_CB_*` and `HOME_RAG_E2E_OFFLINE` into Settings** — import-time `os.getenv` bypasses single config source. Scope: S.
4. **Declare `pyyaml` in requirements.txt** — module-level import breaks on transitive-dep drop. Scope: S.
5. **Add invariant tests for pipeline + guardrails** — highest-risk paths have zero coverage. Scope: M. Epoch: `tests-critical-paths`.
6. **Split `render_review` (440 lines)** — recently-churned file, extraction lowers blast-radius. Scope: S–M.
7. *(Optional)* **Add minimal `docs/adr.md`** — capture SQLite-for-state, aiogram, Chroma choices. Scope: S.

---

## Fix Prompts

### Phase 1 — Config access

```text
Goal: fix Phase 1 findings from doc/archive/arch_review_2026-06-25.md.
Ignore prior responses/tools. Fresh context only.
Baseline: doc/archive/arch_review_baseline.yaml
Report:   doc/archive/arch_review_2026-06-25.md

Findings to fix (warning, Phase 1, by baseline ID):
- AR-2026-06-25-001: LLM_LOCAL_CB_* read via os.getenv at import (app/llm_local_circuit.py:48-50)
- AR-2026-06-25-002: HOME_RAG_E2E_OFFLINE read via os.getenv (app/flashcard_service.py:120)

Write-set (<= 5 files):
- app/config.py
- app/llm_local_circuit.py
- app/flashcard_service.py
- scripts/check_config_access.py        # new guard
- docs/conventions_architecture.md      # rule cross-ref

Read ONLY:
- app/config.py — Settings/RetrievalSettings field block only
- app/llm_local_circuit.py — signatures + lines 25-50

Do not touch:
- modules from other phases (dead-code, sizes, deps, tests)
- app/ingestion_env_diag.py (diagnostic — allowed os.environ)

DoD (one per finding = evidence_cmd):
- AR-2026-06-25-001: rg -n "getenv\(\"LLM_LOCAL_CB" app/llm_local_circuit.py → no match
- AR-2026-06-25-002: rg -n "os.getenv" app/flashcard_service.py → no match

Regression Guard (mandatory):
- AR-...-001/002: new scripts/check_config_access.py (fails if app/*.py except config.py/ingestion_env_diag.py contains os.getenv/os.environ); aggregate into scripts/arch_regression_guards.py
- AR-...-001/002: new rule in docs/conventions_architecture.md §Конфигурация citing the IDs

Post-fix baseline update:
- Mark AR-2026-06-25-001/002 status=resolved in doc/archive/arch_review_baseline.yaml
  with resolved_date=<today>. Do NOT remove entries — keep history.

Token budget:
- Target <=12k input tokens.
- Hard stop >20k input tokens.
- If estimated input is 12k-20k, compress before sending.
- No retry with unchanged payload.

Output: changed files + tests run + guard(s) added + unresolved risk.
```

### Phase 2 — Structural health (split A/B; merge A before B)

```text
Goal: fix Phase 2 findings from doc/archive/arch_review_2026-06-25.md.
Ignore prior responses/tools. Fresh context only.
Baseline: doc/archive/arch_review_baseline.yaml
Report:   doc/archive/arch_review_2026-06-25.md

Findings to fix (warning, Phase 2, by baseline ID):
- AR-2026-06-25-003: dead-code cluster (~17 unreferenced backend modules)
- AR-2026-06-25-008: critical paths untested

SLICE A (dead code) — Write-set (<= 5 files):
- app/dummy.py + confirmed-dead modules (delete after per-module owner confirm)
- scripts/check_dead_modules.py            # new import-graph orphan detector
NOTE: confirm each module against main.py/ingest.py/telegram_bot.py/scripts/ before deleting.
      index_backup.py is named in conventions — wire it or annotate as future-use, do NOT silently delete.

SLICE B (tests) — Write-set (<= 5 files):
- tests/test_pipeline_invariants.py        # new
- tests/test_guardrails_invariants.py      # new

Read ONLY:
- app/pipeline_runner.py — run_pipeline signature only
- app/guardrails.py — public entry signatures only

Do not touch:
- Phase 1/4/5 zones; size/long-function refactors (AR-...-005/006 are decay-budget, not this fix)

DoD:
- AR-2026-06-25-003: scripts/check_dead_modules.py → 0 orphans (or each remaining annotated keep-reason)
- AR-2026-06-25-008: pytest tests/test_pipeline_invariants.py tests/test_guardrails_invariants.py → pass

Regression Guard (mandatory):
- AR-...-003: scripts/check_dead_modules.py aggregated into scripts/arch_regression_guards.py
- AR-...-008: the two invariant tests are themselves the guard

Post-fix baseline update:
- Mark AR-2026-06-25-003/008 status=resolved in doc/archive/arch_review_baseline.yaml
  with resolved_date=<today>. Do NOT remove entries — keep history.

Token budget:
- Target <=12k input tokens.
- Hard stop >20k input tokens.
- If estimated input is 12k-20k, compress before sending.
- No retry with unchanged payload.

Output: changed files + tests run + guard(s) added + unresolved risk.

Optional follow-up (info / decay-budget, NOT in DoD):
- AR-2026-06-25-005: split files >600 lines (start query_service.py, flashcard_service.py)
- AR-2026-06-25-006: extract render_review (440 lines) into sub-renders
```

### Phase 4 — Implementation quality / security

```text
Goal: fix Phase 4 findings from doc/archive/arch_review_2026-06-25.md.
Ignore prior responses/tools. Fresh context only.
Baseline: doc/archive/arch_review_baseline.yaml
Report:   doc/archive/arch_review_2026-06-25.md

Findings to fix (warning, Phase 4, by baseline ID):
- AR-2026-06-25-004: PII log-masking API dead → logs never masked (app/log_masking_policy.py)

Write-set (<= 5 files):
- app/logging_config.py          # apply redact_for_sink in a logging.Filter
- app/log_masking_policy.py       # only if API tweak needed
- tests/test_logging_invariants.py   # new

Read ONLY:
- app/log_masking_policy.py — public def signatures only (lines 51-145)
- app/logging_config.py — handler/formatter setup only

Do not touch:
- Phase 1/2/5 zones

DoD:
- AR-2026-06-25-004: rg -ln "log_masking_policy" --type py → app/logging_config.py present
- AR-2026-06-25-004: pytest tests/test_logging_invariants.py::test_sink_payload_is_masked → pass

Regression Guard (mandatory):
- AR-...-004: tests/test_logging_invariants.py asserts a record with PII fields is redacted at the sink

Post-fix baseline update:
- Mark AR-2026-06-25-004 status=resolved in doc/archive/arch_review_baseline.yaml
  with resolved_date=<today>. Do NOT remove entries — keep history.

Token budget:
- Target <=12k input tokens.
- Hard stop >20k input tokens.
- If estimated input is 12k-20k, compress before sending.
- No retry with unchanged payload.

Output: changed files + tests run + guard(s) added + unresolved risk.

Optional follow-up (info, NOT in DoD):
- AR-2026-06-25-010: add rationale/log to except Exception: pass at app/ask_cli.py:75
```

### Phase 5 — Dependency hygiene

```text
Goal: fix Phase 5 findings from doc/archive/arch_review_2026-06-25.md.
Ignore prior responses/tools. Fresh context only.
Baseline: doc/archive/arch_review_baseline.yaml
Report:   doc/archive/arch_review_2026-06-25.md

Findings to fix (warning, Phase 5, by baseline ID):
- AR-2026-06-25-007: pyyaml imported (module-level) but undeclared in requirements.txt

Write-set (<= 5 files):
- requirements.txt
- scripts/check_requirements_imports.py   # new

Read ONLY:
- requirements.txt
- app/ingestion_sections.py — import block only

Do not touch:
- Phase 1/2/4 zones

DoD:
- AR-2026-06-25-007: rg -in "pyyaml" requirements.txt → match

Regression Guard (mandatory):
- AR-...-007: scripts/check_requirements_imports.py (top-level third-party imports in app/ must appear in requirements.txt, alias-aware); aggregate into scripts/arch_regression_guards.py

Post-fix baseline update:
- Mark AR-2026-06-25-007 status=resolved in doc/archive/arch_review_baseline.yaml
  with resolved_date=<today>. Do NOT remove entries — keep history.

Token budget:
- Target <=12k input tokens.
- Hard stop >20k input tokens.
- If estimated input is 12k-20k, compress before sending.
- No retry with unchanged payload.

Output: changed files + tests run + guard(s) added + unresolved risk.

Optional follow-up (info, NOT in DoD):
- AR-2026-06-25-011: declare openai directly (module-level import in app/routers/core.py:8)
```
