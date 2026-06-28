const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const SOURCE_PATH = path.join(__dirname, '..', 'extension', 'content-flow-dom.js');
const SOURCE_TEXT = fs.readFileSync(SOURCE_PATH, 'utf8');
const ONE_PIXEL_PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9p8Jr0YAAAAASUVORK5CYII=';

function defineRect(node, width = 240, height = 80) {
  Object.defineProperty(node, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: width,
      bottom: height,
      width,
      height,
      toJSON() {
        return { width, height };
      },
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

function appendPreview(window, slotContainer, identity) {
  const img = window.document.createElement('img');
  img.src = `https://example.test/${identity}.png`;
  Object.defineProperty(img, 'currentSrc', { configurable: true, value: img.src });
  Object.defineProperty(img, 'naturalWidth', { configurable: true, value: 96 });
  Object.defineProperty(img, 'naturalHeight', { configurable: true, value: 96 });
  makeVisible(img, 96, 96);
  slotContainer.appendChild(img);
  return img;
}

function getPreviewState(slotContainer) {
  const previews = Array.from(slotContainer.querySelectorAll('img, canvas, video, picture, [style*="background-image"]'));
  return {
    previewFound: previews.length > 0,
    previewCount: previews.length,
    previewKey: previews.map((node) => node.currentSrc || node.src || node.getAttribute('src') || node.tagName).join('|') || 'none',
  };
}

function parseDetail(detail) {
  if (!detail || typeof detail !== 'string') return null;
  const separator = ' — ';
  const index = detail.indexOf(separator);
  if (index === -1) return null;
  try {
    return JSON.parse(detail.slice(index + separator.length));
  } catch (_error) {
    return null;
  }
}

function buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview }) {
  const detail = parseDetail(result?.detail);
  const targetFound = Boolean(
    modalInfo?.targets?.dispatchTarget
    || detail?.file_input_found
    || detail?.dropzone_found
  );
  const targetType = modalInfo?.targets?.fileInput
    ? 'file-input'
    : modalInfo?.targets?.dropzoneTarget
      ? 'dropzone'
      : modalInfo?.targets?.buttonTarget
        ? 'button'
        : modalInfo?.targets?.labelTarget
          ? 'label'
          : detail?.file_input_found
            ? 'file-input'
            : detail?.dropzone_found
              ? 'dropzone-or-button'
              : 'none';

  return {
    modal_found: Boolean(modalInfo?.modal ?? detail?.modal_found),
    shadow_root_found: Boolean(modalInfo?.foundInShadowRoot ?? detail?.open_shadow_root_found),
    target_found: targetFound,
    target_type: targetType,
    start_preview_before: beforePreview,
    start_preview_after: afterPreview,
    accepted_reason: result?.acceptanceReason || result?.reason || null,
    error_code: result?.error || null,
  };
}

function fail(message, diagnostics) {
  const error = new Error(message);
  error.diagnostics = diagnostics;
  throw error;
}

function expect(condition, message, diagnostics) {
  if (!condition) {
    fail(message, diagnostics);
  }
}

function installDomPolyfills(window) {
  window.__FLOWKIT_TEST_MODE__ = true;
  window.__FLOWKIT_ENABLE_TEST_HOOKS__ = true;
  window.fetch = global.fetch.bind(global);
  window.File = global.File;
  window.Blob = global.Blob;
  window.PointerEvent = window.PointerEvent || window.MouseEvent;

  if (!window.CSS) {
    window.CSS = {};
  }
  if (!window.CSS.escape) {
    window.CSS.escape = (value) => String(value).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  }

  if (!Object.getOwnPropertyDescriptor(window.HTMLElement.prototype, 'innerText')) {
    Object.defineProperty(window.HTMLElement.prototype, 'innerText', {
      configurable: true,
      get() {
        return this.textContent || '';
      },
      set(value) {
        this.textContent = value;
      },
    });
  }

  class TestDataTransfer {
    constructor() {
      this._files = [];
      this.items = {
        add: (file) => {
          this._files.push(file);
          this.files = this._toFileList();
          return file;
        },
      };
      this.files = this._toFileList();
    }

    _toFileList() {
      const files = this._files.slice();
      files.item = (index) => files[index] || null;
      return files;
    }
  }

  class TestDragEvent extends window.Event {
    constructor(type, init = {}) {
      super(type, init);
      this.dataTransfer = init.dataTransfer || null;
    }
  }

  window.DataTransfer = TestDataTransfer;
  window.DragEvent = TestDragEvent;
  window.chrome = {
    runtime: {
      lastError: null,
      onMessage: {
        addListener() {},
        removeListener() {},
      },
      sendMessage(_payload, callback) {
        if (typeof callback === 'function') {
          callback({ ok: true });
        }
      },
    },
  };
}

