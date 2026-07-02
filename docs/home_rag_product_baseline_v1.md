# Home RAG Product Baseline v1

Purpose:

```text
Measure Home RAG as a learning product, not as a model benchmark.
```

Canonical model selection is closed:

```text
MODEL_SELECTION_CLOSED:
  model: qwopus3.6-35b-a3b-v1-mtp
  status: HOME_RAG_INTEGRATION_GATE_PASS
  commit: 72601f8
```

Product baseline:

```text
PRODUCT_BASELINE_V1:
  baseline_model: qwopus3.6-35b-a3b-v1-mtp
  rule: do not change model without a separate evidence chain
```

## Files

```text
scripts/home_rag_product_baseline_v1.py
scripts/Run-HomeRagProductBaseline-v1.ps1
eval_data/home_rag_product_baseline/home_rag_product_baseline_v1.json
docs/home_rag_product_baseline_v1.md
```

## Metrics

```text
retrieval_quality
answer_grounding
citation_accuracy
quiz_validity
long_doc_stability
refusal_precision
user_value
```

Unlike `HomeRagIntegrationGate-v1`, this baseline writes a scorecard. Low scores identify product/system gaps; they do not reopen model selection by themselves.

## Preflight

```powershell
cd D:\Projects\hometutor
pwsh -ExecutionPolicy Bypass -File .\scripts\Run-HomeRagProductBaseline-v1.ps1 -PreflightOnly
```

Expected marker:

```text
HOME_RAG_PRODUCT_BASELINE_V1_PREFLIGHT=PASS
```

## Full Run

Start or allow the runner to start the accepted local RAG model. Ensure the embedding endpoint is available:

```text
LLM:    http://127.0.0.1:8080/v1 / qwopus3.6-35b-a3b-v1-mtp
Embed:  http://127.0.0.1:1234/v1 / text-embedding-qwen3-embedding-0.6b
```

Run with a fresh isolated index:

```powershell
cd D:\Projects\hometutor
pwsh -ExecutionPolicy Bypass -File .\scripts\Run-HomeRagProductBaseline-v1.ps1 -StopExisting -ResetHome
```

Fast rerun after index exists:

```powershell
pwsh -ExecutionPolicy Bypass -File .\scripts\Run-HomeRagProductBaseline-v1.ps1 -SkipIngest
```

Reports:

```text
D:\AI\logs\home_rag_product_baseline_v1_*.json
D:\AI\logs\home_rag_product_baseline_v1_*.csv
D:\AI\logs\home_rag_product_baseline_v1_*.md
```

## Status Interpretation

```text
ACCEPTED_BASELINE: overall score >= 0.85
WATCH_BASELINE:    overall score >= 0.70 and < 0.85
NEEDS_WORK:        overall score < 0.70
```

The next useful step after the first run is to inspect weak categories, not to swap the model.

## Current Baseline Run

```text
status: WATCH_BASELINE
report_json: D:\AI\logs\home_rag_product_baseline_v1_2026-07-03_00-53-16.json
baseline_model: qwopus3.6-35b-a3b-v1-mtp
corpus: isolated product-baseline corpus
docs/nodes: 7 / 7
```

Case summary:

```text
baseline_retrieval_001: WATCH
baseline_retrieval_002: PASS
baseline_html_001: WATCH
baseline_wrong_doc_001: PASS
baseline_long_doc_001: WATCH
baseline_long_doc_002: WATCH
baseline_refusal_001: PASS
baseline_refusal_002: PASS
baseline_quiz_001: PASS
baseline_quiz_002: NEEDS_WORK
baseline_citation_001: NEEDS_WORK
baseline_user_value_001: WATCH
```

The first full run exposed overly English-only expectations in the baseline cases. The case file now accepts equivalent Russian phrasing while keeping hallucination and unsupported-fact checks strict.

## Current Product Findings

```text
citation_source_id_integrity:
  finding: answers can cite numeric ids such as [2] or [3] when only one source node is returned
  impact: grounded answers may be useful, but citation integrity is not product-grade yet

quiz_mcq_generation:
  finding: one multiple-choice quiz case refused instead of generating a question from retrieved context
  impact: quiz generation is promising but not stable enough for the accepted product baseline

overall:
  finding: retrieval and refusal behavior are strong enough for WATCH_BASELINE, but citation discipline and quiz consistency need product work
```

This baseline is a product/system scorecard. `WATCH_BASELINE` means the Home RAG path is usable as a measured baseline, not that the canonical model selection should be reopened.
