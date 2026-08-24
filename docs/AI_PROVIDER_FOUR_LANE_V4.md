# BOSMAX AI Provider Lane V4

Status: implementation contract for baseline `5980457b31bcb21390a6fb823f635136d6ef8fee`.

V4 replaces the two-lane `text_assist` / `vision` authority with four
independent, operator-owned lanes:

| Lane | Canonical id | Responsibility | Fresh-install state |
|---|---|---|---|
| Text | `text` | Natural-language copy, captions, angles, ideation, candidate drafts | `NOT_CONFIGURED` |
| Structure | `structure` | Strict JSON/schema calls, Product Intelligence, V3/FAST54 envelopes | `NOT_CONFIGURED` |
| Image | `image` | Product-image understanding and visual classification | `NOT_CONFIGURED` |
| Video | `video` | Explicit provider-backed video review, with provider/model/engine authority | `NOT_CONFIGURED` |

The legacy global active provider remains metadata for compatibility only. It
does not select, override, or repair any lane.

## Consumer mapping

Every runtime consumer of the lane getters, execution gates, or provider
adapters is mapped below. Compatibility names remain only in migration seams,
legacy API names, persisted provenance labels, or user-facing error strings.

### TEXT

- `agent/services/ai_copy_provider_adapter.py` — shared TEXT/STRUCTURE transport, lane gates, and bounded STRUCTURE fallback receipts.
- `agent/services/ai_copy_assist_service.py` — candidate generation.
- `agent/services/ai_caption_assist_service.py` — caption candidate JSON.
- `agent/services/copy_component_author_service.py` — copy component authoring.
- `agent/services/copy_angle_suggestion_service.py` — natural-language angle suggestions.
- `agent/services/poster_copy_ai_service.py` — poster copy candidates.
- `agent/services/poster_copy_fit_service.py` — poster copy fit/repair candidates.
- `agent/services/poster_copy_recommendation_service.py` — ephemeral copy kits.
- `agent/services/poster_builder_settings_service.py` — TEXT-lane readiness/status projection only.
- `agent/services/tiktokshop_extraction_service.py` — review-required marketplace copy candidates; deterministic extraction remains local.

### STRUCTURE

- `agent/services/storyboard_landbank_v3_round2.py` — V3/FAST54 proposal and projection envelopes.
- `agent/services/copy_register_v2_service.py` — strict V2 copy-register envelopes.
- `agent/services/catalog_authority_review_service.py` — catalog authority decisions.
- `agent/services/product_intelligence_prepare_service.py` — Product Intelligence draft envelope.
- `agent/services/product_intelligence_review_draft_service.py` — structured field fill.
- `agent/services/product_intelligence_recompute_service.py` — structured recompute status.
- `agent/services/product_knowledge_service.py` — evidence extraction/classification schema.
- `agent/api/products.py` — Product Intelligence readiness/prepare status.
- `agent/api/scene_context_registry.py` — strict scene context structure; duplicate-output retry removed.
- `agent/api/workspace_packages.py` — strict avatar/package structure; duplicate-output retry removed.

### IMAGE

- `agent/services/product_image_analysis_service.py` — product-image analysis and provider/model/key resolution through `image`.
- `agent/services/vision_provider_adapter.py` — OpenAI-compatible image-understanding transport for the `image` lane.

### VIDEO

- `agent/services/video_reviewer.py` — frame extraction plus the explicit `video` provider/model/engine lane. The historical implicit Claude CLI path is not a V4 runtime path.

The settings and model-catalog services themselves are lane authority, not
business consumers. Their public lane routes accept only `text`, `structure`,
`image`, and `video`; `text_assist` and `vision` are read/migration aliases only.
Read-only compatibility/status surfaces in `agent/api/ai_provider_settings.py`
and `agent/api/copy_register_v2.py` do not execute providers or select lanes.

## State migration: V3 to V4

`agent/services/ai_provider_settings_service.py` loads V1/V2/V3 state into a
canonical V4 payload and idempotently writes the upgrade. It preserves provider
keys, timestamps, active-provider metadata, default models, and lane execution
intent without logging key material.

- `vision` becomes `image`.
- An old `text_assist` entry is copied to both `text` and `structure` only when
  `configured_by_user=true`.
