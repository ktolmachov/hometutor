# hometutor Project Rules for Claude

**Last updated:** 2026-07-05
**Status:** Active — apply to all Claude Code sessions in this project

---

## 📋 Project Brief

**hometutor** is a local-first Python RAG (Retrieval-Augmented Generation) application for
adaptive tutoring: graph-based knowledge retrieval, learner state persistence, spaced
repetition, and LLM-based answer generation with source grounding.

**Tech stack:** FastAPI (port 8000), Streamlit UI (port 8501), CLI (`ask` → `app/ask_cli.py`),
Telegram bot (`app/telegram_handlers.py`), Chroma + llama-index (hybrid BM25 + vector
retrieval), SQLite (user state / auth), optional JWT + bcrypt auth.

**LLM / embeddings access:** exclusively through the provider layer: public factories in
`app/provider.py` and the internal OpenAI-compatible adapter in `app/provider_openai.py`
(local model via LM Studio, cloud via OpenRouter/OpenAI), with `LOCAL_STRICT` /
`BALANCED` / `CLOUD_FAST` profiles and circuit-breaker fallback. There is no LangChain and no
native Anthropic SDK dependency in this codebase — do not assume either.

**Single repository:** unlike some sibling projects, `hometutor` is **one** git working tree.
`app/`, `tests/`, `scripts/`, `docs/` all live directly under this repo root
(`D:\Projects\hometutor`). There is **no** separate CODE_ROOT/DOCS_ROOT split here — every
path in this document resolves against the current working directory.

**Key source-of-truth docs:** current runtime documentation lives under `docs/`, not
`doc/`. `doc/archive/` may contain legacy/archive artifacts, but it is not the working
docs root and not the source of current backlog/workflow state.
- **🧭 [`docs/index.md`](docs/index.md) — START HERE** — navigation hub by role (user, demo,
  backend, architect, developer, devops)
- `docs/conventions.md` — short engineering TL;DR + navigation to details
- `docs/conventions_architecture.md` — architectural boundaries (config, persistence, retrieval)
- `docs/conventions_reference.md` — prompts, API, error handling, testing, doc-sync rules
- `docs/api_reference.md` — HTTP contract; `docs/architecture.md` — runtime architecture

There is a separate sibling repository, `hometutor-studio`, that holds backlog/process
artifacts (`doc/backlog_registry.yaml`, `doc/team_workflow/`, `scripts/workflow.py`, etc.).
That repo is **not** required for code changes in `hometutor` and is out of scope for this
document. If a prompt or rule references `doc/...` paths or workflow scripts that don't exist
in this checkout, they belong to `hometutor-studio` or legacy/archive material — flag it instead
of guessing.

---

## 🎯 Context Policy for Claude Code

**Keep every LLM call reasonably small; avoid reading whole large files when a section or
grep suffices.**

### 1. Read-Set Rules

- Prefer 2–5 files per call; don't fetch files outside what the task actually needs.
- For large Python modules, prefer `grep "^class |^def "` (signatures) over a full read
  when you only need the API surface.
- For large test files, read the specific `def test_<name>(...)` block you need, or list
  `def test_` names first.
- For docs, read the relevant section/table, not the whole file, unless it's short
  (most `docs/*.md` files here are short — check length first if unsure).

### 2. Known Large Areas

- `app/` has 200+ modules (see `docs/architecture.md` for the module map); don't glob-read
  the whole package — target the specific module(s) named in the task.
- `app/ui/` has 100+ Streamlit view modules; same rule applies.
- `tests/` currently has ~40 files; there is no single "core" test suite file — tests are
  named after the feature area (e.g. `test_auth.py`, `test_flashcards_scheduling.py`).

### 3. Retry Policy

- Don't resend an identical failing payload; narrow the file list or use grep/signatures
  first, then retry once.

---

## 🔧 Working Conventions

### Code Changes

1. **Write-set first:** confirm which files can be changed before editing.
2. **Scope tight:** no unrelated refactors/renames/formatting in the same change.
3. **Hard rules (blocker if violated):**
   - Runtime/app config only via `get_settings()` / `get_retrieval_settings()`
     (`app/config.py`). Direct env access is allowed in `app/config.py`,
     diagnostic `app/ingestion_env_diag.py`, and operational scripts.
   - LLM/embeddings only via the provider layer (`app/provider.py` plus internal
     adapter `app/provider_openai.py`).
   - Prompt text source-of-truth is `app/prompts/` (`app/prompts/_impl.py`).
     Bridge/builders such as `app/tutor_prompts.py` and `app/deep_study_prompt.py`
     must import/build from that package, not duplicate prompt text.
   - Endpoint logic only in `app/routers/*`; register new routers with
     `app.include_router(...)` in `app/api.py` (use `dependencies=_protected_dependencies`
     for protected endpoints).
   - Pipeline steps keep the `process(QueryContext) -> QueryContext` contract
     (`app/pipeline_steps.py`, `app/pipeline_runner.py`).
   - User-state persistence only via `app/user_state*.py` helpers; auth via
     `app/auth_service.py`. No ad hoc SQLite connections in services/routers/UI.
   - All entry points (API, CLI, UI, Telegram) go through
     `app/guardrails.py` / `app/input_validation.py`.
   - New code must not add bare `except:`. Broad `except Exception` in new or touched
     code needs `# noqa: BLE001` + a reason; when touching existing broad catches,
     bring that local block up to the rule within the write-set.
