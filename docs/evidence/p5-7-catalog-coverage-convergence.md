# P5.7 Catalog Coverage Convergence Evidence

## Authority and boundaries

- Base after the P5.6-R2 merge:
  `349b2be27bec05c2c92fcc8d87a7b1465c8f4972`.
- Domain: `workspace`, status `IN_PROGRESS`.
- Product Truth authority: exact source `type` plus source category path.
- Canonical database mutation: none.
- Canonical runtime restart or deployment: none during rehearsal.
- Provider calls and credit spend: zero.
- P6 execution: not started.
- Explicitly untouched:
  `agent/services/product_knowledge_service.py` and
  `agent/services/ai_copy_provider_adapter.py`.

## Baseline

The baseline used a consistent SQLite online backup from the canonical
read-only source:

- Total: 659 products (443 active, 216 archived).
- P4 supported: 377.
- `unknown_product_type`: 133.
- `unknown_product_type` with P4: 0.
- Existing P6-shaped cohort: 169.

The baseline incorrectly allowed old reviewed bindings to remain apparently
ready after classifier authority changed. P5.7 therefore treats a stored
binding mismatch as stale and removes it from launch eligibility.

## Isolated rehearsal

Command:

```powershell
python scripts/p57-catalog-coverage-rehearsal.py `
  --database "<isolated-dir>\flow_agent.db" `
  --evidence-dir "<isolated-dir>\evidence\rehearsal" `
  --expected-product-count 659 `
  --apply-isolated
```

Final isolated evidence directory:

```text
C:\Users\USER\AppData\Local\Temp\bosmax-p57-isolated-349b2be2-final2\evidence\rehearsal
```

Results:

- Registry: 47 system-seed inserts, 20 system-seed updates, 73
  `ACTIVE / COVERED`, 6 review-only types.
- Taxonomy: 290 auto-derived bindings refreshed; 169 manual overrides
  preserved.
- Coverage: 566 `COVERED`, 32 `PARTIAL`, 61 `FALLBACK_ONLY`.
- Product Truth exact mappings: 476.
- P4 supported products: 566.
- `unknown_product_type`: 61 total (37 active, 24 archived).
- `unknown_product_type` with P4: 0.
- Broad `beauty_personal_care_other`: 25 total, all P4-unsupported and
  launch-blocked because source Product Truth is insufficient.
- Stale reviewed bindings: 57, all launch-blocked.

Matrix SHA-256:

```text
a4d9b5affbaf0d025f3d6b2a9b1967e679e3d4f44d4bdc18b91e405d43b31da4
```

## Explicit P6 launch cohort

Definition:

```text
VERIFIED + READY + COVERED + P4_SUPPORTED
```

Launch eligibility also fails closed for inactive products, stale taxonomy,
fallback scenes, non-specific scenes, and inactive or mismatched registry
bindings. The isolated rehearsal produced 112 product IDs. The complete
deterministic list is in `p57-p6-launch-cohort.json`; the complete 659-product
matrix is in `p57-catalog-coverage-matrix.csv`. This mission only identifies
the cohort. It does not start P6.

The reduction from the prior 169-row shape to 112 is a fail-closed correction:
57 stored manual bindings no longer match current Product Truth authority and
must be explicitly re-reviewed instead of being silently carried into P6.
