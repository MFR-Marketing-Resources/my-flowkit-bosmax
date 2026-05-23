# Google Flow - Authenticated Editor Scouting Report

## STATUS
- **PARTIAL / CORRECTED**  
  *Note: The authenticated workspace editor UI structure, settings menus, and tool catalogs have been scouted and matched against visual screenshots. Live generation runs and file uploads were not executed to preserve credits. This report acts as a selector refactor reference, not a full runtime UAT execution proof.*

## SCOPE & AUTHORITY DISCLAIMER
> [!IMPORTANT]
> This evidence pack constitutes **authenticated-editor scouting evidence** compiled specifically to guide selector refactoring and DOM navigation planning. It does **not** serve as end-to-end execution proof for the upload, generate, or runtime telemetry workflows.

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

### 1. Model & Module Configuration Popover (Image & Video)
* **Popover Tabs:** Toggling between the **Image** and **Video** modules is handled via tabs on top of the model settings popover. Both tabs are fully interactive and verified.
* **Aspect Ratio Chips:** Mapped five aspect ratio chip controls inside the popover: `16:9`, `4:3`, `1:1`, `3:4`, and `9:16`.
* **Output Count Chips:** Mapped four generation output count chips inside the popover: `1x`, `x2` (default), `x3`, and `x4`.
* **Model Dropdown:** Contains a dropdown menu selector for choosing the active base generator (defaults to `Nano Banana 2`).
* **Zero-Credit Indicator:** The popover displays the text `"Generating will use 0 credits"`, indicating that the selected model configuration does not consume quota.

### 2. Flow Agent Interface Modes
* **Agent OFF Layout (Default):** Displays the visual prompt contenteditable `DIV`, the Model selector chip (`🍌 Nano Banana 2crop_16_9x2`), and the disabled Generate button (`arrow_forwardCreate`).
* **Agent ON Layout:** Toggling the Agent button ON hides the model selector chip entirely and replaces it with two new buttons:
  - **Creative Brief Button:** Symbolized by a document icon, used to set target generation brief structures.
  - **Parameter Settings Button:** Symbolized by slider controls, used to adjust visual generation weights.

### 3. Discover Tools Sidebar
The left-hand Tools tab (`apps_spark_2Tools`) opens a sidebar catalog containing custom tools. The catalog's visual state changes based on scroll positions and DOM availability.

