# Formula-Driven Copywriting Engine — V1 Notes & Hardening

Post-merge notes for PR #260 (merged `6cccb12`) + hardening PR
`fix/copywriting-engine-hardening-v1`. Scope: copywriting engine only. No Google
Flow, queue, prompt compiler, or DB migration touched.

## 1. Final API contracts (supersedes the earlier draft)

The earlier architecture draft floated `POST /api/products/{id}/prepare-copywriting`
with `{dry_run?, sections?[]}`. The **implemented, final** contract is:

- `POST /api/products/{product_id}/intelligence/review-drafts/prepare` — **no request body.**
  Namespaced under `review-drafts` because it *creates a review draft* (the same
  lifecycle as manual drafts). Returns
  `{review_draft_id, review_status, recommended_formula, grounding_source, claim_boundary, draft}`.
  Fail-closed: 503 unconfigured lane · 502 invalid AI JSON · 404 no product.
  Operator-initiated (spends DeepSeek tokens on the click).
- `GET /api/copy-sets/formulas` — read-only Formula Registry (slot contracts).

**`dry_run` / `sections` are intentionally deferred, not dropped.** Rationale: the
review draft IS the safety gate (nothing is approved automatically; the operator
edits every field before approving), so a `dry_run` adds little for V1. A future
`sections[]` (regenerate only the avatar, or only the formula) is a clean V1.1
addition — the service already builds the whole draft in one pass; sectioning is
additive. Tracked below.

## 2. Validator is V1 LEXICAL, not semantic

`formula_validator_service.validate_formula_copy` uses **lexical / token-overlap**
checks for USP grounding (`_any_overlap` — shared ≥4-char tokens between a copy USP
and an approved product fact). This catches "USPs unrelated to the product" but is
**not semantic truth validation** — it cannot tell that a factually-wrong-but-
lexically-overlapping USP is false.

**V1.1 roadmap (semantic / structured fact binding):**
- Give each approved snapshot fact a `fact_id`; store `allowed_claim_refs` on it.
- On generation, ask the provider to cite the `fact_id`(s) each USP is grounded in.
- Validator checks the cited `fact_id` exists + the USP is entailed (semantic score
  via an embedding/NLI check on the text_assist lane), not just token overlap.
- `USP_NOT_GROUNDED` becomes `USP_FACT_REF_MISSING` / `USP_FACT_MISMATCH`.

## 3. Sales Clarity ≠ Copy Strength (V1.1 task)

`sales_clarity_qa_service` answers *clarity* (who / problem / situation / knowledge /
formula / slots / why-now / tiktok-clear). It does **not** score persuasive
strength. **V1.1 "Copy Strength Score"** (planned, not in this PR):
hook strength · emotional tension · objection handling · novelty · CTA sharpness ·
TikTok scroll-stop potential · formula persuasion depth. Additive service +
`claim_review.copy_strength`; never auto-approves.

## 4. Hardening applied in this PR
- **Claim sanitization in the Prepare lane** (`_sanitize_claims`): overclaim is
  NEVER persisted as an *allowed* claim. Each AI `allowed_claim` is scanned with
  the two-tier `claim_boundary`; safe ones stay allowed, overclaim ones are moved
  to `blocked_claims`. In addition, `_sanitize_claims` scans **every AI prepare
  narrative field** — not just allowed_claims — and records any overclaim found
  there as blocked. The scanned fields are: `product_knowledge.{description,
  benefits, usps, usage, ingredients, warnings, target_customer}`,
  `customer_avatar.{audience, tone, pronoun, desires, fears, pains, objections,
  triggers}`, top-level `market_problem_language, situation, desire, objection,
  trigger, use_context`, `allowed_claims`, and `formula_breakdown` values. Closes
  the coverage gap vs the narrower `claim_safety` scan (which lacks `100%` /
  `dijamin` / `klinikal` / `npra` / `rawat` / `ubat`). Market / problem language is
  never flagged, so avatar pains / `market_problem_language` (e.g. "anak kembung
  perut") are safe to scan and are preserved. Overclaim can therefore never reach
  approved copy: the generated copy is independently re-validated by
  `claim_boundary` in the formula validator + `scan_copy_safety`.
- **UI exposes the true formula id** (not just the compiler-safe family): the Copy
  Registry "Formula / QA" column shows `formula_id → compiler_family`,
  `definition_status` (draft), validation issue count + slot coverage (tooltip),
  clarity score, and the formula breakdown (tooltip).

## 5. MWTCB manual UAT script
1. Products → search "Minyak Warisan Tok Cap Burung 25ml" → Intelligence tab.
2. Click **Prepare with AI (DeepSeek)** (this spends tokens).
3. Expect a draft with: avatar audience "ibu ada anak kecil"; pains incl.
   **"anak kembung perut" / "perut berangin"**; `market_problem_language` keeps
   those phrases; recommended formula **PAS**; overclaim (sembuh/dijamin/KKM) NOT
   in allowed_claims.
4. Review → **Approve** → approved snapshot exists.
5. Copy Registry → select MWTCB → grounding shows **APPROVED_SNAPSHOT** → Generate.
6. Expect PAS copy: Problem (anak kembung perut waktu malam) → Agitate (rutin tidur
   terganggu) → Solution (minyak sapuan tradisional botol kecil) → CTA. Formula/QA
   column shows `PAS · ✓ formula ok`. **"kembung perut" preserved**, not collapsed
   into vague "rutin harian / confidence".

Automated mirror: `tests/unit/test_ai_copy_assist_service.py::test_uat_mwtcb_market_language_preserved`.

## 6. BOSMAX sensitive-product manual UAT script
1. A stealth male-health product → Prepare with AI → Approve.
2. Copy Registry → formula PESTA/HPAS/SavagePAS depending on route → Generate.
3. Expect: ego / maruah / keyakinan / rumah-tangga problem language **preserved**;
   NO explicit anatomy (zakar/penis/mati pucuk); NO cure/guarantee/clinical; buyer
   still understands the problem. Formula/QA shows no OVERCLAIM.
4. Negative check: if any copy names explicit anatomy → validation flags OVERCLAIM
   and the set stays review-required.

Automated mirror: `test_uat_bosmax_sensitive_preserves_problem_controls_overclaim`
and `test_uat_bosmax_explicit_anatomy_is_overclaim`.

## 7. Browser proof checklist (operator)
- [ ] Products → Intelligence tab shows **Prepare with AI (DeepSeek)** button.
- [ ] Copy Registry shows the **Formula** picker (auto + 8 formulas, drafts labelled)
      and a **Prepare Product for Copywriting** button.
- [ ] Ungrounded product: Generate returns the "belum ada Product Knowledge +
      Customer Avatar diluluskan… Prepare dahulu" message (block + override).
- [ ] Approved snapshot: Generate produces formula-aware sets.
- [ ] Generated set row shows Formula / QA (formula_id → family, ✓/⚠, clarity).
- [ ] No set is auto-approved (all land "Review required").

## 8. Governance
Merged before this forensic audit; **not reverted** (direction is sound). Fixes
land as follow-up PR `fix/copywriting-engine-hardening-v1`. Deferred items (dry_run/
sections, semantic validator, Copy Strength) are documented, not silently dropped.
