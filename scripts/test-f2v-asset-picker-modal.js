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

  const runtimeMessageListeners = new Set();
  let runtimeSendMessageHandler = null;

  window.DataTransfer = TestDataTransfer;
  window.DragEvent = TestDragEvent;
  window.__setRuntimeSendMessageHandler = (handler) => {
    runtimeSendMessageHandler = handler;
  };
  window.chrome = {
    runtime: {
      lastError: null,
      onMessage: {
        addListener(listener) {
          runtimeMessageListeners.add(listener);
        },
        removeListener(listener) {
          runtimeMessageListeners.delete(listener);
        },
      },
      sendMessage(payload, callback) {
        window.chrome.runtime.lastError = null;
        if (typeof runtimeSendMessageHandler === 'function') {
          runtimeSendMessageHandler(payload, callback, {
            emit(message) {
              for (const listener of Array.from(runtimeMessageListeners)) {
                listener(message, {}, () => {});
              }
            },
            setLastError(message) {
              window.chrome.runtime.lastError = message ? { message } : null;
            },
          });
          return;
        }
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
    setRuntimeSendMessageHandler(handler) {
      window.__setRuntimeSendMessageHandler(handler);
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

function createWrappedVideoTab(window, options = {}) {
  const { active = false } = options;
  const wrapper = window.document.createElement('div');
  wrapper.className = 'sc-ff810a41-13 kiJefd';
  makeVisible(wrapper, 260, 96);

  const button = window.document.createElement('button');
  button.type = 'button';
  button.className = 'sc-ff810a41-20 gkRFpV';
  button.setAttribute('role', 'tab');
  button.setAttribute('data-state', active ? 'active' : 'inactive');
  button.setAttribute('aria-selected', active ? 'true' : 'false');
  makeVisible(button, 220, 72);

  const inner = window.document.createElement('div');
  inner.className = 'sc-ff810a41-15 jJqNzM';
  makeVisible(inner, 200, 56);

  const heading = window.document.createElement('h4');
  heading.className = 'sc-ff810a41-18 fTNhnS';
  heading.textContent = 'Video';
  makeVisible(heading, 160, 32);

  inner.appendChild(heading);
  button.appendChild(inner);
  wrapper.appendChild(button);
  window.document.body.appendChild(wrapper);

  return { wrapper, button, inner, heading };
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

async function runFindElementByTextPrefersNestedInteractiveControlTest() {
  const harness = createHarness();
  const { window, hooks } = harness;

  try {
    const { wrapper, button } = createWrappedVideoTab(window, { active: true });
    const resolved = hooks.findElementByText('button, [role="tab"], [role="button"], span, div', 'Video');
    expect(Boolean(resolved), 'Expected Video element to resolve', { resolved: resolved?.outerHTML || null });
    expect(resolved === button, 'Expected wrapped Video label search to resolve to interactive tab button, not wrapper div', {
      resolved_outer_html: resolved?.outerHTML || null,
      wrapper_outer_html: wrapper.outerHTML,
      button_outer_html: button.outerHTML,
    });
  } finally {
    harness.close();
  }
}

async function runIsSelectedControlUsesInteractiveDescendantStateTest() {
  const harness = createHarness();
  const { window, hooks } = harness;

  try {
    const { wrapper } = createWrappedVideoTab(window, { active: true });
    const selected = hooks.isSelectedControl(wrapper, 'Video');
    expect(selected === true, 'Expected selected-state detection to climb into interactive Video tab descendant', {
      wrapper_outer_html: wrapper.outerHTML,
    });
  } finally {
    harness.close();
  }
}

async function runVerifyFlowModeAllowsUnknownF2VModelTest() {
  const harness = createHarness();
  const { hooks } = harness;

  try {
    const result = hooks.verifyFlowMode(
      { mode: 'F2V' },
      {
        topMode: 'Video',
        subMode: 'Frames',
        model: 'UNKNOWN',
        aspectRatio: 'UNKNOWN',
        count: 'UNKNOWN',
        visibleUploadSlots: ['Start', 'End'],
        visibleAssetPreviews: [],
        composerPresent: true,
        generateButtonState: 'enabled',
      },
    );
    expect(result?.ok === true, 'Expected F2V verifyFlowMode to allow UNKNOWN visible model text when video workspace is otherwise valid', result);
  } finally {
    harness.close();
  }
}

async function runVerifyFlowModeRejectsNanoBananaOnF2VTest() {
  const harness = createHarness();
  const { hooks } = harness;

  try {
    const result = hooks.verifyFlowMode(
      { mode: 'F2V' },
      {
        topMode: 'Video',
        subMode: 'Frames',
        model: 'Nano Banana 2',
        aspectRatio: 'UNKNOWN',
        count: 'UNKNOWN',
        visibleUploadSlots: ['Start', 'End'],
        visibleAssetPreviews: [],
        composerPresent: true,
        generateButtonState: 'enabled',
      },
    );
    expect(result?.ok === false, 'Expected F2V verifyFlowMode to reject explicit Nano Banana image model', result);
    expect(
      String(result?.reason || '').includes('image model'),
      `Expected explicit image-model rejection reason, got ${result?.reason}`,
      result,
    );
  } finally {
    harness.close();
  }
}

async function runGetRequiredAssetSlotsF2VStartOnlyTest() {
  const harness = createHarness();
  const { hooks } = harness;

  try {
    const slots = hooks.getRequiredAssetSlots({ mode: 'F2V', productId: 'product-only-source' });
    expect(Array.isArray(slots), 'Expected required slots result to be an array', { slots });
    expect(slots.length === 1 && slots[0] === 'Start', 'Expected F2V product-only job to require Start only', { slots });
  } finally {
    harness.close();
  }
}

async function runGetRequiredAssetSlotsF2VStartAndEndTest() {
  const harness = createHarness();
  const { hooks } = harness;

  try {
    const slots = hooks.getRequiredAssetSlots({ mode: 'F2V', startImageMediaId: 'start-1', endImageMediaId: 'end-1' });
    expect(slots.length === 2, 'Expected explicit end-image F2V job to require two slots', { slots });
    expect(slots[0] === 'Start' && slots[1] === 'End', 'Expected F2V explicit end-image job to require Start and End in order', { slots });
  } finally {
    harness.close();
  }
}

async function runVerifyFlowModeRejectsWrongRatioOnF2VTest() {
  const harness = createHarness();
  const { hooks } = harness;

  try {
    const result = hooks.verifyFlowMode(
      { mode: 'F2V', orientation: 'VERTICAL' },
      {
        topMode: 'Video',
        subMode: 'Frames',
        model: 'Veo 3.1 - Lite',
        aspectRatio: '16:9',
        count: '1x',
        visibleUploadSlots: ['Start', 'End'],
        visibleAssetPreviews: [],
        composerPresent: true,
        generateButtonState: 'enabled',
      },
    );
    expect(result?.ok === false, 'Expected F2V verifyFlowMode to reject wrong visible aspect ratio', result);
    expect(result?.error === 'ERR_ASPECT_9_16_NOT_SELECTED', `Expected explicit aspect error, got ${result?.error}`, result);
  } finally {
    harness.close();
  }
}

async function runVerifyFlowModeRejectsWrongCountOnF2VTest() {
  const harness = createHarness();
  const { hooks } = harness;

  try {
    const result = hooks.verifyFlowMode(
      { mode: 'F2V', count: '1x' },
      {
        topMode: 'Video',
        subMode: 'Frames',
        model: 'Veo 3.1 - Lite',
        aspectRatio: '9:16',
        count: '2x',
        visibleUploadSlots: ['Start', 'End'],
        visibleAssetPreviews: [],
        composerPresent: true,
        generateButtonState: 'enabled',
      },
    );
    expect(result?.ok === false, 'Expected F2V verifyFlowMode to reject wrong visible count', result);
    expect(result?.error === 'ERR_COUNT_1X_NOT_SELECTED', `Expected explicit count error, got ${result?.error}`, result);
  } finally {
    harness.close();
  }
}

async function runVerifyFlowModeRejectsWrongModelOnF2VTest() {
  const harness = createHarness();
  const { hooks } = harness;

  try {
    const result = hooks.verifyFlowMode(
      { mode: 'F2V', modelLabel: 'Veo 3.1 - Lite' },
      {
        topMode: 'Video',
        subMode: 'Frames',
        model: 'Veo 3 Fast',
        aspectRatio: '9:16',
        count: '1x',
        visibleUploadSlots: ['Start', 'End'],
        visibleAssetPreviews: [],
        composerPresent: true,
        generateButtonState: 'enabled',
      },
    );
    expect(result?.ok === false, 'Expected F2V verifyFlowMode to reject wrong visible model', result);
    expect(result?.error === 'ERR_WRONG_MODEL_FOR_F2V', `Expected explicit model error, got ${result?.error}`, result);
  } finally {
    harness.close();
  }
}

async function runVerifyFlowModeRejectsMissingStartSlotOnF2VTest() {
  const harness = createHarness();
  const { hooks } = harness;

  try {
    const result = hooks.verifyFlowMode(
      { mode: 'F2V' },
      {
        topMode: 'Video',
        subMode: 'Frames',
        model: 'Veo 3.1 - Lite',
        aspectRatio: '9:16',
        count: '1x',
        visibleUploadSlots: ['End'],
        visibleAssetPreviews: [],
        composerPresent: true,
        generateButtonState: 'enabled',
      },
    );
    expect(result?.ok === false, 'Expected F2V verifyFlowMode to reject missing Start slot', result);
    expect(result?.error === 'ERR_START_FRAME_REQUIRED_MISSING', `Expected explicit Start-slot error, got ${result?.error}`, result);
  } finally {
    harness.close();
  }
}

async function runSendRuntimeMessageNoThrowIsOneWayTest() {
  const harness = createHarness();
  const { hooks, setRuntimeSendMessageHandler } = harness;

  try {
    let observedCallbackType = 'missing';
    setRuntimeSendMessageHandler((_payload, callback) => {
      observedCallbackType = typeof callback;
    });
    hooks.sendRuntimeMessageNoThrow({ type: 'FLOW_STAGE_EVENT', stage: 'TEST', status: 'PASS' });
    expect(observedCallbackType === 'undefined', 'Expected fire-and-forget runtime telemetry to omit callback response lane', {
      observedCallbackType,
    });
  } finally {
    harness.close();
  }
}

async function runBackgroundProxyAckAndResultTest() {
  const harness = createHarness();
  const { hooks, setRuntimeSendMessageHandler } = harness;

  try {
    setRuntimeSendMessageHandler((payload, callback, runtime) => {
      if (payload?.type !== 'RESOLVE_LOCAL_ASSET') {
        callback?.({ ok: false, error: 'UNEXPECTED_PAYLOAD' });
        return;
      }
      callback?.({
        ok: true,
        accepted: true,
        proxy_request_id: payload.proxy_request_id,
      });
      setTimeout(() => {
        runtime.emit({
          type: 'RESOLVE_LOCAL_ASSET_RESULT',
          proxy_request_id: payload.proxy_request_id,
          ok: true,
          dataUrl: ONE_PIXEL_PNG,
          mimeType: 'image/png',
          filename: payload.filename,
        });
      }, 10);
    });

    const result = await hooks.resolveLocalAssetViaBackgroundProxy(
      'asset-123',
      'asset-123.jpg',
      'request-123',
      250,
    );
    expect(result?.ok === true, 'Expected proxy helper to resolve successful detached result', result);
    expect(result?.filename === 'asset-123.jpg', 'Expected detached result filename to round-trip', result);
    expect(result?.dataUrl === ONE_PIXEL_PNG, 'Expected detached result dataUrl to round-trip', result);
  } finally {
    harness.close();
  }
}

async function runBackgroundProxyAckTimeoutTest() {
  const harness = createHarness();
  const { hooks, setRuntimeSendMessageHandler } = harness;

  try {
    setRuntimeSendMessageHandler((payload, callback) => {
      if (payload?.type !== 'RESOLVE_LOCAL_ASSET') {
        callback?.({ ok: false, error: 'UNEXPECTED_PAYLOAD' });
        return;
      }
      callback?.({
        ok: true,
        accepted: true,
        proxy_request_id: payload.proxy_request_id,
      });
    });

    const result = await hooks.resolveLocalAssetViaBackgroundProxy(
      'asset-timeout',
      'asset-timeout.jpg',
      'request-timeout',
      40,
    );
    expect(result?.ok === false, 'Expected proxy helper to fail when detached result never arrives', result);
    expect(result?.error === 'ERR_PROXY_MESSAGE_TIMEOUT', `Expected ERR_PROXY_MESSAGE_TIMEOUT, got ${result?.error}`, result);
  } finally {
    harness.close();
  }
}

async function runBackgroundProxyAckFailureResultTest() {
  const harness = createHarness();
  const { hooks, setRuntimeSendMessageHandler } = harness;

  try {
    setRuntimeSendMessageHandler((payload, callback, runtime) => {
      if (payload?.type !== 'RESOLVE_LOCAL_ASSET') {
        callback?.({ ok: false, error: 'UNEXPECTED_PAYLOAD' });
        return;
      }
      callback?.({
        ok: true,
        accepted: true,
        proxy_request_id: payload.proxy_request_id,
      });
      setTimeout(() => {
        runtime.emit({
          type: 'RESOLVE_LOCAL_ASSET_RESULT',
          proxy_request_id: payload.proxy_request_id,
          ok: false,
          error: 'ERR_BACKGROUND_ASSET_FETCH_FAILED',
          detail: 'HTTP_404',
        });
      }, 10);
    });

    const result = await hooks.resolveLocalAssetViaBackgroundProxy(
      'asset-missing',
      'asset-missing.jpg',
      'request-missing',
      250,
    );
    expect(result?.ok === false, 'Expected proxy helper to surface detached failure result', result);
    expect(result?.error === 'ERR_BACKGROUND_ASSET_FETCH_FAILED', `Expected detached failure error, got ${result?.error}`, result);
    expect(result?.detail === 'HTTP_404', 'Expected detached failure detail to round-trip', result);
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
    ['Find element resolves nested interactive Video tab', runFindElementByTextPrefersNestedInteractiveControlTest],
    ['Selected-state uses interactive Video descendant', runIsSelectedControlUsesInteractiveDescendantStateTest],
    ['Required slots F2V start-only', runGetRequiredAssetSlotsF2VStartOnlyTest],
    ['Required slots F2V start-and-end', runGetRequiredAssetSlotsF2VStartAndEndTest],
    ['Verify F2V allows unknown model label', runVerifyFlowModeAllowsUnknownF2VModelTest],
    ['Verify F2V rejects Nano Banana model', runVerifyFlowModeRejectsNanoBananaOnF2VTest],
    ['Verify F2V rejects wrong visible ratio', runVerifyFlowModeRejectsWrongRatioOnF2VTest],
    ['Verify F2V rejects wrong visible count', runVerifyFlowModeRejectsWrongCountOnF2VTest],
    ['Verify F2V rejects wrong visible model', runVerifyFlowModeRejectsWrongModelOnF2VTest],
    ['Verify F2V rejects missing Start slot', runVerifyFlowModeRejectsMissingStartSlotOnF2VTest],
    ['One-way runtime telemetry omits callback lane', runSendRuntimeMessageNoThrowIsOneWayTest],
    ['Background proxy ACK and result', runBackgroundProxyAckAndResultTest],
    ['Background proxy ACK timeout', runBackgroundProxyAckTimeoutTest],
    ['Background proxy ACK failure result', runBackgroundProxyAckFailureResultTest],
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
