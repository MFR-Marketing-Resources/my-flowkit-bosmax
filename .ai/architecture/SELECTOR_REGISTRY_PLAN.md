# Selector Registry Plan

## Goal
- Separate proven selectors from failed or experimental selectors.

## Registry Requirements
- Each selector entry must declare:
  - `id`
  - `surface`
  - `verification_status`
  - `requires_shadow_piercing`
  - `evidence_source`
  - `fallback_policy`

## Policy
- Proven selectors stay frozen until the harness proves drift.
- Failed selectors must not be silently mixed into the live path.
- Upload-specific selectors require explicit local evidence before reuse.
