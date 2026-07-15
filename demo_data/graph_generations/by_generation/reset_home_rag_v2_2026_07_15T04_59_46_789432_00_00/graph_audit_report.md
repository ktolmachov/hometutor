# Knowledge Graph Audit

- gate_passed: `True`
- published: `True`
- concepts: `104`
- relations: `196`
- test_artifacts: `0`
- relations_without_evidence: `0`
- duplicate_candidates: `10`

## Findings

- **P2 duplicate_candidates**: Duplicate/alias candidates: 10
  - `{'source': 'retrieval-augmented-generation', 'target': 'generation', 'reason': 'nested_label', 'match': 'retrieval-augmented-generation ↔ generation'}`
  - `{'source': 'chroma', 'target': 'demo-chroma-db', 'reason': 'nested_label', 'match': 'chroma ↔ demo-chroma-db'}`
  - `{'source': 'sm-2-algorithm', 'target': 'sm-2', 'reason': 'nested_label', 'match': 'sm-2-algorithm ↔ sm-2'}`
  - `{'source': 'interval', 'target': 'integer-data-type', 'reason': 'nested_label', 'match': 'interval ↔ int'}`
  - `{'source': 'hometutor-101', 'target': 'hometutor', 'reason': 'nested_label', 'match': 'hometutor-101 ↔ hometutor'}`

## Next Actions

- Review duplicate candidates and decide merge/keep/parent-child.