function createHarness() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'https://labs.google/fx/tools/flow',
    pretendToBeVisual: true,
    runScripts: 'outside-only',
  });
  const { window } = dom;
  installDomPolyfills(window);
  makeVisible(window.document.body, 1280, 720);
  window.eval(SOURCE_TEXT);
  const hooks = window.__FLOWKIT_TEST_HOOKS__;
  assert.ok(hooks, 'Expected __FLOWKIT_TEST_HOOKS__ to be defined in test mode');
  return {
    window,
    document: window.document,
    hooks,
    close() {
      window.close();
    },
  };
}

function makeVisibleAt(node, left, top, width = 240, height = 40) {
  node.style.display = 'block';
  node.style.visibility = 'visible';
  node.style.opacity = '1';
  Object.defineProperty(node, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({
      x: left,
      y: top,
      top,
      left,
      right: left + width,
      bottom: top + height,
      width,
      height,
      toJSON() {
        return { x: left, y: top, width, height };
      },
    }),
  });
  return node;
}

function createRuntimeMessageHarness(html) {
  const dom = new JSDOM(html, {
    url: 'https://labs.google/fx/tools/flow/project/test',
    pretendToBeVisual: true,
    runScripts: 'outside-only',
  });
  const { window } = dom;
  installDomPolyfills(window);
  window.__FLOWKIT_TEST_MODE__ = false;
  window.__FLOWKIT_ENABLE_TEST_HOOKS__ = false;
  let runtimeListener = null;
  window.chrome.runtime.onMessage.addListener = (listener) => {
    runtimeListener = listener;
  };
  makeVisibleAt(window.document.body, 0, 0, 1280, 900);
  window.eval(SOURCE_TEXT);
  assert.equal(typeof runtimeListener, 'function', 'Expected production runtime listener');
  return {
    window,
    document: window.document,
    async send(message) {
      return await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error(`Timed out waiting for ${message.type}`)), 8000);
        const returned = runtimeListener(message, {}, (response) => {
          clearTimeout(timer);
          resolve(response);
        });
        if (returned !== true && returned !== false && returned !== undefined) {
          clearTimeout(timer);
          reject(new Error(`Unexpected listener return: ${String(returned)}`));
        }
      });
    },
    close() {
      window.close();
    },
  };
}

function createStartSlot(window, options = {}) {
  const { withInput = false } = options;
  const slotButton = window.document.createElement('button');
  slotButton.type = 'button';
  slotButton.textContent = 'Start Upload image';
  makeVisible(slotButton, 280, 120);

  if (withInput) {
    const input = window.document.createElement('input');
    input.type = 'file';
    makeVisible(input, 40, 40);
    slotButton.appendChild(input);
  }

  window.document.body.appendChild(slotButton);
  return slotButton;
}

function createComposerWithDistractor(window) {
  const sidebarButton = window.document.createElement('button');
  sidebarButton.type = 'button';
  sidebarButton.textContent = 'Create Tool';
  makeVisible(sidebarButton, 220, 56);
  window.document.body.appendChild(sidebarButton);

  const dock = window.document.createElement('div');
  makeVisible(dock, 720, 120);
  dock.style.position = 'absolute';
  dock.style.left = '520px';
  dock.style.top = '540px';

  const composer = window.document.createElement('div');
  composer.setAttribute('contenteditable', 'true');
  composer.setAttribute('aria-label', 'Editable text');
  composer.textContent = 'What do you want to create?';
  makeVisible(composer, 420, 72);
  dock.appendChild(composer);

  const createButton = window.document.createElement('button');
  createButton.type = 'button';
  createButton.textContent = 'arrow_forwardCreate';
  makeVisible(createButton, 120, 56);
  dock.appendChild(createButton);

  window.document.body.appendChild(dock);
  return { sidebarButton, dock, composer, createButton };
}

