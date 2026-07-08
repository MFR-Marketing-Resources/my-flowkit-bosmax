# Results Hub v1 — durable deliverable + caption hub

## Why

Two operator needs converge on the same object — **one finished generation**:

1. **Manual-recovery archive.** If Google Flow automation breaks (Google ships a
   new UI, rate limiter, etc.), the operator must be able to open a finished
   result and copy the **exact prompt + settings** that produced it, to re-drive
   Flow by hand.
2. **Publish-ready deliverable.** The finished video/image plus **per-platform
   social captions** (TikTok / Facebook / Instagram / Threads / X), for download
   + copy-paste into the social post.

Before this, the only results surface was the 48h Video/Image Library — a
download-only list that carried **no prompt, no settings, no captions**, and
whose rows are hard-deleted at 48h (captions became orphaned). This hub fixes
both, without touching the proven generation lane.

## Model — heavy file ephemeral, light record durable

| Data | Table | Lifetime |
|------|-------|----------|
| Artifact FILE (mp4/jpg) | `generated_artifact` | **48h** (existing purge, unchanged) |
| Prompt + settings snapshot | `generation_result` (**new**) | **durable** |
| Per-platform captions | `social_copy_package` (existing) | **durable** |

`generation_result` is a lightweight, durable companion keyed by Flow
`media_id`. It is **never** touched by the 48h purge, so the manual-fallback
record and captions never silently vanish when the file expires.

## Capture (additive — `make_video` untouched)

The exact prompt + settings the operator fired are captured at submit inside
`_run_manual_job_via_generate` and passed to the telemetry bridge. On job
`DONE`, `_persist_generation_results()` writes one `generation_result` row per
finished `media_id` (best-effort, wrapped — a DB hiccup never fails the job).
The proven `make_video.start_generate` lane is not modified.

## API (`/api`)

- `GET /api/results?kind=&mode=&limit=` — newest-first list. Runs the lazy 48h
  file purge, merges durable records with any file-only artifacts (older rows /
  direct programmatic lane still appear, so nothing disappears), and attaches a
  one-query caption rollup (`{count, approved}`) per media id.
- `GET /api/results/{media_id}` — detail: the durable prompt/settings snapshot,
  current file availability + `/api/flow/retrieved/{media_id}` download URL, and
  the parsed captions.

## UI — `/results` (Results)

One hub; video/image are a filter (not separate pages). Each card opens a detail
modal with three sections:

1. **Preview & Download** — inline player/image + download while the file lives;
   an "expired but record kept" note after 48h.
2. **Prompt & Settings** — the fired prompt + model/aspect/duration/count/refs,
   each copy-to-clipboard, for manual Flow fallback.
3. **Captions** — reuses `SocialCopyPackagePanel` (no forked editor).

## Scope / follow-ups

- v1 grounds captions with the existing deterministic scaffold + manual editing.
  **PR-2** upgrades caption AI to the grounded `copy_grounding` + provider stack.
- Poster Builder results ride the same hub once its generation handoff lands
  (**PR-3**); on-poster copy stays separate from social captions.
- The two legacy Library nav entries remain; consolidating them into this hub is
  a later cleanup.
