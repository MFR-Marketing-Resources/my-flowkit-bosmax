/**
 * test-f2v-pre-frames-model-gate.js
 *
 * Contract test for the pre-Frames model gate added for manual_fa0d11f4.
 *
 * Frames is a Veo-only sub-workspace per Google's documented feature
 * matrix. The previous F2V state machine ran model selection INSIDE the
 * Frames config menu (which only mounts AFTER Frames is active) — a
 * chicken-and-egg that left Nano Banana projects stuck at Frames check.
 * ensureVeoModelBeforeFrames() now runs between FLOW_TYPE_VIDEO_SELECTED
 * and the Frames readiness gate, attempts a model switch when a non-Veo
 * model is observed, and fails closed with the visible model candidates
 * listed in the diagnostic when no selector is available.
 *
 * Cases:
 *   1. Veo already selected → PASS, no click, strategy=already_veo.
 *   2. Nano Banana + selector available + Veo option in menu → click +
 *      observed model flips to Veo → PASS, strategy=switched.
 *   3. Nano Banana + no model selector visible → FAIL
 *      ERR_WRONG_MODEL_FOR_F2V (detail=model_selector_unavailable),
 *      diagnostic includes visible_model_candidates.
 *   4. Nano Banana + selector opens but Veo option missing → FAIL
 *      ERR_WRONG_MODEL_FOR_F2V (detail=veo_option_not_in_menu).
 *
 * Run: `node scripts/test-f2v-pre-frames-model-gate.js`
 *
 * Authority: AGENTS.md → CHROME_EXTENSION_MV3_DEBUG_CONTRACT.md →
 * Runtime evidence manual_fa0d11f4 (request_telemetry FAIL snapshot).
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
      onMessage: { addListener() {}, removeListener() {} },
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

function makeButton(window, { text, ariaHaspopup, ariaSelected, dataState, role, parent }) {
  const el = window.document.createElement('button');
  el.type = 'button';
  if (ariaHaspopup) el.setAttribute('aria-haspopup', ariaHaspopup);
  if (ariaSelected != null) el.setAttribute('aria-selected', ariaSelected);
  if (dataState) el.setAttribute('data-state', dataState);
  if (role) el.setAttribute('role', role);
  if (text != null) el.textContent = text;
  makeVisible(el, 220, 48);
  (parent || window.document.body).appendChild(el);
  return el;
}

function makeMenu(window) {
  const menu = window.document.createElement('div');
  menu.setAttribute('role', 'menu');
  makeVisible(menu, 320, 240);
  window.document.body.appendChild(menu);
  return menu;
}

// Captured logStage calls
function makeLogger() {
  const stages = [];
  const fn = (stage, status, message) => stages.push({ stage, status, message });
  return { fn, stages };
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 1 — Veo already selected → PASS, no click.
// ──────────────────────────────────────────────────────────────────────────
async function case1_veoAlreadySelected() {
  const h = createHarness();
  try {
    // Active Video tab so observeFlowState sees topMode=Video.
    makeButton(h.window, { role: 'tab', text: 'Video', ariaSelected: 'true' });
    // Visible Veo model label (matches extractObservedModelLabel).
    const modelChip = h.window.document.createElement('span');
    modelChip.textContent = 'Veo 3.1 - Lite';
    makeVisible(modelChip, 140, 32);
    h.window.document.body.appendChild(modelChip);

    const logger = makeLogger();
    const result = await h.hooks.ensureVeoModelBeforeFrames({ mode: 'F2V' }, logger.fn);

    assert.equal(result.ok, true, 'Case1: must PASS when Veo already selected');
    assert.equal(result.strategy, 'already_veo', 'Case1: strategy=already_veo');
    const pre = logger.stages.find(
      (s) => s.stage === 'FLOW_MODEL_VEO_PRE_FRAMES_VERIFIED',
    );
    assert.ok(pre, 'Case1: stage logged');
    assert.equal(pre.status, 'PASS', 'Case1: stage PASS');
    console.log('[PASS] Case1: Veo already selected → no click, strategy=already_veo');
  } finally { h.close(); }
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 2 — Nano Banana + composer model button visible + Veo option in
// the menu that opens on click → switch succeeds, observed model flips.
// ──────────────────────────────────────────────────────────────────────────
async function case2_switchToVeoSucceeds() {
  const h = createHarness();
  try {
    makeButton(h.window, { role: 'tab', text: 'Video', ariaSelected: 'true' });

    // Composer model chip currently shows Nano Banana 2 (with the
    // documented icon-fused label from manual_fa0d11f4).
    const modelChip = h.window.document.createElement('span');
    modelChip.textContent = '🍌 Nano Banana 2crop_16_9x2';
    makeVisible(modelChip, 200, 36);
    h.window.document.body.appendChild(modelChip);

    // Composer model-selector button with aria-haspopup. When clicked it
    // adds a menu with the Veo 3.1 - Lite option AND swaps the visible
    // model chip text. (This is the desired Flow behaviour.)
    const modelBtn = makeButton(h.window, {
      text: 'Nano Banana 2',
      ariaHaspopup: 'menu',
    });
    modelBtn.addEventListener('click', () => {
      const menu = makeMenu(h.window);
      const veoOption = makeButton(h.window, {
        text: 'Veo 3.1 - Lite',
        role: 'option',
        parent: menu,
      });
      veoOption.addEventListener('click', () => {
        modelChip.textContent = 'Veo 3.1 - Lite';
      });
    });

    const logger = makeLogger();
    const result = await h.hooks.ensureVeoModelBeforeFrames({ mode: 'F2V' }, logger.fn);

    assert.equal(result.ok, true, `Case2: must PASS after switch; got ${JSON.stringify(result)}`);
    assert.equal(result.strategy, 'switched', 'Case2: strategy=switched');
    assert.match(result.model || '', /veo/i, 'Case2: observed model is Veo after switch');
    const pre = logger.stages.find(
      (s) => s.stage === 'FLOW_MODEL_VEO_PRE_FRAMES_VERIFIED',
    );
    assert.ok(pre, 'Case2: stage logged');
    assert.equal(pre.status, 'PASS', 'Case2: stage PASS after switch');
    console.log('[PASS] Case2: Nano Banana → Veo switch succeeds');
  } finally { h.close(); }
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 3 — Nano Banana + no composer model-selector visible → FAIL with
// model_selector_unavailable and diagnostic includes visible candidates.
// ──────────────────────────────────────────────────────────────────────────
async function case3_noModelSelectorAvailable() {
  const h = createHarness();
  try {
    makeButton(h.window, { role: 'tab', text: 'Video', ariaSelected: 'true' });

    // Only a static label exists — no aria-haspopup, no combobox.
    const modelLabel = h.window.document.createElement('span');
    modelLabel.textContent = '🍌 Nano Banana 2';
    makeVisible(modelLabel, 200, 36);
    h.window.document.body.appendChild(modelLabel);

    // Add a few asset-library chips so visible_model_candidates surfaces
    // something interesting in the FAIL diagnostic.
    makeButton(h.window, { text: 'videocamVideos' });
    makeButton(h.window, { text: 'imageImages' });

    const logger = makeLogger();
    const result = await h.hooks.ensureVeoModelBeforeFrames({ mode: 'F2V' }, logger.fn);

    assert.equal(result.ok, false, 'Case3: must FAIL');
    assert.equal(result.error, 'ERR_WRONG_MODEL_FOR_F2V', 'Case3: error code');
    assert.equal(result.detail, 'model_selector_unavailable', 'Case3: detail');

    const pre = logger.stages.find(
      (s) => s.stage === 'FLOW_MODEL_VEO_PRE_FRAMES_VERIFIED',
    );
    assert.ok(pre, 'Case3: stage logged');
    assert.equal(pre.status, 'FAIL', 'Case3: stage FAIL');
    assert.match(
      String(pre.message || ''),
      /ERR_WRONG_MODEL_FOR_F2V/,
      'Case3: message includes error code',
    );
    assert.match(
      String(pre.message || ''),
      /visible_model_candidates/,
      'Case3: diagnostic contains visible_model_candidates field',
    );
    console.log('[PASS] Case3: no model selector → FAIL with candidates in telemetry');
  } finally { h.close(); }
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 4 — Selector opens a menu but Veo option missing → FAIL
// veo_option_not_in_menu.
// ──────────────────────────────────────────────────────────────────────────
async function case4_veoOptionNotInMenu() {
  const h = createHarness();
  try {
    makeButton(h.window, { role: 'tab', text: 'Video', ariaSelected: 'true' });
    const modelChip = h.window.document.createElement('span');
    modelChip.textContent = '🍌 Nano Banana 2';
    makeVisible(modelChip, 200, 36);
    h.window.document.body.appendChild(modelChip);

    const modelBtn = makeButton(h.window, {
      text: 'Nano Banana 2',
      ariaHaspopup: 'menu',
    });
    modelBtn.addEventListener('click', () => {
      const menu = makeMenu(h.window);
      // Menu opens but only lists other image models — no Veo.
      makeButton(h.window, { text: 'Nano Banana 2', role: 'option', parent: menu });
      makeButton(h.window, { text: 'Nano Banana Pro', role: 'option', parent: menu });
      makeButton(h.window, { text: 'Imagen 4', role: 'option', parent: menu });
    });

    const logger = makeLogger();
    const result = await h.hooks.ensureVeoModelBeforeFrames({ mode: 'F2V' }, logger.fn);

    assert.equal(result.ok, false, 'Case4: must FAIL');
    assert.equal(result.error, 'ERR_WRONG_MODEL_FOR_F2V', 'Case4: error code');
    assert.equal(result.detail, 'veo_option_not_in_menu', 'Case4: detail');

    const pre = logger.stages.find(
      (s) => s.stage === 'FLOW_MODEL_VEO_PRE_FRAMES_VERIFIED',
    );
    assert.ok(pre, 'Case4: stage logged');
    assert.equal(pre.status, 'FAIL', 'Case4: stage FAIL');
    assert.match(
      String(pre.message || ''),
      /veo_option_not_in_menu/,
      'Case4: message identifies veo_option_not_in_menu',
    );
    assert.match(
      String(pre.message || ''),
      /menu_visible_options/,
      'Case4: diagnostic includes menu_visible_options for forensics',
    );
    console.log('[PASS] Case4: menu opens but no Veo → FAIL veo_option_not_in_menu');
  } finally { h.close(); }
}

async function main() {
  await case1_veoAlreadySelected();
  await case2_switchToVeoSucceeds();
  await case3_noModelSelectorAvailable();
  await case4_veoOptionNotInMenu();
  console.log('\nALL TESTS PASSED');
}

main().catch((err) => {
  console.error('\nTEST FAILED:', err.message);
  if (err.stack) console.error(err.stack.split('\n').slice(0, 6).join('\n'));
  process.exit(1);
});
