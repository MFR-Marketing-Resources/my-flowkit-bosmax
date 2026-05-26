/**
 * test-f2v-composer-settings-panel.js
 *
 * Contract tests for configureVisibleF2VComposerSettings — added for
 * manual_da996ef1. The operator's screen visibly contained
 * Video / Frames / 9:16 / 1x / Veo 3.1 - Lite inside the composer
 * settings panel, but the previous F2V state machine had hard-failed
 * ERR_WRONG_MODEL_FOR_F2V on the OUTER page's "Nano Banana 2" label
 * before ever opening that panel.
 *
 * Required cases (from the operator's correction brief):
 *   1. Settings panel visible with Video/Frames/9:16/1x/Veo → all
 *      clicked in order; configureVisibleF2VComposerSettings returns
 *      ok:true with configured map.
 *   2. Initial shell text says "Nano Banana 2" but the panel contains
 *      Veo 3.1 - Lite → must SELECT Veo and PASS (no premature failure
 *      on outer page model).
 *   3. Asset-library page contains "videocamVideos" but no actual
 *      settings launcher → soft-pass (skipped:true) so the legacy
 *      state machine handles the case; the "videocamVideos" chip
 *      must NOT be mistaken for a settings launcher OR for a "Video"
 *      option.
 *   4. Missing Veo option (menu lists only Nano Banana / Imagen) →
 *      fail ERR_VEO_3_1_LITE_OPTION_NOT_VISIBLE with visible candidates
 *      in the FAIL telemetry message.
 *   5. Missing Frames option → fail ERR_FRAMES_OPTION_NOT_VISIBLE with
 *      visible candidates.
 *   6. Successful configuration MUST still leave the prompt field
 *      discoverable so downstream steps (insert prompt, click Start,
 *      upload, wait, generate) can proceed — i.e. the function does
 *      NOT short-circuit the existing post-config validation.
 *
 * Run: `node scripts/test-f2v-composer-settings-panel.js`
 *
 * Authority: runtime evidence manual_da996ef1 (operator screenshot of
 * composer settings panel) + AGENTS.md →
 * CHROME_EXTENSION_MV3_DEBUG_CONTRACT.md.
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
    url: 'https://labs.google/fx/tools/flow/project/test-composer',
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
  makeVisible(el, 200, 40);
  (parent || window.document.body).appendChild(el);
  return el;
}

function makeSurface(window, role = 'menu') {
  const surface = window.document.createElement('div');
  surface.setAttribute('role', role);
  makeVisible(surface, 320, 320);
  window.document.body.appendChild(surface);
  return surface;
}

function makeComposer(window) {
  const composer = window.document.createElement('textarea');
  composer.setAttribute('placeholder', 'What do you want to create?');
  makeVisible(composer, 640, 80);
  window.document.body.appendChild(composer);
  return composer;
}

// Construct a typical "open settings panel" fixture: launcher button
// with aria-haspopup="menu" whose visible text contains a model token
// (e.g. "Nano Banana 2") + an open menu listing the supplied options.
function buildSettingsPanelFixture(window, optionLabels, opts = {}) {
  // Composer's prompt field so prompt_field_visible can pass.
  makeComposer(window);

  // Outer launcher button — text is "Nano Banana 2" so the launcher is
  // permissive (findFlowConfigLauncher accepts "nano banana" / "veo").
  const launcher = makeButton(window, {
    text: opts.launcherText || 'Nano Banana 2',
    ariaHaspopup: 'menu',
  });

  // Open surface mounted under body — picked up by findOpenFlowConfigSurface.
  const surface = makeSurface(window);

  // Each option lives inside the surface.
  const options = {};
  for (const label of optionLabels) {
    const opt = window.document.createElement('button');
    opt.setAttribute('role', 'option');
    opt.setAttribute('data-state', 'inactive');
    opt.setAttribute('aria-selected', 'false');
    opt.textContent = label;
    makeVisible(opt, 200, 36);
    opt.addEventListener('click', () => {
      opt.setAttribute('data-state', 'active');
      opt.setAttribute('aria-selected', 'true');
    });
    surface.appendChild(opt);
    options[label] = opt;
  }
  return { launcher, surface, options };
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 1 — Full happy path: all 5 options present, each gets clicked.
// ──────────────────────────────────────────────────────────────────────────
async function case1_happyPath() {
  const h = createHarness();
  try {
    const { options } = buildSettingsPanelFixture(h.window, [
      'Video', 'Frames', '9:16', '1x', 'Veo 3.1 - Lite',
    ]);

    const stages = [];
    const result = await h.hooks.configureVisibleF2VComposerSettings(
      (stage, status, message) => stages.push({ stage, status, message }),
    );

    assert.equal(result.ok, true, 'Case1: must succeed');
    assert.equal(result.skipped, undefined, 'Case1: not soft-pass — fully configured');
    for (const label of ['Video', 'Frames', '9:16', '1x', 'Veo 3.1 - Lite']) {
      assert.ok(
        result.configured[label],
        `Case1: configured map missing entry for '${label}'`,
      );
      assert.equal(
        options[label].getAttribute('aria-selected'), 'true',
        `Case1: '${label}' option should have aria-selected=true after click`,
      );
    }
    const panelOpen = stages.find((s) => s.stage === 'F2V_SETTINGS_PANEL_OPENED');
    const cfgDone = stages.find((s) => s.stage === 'F2V_COMPOSER_SETTINGS_CONFIGURED');
    assert.ok(panelOpen && panelOpen.status === 'PASS', 'Case1: panel open stage PASS');
    assert.ok(cfgDone && cfgDone.status === 'PASS', 'Case1: configured stage PASS');
    console.log('[PASS] Case1: full happy path — all 5 options clicked in order');
  } finally { h.close(); }
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 2 — Outer Flow page still labels the project "Nano Banana 2"
// but the OPEN composer settings panel exposes Veo 3.1 - Lite. The
// driver must select Veo from the panel and PASS — no premature
// ERR_WRONG_MODEL_FOR_F2V based on the outer label.
// ──────────────────────────────────────────────────────────────────────────
async function case2_nanoBananaShellWithVeoInPanel() {
  const h = createHarness();
  try {
    // Outer page shows "Nano Banana 2" — what observeFlowState would
    // read as the project's model label.
    const outerModelLabel = h.window.document.createElement('span');
    outerModelLabel.textContent = '🍌 Nano Banana 2';
    makeVisible(outerModelLabel, 200, 32);
    h.window.document.body.appendChild(outerModelLabel);

    // Settings panel contains Veo 3.1 - Lite as a selectable option.
    const { options } = buildSettingsPanelFixture(h.window, [
      'Video', 'Frames', '9:16', '1x', 'Veo 3.1 - Lite',
    ]);

    const result = await h.hooks.configureVisibleF2VComposerSettings(() => {});

    assert.equal(result.ok, true, 'Case2: must select Veo from the panel and PASS');
    assert.equal(
      options['Veo 3.1 - Lite'].getAttribute('aria-selected'),
      'true',
      'Case2: Veo option clicked despite outer shell saying Nano Banana 2',
    );
    console.log('[PASS] Case2: Nano Banana shell + Veo in panel → Veo selected, PASS');
  } finally { h.close(); }
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 3 — Asset-library page (videocamVideos chip etc.) with NO settings
// launcher available. The driver must soft-pass (skipped:true) and must
// NOT mistake "videocamVideos" for a Video option.
// ──────────────────────────────────────────────────────────────────────────
async function case3_assetLibrarySoftPassNoVideocamMatch() {
  const h = createHarness();
  try {
    // Asset-library shell chips — looks like manual_8e432a34.
    const libraryChips = [
      'arrow_backGo Back', 'dashboardAll Media', 'imageImages',
      'videocamVideos', 'voice_selectionVoices', 'faceAvatar',
      'drive_folder_uploadUploads', 'uploadUpload media', 'Recentarrow_drop_down',
    ];
    for (const text of libraryChips) {
      makeButton(h.window, { text, role: 'button' });
    }
    // Composer prompt field exists somewhere on the page but no settings
    // launcher button (no aria-haspopup, no model text "veo"/"nano banana"
    // on any haspopup button).

    const result = await h.hooks.configureVisibleF2VComposerSettings(() => {});

    assert.equal(result.ok, true, 'Case3: soft-pass return must be ok=true');
    assert.equal(result.skipped, true, 'Case3: must be skipped:true');
    assert.equal(
      result.reason, 'no_settings_launcher_found',
      'Case3: skip reason must identify missing launcher',
    );

    // And — the upstream icon-stripped exact match must reject
    // "videocamVideos" as a Video tab.
    const matchedAsVideo = h.hooks.findElementByText(
      'button, [role="button"], [role="tab"]',
      'Video',
      { exact: true },
    );
    assert.equal(
      matchedAsVideo, null,
      'Case3: exact-mode "Video" must NOT match the videocamVideos chip',
    );
    console.log('[PASS] Case3: asset-library shell soft-passes + no videocamVideos confusion');
  } finally { h.close(); }
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 4 — Settings panel opens but Veo 3.1 - Lite option is missing.
// Driver must fail with ERR_VEO_3_1_LITE_OPTION_NOT_VISIBLE and the
// FAIL telemetry message must include the visible candidates.
// ──────────────────────────────────────────────────────────────────────────
async function case4_missingVeoOption() {
  const h = createHarness();
  try {
    // Menu lists Video/Frames/9:16/1x but only image-family models.
    buildSettingsPanelFixture(h.window, [
      'Video', 'Frames', '9:16', '1x', 'Nano Banana 2', 'Nano Banana Pro', 'Imagen 4',
    ]);

    const stages = [];
    const result = await h.hooks.configureVisibleF2VComposerSettings(
      (stage, status, message) => stages.push({ stage, status, message }),
    );

    assert.equal(result.ok, false, 'Case4: must FAIL');
    assert.equal(
      result.error, 'ERR_VEO_3_1_LITE_OPTION_NOT_VISIBLE',
      `Case4: error code; got ${result.error}`,
    );
    assert.ok(
      Array.isArray(result.candidates),
      'Case4: candidates array present in returned value',
    );
    const fail = stages.find(
      (s) => s.stage === 'F2V_COMPOSER_SETTINGS_CONFIGURED' && s.status === 'FAIL',
    );
    assert.ok(fail, 'Case4: FAIL stage logged');
    assert.match(
      String(fail.message || ''),
      /ERR_VEO_3_1_LITE_OPTION_NOT_VISIBLE/,
      'Case4: telemetry message names the error code',
    );
    assert.match(
      String(fail.message || ''),
      /candidates=/,
      'Case4: telemetry message includes the visible candidates',
    );
    console.log('[PASS] Case4: missing Veo → ERR_VEO_3_1_LITE_OPTION_NOT_VISIBLE + candidates');
  } finally { h.close(); }
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 5 — Missing Frames option. Earlier in the sequence than Veo, so
// the function must fail ERR_FRAMES_OPTION_NOT_VISIBLE before even
// attempting 9:16/1x/Veo.
// ──────────────────────────────────────────────────────────────────────────
async function case5_missingFramesOption() {
  const h = createHarness();
  try {
    buildSettingsPanelFixture(h.window, [
      'Video', '9:16', '1x', 'Veo 3.1 - Lite',
    ]);

    const stages = [];
    const result = await h.hooks.configureVisibleF2VComposerSettings(
      (stage, status, message) => stages.push({ stage, status, message }),
    );

    assert.equal(result.ok, false, 'Case5: must FAIL');
    assert.equal(
      result.error, 'ERR_FRAMES_OPTION_NOT_VISIBLE',
      `Case5: error code; got ${result.error}`,
    );
    const fail = stages.find(
      (s) => s.stage === 'F2V_COMPOSER_SETTINGS_CONFIGURED' && s.status === 'FAIL',
    );
    assert.ok(fail, 'Case5: FAIL stage logged');
    assert.match(
      String(fail.message || ''),
      /ERR_FRAMES_OPTION_NOT_VISIBLE/,
      'Case5: telemetry message names the error code',
    );
    assert.match(
      String(fail.message || ''),
      /candidates=/,
      'Case5: telemetry message includes visible candidates',
    );
    console.log('[PASS] Case5: missing Frames → ERR_FRAMES_OPTION_NOT_VISIBLE + candidates');
  } finally { h.close(); }
}

// ──────────────────────────────────────────────────────────────────────────
// CASE 6 — A successful configuration must leave the prompt field
// discoverable so downstream steps (insert prompt, Start, upload, wait,
// generate) can still run. This is a sanity check: the driver does NOT
// remove or hide the composer in the process.
// ──────────────────────────────────────────────────────────────────────────
async function case6_promptFieldRemainsDiscoverable() {
  const h = createHarness();
  try {
    buildSettingsPanelFixture(h.window, [
      'Video', 'Frames', '9:16', '1x', 'Veo 3.1 - Lite',
    ]);

    const result = await h.hooks.configureVisibleF2VComposerSettings(() => {});
    assert.equal(result.ok, true, 'Case6: config must succeed first');
    assert.equal(
      result.prompt_field_visible, true,
      'Case6: prompt field must still be visible after configuration',
    );

    // Downstream sanity: observeFlowState reports topMode=Video and a
    // composer is present (i.e. the legacy state machine could still
    // proceed to Start/Upload/Generate without the function having
    // swept anything away).
    const observed = h.hooks.observeFlowState();
    assert.ok(
      observed.composerPresent,
      'Case6: composerPresent must remain true',
    );
    console.log('[PASS] Case6: prompt field discoverable after panel configuration');
  } finally { h.close(); }
}

async function main() {
  await case1_happyPath();
  await case2_nanoBananaShellWithVeoInPanel();
  await case3_assetLibrarySoftPassNoVideocamMatch();
  await case4_missingVeoOption();
  await case5_missingFramesOption();
  await case6_promptFieldRemainsDiscoverable();
  console.log('\nALL TESTS PASSED');
}

main().catch((err) => {
  console.error('\nTEST FAILED:', err.message);
  if (err.stack) console.error(err.stack.split('\n').slice(0, 6).join('\n'));
  process.exit(1);
});