function createModal(window, { useInput = false, useDropzone = false, inShadowRoot = false } = {}) {
  const buildSurface = (root) => {
    const modal = root.createElement('div');
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.textContent = 'Upload image Search for Assets Recent';
    makeVisible(modal, 420, 260);

    let input = null;
    let dropzone = null;
    if (useInput) {
      input = root.createElement('input');
      input.type = 'file';
      input.setAttribute('aria-label', 'Upload image');
      makeVisible(input, 60, 40);
      modal.appendChild(input);
    }
    if (useDropzone) {
      dropzone = root.createElement('div');
      dropzone.className = 'dropzone';
      dropzone.textContent = 'Upload image';
      makeVisible(dropzone, 220, 160);
      modal.appendChild(dropzone);
    }
    return { modal, input, dropzone };
  };

  if (!inShadowRoot) {
    const surface = buildSurface(window.document);
    window.document.body.appendChild(surface.modal);
    return { ...surface, host: null, shadowRoot: null };
  }

  const host = window.document.createElement('div');
  host.setAttribute('data-test-host', 'asset-picker');
  makeVisible(host, 500, 300);
  window.document.body.appendChild(host);
  const shadowRoot = host.attachShadow({ mode: 'open' });
  const surface = buildSurface(window.document);
  makeVisible(surface.modal, 420, 260);
  shadowRoot.appendChild(surface.modal);
  return { ...surface, host, shadowRoot };
}

async function runDirectSlotFallbackTest() {
  const harness = createHarness();
  const { window, hooks } = harness;

  try {
    const slot = createStartSlot(window, { withInput: true });
    const input = slot.querySelector('input[type="file"]');
    const beforePreview = getPreviewState(slot);
    let previewAddedAt = 0;

    input.addEventListener('change', () => {
      window.setTimeout(() => {
        previewAddedAt = Date.now();
        appendPreview(window, slot, 'direct-slot-preview');
      }, 40);
    });

    const modalInfo = hooks.findVisibleAssetPickerModal();
    expect(!modalInfo.modal, 'Did not expect modal for direct slot fallback', buildFailureDiagnostics({ modalInfo, result: null, beforePreview, afterPreview: beforePreview }));

    const result = await hooks.simulateFileUpload('Start', { previewUrl: ONE_PIXEL_PNG, fileName: 'direct.png' });
    const afterPreview = getPreviewState(slot);

    expect(result.ok, 'Direct slot fallback should succeed after Start preview changes', buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview }));
    expect(result.acceptanceReason === 'start-slot-preview', `Expected start-slot-preview acceptance, got ${result.acceptanceReason}`, buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview }));
    expect(previewAddedAt > 0, 'Expected preview to be added during direct slot fallback', buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview }));
    expect(afterPreview.previewFound && afterPreview.previewKey !== beforePreview.previewKey, 'Expected Start slot preview to change before PASS', buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview }));
  } finally {
    harness.close();
  }
}

async function runModalInputTest() {
  const harness = createHarness();
  const { window, hooks } = harness;

  try {
    const slot = createStartSlot(window, { withInput: false });
    let modalSurface = null;
    let inputEvents = 0;
    let changeEvents = 0;
    let previewAddedAt = 0;

    const openModal = () => {
      if (modalSurface?.modal?.isConnected) return modalSurface;
      modalSurface = createModal(window, { useInput: true });
      modalSurface.input.addEventListener('input', () => {
        inputEvents += 1;
      });
      modalSurface.input.addEventListener('change', () => {
        changeEvents += 1;
        window.setTimeout(() => {
          previewAddedAt = Date.now();
          appendPreview(window, slot, 'modal-input-preview');
        }, 40);
      });
      return modalSurface;
    };

    slot.addEventListener('click', openModal);
    slot.click();
    const modalInfo = await hooks.waitForAssetPickerModal(150);
    const beforePreview = getPreviewState(slot);

    expect(Boolean(modalInfo.modal), 'Expected visible asset picker modal with file input', buildFailureDiagnostics({ modalInfo, result: null, beforePreview, afterPreview: beforePreview }));
    expect(Boolean(modalInfo.targets?.fileInput), 'Expected modal file input target', buildFailureDiagnostics({ modalInfo, result: null, beforePreview, afterPreview: beforePreview }));

    const result = await hooks.simulateFileUpload('Start', { previewUrl: ONE_PIXEL_PNG, fileName: 'modal-input.png' });
    const afterPreview = getPreviewState(slot);

    expect(result.ok, 'Modal file input upload should succeed', buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview }));
    expect(inputEvents >= 1 && changeEvents >= 1, 'Expected input and change events on modal file input', buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview }));
    expect(previewAddedAt > 0, 'Expected Start slot preview change before modal PASS', buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview }));
    expect(afterPreview.previewFound && afterPreview.previewKey !== beforePreview.previewKey, 'Expected Start slot preview to change before modal PASS', buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview }));
  } finally {
    harness.close();
  }
}