* **Visually Represented on Default Tools Panel (see [screenshot_11_tools_panel.png](file:///c:/Users/USER/Desktop/_ref_flowkit/docs/google-flow/2026-05-authenticated-editor-scout/screenshots/screenshot_11_tools_panel.png)):**
  > [!NOTE]
  > In the default tools sidebar, items under the "Image" header are represented only by graphical card previews. No text titles or descriptions are shown visually on the screen. The names below are mapped to the cards via DOM tree association:
  - **Simple Sketch** (by Google): Card showing a yellow cute outline creature next to its 3D rendered version.
  - **Scene Explorer** (by Google): Card showing a split-screen image layout of a modern house.
  - **Mockup** (by Google): Card showing an iPhone mockup template.
  - **Image Editor** (by Google): Card showing a pink balloon with an active "DRIFT" text bounding box.

* **Visually Confirmed on Scrolled Tools Panel (see [screenshot_14_tools_panel_scrolled.png](file:///c:/Users/USER/Desktop/_ref_flowkit/docs/google-flow/2026-05-authenticated-editor-scout/screenshots/screenshot_14_tools_panel_scrolled.png)):**
  The scrolled tools sidebar visually displays cards with both titles, author sub-labels, and descriptions:
  - **Datamosh** (by Kaloyan Kolev, Google): "Add datamoshing effects to your videos"
  - **3D Model Visualizer** (by Filip Havlena, Google): "Use a 3D model to guide your image generation"
  - **Scout360** (by PJ Ace): "Capture a 360 degree environment from an image"
  - **Ribbit** (by Kat Zhang): "Perform videos live as the beat drives playback"
  - **Whisk** (by Google): "Use images as prompts to visualize your ideas"
  - **Pose Text** (by Alan Yam, Google): "Add text labels that track a character in your video"
  - **3D Face Swap** (by Google): "Swap your face with virtual characters"

* **Partially Visible / Scrolled Out at Top of Scrolled Tools Panel (see [screenshot_14_tools_panel_scrolled.png](file:///c:/Users/USER/Desktop/_ref_flowkit/docs/google-flow/2026-05-authenticated-editor-scout/screenshots/screenshot_14_tools_panel_scrolled.png)):**
  Four tools are partially cut off at the top of the scrolled view. Their titles are off-screen, but their author credits and descriptions are visible:
  - **[Title Scrolled Out]** (by Shashwath Santosh and Alan Yam, Google): "Deconstruct videos and gifs to create 3D sculptures"
  - **[Title Scrolled Out]** (by Arden Schager, Google): "Generate futuristic tracking effects" *(Note: See discrepancy below regarding Mask Magic)*
  - **[Title Scrolled Out]** (by Sam Lawton, Google): "See your video in a new dimension"
  - **[Title Scrolled Out]** (by Google): "Drop yourself into footage"

* **Present in DOM / Inferred but Off-Screen (confirmed via DOM scan or codebase context, NOT visible in screenshots):**
  - **Shot Explorer** (by Google): "See your scene from new angles"
  - **Mask Magic** (by Arden Schager, Google): "Perform selective image edits using segmentation" *(Note: The visible card by Arden Schager displays a different description 'Generate futuristic tracking effects' in screenshot 14, indicating a possible description shift or a separate tool configuration)*
  - **Converge** (by Chris Maestas): "Render your sketches"
  - **Grid Architect** (by Henry Daubrez): "Create image grids and extract individual images from them"
  - **Shader Effects** (by Google): "Apply customizable filters to your media"
  - **Type Overlays** (by Google): "Add animated text to your videos"
  - **pixelBento** (by László Gaal): "Apply post-processing effects like lo-fi and glitch"

---

## INFERRED_FROM_CODE
* **CDP File Interception:** Suppression of OS file pickers requires registering a background listener for `Page.fileChooserOpened` and injecting paths via `DOM.setFileInputFiles` relative to the hidden `input[type="file"]`.
* **React Synthetic Actions:** Text injection into the contenteditable `DIV` requires dispatching custom synthetic Input and Change events so the React state updates properly.

---

## NOT VERIFIED
* Live drawing or rendering execution of custom sidebar tools (Simple Sketch, pixelBento, etc.).
* DOM structure transitions when a preview thumbnail is populated.
* Operations progress tracker updates during live generation cycles.
* Paywall billing modal warnings.

---

## SCREEN MAP
- **Dashboard Hub:** Initial view containing historical projects grid and the primary `+ New Project` button.
- **Editor Workspace Canvas:** Split panel containing the left navigation sidebar (All Media, Characters, Scenes, Tools, Trash) and the bottom composer dock (Prompt DIV, Model trigger, Agent toggle, Create CTA).

---

## SELECTOR INVENTORY
- **Summary:** Mapped prompt text fields, model dropdown triggers, popover controls, and navigation selectors.
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
4. **Agent Mode Layout Shift:** The selector for the model trigger chip disappears when Agent is toggled ON, and the UI shifts to show brief/parameter triggers instead. Automation must verify Agent state before looking for model settings.

---

## FLOWCHARTS
- **Operator Flowchart:** [operator-flowchart-authenticated.md](file:///c:/Users/USER/Desktop/_ref_flowkit/docs/google-flow/2026-05-authenticated-editor-scout/operator-flowchart-authenticated.md)
- **Extension Flowchart:** [extension-flowchart-authenticated.md](file:///c:/Users/USER/Desktop/_ref_flowkit/docs/google-flow/2026-05-authenticated-editor-scout/extension-flowchart-authenticated.md)

---

## SCREENSHOT INDEX & QUALITY STATUS
> [!NOTE]
> All screenshots in this index are **raw, non-annotated visual captures** of the browser window. They do not contain custom graphical overlays, highlight circles, or callout labels.

All screenshots are saved in `docs/google-flow/2026-05-authenticated-editor-scout/screenshots/`:
1. `screenshot_1_workspace_landing.png`: Editor workspace load screen.
2. `screenshot_2_editor_default.png`: Editor default state with the bottom composer panel.
3. `screenshot_4_model_settings.png`: Open dropdown selection popup menu.
4. `screenshot_state_step_1.png` - `screenshot_state_step_8.png`: Sequential UI state updates.
5. `screenshot_13_model_dropdown_real.png`: The model config popover open, showing the **Image** and **Video** module tabs, aspect ratios, count chips, and base model options.
6. `screenshot_14_tools_panel_scrolled.png`: Scrolled view of the left Tools panel showing categorized custom Image and Video tools.
7. `screenshot_15_agent_toggled_real.png`: View of the composer dock with Flow Agent ON, showing brief and settings slider controls.

---

## GITHUB DELIVERY
- **Branch:** `codex/google-flow-authenticated-scout`
- **Commit SHA:** `bf1d4e9b3beddd08f4523d3aff8b2127514f953b`
- **Push Target:** `https://github.com/farisdatosheikh/my-flowkit-bosmax`
- **Push Result:** `Successfully pushed to remote origin branch codex/google-flow-authenticated-scout`
- **Uploaded Paths:** `docs/google-flow/2026-05-authenticated-editor-scout/`

---

## NEXT_DECISION
1. **Codex Task:** Refactor the selectors in `extension/content-flow-dom.js` to target the contenteditable `DIV` prompt field and the `"Create"` button text instead of old legacy textareas.
2. **Codex Task:** Update the background worker debugger script to handle file selection interception targetting the hidden file input element.
