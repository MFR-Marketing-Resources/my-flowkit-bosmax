# AI Copy Assist — Candidate Copy Set V1

Status: implemented (backend + operator UI). Builds on the Copy Selection +
Compiler Binding + Explicit Fallback Confirmation workflow already on `main`.

## Purpose

Give the operator a stronger way to draft copy candidates (angle / hook / subhook
/ USP / CTA) grounded in product truth — **without** ever bypassing review,
safety, approval, or the deterministic final compiler.

## What it is (and is NOT)

- **IS:** a controlled generator of **candidate Copy Sets** that enter the
  existing Copy Set lifecycle as `COPY_REVIEW_REQUIRED`.
- **IS NOT:** a final-prompt generator. The AI provider never produces the
  9-section engine prompt; the deterministic compiler is unchanged. AI output is
  never auto-approved and cannot bind until an operator approves it.

## Flow

```
Operator → "AI Assist Draft Copy Set" (optional brief note)
   → POST /api/copy-sets/ai-assist
   → ai_copy_assist_service.generate_ai_copy_candidate
        product truth ground → provider adapter (disabled by default)
        → sanitize → EXISTING claim-risk + completeness → EXISTING dedupe
        → crud.create_copy_set(status=COPY_REVIEW_REQUIRED, source=AI_COPY_ASSIST)
   → candidate appears in Copy Set list as "review required"
   → operator reviews → approves via existing POST /copy-sets/{id}/approve
   → only then selectable + bindable into the deterministic compiler
```

## Provider behavior (adapter boundary)

`agent/services/ai_copy_provider_adapter.py` reuses the on-main lane provider
abstraction (`ai_provider_settings_service`, the **`text_assist`** lane) — the
same mechanism `product_knowledge_service` already uses. No new secrets, no new
settings UI, no hardcoded keys.

- **Disabled by default.** With no configured/enabled `text_assist` key, every
  call fails closed: `AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED` (HTTP 409).
- When configured, it performs an OpenAI-compatible `chat/completions` call
  (base URL / model via `PRODUCT_TEXT_ASSIST_BASE_URL` / `PRODUCT_TEXT_ASSIST_MODEL`
  or a small provider default map) and parses strict JSON.
- Invalid JSON / call failure → `AI_COPY_ASSIST_RESPONSE_INVALID` /
  `AI_COPY_ASSIST_CALL_FAILED` (HTTP 502).
- `generate_candidate(brief)` is the single mockable seam; tests never touch the
  network.

## Copy Set lifecycle behavior

- Candidates are saved **`COPY_REVIEW_REQUIRED`** — always (AI output is never
  DRAFT-clean and never `COPY_APPROVED`).
- Approval uses the **existing** gate (`APPROVE_COPY_SET` phrase +
  completeness/safety fail-closed). Unsafe/incomplete AI copy cannot be approved.
- `source = AI_COPY_ASSIST`; provenance (provider lane/id, rationale, risk_notes)
  is **internal only**.

## Safety / claim-risk

The candidate copy fields run through the **same** `scan_copy_safety` +
`assess_copy_completeness` used by every Copy Set. Banned: medical/cure/treat/heal,
guaranteed results, universal-safety, before/after, clinical-authority claims.
The provider system prompt also bans these and bans final/engine output and
internal-metadata leakage. Unsafe candidates are stored review-required with the
violations surfaced, and the approval gate blocks them.

## Dedupe

Reuses `copy_set_service` dedupe (`_dedupe_key_for` +
`crud.find_copy_set_by_dedupe_key`). A candidate whose angle/hook/subhook/USP/CTA/
platform/language/route collapses to an existing key returns the existing Copy Set
(`created: false, dedupe_match: true`) instead of duplicating.

## No metadata leak

Only clean copy fields cross into the compiler via `to_compiler_copy(...)` —
after approval. The provider name, raw prompt, raw response, provenance, and
internal ids never enter compiler copy or the engine-facing prompt.

## API

`POST /api/copy-sets/ai-assist` — request: `product_id` (+ optional `angle`,
`hook`, `subhook`, `usp_set`, `cta`, `platform`, `language`, `route_type`,
`formula_family`, `content_style_mode`, `operator_notes`, `candidate_count`
[1..3]). Response: `{ provider: {lane, configured, provider_id}, candidates: [{
copy_set, created, dedupe_match, safety, warnings }] }`. Explicit request fields
override the AI value for that field.

## Files

Backend: `agent/services/ai_copy_provider_adapter.py` (new),
`agent/services/ai_copy_assist_service.py` (new),
`agent/api/copy_sets.py` (route), `agent/models/copy_set.py`
(`AICopyAssistRequest`, `SOURCE_AI_COPY_ASSIST`).
Frontend: `dashboard/src/api/copySets.ts`, `dashboard/src/types/index.ts`,
`dashboard/src/components/workspace/CopySelectionPanel.tsx` (AI Assist button +
brief input + review-required notice).
Tests: `tests/unit/test_ai_copy_assist_service.py`,
`tests/api/test_ai_copy_assist_api.py`.

## Known limitations

- Disabled unless the `text_assist` lane is configured on the runtime; otherwise
  the button surfaces `AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED`.
- The live provider transport is exercised only when a key is present; CI/tests
  mock the adapter seam.
- `candidate_count` is capped at 3; near-identical candidates collapse via dedupe.
- No streaming; one synchronous completion per candidate.

## Next phase (not in this task)

Optional: richer brief controls in the UI (angle family / route selectors), and
multi-candidate side-by-side review. Must continue to feed the approve gate only —
never the deterministic final compiler.
