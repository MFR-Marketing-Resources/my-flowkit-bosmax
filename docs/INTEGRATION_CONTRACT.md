# OTAK ↔ TANGAN Integration Contract

> The HTTP seam between **BOSMAX (OTAK / prompt+scene brain)** and
> **`_ref_flowkit` (TANGAN / Google Flow execution service)**.
> Local-first, cloud-ready. Two repos, **zero git coupling** — they talk over HTTP only.
>
> Companion docs: `docs/AISANDBOX_API_HANDOFF.md` (how TANGAN talks to Google),
> `scripts/api_shoot_video.py` (proven end-to-end reference).

```
[ BOSMAX OTAK ]──envelope(JSON)──▶[ TANGAN :8100 ]──WS──▶[ Chrome ext + Flow tab ]──▶ Google Flow
  builds prompt+frame brief         FastAPI service          token + reCAPTCHA          aisandbox API
```

---

## 1. Transport & base URL (cloud-ready rule)

- All calls are **plain HTTP + JSON**. No code import across repos.
- Base URL is **config-driven**, never hardcoded:
  ```
  FLOW_API_BASE = "http://127.0.0.1:8100"   # local today
                  → swap one env var to migrate to a hosted box later
  ```
- **Honest limit:** swapping the base URL moves the *software*. It does NOT solve the
  per-user token/extension/account wall (each Flow session needs its own logged-in
  browser + extension + paid account). True multi-user hosting is a separate problem.

---

## 2. Preconditions (the 3 things that must be live)

A generate call only succeeds when **all three** hold. Check before enabling a
"Generate" button.

| # | Precondition | How to detect | Failure |
|---|---|---|---|
| 1 | TANGAN backend running | `GET /health` responds | connection refused |
| 2 | Chrome extension connected + Flow tab logged in | `GET /api/flow/status` → `connected:true, flow_key_present:true` | **HTTP 503** "Extension not connected" |
| 3 | Account on a **paid tier** | `GET /api/flow/credits` → `userPaygateTier ∈ {PAYGATE_TIER_ONE, _TWO}` | video → **500/no-model** |

`GET /health` (top-level) → `{ extension_connected, flow_key_present, tier? }`
`GET /api/flow/status` → `{ connected, flow_key_present }`

> **Rule for the web/OTAK side:** poll `/health` + `/credits` first; show a clear
> "not ready" state instead of letting a job 503/500 mid-flight.

---

## 3. Existing endpoints (BUILT — verified in `agent/api/flow.py`)

All POST bodies are JSON. Uniform error contract on every handler:
- **503** — extension not connected (precondition 2).
- **502** — upstream Google error (message passed through).
- **500 / "No model for tier=..."** — paid-tier gate (precondition 3) or Google INTERNAL.
- **200** — returns Google's `data` payload.

### 3.1 `GET /api/flow/credits` — tier & balance (free, read-only)
→ `{ "credits": 1120, "userPaygateTier": "PAYGATE_TIER_NOT_PAID", "sku": "...",
     "topUpCredits": 1070, "subscriptionCredits": 50 }`

### 3.2 `POST /api/flow/create-project-raw`
```json
{ "project_title": "string", "tool_name": "PINHOLE" }
```
→ response contains `projectId`.

### 3.3 `POST /api/flow/generate-image` — AI frame (works on freemium, 0 credits)
```json
{ "prompt": "string", "project_id": "UUID",
  "aspect_ratio": "IMAGE_ASPECT_RATIO_PORTRAIT", "user_paygate_tier": "PAYGATE_TIER_ONE" }
```
→ `media[0].name` = **media_id (UUID)** · `media[0].image.generatedImage.fifeUrl` = signed image URL

### 3.4 `POST /api/flow/upload-image-base64` — real product frame (web upload)
```json
{ "image_base64": "....", "mime_type": "image/png",
  "project_id": "UUID", "file_name": "product.png" }
```
→ **`{ "media_id": "UUID", "raw": {...} }`** — read the top-level `media_id`.
(Local-file variant: `POST /api/flow/upload-image` with `{file_path, project_id, file_name}` → same `{media_id, raw}` shape.)

> ⚠️ **Shape difference (lock this):** `generate-image` (§3.3) returns `media[0].name`
> (a list); the upload endpoints return a clean top-level **`media_id`**. The adapter's
> media-id reader must handle **both**.

### 3.5 `POST /api/flow/generate-video` — submit i2v (returns operations, **not** the video)
```json
{ "start_image_media_id": "UUID", "prompt": "string", "project_id": "UUID",
  "scene_id": "string", "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
  "end_image_media_id": null, "user_paygate_tier": "PAYGATE_TIER_ONE" }
```
→ `operations[]` each `{ operation:{name}, status:"MEDIA_GENERATION_STATUS_PENDING" }`