- Unconfigured legacy lanes do not create new configuration.
- `video` remains `NOT_CONFIGURED` unless a truthful explicit video authority
  already exists; V3 has no such authority.
- One canonical stored lane set is written: `text`, `structure`, `image`,
  `video`.
- The mutable model catalog normalizes old lane spellings on read while V4
  mutation APIs reject old aliases.

The external-state migration at
`scripts/migrate-canonical-runtime-state.ps1` stages `flow_agent.db`, `data\`,
and `.local-agent\ai-provider-settings.json` under the external
`FLOW_AGENT_DIR` state root. `scripts/migrate-provider-settings-state.py`
verifies source/destination metadata and key fingerprints without emitting key
values, refuses a populated/conflicting destination, and retains the source.

## Capability catalog

Capabilities are declared per model entry and are also transport-gated. A
provider identity alone never grants a lane.

- DeepSeek V4 Flash and V4 Pro: `text`, `structure`; no `image`, no `video`.
- OpenAI `gpt-5.6-luna`: label `GPT-5.6 Luna`, `text`, `structure` only under
  the current local adapter contract.
- Existing `gpt-4o` and `gpt-4o-mini` remain in the OpenAI catalog.
- Image-capable seeds remain independently selectable from Anthropic, OpenAI,
  Gemini, and Qwen where the catalog declares `image`.
- DeepSeek image capability is deliberately not seeded until first-party API
  evidence changes.

The official DeepSeek references checked for this decision are:

- [DeepSeek GitHub Copilot integration](https://api-docs.deepseek.com/quick_start/agent_integrations/github_copilot/) — V4 is documented as text-only in the image-handling guidance.
- [DeepSeek Anthropic API guide](https://api-docs.deepseek.com/guides/anthropic_api/) — image content is not supported by that API surface.
- [DeepSeek model list](https://api-docs.deepseek.com/api/list-models/), [V4 news](https://api-docs.deepseek.com/news/news260424/), and [pricing/quick start](https://api-docs.deepseek.com/quick_start/pricing/) — current V4 model/API references.

No hidden image proxy or capability label is introduced.

## Structure fallback

The `structure` lane persists a primary provider/model and an independently
visible fallback provider/model plus `fallback_enabled`.

The adapter permits at most one fallback call, only after a classified provider
capability/nonconformance failure (invalid structured response or an eligible
4xx capability/format response). It never retries the primary, traverses a
provider carousel, or recursively falls back. Deterministic BOSMAX errors,
Product Truth/evidence/approval blockers, database failures, authorization
failures, invalid operator configuration, and ordinary 5xx failures do not
trigger fallback. Primary and fallback receipts are retained as separate nested
receipt objects with no secrets.

## Settings and API

The Settings page renders exactly four authoritative lane cards. The Structure
card exposes primary and fallback controls. The Video card exposes provider,
model, execution, and engine. Model dropdowns filter to enabled models that
declare the selected lane. The global provider control is labelled legacy and
does not drive these cards.

`/api/ai-providers/lanes/{lane}` accepts only the four canonical IDs. Legacy
route aliases are rejected after migration; compatibility exists in the
settings/catalog read seams only.

Every lane is independently fail-closed until its provider/model (and video
engine where applicable), credential, and execution gate are valid. Four V4
execution environment gates are supported:

```text
BOSMAX_TEXT_EXECUTION_ENABLED
BOSMAX_STRUCTURE_EXECUTION_ENABLED
BOSMAX_IMAGE_EXECUTION_ENABLED
BOSMAX_VIDEO_EXECUTION_ENABLED
```

The older text/image gate names are compatibility reads only and are never
written as V4 state.

## Provider-free V3/FAST54 proof

With a local operator selection of DeepSeek V4 Flash as the Structure primary
and DeepSeek V4 Pro as the enabled Structure fallback, the V3/FAST54 service
reports `lane=structure`, primary `deepseek-v4-flash`, and fallback
`deepseek-v4-pro`. Without a key or execution gate, the adapter remains
`NOT_CONFIGURED`/`KEY_MISSING` and its HTTP seam is not reached. This proof is
covered by the V4 unit test and does not call a provider.

## Safety boundary

This architecture change does not call providers, Google Flow, or paid media
generation. It does not modify Product Truth or approval state. API keys are
never placed in registry responses, receipts, logs, docs, Git, or migration
reports; tests use isolated synthetic settings only.
