# Google Flow - Selector Inventory

This inventory documents the exact selector candidates, fallback strategies, and state prerequisites for the Google Flow Frames-to-Video (F2V) automation Golden Path.

---

## 1. Project Navigation and Landing Page

| Target Element | Purpose | CSS Selector Candidate | XPath / Sibling Fallback | Stability Assessment |
| --- | --- | --- | --- | --- |
| **Create with Flow** | Start application from landing | `button:has-text("Create with Google Flow")` | `//button[contains(., "Create with Google Flow")]` | **Stable** (Primary CTA on public landing page) |
| **New Project** | Open blank workspace | `button:has-text("New project")`, `[role="button"]:has-text("Create new")` | `//button[contains(translate(., 'N', 'n'), "new project")]` | **Medium Risk** (Class name varies, relies on text match) |

---

## 2. Composer Mode Selection

| Target Element | Purpose | CSS Selector Candidate | Sibling/Aria Suffix | Stability Assessment |
| --- | --- | --- | --- | --- |
| **Video Mode Tab** | Switch to video generation | `button[role="tab"]:has-text("Video")` | Sibling of "Image" tab control | **Stable** (Standard Radix tab structure) |
| **Frames Sub-mode** | Activate start/end upload slots | `button[role="tab"]:has-text("Frames")` | Near "Ingredients" tab | **Stable** (Required for Golden Path) |

---

## 3. Aspect Ratio and Settings

| Target Element | Purpose | CSS Selector Candidate | Sibling/Aria Suffix | Stability Assessment |
| --- | --- | --- | --- | --- |
| **Model Menu Trigger** | Open model popover/dropdown | `button[aria-haspopup="menu"]` | Sibling of Aspect Ratio trigger | **High Risk** (Subject to A/B testing model labels) |
| **9:16 Aspect Chip** | Configure Portrait aspect | `button[role="tab"][aria-controls$="content-PORTRAIT"]` | Chip labeled "9:16" | **Stable** (Radix controlled tabs) |
| **1x Quantity Chip** | Set outputs count to 1 | `button[role="tab"][aria-controls$="content-1"]` | Chip labeled "1x" | **Stable** (Radix controlled tabs) |

---

## 4. Input slots & Prompt box

| Target Element | Purpose | CSS Selector Candidate | XPath / Inner Elements | Stability Assessment |
| --- | --- | --- | --- | --- |
| **Start Upload Slot** | Intercept click for CDP upload | `button:has-text("Start"), label:has-text("Start")` | Container query for slot "Start" | **High Risk** (Encapsulated in Shadow DOM or nested flexbox) |
| **Hidden File Input** | File path receiver | `input[type="file"]` | Sibling inside slot container | **Medium Risk** (React portals make DOM nesting dynamic) |
| **Prompt Box** | Input text prompt | `textarea`, `[contenteditable="true"]`, `[role="textbox"]` | Placeholder "What do you want to create?" | **Stable** (Main textarea present in composer footer) |
| **Generate Button** | Trigger submission | `button[aria-label*="Create"]`, `button[aria-label*="Generate"]` | Enabled state suffix indicator | **Stable** (CTA button on composer footer) |

---

## 5. Status Indicators and Modals

| Target Element | Purpose | CSS Selector Candidate | XPath / Text | Stability Assessment |
| --- | --- | --- | --- | --- |
| **Asset Picker Modal** | Multi-asset select dialog | `[role="dialog"]`, `[aria-modal="true"]`, `dialog` | Dialog containing text "Upload image" | **High Risk** (Renders inside Shadow DOM / React portal) |
| **Loading Skeleton** | Progress indicator | `[aria-busy="true"]`, `[role="progressbar"]`, `.spinner` | Loading class matching | **Medium Risk** (Spinners are dynamically loaded/removed) |
| **Error Popups** | Error classification | `[role="alert"]`, `.error-toast` | Matching text: "Something went wrong" | **Medium Risk** |
| **Paywall Modal** | Detect limit / billing walls | `[role="dialog"]:has-text("Credits")` | Dialog text containing "Upgrade" or "Pricing" | **Medium Risk** |
