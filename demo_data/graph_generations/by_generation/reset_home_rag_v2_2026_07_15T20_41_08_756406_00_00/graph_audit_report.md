# Knowledge Graph Audit

- gate_passed: `True`
- published: `True`
- concepts: `131`
- relations: `288`
- test_artifacts: `0`
- relations_without_evidence: `0`
- duplicate_candidates: `16`

## Findings

- **P2 duplicate_candidates**: Duplicate/alias candidates: 16
  - `{'source': 'retrieval-augmented-generation', 'target': 'retrieval', 'reason': 'nested_label', 'match': 'retrieval-augmented-generation-rag ↔ retrieval'}`
  - `{'source': 'retrieval-augmented-generation', 'target': 'generation', 'reason': 'nested_label', 'match': 'retrieval-augmented-generation-rag ↔ generation'}`
  - `{'source': 'chroma', 'target': 'pre-index-chroma-db', 'reason': 'nested_label', 'match': 'chroma ↔ pre-index-chroma-db'}`
  - `{'source': 'metadata-filtering', 'target': 'filtering', 'reason': 'nested_label', 'match': 'metadata-filtering ↔ filtering'}`
  - `{'source': 'sm-2-algorithm', 'target': 'sm-2', 'reason': 'nested_label', 'match': 'sm-2-algorithm ↔ sm-2'}`

## Next Actions

- Review duplicate candidates and decide merge/keep/parent-child.
