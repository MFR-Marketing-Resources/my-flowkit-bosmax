# Multi-Provider Vision Lane Adapters V1

Status: implemented. Extends the Dynamic AI Model Catalog & Explicit Lane
Configuration V3 (PR #208) so the **Vision Lane is no longer Anthropic-only**.
Product-image analysis can now run through Anthropic, OpenAI, Gemini, or Qwen —
each backed by a real, tested runtime transport, not a catalog-only claim.

## Scope

The Vision Lane powers **product-image analysis / image understanding only**
(`agent/services/product_image_analysis_service.py`). It never touches the
deterministic 9-section compiler and never produces final engine-facing prompts.

## Supported vision providers & transports

Two real transports serve the vision lane. A provider is vision-eligible only if
its declared transport is in `LANE_TRANSPORT_SUPPORT["vision"]` **and** the chosen
model lists the `vision` lane.

| Provider  | Transport                 | Endpoint (default, override per deployment)                          | Seed vision model(s)            |
|-----------|---------------------------|---------------------------------------------------------------------|---------------------------------|
| Anthropic | `anthropic_messages`      | `https://api.anthropic.com` (`/v1/messages`, Anthropic SDK)         | claude-sonnet-5 / haiku / opus  |
| OpenAI    | `openai_compatible_chat`  | `https://api.openai.com/v1` (`/chat/completions`)                   | gpt-4o, gpt-4o-mini             |
| Gemini    | `openai_compatible_chat`  | `https://generativelanguage.googleapis.com/v1beta/openai`          | gemini-2.0-flash                |
| Qwen-VL   | `openai_compatible_chat`  | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`           | qwen-vl-max                     |

- **Anthropic** keeps its existing SDK path in `product_image_analysis_service`
  (`_analyze_with_anthropic`) — unchanged, zero regression.
- **OpenAI / Gemini / Qwen-VL** share ONE wired transport in
  `agent/services/vision_provider_adapter.py`. There is no second Anthropic code
  path and no per-provider copy-paste.

## Transport formats

### OpenAI-compatible (`vision_provider_adapter.py`)

`POST {base_url}/chat/completions` with a single multimodal user turn:

```json
{
  "model": "<selected vision model>",
  "max_tokens": 500,
  "temperature": 0,
  "messages": [
    {"role": "user", "content": [
      {"type": "text", "text": "Product title context: <title>"},
      {"type": "text", "text": "<JSON-only analysis prompt>"},
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<...>"}}
    ]}
  ]
}
```

- Local images become a base64 `data:` URL; a remote image is passed as an
  `https` URL. Exactly one image source per request.
- The key travels only in the `Authorization: Bearer <key>` header — never in the
  prompt, the response, logs, or telemetry.

### Anthropic (existing, preserved)

`client.messages.create(...)` with `content` blocks
(`{"type": "image", "source": {"type": "base64"|"url", ...}}`). Untouched.

## Fail-closed behavior (no hidden defaults)

- **Fresh install → `NOT_CONFIGURED`.** No provider/model/key/execution is
  auto-selected for either lane. The operator must explicitly choose provider +
  model, store a key, and turn on the execution toggle.
- `vision_provider_adapter.run_vision_completion` raises when the key or model is
  unresolved, when the transport is not implemented (e.g. Anthropic is rejected by
  this adapter — it is served by the SDK path), or on any network/shape error.
- `product_image_analysis_service` maps an unconfigured lane to
  `VISION_PROVIDER_NOT_CONFIGURED`, a disabled execution toggle to
  `ANALYSIS_SKIPPED`, and any adapter failure to `ANALYSIS_FAILED` — it never
  fabricates detections.
- The operator-selected **vision lane model is authoritative** for every provider
  (`get_lane_model("vision")`); the deployment default is only a last-resort
  fallback, never a silent override.

## How to add a custom vision model

Vision-capable model IDs change often. Operators can add one with **no code
change** via the Settings page ("Add custom model", tick **vision**) or:

```
PUT /api/ai-providers/model-catalog/{provider}/models/{model_id}
{ "label": "My VL model", "lanes": ["vision"], "enabled": true }
```

The lane checkbox / API accepts `vision` only for providers whose transport is a
wired vision transport (`anthropic_messages` or `openai_compatible_chat`). A
text-only model still cannot be selected for vision (`MODEL_NOT_SUPPORTED_FOR_LANE`).

## No compiler impact

The Vision Lane is confined to image understanding. The deterministic canonical
prompt compiler and the final prompt path are untouched and unaware of provider
selection.

## Known limitations

- **DeepSeek** ships no vision model and is intentionally not vision-eligible.
- Gemini and Qwen-VL are reached through their **OpenAI-compatible** endpoints
  (not their native REST APIs). If a deployment needs the native API, override
  `PRODUCT_VISION_BASE_URL` or add a transport.
- Seed model IDs (`gpt-4o`, `gemini-2.0-flash`, `qwen-vl-max`) are starter
  presets. Providers rename models over time — use custom-model entry to track
  changes without a release.
- Live provider round-trips are exercised via mocked HTTP in tests (payload shape,
  headers, fail-closed, no key leak). Real end-to-end calls require the operator's
  own keys and are gated behind the execution toggle.
