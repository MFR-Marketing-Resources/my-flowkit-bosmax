# Google Flow - Authenticated Editor Scouting Report

## STATUS
- **PARTIAL**  
  *Note: The authenticated workspace editor canvas, navigation sidebar, model selectors, prompt box, and hidden file inputs were successfully scouted live and documented. Live image upload and generation submissions were not executed to avoid billing credit consumption and adhere to safety restrictions.*

---

## NOTEBOOKLM ACCESS
- **FALLBACK_ONLY**  
  *Reason: Direct live NotebookLM profile access was unavailable in our terminal context. We used the local repository Q&A file: [.ai/research/notebooklm-qna-chrome-extension.md](file:///c:/Users/USER/Desktop/_ref_flowkit/.ai/research/notebooklm-qna-chrome-extension.md) as context.*

---

## AUTHENTICATED EDITOR ACCESS
- **VERIFIED**  
  *Successfully navigated to the active Google Flow project workspace at `https://labs.google/fx/tools/flow/project/6d37e3eb-a8f5-4ea4-ba01-d25514213d4c` and extracted the DOM tree.*

---

## BRANCH
- `codex/google-flow-authenticated-scout`

---

## VERIFIED_LIVE
- **Prompt Composer Box:** Confirmed as a contenteditable `DIV` element with a dynamic class wrapper (e.g. `sc-a8ba1f43-0 djaQmW sc-439ac1d3-6 gmMGa`).
- **Model Selector Trigger:** Confirmed as a Radix-styled button element. During the live session, it displayed the text `"🍌 Nano Banana 2crop_16_9x2"` and had the ID `radix-:r3b:`.
- **Generate / Submission Button:** Confirmed as a button containing the text `"arrow_forwardCreate"`. The button is disabled (`disabled: true`) by default when the prompt box is empty.
- **Flow Agent Toggle:** Confirmed as a button containing the text `"Agent"`, situated adjacent to the Create button.
- **Upload / Reference Slots:** Confirmed the presence of a hidden file input element: `input[type="file"]` (className `sc-dcc7b7da-0 fhJvUC`) located under `/html/body/div/div/input`.
- **Add Media Button:** Confirmed as a button with text `"addAdd Media"` and Radix ID `radix-:r2r:`.
- **Workspace Navigation Sidebar:** Confirmed left-hand sidebar buttons:
  - `"dashboardAll Media"`
  - `"accessibility_newCharacters"`
  - `"movieView scenes"`
  - `"apps_spark_2Tools"`
  - `"deleteView Trash"`
  - `"left_panel_closeCollapse"`

---

## INFERRED_FROM_CODE
- **Settings Chips:** Preset tabs for Aspect Ratio (`9:16`) and Count (`1x`) are rendered dynamically depending on the selected model/mode.
- **CDP File Interception:** Suppression of OS file pickers requires registering a background listener for `Page.fileChooserOpened` and injecting paths via `DOM.setFileInputFiles` relative to the hidden `input[type="file"]`.
- **React Synthetic Actions:** Text injection into the contenteditable `DIV` requires dispatching custom synthetic Input and Change events so the React state updates properly.

---

## NOT VERIFIED
- DOM structure transitions when a preview thumbnail is populated.
- Operations progress tracker updates during live generation cycles.
- Paywall billing modal warnings.

---

## SCREEN MAP
- **Dashboard Hub:** Initial view containing historical projects grid and the primary `+ New Project` button.
- **Editor Workspace Canvas:** Split panel containing the left navigation sidebar (All Media, Characters, Scenes, Tools, Trash) and the bottom composer dock (Prompt DIV, Model trigger, Agent toggle, Create CTA).

---

## SELECTOR INVENTORY
- **Summary:** Mapped prompt text fields, model dropdown triggers, file input receivers, and navigation selectors.
- **Full File Path:** [selector-inventory-authenticated.md](file:///c:/Users/USER/Desktop/_ref_flowkit/docs/google-flow/2026-05-authenticated-editor-scout/selector-inventory-authenticated.md)

---

## NETWORK PAYLOAD MAP
- **Summary:** Outlined `clientContext` schemas, tRPC project endpoints, and REST API generation paths.
- **Full File Path:** [network-payload-map-authenticated.md](file:///c:/Users/USER/Desktop/_ref_flowkit/docs/google-flow/2026-05-authenticated-editor-scout/network-payload-map-authenticated.md)

---

## FAILURE MODES
1. **Dynamic Class Drift:** Selector configurations using styled-component hashed prefixes will break on Google Flow updates. Centralized text matching locator keys (e.g. `:has-text("Create")`) must be used.
2. **OS Dialog Freeze:** Triggering upload clicks directly in sandboxes without active CDP interception blocks the automation pipeline.
3. **Stale Script Context:** Orphaned content scripts running on tab refresh are resolved by compiling Git SHAs into background connections.

---

## FLOWCHARTS
- **Operator Flowchart:** [operator-flowchart-authenticated.md](file:///c:/Users/USER/Desktop/_ref_flowkit/docs/google-flow/2026-05-authenticated-editor-scout/operator-flowchart-authenticated.md)
- **Extension Flowchart:** [extension-flowchart-authenticated.md](file:///c:/Users/USER/Desktop/_ref_flowkit/docs/google-flow/2026-05-authenticated-editor-scout/extension-flowchart-authenticated.md)

---

## SCREENSHOT INDEX
All screenshots are saved in `docs/google-flow/2026-05-authenticated-editor-scout/screenshots/`:
1. `screenshot_1_workspace_landing.png`: Editor workspace load screen.
2. `screenshot_2_editor_default.png`: Editor default state with the bottom composer panel.
3. `screenshot_4_model_settings.png`: Open dropdown selection popup menu.
4. `screenshot_state_step_1.png` - `screenshot_state_step_8.png`: Sequential UI state updates.

---

## GITHUB DELIVERY
- **Branch:** `codex/google-flow-authenticated-scout`
- **Commit SHA:** [To be completed post-commit]
- **Push Target:** `https://github.com/farisdatosheikh/my-flowkit-bosmax`
- **Push Result:** [To be completed post-push]
- **Uploaded Paths:** `docs/google-flow/2026-05-authenticated-editor-scout/`

---

## NEXT_DECISION
1. **Codex Task:** Refactor the selectors in `extension/content-flow-dom.js` to target the contenteditable `DIV` prompt field and the `"Create"` button text instead of old legacy textareas.
2. **Codex Task:** Update the background worker debugger script to handle file selection interception targetting the hidden file input element.
