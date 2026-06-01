# Google Flow — Frames Video Sample: Step-by-Step Manual (v1)

**Document type:** Verified human UI walkthrough + telemetry mapping (Antigravity guidance)
**Source of truth:** `Project chrome extension-frames-canva.pdf` (7-page click-path, user-verified)
**Mode covered:** F2V / Frames-to-Video (Start + End frame upload)
**Companion contract:** `docs/google-flow/GOOGLE_FLOW_F2V_ANTIGRAVITY_SOP_MANUAL_v1.md`
**Runner under automation:** `extension/f2v-flow-queue-runner.js`

> Purpose: give Antigravity (and any human operator) the exact, ordered click-path
> for producing **one** sample Frames video in Google Flow, and map each visible UI
> action to the telemetry stage the runner is contracted to emit. This is the
> "happy path". It does **not** authorise debugging loops, selector experiments, or
> Generate clicks beyond a single authorised sample.

---

## 0. Locked configuration (must never drift)

| Setting | Required value |
|---|---|
| Type | **Video** |
| Sub-mode | **Frames** |
| Aspect ratio | **9:16** |
| Quantity | **1x** |
| Model | **Veo 3.1 - Lite** |
| Frames | **2 photos** — Start frame **and** End frame |

Forbidden in this flow: Image mode, Nano Banana, Ingredients mode, I2V subject/scene/style,
reusing a stale project URL, bulk queueing, any model other than Veo 3.1 Lite.

---

## 1. The click-path (mirrors the PDF, page-for-page)

### Step 1 — New project (PDF p.1)
- Click **`+ New project`** on the Flow home/dashboard.
- **Telemetry:** `F2V_SOP_NEW_PROJECT_READY`
- **Pass when:** the composer/project workspace appears.

### Step 2 — Workspace ready (PDF p.2)
- Wait until the page is **open and ready for setting up** (composer visible, settings pill reachable).
- **Telemetry:** `F2V_SOP_SETTINGS_EXPLORER_STARTED` → `F2V_SOP_SETTINGS_LAUNCHER_FOUND` → `F2V_SOP_SETTINGS_PANEL_OPENED`
- **Pass when:** the settings panel is open and the type/config controls are visible.

### Step 3 — Configure the five settings (PDF p.3 checklist)
Select **in this exact order**:
1. **Video** → `F2V_SOP_VIDEO_CLICKED` → `F2V_SOP_VIDEO_CONFIRMED`
2. **Frames** → `F2V_SOP_FRAMES_CLICKED` → `F2V_SOP_FRAMES_CONFIRMED`
3. **9:16** → `F2V_SOP_RATIO_9_16_CLICKED` → `F2V_SOP_RATIO_9_16_CONFIRMED`
4. **1x** → `F2V_SOP_COUNT_1X_CLICKED` → `F2V_SOP_COUNT_1X_CONFIRMED`
5. **Veo 3.1 - Lite** → `F2V_SOP_MODEL_VEO_CLICKED` → `F2V_SOP_MODEL_VEO_CONFIRMED`

- Each option is scanned first: `F2V_SOP_SETTING_CANDIDATES_SCANNED`.
- After all five verify: **`F2V_SOP_SETTINGS_CONFIGURED`**.
- **Pass when:** every selected chip/dropdown matches the locked config in §0.
- **Aliases the runner accepts** (so the operator knows what "correct" looks like):
  - 9:16 → `crop_9_16`, `Portrait 9:16`
  - 1x → `1×`, `1 variation`
  - Veo 3.1 - Lite → `Veo 3.1 Lite`, `Veo 3.1 — Lite`

### Step 3b — Close the settings panel (NOT in the PDF, but mandatory)
> This step does not appear in the screenshots because a human closes the panel
> reflexively. The automation must do it **explicitly**, and this is the exact spot
> the runner most recently broke. Document it so it is never skipped again.

- Google Flow sets `contenteditable="false"` on the Slate prompt editor **while the
  settings panel is open**. If the panel is not closed, prompt insertion in Step 6
  silently fails.
- Close the panel by re-clicking the bottom composer config pill (the toggle that
  shows the current `crop_9_16` / `video + 1x` / `frames + 1x` signature), or by
  collapsing the `aria-expanded="true"` toggle, or as a last resort Escape on the
  focused element.
- **Telemetry:** `F2V_SOP_SETTINGS_PANEL_CLOSE_ATTEMPT` (records which close action fired
  and the editor `contenteditable` state afterwards).
- **Pass when:** the Slate editor reports `contenteditable="true"` (panel closed).

