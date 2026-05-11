# Google Flow Frames-to-Video (F2V) SOP

**Document type:** Professional SOP + AI Coding-Agent Execution Contract  
**Mode covered:** F2V / Frames-to-Video using Start/End frame UI  
**Verification status:** Partially verified from uploaded screenshot/chart only; exact DOM selectors are NOT VERIFIED.

## Purpose

This SOP is the source of truth for Google Flow F2V automation. It prevents the extension or coding agent from selecting the wrong Google Flow mode.

F2V must use:

```txt
New Project
→ Video
→ Frames
→ 9:16
→ 1x
→ Veo 3.1 - Lite
→ Start frame upload
→ Prompt injection
→ Arrow submit
```

Forbidden for this SOP:

```txt
Image mode
Nano Banana / Nano Banana 2
Ingredients mode
I2V subject/scene/style workflow
Existing stale project URL as primary path
Bulk queueing
Catalog/product intelligence
```

---

## 1. Required Operating Workflow

| Phase | Required state | Primary action | Pass condition |
|---|---|---|---|
| Project Init | Flow home/dashboard visible | Click New Project | Composer/project workspace appears |
| Mode Configuration | Composer settings panel available | Select Video → Frames → 9:16 → 1x → Veo 3.1 Lite | All selected states are verified |
| Input Injection | Frames composer visible | Upload Start frame, then inject prompt | Start slot has preview and prompt field contains exact text |
| Submission | Submit arrow enabled | Click arrow submit | Job enters generating/submitted state with no validation error |
| Export | Generated project available | 3-dot menu → Download Project | Browser download starts or export confirmation appears |

---

## 2. Mandatory State Machine

| State ID | Entry condition | Action | Exit condition | Failure code |
|---|---|---|---|---|
| S0_READY | Flow page loaded and extension active | Wait for New Project button | New Project clickable | ERR_FLOW_HOME_NOT_READY |
| S1_PROJECT_OPEN | Composer/workspace visible | Open settings/type selector | Type controls visible | ERR_COMPOSER_NOT_OPEN |
| S2_MODE_SET | Settings popover visible | Select Video + Frames | Frames UI with Start/End slots visible | ERR_MODE_SELECTION_FAILED |
| S3_CONFIG_SET | Frames mode active | Select 9:16, 1x, Veo 3.1 Lite | Selected chips/dropdown match config | ERR_CONFIG_MISMATCH |
| S4_IMAGE_READY | Start slot visible | Upload image file | Start slot contains media preview | ERR_IMAGE_UPLOAD_FAILED |
| S5_PROMPT_READY | Prompt field editable | Set prompt value and dispatch input/change events | Prompt exact-match assertion passes | ERR_PROMPT_INJECTION_FAILED |
| S6_SUBMITTED | Submit arrow enabled | Click submit | Generating/submitted state detected | ERR_SUBMIT_FAILED |
| S7_DOWNLOADABLE | Project generated or project menu available | Open 3-dot menu | Download Project item visible | ERR_MENU_NOT_FOUND |
| S8_EXPORTED | Download item visible | Click Download Project | Download starts/completes | ERR_DOWNLOAD_FAILED |

---

## 3. Selector and DOM Strategy

Use DOM-accessible selectors first: role, aria-label, visible text, placeholder, and stable attributes. Do not use brittle pixel coordinates as primary selectors. Pixel or image matching may be fallback only with explicit logging.

| Target | Preferred locator | Fallback locator | Required assertion |
|---|---|---|---|
| New Project | Button text / aria-label contains “New project” | Visible text match | Composer opens |
| Video Toggle | Role tab/button text “Video” | Sibling of Image toggle | Video selected |
| Frames Mode | Role tab/button text “Frames” | Text near Ingredients tab | Frames selected |
| 9:16 Ratio | Button/chip text “9:16” | Aspect-ratio group first option | 9:16 selected, 16:9 not selected |
| 1x Quantity | Button/chip text “1x” | Quantity group first option | Generation count equals 1 |
| Veo 3.1 Lite | Dropdown selected text | Menu item exact text | Selected package text visible |
| Start Upload | File input linked to Start slot | Click Start slot then attach file to active input | Start slot has preview/filled state |
| Prompt Field | Textarea/input placeholder “What do you want to create?” | Focused editable near frame slots | Field value equals prompt |
| Submit Arrow | Enabled submit button near prompt box | Arrow icon in composer footer | Generation starts |
| 3-dot Menu | Button aria-label/menu trigger near project top bar | Visible kebab icon trigger | Menu contains Download Project |
| Download Project | Menu item exact text | Download icon/menu item | Download event triggered |

