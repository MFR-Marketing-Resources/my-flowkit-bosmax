# ADR-007: Abandon Chrome→Flow DOM Wiring; API-First Rebuild (IMG → I2V → T2V → F2V)

- Status: ACCEPTED (owner decision, 2026-07-02)
- Owner: Faris (final authority)
- Decided after live incidents: manual_5353152e, manual_efad2bb1, manual_8fa93d98
  (root-shell authority leak; infinite mutual recursion / "Maximum call stack
  size exceeded"; frozen renderer killing F12) — all in the DOM-clicking lane.

## Decision

1. The DOM-clicking wiring from the Chrome extension into Google Flow UI is
   **DEAD**. It is not repaired, extended, or "quickly patched" ever again.
2. All four generation modes are rebuilt **API-first** through the unified door
   `POST /api/flow/generate` (mode = IMG | T2V | I2V | F2V), in this order:
   **IMG → I2V → T2V → F2V**.
3. The Chrome extension's ONLY remaining role is **authenticated transport**:
   it holds the user's Google session and executes fetch/API calls the agent
   asks for. It never reads or clicks Flow DOM to drive generation.
4. Google Flow's live UI is Omni/V2. Any code, contract, or SOP that assumes
   Video/Frames tabs, Start/End slot clicking, mode pills, or settings-panel
   clicking describes a UI that NO LONGER EXISTS and is void.

## What is FROZEN (deprecated, do-not-touch, delete after F2V ships)

- `extension/content-flow-dom.js` DOM-driving lanes: mode/submode selection,
  settings-panel clicking, upload-by-click, create-project-by-click,
  findNewProjectControl flows, F2V Start/End slot logic.
- `extension/f2v-flow-queue-runner.js` DOM SOP runner.
- GFV2 DOM lane in `extension/background.js`
  (`GFV2_UPLOAD_SETTINGS_PROMPT_GENERATE` click path, `gfv2EnsureSurface`
  DOM create path).
- The "Frozen And Proven Paths" list in AGENTS.md that froze Video/Frames/9:16
  DOM selection: those paths are proven against a DEAD UI. They are no longer
  "proven"; they are archaeology. Superseded by this ADR.
- Zero engineering hours may be spent fixing bugs inside frozen files except:
  (a) a crash that blocks the API lane, or (b) deleting code.

## What is KEPT (the working core)

- Agent backend, job pipeline (`agent/services/make_video.py` start_generate),
  unified `/api/flow/generate` + `/api/flow/generate-job/{id}`.
- Telemetry, build handshake, recovery endpoints (reload-extension,
  reload-flow-tab), REPORT/REJECTION contracts.
- Prompt compiler (OTAK) and workspace packages.
- Extension WS transport + authenticated fetch. CDP file-feed ONLY as
  API-upload transport if the API upload needs it (not for DOM clicking).
- Dashboard/operator UI (pages may be renamed/reworked freely — see Naming).

## Naming contract (kills the T2V/F2V/I2V/IMG confusion)

- `IMG / T2V / I2V / F2V` are **BOSMAX-internal job modes** at the API
  boundary only. They are user/system markers, NOT Google Flow concepts.
- Google Flow today has no "Frames mode" or "Video tab". Nothing in the
  codebase may use the mode name to imply a Flow UI surface exists for it.
- Dashboard pages may present human labels (e.g. "Gambar", "Video dari Gambar")
  and may be restructured without contract ceremony, as long as they call the
  unified door with the canonical mode string.

## Phase gates (each phase must pass before the next starts)

- Phase IMG: direct API image generation through the unified door.
  Gate: real image bytes retrieved + telemetry row. (Already proven live.)
- Phase I2V: image→video through the unified door.
  Gate: real mp4 retrieved and size-verified. (Proven once: e7871bde 2.0MB.)
- Phase T2V: text→video on the current Flow video protocol
  (flowCreationAgent session + streamChat SSE, captured live 2026-06-29).
  Gate: real mp4 retrieved and size-verified.
- Phase F2V: T2V + frame attachments via API upload.
  Gate: real mp4 retrieved with the start frame respected.
- Every gate: local harness first; ONE live shot; telemetry-backed report;
  no video claim without retrieved bytes (see No-Video Run 1a14fd76 rule).

## Conflict rule

If AGENTS.md, any `.ai/contracts/*` pack, or a phase contract conflicts with
this ADR about the DOM lane or rebuild order, **this ADR wins**. Older ADRs
(ADR-003 CDP upload strategy, ADR-006 harness-before-UAT) remain valid where
they don't assume the DOM lane; report/rejection and git-proof contracts
remain fully in force.
