# Benefit-Centric Creative Factory — V1 (Round 1)

> **SYSTEM OWNS STRUCTURE · AI AUTHORS CREATIVE WORDS · VIDEO ENGINE OWNS VISUAL EXECUTION.**

Round 1 replaces the frozen FAST54 / Storyboard-V3 single-route-anchor authoring
(which overloaded one provider call with Product Truth + route + storyline +
evidence + hooks/body/CTA + WPS + duration + projection). It builds the
**foundation only**: a Benefit Registry, a deterministic Product-Intelligence
cross-check with an audited manual-review path, and a Creative Atom Factory whose
capacity is computed deterministically. It does **not** generate full copy
(Round 2) or touch Montage / Production Studio (Round 3).

## The pipeline

```
Product ─▶ Benefit Registry (row: Benefit REQUIRED + Usage Hint OPTIONAL)
   │  deterministic, provider-free PI cross-check
   ▼  VERIFIED / REVIEW_REQUIRED / BLOCKED
   │  REVIEW_REQUIRED ─▶ audited operator VERIFY/BLOCK (provider-free; hard block not promotable)
   │  operator Build (one VERIFIED benefit) ── exactly ONE bounded STRUCTURE call, fallback OFF
   ▼  3 Angles ├─ 6 Hooks ┐
              ├─ 3 Bodies ┼─ (Hook × Body × CTA) triples within an Angle = 54/angle → 162/benefit
              └─ 3 CTAs  ┘   (virtual, fingerprinted, NOT materialised)
   ▼  deterministic capacity / readiness (ZERO provider calls)
```

The AI returns **only words**. BOSMAX assigns every id, parent id, digest,
version, status, lineage, timestamp and provider receipt.

## Data model (`agent/db/schema.py` → `CREATIVE_FACTORY_SCHEMA`)

| table | role |
|---|---|
| `product_benefit` | one registry row per benefit (`BEN_…`); status DRAFT/VERIFIED/REVIEW_REQUIRED/BLOCKED/ARCHIVED; PI verdict + snapshot binding in `pi_check_json` |
| `creative_angle` / `creative_hook` / `creative_body` / `creative_cta` | immutable authored atoms, bound to a `source_benefit_digest`; status ACTIVE/STALE/SUPERSEDED/ARCHIVED |
| `creative_atom_compatibility` | optional `(hook_id, body_id, cta_id)` triple narrowing; **empty ⇒ full within-Angle Cartesian** |
| `creative_build_receipt` | one immutable receipt per build call (COMPLETED / FAILED + diagnostics) |
| `product_benefit_review` | append-only audit of manual VERIFY/BLOCK resolutions |

**Revision/stale law.** An atom is stale iff `source_benefit_digest !=`
digest(benefit text + usage). Editing Benefit A stales only A's atoms; Benefit B
is untouched. A rebuild supersedes the prior ACTIVE build **only after** the new
build fully validates (atomic).

## Deterministic PI cross-check (reuse, never duplicate)

Reuses `product_intelligence_snapshot_service.get_latest_approved_snapshot`, the
deterministic claim gate (`product_intelligence_claim_safety_service.evaluate_claim_safety`
+ `authority/claim_boundary`) and the deterministic similarity primitives
(`copy_similarity_service`). **BLOCKED** on a hard claim/overclaim/blocked-list
hit; **REVIEW_REQUIRED** on soft-review, HIGH product risk, or no authority;
**VERIFIED** on strong lexical support of approved evidence. No LLM classifies a
benefit. Ambiguous EN↔MS paraphrases fall to REVIEW_REQUIRED and are resolved by
an authorized human (audited); a hard safety BLOCK is never manually promotable.

## The one build call

`creative_factory_service.build_benefit_atoms` issues exactly ONE
`ai_copy_provider_adapter.complete_json_with_receipt(..., lane="structure",
allow_fallback=False)` — the additive `allow_fallback` parameter suppresses the
structure-lane fallback for this call only, without disabling or mutating the
global provider fallback setting. The output is validated against a strict,
`extra="forbid"`, per-string-bounded Pydantic contract; then the existing
deterministic claim gate runs over ALL authored atoms. **All pass ⇒** atomic
commit; **any fail ⇒** FAILED receipt + zero atoms + prior build untouched. The
governed batch (`build-verified`) previews `verified_benefit_count` +
`expected_provider_calls`, requires explicit confirmation, and runs sequentially
so one benefit's failure never invalidates another.

## Workbook mapping (`Universal_Angle_Hook_Video_Factory.xlsx`)

**Adopted** (reference model, binary NOT committed): the master Benefit Registry
row shape (`20_PRODUCT_BENEFIT_REGISTRY`), per-benefit Allowed/Prohibited Wording
as claim constraints (`02_DB_BENEFITS`), the Angle→Hook + Body-route + CTA-intent
atom taxonomy (`03/04/05/17`) → the `(hook, body, cta)` triple compatibility key,
and the gated build-queue discipline (`21_AI_BUILD_QUEUE`).

**Deliberately NOT adopted into Round-1 atoms:** Runtime / Word-Budget / WPS,
duration, Claim-Gate-per-final-row, and scene/camera/avatar — all belong to
Round-2 runtime copy stitching and the existing video engines.

## Boundary

- **Round 2 (not built):** on-demand copy renderer (Benefit + duration + target →
  one AI call → 5 suggestions → lock/regenerate → cache), formula (PAS/AIDA)
  stitching, initial Hybrid/Faceless integration.
- **Round 3 (not built):** Montage / Production Studio integration.
- **Frozen / untouched:** Storyboard Landbank V3 / FAST54, Copy Register V2, and
  all video/scene engines.
