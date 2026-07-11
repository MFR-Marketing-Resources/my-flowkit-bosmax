# Creative diversity and dedupe audit (repair v1.1)

**Matrices:** `evidence/variation_dimension_matrix.csv`, `evidence/duplicate_rule_matrix.csv`

## Verified current behaviour

- Batch prompt planner: fingerprints via sha1 over dialogue, hook, avatar, scene, angle — **VERIFIED_CODE** (`batch_prompt_planner.py`)
- Semantic dialogue soft ceiling 0.90 in planner tests — **VERIFIED_TEST_IN_THIS_AUDIT**
- Legacy `variation_matrix`: strategies SAME_SCRIPT_*, DIFFERENT_SCRIPT_* — **VERIFIED_CODE**
- Copy sets: uniqueness_score fields — **VERIFIED_CODE**; not wired to batch preflight

## Dedupe types (separate policies)

| Type | Current | Recommended default (PROPOSED) |
|------|---------|--------------------------------|
| Exact prompt duplicate | hard in batch | keep hard |
| Exact dialogue | partial | hard within batch |
| Hook duplicate | fingerprint | soft warn cross-batch |
| Semantic dialogue | soft 0.90 | D5 threshold |
| Same angle, wording tweak | partial | creative DNA hash |
| Same copy, different visual | rotation | allow with visual fingerprint |
| Avatar+scene+hook combo | partial history | track triple in lineage |
| Cross-batch / historical | product history inputs | extend global index |
| Intentional reuse | SAME_SCRIPT strategies | explicit quota in plan |
| Generated visual similarity | none | provider QA optional |

## Gaps

- **creative_DNA** — PROPOSED
- **max_capacity_preflight** — doc `13_UNIQUE_CAPACITY_PREFLIGHT_CONTRACT.md`
- Poster dimensions partially separate — **VERIFIED_TEST_IN_THIS_AUDIT**