async function runModalDropzoneTest() {
  const harness = createHarness();
  const { window, hooks } = harness;

  try {
    const slot = createStartSlot(window, { withInput: false });
    const slotDropCounts = { dragenter: 0, dragover: 0, drop: 0 };
    for (const eventName of Object.keys(slotDropCounts)) {
      slot.addEventListener(eventName, () => {
        slotDropCounts[eventName] += 1;
      });
    }

    let modalSurface = null;
    const dropzoneCounts = { dragenter: 0, dragover: 0, drop: 0 };
    const openModal = () => {
      if (modalSurface?.modal?.isConnected) return modalSurface;
      modalSurface = createModal(window, { useDropzone: true });
      for (const eventName of Object.keys(dropzoneCounts)) {
        modalSurface.dropzone.addEventListener(eventName, () => {
          dropzoneCounts[eventName] += 1;
          if (eventName === 'drop') {
            window.setTimeout(() => {
              appendPreview(window, slot, 'modal-dropzone-preview');
            }, 40);
          }
        });
      }
      return modalSurface;
    };

    slot.addEventListener('click', openModal);
    slot.click();
    const modalInfo = await hooks.waitForAssetPickerModal(150);
    const beforePreview = getPreviewState(slot);
    const result = await hooks.simulateFileUpload('Start', { previewUrl: ONE_PIXEL_PNG, fileName: 'modal-dropzone.png' });
    const afterPreview = getPreviewState(slot);

    expect(result.ok, 'Modal dropzone upload should succeed', buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview }));
    expect(dropzoneCounts.dragenter === 1 && dropzoneCounts.dragover === 1 && dropzoneCounts.drop === 1, 'Expected dragenter/dragover/drop on modal dropzone', buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview }));
    expect(slotDropCounts.drop === 0, 'Expected Start slot fallback target not to receive drop events', buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview }));
  } finally {
    harness.close();
  }
}

async function runShadowRootModalTest() {
  const harness = createHarness();
  const { window, hooks } = harness;

  try {
    const slot = createStartSlot(window, { withInput: false });
    let modalSurface = null;
    const openModal = () => {
      if (modalSurface?.modal?.isConnected) return modalSurface;
      modalSurface = createModal(window, { useInput: true, inShadowRoot: true });
      modalSurface.input.addEventListener('change', () => {
        window.setTimeout(() => {
          appendPreview(window, slot, 'shadow-root-preview');
        }, 40);
      });
      return modalSurface;
    };

    slot.addEventListener('click', openModal);
    slot.click();
    const modalInfo = await hooks.waitForAssetPickerModal(150);
    const beforePreview = getPreviewState(slot);

    expect(Boolean(modalInfo.modal), 'Expected asset picker modal in open shadow root', buildFailureDiagnostics({ modalInfo, result: null, beforePreview, afterPreview: beforePreview }));
    expect(Boolean(modalInfo.foundInShadowRoot), 'Expected modal detection to report open shadow root', buildFailureDiagnostics({ modalInfo, result: null, beforePreview, afterPreview: beforePreview }));
    expect(modalInfo.targets?.fileInput?.getRootNode() === modalSurface.shadowRoot, 'Expected file input target to resolve inside shadow root', buildFailureDiagnostics({ modalInfo, result: null, beforePreview, afterPreview: beforePreview }));

    const result = await hooks.simulateFileUpload('Start', { previewUrl: ONE_PIXEL_PNG, fileName: 'shadow-root.png' });
    const afterPreview = getPreviewState(slot);
    expect(result.ok, 'Open shadow root modal upload should succeed', buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview }));
  } finally {
    harness.close();
  }
}

