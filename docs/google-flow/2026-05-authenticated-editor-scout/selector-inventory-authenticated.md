# Google Flow - Authenticated Editor Selector Inventory

This inventory catalogs the DOM selectors encountered and verified live inside the authenticated Google Flow project editor workspace.

---

## 1. Verified Live Selectors (VERIFIED_LIVE)

These selectors were captured directly from the active workspace DOM during the live session at URL `https://labs.google/fx/tools/flow/project/6d37e3eb-a8f5-4ea4-ba01-d25514213d4c`.

### 1.1 Composer Dock & Toggle Controls

| Element Name | Purpose | CSS Selector Candidate | Sibling/Aria Suffix | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| **Prompt Box** | Input text prompt | `div[contenteditable="true"]` | `sc-a8ba1f43-0` styled hash wrapper | **VERIFIED_LIVE** | Dynamic classes present; rely on `contenteditable` |
| **Generate Button** | Trigger submission | `button:has-text("Create")` | Inner text: `arrow_forwardCreate` | **VERIFIED_LIVE** | Disabled (`disabled: true`) until input is active |
| **Model selector trigger** | Open model popup menu | `button:has-text("Banana")` | Text: `🍌 Nano Banana 2crop_16_9x2` | **VERIFIED_LIVE** | Hidden when Flow Agent is toggled ON |
| **Flow Agent Toggle** | Enable/disable Flow Agent | `button:has-text("Agent")` | Sibling of Create CTA | **VERIFIED_LIVE** | Standard button element. Toggling ON hides the model selector |
| **Agent Brief Button** | Open prompt templates/briefs | `button:has(span:has-text("document"))` | Appears when Agent is ON | **VERIFIED_LIVE** | Rendered as text symbol/icon button |
| **Agent Settings Button** | Open generation settings sliders | `button:has(span:has-text("settings"))` | Appears when Agent is ON | **VERIFIED_LIVE** | Rendered as settings/sliders icon button |
| **Hidden File Input** | Handle background file paths | `input[type="file"]` | className `sc-dcc7b7da-0 fhJvUC` | **VERIFIED_LIVE** | Located directly under root `/html/body/div/div/input` |
| **Add Media Trigger** | Open upload modal / file selector | `button:has-text("Add Media")` | Radix ID `radix-:r2r:` | **VERIFIED_LIVE** | Spawns file dialog |

### 1.2 Model Config Popover Controls

The following selectors are visible and active inside the popover spawned by clicking the model selector trigger button.

| Element Name | Purpose | CSS Selector Candidate | Sibling/Aria Suffix | Status |
| --- | --- | --- | --- | --- |
| **Image Mode Tab** | Switch composer to Image mode | `[role="tab"]:has-text("Image")`, `button:has-text("Image")` | Top left tab inside popover | **VERIFIED_LIVE** |
| **Video Mode Tab** | Switch composer to Video mode | `[role="tab"]:has-text("Video")`, `button:has-text("Video")` | Top right tab inside popover | **VERIFIED_LIVE** |
| **Aspect: 16:9** | Set landscape layout | `button:has-text("16:9")` | Chip under aspect ratio section | **VERIFIED_LIVE** |
| **Aspect: 9:16** | Set portrait layout | `button:has-text("9:16")` | Chip under aspect ratio section | **VERIFIED_LIVE** |
| **Aspect: 1:1** | Set square layout | `button:has-text("1:1")` | Chip under aspect ratio section | **VERIFIED_LIVE** |
| **Count: 1x** | Output count = 1 | `button:has-text("1x")` | Chip under outputs section | **VERIFIED_LIVE** |
| **Count: x2** | Output count = 2 | `button:has-text("x2")` | Chip under outputs section | **VERIFIED_LIVE** |
| **Active Model Dropdown** | Change selected base model | `button:has-text("Nano Banana 2")` | Bottom model selector row inside popover | **VERIFIED_LIVE** |

### 1.3 Left Navigation & Tools Panel

| Element Name | Purpose | CSS Selector Candidate | Sibling/Aria Suffix | Status |
| --- | --- | --- | --- | --- |
| **All Media navigation** | List workspace images/videos | `button:has-text("All Media")` | Left navigation panel | **VERIFIED_LIVE** |
| **Characters tab** | Toggle characters library view | `button:has-text("Characters")` | Left navigation panel | **VERIFIED_LIVE** |
| **View Scenes tab** | Toggle scene list view | `button:has-text("View scenes")` | Left navigation panel | **VERIFIED_LIVE** |
| **Tools tab** | Open generation/edit tools list | `button:has-text("Tools")` | Left navigation panel | **VERIFIED_LIVE** |
| **Discover Tools Tab** | View all available custom tools | `button:has-text("Discover")` | Top center tab in Tools panel | **VERIFIED_LIVE** |
| **My Tools Tab** | View user-installed custom tools | `button:has-text("My Tools")` | Top center tab in Tools panel | **VERIFIED_LIVE** |

---

## 2. Inferred Selectors (INFERRED_FROM_CODE)

These selectors are mapped from the extension's execution code (`content-flow-dom.js`) and historical UAT fixtures. They could not be visually confirmed or clicked in the live workspace (e.g. because they target advanced models/modes that require active generation credits or specific backend triggers):

| Element Name | Purpose | CSS Selector Candidate | XPath / Sibling | Status |
| --- | --- | --- | --- | --- |
| **Veo 3.1 Model selector** | Choose target generation model | `[role="menuitem"]:has-text("Veo 3.1")` | Triggered inside model popup | **INFERRED_FROM_CODE** |

---

## 3. Unresolved/Not Verified Selectors (NOT VERIFIED)

These elements were not encountered or verified in the live workspace.

| Element Name | Purpose | Selector Candidate | Status |
| --- | --- | --- | --- |
| **Paywall Dialog** | Detect limit / pricing upgrades | `[role="dialog"]:has-text("Pricing")` | **NOT VERIFIED** |
| **Error Toast** | Capture error messages | `[role="alert"]` | **NOT VERIFIED** |
| **OS File Interceptor** | CDP suppression state | `Page.fileChooserOpened` event | **NOT VERIFIED** |
