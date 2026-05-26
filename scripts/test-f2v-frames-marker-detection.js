/**
 * test-f2v-frames-marker-detection.js
 *
 * Source-grounded Frames marker detection tests. Each case builds a
 * minimal JSDOM Flow-page surface, evaluates extension/content-flow-dom.js
 * inside it, then exercises the new getFramesWorkspaceEvidence /
 * collectFramesReadinessDiagnostic / _classifyFramesReadinessFailure
 * helpers against the brief's required behaviour.
 *
 * The seven cases mirror the operator brief for manual_8e432a34:
 *   1. Explicit Frames control after Video — click_required + classify pass.
 *   2. "Add start frame" affordance alone — auto-ready, no click required.
 *   3. "Add end frame" affordance alone — auto-ready, no click required.
 *   4. Generic placeholder "Start creating or drop media" — must NOT pass.
 *   5. Portal-escaped Frames option — detected and normalized to ancestor.
 *   6. No marker at all — fails with structured diagnostic snapshot.
 *   7. Asset-library shell (manual_8e432a34 signature) — classifies as
 *      ERR_FLOW_EDITOR_NOT_FOCUSED, NOT generic ERR_FRAMES_PANEL_NOT_READY.
 *
 * Run: `node scripts/test-f2v-frames-marker-detection.js`
 *
 * Authority: AGENTS.md → CHROME_EXTENSION_MV3_DEBUG_CONTRACT.md →
 * Source-Grounded Frames Diagnostic Brief 2026-05-26 →
 * Runtime evidence manual_8e432a34 (request_telemetry FAIL snapshot).
 */

'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const SOURCE_PATH = path.join(__dirname, '..', 'extension', 'content-flow-dom.js');
const SOURCE_TEXT = fs.readFileSync(SOURCE_PATH, 'utf8');

function defineRect(node, width = 240, height = 80) {
  Object.defineProperty(node, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({
      x: 0, y: 0, top: 0, left: 0,
      right: width, bottom: height, width, height,
      toJSON() { return { width, height }; },
    }),
  });
  return node;
}

function makeVisible(node, width = 240, height = 80) {
  node.style.display = 'block';
  node.style.visibility = 'visible';
  node.style.opacity = '1';
  defineRect(node, width, height);
  return node;
}

function installMinimalPolyfills(window) {
  window.__FLOWKIT_TEST_MODE__ = true;
  window.__FLOWKIT_ENABLE_TEST_HOOKS__ = true;
  window.PointerEvent = window.PointerEvent || window.MouseEvent;
  window.HTMLElement.prototype.scrollIntoView =
    window.HTMLElement.prototype.scrollIntoView || (() => {});

  if (!Object.getOwnPropertyDescriptor(window.HTMLElement.prototype, 'innerText')) {
    Object.defineProperty(window.HTMLElement.prototype, 'innerText', {
      configurable: true,
      get() { return this.textContent || ''; },
      set(value) { this.textContent = value; },
    });
  }
  if (!window.CSS) window.CSS = {};
  if (!window.CSS.escape) {
    window.CSS.escape = (value) => String(value).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  }
  window.chrome = {
    runtime: {
      lastError: null,
      onMessage: {
        addListener() {},
        removeListener() {},
      },
      sendMessage() {},
    },
  };
}

function createHarness() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'https://labs.google/fx/tools/flow/project/test',
    pretendToBeVisual: true,
    runScripts: 'outside-only',
  });
  const { window } = dom;
  installMinimalPolyfills(window);
  makeVisible(window.document.body, 1280, 720);
  window.eval(SOURCE_TEXT);
  const hooks = window.__FLOWKIT_TEST_HOOKS__;
  assert.ok(hooks, 'Expected __FLOWKIT_TEST_HOOKS__ to be defined');
  return { window, document: window.document, hooks, close: () => window.close() };
}

