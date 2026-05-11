# F2V Manual Mode Golden Path Assessment

> **Archive status:** LEGACY STATIC ASSESSMENT  
> **Original assessment commit target:** `86583c2162b4dc399b59246eb17caf3e5553b3eb`  
> **Important:** This document is preserved as a historical audit artifact. Some findings are superseded by later repo changes, including the addition of `/api/flow/execute-flow-job`, telemetry schema repairs, and the F2V SOP contract. Do not treat this archived file as the current implementation source of truth.

## STATUS

`FAIL_CODE_PATH_INCOMPLETE` — The repository’s implementation for the F2V manual video workflow was assessed as incomplete at commit `86583c2162b4dc399b59246eb17caf3e5553b3eb`. The assessment said no verified backend route `/api/flow/execute-flow-job` existed and that the Chrome extension content script did not attach uploaded frames or reliably detect generation.

## VERIFIED IN ORIGINAL ASSESSMENT

- Repo: `farisdatosheikh/my-flowkit-bosmax`
- Commit SHA: `86583c2162b4dc399b59246eb17caf3e5553b3eb`
- Branch: `main`
- Files inspected:
  - `agent/api/flow.py`
  - `agent/api/batch_executor.py`
  - `agent/api/operator.py`
  - `dashboard/src/pages/OperatorPage.tsx`
  - `agent/services/flow_client.py`
  - `extension/background.js`
  - `extension/content-flow-dom.js`

## ORIGINAL NOT VERIFIED ITEMS

- Backend route `/api/flow/execute-flow-job`
- Request log creation before dispatch
- Start/end frame upload in content script
- Generation progress/output detection
- Complete telemetry chain for request validation, log creation, dispatch, and output card detection

## ORIGINAL GOLDEN PATH

The expected manual F2V golden path was:

```txt
USER_SUBMIT_RECEIVED
REQUEST_PAYLOAD_VALIDATED
REQUEST_LOG_CREATED
BACKEND_EXECUTE_FLOW_JOB_ACCEPTED
LOCAL_AGENT_OR_OPERATOR_DISPATCHED
EXTENSION_RUNTIME_HEALTH_CONFIRMED
FLOW_TAB_FOUND
FLOW_EDITOR_READY
FLOW_MODE_VERIFIED
START_FRAME_ATTACHED
START_FRAME_VERIFIED
END_FRAME_HANDLED
JOB_PROMPT_RECEIVED
PROMPT_FIELD_FOUND
PROMPT_INSERT_METHOD_RECORDED
PROMPT_VISIBLE
PROMPT_EDITABLE_AFTER_INSERT
GENERATE_BUTTON_FOUND
GENERATE_BUTTON_ENABLED
GENERATE_CLICKED
GENERATE_CLICK_ACCEPTED
GENERATION_STARTED
OUTPUT_CARD_FOUND_OR_NOT_REACHED
```

## REQUIRED DOM / STATE CHECKS

Minimum checks listed by the assessment:

1. Flow URL / tab state
   - Active tab must match Google Flow project/editor URL.
   - Content script must be injected and responsive.
2. Editor loaded
   - Composer/editor container visible.
   - No login/permission/blocking modal.
3. Mode state
   - Video mode active.
   - Frames submode selected.
4. Start frame upload
   - Start slot/file input found.
   - File attached.
   - Thumbnail/attach indicator appears.
5. Optional end frame upload
   - Attach if provided; otherwise explicit skip telemetry.
6. Prompt insertion
   - Composer found and editable.
   - Prompt inserted through Flow-compatible input events.
   - Visible prompt matches source.
7. Generate/Create button
   - Correct button near composer found and enabled.
8. Click acceptance
   - DOM state changes after click.
9. Generation/output detection
   - Progress/spinner/job card/output tile detected.

## ORIGINAL FAILURE MATRIX SUMMARY

| Area | Failure signature | Classification | First file |
|---|---|---:|---|
| Extension messaging | runtime lastError / no EXECUTE response | Retryable | `extension/background.js` |
| Content DOM mismatch | composer/button not found | Hard blocker | `extension/content-flow-dom.js` |
| Flow page state mismatch | root page instead of editor | Retryable | `extension/background.js` |
| Mode mismatch | Frames not active | Hard blocker | `extension/content-flow-dom.js` |
| Asset upload failure | no thumbnail appears | Hard blocker | `extension/content-flow-dom.js` |
| Prompt insertion failure | prompt not visible/accepted | Hard blocker | `extension/content-flow-dom.js` |
| Generate action failure | disabled/wrong button/no UI change | Retryable | `extension/content-flow-dom.js` |
| Generation started but no callback | progress/output not tracked | Telemetry warning | `extension/content-flow-dom.js` |

## ORIGINAL MOST LIKELY ROOT CAUSES

1. Missing `/api/flow/execute-flow-job` route.
2. Content script does not attach start/end frames.
3. No detection of generation start or output.
4. UI does not call the extension for manual mode.

## ORIGINAL 60-MINUTE DEBUG WAR PLAN

```txt
0–10 min: repo and SHA lock
10–20 min: UI → backend request proof
20–35 min: backend → extension bridge proof
35–50 min: content script → Flow DOM proof
50–60 min: generation start / output proof
```

## ORIGINAL STRICT SUCCESS DEFINITION

A manual F2V run passes only if all are true:

```txt
ENTRYPOINT_USED = BOSMAX_UI_MANUAL_SUBMIT
REQUEST_ACCEPTED = PASS
REQUEST_LOG_ID present
MODE = TRUE_F2V / Video → Frames
FLOW_TAB_FOUND = PASS
FLOW_EDITOR_READY = PASS
FLOW_MODE_VERIFIED = PASS
START_FRAME_ATTACHED = PASS
START_FRAME_VERIFIED = PASS
END_FRAME_HANDLED = PASS or SKIPPED_NOT_PROVIDED
MANUAL_PROMPT_RECEIVED = PASS
PROMPT_FIELD_FOUND = PASS
PROMPT_VISIBLE = PASS
PROMPT_EDITABLE_AFTER_INSERT = PASS
GENERATE_BUTTON_FOUND = PASS
GENERATE_BUTTON_ENABLED = PASS
GENERATE_CLICKED = PASS
GENERATE_CLICK_ACCEPTED = PASS
GENERATION_STARTED = PASS
OUTPUT_CARD_FOUND = PASS or NOT_REACHED_GENERATION_RUNNING
MV3_MESSAGE_PORT_ERROR = PASS_NONE
STAGE_ORDER_PROOF = PASS
```

## ORIGINAL STOP-DOING LIST

- Stop changing selectors once readiness smoke is green unless live run proves failure.
- Stop using curl-only endpoint checks as success proof.
- Stop relying on direct DOM injection as production proof.
- Stop adding output capture logic before generation start is verified.
- Stop debugging prompt automation before file upload and generation start are proven.
- Stop mass batch testing.
- Stop accepting screenshots without request log or stage telemetry.
- Stop fixing unrelated product catalog or physics systems.
- Stop broad architecture refactors.
- Stop adding new modes before F2V manual path passes once.

## CURRENT SOURCE OF TRUTH

Use these current repo docs instead of treating this legacy assessment as active truth:

```txt
docs/google-flow/GOOGLE_FLOW_F2V_ANTIGRAVITY_SOP_MANUAL_v1.md
```

Current F2V mode lock:

```txt
New Project → Video → Frames → 9:16 → 1x → Veo 3.1 - Lite
```

Forbidden for F2V:

```txt
Image mode
Nano Banana / Nano Banana 2
Ingredients mode
Existing stale project URL as primary path
```
