# Unified Generate Pipeline — THE one door for IMG / T2V / I2V / F2V

> **Status:** PROVEN end-to-end 2026-06-29 (real 2.0 MB mp4 saved from a user's uploaded image).
> **Read this before touching any generation code.** It tells you what is proven, what is
> frozen, what is dead, and where the single entry point is — so you don't fire-fight or
> reinvent the wheel.

---

## 0. Operating principles (locked)
1. **Don't fix what's not broken.**
2. **Don't reinvent the wheel.**
3. **Surgical patches only.** No full rewrites except a forced architecture change — and that
   needs explicit approval first.
4. **Verify before claim.** Never report success without the saved artifact on disk
   (mp4 `ftyp` header / image bytes). A credit drop or an "approved" flag is NOT proof.
5. **One entry point.** All generation goes through `POST /api/flow/generate`. Do not add
   parallel paths or resurrect the retired DOM automation.
6. **Ask before credits.** Each video ≈ 10 credits. DRY-run / ask the owner before any paid run.

---

## 1. The architecture decision (why this exists)
Google Flow's UI is now **Omni/V2** — a conversational **"Agent"** box ("What do you want to
create?"). The old **Video / Frames tab** UI is GONE. Therefore:

> **API-first. Extension = transport only (auth + reCAPTCHA + relay + harvest). Backend = brain.
> UI = thin buttons.**

DOM-clicking automation against the dead tab UI is the root cause of months of failures. It is
**retired**, not broken. Do not try to "fix" it.

```
UI (dashboard buttons) ──POST /api/flow/generate {mode}──▶ Backend pipeline ──▶ Extension (transport)
        ▲                                                        │                      │
        └──────────── poll GET /generate-job/{id} ◀─────────────┘         relay + harvest to Google
```

---

## 2. THE ONE DOOR
```
POST /api/flow/generate
{
  "mode": "IMG" | "T2V" | "I2V" | "F2V",   // required
  "prompt": "…",                            // required
  "project_id": "uuid",                     // optional (else a new project is minted)
  "image_media_ids": ["uuid", …],           // refs for I2V/F2V (e.g. user upload)
  "image_prompt": "…",                      // optional: auto start-frame if no refs (I2V/F2V)
  "aspect": "9:16" | "16:9"                 // default 9:16
}
→ { "job_id": "g_…", "status": "SUBMITTED", "mode": "…" }

GET /api/flow/generate-job/{job_id}
→ { status: SUBMITTED|SETUP|NEGOTIATING|GENERATING|DONE|FAILED,
    stage, mode, project_id, media_id, local_path, size_mb, artifact, error }
```
Async job — survives client timeouts. Poll until `DONE` (artifact saved) or `FAILED` (with reason).

### Mode matrix (modes = INPUT variants of ONE pipeline)
| Mode | Engine | Input | Credits | Notes |
|------|--------|-------|---------|-------|
| IMG  | direct `generate_images` (GEM_PIX_2) | prompt (+optional refs) | ~0 | downloads `fifeUrl` → `.jpg` |
| T2V  | agent (flowCreationAgent) | prompt only | ~10 | no reference |
| I2V  | agent | prompt + reference image(s) | ~10 | refs = uploaded media_ids |
| F2V  | agent | prompt + start frame(s) | ~10 | same path as I2V |

`I2V` and `F2V` are the same code path (reference images). `T2V` = no reference. `IMG` = different
engine (no agent, no video credits).

---

## 3. Internals (where the code lives)
- **Pipeline:** `agent/services/make_video.py` → `start_generate()` / `_run_generate()` (the one
  door's worker). Also `_save_video_by_get_media()` (robust retrieval).
- **Endpoint:** `agent/api/flow.py` → `POST /generate`, `GET /generate-job/{id}`.
- **Negotiation brain:** `agent/services/agent_video.py` — drives the conversational agent:
  - `parse_agent_sse()` → reads the SSE; `started` = `beginRendering` or a generate_video tool.
  - `decide()` — **REQUIRES `num_videos >= 1`**. Rejects image-only / `num_images` proposals
    (this bug once produced "only images"). Omni (15) → reject → steer to **Veo 3.1 Lite (10)** →
    **approve exactly once** (no double-charge).
- **Transport (extension):** `extension/background.js`
  - `handleApiRequest` solves reCAPTCHA (**action `CHAT_GENERATION`**) + injects token into
    `agentClientContext.recaptchaContext.token`.
  - `handleHarvestVideoUrls` (`HARVEST_VIDEO_URLS`) scans the Flow tab DOM → `projectId`,
    `videoIds`, `imageIds` (from `getMediaUrlRedirect?name={media_id}` srcs).
- **Retrieval (the part that was hard):** the finished video's `media_id` comes from the DOM
  harvest of the OPEN project (no tab drift). For each candidate, **`get_media(media_id)` returns
  the video BYTES as base64 `video.encodedVideo`** — accept ONLY if `encodedVideo` is present
  (real video), **excluding** the reference image id and `_STALE_VIDEO_IDS`. Save `.mp4`, verify.
- **Dashboard:** `dashboard/src/pages/OperatorPage.tsx` → `handleExecute` posts to `/generate` +
  `pollJob` (T2V/I2V/F2V); `handleGenerateImageApi` → `/generate-image-oneshot` (IMG). `npm run
  build` passes.

---

## 4. PROVEN (frozen — do not rewrite)
- The agent negotiation → approve → `beginRendering` (10 credits, Veo 3.1 Lite).
- `get_media` → `encodedVideo` → mp4 retrieval (saved real videos: `b267d480` 1.7 MB, `e7871bde`
  2.0 MB).
- **End-to-end I2V 2026-06-29:** user's uploaded 7Lume image (`f3ebd8c0`) in his project
  (`cb3ba639`) → real **2.0 MB H.264 mp4** `e7871bde…` (verified `ftyp isom … avc1` header).
- The `/generate` one door + dashboard wiring (build-validated).

## 5. DEAD (retired — do NOT resurrect or "fix")
- `extension/f2v-flow-queue-runner.js` — clicks Video/Frames/9:16/1x/Veo TABS that no longer exist.
- The Video/Frames tab SOP inside `extension/content-flow-dom.js`.
- `POST /api/flow/execute-flow-job` as a generation path from the dashboard (replaced by `/generate`).
- Direct video API `batchAsyncGenerateVideoStartImage` (`models.json` videoModelKey scheme) — 400/500.

## 6. TODO (not yet done)
- **Live-verify each mode once** from the button: IMG (cheap), T2V / I2V / F2V (~10 credits each —
  **ask the owner first**).
- Wire `image_media_ids` end-to-end from the dashboard upload UI for I2V/F2V (currently the engine
  accepts them; the UI passes `data.refs.*`).

---

## 7. For the next AI / agent
- Read `.ai/status/CURRENT_STATE.md` and `AGENTS.md` first.
- The owner (Faris) is non-technical and has been burned by **false success claims** and **wasted
  credits**. Verify with the saved file. Ask before any paid generation. State failures plainly.