4. **Test mandatory:** run the tests for the affected area before calling a change done
   (see § Test Selection). Full `pytest` run only on explicit request.
5. **Doc sync required:** if API/UI/architecture behavior changes, update the matching
   `docs/*.md` file (see § Document Sync).

### Document Sync

When code changes, update these **if affected** (all under `docs/`):

- `docs/api_reference.md` — if the HTTP contract changed
- `docs/user_guide.md` / `docs/quickstart.md` — if user-facing UI behavior changed
- `docs/architecture.md`, `docs/technical_specification.md`,
  `docs/conventions_architecture.md` — if architecture/config/persistence changed
- `docs/conventions.md` / `docs/conventions_reference.md` — if engineering rules changed
- `.env.example`, `config.env` — if new settings were introduced

There is no current `doc/changelog.md` or `doc/backlog_registry.yaml` in this repo — don't
try to update them here. `doc/archive/` is legacy/archive only; active process bookkeeping
lives in `hometutor-studio`, if relevant.

### Test Selection

Never run tests without a clear reason. Prefer targeted test files, picked by feature area
(there is no single canonical "core" bundle — pick from `tests/*.py` by keyword):

```bash
# Auth
pytest tests/test_auth.py tests/test_auth_integration.py

# Flashcards
pytest tests/test_flashcards_scheduling.py tests/test_flashcards_memory_signals.py

# Guardrails / pipeline invariants
pytest tests/test_guardrails_invariants.py tests/test_pipeline_invariants.py

# Retrieval / ingestion
pytest tests/test_hybrid_retrieval_bm25.py tests/test_retrieval_context_budget.py
pytest tests/test_ingestion_support.py tests/test_reindex_poll.py

# UI / navigation
pytest tests/test_navigation_visibility.py tests/test_feature_registry.py
```

Run via `.\.venv\Scripts\python.exe -m pytest ...` (fallback `python`/`py` if `.venv` is
unavailable). Reranker defaults to `ENABLE_RERANKER=true`; disable it only for targeted
tests/commands that explicitly need that.

---

## ✅ Positive Patterns to Preserve

1. **Modular service layer** (`app/*_service.py`) — keeps business logic separate from API/UI.
2. **Typed contracts** (`QueryContext`, etc. in `app/models.py`) — prevents payload mismatches.
3. **Guardrails pattern** (`app/guardrails.py`, `app/input_validation.py`) — centralized
   input validation across API/CLI/UI/Telegram.
4. **Config through `app/config.py`** (pydantic Settings, `config.env` tracked defaults +
   `.env` local override) — app modules consume settings, not raw env.
5. **Provider abstraction** (`app/provider.py` + internal `app/provider_openai.py`) — single
   layer for LLM/embedding client creation and local/cloud fallback logic.

---

## 🚫 Prohibited Actions

These require **explicit user confirmation in chat** before proceeding:

- Permanent deletes (files, database records, git branches).
- Force-push to main/master.
- Modifying CI/CD pipelines (`.github/workflows/ci.yml`, `.github/workflows/deploy.yml`).
- Changing security permissions (file access, API keys — `HOME_RAG_API_KEY`/`X-API-Key`,
  environment variables).
- Creating new accounts or external API integrations.
- Large refactors without owner sign-off.

---

## 📞 When to Stop and Ask for Clarification

Stop work and ask the user if:

- Scope is ambiguous (change vs. refactor vs. feature?).
- The required test bundle for a change is unclear (no obvious `tests/test_*.py` match).
- A task references missing `doc/` paths, `backlog_registry.yaml`, or workflow scripts —
  that's likely `hometutor-studio` or legacy/archive material, not current runtime docs.
- Discovered a blocker not covered by `docs/conventions*.md` or the code itself.

**Default:** narrow scope beats broad scope. If unsure, ask.

---

## 🔗 Related Documents

- [`docs/index.md`](docs/index.md) — documentation navigation hub (start here)
- [`docs/conventions.md`](docs/conventions.md) — short engineering rules
- [`docs/conventions_architecture.md`](docs/conventions_architecture.md) — architecture boundaries
- [`docs/conventions_reference.md`](docs/conventions_reference.md) — prompts/API/errors/tests/docs
- [`docs/api_reference.md`](docs/api_reference.md) — HTTP contract
- [`docs/architecture.md`](docs/architecture.md) — runtime architecture

---

**Version:** 2.1 (2026-07-05) — corrected the single-repo rules against the actual checkout:
current docs are under `docs/`, legacy `doc/archive/` may exist, reranker is not globally
disabled in pytest, and provider/config/prompt boundaries match the code.
