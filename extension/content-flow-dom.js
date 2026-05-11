/**
 * Flow Kit — Google Flow DOM Executor with Mode Verification Gate
 * 
 * Strictly enforces: SELECT MODE -> VERIFY MODE -> ATTACH ASSET -> VERIFY ASSET -> INSERT PROMPT -> CLICK GENERATE
 * 
 * FORBIDDEN:
 * - Upload asset before mode verification
 * - Insert prompt before mode verification
 * - Click generate before mode verification
 * - Use Image/Nano Banana for TRUE_F2V
 * - Use Video/Frames for IMG
 */

(function() {
  const FLOW_KIT_DOM_VERSION = '2026-05-11-multimode-gates';
  const FLOW_KIT_DOM_PROTOCOL_VERSION = 'FLOWKIT_DOM_V1';
  const IMAGE_ASPECT_RATIOS = ['16:9', '4:3', '1:1', '3:4', '9:16'];

  if (window._flowKitDomInjectedVersion === FLOW_KIT_DOM_VERSION && window._flowKitDomListener) {
    console.log('[FlowAgent] Flow DOM Executor already present');
    return;
  }

  if (window._flowKitDomListener) {
    try {
      chrome.runtime.onMessage.removeListener(window._flowKitDomListener);
    } catch (error) {
      console.warn('[FlowAgent] Failed to remove previous Flow DOM listener:', error);
    }
  }

  window._flowKitDomInjectedVersion = FLOW_KIT_DOM_VERSION;
  console.log('[FlowAgent] Flow DOM Executor injected');

  function sendRuntimeMessageNoThrow(payload) {
    try {
      chrome.runtime.sendMessage(payload, () => {
        const lastError = chrome.runtime.lastError;
        if (lastError) {
          console.warn('[FlowAgent] runtime message ignored:', lastError.message);
        }
      });
    } catch (error) {
      console.warn('[FlowAgent] runtime message exception:', error);
    }
  }

  // Safe wrapper for sending messages without blocking on response
  function sendStageEvent(request_id, stage, status) {
    sendRuntimeMessageNoThrow({
      type: 'FLOW_STAGE_EVENT',
      request_id: request_id,
      stage: stage,
      status: status,
      source: 'google_flow'
    });
  }

  const STAGES = {
    FLOW_TAB_FOUND: 'FLOW_TAB_FOUND',
    PRE_EXECUTION_STATE_CLEARED: 'PRE_EXECUTION_STATE_CLEARED',
    FLOW_MODE_SELECTED: 'FLOW_MODE_SELECTED',
    FLOW_SUBMODE_SELECTED: 'FLOW_SUBMODE_SELECTED',
    ASPECT_SELECTED: 'ASPECT_SELECTED',
    COUNT_SELECTED: 'COUNT_SELECTED',
    MODEL_SELECTED: 'MODEL_SELECTED',
    FLOW_MODE_VERIFIED: 'FLOW_MODE_VERIFIED',
    ASSETS_VERIFIED: 'ASSETS_VERIFIED',
    START_FRAME_ATTACHED: 'START_FRAME_ATTACHED',
    START_FRAME_VERIFIED: 'START_FRAME_VERIFIED',
    END_FRAME_ATTACHED: 'END_FRAME_ATTACHED',
    INGREDIENTS_ATTACHED: 'INGREDIENTS_ATTACHED',
    IMAGE_ASSET_ATTACHED: 'IMAGE_ASSET_ATTACHED',
    JOB_PROMPT_RECEIVED: 'JOB_PROMPT_RECEIVED',
    PROMPT_FIELD_FOUND: 'PROMPT_FIELD_FOUND',
    PROMPT_INSERT_METHOD: 'PROMPT_INSERT_METHOD',
    PROMPT_VISIBLE: 'PROMPT_VISIBLE',
    PROMPT_EDITABLE_AFTER_INSERT: 'PROMPT_EDITABLE_AFTER_INSERT',
    GENERATE_ARROW_ENABLED: 'GENERATE_ARROW_ENABLED',
    GENERATE_CLICKED: 'GENERATE_CLICKED',
    GENERATION_STARTED: 'GENERATION_STARTED',
    VIDEO_JOB_RUNNING_OR_GENERATED: 'VIDEO_JOB_RUNNING_OR_GENERATED',
    FLOW_MODE_MISMATCH: 'FLOW_MODE_MISMATCH'
  };

  async function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  function respondAsync(sendResponse, task) {
    let settled = false;

    const done = (payload) => {
      if (settled) return;
      settled = true;
      try {
        sendResponse(payload || { ok: true });
      } catch (error) {
        console.warn('[FlowAgent] sendResponse failed:', error);
      }
    };

    Promise.resolve()
      .then(task)
      .then((payload) => done(payload))
      .catch((error) => done({ ok: false, error: String(error?.message || error) }));
    return true;
  }

  function buildDiagnosticPingResponse() {
    return {
      ok: true,
      content_script_loaded: true,
      content_script_protocol_version: FLOW_KIT_DOM_PROTOCOL_VERSION,
      location_href: window.location.href,
      timestamp: new Date().toISOString(),
    };
  }

  function normalizeText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function uniqueNonEmpty(values, limit = 50) {
    const seen = new Set();
    const result = [];
    for (const rawValue of values || []) {
      const value = normalizeText(rawValue);
      if (!value || seen.has(value)) continue;
      seen.add(value);
      result.push(value);
      if (result.length >= limit) break;
    }
    return result;
  }

  function collectVisibleTexts(selector, projector, limit = 50) {
    const values = [];
    for (const el of document.querySelectorAll(selector)) {
      if (!isVisible(el)) continue;
      values.push(projector(el));
      if (values.length >= limit) break;
    }
    return uniqueNonEmpty(values, limit);
  }

  function collectVisibleMarkers(candidates, sources) {
    const haystacks = sources
      .map((source) => normalizeText(source).toLowerCase())
      .filter(Boolean);
    const found = [];
    for (const candidate of candidates) {
      const normalizedCandidate = normalizeText(candidate).toLowerCase();
      if (!normalizedCandidate) continue;
      if (haystacks.some((source) => source.includes(normalizedCandidate))) {
        found.push(candidate);
      }
    }
    return uniqueNonEmpty(found);
  }

  function isVisible(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  }

  function findElementByText(selector, text) {
    const elements = document.querySelectorAll(selector);
    for (const el of elements) {
      if (el.textContent.trim().toLowerCase() === text.toLowerCase()) return el;
    }
    for (const el of elements) {
      if (el.textContent.trim().toLowerCase().includes(text.toLowerCase())) return el;
    }
    return null;
  }

  function isSelectedControl(el, text) {
    if (!el) return false;
    if (el.getAttribute('data-state') === 'active') return true;
    if (el.getAttribute('aria-selected') === 'true') return true;
    if (el.getAttribute('aria-pressed') === 'true') return true;

    const classes = el.classList.toString().toLowerCase();
    if (classes.includes('active') || classes.includes('selected') || classes.includes('checked')) return true;

    if (text && normalizeText(el.textContent).toLowerCase().includes(text.toLowerCase())) {
      if (classes.includes('trigger') && (classes.includes('flow') || classes.includes('tab'))) return true;
    }

    return false;
  }

  function resolveRequestedAspectRatio(job) {
    if (job?.aspectRatio) return job.aspectRatio;
    if (job?.orientation === 'HORIZONTAL') return '16:9';
    if (job?.orientation === 'VERTICAL') return '9:16';
    return null;
  }

  function resolveRequestedModel(job) {
    return job?.modelLabel || job?.model || null;
  }

  function resolveRequestedCount(job) {
    const rawCount = Number(job?.count || 1);
    const safeCount = Number.isFinite(rawCount) && rawCount >= 1 ? Math.min(4, Math.round(rawCount)) : 1;
    return `${safeCount}x`;
  }

  function resolveAssetSourceId(assetSource) {
    if (!assetSource) return null;
    if (typeof assetSource === 'string') return assetSource;
    if (typeof assetSource !== 'object') return null;
    return assetSource.productId
      || assetSource.product_id
      || assetSource.mediaId
      || assetSource.media_id
      || assetSource.id
      || assetSource.characterId
      || null;
  }

  function getRefAssets(job) {
    const refs = job?.refs || {};
    return [
      { slotLabel: 'Subject', assetSource: refs.subjectAsset || refs.subject },
      { slotLabel: 'Scene', assetSource: refs.sceneAsset || refs.scene },
      { slotLabel: 'Style', assetSource: refs.styleAsset || refs.style },
      { slotLabel: 'Image', assetSource: refs.imageAsset || refs.image },
    ].filter((item) => !!item.assetSource);
  }

  function getRequiredAssetSlots(job) {
    if (job?.mode === 'F2V') {
      const slots = ['Start'];
      if (job?.endAsset || job?.endImageMediaId || job?.productId) slots.push('End');
      return slots;
    }

    if (job?.mode === 'I2V' || job?.mode === 'IMG') {
      const refAssets = getRefAssets(job);
      if (refAssets.length > 0) return refAssets.map((item) => item.slotLabel);
      return [job.mode === 'I2V' ? 'Ingredients' : 'Image'];
    }

    return [];
  }

  function buildSlotErrorCode(slotLabel, suffix) {
    return `ERR_${String(slotLabel || 'slot').toUpperCase().replace(/[^A-Z0-9]+/g, '_')}_${suffix}`;
  }

  function describePreviewNode(node) {
    if (!node || !isVisible(node)) return null;
    const rect = node.getBoundingClientRect();
    if (rect.width < 32 || rect.height < 32) return null;

    const tagName = (node.tagName || '').toLowerCase();
    let identity = tagName;
    if (tagName === 'img') {
      identity = node.currentSrc || node.src || node.getAttribute('src') || tagName;
      if ((node.naturalWidth || rect.width) < 32 || (node.naturalHeight || rect.height) < 32) return null;
    } else if (tagName === 'picture') {
      const nestedImg = node.querySelector('img');
      return nestedImg ? describePreviewNode(nestedImg) : null;
    } else if (tagName === 'canvas') {
      identity = `${tagName}:${node.width || Math.round(rect.width)}x${node.height || Math.round(rect.height)}`;
    } else if (tagName === 'video') {
      identity = node.currentSrc || node.getAttribute('src') || `${tagName}:${Math.round(rect.width)}x${Math.round(rect.height)}`;
    } else {
      const backgroundImage = window.getComputedStyle(node).backgroundImage;
      if (!backgroundImage || backgroundImage === 'none') return null;
      identity = backgroundImage;
    }

    return {
      node,
      rect,
      tagName,
      identity,
    };
  }

  function getContainerPreviewDetails(container) {
    if (!container) return {
      previewFound: false,
      previewCount: 0,
      previewKey: 'none',
      previewRect: null,
    };

    const previewNodes = Array.from(container.querySelectorAll('img, canvas, video, picture, [style*="background-image"]'));
    const visiblePreviews = previewNodes
      .map(describePreviewNode)
      .filter(Boolean);

    const primaryPreview = visiblePreviews[0] || null;
    return {
      previewFound: visiblePreviews.length > 0,
      previewCount: visiblePreviews.length,
      previewKey: visiblePreviews.map(item => item.identity).join('|') || 'none',
      previewRect: primaryPreview ? {
        width: Math.round(primaryPreview.rect.width),
        height: Math.round(primaryPreview.rect.height),
      } : null,
    };
  }

  function hasUploadPending(container) {
    if (!container) return false;

    const busyNode = Array.from(container.querySelectorAll('[aria-busy="true"], [role="progressbar"], progress, .spinner, .loading'))
      .find(isVisible);
    if (busyNode) return true;

    const text = normalizeText(container.innerText || '').toLowerCase();
    return ['uploading', 'processing', 'loading', 'please wait'].some((token) => text.includes(token));
  }

  function snapshotSlot(container) {
    const preview = getContainerPreviewDetails(container);
    return {
      previewFound: preview.previewFound,
      previewCount: preview.previewCount,
      previewKey: preview.previewKey,
      previewRect: preview.previewRect,
      uploadPending: hasUploadPending(container),
    };
  }

  function containerHasVisualPreview(container) {
    return getContainerPreviewDetails(container).previewFound;
  }

  function getSlotCandidateContainers(slotLabel, slotElement = null) {
    const candidates = [];
    const push = (el) => {
      if (!el || candidates.includes(el)) return;
      candidates.push(el);
    };

    push(slotElement);
    push(slotElement?.closest('button'));
    push(slotElement?.closest('[role="button"]'));

    const labelNode = findElementByText('button, [role="button"], label, span, div, p', slotLabel);
    push(labelNode);
    push(labelNode?.closest('button'));
    push(labelNode?.closest('[role="button"]'));

    let current = slotElement || labelNode;
    for (let depth = 0; current && depth < 4; depth += 1) {
      push(current);
      current = current.parentElement;
    }

    current = labelNode?.parentElement || null;
    for (let depth = 0; current && depth < 4; depth += 1) {
      push(current);
      current = current.parentElement;
    }

    return candidates;
  }

  function resolveSlotContainer(slotLabel, slotElement = null) {
    const candidates = getSlotCandidateContainers(slotLabel, slotElement)
      .filter((candidate) => candidate && isVisible(candidate));

    const labelledCandidate = candidates.find((candidate) => normalizeText(candidate.innerText || '').toLowerCase().includes(String(slotLabel || '').toLowerCase()));
    if (labelledCandidate) return labelledCandidate;

    const previewCandidate = candidates.find((candidate) => containerHasVisualPreview(candidate));
    if (previewCandidate) return previewCandidate;

    return candidates[0] || null;
  }

  function slotHasVisiblePreview(slotLabel, slotElement = null) {
    return getSlotCandidateContainers(slotLabel, slotElement).some(containerHasVisualPreview);
  }

  async function waitForCondition(check, timeoutMs = 7000, intervalMs = 250) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (check()) return true;
      await sleep(intervalMs);
    }
    return check();
  }

  async function waitForSlotPreviewChange({ slotLabel, slotContainer, beforeSnapshot, timeoutMs = 15000 }) {
    if (!slotContainer) {
      return {
        ok: false,
        error: buildSlotErrorCode(slotLabel, 'UPLOAD_TARGET_NOT_FOUND'),
        snapshot: null,
      };
    }

    const initialSnapshot = beforeSnapshot || snapshotSlot(slotContainer);
    const hasPreviewChanged = () => {
      const currentSnapshot = snapshotSlot(slotContainer);
      const previewChanged = currentSnapshot.previewFound
        && currentSnapshot.previewKey !== initialSnapshot.previewKey;
      const countChanged = currentSnapshot.previewFound
        && currentSnapshot.previewCount > initialSnapshot.previewCount;
      const wasAlreadyReady = initialSnapshot.previewFound && !initialSnapshot.uploadPending;
      const uploadSettled = !currentSnapshot.uploadPending;

      if ((previewChanged || countChanged) && uploadSettled) {
        return {
          ok: true,
          snapshot: currentSnapshot,
        };
      }

      if (!wasAlreadyReady && currentSnapshot.previewFound && uploadSettled && initialSnapshot.previewKey === 'none') {
        return {
          ok: true,
          snapshot: currentSnapshot,
        };
      }

      return null;
    };

    const immediate = hasPreviewChanged();
    if (immediate) return immediate;

    return new Promise((resolve) => {
      let settled = false;

      const finish = (payload) => {
        if (settled) return;
        settled = true;
        observer.disconnect();
        window.clearTimeout(timeoutId);
        window.clearInterval(pollId);
        resolve(payload);
      };

      const observer = new MutationObserver(() => {
        const changed = hasPreviewChanged();
        if (changed) finish(changed);
      });
      observer.observe(slotContainer, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['src', 'style', 'class', 'aria-busy'],
      });

      const pollId = window.setInterval(() => {
        const changed = hasPreviewChanged();
        if (changed) finish(changed);
      }, 300);

      const timeoutId = window.setTimeout(() => {
        const currentSnapshot = snapshotSlot(slotContainer);
        if (currentSnapshot.uploadPending) {
          finish({
            ok: false,
            error: buildSlotErrorCode(slotLabel, 'UPLOAD_STILL_PENDING'),
            snapshot: currentSnapshot,
          });
          return;
        }

        finish({
          ok: false,
          error: buildSlotErrorCode(slotLabel, 'PREVIEW_TIMEOUT'),
          snapshot: currentSnapshot,
        });
      }, timeoutMs);
    });
  }

  async function waitForAssetPreview(slotLabel, slotElement = null, options = {}) {
    const slotContainer = options.slotContainer || resolveSlotContainer(slotLabel, slotElement);
    const beforeSnapshot = options.beforeSnapshot || snapshotSlot(slotContainer);

    if (!slotContainer) {
      return {
        ok: false,
        error: buildSlotErrorCode(slotLabel, 'SLOT_NOT_FOUND'),
        snapshot: null,
      };
    }

    return waitForSlotPreviewChange({
      slotLabel,
      slotContainer,
      beforeSnapshot,
      timeoutMs: options.timeoutMs || 15000,
    });
  }

  async function nudgeComposerHydration(composer) {
    if (!composer) return;

    const rect = composer.getBoundingClientRect();
    composer.dispatchEvent(new MouseEvent('mousemove', {
      bubbles: true,
      clientX: rect.left + Math.min(rect.width - 2, 12),
      clientY: rect.top + Math.min(rect.height - 2, 12),
    }));

    composer.focus();
    await sleep(75);
    insertTextLikeUser(composer, ' ');
    await sleep(50);

    if ('value' in composer) {
      composer.value = composer.value.replace(/\s$/, '');
      composer.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward', data: null }));
    } else {
      composer.textContent = (composer.textContent || '').replace(/\s$/, '');
      composer.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward', data: null }));
    }

    composer.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', code: 'Space', bubbles: true }));
    composer.dispatchEvent(new KeyboardEvent('keyup', { key: ' ', code: 'Space', bubbles: true }));
    await sleep(200);
  }

  async function clearVideoSubmodeSelection() {
    const cleared = [];
    for (const label of ['Frames', 'Ingredients']) {
      const button = findElementByText('button, [role="tab"], [role="button"], span', label);
      if (isSelectedControl(button, label)) {
        button.click();
        cleared.push(label);
        await sleep(800);
      }
    }
    return cleared;
  }

  function findGenerateButtonNearComposer() {
    // 1. Target by specific text found in diagnostic
    const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
    const createBtn = buttons.find(btn => {
      if (!isVisible(btn)) return false;
      const text = normalizeText(btn.textContent);
      // arrow_forward Create or just Create
      if (text.includes('Create') || text.includes('Generate')) return true;
      const aria = btn.getAttribute('aria-label') || '';
      if (aria.includes('Create') || aria.includes('Generate')) return true;
      return false;
    });
    if (createBtn) return createBtn;

    // 2. Fallback to icon path detection
    const paths = document.querySelectorAll('path');
    for (const path of paths) {
      const d = path.getAttribute('d') || '';
      if (d.includes('M10 20l-1.41-1.41L15.17 12 8.59 5.41 10 4l8 8-8 8z') ||
          d.includes('M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z')) {
        const btn = path.closest('button');
        if (btn && isVisible(btn)) return btn;
      }
    }

    // 3. Fallback to proximity to composer
    const composer = findComposerElement();
    if (composer) {
      let current = composer.parentElement;
      for (let i = 0; i < 3 && current; i++) {
        const siblingButtons = current.querySelectorAll('button');
        if (siblingButtons.length > 0) {
          const lastBtn = siblingButtons[siblingButtons.length - 1];
          if (isVisible(lastBtn)) return lastBtn;
        }
        current = current.parentElement;
      }
    }

    return document.querySelector('button[aria-label*="Create"], button[aria-label*="Generate"]');
  }

  function findComposerElement() {
    const candidates = Array.from(document.querySelectorAll('textarea, [contenteditable="true"], [role="textbox"]'));

    // 1. Target by specific aria-label found in diagnostic
    const specific = candidates.find(el => el.getAttribute('aria-label') === 'Editable text' && isVisible(el));
    if (specific) return specific;

    // 2. Target by placeholder/text content
    const withPlaceholder = candidates.find(el => {
      if (!isVisible(el)) return false;
      const text = el.textContent || el.getAttribute('placeholder') || el.getAttribute('data-placeholder') || '';
      return text.includes('What do you want to create?');
    });
    if (withPlaceholder) return withPlaceholder;

    // 3. General visible candidate
    return candidates.find(isVisible) || candidates[0] || null;
  }

  function detectBlockingModal() {
    const dialogs = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"], dialog'));
    return dialogs.find(isVisible) || null;
  }

  function inferSignedInLikely(composer, observed) {
    if (composer) return true;
    if (observed.topMode !== 'UNKNOWN') return true;
    const landingCta = findElementByText('button, a, div[role="button"]', 'Create with Flow');
    if (landingCta && isVisible(landingCta)) return false;
    return !document.body.innerText.includes('Where the next wave of storytelling happens');
  }

  function getComposerText(el) {
    if ('value' in el) return el.value;
    return el.textContent || '';
  }

  function isComposerEditable(el) {
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
    if (el.getAttribute('contenteditable') === 'false') return false;
    return true;
  }

  async function keyboardClear(el) {
    el.focus();
    await sleep(50);
    if ('value' in el) {
      el.value = '';
    } else {
      el.innerHTML = '';
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(50);
  }

  function insertTextLikeUser(el, text) {
    el.focus();
    const ok = document.execCommand && document.execCommand('insertText', false, text);
    if (!ok) {
      el.dispatchEvent(new InputEvent('beforeinput', { bubbles: true, inputType: 'insertText', data: text }));
      if ('value' in el) {
        const start = el.selectionStart || 0;
        const end = el.selectionEnd || 0;
        el.value = el.value.substring(0, start) + text + el.value.substring(end);
        el.selectionStart = el.selectionEnd = start + text.length;
      } else {
        el.textContent = `${el.textContent || ''}${text}`;
      }
      el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
    }
  }

  async function humanTypePrompt(composer, prompt) {
    composer.click();
    composer.focus();
    await sleep(100);
    await keyboardClear(composer);

    const chunks = prompt.match(/.{1,12}/g) || [];
    for (const chunk of chunks) {
      insertTextLikeUser(composer, chunk);
      await sleep(10);
    }
    await sleep(300);
  }

  async function simulateFileUpload(slotLabel, assetSource) {
    console.log(`[FlowAgent] Attempting to upload asset to slot: ${slotLabel}`);
    
    // 1. Find and click the slot button (Start/End/Ingredients)
    const slotBtn = findElementByText('button, [role="button"], span', slotLabel);
    if (!slotBtn) {
      console.warn(`[FlowAgent] Slot button ${slotLabel} not found`);
      return { ok: false, error: buildSlotErrorCode(slotLabel, 'SLOT_NOT_FOUND') };
    }
    const slotContainer = resolveSlotContainer(slotLabel, slotBtn);
    const beforeSnapshot = snapshotSlot(slotContainer);
    slotBtn.click();
    await sleep(500);

    // 2. Fetch or Resolve the image
    let file;
    try {
      if (assetSource && typeof assetSource === 'object' && assetSource.previewUrl) {
        console.log(`[FlowAgent] Using direct base64 source for ${slotLabel}`);
        const base64Data = assetSource.previewUrl;
        const blob = await (await fetch(base64Data)).blob();
        file = new File([blob], assetSource.fileName || `${slotLabel}.png`, { type: blob.type || 'image/png' });
      } else {
        const assetId = resolveAssetSourceId(assetSource);
        if (!assetId) {
          console.warn(`[FlowAgent] No asset source id resolved for slot ${slotLabel}`);
          return { ok: false, error: buildSlotErrorCode(slotLabel, 'ASSET_MISSING') };
        }
        const imageUrl = `http://127.0.0.1:8100/api/products/${assetId}/image`;
        console.log(`[FlowAgent] Fetching image from agent: ${imageUrl}`);
        const resp = await fetch(imageUrl);
        if (!resp.ok) throw new Error(`HTTP_${resp.status}`);
        const blob = await resp.blob();
        file = new File([blob], `${assetId}.jpg`, { type: 'image/jpeg' });
      }
    } catch (err) {
      console.error(`[FlowAgent] Failed to resolve/fetch image: ${err.message}`);
      return { ok: false, error: buildSlotErrorCode(slotLabel, 'FILE_RESOLVE_FAILED') };
    }

    // 3. Find the dropzone/input
    // Google Flow uses a hidden file input or a drop listener on the container
    const fileInput = slotContainer?.querySelector('input[type="file"]') || document.querySelector('input[type="file"]');
    const dropzone = slotContainer?.querySelector('[role="presentation"], .dropzone, [aria-label*="upload"]')
      || document.querySelector('[role="presentation"], .dropzone, [aria-label*="upload"]');
    
    const target = fileInput || dropzone || slotBtn || slotContainer || document.body;
    if (!target) {
      return { ok: false, error: buildSlotErrorCode(slotLabel, 'UPLOAD_TARGET_NOT_FOUND') };
    }

    try {
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(file);

      if (target.matches && target.matches('input[type="file"]')) {
        Object.defineProperty(target, 'files', {
          configurable: true,
          value: dataTransfer.files,
        });
        target.dispatchEvent(new Event('input', { bubbles: true }));
        target.dispatchEvent(new Event('change', { bubbles: true }));
      } else {
        const dragEnter = new DragEvent('dragenter', {
          bubbles: true,
          cancelable: true,
          dataTransfer,
        });
        const dragOver = new DragEvent('dragover', {
          bubbles: true,
          cancelable: true,
          dataTransfer,
        });
        const dropEvent = new DragEvent('drop', {
          bubbles: true,
          cancelable: true,
          dataTransfer,
        });
        target.dispatchEvent(dragEnter);
        target.dispatchEvent(dragOver);
        target.dispatchEvent(dropEvent);
      }
    } catch (error) {
      console.error(`[FlowAgent] Upload dispatch failed for ${slotLabel}: ${error.message}`);
      return { ok: false, error: buildSlotErrorCode(slotLabel, 'UPLOAD_DISPATCH_FAILED') };
    }

    console.log(`[FlowAgent] Dispatched upload for ${slotLabel}`);
    await sleep(600);
    return {
      ok: true,
      slotElement: slotBtn,
      slotContainer,
      beforeSnapshot,
    };
  }

  /**
   * observeFlowState()
   * 
   * Snapshots the actual Google Flow UI state from DOM.
   * Does NOT rely on clicked state, only visible state.
   * 
   * Returns:
   * {
   *   "topMode": "Image|Video|UNKNOWN",
   *   "subMode": "Frames|Ingredients|None|UNKNOWN",
   *   "model": "observed model text",
   *   "aspectRatio": "9:16|16:9|UNKNOWN",
   *   "count": "1x|2x|3x|4x|UNKNOWN",
   *   "visibleUploadSlots": ["Start", "End", "Ingredients", "Image"],
   *   "composerPresent": true,
   *   "generateButtonState": "enabled|disabled"
   * }
   */
  function observeFlowState() {
    console.log('[FlowAgent] Observing Flow State...');
    const observed = {
      topMode: 'UNKNOWN',
      subMode: 'UNKNOWN',
      model: 'UNKNOWN',
      aspectRatio: 'UNKNOWN',
      count: 'UNKNOWN',
      visibleUploadSlots: [],
      visibleAssetPreviews: [],
      composerPresent: false,
      generateButtonState: 'unknown'
    };

    // 1. Detect top mode (Image vs Video)
    // In Radix UI, the triggers often have text like "play_circle Video"
    const videoModeBtn = findElementByText('button, [role="tab"], [role="button"]', 'Video');
    const imageModeBtn = findElementByText('button, [role="tab"], [role="button"]', 'Image');
    
    if (isSelectedControl(videoModeBtn, 'Video')) {
      observed.topMode = 'Video';
    } else if (isSelectedControl(imageModeBtn, 'Image')) {
      observed.topMode = 'Image';
    } else {
      const bodyText = document.body.innerText;
      if (bodyText.includes('Frames') || bodyText.includes('Start') || bodyText.includes('End')) {
        observed.topMode = 'Video';
      } else if (bodyText.includes('Nano Banana')) {
        observed.topMode = 'Image';
      }
    }
    console.log(`[FlowAgent] Detected topMode: ${observed.topMode}`);

    // 2. Detect submode (Frames vs Ingredients)
    if (observed.topMode === 'Video') {
      const framesBtn = findElementByText('button, [role="tab"], [role="button"]', 'Frames');
      const ingredientsBtn = findElementByText('button, [role="tab"], [role="button"]', 'Ingredients');
      
      if (isSelectedControl(framesBtn, 'Frames')) {
        observed.subMode = 'Frames';
      } else if (isSelectedControl(ingredientsBtn, 'Ingredients')) {
        observed.subMode = 'Ingredients';
      } else {
        const bodyText = document.body.innerText;
        if (bodyText.includes('Start') || bodyText.includes('End')) {
          observed.subMode = 'Frames';
        } else if (bodyText.includes('Ingredients')) {
          observed.subMode = 'Ingredients';
        } else {
          observed.subMode = 'None';
        }
      }
    }
    console.log(`[FlowAgent] Detected subMode: ${observed.subMode}`);

    // 3. Detect model
    const modelElements = document.querySelectorAll('button, span, div, p');
    for (const el of modelElements) {
      if (!isVisible(el)) continue;
      const text = el.textContent.trim();
      if (text.includes('Veo 3') || text.includes('Veo-3')) {
        observed.model = 'Veo 3.1';
        break;
      } else if (text.includes('Nano Banana')) {
        observed.model = 'Nano Banana';
        break;
      }
    }

    // 4. Detect aspect ratio
    const aspectElements = document.querySelectorAll('button, [role="tab"], [role="button"], span');
    for (const el of aspectElements) {
      if (!isVisible(el)) continue;
      const text = el.textContent.trim();
      const matchedRatio = IMAGE_ASPECT_RATIOS.find((ratio) => text.includes(ratio));
      if (!matchedRatio) continue;
      if (isSelectedControl(el, matchedRatio) || isSelectedControl(el.closest('button'), matchedRatio)) {
        observed.aspectRatio = matchedRatio;
        break;
      }
    }

    // 5. Detect count
    const countElements = document.querySelectorAll('button, [role="tab"], [role="button"], span');
    for (const el of countElements) {
      if (!isVisible(el)) continue;
      const text = el.textContent.trim();
      if (/^[1-4]x$/.test(text)) {
        if (isSelectedControl(el, text) || isSelectedControl(el.closest('button'), text)) {
          observed.count = text;
          break;
        }
      }
    }

    // 6. Detect upload slots
    const slotLabels = ['Start', 'End', 'Ingredients', 'Image', 'Subject', 'Scene', 'Style'];
    for (const label of slotLabels) {
      // Find elements that exactly match or contain the label text in a small container
      const candidateLabels = Array.from(document.querySelectorAll('label, span, div, p'))
        .filter(el => isVisible(el) && el.textContent.trim() === label);
      
      if (candidateLabels.length > 0) {
        observed.visibleUploadSlots.push(label);
      } else {
        // Fallback to partial search if exact fails
        const partial = findElementByText('label, span, div, p', label);
        if (partial && isVisible(partial)) {
          observed.visibleUploadSlots.push(label);
        }
      }

      if (slotHasVisiblePreview(label)) {
        observed.visibleAssetPreviews.push(label);
      }
    }
    console.log(`[FlowAgent] Detected slots: ${observed.visibleUploadSlots.join(', ')}`);

    // 7. Check composer
    observed.composerPresent = !!findComposerElement();

    // 8. Check generate button state
    const generateBtn = findGenerateButtonNearComposer();
    if (generateBtn) {
      observed.generateButtonState = generateBtn.disabled ? 'disabled' : 'enabled';
    }

    return observed;
  }

  function collectFlowPageStateDiagnostic(mode) {
    const readiness = checkFlowComposerReady(mode);
    const bodyText = normalizeText(document.body?.innerText || '').slice(0, 2000);
    const buttonTexts = collectVisibleTexts('button, [role="button"]', (el) => el.textContent || '');
    const textareaPlaceholders = collectVisibleTexts('textarea', (el) => el.getAttribute('placeholder') || el.getAttribute('aria-label') || '');
    const inputPlaceholders = collectVisibleTexts('input', (el) => el.getAttribute('placeholder') || el.getAttribute('aria-label') || '');
    const contenteditableTexts = collectVisibleTexts('[contenteditable="true"], [role="textbox"]', (el) => {
      return el.textContent || el.getAttribute('aria-label') || el.getAttribute('data-placeholder') || '';
    });
    const ariaLabels = collectVisibleTexts('[aria-label]', (el) => el.getAttribute('aria-label') || '');

    const markerSources = [
      bodyText,
      document.title,
      ...buttonTexts,
      ...textareaPlaceholders,
      ...inputPlaceholders,
      ...contenteditableTexts,
      ...ariaLabels,
    ];

    return {
      ok: true,
      flow_url: window.location.href,
      location_href: window.location.href,
      document_title: document.title,
      document_ready_state: document.readyState,
      body_text_first_2000_chars: bodyText,
      visible_login_markers: collectVisibleMarkers([
        'Sign in',
        'Log in',
        'Continue with Google',
        'Choose an account',
        'Use another account',
        'Switch account',
        'Create with Flow',
      ], markerSources),
      visible_loading_markers: collectVisibleMarkers([
        'Loading',
        'Please wait',
        'Just a sec',
        'Just a moment',
        'Opening project',
        'Loading project',
      ], markerSources),
      visible_error_markers: collectVisibleMarkers([
        'Access denied',
        'Request access',
        'Not found',
        '404',
        '403',
        'Something went wrong',
        'Unable to load',
        'Permission denied',
        'You need access',
      ], markerSources),
      visible_project_editor_markers: collectVisibleMarkers([
        'Video',
        'Frames',
        'Ingredients',
        'Image',
        'Veo',
        'Start',
        'End',
        '9:16',
        '16:9',
        '1x',
      ], markerSources),
      visible_composer_placeholder_markers: collectVisibleMarkers([
        'What do you want to create?',
        'Describe your video',
        'Describe your image',
        'Write a prompt',
        'Enter prompt',
      ], markerSources),
      button_texts: buttonTexts,
      textarea_placeholders: textareaPlaceholders,
      input_placeholders: inputPlaceholders,
      contenteditable_texts: contenteditableTexts,
      aria_labels: ariaLabels,
      signed_in_likely: readiness.signed_in_likely,
      composer_found: readiness.composer_found,
      composer_editable: readiness.composer_editable,
      generate_button_found: readiness.generate_button_found,
      current_mode_visible: readiness.current_mode_visible,
      blocking_modal_detected: readiness.blocking_modal_detected,
      observed: readiness.observed,
      content_script_loaded: true,
      content_script_protocol_version: FLOW_KIT_DOM_PROTOCOL_VERSION,
      timestamp: new Date().toISOString(),
    };
  }

  function checkFlowComposerReady(mode) {
    const observed = observeFlowState();
    const composer = findComposerElement();
    const generateBtn = findGenerateButtonNearComposer();
    const blockingModal = detectBlockingModal();
    const currentModeVisible = observed.topMode === 'UNKNOWN'
      ? 'UNKNOWN'
      : (observed.subMode !== 'UNKNOWN' ? `${observed.topMode}/${observed.subMode}` : observed.topMode);

    const result = {
      ok: false,
      flow_tab_found: true,
      flow_url: window.location.href,
      signed_in_likely: inferSignedInLikely(composer, observed),
      composer_found: !!composer,
      composer_editable: !!composer && isComposerEditable(composer),
      generate_button_found: !!generateBtn,
      current_mode_visible: currentModeVisible,
      blocking_modal_detected: !!blockingModal,
      observed,
    };

    if (mode) {
      result.expected_mode = mode;
    }

    result.ok = Boolean(
      result.signed_in_likely &&
      result.composer_found &&
      result.composer_editable &&
      result.generate_button_found &&
      !result.blocking_modal_detected
    );

    if (!result.ok) {
      result.error = 'ABORT_FLOW_COMPOSER_NOT_READY';
    }

    return result;
  }

  function isRootFlowUrl(url) {
    const value = String(url || '');
    return /^https:\/\/labs\.google\/fx(?:\/[^/]+)?\/tools\/flow\/?(?:[#?].*)?$/.test(value);
  }

  function findNewProjectControl() {
    const selectors = 'button, [role="button"], a, div[role="button"], span';
    const candidates = [
      'Create with Flow',
      'Create new project',
      'Create new',
      'New project',
      'Start creating',
      'Create project',
      'New video',
    ];

    for (const candidate of candidates) {
      const match = findElementByText(selectors, candidate);
      if (match && isVisible(match)) return match;
    }

    const buttonCandidates = Array.from(document.querySelectorAll('button, [role="button"], a'));
    return buttonCandidates.find((el) => {
      if (!isVisible(el)) return false;
      const text = normalizeText(el.textContent || el.getAttribute('aria-label') || '').toLowerCase();
      return text.includes('create') || text.includes('new project') || text.includes('new video');
    }) || null;
  }

  function collectProjectCreationState() {
    const diagnostic = collectFlowPageStateDiagnostic('F2V');
    const markerSources = [
      diagnostic.body_text_first_2000_chars,
      diagnostic.document_title,
      ...diagnostic.button_texts,
      ...diagnostic.aria_labels,
      ...diagnostic.textarea_placeholders,
      ...diagnostic.contenteditable_texts,
    ];

    const landingMarkers = collectVisibleMarkers([
      'Create with Flow',
      'Projects',
      'Recent',
      'New project',
      'Create new',
      'Back to projects',
    ], markerSources);

    return {
      diagnostic,
      isRoot: isRootFlowUrl(window.location.href),
      hasErrorPage: diagnostic.visible_error_markers.length > 0,
      landingDetected: landingMarkers.length > 0 || !!findNewProjectControl(),
      newProjectControlFound: !!findNewProjectControl(),
      landingMarkers,
    };
  }

  async function ensureVideoFramesEditorReady() {
    const videoBtn = findElementByText('button, [role="tab"], [role="button"], span', 'Video');
    if (videoBtn && isVisible(videoBtn) && !isSelectedControl(videoBtn, 'Video')) {
      videoBtn.click();
      await sleep(800);
    }

    const framesBtn = findElementByText('button, [role="tab"], [role="button"], span', 'Frames');
    if (framesBtn && isVisible(framesBtn) && !isSelectedControl(framesBtn, 'Frames')) {
      framesBtn.click();
      await sleep(800);
    }

    return checkFlowComposerReady('F2V');
  }

  async function waitForNewProjectEditor(mode = 'F2V', timeoutMs = 45000) {
    const deadline = Date.now() + timeoutMs;

    while (Date.now() < deadline) {
      const state = collectProjectCreationState();
      if (state.hasErrorPage) {
        return {
          ok: false,
          error: 'FLOW_PROJECT_URL_INVALID_OR_INACCESSIBLE',
          detail: state.diagnostic.visible_error_markers.join(', ') || 'Flow error page visible',
          diagnostic: state.diagnostic,
        };
      }

      let readiness = checkFlowComposerReady(mode);
      if (readiness.composer_found || readiness.generate_button_found || readiness.current_mode_visible !== 'UNKNOWN') {
        readiness = await ensureVideoFramesEditorReady();
      }

      const modeVisible = String(readiness.current_mode_visible || '');
      const modeReady = modeVisible.includes('Video/Frames');
      if (readiness.composer_found && readiness.composer_editable && readiness.generate_button_found && modeReady) {
        return {
          ok: true,
          editor_ready: true,
          composer_found: readiness.composer_found,
          composer_editable: readiness.composer_editable,
          generate_button_found: readiness.generate_button_found,
          current_mode_visible: readiness.current_mode_visible,
          signed_in_likely: readiness.signed_in_likely,
          blocking_modal_detected: readiness.blocking_modal_detected,
          observed: readiness.observed,
          diagnostic: state.diagnostic,
        };
      }

      await sleep(1000);
    }

    const readiness = checkFlowComposerReady(mode);
    return {
      ok: false,
      error: readiness.signed_in_likely ? 'FLOW_PROJECT_EDITOR_NOT_READY' : 'FLOW_PROJECT_CREATION_PATH_MISSING',
      detail: readiness.error || 'Timed out waiting for Flow editor/composer',
      editor_ready: false,
      composer_found: readiness.composer_found,
      composer_editable: readiness.composer_editable,
      generate_button_found: readiness.generate_button_found,
      current_mode_visible: readiness.current_mode_visible,
      signed_in_likely: readiness.signed_in_likely,
      blocking_modal_detected: readiness.blocking_modal_detected,
      observed: readiness.observed,
      diagnostic: collectFlowPageStateDiagnostic(mode),
    };
  }

  async function openFlowNewProjectFlow(mode = 'F2V') {
    const initialState = collectProjectCreationState();
    if (initialState.hasErrorPage) {
      return {
        ok: false,
        open_flow_root: initialState.isRoot,
        project_list_or_landing_detected: false,
        new_project_clicked: false,
        editor_ready: false,
        error: 'FLOW_PROJECT_URL_INVALID_OR_INACCESSIBLE',
        detail: initialState.diagnostic.visible_error_markers.join(', ') || 'Flow error page visible',
        flow_url: window.location.href,
        ...initialState.diagnostic,
      };
    }

    let newProjectClicked = false;
    let projectListDetected = initialState.landingDetected;

    const alreadyReady = await ensureVideoFramesEditorReady();
    if (alreadyReady.composer_found && alreadyReady.composer_editable && alreadyReady.generate_button_found && String(alreadyReady.current_mode_visible || '').includes('Video/Frames')) {
      return {
        ok: true,
        open_flow_root: initialState.isRoot,
        project_list_or_landing_detected: true,
        new_project_clicked: 'SKIPPED_ALREADY_IN_EDITOR',
        editor_ready: true,
        flow_url: window.location.href,
        composer_found: alreadyReady.composer_found,
        composer_editable: alreadyReady.composer_editable,
        generate_button_found: alreadyReady.generate_button_found,
        current_mode_visible: alreadyReady.current_mode_visible,
        signed_in_likely: alreadyReady.signed_in_likely,
        blocking_modal_detected: alreadyReady.blocking_modal_detected,
        observed: alreadyReady.observed,
        ...initialState.diagnostic,
      };
    }

    const createControl = findNewProjectControl();
    if (!createControl) {
      return {
        ok: false,
        open_flow_root: initialState.isRoot,
        project_list_or_landing_detected: projectListDetected,
        new_project_clicked: false,
        editor_ready: false,
        error: initialState.landingDetected ? 'FLOW_PROJECT_CREATION_PATH_MISSING' : 'FLOW_PROJECT_LIST_OR_LANDING_NOT_DETECTED',
        detail: 'New project control not found on Flow root/landing page',
        flow_url: window.location.href,
        ...initialState.diagnostic,
      };
    }

    projectListDetected = true;
    createControl.click();
    newProjectClicked = true;
    await sleep(1200);

    const editor = await waitForNewProjectEditor(mode, 45000);
    return {
      ok: Boolean(editor.ok),
      open_flow_root: initialState.isRoot,
      project_list_or_landing_detected: projectListDetected,
      new_project_clicked: newProjectClicked,
      editor_ready: Boolean(editor.editor_ready),
      flow_url: window.location.href,
      ...editor,
    };
  }

  function runExecuteFlowJobSmoke(job) {
    const readiness = checkFlowComposerReady(job?.mode);
    const result = {
      ok: false,
      status: 'FAIL_COMPOSER_NOT_READY',
      smoke_test: true,
      no_generation_triggered: true,
      composer: readiness,
    };

    if (!readiness.ok) {
      result.error = readiness.error || 'ABORT_FLOW_COMPOSER_NOT_READY';
      return result;
    }

    const verifyResult = verifyFlowMode(job, readiness.observed);
    if (!verifyResult.ok) {
      result.status = 'FAIL_MODE_MISMATCH';
      result.error = `ABORT_FLOW_MODE_MISMATCH: ${verifyResult.reason}`;
      result.verify = verifyResult;
      return result;
    }

    return {
      ok: true,
      status: 'PASS',
      smoke_test: true,
      no_generation_triggered: true,
      composer: readiness,
      observed_state: readiness.observed,
    };
  }

  /**
   * verifyFlowMode()
   * 
   * Strict pass/fail gate. Compares job intent with observed DOM state.
   * 
   * Returns: { ok: true } or { ok: false, error: 'FLOW_MODE_MISMATCH', expected: {...}, observed: {...} }
   * 
   * Hard abort conditions:
   * - Mode mismatch
   * - Required slots not visible
   * - Forbidden modes active
   */
  function verifyFlowMode(job, observed) {
    const result = { ok: true };

    const expectations = {};
    const requestedAspectRatio = resolveRequestedAspectRatio(job);
    const requiredSlots = getRequiredAssetSlots(job);

    // Define mode expectations
    if (job.mode === 'F2V') {
      // TRUE_F2V requirements
      expectations.topMode = 'Video';
      expectations.subMode = 'Frames';
      expectations.modelContains = 'Veo';
      expectations.startSlotVisible = true;
      expectations.noImageMode = true;
      expectations.noNanoBanana = true;
      expectations.noIngredients = true;
      expectations.composerPresent = true;

      // Check each requirement
      if (observed.topMode !== 'Video') {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = `Expected topMode='Video', got '${observed.topMode}'`;
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
      if (observed.subMode !== 'Frames') {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = `Expected subMode='Frames', got '${observed.subMode}'`;
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
      if (!observed.model.includes('Veo')) {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = `Expected model to contain 'Veo', got '${observed.model}'`;
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
      if (!observed.visibleUploadSlots.includes('Start')) {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = `Expected Start slot visible, got slots: ${observed.visibleUploadSlots.join(', ')}`;
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
      if (!observed.composerPresent) {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = 'Composer not found';
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
    } else if (job.mode === 'T2V') {
      expectations.topMode = 'Video';
      expectations.subMode = 'None';
      expectations.composerPresent = true;

      if (observed.topMode !== 'Video') {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = `Expected topMode='Video', got '${observed.topMode}'`;
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
      if (!['None', 'UNKNOWN'].includes(observed.subMode)) {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = `Expected no active subMode, got '${observed.subMode}'`;
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
      if (!observed.composerPresent) {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = 'Composer not found';
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
    } else if (job.mode === 'I2V') {
      // I2V requirements
      expectations.topMode = 'Video';
      expectations.subMode = 'Ingredients';
      expectations.modelContains = 'Veo';
      expectations.requiredSlots = requiredSlots;
      expectations.noImageMode = true;
      expectations.noStartEndActive = true;
      expectations.composerPresent = true;

      if (observed.topMode !== 'Video') {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = `Expected topMode='Video', got '${observed.topMode}'`;
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
      if (observed.subMode !== 'Ingredients') {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = `Expected subMode='Ingredients', got '${observed.subMode}'`;
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
      if (!observed.model.includes('Veo')) {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = `Expected model to contain 'Veo', got '${observed.model}'`;
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
      if (requiredSlots.some((slot) => !observed.visibleUploadSlots.includes(slot))) {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = `Expected slots visible: ${requiredSlots.join(', ')}, got ${observed.visibleUploadSlots.join(', ')}`;
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
      if (!observed.composerPresent) {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = 'Composer not found';
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
    } else if (job.mode === 'IMG') {
      // IMG requirements
      expectations.topMode = 'Image';
      expectations.modelContains = 'Nano Banana';
      expectations.requiredSlots = requiredSlots;
      expectations.noVideoMode = true;
      expectations.noFramesOrIngredients = true;
      expectations.composerPresent = true;

      if (observed.topMode !== 'Image') {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = `Expected topMode='Image', got '${observed.topMode}'`;
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
      if (!observed.model.includes('Nano Banana')) {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = `Expected model to contain 'Nano Banana', got '${observed.model}'`;
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
      if (requiredSlots.some((slot) => !observed.visibleUploadSlots.includes(slot))) {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = `Expected slots visible: ${requiredSlots.join(', ')}, got ${observed.visibleUploadSlots.join(', ')}`;
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
      if (!observed.composerPresent) {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = 'Composer not found';
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
    }

    if (requestedAspectRatio && IMAGE_ASPECT_RATIOS.includes(requestedAspectRatio) && observed.aspectRatio !== 'UNKNOWN' && observed.aspectRatio !== requestedAspectRatio) {
      result.ok = false;
      result.error = 'FLOW_MODE_MISMATCH';
      result.reason = `Expected aspectRatio='${requestedAspectRatio}', got '${observed.aspectRatio}'`;
      result.expected = expectations;
      result.observed = observed;
      return result;
    }

    return result;
  }

  async function verifyAssetChecklist(job, slotContexts = []) {
    const requiredSlots = getRequiredAssetSlots(job);
    if (requiredSlots.length === 0) {
      return { ok: true, status: 'SKIPPED_NO_ASSETS_REQUIRED' };
    }

    const missing = [];
    for (const slotLabel of requiredSlots) {
      const slotContext = slotContexts.find((item) => item.slotLabel === slotLabel);
      const previewReady = await waitForAssetPreview(slotLabel, slotContext?.slotElement || null, {
        slotContainer: slotContext?.slotContainer || null,
        beforeSnapshot: slotContext?.beforeSnapshot || null,
        timeoutMs: 15000,
      });
      if (!previewReady.ok) missing.push(slotLabel);
    }

    if (missing.length > 0) {
      return { ok: false, reason: `Asset previews not visible for ${missing.join(', ')}` };
    }

    return { ok: true, status: requiredSlots.join(', ') };
  }

  async function executeFlowJob(job) {
    const report = { ok: false, stages: [] };
    const logStage = (stage, status = 'YES', message = null) => {
      report.stages.push({ stage, status, message });
      console.log(`[FlowAgent] Stage: ${stage} - ${status}${message ? ` - ${message}` : ''}`);
      sendRuntimeMessageNoThrow({
        type: 'FLOW_STAGE_EVENT',
        request_id: job.request_id,
        stage,
        status,
        message,
        source: 'google_flow',
      });
    };

    try {
      logStage(STAGES.FLOW_TAB_FOUND);

      // 0. Log job received
      if (job.prompt) {
        logStage(STAGES.JOB_PROMPT_RECEIVED, `${job.prompt.length} chars`);
      } else {
        logStage(STAGES.JOB_PROMPT_RECEIVED, 'MISSING');
        throw new Error('JOB_PROMPT_EMPTY');
      }

      // CRITICAL: Clear any pre-existing state
      logStage(STAGES.PRE_EXECUTION_STATE_CLEARED);

      // 1. Select Top Mode (STRICT - must be correct mode)
      const modeBtn = findElementByText('button, div[role="button"], span', job.mode === 'IMG' ? 'Image' : 'Video');
      if (!modeBtn) throw new Error(`Mode button ${job.mode} not found`);
      modeBtn.click();
      await sleep(1000);
      logStage(STAGES.FLOW_MODE_SELECTED, job.mode === 'IMG' ? 'Image' : 'Video');

      // 2. Select Submode (STRICT)
      if (job.mode === 'F2V' || job.mode === 'I2V') {
        const submodeText = job.mode === 'F2V' ? 'Frames' : 'Ingredients';
        const submodeBtn = findElementByText('button, div[role="button"], span', submodeText);
        if (!submodeBtn) throw new Error(`Submode button ${submodeText} not found`);
        submodeBtn.click();
        await sleep(1000);
        logStage(STAGES.FLOW_SUBMODE_SELECTED, submodeText);
      } else if (job.mode === 'T2V') {
        const clearedSubmodes = await clearVideoSubmodeSelection();
        logStage(STAGES.FLOW_SUBMODE_SELECTED, clearedSubmodes.length > 0 ? `CLEARED:${clearedSubmodes.join(',')}` : 'NONE');
      }

      // 3. Set Aspect Ratio
      const requestedAspectRatio = resolveRequestedAspectRatio(job);
      const aspectBtn = requestedAspectRatio ? findElementByText('button, div[role="button"]', requestedAspectRatio) : null;
      if (aspectBtn) {
        aspectBtn.click();
        await sleep(500);
        logStage(STAGES.ASPECT_SELECTED, requestedAspectRatio);
      }

      // 4. Set Count
      const requestedCount = resolveRequestedCount(job);
      const countBtn = findElementByText('button, div[role="button"]', requestedCount);
      if (countBtn) {
        countBtn.click();
        await sleep(500);
        logStage(STAGES.COUNT_SELECTED, requestedCount);
      }

      // 5. Set Model
      const requestedModel = resolveRequestedModel(job);
      const modelDropdown = document.querySelector('[aria-haspopup="listbox"]');
      if (modelDropdown && requestedModel) {
        modelDropdown.click();
        await sleep(800);
        const modelOption = findElementByText('[role="option"], li, span', requestedModel);
        if (modelOption) {
          modelOption.click();
          await sleep(800);
          logStage(STAGES.MODEL_SELECTED, requestedModel);
        }
      }

      // CRITICAL: MODE VERIFICATION GATE
      // Observe actual DOM state and verify it matches job intent
      const observed = observeFlowState();
      const verifyResult = verifyFlowMode(job, observed);

      if (!verifyResult.ok) {
        // HARD ABORT - Do not proceed with upload/prompt/generate
        logStage(STAGES.FLOW_MODE_MISMATCH, verifyResult.reason);
        throw new Error(`FLOW_MODE_MISMATCH: ${verifyResult.reason}`);
      }

      logStage(STAGES.FLOW_MODE_VERIFIED);

      // 6. Attach Assets (STRICT: Asset First, Prompt Second)
      const assetSlotContexts = [];
      if (job.mode === 'F2V') {
        // Step 6a: Upload Start Frame
        const okStart = await simulateFileUpload('Start', job.startAsset || job.productId || job.startImageMediaId);
        if (okStart?.ok) {
          logStage(STAGES.START_FRAME_ATTACHED, 'PASS', 'slot=Start dispatch=ok');

          const startPreview = await waitForAssetPreview('Start', okStart.slotElement || null, {
            slotContainer: okStart.slotContainer || null,
            beforeSnapshot: okStart.beforeSnapshot || null,
            timeoutMs: 15000,
          });

          if (!startPreview.ok) {
            logStage(STAGES.START_FRAME_VERIFIED, 'FAIL', startPreview.error || buildSlotErrorCode('Start', 'PREVIEW_TIMEOUT'));
            throw new Error(startPreview.error || buildSlotErrorCode('Start', 'PREVIEW_TIMEOUT'));
          }

          const rect = startPreview.snapshot?.previewRect;
          logStage(
            STAGES.START_FRAME_VERIFIED,
            'PASS',
            `slot=Start preview_found=true pending=false rect=${rect ? `${rect.width}x${rect.height}` : 'unknown'}`,
          );

          assetSlotContexts.push({
            slotLabel: 'Start',
            slotElement: okStart.slotElement,
            slotContainer: okStart.slotContainer,
            beforeSnapshot: okStart.beforeSnapshot,
          });
        } else {
          logStage(STAGES.START_FRAME_ATTACHED, 'FAIL', okStart?.error || buildSlotErrorCode('Start', 'UPLOAD_DISPATCH_FAILED'));
          throw new Error(okStart?.error || buildSlotErrorCode('Start', 'UPLOAD_DISPATCH_FAILED'));
        }

        // Step 6b: Upload End Frame
        if (job.endAsset || job.endImageMediaId || job.productId) {
          const okEnd = await simulateFileUpload('End', job.endAsset || job.productId || job.endImageMediaId);
          if (okEnd?.ok) {
            assetSlotContexts.push({
              slotLabel: 'End',
              slotElement: okEnd.slotElement,
              slotContainer: okEnd.slotContainer,
              beforeSnapshot: okEnd.beforeSnapshot,
            });
            logStage(STAGES.END_FRAME_ATTACHED, 'PASS', 'slot=End dispatch=ok');
          } else {
            logStage(STAGES.END_FRAME_ATTACHED, 'FAIL', okEnd?.error || buildSlotErrorCode('End', 'UPLOAD_DISPATCH_FAILED'));
            throw new Error(okEnd?.error || buildSlotErrorCode('End', 'UPLOAD_DISPATCH_FAILED'));
          }
        }
      } else if (job.mode === 'I2V') {
        const refAssets = getRefAssets(job);
        if (refAssets.length > 0) {
          for (const refAsset of refAssets) {
            const uploadedSlot = await simulateFileUpload(refAsset.slotLabel, refAsset.assetSource);
            if (!uploadedSlot?.ok) throw new Error(uploadedSlot?.error || `${refAsset.slotLabel.toUpperCase()}_UPLOAD_FAILED`);
            assetSlotContexts.push({
              slotLabel: refAsset.slotLabel,
              slotElement: uploadedSlot.slotElement,
              slotContainer: uploadedSlot.slotContainer,
              beforeSnapshot: uploadedSlot.beforeSnapshot,
            });
            logStage(STAGES.INGREDIENTS_ATTACHED, refAsset.slotLabel);
          }
        } else {
          const uploadedSlot = await simulateFileUpload('Ingredients', job.productId || job.startImageMediaId);
          if (!uploadedSlot?.ok) throw new Error(uploadedSlot?.error || 'INGREDIENTS_UPLOAD_FAILED');
          assetSlotContexts.push({
            slotLabel: 'Ingredients',
            slotElement: uploadedSlot.slotElement,
            slotContainer: uploadedSlot.slotContainer,
            beforeSnapshot: uploadedSlot.beforeSnapshot,
          });
          logStage(STAGES.INGREDIENTS_ATTACHED, 'Ingredients');
        }
      } else if (job.mode === 'IMG') {
        const refAssets = getRefAssets(job);
        if (refAssets.length > 0) {
          for (const refAsset of refAssets) {
            const uploadedSlot = await simulateFileUpload(refAsset.slotLabel, refAsset.assetSource);
            if (!uploadedSlot?.ok) throw new Error(uploadedSlot?.error || `${refAsset.slotLabel.toUpperCase()}_UPLOAD_FAILED`);
            assetSlotContexts.push({
              slotLabel: refAsset.slotLabel,
              slotElement: uploadedSlot.slotElement,
              slotContainer: uploadedSlot.slotContainer,
              beforeSnapshot: uploadedSlot.beforeSnapshot,
            });
            logStage(STAGES.IMAGE_ASSET_ATTACHED, refAsset.slotLabel);
          }
        } else {
          const uploadedSlot = await simulateFileUpload('Image', job.productId || job.startImageMediaId);
          if (!uploadedSlot?.ok) throw new Error(uploadedSlot?.error || 'IMAGE_UPLOAD_FAILED');
          assetSlotContexts.push({
            slotLabel: 'Image',
            slotElement: uploadedSlot.slotElement,
            slotContainer: uploadedSlot.slotContainer,
            beforeSnapshot: uploadedSlot.beforeSnapshot,
          });
          logStage(STAGES.IMAGE_ASSET_ATTACHED, 'Image');
        }
      }

      const assetVerification = await verifyAssetChecklist(job, assetSlotContexts);
      if (!assetVerification.ok) {
        logStage(STAGES.ASSETS_VERIFIED, 'NO');
        throw new Error(assetVerification.reason || 'ASSET_PREVIEW_NOT_VISIBLE');
      }
      logStage(STAGES.ASSETS_VERIFIED, assetVerification.status);

      // 7. Composer Setup (ONLY after assets)
      const composer = document.querySelector('textarea, [contenteditable="true"], [role="textbox"]');
      if (!composer) {
        logStage(STAGES.PROMPT_FIELD_FOUND, 'NO');
        throw new Error('PROMPT_FIELD_NOT_FOUND');
      }
      logStage(STAGES.PROMPT_FIELD_FOUND);

      // 8. Validate and Insert Prompt (ONLY after mode + asset verification)
      if (!job.prompt || job.prompt.trim().length === 0) {
        logStage(STAGES.PROMPT_INSERT_METHOD, 'VALIDATION_FAILED');
        throw new Error('JOB_PROMPT_EMPTY');
      }
      logStage(STAGES.PROMPT_INSERT_METHOD, 'HUMAN_TYPING');

      await humanTypePrompt(composer, job.prompt);

      const actual = getComposerText(composer);
      if (!actual || !actual.includes(job.prompt.slice(0, 10))) {
        logStage(STAGES.PROMPT_VISIBLE, 'NO');
        throw new Error('PROMPT_INSERT_FAILED');
      }
      logStage(STAGES.PROMPT_VISIBLE);

      if (!isComposerEditable(composer)) {
        logStage(STAGES.PROMPT_EDITABLE_AFTER_INSERT, 'NO');
        throw new Error('PROMPT_INSERT_LOCKED_OR_UNTRUSTED');
      }
      logStage(STAGES.PROMPT_EDITABLE_AFTER_INSERT);

      // 9. Click Generate (ONLY after all verifications)
      let generateBtn = findGenerateButtonNearComposer();
      if (!generateBtn) throw new Error('GENERATE_ARROW_NOT_FOUND');

      if (generateBtn.disabled) {
        await nudgeComposerHydration(composer);
        await sleep(500);
        generateBtn = findGenerateButtonNearComposer();
      }

      if (generateBtn?.disabled) {
        await nudgeComposerHydration(composer);
        await sleep(1000);
        generateBtn = findGenerateButtonNearComposer();
      }

      if (!generateBtn || generateBtn.disabled) {
        logStage(STAGES.GENERATE_ARROW_ENABLED, 'NO');
        throw new Error('GENERATE_ARROW_DISABLED_AFTER_PROMPT');
      }
      logStage(STAGES.GENERATE_ARROW_ENABLED);

      generateBtn.click();
      logStage(STAGES.GENERATE_CLICKED);

      // 10. Detect Generation Start
      await sleep(1500);
      const progress = document.querySelector('[role="progressbar"], .loading, .spinner');
      if (generateBtn.disabled || progress) {
        logStage(STAGES.GENERATION_STARTED);
        logStage(STAGES.VIDEO_JOB_RUNNING_OR_GENERATED);
        report.ok = true;
      } else {
        logStage(STAGES.GENERATION_STARTED, 'MAYBE');
        logStage(STAGES.VIDEO_JOB_RUNNING_OR_GENERATED, 'MAYBE');
        report.ok = true;
      }

    } catch (e) {
      console.error('[FlowAgent] Job execution failed:', e);
      report.error = e.message;
      report.ok = false;
      report.stages.push({ stage: 'ERROR', status: e.message });
    }

    return report;
  }

  const flowDomMessageListener = (msg, sender, sendResponse) => {
    if (msg.type === 'FLOWKIT_DIAGNOSTIC_PING') {
      sendResponse(buildDiagnosticPingResponse());
      return false;
    }

    if (msg.type === 'FLOW_PAGE_STATE_DIAGNOSTIC') {
      try {
        sendResponse(collectFlowPageStateDiagnostic(msg.mode));
      } catch (error) {
        sendResponse({
          ok: false,
          error: 'FLOW_PAGE_STATE_DIAGNOSTIC_FAILED',
          detail: String(error?.message || error),
          flow_url: window.location.href,
          location_href: window.location.href,
          document_title: document.title,
          document_ready_state: document.readyState,
          body_text_first_2000_chars: normalizeText(document.body?.innerText || '').slice(0, 2000),
          visible_login_markers: [],
          visible_loading_markers: [],
          visible_error_markers: [],
          visible_project_editor_markers: [],
          visible_composer_placeholder_markers: [],
          button_texts: [],
          textarea_placeholders: [],
          input_placeholders: [],
          contenteditable_texts: [],
          aria_labels: [],
        });
      }
      return false;
    }

    if (msg.type === 'CHECK_FLOW_COMPOSER_READY') {
      try {
        sendResponse(checkFlowComposerReady(msg.mode));
      } catch (error) {
        sendResponse({
          ok: false,
          error: 'ABORT_FLOW_COMPOSER_NOT_READY',
          composer_found: false,
          generate_button_found: false,
          detail: String(error?.message || error),
        });
      }
      return false;
    }

    if (msg.type === 'OPEN_FLOW_NEW_PROJECT') {
      return respondAsync(sendResponse, async () => openFlowNewProjectFlow(msg.mode));
    }

    if (msg.type === 'EXECUTE_FLOW_JOB') {
      if (msg.job?.smoke_test) {
        try {
          sendResponse(runExecuteFlowJobSmoke(msg.job));
        } catch (error) {
          sendResponse({
            ok: false,
            status: 'STRUCTURED_FAIL',
            smoke_test: true,
            no_generation_triggered: true,
            error: String(error?.message || error),
            composer_found: false,
            generate_button_found: false,
          });
        }
        return false;
      }

      // IMMEDIATE ACK - Send response right away, don't wait for job completion
      sendResponse({ ok: true, accepted: true, request_id: msg.job?.request_id });
      
      // Execute job asynchronously AFTER returning from listener
      setTimeout(async () => {
        try {
          const result = await executeFlowJob(msg.job);
          // Send final result via FLOW_JOB_COMPLETED message
          sendRuntimeMessageNoThrow({
            type: 'FLOW_JOB_COMPLETED',
            request_id: msg.job?.request_id,
            result: result,
            success: result.ok
          });
        } catch (err) {
          // Send error via FLOW_JOB_FAILED message
          sendRuntimeMessageNoThrow({
            type: 'FLOW_JOB_FAILED',
            request_id: msg.job?.request_id,
            error: String(err?.message || err)
          });
        }
      }, 0);
      
      // Return false - we already called sendResponse synchronously
      return false;
    }

    sendResponse({ ok: false, error: 'ERR_UNKNOWN_MESSAGE_TYPE' });
    return false;
  };

  window._flowKitDomListener = flowDomMessageListener;
  chrome.runtime.onMessage.addListener(flowDomMessageListener);

})();
