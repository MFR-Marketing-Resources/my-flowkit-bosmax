# Creative diversity and dedupe audit

See `evidence/variation_dimension_matrix.csv` and `evidence/duplicate_rule_matrix.csv`.

## Max unique capacity preflight

**MISSING** — No API computes maximum safe unique combinations from pool sizes (avatars × scenes × hooks × copy sets) before generation. **DECISION_REQUIRED** for business thresholds.

## Duplicate controls summary

| Rule | Hard block | Scope | Classification |
|------|------------|-------|----------------|
| Exact fingerprint collision in legacy batch | Yes | batch-local | VERIFIED_CODE |
| Planner batch duplicate dialogue | Soft warn | batch-local | VERIFIED_TEST |
| Copy set batch AI dedupe | Near-dup metadata | copy generation | VERIFIED_TEST |
| Cross-batch product history | Partial hooks | planner history inputs | NOT_VERIFIED |
| Semantic near-duplicate video output | No | provider | BLOCKED_BY_EXTERNAL_RUNTIME |
