# Codex Audit Handover — adversarial review of the API-first /generate pipeline

**To: Codex (acting as senior system architect + senior software engineer).**
**From: Claude Code (same level).** This is a peer audit, not a sign-off. **Counter my report.**
I will counter yours. We converge on findings before Faris live-tests the 4 modes
(T2V/F2V/I2V/IMG) in the Chrome extension. No cheerleading — find what breaks.

---

## 0. Rules of engagement
- Be adversarial and specific. Every claim needs a file:line or a repro. "Looks fine" is not a finding.
- Rank each finding: **BLOCKER / HIGH / MEDIUM / LOW** + a concrete fix proposal.
- Respect the locked principles: **don't fix what's not broken · don't reinvent the wheel ·
  surgical patches only (no full rewrite without architecture-change approval) · verify-before-claim
  (no "done" without the saved artifact) · one entry point (`/generate`) · ask before credits.**
- Do **not** resurrect retired DOM automation (`f2v-flow-queue-runner.js`, the Video/Frames tab SOP
  in `content-flow-dom.js`, `execute-flow-job` as a generation path).

## 1. Read first
1. `docs/UNIFIED_GENERATE_PIPELINE.md` (the architecture + the one door)
2. `AGENTS.md` + `.ai/status/CURRENT_STATE.md` (the 2026-06-29 pivot)
3. Code: `agent/services/make_video.py`, `agent/services/agent_video.py`,
   `agent/api/flow.py` (`/generate`, `/generate-job`), `agent/services/flow_client.py`,
   `extension/background.js` (`handleHarvestVideoUrls`, token inject), `extension/injected.js`,
   `dashboard/src/pages/OperatorPage.tsx` (`handleExecute`/`pollJob`).
4. Branch state: PR **#146** (`feat/gfv2-runner-upload-settings-prompt` → `main`) is **CONFLICTING**.

## 2. What is claimed PROVEN (verify it, don't trust it)
- End-to-end **I2V**: real 2.0 MB H.264 mp4 (`e7871bde`) generated from a user-uploaded image in
  the user's OPEN project, saved to `output/retrieved/`. Verify the claim holds for the *dashboard*
  path, not just the hand-driven API call.

## 3. My own self-identified blindspots — VERIFY + hunt beyond these
- **[BLOCKER candidate] Dashboard project/tab mismatch.** `handleExecute` calls `/generate`
  **without `project_id`** → `_run_generate` mints a NEW project → but the user's Flow tab is NOT on
  it → `harvest_video_urls` scans the wrong tab → **video retrieval will fail**. The proof run only
  worked because generation happened in the user's *already-open* project. Proposed fix: for video
  modes with no `project_id`, harvest the current tab's `projectId` and generate there (proven
  pattern); or navigate the tab to the minted project (note: `open_target_flow_project` drifted to
  the Flow home page before). **Which is robust? Pressure-test.**
- **[HIGH] Retrieval is DOM-harvest dependent + brittle.** Relies on the finished video appearing as
  a `<video>`/`<img>` with `getMediaUrlRedirect?name={id}` in the open tab. Thumbnail-vs-player
  timing, tab focus, and drift all break it. `_STALE_VIDEO_IDS = {b267d480}` is a hardcoded hack — a
  robust design snapshots existing media_ids BEFORE generation and accepts only NEW ones. Is there a
  project-media LIST API we missed (`refresh_project_urls` is a no-op)?
- **[HIGH] `agent_video.decide()` strictness.** It rejects any proposal with `num_images` set and
  requires `num_videos==1, cost<=10`. Does a legitimate Veo-Lite proposal ever include a first-frame
  `num_images>0` (→ wrongly rejected → max_turns fail)? Does `cost<=10` actually guarantee Veo 3.1
  Lite vs another 10-credit model? Verify against real agent SSE.
- **[HIGH] Only I2V is live-proven.** T2V (no ref), F2V, and IMG via the unified door are untested.
  IMG via the dashboard still uses the OLD `generate-image-oneshot` (opens a browser tab, does NOT
  save to the system) — inconsistent with `/generate` IMG (saves to disk). Two IMG paths; reconcile.
- **[MEDIUM] No tests** for `parse_agent_sse` / `decide` / the retrieval loop. Zero CI coverage on
  the new brain + pipeline.
- **[MEDIUM] Redundant scaffolding** in `make_video.py`: `start`/`start_on_existing`/`start_negotiate`
  predate the unified `start_generate`. `/generate` is canonical; `make-video*` / `negotiate-job`
  endpoints are legacy. Consolidate or mark (left in place per the surgical rule — your call).
- **[MEDIUM] `_JOBS` is in-memory** (lost on restart, no GC) and **multiple concurrent jobs share one
  Flow tab** (harvest contention). T2V+IMG fired together would collide.
- **[MEDIUM] Secret hygiene.** The webRequest capture hook posts request bodies (which carry tokens)
  to `/api/local-agent/capture-video-payload`. Confirm no token/credential leaks into logs/telemetry.
- **[LOW] Assumptions:** reCAPTCHA action `CHAT_GENERATION`; the agent inherits the model from the
  user's Flow setting (if it's not Lite, cost/behaviour shift); credit prices.

## 4. Deliverable from Codex
A counter-report: confirmed/refuted findings (with file:line + repro), NEW blindspots I missed, and a
ranked fix list. I will counter each. We iterate until we agree, THEN Faris tests the 4 modes.

## 5. Also resolve
PR #146 conflicts (14 files). For files overlapping the pipeline
(`extension/background.js`, `manifest.json`, `agent/api/local_agent.py`, `F2VModule.tsx`,
`I2VModule.tsx`) keep BOTH sides; the rest (fastmoss / product-registration / tests) keep main's.
After resolution: `npm run build` + `python -m py_compile` + `node --check` must pass, and the
`/generate` door must stay intact.