async function runWeakAcceptanceRejectionTest() {
  const harness = createHarness();
  const { window, hooks, document } = harness;

  try {
    const slot = createStartSlot(window, { withInput: false });
    let modalSurface = null;
    const openModal = () => {
      if (modalSurface?.modal?.isConnected) return modalSurface;
      modalSurface = createModal(window, { useInput: true });
      modalSurface.input.addEventListener('change', () => {
        window.setTimeout(() => {
          const outsidePreview = document.createElement('img');
          outsidePreview.src = 'https://example.test/outside-preview.png';
          Object.defineProperty(outsidePreview, 'naturalWidth', { configurable: true, value: 96 });
          Object.defineProperty(outsidePreview, 'naturalHeight', { configurable: true, value: 96 });
          makeVisible(outsidePreview, 96, 96);
          document.body.appendChild(outsidePreview);
          modalSurface.modal.remove();
        }, 40);
      });
      return modalSurface;
    };

    slot.addEventListener('click', openModal);
    slot.click();
    const modalInfo = await hooks.waitForAssetPickerModal(150);
    const beforePreview = getPreviewState(slot);
    const result = await hooks.simulateFileUpload('Start', { previewUrl: ONE_PIXEL_PNG, fileName: 'weak-reject.png' });
    const afterPreview = getPreviewState(slot);

    expect(!result.ok, 'Weak acceptance path must fail without Start slot preview change', buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview }));
    expect(result.error === 'ERR_START_ASSET_PICKER_ACCEPTANCE_NOT_VERIFIED', `Expected acceptance rejection error, got ${result.error}`, buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview }));
  } finally {
    harness.close();
  }
}

async function runTimeoutPathTest() {
  const harness = createHarness();
  const { window, hooks } = harness;

  try {
    const slot = createStartSlot(window, { withInput: false });
    let modalSurface = null;
    const openModal = () => {
      if (modalSurface?.modal?.isConnected) return modalSurface;
      modalSurface = createModal(window, { useInput: true });
      return modalSurface;
    };

    slot.addEventListener('click', openModal);
    slot.click();
    const modalInfo = await hooks.waitForAssetPickerModal(150);
    const beforePreview = getPreviewState(slot);
    const result = await hooks.simulateFileUpload('Start', { previewUrl: ONE_PIXEL_PNG, fileName: 'timeout-path.png' });
    const afterPreview = getPreviewState(slot);

    expect(!result.ok, 'Timeout path must fail when Start slot preview never appears', buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview }));
    expect(
      result.error === 'ERR_START_ASSET_PICKER_ACCEPTANCE_NOT_VERIFIED' || result.error === 'ERR_START_ASSET_PICKER_UPLOAD_FAILED',
      `Expected timeout-path asset picker error, got ${result.error}`,
      buildFailureDiagnostics({ modalInfo, result, beforePreview, afterPreview })
    );
  } finally {
    harness.close();
  }
}

async function runComposerGenerateTargetingTest() {
  const harness = createHarness();
  const { window, hooks } = harness;

  try {
    const { sidebarButton, createButton } = createComposerWithDistractor(window);
    const resolved = hooks.findGenerateButtonNearComposer();
    expect(Boolean(resolved), 'Expected generate button to resolve near composer', {
      resolved_text: resolved?.textContent || null,
    });
    expect(resolved === createButton, 'Expected composer create button to win over Create Tool distractor', {
      resolved_text: resolved?.textContent || null,
      distractor_text: sidebarButton.textContent,
      expected_text: createButton.textContent,
    });
  } finally {
    harness.close();
  }
}

async function runDiagnosticPingHeaderTest() {
  const harness = createHarness();
  const { hooks } = harness;

  try {
    const payload = hooks.buildDiagnosticPingResponse();
    expect(payload?.ok === true, 'Expected diagnostic ping payload to report ok=true', payload);
    expect(payload?.runtime_ready === true, 'Expected diagnostic ping payload to report runtime_ready=true', payload);
    expect(typeof payload?.content_build_id === 'string' && payload.content_build_id.length > 0, 'Expected non-empty content_build_id', payload);
    expect(payload?.git_sha === payload?.content_build_id, 'Expected git_sha to align with content_build_id build stamp', payload);
  } finally {
    harness.close();
  }
}

