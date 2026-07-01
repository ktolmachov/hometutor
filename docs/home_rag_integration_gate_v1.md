# Home RAG Integration Gate v1

Purpose:

```text
documents folder -> ingestion/indexing -> retriever -> selected chunks
-> answer_question() -> sources/citations/grounding checks
```

This gate is the first layer after `RetrievalBackedRagGate-v1.1`. Unlike the model-pack gates, it runs inside the `hometutor` application and uses the real ingestion and query pipeline.

## Files

```text
scripts/home_rag_integration_gate_v1.py
eval_data/home_rag_gate/home_rag_cases_v1.json
docs/home_rag_integration_gate_v1.md
```

## Preflight

```powershell
.\.venv\Scripts\python.exe .\scripts\home_rag_integration_gate_v1.py --preflight-only
```

Expected marker:

```text
HOME_RAG_INTEGRATION_GATE_V1_PREFLIGHT=PASS
```

## Full Gate

Start the local RAG LLM and embedding endpoint first. By default the gate expects:

```text
LLM:       http://127.0.0.1:8080/v1 / qwopus36-35b-a3b-mtp
Embeds:    http://127.0.0.1:1234/v1 / text-embedding-qwen3-embedding-0.6b
Gate home: D:\AI\home_rag_gate_v1
Reports:   D:\AI\logs
```

Run:

```powershell
.\.venv\Scripts\python.exe .\scripts\home_rag_integration_gate_v1.py --reset-home
```

Expected marker:

```text
HOME_RAG_INTEGRATION_GATE_V1=PASS
```

If the application runtime cannot be imported on the current machine, the gate writes a report and exits with:

```text
HOME_RAG_INTEGRATION_GATE_V1=BLOCKED_RUNTIME_IMPORT
```

This is an environment blocker, not a case failure. One observed cause is Windows application-control policy blocking compiled Python extensions in the active virtual environment.

Reports:

```text
D:\AI\logs\home_rag_integration_gate_v1_*.json
D:\AI\logs\home_rag_integration_gate_v1_*.csv
D:\AI\logs\home_rag_integration_gate_v1_*.md
```

## Scope

Checks:

- real corpus files under an isolated `HOME_RAG_HOME`
- real `ingest.build_index(reset=True)`
- real `answer_question()`
- grounded answers
- no-evidence refusals without citations
- wrong-document traps
- numeric exactness
- citation source-id integrity
- one long-context retrieval case

Still out of scope:

- arbitrary user document collections
- production-sized corpora
- reranker quality benchmarking
- end-to-end UI/browser flows

## Current Known Blocker

```text
HOME_RAG_INTEGRATION_GATE_V1=BLOCKED_RUNTIME_ENDPOINT
Cause: embedding endpoint is not accepting connections at http://127.0.0.1:1234/v1.

Resolved native blockers:
  _tiktoken: D:\AI\logs\home_rag_integration_gate_v1_2026-07-01_23-21-57.json
  rpds:      D:\AI\logs\home_rag_integration_gate_v1_2026-07-01_23-31-26.json

Current endpoint blocker:
  report: D:\AI\logs\home_rag_integration_gate_v1_2026-07-02_00-24-58.json
  llm_probe: PASS, qwopus36-35b-a3b-mtp found at http://127.0.0.1:8080/v1/models
  embed_probe: BLOCKED, WinError 10061 connection refused at http://127.0.0.1:1234/v1/models
```

Diagnostics already tried:

```text
Unblock-File over .venv native extensions: no effect
Reinstall rpds-py/tiktoken wheels: no effect
requests pin restored after reinstall: requests==2.33.1
Zone.Identifier streams: absent
Authenticode signature: NotSigned
After App Control policy update:
  rpds import: PASS
  tiktoken import: PASS
  app.query_service import: PASS
```

Blocked native files observed after reinstall:

```text
D:\Projects\hometutor\.venv\Lib\site-packages\rpds\rpds.cp311-win_amd64.pyd
  sha256: 3FBD6D9AA1CE4669506A91C4321BB751895DFA4E78EFB6ED1151CEA8C51B238F

D:\Projects\hometutor\.venv\Lib\site-packages\tiktoken\_tiktoken.cp311-win_amd64.pyd
  sha256: BB75E9970E743663C7DBF30D48CD27EB163F18395C31BDD48722514D9F566373
```

Resolution options:

1. Start LM Studio or another OpenAI-compatible embedding server on `http://127.0.0.1:1234/v1`.
2. Load an embedding model that appears as `text-embedding-qwen3-embedding-0.6b` in `GET /v1/models`, or run the gate with `--embed-model <actual-model-id>`.
3. Re-run the gate with `--skip-ingest` if the existing Chroma index should be reused, or with `--reset-home` if the index should be rebuilt with the active embedding model.
4. Keep the gate-level tokenizer fallback for `_tiktoken`; it is no longer required on the current machine state, but remains useful if App Control blocks `_tiktoken` again.