### Step 4 — Upload Start and End frames (PDF p.4)
- Click **`Start`**.
- Click **`Upload media`**.
- Upload **2 photos**: the **Start** frame and the **End** frame.
- **Telemetry:** `F2V_SOP_START_CLICKED` → `F2V_SOP_UPLOAD_CLICKED` → `F2V_SOP_UPLOAD_WAIT_DONE`
- **Pass when:** both frame slots show a media preview.

### Step 5 — Confirm upload, open prompt (PDF p.4–5)
- Confirm **`photo uploaded`** (preview present in the slot).
- Click **`Add Prompt`**.
- **Pass when:** the prompt field is editable (`contenteditable="true"` — depends on Step 3b).

### Step 6 — Enter prompt and submit (PDF p.6)
- Focus **`What do you want to create`**.
- Insert the **video prompt** text (exact-match assertion).
- Click the **arrow / submit** symbol.
- **Telemetry:** `F2V_SOP_PROMPT_INSERTED` → `F2V_SOP_GENERATE_SUBMITTED`
- **Pass when:** prompt field contains the exact prompt **and** the job enters the
  generating/submitted state with no validation error.
- ⚠️ The Generate/submit click requires **explicit authorization** per the contract.
  Do not auto-fire it during a dry harness run.

### Step 7 — Export (PDF p.7)
- Click the **`+ Button`** (project actions).
- Click **`Download Project`**.
- **Pass when:** a browser download starts or an export confirmation appears.

---

## 2. End-to-end telemetry stage order (canonical)

The runner's frozen contract is `F2V_SOP_STAGE_CONTRACT` in
`extension/f2v-flow-queue-runner.js`. A clean sample run must emit, in order:

```
F2V_SOP_NEW_PROJECT_READY
F2V_SOP_SETTINGS_EXPLORER_STARTED
F2V_SOP_SETTINGS_LAUNCHER_FOUND
F2V_SOP_SETTINGS_PANEL_OPENED
F2V_SOP_SETTING_CANDIDATES_SCANNED
F2V_SOP_VIDEO_CLICKED        → F2V_SOP_VIDEO_CONFIRMED
F2V_SOP_FRAMES_CLICKED       → F2V_SOP_FRAMES_CONFIRMED
F2V_SOP_RATIO_9_16_CLICKED   → F2V_SOP_RATIO_9_16_CONFIRMED
F2V_SOP_COUNT_1X_CLICKED     → F2V_SOP_COUNT_1X_CONFIRMED
F2V_SOP_MODEL_VEO_CLICKED    → F2V_SOP_MODEL_VEO_CONFIRMED
F2V_SOP_SETTINGS_CONFIGURED
F2V_SOP_SETTINGS_PANEL_CLOSE_ATTEMPT
F2V_SOP_START_CLICKED
F2V_SOP_UPLOAD_CLICKED
F2V_SOP_UPLOAD_WAIT_DONE
F2V_SOP_PROMPT_INSERTED
F2V_SOP_GENERATE_SUBMITTED   (authorised sample only)
```

A report that skips a stage, or shows `REQUEST_ID=N/A` / `build=legacy`, is **rejected**
per `.ai/contracts/REPORT_REJECTION_RULES.md`.

---

## 3. Failure-code quick reference

| Where it fails | Error code |
|---|---|
| Settings panel never opened | `ERR_F2V_SETTINGS_PANEL_NOT_OPEN` |
| A setting option not found | `ERR_F2V_OPTION_<NAME>_NOT_FOUND` |
| Upload Start/End frames missing | `ERR_F2V_UPLOAD_MEDIA_NOT_FOUND` |
| Settings not done before upload | `ERR_F2V_SETTINGS_NOT_CONFIGURED_BEFORE_UPLOAD` |
| Prompt field not editable / not found | `ERR_F2V_PROMPT_FIELD_NOT_FOUND` |
| Generate preconditions not met | `ERR_F2V_GENERATE_PRECONDITION_FAILED` |
| Runner threw | `ERR_F2V_SOP_RUNNER_THREW` |

---

## 4. Operator guardrails

- This manual is the **happy path only**. If any stage fails, **stop** and report the
  `FIRST_FAIL_STAGE` + `FULL_FAIL_MESSAGE`. Do **not** enter a debug/retry loop.
- Antigravity is **one-shot live UAT only**. It does not patch, edit, or repair the
  extension. Repairs are escalated to Codex (see the recovery prompt in
  `.ai/prompts/`).
- Live Google Flow may not be used to compensate for a missing local harness pass.