async function runAgentSettingsSaveTransitionTest() {
  const harness = createRuntimeMessageHarness(`
    <!doctype html>
    <html>
      <body>
        <button id="settings-launcher" type="button" aria-label="tune">tune</button>
        <form id="composer">
          <textarea id="prompt" placeholder="What do you want to create?">hero product shot</textarea>
          <button id="submit" type="button"><span>arrow_forward</span></button>
        </form>
      </body>
    </html>
  `);
  const { document, window } = harness;
  try {
    const launcher = document.getElementById('settings-launcher');
    const composer = document.getElementById('composer');
    const prompt = document.getElementById('prompt');
    const submit = document.getElementById('submit');
    makeVisibleAt(launcher, 900, 820, 40, 32);
    makeVisibleAt(composer, 700, 700, 520, 180);
    makeVisibleAt(prompt, 740, 760, 390, 50);
    makeVisibleAt(submit, 1140, 820, 40, 32);
    let saveClicks = 0;

    launcher.addEventListener('click', () => {
      if (document.getElementById('agent-settings')) return;
      const panel = document.createElement('div');
      panel.id = 'agent-settings';
      panel.setAttribute('role', 'dialog');
      panel.innerHTML = `
        <h2 id="agent-title">Agent settings</h2>
        <div id="confirm">Confirm before generating</div>
        <button id="never-radio" type="button" role="radio">Never Agent will generate media and spend credits automatically</button>
        <div id="video-label">Video generation default</div>
        <button id="ratio" type="button" aria-pressed="true">9:16</button>
        <button id="count" type="button" aria-pressed="true">1x</button>
        <button id="model" type="button">Veo 3.1 - Lite</button>
        <button id="save" type="button">Save</button>
      `;
      document.body.appendChild(panel);
      makeVisibleAt(panel, 900, 80, 320, 620);
      makeVisibleAt(document.getElementById('agent-title'), 930, 100, 180, 30);
      makeVisibleAt(document.getElementById('confirm'), 930, 150, 220, 30);
      makeVisibleAt(document.getElementById('never-radio'), 930, 190, 250, 45);
      makeVisibleAt(document.getElementById('video-label'), 930, 300, 220, 30);
      makeVisibleAt(document.getElementById('ratio'), 930, 350, 80, 32);
      makeVisibleAt(document.getElementById('count'), 930, 400, 80, 32);
      makeVisibleAt(document.getElementById('model'), 930, 450, 180, 32);
      const save = document.getElementById('save');
      makeVisibleAt(save, 930, 620, 240, 36);
      save.addEventListener('click', () => {
        saveClicks += 1;
        panel.remove();
        prompt.disabled = false;
      });
    });

    const result = await harness.send({
      type: 'GFV2_APPLY_SETTINGS',
      options: {
        panelWaitMs: 0,
        requireSaveTransition: true,
        expectedPrompt: 'hero product shot',
      },
    });
    assert.equal(saveClicks, 1, 'Save must receive exactly one click');
    assert.equal(result.settings_transition_verified, true);
    assert.equal(result.agent_settings_active_after_save, false);
    assert.equal(result.composer_editable_after_save, true);
    assert.equal(result.prompt_reflected_after_save, true);
    assert.equal(result.settings_saved_or_persisted, true);
    assert.equal(window.document.getElementById('agent-settings'), null);
  } finally {
    harness.close();
  }
}

async function main() {
  const tests = [
    ['Direct slot fallback', runDirectSlotFallbackTest],
    ['Modal with visible input', runModalInputTest],
    ['Modal with dropzone only', runModalDropzoneTest],
    ['Open shadow root modal', runShadowRootModalTest],
    ['Weak acceptance rejection', runWeakAcceptanceRejectionTest],
    ['Timeout path', runTimeoutPathTest],
    ['Composer generate targeting', runComposerGenerateTargetingTest],
    ['Diagnostic ping header', runDiagnosticPingHeaderTest],
    ['Agent settings Save transition', runAgentSettingsSaveTransitionTest],
  ];

  let failures = 0;
  for (const [name, testFn] of tests) {
    try {
      await testFn();
      console.log(`PASS ${name}`);
    } catch (error) {
      failures += 1;
      console.error(`FAIL ${name}`);
      if (error.diagnostics) {
        console.error(JSON.stringify(error.diagnostics, null, 2));
      }
      console.error(error.stack || String(error));
    }
  }

  if (failures > 0) {
    throw new Error(`Harness failed with ${failures} failing case(s)`);
  }

  console.log(`PASS All ${tests.length} asset picker fixture cases`);
}

main().catch((error) => {
  console.error(error.stack || String(error));
  process.exitCode = 1;
});