---

## 4. Hard Mode Lock for F2V

Before upload or prompt insertion, automation must prove:

```txt
FLOW_TYPE_VIDEO_SELECTED = PASS
FLOW_SUBMODE_FRAMES_SELECTED = PASS
FLOW_ASPECT_9_16_SELECTED = PASS
FLOW_COUNT_1X_SELECTED = PASS
FLOW_MODEL_VEO_3_1_LITE_SELECTED = PASS
START_SLOT_VISIBLE = PASS
PROMPT_FIELD_VISIBLE = PASS
```

Abort immediately if:

```txt
ERR_WRONG_MODE_IMAGE_SELECTED
ERR_WRONG_MODEL_FOR_F2V
ERR_FRAMES_MODE_NOT_ACTIVE
ERR_START_SLOT_NOT_VISIBLE
ERR_PROMPT_FIELD_NOT_FOUND
```

---

## 5. QA Checklist

| Check ID | Test | Expected proof | Pass / Fail rule |
|---|---|---|---|
| QA-01 | Load unpacked extension and open Google Flow | Extension service worker active; content script injected | FAIL if no content heartbeat |
| QA-02 | Run F2V automation with one local image + one prompt | Step log reaches S8_EXPORTED | FAIL if any state skipped |
| QA-03 | Refresh already-open Flow tab after extension reload | Reinjection succeeds | FAIL if manual reopen required |
| QA-04 | Validate selector resilience | Primary + fallback locator per target | FAIL if only pixel coordinates used |
| QA-05 | Validate prompt integrity | Inserted prompt equals source string byte-for-byte | FAIL if prompt mutates/truncates |
| QA-06 | Validate upload | Start slot visibly filled or DOM preview detected | FAIL if file selection not reflected |
| QA-07 | Validate submit | Generation or queue state detected | FAIL if click fires with no UI transition |
| QA-08 | Validate download | Chrome downloads API or browser event confirms start/completion | FAIL if only menu click is logged |

---

## 6. Error Handling Rules

Every step must log:

```txt
state_id
locator_used
action_attempted
before/after DOM proof or screenshot hash
timestamp
```

Rules:

- If locator fails, attempt exactly one fallback locator family before aborting.
- If Google Flow UI changes, abort with `ERR_SELECTOR_DRIFT` and attach DOM snapshot + screenshot.
- If upload fails, do not submit. Abort with `ERR_IMAGE_UPLOAD_FAILED`.
- If prompt injection fails, do not submit. Abort with `ERR_PROMPT_INJECTION_FAILED`.
- If generation is slow, wait by explicit UI state or network/download event, not fixed sleep only.

---

## 7. Antigravity / Codex Implementation Contract

Objective:

```txt
Build or repair Chrome Extension automation for Google Flow Frames-to-Video mode:
New Project → Video → Frames → 9:16 → 1x → Veo 3.1 - Lite → upload Start frame → inject prompt → submit → Download Project.
```

Scope in:

```txt
F2V / Frames only.
```

Scope out:

```txt
Image mode
Nano Banana
Ingredients mode
I2V subject/scene/style
Bulk queueing
Prompt automation
Catalog/product intelligence
Credit purchasing
Undocumented DOM shortcuts without proof
```

Remote proof required:

```txt
exact files changed
git diff summary
test command
test output
screenshots/log snippets proving each state
commit SHA
pass/fail status
```

If selectors are not verified against live Google Flow DOM, report:

```txt
NOT VERIFIED — LIVE DOM SELECTORS NOT CONFIRMED
```

---

## 8. Final Acceptance Gate

| Gate | Required evidence | Status rule |
|---|---|---|
| Functional | Automation completes all SOP actions in order | PASS only if S8_EXPORTED reached |
| Selector Integrity | Every selector has primary + fallback + assertion | FAIL on coordinate-only automation |
| Upload Integrity | Start image selected and visible/DOM-confirmed | FAIL if upload cannot be proven |
| Prompt Integrity | Prompt field exact-match verified after injection | FAIL if value differs |
| Download Integrity | Download event confirmed, not merely clicked | FAIL if no file/download event |
| Regression | Existing extension functions still pass tests | FAIL if unrelated working mode breaks |
