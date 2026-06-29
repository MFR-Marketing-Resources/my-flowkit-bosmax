# Patch Plan A–H — canonical shake-hand spec (Claude ⇄ Codex, 2026-06-29)

Audit converged. Surgical patches only · one entry point (`/generate`) · no DOM revival ·
verify-before-claim (no "done" without the saved file) · ask before credits.
**Order:** `A + G + H` → `B` → `E` → `D` → `F` throughout → `C` only after Faris's nod.

Every patch validates: `python -m py_compile` (touched) · `node --check` (touched JS) ·
`npm --prefix dashboard run build` · `/generate` stays intact. Live credit-burning test = Faris, post-patch.

---

## A. Bound editor session  (BLOCKER — does #1+#2+#3)
- Bind `{project_id, flow_tab_id, flow_project_url}` from the **open Flow editor** at job start; thread all three through the unified job.
- Target that **exact tab** for harvest + captcha + token (no `tabs[0]`).
- **Fail-closed:** reject *before* approve/credits if no open editor project. Do NOT mint a hidden backend-only project for the dashboard video lane.
- Harvest invariant: fail if `diag.projectId !== bound project_id` OR tab is not the editor URL.
- Files: `make_video.py` (`_run_generate`), `flow_client.py`/`background.js` (tab-targeted harvest/captcha/token), `flow.py` (`/generate` binds).
- **Accept:** dashboard T2V/I2V/F2V on the user's open project → harvest hits the bound tab; closing/switching the tab → job rejects early (no late timeout, no credits).

## G. No silent fallback to unbound tab
- Remove every `tabs[0]` fallback in unified-job paths (harvest, captcha, token). Incomplete binding → reject pre-approve.
- **Accept:** two Flow tabs open → no wrong-tab action; incomplete binding → early reject.

## H. Single-flight video lane + `_JOBS` GC
- ≤1 in-flight video job per bound Flow tab; **reject** (fail-closed, not silent queue) a new video job while one is active. IMG exempt.
- `_JOBS` TTL/GC; safe on restart.
- **Accept:** two concurrent video jobs → 2nd rejected; completed jobs GC'd.

## B. Real SSE fixture + model gate + tests
- Capture ONE real SSE into a committed fixture — the single authority for: `parse_agent_sse()`, `decide()`, the `veo_3_1_r2v_lite` / `model_display_name` gate, whether `num_images` is valid, and pre- vs post-approve model location.
- `decide()`: gate on the model signal if it appears **pre-approve**; else preflight the active Flow model before approving. Keep `num_videos>=1`.
- Unit tests for `parse_agent_sse` + `decide` against the fixture.
- **Accept:** tests pass; `decide()` approves only a verified 1-video Veo-Lite proposal.

## E. Secret redaction + debug gate  (security — ships in the same set)
- Redact tokens (`recaptchaContext.token`, etc.) before storing in `capture-video-payload`; gate the debug endpoint behind an explicit switch (off by default).
- **Accept:** stored payloads carry no token; endpoint disabled by default.

## D. IMG one-door consistency  (after A/B/E; independent of harvest)
- Route dashboard IMG through `/generate`, OR make `generate-image-oneshot` save to disk + return `local_path`.
- **Accept:** IMG click → a saved image file + `local_path` (verify-before-claim).

## F. Doc/proof correction  (throughout)
- Build command is `npm --prefix dashboard run build` (root has no `build` script). No "dashboard-proven" claim until a live button path produces a saved file.

## C. Telemetry — HOLD pending Faris's nod
- Until the nod: only remove the stale "Waiting for telemetry" toast (`OperatorPage.tsx:386`) and mark the lane **pollJob-driven**. No architecture retrofit.
- Then either **(a)** bridge the unified job into the telemetry tables (`job_id`=`request_id`, stage events) for `RUNTIME_TELEMETRY_LOCKDOWN` compliance, or **(b)** formalize "job-status = the telemetry surface" for the API-first lane and update the contract.

---

## Roles (this phase)
- **Implementer** does the surgical patches in the locked order; **Reviewer** counter-checks each
  (no regression to the proven engine, no DOM revival, surgical scope, verify-before-claim) before accept.
- Phase-2 note (not now): allowing the pipeline to open+bind a fresh editor (vs requiring one open) is deferred; fail-closed-requires-open is the current rule.