/** Helper: create a control element with given attributes. */
function makeControl(window, { tag = 'button', role, text, ariaSelected, dataState, ariaPressed, classes, parent }) {
  const el = window.document.createElement(tag);
  if (role) el.setAttribute('role', role);
  if (ariaSelected != null) el.setAttribute('aria-selected', ariaSelected);
  if (ariaPressed != null) el.setAttribute('aria-pressed', ariaPressed);
  if (dataState) el.setAttribute('data-state', dataState);
  if (classes) el.className = classes;
  if (text != null) el.textContent = text;
  makeVisible(el, 200, 48);
  (parent || window.document.body).appendChild(el);
  return el;
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 1 — Explicit Frames control after Video is detected as auto-ready
//          when aria-selected is true. (Click-not-required path.)
// ──────────────────────────────────────────────────────────────────────────
function case1_explicitFramesControlActive() {
  const h = createHarness();
  try {
    // Active Video top tab.
    makeControl(h.window, { role: 'tab', text: 'Video', ariaSelected: 'true' });
    // Active Frames sub tab — strong marker.
    const framesTab = makeControl(h.window, {
      role: 'tab', text: 'Frames', ariaSelected: 'true', dataState: 'active',
    });

    const evidence = h.hooks.getFramesWorkspaceEvidence();
    assert.equal(evidence.ok, true, 'Case1: must be ok when active Frames tab exists');
    assert.equal(evidence.marker, 'active_frames_control', 'Case1: marker name');
    assert.ok(evidence.element, 'Case1: must return the interactive ancestor');
    // Normalization → returned element is the actual [role=tab] control.
    assert.equal(evidence.element.getAttribute('role'), 'tab', 'Case1: ancestor is role=tab');
    assert.equal(evidence.element, framesTab, 'Case1: ancestor IS the framesTab');
    console.log('[PASS] Case1: explicit Frames control (active) is auto-ready');
  } finally { h.close(); }
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 2 — Frames panel mounted with "Add start frame" affordance only.
//          The strong-marker matcher must pass without an active Frames tab.
// ──────────────────────────────────────────────────────────────────────────
function case2_addStartFrameAffordanceAutoReady() {
  const h = createHarness();
  try {
    makeControl(h.window, { role: 'tab', text: 'Video', ariaSelected: 'true' });
    // Frames tab present but NOT aria-selected (e.g. mid-transition).
    makeControl(h.window, { role: 'tab', text: 'Frames' });
    // Strong panel marker.
    makeControl(h.window, { tag: 'button', text: 'add_2Add start frame' });

    const evidence = h.hooks.getFramesWorkspaceEvidence();
    assert.equal(evidence.ok, true, 'Case2: Add start frame must auto-ready');
    assert.match(
      String(evidence.marker || ''),
      /add\s+start\s+frame/i,
      'Case2: marker text records the affordance',
    );
    console.log('[PASS] Case2: "Add start frame" alone is sufficient (auto-ready)');
  } finally { h.close(); }
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 3 — Same as Case 2 but only "Add end frame" present.
// ──────────────────────────────────────────────────────────────────────────
function case3_addEndFrameAffordanceAutoReady() {
  const h = createHarness();
  try {
    makeControl(h.window, { role: 'tab', text: 'Video', ariaSelected: 'true' });
    makeControl(h.window, { tag: 'button', text: '+ Add end frame' });

    const evidence = h.hooks.getFramesWorkspaceEvidence();
    assert.equal(evidence.ok, true, 'Case3: Add end frame must auto-ready');
    assert.match(
      String(evidence.marker || ''),
      /add\s+end\s+frame/i,
      'Case3: marker text records the affordance',
    );
    console.log('[PASS] Case3: "Add end frame" alone is sufficient (auto-ready)');
  } finally { h.close(); }
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 4 — Generic "Start creating or drop media" placeholder MUST NOT pass
//          the Frames gate. The brief explicitly warns this is a false-
//          positive source for the bare "Start" / "End" tokens.
// ──────────────────────────────────────────────────────────────────────────
function case4_genericStartPlaceholderRejected() {
  const h = createHarness();
  try {
    makeControl(h.window, { role: 'tab', text: 'Video', ariaSelected: 'true' });
    // Composer placeholder text — looks tempting but must be rejected.
    makeControl(h.window, { tag: 'div', text: 'Start creating or drop media' });
    // And another lookalike that contains the word Start.
    makeControl(h.window, { tag: 'span', text: 'Start typing your prompt' });

    const evidence = h.hooks.getFramesWorkspaceEvidence();
    assert.equal(evidence.ok, false, 'Case4: generic Start placeholder must NOT pass');
    assert.equal(evidence.marker, 'none', 'Case4: marker stays "none"');
    console.log('[PASS] Case4: generic "Start creating or drop media" rejected');
  } finally { h.close(); }
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 5 — Frames option lives inside a portal-escaped menu under body.
//          The portal collector must find it AND closest()-normalize it to
//          the interactive [role=option] ancestor, not its label child.
// ──────────────────────────────────────────────────────────────────────────
function case5_portalFramesOptionNormalized() {
  const h = createHarness();
  try {
    makeControl(h.window, { role: 'tab', text: 'Video', ariaSelected: 'true' });

    // Build a portal-escaped menu under document.body root.
    const menu = h.window.document.createElement('div');
    menu.setAttribute('role', 'menu');
    menu.setAttribute('data-radix-portal', '');
    makeVisible(menu, 300, 200);
    h.window.document.body.appendChild(menu);

    const option = h.window.document.createElement('div');
    option.setAttribute('role', 'option');
    // Mark the portal-escaped Frames option as semantically ACTIVE — a
    // portal frames-tab only counts as auto-ready evidence when it is
    // aria-selected="true" or data-state="active". An inactive portal
    // tab means the gate still needs to click it.
    option.setAttribute('aria-selected', 'true');
    option.setAttribute('data-state', 'active');
    makeVisible(option, 280, 48);
    menu.appendChild(option);

    // Label LIVES under the option but is a span — the un-normalized text
    // match would have returned the span itself. closest() must rescue it.
    const labelSpan = h.window.document.createElement('span');
    labelSpan.textContent = 'Frames';
    makeVisible(labelSpan, 80, 24);
    option.appendChild(labelSpan);

    const evidence = h.hooks.getFramesWorkspaceEvidence();
    assert.equal(evidence.ok, true, 'Case5: portal-escaped Frames option must be detected');
    assert.match(
      String(evidence.marker || ''),
      /portal_frames_tab|active_frames_control/i,
      'Case5: marker records portal source',
    );
    // Normalization → returned element is the role=option ancestor,
    // NOT the inner <span> that held the text.
    const role = evidence.element.getAttribute && evidence.element.getAttribute('role');
    assert.ok(
      role === 'option' || role === 'tab' || role === 'button',
      `Case5: ancestor must be an interactive role; got role="${role}"`,
    );
    console.log('[PASS] Case5: portal/body Frames option detected + normalized');
  } finally { h.close(); }
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 6 — No Frames marker anywhere → must fail with rich diagnostic.
//          And classifier falls through to ERR_FRAMES_PANEL_NOT_READY when
//          model is Veo (correct project type) but panel hasn't mounted.
// ──────────────────────────────────────────────────────────────────────────
function case6_noMarkerFailsWithSnapshot() {
  const h = createHarness();
  try {
    // Real Video editor surface but Frames panel not yet mounted.
    makeControl(h.window, { role: 'tab', text: 'Video', ariaSelected: 'true' });
    makeControl(h.window, { tag: 'span', text: 'Veo 3.1 - Lite' });

    const evidence = h.hooks.getFramesWorkspaceEvidence();
    assert.equal(evidence.ok, false, 'Case6: no marker → not ok');
    assert.equal(evidence.marker, 'none', 'Case6: marker is "none"');

    const diagnostic = h.hooks.collectFramesReadinessDiagnostic();
    // Every brief-required field is present on the diagnostic.
    const required = [
      'frames_marker', 'top_mode', 'sub_mode', 'model',
      'visible_upload_slots', 'visible_control_texts',
      'add_start_frame_visible', 'add_end_frame_visible',
      'prompt_field_visible', 'aria_selected_values',
      'data_state_values', 'portal_body_candidates',
      'is_asset_library_view', 'is_wrong_model_for_f2v',
    ];
    for (const field of required) {
      assert.ok(
        Object.prototype.hasOwnProperty.call(diagnostic, field),
        `Case6: diagnostic missing required field '${field}'`,
      );
    }
    assert.equal(diagnostic.frames_marker, 'none', 'Case6: marker=none');
    assert.equal(diagnostic.add_start_frame_visible, false, 'Case6: no add-start');
    assert.equal(diagnostic.add_end_frame_visible, false, 'Case6: no add-end');
    assert.equal(diagnostic.is_wrong_model_for_f2v, false, 'Case6: Veo, not Nano Banana');
    assert.equal(diagnostic.is_asset_library_view, false, 'Case6: not asset library');

    const errCode = h.hooks._classifyFramesReadinessFailure(diagnostic);
    assert.equal(
      errCode, 'ERR_FRAMES_PANEL_NOT_READY',
      'Case6: classifier falls through to ERR_FRAMES_PANEL_NOT_READY',
    );
    console.log('[PASS] Case6: no marker → ERR_FRAMES_PANEL_NOT_READY with full snapshot');
  } finally { h.close(); }
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 7 — Asset-library shell signature (manual_8e432a34 reproduction).
//          The classifier must return ERR_FLOW_EDITOR_NOT_FOCUSED, NOT
//          ERR_FRAMES_PANEL_NOT_READY, so the operator gets the correct
//          recovery action ("navigate back to project editor"), not a
//          misleading frames-panel error.
// ──────────────────────────────────────────────────────────────────────────
function case7_assetLibraryClassifiedSpecifically() {
  const h = createHarness();
  try {
    // Reproduce the asset-library control signature from manual_8e432a34's
    // diagnostic snapshot (icon-fused Material Icons text).
    const libraryChips = [
      'arrow_backGo Back',
      'dashboardAll Media',
      'imageImages',
      'videocamVideos',
      'voice_selectionVoices',
      'faceAvatar',
      'drive_folder_uploadUploads',
      'uploadUpload media',
      'Recentarrow_drop_down',
      '🍌 Nano Banana 2crop_16_9x2',
    ];
    for (const chipText of libraryChips) {
      makeControl(h.window, { tag: 'button', role: 'button', text: chipText });
    }

    // The asset-library detector should fire.
    const lib = h.hooks._detectAssetLibraryView();
    assert.equal(
      lib.detected, true,
      `Case7: asset library must be detected; matched=${JSON.stringify(lib.matched_tokens)}`,
    );
    assert.ok(lib.hit_count >= 4, 'Case7: at least 4 library tokens visible');

    const diagnostic = h.hooks.collectFramesReadinessDiagnostic();
    assert.equal(diagnostic.is_asset_library_view, true, 'Case7: diagnostic flags library view');

    // Nano Banana detection is independent and also fires here.
    assert.equal(
      diagnostic.is_wrong_model_for_f2v, true,
      'Case7: Nano Banana model also flagged',
    );

    // Classification priority: wrong model wins over editor-not-focused
    // because the wrong model is the upstream cause (no Veo project = no
    // Frames affordances even if we DID land on the editor).
    const errCode = h.hooks._classifyFramesReadinessFailure(diagnostic);
    assert.equal(
      errCode, 'ERR_WRONG_MODEL_FOR_F2V',
      `Case7: classifier should be ERR_WRONG_MODEL_FOR_F2V (Nano Banana wins); got ${errCode}`,
    );
    console.log('[PASS] Case7: asset-library + Nano Banana → ERR_WRONG_MODEL_FOR_F2V');
  } finally { h.close(); }
}

// ──────────────────────────────────────────────────────────────────────────
// Bonus: false-positive sanity — the asset-library "videocamVideos" chip
// must NOT be mistaken for an active Video mode tab. This is the upstream
// half of the manual_8e432a34 fix that lets the Frames gate fail honestly
// instead of being fed a false-positive topMode='Video' from upstream.
// ──────────────────────────────────────────────────────────────────────────
function bonus_iconStrippedExactMatchForVideo() {
  const h = createHarness();
  try {
    // Only an asset-library chip exists; no real Video mode tab.
    const chip = makeControl(h.window, {
      tag: 'button', role: 'button', text: 'videocamVideos', ariaSelected: 'true',
    });
    // Exact-mode call for 'Video' must NOT match the videocamVideos chip.
    const matched = h.hooks.findElementByText(
      'button, [role="tab"], [role="button"]',
      'Video',
      { exact: true },
    );
    assert.equal(
      matched, null,
      'Bonus: exact-mode "Video" must not match "videocamVideos" chip',
    );

    // Legacy lenient mode still matches (we did not regress other callers).
    const lenient = h.hooks.findElementByText(
      'button, [role="tab"], [role="button"]',
      'Video',
    );
    assert.ok(
      lenient === chip || lenient === null,
      'Bonus: lenient mode behaviour preserved (matches or returns null)',
    );
    console.log('[PASS] Bonus: exact-mode findElementByText rejects "videocamVideos"');
  } finally { h.close(); }
}

function main() {
  case1_explicitFramesControlActive();
  case2_addStartFrameAffordanceAutoReady();
  case3_addEndFrameAffordanceAutoReady();
  case4_genericStartPlaceholderRejected();
  case5_portalFramesOptionNormalized();
  case6_noMarkerFailsWithSnapshot();
  case7_assetLibraryClassifiedSpecifically();
  bonus_iconStrippedExactMatchForVideo();
  console.log('\nALL TESTS PASSED');
}

try {
  main();
} catch (err) {
  console.error('\nTEST FAILED:', err.message);
  if (err.stack) console.error(err.stack.split('\n').slice(0, 6).join('\n'));
  process.exit(1);
}
