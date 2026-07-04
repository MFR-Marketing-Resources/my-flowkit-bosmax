# AI Provider Model & Lane Settings V1

Operator-facing model selection and lane routing for the AI Provider Registry.
This is additive to the existing key-storage + activation flow — it does **not**
touch the deterministic prompt compiler and adds **no** AI execution to the final
prompt path.

## What this adds

Before V1 the registry could store an API key per provider and mark one provider
"active", but the operator could **not**:

- choose a specific model per provider (e.g. `qwen-plus` vs `qwen-max`, or a
  specific Claude tier), or
- decide which provider/model each **lane** (`text_assist`, `vision`) uses.

V1 adds a per-provider default-model dropdown and an explicit **Lane Settings**
panel. The backend now resolves lane provider + model from stored operator state
(instead of hidden hardcoded defaults) and validates every provider/model/lane
combination server-side, failing closed on anything the catalog does not permit.

## Concepts

- **Provider key** — stored per provider under the local-agent state directory.
  Responses only ever expose `has_key` + a masked key; the raw key is never
  returned to the frontend and never written into tracked repo files.
- **Provider default model** — the pre-selected model for a provider, chosen from
  the provider's catalog.
- **Global active provider** — legacy runtime-wide selector. Kept for backward
  compatibility. It is **not** what decides which model a lane uses.
- **Lane** — a task category with its own provider + model + execution toggle:
  - `text_assist` — powers **AI Copy Assist** candidate generation.
  - `vision` — powers product-image vision tasks.

Global active provider vs. lane settings is the key clarification the UI now
makes explicit: **lane settings decide runtime provider/model; the active
provider does not.**

## Provider / model catalog

Source of truth: `agent/services/ai_provider_model_catalog.py`. Each model
declares which lanes it may serve and (informationally) which lanes it is the
catalog default for.

| Provider  | Models                                                        | Lanes                    |
| --------- | ------------------------------------------------------------- | ------------------------ |
| anthropic | Claude Sonnet 5, Claude Haiku 4.5, Claude Opus 4.8            | text_assist, vision      |
| qwen      | Qwen Plus (text default), Qwen Max                            | text_assist              |
| openai    | GPT-4o mini, GPT-4o                                           | text_assist              |
| gemini    | Gemini 2.0 Flash                                              | text_assist              |
| deepseek  | DeepSeek Chat                                                 | text_assist              |

Lane defaults: `text_assist` → qwen / `qwen-plus`; `vision` → anthropic /
`claude-sonnet-5`.

### Transport honesty

`text_assist` executes through `ai_copy_provider_adapter`:

- qwen / openai / gemini / deepseek use the OpenAI-compatible
  `/chat/completions` shape.
- **anthropic uses its native `/v1/messages` shape** (NOT OpenAI-compatible).
  This transport is implemented behind the adapter and unit-tested, so choosing
  Claude Haiku / Sonnet / Opus for `text_assist` is a real, working selection —
  not a false offer.

`vision` is a **selection surface** in V1: the registry lets an operator pick the
provider/model and toggle execution, but the actual vision execution lane is
owned by `product_image_analysis_service` and remains disabled-by-default. Enabling
the vision toggle here does not create a new vision call path.

## State schema (V2) + migration

State lives at `.local-agent/ai-provider-settings.json` (untracked). V2 shape:

```json
{
  "version": 2,
  "active_provider": null,
  "providers": {
    "qwen": {
      "api_key": "",
      "updated_at": null,
      "activated_at": null,
      "default_model": "qwen-plus"
    }
  },
  "lanes": {
    "text_assist": { "provider_id": "qwen", "model_id": "qwen-plus", "execution_enabled": true },
    "vision": { "provider_id": "anthropic", "model_id": "claude-sonnet-5", "execution_enabled": false }
  }
}
```

Migration is **backward-compatible and non-destructive**:

- A V1 file (no `default_model`, no `lanes`) loads and is migrated **in memory**.
  Existing `api_key` / `updated_at` / `activated_at` are preserved exactly.