### 3.6 `POST /api/flow/check-status` — poll the operations
```json
{ "operations": [ ...from 3.5... ] }
```
→ `operations[]` with `status ∈ PENDING | SUCCESSFUL | FAILED`; on SUCCESSFUL the op
carries the video media (look for `fifeUrl` / `servingUrl` / `url`).

---

## 4. The NEW one-shot async endpoint (TO BUILD — TANGAN side)

Video gen takes **~6–7 min**. A blocking HTTP call is unacceptable. The seam is async:

### 4.1 `POST /api/flow/shoot-oneshot` — submit, returns immediately
**Input = the OTAK envelope (§5).** Internally chains: precheck → create project →
start frame (AI `generate-image` **or** `upload-image-base64`) → `generate-video` →
background poll. Reuses the existing worker/job infra.
→ **202** `{ "job_id": "j_xxx", "status": "SUBMITTED" }`
→ **503/500** immediately if a precondition fails (so the UI fails fast, not after 7 min).

> ✅ **`/shoot-oneshot` mints `project_id` (via create-project) AND an internal
> `scene_id` itself.** The OTAK envelope (§5) **must NOT** carry them — the adapter is
> correct to omit both. They are TANGAN-internal identifiers.

### 4.2 `GET /api/flow/job/{job_id}` — poll
→ `{ "job_id": "j_xxx",
     "status": "SUBMITTED | RUNNING_FRAME | SUBMITTED_VIDEO | POLLING | SUCCESSFUL | FAILED",
     "stage": "human-readable",
     "video_url": "https://... signed, EXPIRES (when SUCCESSFUL)",
     "local_path": "TANGAN-stored copy (when SUCCESSFUL)",
     "media_id": "video media_id (for re-signing)",
     "error": "null | message (when FAILED)" }`

> Web UI flow: POST shoot-oneshot → store `job_id` → poll `GET /job/{id}` every ~10s →
> render `video_url` when `SUCCESSFUL`, or the error.

> ⚠️ **URL expiry (lock this):** `video_url` is a **signed GCS URL with an `Expires`
> param — it dies after a window.** Do **not** persist the URL long-term. Two defenses,
> both available:
> - `/shoot-oneshot` **downloads the video bytes to TANGAN storage on success** and
>   returns `local_path` → persist/serve the bytes, not the URL.
> - To re-sign on demand: `GET /api/flow/media/{media_id}` (single) or
>   `POST /api/flow/refresh-urls/{project_id}` (bulk) → fresh `fifeUrl`/`servingUri`.

---

## 5. The OTAK → TANGAN envelope (the seam BOSMAX must emit)

This is the single JSON object BOSMAX's adapter produces per job:

```json
{
  "prompt": "<video motion prompt from BOSMAX block_script_json>",
  "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
  "user_paygate_tier": "PAYGATE_TIER_ONE",
  "start_frame": {
    "mode": "ai" | "upload",
    "image_prompt": "<used when mode=ai — BOSMAX scene/product brief>",
    "image_base64": "<used when mode=upload — real product photo bytes>",
    "mime_type": "image/png"
  }
}
```

Mapping rules:
- `mode:"upload"` → TANGAN calls `upload-image-base64` (real product — the BOSMAX
  "product is the anchor" requirement). **Default for product ads.**
- `mode:"ai"` → TANGAN calls `generate-image` with `image_prompt` (scene/B-roll frames).
- `prompt` → `generate-video.prompt` (i2v motion).
- `aspect_ratio`/`user_paygate_tier` pass straight through.

BOSMAX already has the pieces to fill this (`video_prompt_compiler.py`
`FLOW_EXTEND_UI_V1`, `asset_role_map`, `storyboard.block_script_json`, aspect). The
adapter's only job is to **project them into this envelope** instead of copy-paste text.

---

## 6. Error-handling guide (web/OTAK side)

| Symptom | Meaning | Action |
|---|---|---|
| Connection refused | TANGAN backend down | start the local agent |
| **503** "Extension not connected" | Flow tab/extension not live | tell operator to open + log in to Flow tab |
| `userPaygateTier=NOT_PAID` / 500 no-model | not a paid account | block video; allow image-only |
| First generate `CAPTCHA_FAILED ...TIMEOUT` | reCAPTCHA cold start | **retry** (already built into one-shot) |
| **502** | Google upstream error | surface message; retry once |

---

## 7. Build status

| Piece | Status |
|---|---|
| credits / status / health | ✅ built |
| create-project-raw | ✅ built |
| generate-image (AI frame) | ✅ built, proven on freemium |
| upload-image-base64 (product frame) | ✅ built |
| generate-video + check-status | ✅ built (submit+poll) |
| **`/shoot-oneshot` + `/job/{id}` (async)** | ⏳ **TANGAN to build** (§4) |
| BOSMAX → envelope adapter (§5) | ⏳ **OTAK to build** |

**Provable on freemium today (no Pro):** envelope → `generate-image` → media_id →
*(stop before generate-video)*. Only the final `generate-video` step needs Pro.
