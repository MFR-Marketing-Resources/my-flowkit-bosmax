# ADR-008: One Canonical Final Prompt Compiler Authority

- Status: ACCEPTED AND EXECUTED (owner mission order, 2026-07-02)
- Scope: final engine-facing prompt output for T2V / HYBRID / FRAMES /
  INGREDIENTS / IMAGES
- Supersedes: every other prompt-output surface for FINAL output

## Problem (confirmed by dual audit — Codex read-only audit + Claude verification)

- Final output was 8 heuristic chunks, not the canonical 9-section contract.
- TWO conflicting "9-section" definitions existed (retained taxonomy vs
  prompt_compiler_9_section's "Biometric Anchor DNA" taxonomy).
- Dialogue was generic/short: hardcoded body_wps=1.7 vs retained workbook
  authority (Malay SafeWPS 2.4, SweetWPS 2.7) — an 8s Malay block got 13 words
  instead of 19-22.
- Multi-block output was capped at 2 (`[:2]`) vs workbook chains of 1-7
  (Google Flow 56s = [8,8,8,8,8,8,8]).
- Source modes were blurred: HYBRID rode on F2V heuristics, FRAMES was generic
  prompt-writing instead of frame-truth continuation, INGREDIENTS had no
  asset-role map law.
- overlay_enabled defaulted True vs the retained NO_OVERLAY law.
- Presenter output was the generic "one visible creator" placeholder.

## Decision

1. `agent/services/canonical_prompt_compiler.py` is **THE only sanctioned
   final engine-facing prompt renderer**. Everything else routes through it.
2. Authority data is vendored in-repo under `agent/authority/` (retained pack
   2026-06-21): canonical section templates, custom instruction,
   `wps_blocking_authority.json` (extracted verbatim from
   WPS_Blocking_Template_REPAIRED.xlsx — 20 block plans, 9 language WPS
   profiles, continuation timing), avatar pool CSV, copywriting framework.
3. Source-mode law implemented explicitly: T2V (text-driven), HYBRID (product
   image anchor + ONE resolved concrete presenter, first-class — never hidden
   under F2V heuristics), FRAMES (single frame truth, motion-delta only),
   INGREDIENTS (explicit asset-role map, product truth outranks all, missing
   style → SCENE_CONTEXT_ONLY), IMAGES (still-image lane, same authority).
4. Avatar resolution layer `agent/services/avatar_registry.py`: deterministic
   (explicit AvatarCode → usage-tag context → product-seeded pick; same
   product = same presenter), renders concrete descriptive prose. The pool is
   a growing registry (repo CSV seed of the live Notion avatar database);
   registry fields never leak into engine output.
5. WPS law: SafeWPS default, SweetWPS deliberate mode, per-block budgets,
   workbook values only. Block plans come from workbook only (1-7 blocks;
   Flow 40s requires preferred lane A/B).
6. Copywriting intelligence: structured angle/hook/subhook/USP/CTA/formula
   (PAS, AIDA, HSO, BAB, PESTA, PASTOR). Resolution order: explicit operator
   copy > product copywriting landbank (SECONDARY reference — helper, never a
   hard dependency) > claim-safe package fields. Landbank = operator-uploaded
   COPY_MASTER CSVs via POST /api/workspace/copywriting-landbank/{product_id}
   (stored in data/copywriting_landbank/, grows over time).
7. NO_OVERLAY default everywhere (runtime config + compiler signature).
8. Output scrub is fail-closed: source-mode taxonomy, WPS numbers, block
   plans, debug JSON, avatar-pool codes, and generic placeholder presenter
   wording ABORT the compile.

## Legacy disposition

- `compile_ugc_video_prompt` KEEPS its public signature/return shape (all
  workspace-package callers and the locked Flow runtime lane are untouched)
  but delegates every block render to the canonical compiler. The 2-block cap
  is deleted.
- `prompt_compiler_9_section.py`, `prompt_output_composer.py`,
  `prompt_preview_pipeline.py`: FROZEN and de-authorized for final output
  (header stamped); delete after parity proof.

## Proofs

- `tests/unit/test_canonical_prompt_compiler.py` (17 contracts): canonical
  9-section order per block · 7-block Flow 56s · preferred-lane 40s · workbook
  WPS budgets (Safe/Sweet) · dialogue richer than legacy 13-word budget · CTA
  final-block law · HYBRID concrete presenter (deterministic per product) ·
  FRAMES motion-delta · INGREDIENTS role-map + style normalization ·
  NO_OVERLAY default · leak scrub · Section-6-only target language · IMAGES
  lane · legacy entrypoint delegation + uncapped blocks.
- Full regression: unit+api = 912 passed; ALL remaining failures reproduce on
  clean HEAD (verified via disposable worktree) — none introduced here.

## Future (recorded, not implemented here)

- Batch prompt production rides HYBRID + the avatar registry structure.
- Avatar DB, product list, and copywriting landbank all grow over time; the
  registry/landbank layers are the ingestion points, the canonical compiler
  never changes shape for growth.