- Missing `default_model` is backfilled from the catalog; missing/invalid
  `lanes` are seeded with safe defaults.
- A plain read never rewrites a valid V1 file — the file is only upgraded to V2
  on the next explicit save (key/model/lane update, activate, clear, deactivate).

## API

Prefix: `/api/ai-providers`.

| Method | Path                        | Purpose                              |
| ------ | --------------------------- | ------------------------------------ |
| GET    | `/`                         | Registry: providers, catalog, lanes  |
| PUT    | `/{provider_id}/key`        | Store provider key                   |
| DELETE | `/{provider_id}/key`        | Clear provider key                   |
| POST   | `/{provider_id}/activate`   | Set global active provider (legacy)  |
| POST   | `/deactivate`               | Clear global active provider         |
| PUT    | `/{provider_id}/model`      | Set provider default model           |
| PUT    | `/lanes/{lane}`             | Set lane provider + model (+ toggle)  |

`PUT /{provider_id}/model` body: `{ "model_id": "qwen-max" }`.
`PUT /lanes/{lane}` body: `{ "provider_id": "qwen", "model_id": "qwen-plus", "execution_enabled": true }`
(`execution_enabled` optional — omit/`null` leaves the toggle unchanged).

Every response is the full registry with: `active_provider`, `providers`
(masked keys + `default_model` + `supported_lanes`), `model_catalog`, and `lanes`
(each with `provider_id`, `model_id`, `execution_enabled`, `configured`). **No raw
API key ever appears.**

### Fail-closed validation (HTTP 422)

- `UNKNOWN_MODEL_FOR_PROVIDER:<provider>:<model>` — model not in the provider's catalog.
- `MODEL_NOT_SUPPORTED_FOR_LANE:<provider>:<model>:<lane>` — model may not serve the lane.
- `UNSUPPORTED_LANE:<lane>` / `UNSUPPORTED_PROVIDER:<provider>` — unknown lane/provider.

## Runtime behavior

### AI Copy Assist (`text_assist`)

- Uses `get_lane_provider("text_assist")`, `get_lane_model("text_assist")`,
  `get_lane_api_key("text_assist")`, `is_lane_execution_enabled("text_assist")`.
- The UI-selected lane model is **primary** and is what appears in
  `provider_status()` (`lane`, `configured`, `provider_id`, `model_id`,
  `execution_enabled`).
- Still fails closed with `AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED` when the lane
  has no key or execution is disabled. Still produces **candidate** Copy Sets only
  (`COPY_REVIEW_REQUIRED`), never auto-approved, never on the compiler path.

### Product Knowledge (`text_assist`)

The Qwen USP-extraction path honors the operator-selected `text_assist` model
**only when the lane provider is qwen** (that path is a qwen-specific transport).
When the lane points at a non-qwen provider it keeps the env/default qwen model —
documented limitation, not a silent wrong-model call. Default configuration
(qwen / `qwen-plus`) is unchanged.

### Environment overrides

Optional deployment overrides remain:

- `PRODUCT_TEXT_ASSIST_MODEL` / `PRODUCT_TEXT_ASSIST_BASE_URL` — transport overrides.
- `BOSMAX_TEXT_ASSIST_EXECUTION_ENABLED` / `BOSMAX_VISION_PROVIDER_EXECUTION_ENABLED`
  — an **explicitly set** value wins over stored state; otherwise the stored
  `execution_enabled` toggle decides; otherwise the conservative lane default
  (vision off, text_assist on).

The UI-selected setting is the normal operator path and is always visible in the
registry response.

## Guardrails honored

- Deterministic compiler unchanged; no provider generates the final 9-section prompt.
- No raw keys in any API/UI response; no keys in tracked files; no `.env` changes.
- Global active provider preserved as legacy; lane assignment is explicit.
- Provider/model/lane compatibility validated server-side; invalid combos fail closed.
- Existing V1 settings migrate without losing keys.
- Surgical patch: reuses the existing provider settings service + adapter seams.
