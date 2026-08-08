# Poster Builder V3 — PR-B Design-System Audit

Date: 2026-08-08
Base merge SHA: `3aae043866cb2dd7ca5c446df7f4566e6c9d8836` (PR-A)
Workstream: `codex/poster-builder-v3-b-design-system-20260808`

## Scope

PR-B adds a typed Campaign Design Brief, grounded copy-route scoring and a
route-aware design authority. It does not change Exact Commerce, call a
provider, mutate the database or enable the Creative Campaign flag.

The implementation extends the existing `POSTER_TEMPLATE_TOKENS.yaml`
authority and the existing deterministic compositor. It does not introduce a
second renderer or a parallel save path.

## Product intelligence contract

`PosterCampaignDesignBrief` is resolved read-only from the registered product,
the existing approved product-intelligence snapshot and the existing copy
grounding service. The brief carries the approved snapshot ID/version,
claim-boundary status, audience, buyer moment, desire, objection, trigger,
approved proof points, route decision and field-level provenance.

Missing approved intelligence, non-approved snapshot status, missing approved
provenance or an unverified claims boundary becomes a visible blocker. A
fail-closed request raises `CAMPAIGN_INTELLIGENCE_INCOMPLETE`; no guessed
persona, claim or product fact is substituted.

## Copy intelligence contract

The route generator has one explicit provider boundary and a zero-spend draft
fallback. The fallback is always `DRAFT_FALLBACK_NOT_PRODUCTION`, never
auto-selected, and records zero provider operations. A provider invocation is
bounded to one operation, accepts at most five candidates, records the
operation count, and performs no hidden retry.

Each candidate is scored across product specificity, customer relevance,
comprehension, reason to believe, emotional-commercial tension, Malaysian
naturalness, proof relevance, non-redundancy, visual line budget,
differentiation, claim safety and approved-fact provenance. Unsupported
superlatives, generic phrases and headline/support repetition are explicit
rejection reasons.

## Route and typography authority

Campaign resolution considers category, subcategory, product type/family,
physics/material signals, objective, angle, audience and human-presence intent.
The available campaign routes are:

- `HERITAGE_EDITORIAL`
- `PRODUCT_HERO_SCULPTURE`
- `ROUTINE_LIFESTYLE_EDITORIAL`
- `BOLD_VALUE_COMMERCE`
- `TECHNICAL_PRECISION`
- `MODEL_AMBASSADOR_SPLIT`

Every route declares at least two layout variants, a type pairing, color
strategy, proof treatment, Malaysian-context route and anti-cliche rules in
the existing authority YAML. Campaign manifests carry route, variant and
font-readiness provenance. Font families remain host-installed and
`HOST_SYSTEM_LICENSED`; no font package is bundled or silently substituted.
`font_readiness` returns `HOST_RUNTIME_REQUIRED` until the host compositor can
prove availability and fails closed when an injected availability set is
missing a required family.

The legacy global tokens and Exact Commerce callers remain unchanged when no
Campaign route is supplied. Campaign composition supplies the resolved route
and variant explicitly, so the legacy Segoe-based exact path is not the
Campaign default.

## Verification boundary

Local tests cover approved-snapshot provenance, fail-closed intelligence,
distinct draft routes, copy quality blockers, category/objective route changes,
font readiness and the single explicit provider-operation contract. PR-B
implementation and tests use no provider calls and no database writes.

Live provider behavior, generated clean-key-visual identity, typography in a
browser host, final composed poster quality and human approval remain
unproven until the PR-C dry-run gates pass and the later bounded live
benchmark is explicitly executed.
