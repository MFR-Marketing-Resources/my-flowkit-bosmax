# Dynamic AI Model Catalog & Explicit Lane Configuration V1

Supersedes the runtime-default behavior of `AI_PROVIDER_MODEL_AND_LANE_SETTINGS_V1`.
Provider/model/lane configuration is now **operator-owned and mutable**, and lanes
are **explicit** — a fresh install auto-selects nothing.

The deterministic final compiler is untouched. No AI provider generates the final
9-section prompt. These settings affect the AI assist / product-knowledge / vision
lanes only.

## Why hardcoded runtime defaults were removed

PR #202 kept a static `PROVIDER_MODEL_CATALOG` in source and seeded lanes with
hardcoded defaults (`text_assist → qwen/qwen-plus`, `vision → anthropic/…`). That
made the system look opinionated before the operator decided anything, and adding a
new model ID (e.g. a new DeepSeek model) required a code patch. V1 fixes both:
lanes are explicit and the model catalog is mutable local state.

## Seed catalog vs. mutable catalog

- **Seed catalog** — reference constants in
  `agent/services/ai_provider_model_catalog.py` (`SEED_CATALOG`). A bootstrap/
  reference layer only; it does **not** force a runtime lane default.
- **Mutable catalog** — `.local-agent/ai-model-catalog.json` (untracked). Seeded
  from the seed catalog on first run, then freely editable. Operator edits persist
  here, outside tracked code. A non-destructive forward merge only *adds* seed
  providers that are missing; it never overwrites operator edits.

Catalog shape:

```json
{
  "version": 1,
  "providers": {
    "deepseek": {
      "label": "DeepSeek",
      "transport": "openai_compatible_chat",
      "enabled": true,
      "models": [
        { "model_id": "deepseek-chat", "label": "DeepSeek Chat", "enabled": true, "lanes": ["text_assist"], "source": "seed" }
      ]
    }
  }
}
```

A `model_id` is treated as operator-provided runtime config, **not** a claim the
model exists.

## Transports

Each provider declares one `transport`:

- `openai_compatible_chat` — qwen, openai, gemini, deepseek (`/chat/completions`).
- `anthropic_messages` — anthropic (`/v1/messages`).

A model may serve a lane only if the provider's transport implements that lane
(`LANE_TRANSPORT_SUPPORT`): `text_assist` is served by both transports; `vision` is
served only by `anthropic_messages` (the wired vision provider). An unknown or
unsupported transport **fails closed** and is never runnable.

## How to add a custom model (no code change)

UI: **Settings → AI Provider Registry → (provider card) → Add custom model**. Enter
`model_id`, an optional label, and tick the lane(s). Or via API:

```txt
PUT /api/ai-providers/model-catalog/{provider_id}/models/{model_id}
{ "label": "DeepSeek Reasoner", "lanes": ["text_assist"], "enabled": true }
```

Example: add `deepseek-reasoner` (or any future DeepSeek ID) to DeepSeek. It appears
in the DeepSeek model dropdowns immediately. Adding a `vision` lane to an
`openai_compatible_chat` provider is rejected (`TRANSPORT_NOT_SUPPORTED_FOR_LANE`).

Disable a model: `PATCH /api/ai-providers/model-catalog/{provider_id}/models/{model_id}/disable`.
Restore presets: `POST /api/ai-providers/model-catalog/reset-seed`.

## How lane configuration works

State V3 (`.local-agent/ai-provider-settings.json`):

```json
{
  "version": 3,
  "active_provider": null,
  "providers": { "qwen": { "api_key": "", "updated_at": null, "activated_at": null, "default_model": null } },
  "lanes": {
    "text_assist": { "provider_id": null, "model_id": null, "execution_enabled": false, "configured_by_user": false },
    "vision":      { "provider_id": null, "model_id": null, "execution_enabled": false, "configured_by_user": false }
  }
}
```

Configure a lane: `PUT /api/ai-providers/lanes/{lane}` with `{provider_id, model_id,
execution_enabled?}` — validated against the mutable catalog (existence, enabled,
lane membership, transport). Clear a lane back to NOT_CONFIGURED:
`DELETE /api/ai-providers/lanes/{lane}`.

Each lane reports a **status** in the registry response:

`NOT_CONFIGURED` → `MODEL_MISSING` → `MODEL_DISABLED` → `KEY_MISSING` →
`EXECUTION_DISABLED` → `READY`. The response also exposes `key_present`,
`model_valid`, and `configured_by_user` so the UI can render precisely and only
enable the execution toggle once provider + model + key are all present.

**Global active provider** stays a legacy runtime-wide selector; it does **not**
decide lane provider/model. The UI states this explicitly.

## Why first-run lanes are NOT_CONFIGURED

A new install must not silently activate Qwen or Anthropic. `_default_payload`
ships both lanes as `provider_id=null, model_id=null, execution_enabled=false`. No
`get_lane_provider` / `get_lane_model` fallback exists — unconfigured resolves to
`None` and every runtime consumer fails closed.

### Migration (deterministic)

- **V1** (no lanes): keys preserved; lanes → NOT_CONFIGURED.
- **V2**: for each lane — preserved as `configured_by_user` iff its provider has a
  stored key **or** it deviates from the old hardcoded seed default; otherwise (a
  pure seeded default with no key) → NOT_CONFIGURED. Keys are always preserved.
- **V3**: preserved verbatim.
- A plain read never rewrites a valid existing file.

## Runtime behavior

- **AI Copy Assist** (`text_assist`): uses the selected lane provider/model only.
  Fails closed with `AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED` when the lane lacks a
  configured provider+model, a key, or execution. **No fallback to qwen; no hidden
  default.** Anthropic text_assist runs on the native `/v1/messages` transport;
  transport is chosen from the catalog, and an unknown transport fails closed.
- **Product Knowledge** (Qwen USP extraction): runs only when the `text_assist`
  lane provider is `qwen` (it posts to the Qwen/DashScope endpoint). When the lane
  is unconfigured or non-Qwen, it is skipped before any key is read — no fallback to
  qwen, no non-Qwen key ever sent to the Qwen endpoint.
- **Vision**: a selection surface. It stays NOT_CONFIGURED until an operator
  configures it; no hidden Anthropic default. Actual vision execution remains owned
  by `product_image_analysis_service`.

## Autodiscovery / Refresh Models

Not implemented in V1 — provider list-model APIs are not wired. Manual add/edit is
the supported path. A future `Refresh Models` button is out of scope until those
provider APIs are implemented and tested.

## Guarantees

- No raw API key in any API/UI response, log, doc, or tracked file (masked only).
- No deterministic compiler change; no AI on the final prompt path.
- Existing keys preserved across migration; existing explicit lane config preserved.
- New model IDs require no code change.
