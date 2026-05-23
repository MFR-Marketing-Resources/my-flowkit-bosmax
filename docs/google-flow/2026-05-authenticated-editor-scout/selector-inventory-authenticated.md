# Google Flow - Authenticated Editor Selector Inventory

This inventory catalogs the DOM selectors encountered and verified live inside the authenticated Google Flow project editor workspace.

---

## 1. Verified Live Selectors (VERIFIED_LIVE)

These selectors were captured directly from the active workspace DOM during the live session at URL `https://labs.google/fx/tools/flow/project/6d37e3eb-a8f5-4ea4-ba01-d25514213d4c`.

| Element Name | Purpose | CSS Selector Candidate | Sibling/Aria Suffix | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| **Prompt Box** | Input text prompt | `div[contenteditable="true"]` | `sc-a8ba1f43-0` styled hash wrapper | **VERIFIED_LIVE** | Dynamic classes present; rely on `contenteditable` |
| **Generate Button** | Trigger submission | `button:has-text("Create")` | Inner text: `arrow_forwardCreate` | **VERIFIED_LIVE** | Disabled (`disabled: true`) until input is active |
| **Model selector trigger** | Open model popup menu | `button[aria-haspopup="menu"]` | Text: `🍌 Nano Banana 2crop_16_9x2` | **VERIFIED_LIVE** | Labeled with Radix ID `radix-:r3b:` |
| **Flow Agent Toggle** | Enable/disable Flow Agent | `button:has-text("Agent")` | Sibling of Create CTA | **VERIFIED_LIVE** | Standard button element |
| **Hidden File Input** | Handle background file paths | `input[type="file"]` | className `sc-dcc7b7da-0 fhJvUC` | **VERIFIED_LIVE** | Located directly under root `/html/body/div/div/input` |
| **Add Media Trigger** | Open upload modal / file selector | `button:has-text("Add Media")` | Radix ID `radix-:r2r:` | **VERIFIED_LIVE** | Spawns file dialog |
| **All Media navigation** | List workspace images/videos | `button:has-text("All Media")` | Left navigation panel | **VERIFIED_LIVE** | Active tab indicator state |
| **Characters tab** | Toggle characters library view | `button:has-text("Characters")` | Left navigation panel | **VERIFIED_LIVE** | Standard navigation button |
| **View Scenes tab** | Toggle scene list view | `button:has-text("View scenes")` | Left navigation panel | **VERIFIED_LIVE** | Standard navigation button |
| **Tools tab** | Open generation/edit tools list | `button:has-text("Tools")` | Left navigation panel | **VERIFIED_LIVE** | Standard navigation button |

---

## 2. Inferred Selectors (INFERRED_FROM_CODE)

These selectors were not directly interacted with in the live session, but are mapped from the extension's execution code (`content-flow-dom.js`) and historical UAT fixtures.

| Element Name | Purpose | CSS Selector Candidate | XPath / Sibling | Status |
| --- | --- | --- | --- | --- |
| **Aspect Ratio Tab (9:16)** | Select Portrait aspect | `button[role="tab"][aria-controls$="content-PORTRAIT"]` | `//button[contains(., "9:16")]` | **INFERRED_FROM_CODE** |
| **Quantity Chip (1x)** | Select single output count | `button[role="tab"][aria-controls$="content-1"]` | `//button[contains(., "1x")]` | **INFERRED_FROM_CODE** |
| **Video Mode Tab** | Switch composer to Video mode | `button[role="tab"]:has-text("Video")` | Tab control | **INFERRED_FROM_CODE** |
| **Frames Sub-mode Tab** | Switch composer to Frames sub-mode | `button[role="tab"]:has-text("Frames")` | Tab control | **INFERRED_FROM_CODE** |
| **Veo 3.1 Model selector** | Choose target generation model | `[role="menuitem"]:has-text("Veo 3.1")` | Triggered inside model popup | **INFERRED_FROM_CODE** |

---

## 3. Unresolved/Not Verified Selectors (NOT VERIFIED)

These elements were not encountered or verified in the live workspace.

| Element Name | Purpose | Selector Candidate | Status |
| --- | --- | --- | --- |
| **Paywall Dialog** | Detect limit / pricing upgrades | `[role="dialog"]:has-text("Pricing")` | **NOT VERIFIED** |
| **Error Toast** | Capture error messages | `[role="alert"]` | **NOT VERIFIED** |
| **OS File Interceptor** | CDP suppression state | `Page.fileChooserOpened` event | **NOT VERIFIED** |
