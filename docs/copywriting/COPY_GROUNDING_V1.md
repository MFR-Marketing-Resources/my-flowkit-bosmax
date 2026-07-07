# Copy Grounding Intelligence V1

Grounds AI copy generation in **product knowledge + customer avatar** so the copy
is angle-first and strategy-driven — not guessed.

## Why

`ai_copy_assist_service._build_brief` used to send only product name + category +
angle to DeepSeek. The copy therefore "didn't know the product" (e.g. Bosmax read
as generic, not a Male-Health / STEALTH / privacy item). The causal chain the
operator identified is correct:

```
Product Knowledge + Customer Avatar  ──►  Angle  ──►  Hook ──► Subhook ──► USP ──► CTA
```

Without the two IBU KUNCI, the angle is guessed and everything downstream inherits
the guess. The rich store (`product_intelligence_snapshot`: benefits/USP/persona/
copy_strategy/claims) existed but was empty for real products and unwired; the
authority framework (`COPYWRITING_FRAMEWORK_UNIVERSAL.yaml`) + BOSMAX avatar/
copywriting method existed but weren't wired into the generator.

## What shipped

### Two-tier grounding — `agent/services/copy_grounding_service.py`
`resolve_copy_grounding(product) -> CopyGrounding` (`agent/models/copy_grounding.py`):
1. **APPROVED_SNAPSHOT** — if `get_latest_approved_snapshot(product_id)` exists, use
   the operator-authored product knowledge (description/benefits/USPs/ingredients/
   target_customer) + buyer persona + copy strategy + allowed/blocked claims. The
   framework tier fills any avatar/angle/silo/route gaps.
2. **FRAMEWORK_FAMILY** — else derive from the product-intelligence family
   (`resolve_product_intelligence_profile` → e.g. `MALE_HEALTH_SENSITIVE`) via the
   curated authority `agent/authority/copy_family_grounding.py`, which crosswalks
   each family to the framework's avatar dimensions, trigger library, angle
   families, tone and claim posture. **This makes Bosmax grounded now** (STEALTH,
   ego/maruah avatar, stealth angle strategies, metaphor silos, CLAIM_REVIEW) with
   **zero tokens and zero invented product claims**.
3. **MINIMAL** — unknown family + no snapshot → ungrounded (flagged).

**Honesty boundary:** product FACTS (benefits/USPs/ingredients) are read only from
an approved snapshot — never invented. The framework tier grounds only the AVATAR /
ANGLE STRATEGY / TONE / CLAIM guardrails (family-level framework truths).

### Wired into the AI lane — `ai_copy_assist_service`
`_build_brief` now carries the full grounding: customer avatar (audience/desires/
fears/pains/objections/triggers/tone/pronoun), product knowledge, claim guardrails
(incl. the framework `banned_terms`: `zakar/penis/…/cure/guarantee/…`), and a
per-candidate **target angle**. The batch resolves grounding once and **rotates a
DISTINCT strategic angle per candidate** (`_rotation_angles`) so "Generate 5"
produces 5 different angles, not one reworded five times. An operator-pinned angle
disables rotation. The DeepSeek system prompt (`build_messages`) is angle-first:
pick one buyer pain/desire → derive the angle → build hook→subhook→USP→CTA from that
angle + avatar; ground USPs in product knowledge; obey claim guardrails.

### Grounding readiness — `GET /api/copy-sets/grounding/{product_id}`
Returns the `CopyGrounding` (grounded / source / family / avatar / angle strategies
/ claims / missing). The Copy Registry page shows a **grounding banner**: approved-
snapshot (green) / framework-family (blue, with "author a snapshot for richer copy")
/ ungrounded (red).

## Path to richer grounding (Fix 2/3 — future)
Author real `product_intelligence_snapshot`s per product (via the existing
`/api/product-knowledge/complete` + `/api/product-intelligence/review-drafts →
approve` workflow). Once approved, Tier 1 automatically supplies real benefits/USPs/
persona to the same brief. No further code change needed in this module.

## Guardrails
Reuse existing resolvers + framework — no parallel logic, no new DB, no data
backfill. Zero AI token spend to build/verify (framework tier is deterministic;
provider mocked in tests; the real "Generate 5" is an operator click). Deterministic
lane, approval gate, safety scan, dedupe — untouched. No invented product claims.

## Verify
```
python -m pytest tests/unit/test_copy_grounding_service.py \
  tests/unit/test_ai_copy_assist_service.py tests/api/test_copy_sets_api.py \
  tests/api/test_copy_sets_batch_api.py -q
cd dashboard && npm test && npm run build
npx tsx scripts/mandor-check.ts
```
Zero-token proof: `build_framework_grounding` + `_build_brief` for Bosmax shows the
brief now carries the Male-Health STEALTH avatar + 5 distinct angle strategies +
banned terms — with no provider call.
