# Google Flow (aisandbox) API — Handoff Note for a New System

> Purpose: everything proven in this project about driving Google Flow **via its
> private API** (`aisandbox-pa.googleapis.com`) instead of clicking the UI, so the
> logic can be lifted cleanly into a new/updated system.
>
> Status (2026-06-29): API generation **mechanism proven alive** — project create +
> image generation work end-to-end, zero UI clicks, zero credits burned on freemium.
> Veo **video** is entitlement-gated to **paid tiers** (Pro = TIER_ONE, Ultra = TIER_TWO).

---

## 0. Plain-language summary (read this first)

- Google Flow's website talks to a **hidden Google API** at `aisandbox-pa.googleapis.com`.
  "aisandbox" is just Google's internal name for the backend that Flow/Veo runs on.
- If you have **(a) a logged-in user's token** and **(b) a way to pass Google's
  reCAPTCHA check**, you can call that API **directly** — create projects, generate
  images, generate Veo videos — **without ever clicking the Flow website**.
- That is the whole point: the UI-clicking layer (the brittle part that broke every
  time Google changed Flow) **disappears**. You talk to the API.
- The **hard parts** are not the API calls (they're simple HTTP). The hard parts are:
  1. **Getting a valid user token** (only a logged-in browser has it), and
  2. **Solving reCAPTCHA** (Google requires a fresh token per generate call).
  This project solves both with a **Chrome extension** that captures the token and
  injects a solved reCAPTCHA. A new system must solve these two things **somehow**.

---

## 1. What `aisandbox-pa.googleapis.com` is

- Google Flow / Veo's **private generation backend** (not a public/documented API).
- Base URL: `https://aisandbox-pa.googleapis.com`
- Every request carries a **public web-app API key** as `?key=...` (this is NOT a
  secret — it is embedded in the Flow web client) **plus** a **per-user bearer token**
  (the real auth) injected by the browser/extension.
- Because it is private, Google **can change it without notice** and automated use is
  against Flow's ToS — treat as an unstable dependency (see §10).

---

## 2. The auth model (the part that actually matters)

Three things travel with a generate call:

| Item | What it is | Secret? | Where it comes from |
|---|---|---|---|
| `?key=AIza...` | Public Flow web-app API key | No (public) | Hardcoded — see config |
| reCAPTCHA token | Fresh per-call bot check | Per-call | Solved live in a browser context |
| **User bearer token** (`flowKey`) | The logged-in user's auth | **YES** | Captured from the live Flow session |

**Static/public values currently used** (from `agent/config.py`):
```
GOOGLE_FLOW_API   = "https://aisandbox-pa.googleapis.com"
GOOGLE_API_KEY    = "AIzaSyBtrm0o5ab1c-Ec8ZuLcGt3oJAA5VWt3pY"   # public web-app key
RECAPTCHA_SITE_KEY= "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"   # public site key
```
> These two are the **same for everyone** — they are baked into Flow's website. They
> are NOT the thing that authenticates you. The **user bearer token is**, and it is
> per-account, per-session, and expires — so it must be captured live each time.

**How this project captures token + solves reCAPTCHA:** a Chrome extension (MV3) sits
on the logged-in Flow tab. It (1) sniffs the bearer token out of the live session and
hands it to the local agent, and (2) when a generate call needs reCAPTCHA, it runs the
solve **in the page context** and injects the resulting token. The Python side never
sees a browser — it just sends "do this fetch" over a WebSocket and the extension
performs it inside the authenticated page.

**Transport (Python → extension):** `FlowClient._send(type, params)` pushes a JSON
message over WebSocket to the extension and waits on a future keyed by request id.
Message types used for the API path:
- `"api_request"` → extension does `fetch(url, {method, headers, body})` against
  aisandbox, **injecting the bearer token + solved reCAPTCHA** (driven by the
  `captchaAction` field, e.g. `"VIDEO_GENERATION"`).
- `"trpc_request"` → same idea but for Flow's tRPC endpoints (project create).
- (`"EXECUTE_FLOW_JOB"` etc. are the OLD DOM-automation path — **not** needed for the
  API path; ignore for the new system.)

> **Porting implication:** the new system needs *any* mechanism that yields a live
> token + a solved reCAPTCHA. Options: keep a thin browser extension; OR drive a
> persistent logged-in headless browser (Playwright) to capture token + solve captcha;
> OR intercept the token from network traffic. The API calls below are the easy 20%.

---

## 3. Endpoint map (from `agent/config.py` → `ENDPOINTS`)

All are `GOOGLE_FLOW_API + path`, with `?key=GOOGLE_API_KEY` appended by `_build_url()`.

| Key | Path | Purpose |
|---|---|---|
| `get_credits` | `/v1/credits` | Read tier + credit balance (**free, read-only**) |
| `generate_images` | `/v1/projects/{project_id}/flowMedia:batchGenerateImages` | Image gen (Nano Banana) |
| `generate_video` | `/v1/video:batchAsyncGenerateVideoStartImage` | i2v (one start frame) |
| `generate_video_start_end` | `/v1/video:batchAsyncGenerateVideoStartAndEndImage` | i2v with start+end frame |
| `generate_video_references` | `/v1/video:batchAsyncGenerateVideoReferenceImages` | r2v (multi reference images) |
| `upscale_video` | `/v1/video:batchAsyncGenerateVideoUpsampleVideo` | 1080p/4K upscale |
| `check_video_status` | `/v1/video:batchCheckAsyncVideoGenerationStatus` | Poll async video ops |
| `upload_image` | `/v1/flow/uploadImage` | Upload a local image → media_id |
| `upscale_image` | `/v1/flow/upsampleImage` | Image upscale |
| `get_media` | `/v1/media/{media_id}` | Fetch a media record |

Project create is **not** on aisandbox — it is a Flow tRPC call:
```
POST https://labs.google/fx/api/trpc/project.createProject
body: {"json": {"projectTitle": "...", "toolName": "PINHOLE"}}
```

`_build_url`:
```python
def _build_url(self, endpoint_key, **kwargs):
    path = ENDPOINTS[endpoint_key].format(**kwargs)
    sep = "&" if "?" in path else "?"
    return f"{GOOGLE_FLOW_API}{path}{sep}key={GOOGLE_API_KEY}"
```

---

## 4. Tier → model mapping + entitlement reality (from `agent/models.json`)

The account's **paygate tier** decides which Veo model key you may use. This is the
gate that blocks freemium video.

| Paygate tier | = Google product | i2v portrait model key | Video? |
|---|---|---|---|
| `PAYGATE_TIER_NOT_PAID` | Free / freemium | **(none in catalog)** | ❌ image only |
| `PAYGATE_TIER_ONE` | **AI Pro** ($19.99/mo) | `veo_3_1_i2v_s_fast_portrait` | ✅ |
| `PAYGATE_TIER_TWO` | **AI Ultra** ($249/mo) | `veo_3_1_i2v_s_fast_ultra_relaxed` | ✅ |

Full `models.json` video block:
```json
{
  "video_models": {
    "PAYGATE_TIER_TWO": {
      "frame_2_video":            {"...LANDSCAPE": "veo_3_1_i2v_s_fast_ultra_relaxed",
                                   "...PORTRAIT":  "veo_3_1_i2v_s_fast_ultra_relaxed"},
      "start_end_frame_2_video":  {"...": "veo_3_1_i2v_s_fast_ultra_relaxed"},
      "reference_frame_2_video":  {"...": "veo_3_1_r2v_fast_landscape_ultra_relaxed"}
    },
    "PAYGATE_TIER_ONE": {
      "frame_2_video":            {"...LANDSCAPE": "veo_3_1_i2v_s_fast",
                                   "...PORTRAIT":  "veo_3_1_i2v_s_fast_portrait"},
      "start_end_frame_2_video":  {"...LANDSCAPE": "veo_3_1_i2v_s_fast_fl",
                                   "...PORTRAIT":  "veo_3_1_i2v_s_fast_portrait_fl"},
      "reference_frame_2_video":  {"...": "veo_3_1_r2v_fast / _portrait"}
    }
  },
  "upscale_models": {"VIDEO_RESOLUTION_4K": "veo_3_1_upsampler_4k",
                     "VIDEO_RESOLUTION_1080P": "veo_3_1_upsampler_1080p"},
  "image_models":   {"NANO_BANANA_PRO": "GEM_PIX_2", "NANO_BANANA_2": "NARWHAL"}
}
```
**Confirmed (official Google sources):** AI Pro = "Veo 3.1 Fast" → matches the
`veo_3_1_i2v_s_fast*` keys under `PAYGATE_TIER_ONE`. So **Pro unlocks the API video
path.** A `NOT_PAID` account returns *"No model for tier=PAYGATE_TIER_NOT_PAID"* and
Google answers **500 INTERNAL** if you force a paid model key on it.

> **Money note:** the gate is the **subscription tier**, NOT credits. An account can
> hold purchased credits and still be `NOT_PAID` → still no video. You must subscribe
> Pro/Ultra to flip the tier.

---

## 5. Request / response shapes (the calls to port)

### 5.1 Read credits / tier (free, do this first to know what an account can do)
```
GET  _build_url("get_credits")        # via "api_request", no captcha
→ {"credits": 1120, "userPaygateTier": "PAYGATE_TIER_NOT_PAID",
   "sku": "G1_FREEMIUM", "topUpCredits": 1070, "subscriptionCredits": 50}
```

### 5.2 Create project (tRPC, not aisandbox)
```
POST https://labs.google/fx/api/trpc/project.createProject
body: {"json": {"projectTitle": "...", "toolName": "PINHOLE"}}
→ response contains projectId
```

### 5.3 Generate image (Nano Banana) — works even on freemium
```
POST _build_url("generate_images", project_id=PID)   # via "api_request" + captcha
→ media[0].name           = <media_id UUID>          # use as start frame
  media[0].image.generatedImage.fifeUrl = <signed image URL, downloadable>
  media[0].image.generatedImage.mediaId = <same UUID>
```

### 5.4 Generate video (i2v) — the shape that 500s on freemium, works on paid
```python
model_key = VIDEO_MODELS[user_paygate_tier]["frame_2_video"][aspect_ratio]
request = {
    "aspectRatio": aspect_ratio,                               # VIDEO_ASPECT_RATIO_PORTRAIT
    "seed": int(time.time()) % 10000,
    "textInput": {"structuredPrompt": {"parts": [{"text": prompt}]}},
    "videoModelKey": model_key,                                # from models.json by tier
    "startImage": {"mediaId": start_image_media_id},           # UUID from 5.3 or uploadImage
    "metadata": {"sceneId": scene_id},
    # optional: "endImage": {"mediaId": end_id}  → use endpoint generate_video_start_end
}
body = {
    "mediaGenerationContext": {"batchId": str(uuid4())},
    "clientContext": client_context(project_id, user_paygate_tier),
    "requests": [request],
    "useV2ModelConfig": True,
}
POST _build_url("generate_video")   # via "api_request", captchaAction="VIDEO_GENERATION"
→ data.operations[] each: {operation:{name:<op_id>}, status:"MEDIA_GENERATION_STATUS_PENDING"}
```

`client_context` (recaptcha token left empty — extension fills it):
```python
{
  "projectId": project_id,
  "recaptchaContext": {"applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB", "token": ""},
  "sessionId": f";{int(time.time()*1000)}",
  "tool": "PINHOLE",
  "userPaygateTier": user_paygate_tier,
}
```

### 5.5 Poll status (no captcha)
```
POST _build_url("check_video_status")  body: {"operations": <ops from 5.4>}
→ data.operations[] with status:
   MEDIA_GENERATION_STATUS_PENDING | _SUCCESSFUL | _FAILED
On _SUCCESSFUL the completed op carries the video media (look for fifeUrl/servingUrl/url).
Poll every ~10s, timeout ~360–420s.
```

---

## 6. reCAPTCHA mechanics (and the cold-start quirk)

- Generate calls (image/video/upscale) need `captchaAction` set; the extension solves
  reCAPTCHA in the page and injects the token. Read-only calls (credits, status) don't.
- **Cold-start quirk (proven):** the **first** generate call after idle often fails
  with `CAPTCHA_FAILED: ERR_MESSAGE_RESPONSE_TIMEOUT` / `ERR_RUNTIME_LASTERROR`.
  A **retry warms it up** and succeeds. A failed captcha burns **no credit**.
  → Always wrap generate calls in a small retry loop (see `scripts/api_shoot_video.py`).
- Requires a **live Flow tab open & logged in** for the solve to work.

---

## 7. End-to-end pipeline (the orchestration to replicate)

```
1. GET credits            → confirm tier ∈ {TIER_ONE, TIER_TWO}; else stop (no video)
2. create project         → project_id
3. start frame:
     option A: generate_images(prompt) → media_id (+fifeUrl)   [AI-generated frame]
     option B: upload_image(local_file) → media_id             [real product/asset frame]
4. generate_video(start_image_media_id, prompt, tier)  [retry on captcha cold-start]
                          → operations[]
5. poll check_video_status(operations) until SUCCESSFUL → video URL
```
Working reference implementation (self-contained, urllib, dry-run-safe):
**`scripts/api_shoot_video.py`** — mirrors this exact pipeline with tier auto-detect,
captcha retry, and a `--confirm-burn` gate.

---

## 8. What is PROVEN vs UNPROVEN (this project, 2026-06)

| Capability | Status |
|---|---|
| Read credits/tier via API | ✅ proven |
| Create project via API | ✅ proven |
| Generate image via API (freemium, 0 credits) | ✅ proven — real image + fifeUrl |
| reCAPTCHA solve + cold-start retry | ✅ proven |
| Clean request reaches Google (no UI) | ✅ proven |
| Veo **video** on freemium | ❌ blocked — entitlement (500 / no model) |
| Veo **video** on paid (Pro/Ultra) | ⏳ untested (needs paid account); wiring matches production `operations.py` |

---

## 9. Porting checklist for the new system

1. **Decide the token+captcha mechanism** (the only hard part):
   - Keep a minimal browser extension (current approach), OR
   - Persistent logged-in Playwright/CDP browser that captures the bearer token and
     solves reCAPTCHA, OR
   - Token interception from the authenticated session.
2. **Copy the static config** (`GOOGLE_FLOW_API`, public API key, recaptcha site key,
   `ENDPOINTS` map, `models.json`).
3. **Port the 5 calls** in §5 (credits, create project, generate image, generate video,
   check status). They are plain HTTP once token+captcha are handled.
4. **Tier-gate up front**: call credits first; refuse video unless tier ∈ {ONE, TWO}.
5. **Build captcha cold-start retry** into every generate call.
6. **Keep the poll loop** with the status enums in §5.5.
7. (Updated logic you mentioned) layer your new business rules — avatar/product
   resolution, prompt compiler, source modes — **on top of** this API client. The API
   client itself should stay a thin, dumb transport.

---

## 10. Risks & caveats (do not skip)

- **Private/undocumented API** — Google can change endpoints, model keys, or the
  request shape at any time. Pin nothing; expect drift.
- **ToS** — automated use of Flow's internal API is against Google's terms; accounts
  doing high-volume automation can be flagged/suspended. Use a disposable, separately
  funded account; cap spend; don't put your main identity on it.
- **Token expiry** — the user bearer token is short-lived; the capture mechanism must
  refresh it continuously, not once.
- **Entitlement** — video needs paid tier; verify with the free credits call before
  spending. Limits per tier (e.g. ~5 full-quality Veo/day on Pro) still apply.
- **reCAPTCHA** — Google can tighten this; the solve depends on a real logged-in tab.

---

## 11. Source files (pull from these)

| File | What to take |
|---|---|
| `agent/config.py` | `GOOGLE_FLOW_API`, public keys, `ENDPOINTS` map, poll/timeout constants |
| `agent/models.json` | tier → Veo model-key mapping, image/upscale model keys |
| `agent/services/flow_client.py` | `_build_url`, `_client_context`, `_send` transport, and the methods: `get_credits`, `create_project`, `generate_images`, `generate_video`, `generate_video_from_references`, `check_video_status`, `upload_image`, `upscale_video` |
| `agent/sdk/services/operations.py` | the proven submit→`_extract_operations`→`_poll_operations` pattern (video status enums, final-media extraction) |
| `scripts/api_shoot_video.py` | end-to-end, dry-run-safe reference orchestration |

> The DOM-automation lane (`extension/content-flow-dom.js`, `f2v-flow-queue-runner.js`,
> `execute_flow_job`) is the OLD UI-clicking path. **Do not port it** — the whole gain
> of the new system is dropping it in favour of the API path above.
