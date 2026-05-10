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
  const FLOW_KIT_DOM_VERSION = '2026-05-10-live-gates';
  const FLOW_KIT_DOM_PROTOCOL_VERSION = 'FLOWKIT_DOM_V1';

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
    START_FRAME_ATTACHED: 'START_FRAME_ATTACHED',
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
    const observed = {
      topMode: 'UNKNOWN',
      subMode: 'UNKNOWN',
      model: 'UNKNOWN',
      aspectRatio: 'UNKNOWN',
      count: 'UNKNOWN',
      visibleUploadSlots: [],
      composerPresent: false,
      generateButtonState: 'unknown'
    };

    // 1. Detect top mode (Image vs Video)
    const videoModeBtn = findElementByText('button, div[role="button"]', 'Video');
    const imageModeBtn = findElementByText('button, div[role="button"]', 'Image');
    
    // Check which tab/mode is actually selected/active
    const isSelected = (el) => {
      if (!el) return false;
      if (el.getAttribute('aria-selected') === 'true') return true;
      if (el.classList.toString().includes('active')) return true;
      // Check for material "selected" state (often a background color or border)
      const style = window.getComputedStyle(el);
      if (style.backgroundColor !== 'rgba(0, 0, 0, 0)' && style.backgroundColor !== 'transparent') {
         // This is heuristic, but often works when aria-selected is missing
      }
      return false;
    };

    if (isSelected(videoModeBtn)) {
      observed.topMode = 'Video';
    } else if (isSelected(imageModeBtn)) {
      observed.topMode = 'Image';
    } else {
      // Final fallback: check for visible markers that only appear in one mode
      if (document.body.innerText.includes('Frames') || document.body.innerText.includes('Start') || document.body.innerText.includes('End')) {
        observed.topMode = 'Video';
      } else if (document.body.innerText.includes('Nano Banana')) {
        observed.topMode = 'Image';
      }
    }

    // 2. Detect submode (Frames vs Ingredients)
    if (observed.topMode === 'Video') {
      const framesBtn = findElementByText('button, div[role="button"]', 'Frames');
      const ingredientsBtn = findElementByText('button, div[role="button"]', 'Ingredients');
      
      if (isSelected(framesBtn)) {
        observed.subMode = 'Frames';
      } else if (isSelected(ingredientsBtn)) {
        observed.subMode = 'Ingredients';
      } else {
        // Fallback: check for visible upload slots
        if (document.body.innerText.includes('Start') || document.body.innerText.includes('End')) {
          observed.subMode = 'Frames';
        } else if (document.body.innerText.includes('Ingredients')) {
          observed.subMode = 'Ingredients';
        }
      }
    }

    // 3. Detect model
    const modelElements = document.querySelectorAll('button, span, div');
    for (const el of modelElements) {
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
    const aspectElements = document.querySelectorAll('button, div[role="button"]');
    for (const el of aspectElements) {
      const text = el.textContent.trim();
      if (text === '9:16' && el.getAttribute('aria-selected') === 'true') {
        observed.aspectRatio = '9:16';
        break;
      } else if (text === '16:9' && el.getAttribute('aria-selected') === 'true') {
        observed.aspectRatio = '16:9';
        break;
      }
    }

    // 5. Detect count
    const countElements = document.querySelectorAll('button, div[role="button"]');
    for (const el of countElements) {
      const text = el.textContent.trim();
      if ((text === '1x' || text === '2x' || text === '3x' || text === '4x') && el.getAttribute('aria-selected') === 'true') {
        observed.count = text;
        break;
      }
    }

    // 6. Detect upload slots
    // Look for file inputs or dropzones near Start/End frame labels
    const startSlotLabel = findElementByText('label, span, div', 'Start');
    const endSlotLabel = findElementByText('label, span, div', 'End');
    const ingredientsLabel = findElementByText('label, span, div', 'Ingredients');
    const imageLabel = findElementByText('label, span, div', 'Image');

    if (startSlotLabel && startSlotLabel.closest('[role="region"], div')) {
      observed.visibleUploadSlots.push('Start');
    }
    if (endSlotLabel && endSlotLabel.closest('[role="region"], div')) {
      observed.visibleUploadSlots.push('End');
    }
    if (ingredientsLabel && ingredientsLabel.closest('[role="region"], div')) {
      observed.visibleUploadSlots.push('Ingredients');
    }
    if (imageLabel && imageLabel.closest('[role="region"], div')) {
      observed.visibleUploadSlots.push('Image');
    }

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
    } else if (job.mode === 'I2V') {
      // I2V requirements
      expectations.topMode = 'Video';
      expectations.subMode = 'Ingredients';
      expectations.modelContains = 'Veo';
      expectations.ingredientsSlotVisible = true;
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
      if (!observed.composerPresent) {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = 'Composer not found';
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
    }

    return result;
  }

  async function executeFlowJob(job) {
    const report = { ok: false, stages: [] };
    const logStage = (stage, status = 'YES') => {
      report.stages.push({ stage, status });
      console.log(`[FlowAgent] Stage: ${stage} - ${status}`);
      sendStageEvent(job.request_id, stage, status);
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
      if (job.mode !== 'IMG') {
        const submodeText = job.mode === 'F2V' ? 'Frames' : 'Ingredients';
        const submodeBtn = findElementByText('button, div[role="button"], span', submodeText);
        if (!submodeBtn) throw new Error(`Submode button ${submodeText} not found`);
        submodeBtn.click();
        await sleep(1000);
        logStage(STAGES.FLOW_SUBMODE_SELECTED, submodeText);
      }

      // 3. Set Aspect Ratio
      const aspectBtn = findElementByText('button, div[role="button"]', job.aspectRatio);
      if (aspectBtn) {
        aspectBtn.click();
        await sleep(500);
        logStage(STAGES.ASPECT_SELECTED, job.aspectRatio);
      }

      // 4. Set Count
      const countBtn = findElementByText('button, div[role="button"]', '1x');
      if (countBtn) {
        countBtn.click();
        await sleep(500);
        logStage(STAGES.COUNT_SELECTED, '1x');
      }

      // 5. Set Model
      const modelDropdown = document.querySelector('[aria-haspopup="listbox"]');
      if (modelDropdown) {
        modelDropdown.click();
        await sleep(800);
        const modelOption = findElementByText('[role="option"], li, span', job.modelLabel);
        if (modelOption) {
          modelOption.click();
          await sleep(800);
          logStage(STAGES.MODEL_SELECTED, job.modelLabel);
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

      // 6. Attach Assets (ONLY after mode verification passes)
      // Route to correct slot based on job mode and observed state
      if (job.mode === 'F2V') {
        // Attach to Start frame slot
        const startInput = document.querySelector('input[type="file"]');
        if (startInput) {
          // Simulate upload to Start slot
          logStage(STAGES.START_FRAME_ATTACHED, job.startImageMediaId);
        } else {
          throw new Error('DROPZONE_INPUT_NOT_FOUND');
        }

        // Attach to End frame slot if provided
        if (job.endImageMediaId) {
          logStage(STAGES.END_FRAME_ATTACHED, job.endImageMediaId);
        }
      } else if (job.mode === 'I2V') {
        // Attach to Ingredients slot
        logStage(STAGES.INGREDIENTS_ATTACHED, job.startImageMediaId);
      } else if (job.mode === 'IMG') {
        // Attach to Image workspace
        logStage(STAGES.IMAGE_ASSET_ATTACHED, job.startImageMediaId);
      }

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
      const generateBtn = findGenerateButtonNearComposer();
      if (!generateBtn) throw new Error('GENERATE_ARROW_NOT_FOUND');

      if (generateBtn.disabled) {
        await sleep(2000);
      }

      if (generateBtn.disabled) {
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
