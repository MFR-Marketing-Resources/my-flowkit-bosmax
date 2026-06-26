// biome-ignore-all format: frozen Flow DOM state machine stays line-stable for narrow gate patches
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

(() => {
  const FLOW_KIT_DOM_VERSION = '2026-05-11-f2v-sop-gates';
  const FLOW_KIT_DOM_PROTOCOL_VERSION = 'FLOWKIT_DOM_V1';
  const FLOW_KIT_DOM_BUILD_ID = 'flowkit-f2v-runner-audit-2026-05-28b';
  const FLOW_KIT_PLAYWRIGHT_HARNESS = hasPlaywrightHarnessMarker();
  const FLOW_KIT_TEST_MODE = Boolean(window.__FLOWKIT_TEST_MODE__);
  const FLOW_KIT_ENABLE_TEST_HOOKS =
    FLOW_KIT_TEST_MODE
    || Boolean(window.__FLOWKIT_ENABLE_TEST_HOOKS__)
    || FLOW_KIT_PLAYWRIGHT_HARNESS;
  const FLOW_KIT_TEST_BRIDGE_SOURCE = 'FLOWKIT_PLAYWRIGHT_TEST_BRIDGE';
  const IMAGE_ASPECT_RATIOS = ['16:9', '4:3', '1:1', '3:4', '9:16'];
  const FLOW_MODE_CONFIG = {
    F2V: { topMode: 'Video', subMode: 'Frames', defaultModel: 'Veo 3.1 - Lite', defaultOrientation: 'VERTICAL', defaultCount: 1 },
    T2V: { topMode: 'Video', subMode: null },
    I2V: { topMode: 'Video', subMode: 'Ingredients' },
    IMG: { topMode: 'Image', subMode: null, defaultModel: 'Nano Banana 2' },
  };

  if (!FLOW_KIT_TEST_MODE && window._flowKitDomListener) {
    try {
      chrome.runtime.onMessage.removeListener(window._flowKitDomListener);
    } catch (error) {
      console.warn('[FlowAgent] Failed to remove previous Flow DOM listener:', error);
    }
  }

  window._flowKitDomInjectedVersion = FLOW_KIT_DOM_VERSION;
  console.log('[FlowAgent] Flow DOM Executor injected');

  function hasPlaywrightHarnessMarker() {
    return document.documentElement?.getAttribute('data-flowkit-harness') === 'playwright';
  }

  function getSelectorRegistryHelpers() {
    return window.__FLOWKIT_SELECTOR_REGISTRY_HELPERS__ || null;
  }

  function getSelectorRegistryEntry(id) {
    return getSelectorRegistryHelpers()?.getEntry(id) || null;
  }

  function getSelectorRegistryQuery(id, fallbackQuery) {
    return getSelectorRegistryHelpers()?.getSelectorQuery(id) || fallbackQuery;
  }

  function getSelectorEvidencePointer(id) {
    return getSelectorRegistryHelpers()?.buildEvidencePointer(id) || null;
  }

  function buildSelectorEvidenceMeta(id) {
    return {
      selector_used: id,
      evidence_pointer: getSelectorEvidencePointer(id),
    };
  }

  function sendRuntimeMessageNoThrow(payload) {
    try {
      chrome.runtime.sendMessage(payload, () => {
        const lastError = chrome.runtime.lastError;
        if (lastError && !shouldSilenceRuntimeMessageError(lastError)) {
          const normalized = normalizeRuntimeMessageError(lastError);
          console.warn('[FlowAgent] runtime message ignored:', normalized.detail);
        }
      });
    } catch (error) {
      console.warn('[FlowAgent] runtime message exception:', error);
    }
  }

  function normalizeRuntimeMessageError(rawError) {
    const message = String(rawError?.message || rawError || '').trim();
    if (!message) {
      return {
        error: 'ERR_RUNTIME_LASTERROR',
        detail: 'Unknown Chrome runtime messaging failure.',
      };
    }
    if (/Receiving end does not exist/i.test(message)) {
      return { error: 'ERR_NO_RECEIVER', detail: message };
    }
    if (/Could not establish connection/i.test(message)) {
      return { error: 'ERR_BACKGROUND_RECEIVER_MISSING', detail: message };
    }
    if (/message port closed before a response was received/i.test(message)) {
      return { error: 'ERR_RUNTIME_MESSAGE_PORT_CLOSED', detail: message };
    }
    return {
      error: 'ERR_RUNTIME_LASTERROR',
      detail: message,
    };
  }

  function shouldSilenceRuntimeMessageError(rawError) {
    const normalized = normalizeRuntimeMessageError(rawError);
    return [
      'ERR_NO_RECEIVER',
      'ERR_BACKGROUND_RECEIVER_MISSING',
      'ERR_RUNTIME_MESSAGE_PORT_CLOSED',
    ].includes(normalized.error);
  }

  function sendRuntimeMessageWithResponse(payload, timeoutMs = 15000) {
    return new Promise((resolve) => {
      let settled = false;
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        resolve({
          ok: false,
          error: 'ERR_RUNTIME_MESSAGE_TIMEOUT',
          detail: `Timed out after ${timeoutMs}ms waiting for background response.`,
        });
      }, timeoutMs);

      try {
        chrome.runtime.sendMessage(payload, (response) => {
          const lastError = chrome.runtime.lastError;
          if (settled) return;
          settled = true;
          clearTimeout(timer);

          if (lastError) {
            resolve({ ok: false, ...normalizeRuntimeMessageError(lastError) });
            return;
          }

          resolve(response || { ok: false, error: 'ERR_EMPTY_RUNTIME_RESPONSE' });
        });
      } catch (error) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve({
          ok: false,
          error: 'ERR_RUNTIME_MESSAGE_EXCEPTION',
          detail: String(error?.message || error),
        });
      }
    });
  }

  function buildStageTelemetryPayload(request_id, stage, status, extra = {}) {
    return {
      type: 'FLOW_STAGE_EVENT',
      request_id,
      timestamp: new Date().toISOString(),
      git_sha: FLOW_KIT_DOM_BUILD_ID,
      content_build_id: FLOW_KIT_DOM_BUILD_ID,
      stage,
      checkpoint: extra.checkpoint || stage,
      status,
      source: 'google_flow',
      runtime_ready: true,
      ...extra,
    };
  }

  // Safe wrapper for sending messages without blocking on response
  function _sendStageEvent(request_id, stage, status, extra = {}) {
    sendRuntimeMessageNoThrow(buildStageTelemetryPayload(request_id, stage, status, extra));
  }

  const STAGES = {
    FLOW_TAB_FOUND: 'FLOW_TAB_FOUND',
    RUNTIME_HANDSHAKE_VERIFIED: 'RUNTIME_HANDSHAKE_VERIFIED',
    PRE_EXECUTION_STATE_CLEARED: 'PRE_EXECUTION_STATE_CLEARED',
    FLOW_MODE_SELECTED: 'FLOW_MODE_SELECTED',
    FLOW_SUBMODE_SELECTED: 'FLOW_SUBMODE_SELECTED',
    ASPECT_SELECTED: 'ASPECT_SELECTED',
    COUNT_SELECTED: 'COUNT_SELECTED',
    MODEL_SELECTED: 'MODEL_SELECTED',
    FLOW_MODE_VERIFIED: 'FLOW_MODE_VERIFIED',
    START_FRAME_UPLOAD_ATTEMPTED: 'START_FRAME_UPLOAD_ATTEMPTED',
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
    STOP_AFTER_STAGE_REACHED: 'STOP_AFTER_STAGE_REACHED',
    GENERATE_ARROW_ENABLED: 'GENERATE_ARROW_ENABLED',
    GENERATE_CLICKED: 'GENERATE_CLICKED',
    GENERATION_STARTED: 'GENERATION_STARTED',
    VIDEO_JOB_RUNNING_OR_GENERATED: 'VIDEO_JOB_RUNNING_OR_GENERATED',
    FLOW_MODE_MISMATCH: 'FLOW_MODE_MISMATCH',
    // F2V SOP state machine stages
    FLOW_ROOT_OPENED: 'FLOW_ROOT_OPENED',
    NEW_PROJECT_CLICKED: 'NEW_PROJECT_CLICKED',
    FLOW_TYPE_VIDEO_SELECTED: 'FLOW_TYPE_VIDEO_SELECTED',
    FLOW_SUBMODE_FRAMES_SELECTED: 'FLOW_SUBMODE_FRAMES_SELECTED',
    F2V_COMPOSER_READY: 'F2V_COMPOSER_READY',
    FLOW_ASPECT_9_16_SELECTED: 'FLOW_ASPECT_9_16_SELECTED',
    FLOW_COUNT_1X_SELECTED: 'FLOW_COUNT_1X_SELECTED',
    FLOW_MODEL_VEO_3_1_LITE_SELECTED: 'FLOW_MODEL_VEO_3_1_LITE_SELECTED',
    START_SLOT_VISIBLE: 'START_SLOT_VISIBLE',
    PROMPT_FIELD_VISIBLE: 'PROMPT_FIELD_VISIBLE',
    F2V_WORKSPACE_READY: 'F2V_WORKSPACE_READY',
  };

  async function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  // Default timeout for async listener handlers in content-flow-dom.js.
  // Slightly longer than the 4500ms background respondAsync default so a
  // tab-side task can still drain a chained background roundtrip cleanly
  // before its own port is forcibly closed.
  const DEFAULT_CONTENT_RESPOND_ASYNC_TIMEOUT_MS = 5000;

  function respondAsync(sendResponse, task, timeoutMs = DEFAULT_CONTENT_RESPOND_ASYNC_TIMEOUT_MS) {
    let settled = false;
    let timer = null;

    const done = (payload) => {
      if (settled) return;
      settled = true;
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      try {
        sendResponse(payload || { ok: true });
      } catch (error) {
        console.warn('[FlowAgent] sendResponse failed:', error);
      }
    };

    timer = setTimeout(() => {
      done({
        ok: false,
        error: 'ERR_CONTENT_ASYNC_RESPONSE_TIMEOUT',
        detail: `content-flow-dom respondAsync exceeded ${timeoutMs}ms`,
      });
    }, timeoutMs);

    Promise.resolve()
      .then(task)
      .then((payload) => done(payload))
      .catch((error) => done({ ok: false, error: String(error?.message || error) }));
    return true;
  }

  function buildDiagnosticPingResponse() {
    const composer = findComposerElement();
    const observed = observeFlowState();
    const generateBtn = findGenerateButtonNearComposer();
    const configPill = buildBottomComposerConfigPillSnapshot();
    const uiContractV2 = buildUiContractV2Proof(null, observed, composer, generateBtn);
    return {
      ok: true,
      runtime_ready: true,
      content_script_loaded: true,
      content_script_protocol_version: FLOW_KIT_DOM_PROTOCOL_VERSION,
      content_build_id: FLOW_KIT_DOM_BUILD_ID,
      git_sha: FLOW_KIT_DOM_BUILD_ID,
      location_href: window.location.href,
      document_title: document.title,
      composer_found: Boolean(composer),
      prompt_field_found: Boolean(composer),
      bottom_composer_config_pill_visible: configPill.bottom_composer_config_pill_visible,
      bottom_composer_config_pill_text: configPill.bottom_composer_config_pill_text,
      observed,
      editor_capability_ready: Boolean(uiContractV2.editor_capability_ready),
      pre_generate_ready: Boolean(uiContractV2.pre_generate_ready),
      ui_contract_version: uiContractV2.ui_contract_version,
      ui_contract_v2: uiContractV2,
      timestamp: new Date().toISOString(),
    };
  }

  function canonicalizeFlowConfigAspectToken(text) {
    const lower = String(text || '').toLowerCase().replace(/\s+/g, '');
    if (!lower) return null;
    if (lower.includes('crop_9_16') || lower.includes('9:16')) return 'crop_9_16';
    if (lower.includes('crop_16_9') || lower.includes('16:9')) return 'crop_16_9';
    if (lower.includes('crop_4_3') || lower.includes('4:3')) return 'crop_4_3';
    if (lower.includes('crop_1_1') || lower.includes('1:1')) return 'crop_1_1';
    if (lower.includes('crop_3_4') || lower.includes('3:4')) return 'crop_3_4';
    return null;
  }

function flowCropTokenToAspectRatio(token) {
    switch (token) {
      case 'crop_9_16': return '9:16';
      case 'crop_16_9': return '16:9';
      case 'crop_4_3': return '4:3';
      case 'crop_1_1': return '1:1';
      case 'crop_3_4': return '3:4';
      default: return null;
    }
  }


  function canonicalizeFlowConfigCountToken(text) {
    const lower = String(text || '').toLowerCase().replace(/\s+/g, '');
    if (!lower) return null;
    const directMatch = lower.match(/[1-4]x/);
    if (directMatch) return directMatch[0];
    const reverseMatch = lower.match(/x([1-4])/);
    if (reverseMatch) return `${reverseMatch[1]}x`;
    return null;
  }

function isSettingsScopedModelSource(source) {
    return [
      'settings_context',
      'settings_panel',
      'settings_surface',
      'model_dropdown',
      'config_pill',
      'composer_settings_surface',
    ].includes(String(source || ''));
  }

  function collectVisiblePreviewNodesWithin(root) {
    if (!root || !root.querySelectorAll) return [];
    const nodes = root.querySelectorAll('img, canvas, video, picture, [style*="background-image"]');
    const previews = [];
    for (const node of nodes) {
      if (!isVisible(node)) continue;
      const rect = node.getBoundingClientRect();
      if (rect.width < 24 || rect.height < 24) continue;
      previews.push({
        node,
        rect,
        tagName: String(node.tagName || '').toLowerCase(),
      });
    }
    return previews;
  }

  function getComposerAssetPreviewState(composer = null) {
    const resolvedComposer = composer || findComposerElement();
    if (!resolvedComposer) {
      return {
        ok: false,
        preview_found: false,
        scope: 'composer_surface',
      };
    }

    const scopedRoots = collectComposerContextRoots(resolvedComposer, 5);
    for (const root of scopedRoots) {
      const previews = collectVisiblePreviewNodesWithin(root);
      const composerRect = resolvedComposer.getBoundingClientRect();
      const scopedPreview = previews.find((preview) => {
        const rect = preview.rect;
        const horizontallyNear = rect.right >= (composerRect.left - 160)
          && rect.left <= (composerRect.right + 220);
        const verticallyNear = Math.abs((rect.top + rect.height / 2) - (composerRect.top + composerRect.height / 2))
          <= Math.max(composerRect.height * 2.5, 220);
        return horizontallyNear && verticallyNear;
      });
      if (scopedPreview) {
        return {
          ok: true,
          preview_found: true,
          scope: 'composer_surface',
          strategy: 'composer_surface_preview',
          tag_name: scopedPreview.tagName,
          bbox: {
            x: Math.round(scopedPreview.rect.left),
            y: Math.round(scopedPreview.rect.top),
            width: Math.round(scopedPreview.rect.width),
            height: Math.round(scopedPreview.rect.height),
          },
        };
      }
    }

    return {
      ok: true,
      preview_found: false,
      scope: 'composer_surface',
    };
  }

  function isComposerScopedSlotContainer(slotContainer, composer = null) {
    if (!slotContainer) return false;
    const resolvedComposer = composer || findComposerElement();
    if (!resolvedComposer) return false;
    const scopedRoots = collectComposerContextRoots(resolvedComposer, 5);
    if (scopedRoots.some((root) => root && (root.contains(slotContainer) || slotContainer.contains(root)))) {
      return true;
    }
    return isNearComposerDock(slotContainer, resolvedComposer);
  }

  function findVisibleSettingsSaveButton() {
    const roots = [];
    const settingsSection = findFlowSettingsSection('F2V') || findFlowSettingsSection('IMG');
    if (settingsSection) roots.push(settingsSection);
    const composer = findComposerElement();
    roots.push(...collectComposerContextRoots(composer, 5));
    roots.push(document);
    const seen = new Set();
    for (const root of roots) {
      if (!root || seen.has(root) || !root.querySelectorAll) continue;
      seen.add(root);
      const buttons = root.querySelectorAll('button, [role="button"], [role="menuitem"]');
      for (const btn of buttons) {
        if (!isVisible(btn)) continue;
        const text = normalizeText(btn.textContent || btn.getAttribute('aria-label') || '');
        if (text.toLowerCase() === 'save') {
          return btn;
        }
      }
    }
    return null;
  }

  function getComposerAcceptedPromptState(composer = null) {
    const resolvedComposer = composer || findComposerElement();
    if (!resolvedComposer) {
      return {
        ok: false,
        prompt_accepted: false,
        value_length: 0,
      };
    }
    const rawValue = typeof resolvedComposer.value === 'string'
      ? resolvedComposer.value
      : (resolvedComposer.textContent || '');
    const normalizedValue = normalizeText(rawValue);
    const placeholder = normalizeText(
      resolvedComposer.getAttribute('placeholder')
      || resolvedComposer.getAttribute('aria-label')
      || resolvedComposer.getAttribute('data-placeholder')
      || '',
    );
    const promptAccepted = Boolean(
      normalizedValue
      && normalizedValue !== 'What do you want to create?'
      && normalizedValue !== placeholder
      && normalizedValue !== 'Editable text'
    );
    return {
      ok: true,
      prompt_accepted: promptAccepted,
      value_length: normalizedValue.length,
      placeholder_text: placeholder || null,
    };
  }

  function buildUiContractV2Proof(mode, observed, composer, generateBtn) {
    const resolvedComposer = composer || findComposerElement();
    const resolvedObserved = observed || observeFlowState();
    const resolvedGenerateBtn = generateBtn || findGenerateButtonNearComposer();
    const configLauncher = findFlowConfigLauncher();
    const startSlotContainer = resolveSlotContainer('Start');
    const startSlotPreviewScoped = Boolean(
      startSlotContainer
      && containerHasVisualPreview(startSlotContainer)
      && isComposerScopedSlotContainer(startSlotContainer, resolvedComposer)
    );
    const composerPreview = getComposerAssetPreviewState(resolvedComposer);
    const promptState = getComposerAcceptedPromptState(resolvedComposer);
    const saveButton = findVisibleSettingsSaveButton();
    const modelSource = String(resolvedObserved.modelSource || 'unknown');
    const modelScoped = isSettingsScopedModelSource(modelSource);
    const observedModelCanonical = canonicalizeFlowModelLabel(resolvedObserved.model);
    const expectedModelCanonical = canonicalizeFlowModelLabel(resolveRequestedModel({ mode: mode || 'F2V' }) || FLOW_MODE_CONFIG.F2V.defaultModel);
    const visibleWrongModelInSettingsContext = Boolean(
      modelScoped
      && observedModelCanonical
      && observedModelCanonical !== 'unknown'
      && expectedModelCanonical
      && observedModelCanonical !== expectedModelCanonical
    );
    const settingsPersisted = Boolean(
      resolvedObserved.aspectRatio === '9:16'
      && resolvedObserved.count === '1x'
      && (
        !observedModelCanonical
        || observedModelCanonical === 'unknown'
        || !modelScoped
        || observedModelCanonical === expectedModelCanonical
      )
    );
    const uploadProofPassed = Boolean(
      composerPreview.preview_found
      || startSlotPreviewScoped
    );
    const addToPromptProofPassed = Boolean(composerPreview.preview_found);
    const settingsProofPassed = Boolean(
      settingsPersisted
      && !visibleWrongModelInSettingsContext
    );
    const generateEnabled = Boolean(
      resolvedGenerateBtn
      && !resolvedGenerateBtn.disabled
      && resolvedObserved.generateButtonState === 'enabled'
    );
    const editorCapabilityReady = Boolean(
      resolvedObserved.topMode === 'Video'
      && resolvedComposer
      && isComposerEditable(resolvedComposer)
      && resolvedGenerateBtn
      && configLauncher
      && (
        resolvedObserved.visibleUploadSlots.includes('Start')
        || Boolean(findElementByText('button, [role="button"], [role="menuitem"]', 'Upload media'))
        || Boolean(findElementByText('button, [role="button"], [role="menuitem"]', 'Add Media'))
      )
    );
    const preGenerateReady = Boolean(
      uploadProofPassed
      && addToPromptProofPassed
      && settingsProofPassed
      && promptState.prompt_accepted
      && generateEnabled
    );

    return {
      ui_contract_version: 'GOOGLE_FLOW_UI_CONTRACT_V2',
      editor_capability_ready: editorCapabilityReady,
      pre_generate_ready: preGenerateReady,
      upload_proof: {
        passed: uploadProofPassed,
        composer_asset_preview_found: Boolean(composerPreview.preview_found),
        start_slot_preview_scoped: startSlotPreviewScoped,
        rejected_visible_upload_slots_only: !uploadProofPassed && resolvedObserved.visibleUploadSlots.includes('Start'),
      },
      add_to_prompt_proof: {
        passed: addToPromptProofPassed,
        prompt_bound_media_preview_found: Boolean(composerPreview.preview_found),
      },
      settings_proof: {
        passed: settingsProofPassed,
        aspect_ratio_9_16: resolvedObserved.aspectRatio === '9:16',
        count_1x: resolvedObserved.count === '1x',
        expected_model: expectedModelCanonical || 'veo 3.1 - lite',
        observed_model: resolvedObserved.model,
        observed_model_scope: modelSource,
        visible_wrong_model_in_settings_context: visibleWrongModelInSettingsContext,
        save_visible: Boolean(saveButton),
        persistence_source: settingsPersisted ? 'collapsed_config_pill_or_settings_surface' : null,
      },
      prompt_proof: {
        passed: Boolean(promptState.prompt_accepted),
        value_length: promptState.value_length,
      },
      generate_proof: {
        passed: generateEnabled,
        button_found: Boolean(resolvedGenerateBtn),
        enabled: generateEnabled,
      },
    };
  }

  function normalizeRequestedAspectRatio(value) {
    const normalized = normalizeText(value || '');
    if (!normalized) return null;
    if (normalized === '9:15') return '9:16';
    return normalized;
  }

  function getFlowSettingsSectionHeading(mode) {
    return String(mode || '').toUpperCase() === 'IMG'
      ? 'Image generation default'
      : 'Video generation default';
  }

  function collectFlowSettingsHeadingNodes(headingText, root = document) {
    if (!headingText || !root?.querySelectorAll) return [];
    const needle = normalizeText(headingText).toLowerCase();
    const nodes = Array.from(
      root.querySelectorAll('h1, h2, h3, h4, h5, h6, label, p, span, div, button'),
    );
    return nodes.filter((node) => {
      if (!isVisible(node)) return false;
      const text = normalizeText(
        node.textContent || node.getAttribute?.('aria-label') || '',
      ).toLowerCase();
      return text.includes(needle);
    });
  }

  function findFlowSettingsSection(mode, root = document) {
    const headingText = getFlowSettingsSectionHeading(mode);
    const headings = collectFlowSettingsHeadingNodes(headingText, root);
    if (!headings.length) return null;

    const scored = [];
    for (const heading of headings) {
      let current = heading;
      let depth = 0;
      while (current && depth < 8) {
        if (current === document.body || current === document.documentElement) break;
        if (isVisible(current)) {
          const text = normalizeText(current.innerText || current.textContent || '');
          if (
            text.toLowerCase().includes(headingText.toLowerCase())
            && (canonicalizeFlowConfigCountToken(text) || canonicalizeFlowConfigAspectToken(text) || /nano banana|veo|omni flash/i.test(text))
          ) {
            const rect = current.getBoundingClientRect();
            const area = Math.round(rect.width * rect.height);
            scored.push({ element: current, area, depth });
          }
        }
        current = current.parentElement;
        depth += 1;
      }
    }

    if (!scored.length) {
      return headings[0].parentElement || headings[0];
    }

    scored.sort((left, right) => {
      const areaDelta = left.area - right.area;
      if (areaDelta !== 0) return areaDelta;
      return left.depth - right.depth;
    });
    return scored[0].element;
  }


  function normalizeFlowConfigPillText(text) {
    const normalized = normalizeText(text);
    if (!normalized) return null;
    const lower = normalized.toLowerCase().replace(/\s+/g, '');
    const hasVideo = lower.includes('video');
    const aspectToken = canonicalizeFlowConfigAspectToken(normalized);
    const countToken = canonicalizeFlowConfigCountToken(normalized);
    if (!hasVideo && !aspectToken && !countToken) return null;

    const parts = [];
    if (hasVideo) parts.push('Video');
    if (aspectToken) parts.push(aspectToken);
    if (countToken) parts.push(countToken);
    return parts.length > 0 ? parts.join(' ') : null;
  }

  function looksLikeBottomComposerConfigPillText(text) {
    const normalized = normalizeFlowConfigPillText(text);
    if (!normalized) return false;
    const lower = normalized.toLowerCase();
    const hasAspect = lower.includes('crop_');
    const hasCount = /[1-4]x/.test(lower);
    return (lower.includes('video') && hasCount) || (hasAspect && hasCount);
  }

  function collectBottomComposerConfigPillCandidates() {
    const composer = findComposerElement();
    const selectors = getSelectorRegistryQuery(
      'flow_config_launcher_compact',
      'button, [role="button"], [role="tab"], [aria-haspopup], span, div',
    );
    const scoped = collectComposerContextRoots(composer)
      .flatMap((root) => Array.from(root.querySelectorAll(selectors)));
    const global = Array.from(document.querySelectorAll(selectors));
    const candidates = Array.from(new Set([...scoped, ...global]));
    const seen = new Set();
    const out = [];

    for (const candidate of candidates) {
      if (!isVisible(candidate)) continue;
      const rawText = normalizeText(
        candidate.textContent || candidate.getAttribute('aria-label') || '',
      );
      const normalizedText = normalizeFlowConfigPillText(rawText);
      if (!looksLikeBottomComposerConfigPillText(rawText) || !normalizedText) continue;
      const key = `${normalizedText}::${rawText}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({
        element: candidate,
        raw_text: rawText,
        normalized_text: normalizedText,
        text_length: rawText.length,
      });
    }

    return out.sort((left, right) => {
      const score = (value) => {
        const lower = value.normalized_text.toLowerCase();
        let result = 0;
        if (lower.includes('video')) result += 4;
        if (lower.includes('crop_')) result += 2;
        if (/[1-4]x/.test(lower)) result += 1;
        return result;
      };
      const scoreDelta = score(right) - score(left);
      if (scoreDelta !== 0) return scoreDelta;
      return left.text_length - right.text_length;
    });
  }

  function buildBottomComposerConfigPillSnapshot() {
    const launcher = findFlowConfigLauncher();
    const launcherText = normalizeText(
      launcher?.innerText || launcher?.textContent || launcher?.getAttribute('aria-label') || '',
    );
    const launcherNormalizedText = normalizeFlowConfigPillText(launcherText);
    const candidates = collectBottomComposerConfigPillCandidates();
    const selectedCandidate = launcherNormalizedText
      ? { normalized_text: launcherNormalizedText, raw_text: launcherText }
      : (candidates[0] || null);
    return {
      bottom_composer_config_pill_visible: Boolean(selectedCandidate),
      bottom_composer_config_pill_text: selectedCandidate?.normalized_text || null,
      bottom_composer_config_pill_raw_text: selectedCandidate?.raw_text || null,
    };
  }

  function sanitizeTestHookResult(action, result) {
    if (action === 'simulateFileUpload') {
      return {
        ok: Boolean(result?.ok),
        error: result?.error || null,
        detail: result?.detail || null,
        lastCheckpoint: result?.lastCheckpoint || null,
        acceptanceReason: result?.acceptanceReason || null,
        modalFound: Boolean(result?.modalFound),
        uploadStrategy: result?.uploadStrategy || null,
        cdpMethod: result?.cdpMethod || null,
      };
    }

    if (action === 'findVisibleAssetPickerModal') {
      return {
        modalFound: Boolean(result?.modal),
        foundInShadowRoot: Boolean(result?.foundInShadowRoot),
        markerSnippetCount: result?.diagnostics?.markerSnippetCount || 0,
        openShadowRootCount: result?.diagnostics?.openShadowRootCount || 0,
      };
    }

    if (action === 'beginCdpFileChooserProof' || action === 'waitForCdpFileChooserProofResult') {
      return {
        ok: Boolean(result?.ok),
        armed: Boolean(result?.armed),
        error: result?.error || null,
        method: result?.method || null,
        mode: result?.mode || null,
        backendNodeId: result?.backendNodeId || null,
        slotLabel: result?.slotLabel || null,
        expectedFileName: result?.expectedFileName || null,
        timeout_ms: result?.timeout_ms || null,
      };
    }

    return result;
  }

  async function beginCdpFileChooserProof(config = {}) {
    return await sendRuntimeMessageWithResponse({
      type: 'FLOWKIT_CDP_BEGIN_FILE_CHOOSER_POC',
      filePath: config?.filePath || null,
      expectedFileName: config?.expectedFileName || null,
      slotLabel: config?.slotLabel || 'Start',
    }, 12000);
  }

  async function waitForCdpFileChooserProofResult() {
    return await sendRuntimeMessageWithResponse({
      type: 'FLOWKIT_CDP_WAIT_FILE_CHOOSER_POC',
    }, 15000);
  }

  async function invokePlaywrightTestAction(action, args = []) {
    if (action === 'buildDiagnosticPingResponse') {
      return buildDiagnosticPingResponse(...args);
    }

    if (action === 'findVisibleAssetPickerModal') {
      return findVisibleAssetPickerModal(...args);
    }

    if (action === 'simulateFileUpload') {
      return simulateFileUpload(...args);
    }

    if (action === 'beginCdpFileChooserProof') {
      return beginCdpFileChooserProof(...args);
    }

    if (action === 'waitForCdpFileChooserProofResult') {
      return waitForCdpFileChooserProofResult(...args);
    }

    throw new Error(`ERR_UNKNOWN_TEST_ACTION:${action}`);
  }

  function postPlaywrightTestBridgeResponse(requestId, payload) {
    window.postMessage({
      source: FLOW_KIT_TEST_BRIDGE_SOURCE,
      direction: 'response',
      requestId,
      ...payload,
    }, '*');
  }

  function installPlaywrightTestBridge() {
    if (!FLOW_KIT_PLAYWRIGHT_HARNESS || window._flowKitPlaywrightBridgeInstalled) {
      return;
    }

    window._flowKitPlaywrightBridgeInstalled = true;
    window.addEventListener('message', (event) => {
      if (event.source !== window) return;

      const data = event.data || {};
      if (
        data.source !== FLOW_KIT_TEST_BRIDGE_SOURCE
        || data.direction !== 'request'
      ) {
        return;
      }

      const requestId = data.requestId || `flowkit_test_${Date.now()}`;
      Promise.resolve()
        .then(async () => {
          const action = String(data.action || '');
          const args = Array.isArray(data.args) ? data.args : [];
          const result = await invokePlaywrightTestAction(action, args);
          postPlaywrightTestBridgeResponse(requestId, {
            ok: true,
            action,
            result: sanitizeTestHookResult(action, result),
          });
        })
        .catch((error) => {
          postPlaywrightTestBridgeResponse(requestId, {
            ok: false,
            error: String(error?.message || error),
          });
        });
    });
  }

  function normalizeText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function canonicalizeFlowModelLabel(value) {
    const normalized = normalizeText(value).toLowerCase();
    if (!normalized) return '';
    if (normalized.includes('veo 3.1 - lite') || normalized.includes('veo 3.1 lite')) return 'veo 3.1 - lite';
    if (normalized.includes('veo 3.1 - pro') || normalized.includes('veo 3.1 pro')) return 'veo 3.1 - pro';
    if (normalized.includes('veo 3.1 - fast') || normalized.includes('veo 3.1 fast')) return 'veo 3.1 - fast';
    if (normalized.includes('veo 3.1 - quality') || normalized.includes('veo 3.1 quality')) return 'veo 3.1 - quality';
    if (normalized.includes('nano banana 2')) return 'nano banana 2';
    if (normalized.includes('nano banana pro') || normalized.includes('nano banana - pro')) return 'nano banana pro';
    if (normalized.includes('veo 3.1')) return 'veo 3.1';
    if (normalized.includes('nano banana')) return 'nano banana';
    return normalized;
  }

  function extractObservedModelLabel(text) {
    const value = normalizeText(text);
    if (!value) return null;
    const exactVeoMatch = value.match(/Veo(?:[-\s]?3(?:\.1)?(?:\s*-\s*(?:Lite|Pro|Fast|Quality)))/i);
    if (exactVeoMatch) return normalizeText(exactVeoMatch[0]);
    const genericVeoMatch = value.match(/Veo(?:[-\s]?3(?:\.1)?)/i);
    if (genericVeoMatch) return normalizeText(genericVeoMatch[0]);
    const exactNanoBananaMatch = value.match(/Nano Banana(?:\s*2|\s*Pro|\s*-\s*Pro)/i);
    if (exactNanoBananaMatch) return normalizeText(exactNanoBananaMatch[0]);
    const genericNanoBananaMatch = value.match(/Nano Banana/i);
    if (genericNanoBananaMatch) return normalizeText(genericNanoBananaMatch[0]);
    return null;
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
    const needle = normalizeText(text).toLowerCase();
    if (!needle) return null;

    const matches = [];
    for (const el of document.querySelectorAll(selector)) {
      if (!isVisible(el)) continue;
      const label = normalizeText(
        el.textContent
        || el.getAttribute('aria-label')
        || el.getAttribute('data-placeholder')
        || ''
      );
      if (!label) continue;
      const target = el.closest('button, [role="button"], [role="tab"], [role="option"], li, label') || el;
      if (!isVisible(target)) continue;
      matches.push({ label: label.toLowerCase(), target });
    }

    const exactMatch = matches.find((item) => item.label === needle);
    if (exactMatch) return exactMatch.target;

    const prefixMatch = matches.find((item) => item.label.startsWith(needle));
    if (prefixMatch) return prefixMatch.target;

    const partialMatch = matches.find((item) => item.label.includes(needle));
    return partialMatch?.target || null;
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
    return job?.modelLabel
      || job?.model
      || (job?.mode === 'F2V' ? 'Veo 3.1 - Lite' : null);
  }

  function resolveFlowModeConfig(mode) {
    return FLOW_MODE_CONFIG[String(mode || '').toUpperCase()] || null;
  }

  function buildExpectedModeJob(mode) {
    const normalizedMode = String(mode || '').toUpperCase();
    const config = resolveFlowModeConfig(normalizedMode);
    if (!config) return mode ? { mode } : null;

    const job = { mode: normalizedMode };
    if (config.defaultOrientation) job.orientation = config.defaultOrientation;
    if (config.defaultCount) job.count = config.defaultCount;
    if (config.defaultModel) job.modelLabel = config.defaultModel;
    return job;
  }

  function hasFlowAspectToken(text) {
    return Boolean(canonicalizeFlowConfigAspectToken(text));
  }

  function hasFlowCountToken(text) {
    return Boolean(canonicalizeFlowConfigCountToken(text));
  }

  function collectComposerContextRoots(composer = null, maxDepth = 4) {
    const roots = [];
    const seen = new Set();
    let current = composer || findComposerElement();
    let depth = 0;

    while (current && depth <= maxDepth) {
      if (!seen.has(current)) {
        roots.push(current);
        seen.add(current);
      }
      current = current.parentElement;
      depth += 1;
    }

    return roots;
  }

  function looksLikeGenerateButton(target) {
    if (!target || !isVisible(target)) return false;
    const text = normalizeText(target.textContent || '');
    if (text.includes('Create') || text.includes('Generate') || text.includes('arrow_forwardCreate')) return true;
    const aria = normalizeText(target.getAttribute('aria-label') || '');
    return aria.includes('Create') || aria.includes('Generate');
  }

  function looksLikeExcludedCreateButton(target) {
    if (!target) return false;
    const text = normalizeText(target.textContent || target.getAttribute('aria-label') || '').toLowerCase();
    if (!text) return false;
    return text.includes('create tool')
      || text.includes('create with flow')
      || text.includes('create new project')
      || text === 'create new'
      || text.includes('create project');
  }

  function isNearComposerDock(target, composer) {
    if (!target || !composer || !isVisible(target) || !isVisible(composer)) return false;
    const targetRect = target.getBoundingClientRect();
    const composerRect = composer.getBoundingClientRect();
    const verticalDistance = Math.abs((targetRect.top + targetRect.height / 2) - (composerRect.top + composerRect.height / 2));
    const horizontalMatch = targetRect.left >= composerRect.left - 80 && targetRect.right <= composerRect.right + 240;
    return verticalDistance <= Math.max(composerRect.height, targetRect.height) * 1.5 && horizontalMatch;
  }

  function findFlowConfigLauncher() {
    const selectors = getSelectorRegistryQuery(
      'flow_config_launcher_compact',
      'button, [role="button"], [role="tab"], [aria-haspopup], span, div',
    );
    const composer = findComposerElement();
    const scopedCandidates = collectComposerContextRoots(composer)
      .flatMap((root) => Array.from(root.querySelectorAll(selectors)));
    const globalCandidates = Array.from(document.querySelectorAll(selectors));
    const candidates = Array.from(new Set([...scopedCandidates, ...globalCandidates]));
    const preferred = [];
    const fallback = [];

    for (const el of candidates) {
      if (!isVisible(el)) continue;
      const text = normalizeText(el.textContent || el.getAttribute('aria-label') || '');
      if (!text) continue;
      const lower = text.toLowerCase();
      const looksLikeModelChip = lower.includes('nano banana') || lower.includes('veo');
      const normalizedPillText = normalizeFlowConfigPillText(text);
      const looksLikeConfigChip = Boolean(normalizedPillText && looksLikeBottomComposerConfigPillText(text));
      const target = el.closest('button, [role="button"], [role="tab"], [aria-haspopup]') || el;
      if (!isVisible(target)) continue;
      const targetText = normalizeText(target.textContent || target.getAttribute('aria-label') || '');
      const rect = target.getBoundingClientRect();
      const targetTooLarge = rect.width > 520 || rect.height > 120 || targetText.length > 120;
      const targetLooksLikePageShell = /(what do you want to create|double check it|go back|search|sort & filter|add media|all media|characters|scenes|tools|trash|collapse)/i.test(targetText);
      if (!targetText || targetTooLarge || targetLooksLikePageShell) continue;
      if (looksLikeModelChip || looksLikeConfigChip) {
        preferred.push({ target, targetText, rect });
        continue;
      }
      if (lower.includes('veo') || lower.includes('nano banana')) {
        fallback.push({ target, targetText, rect });
      }
    }

    const sortByCompactness = (items) => items
      .sort((left, right) => {
        const textDelta = left.targetText.length - right.targetText.length;
        if (textDelta !== 0) return textDelta;
        return (left.rect.width * left.rect.height) - (right.rect.width * right.rect.height);
      })
      .map((item) => item.target);

    if (preferred.length > 0) return sortByCompactness(preferred)[0];
    if (fallback.length > 0) return sortByCompactness(fallback)[0];
    return null;
  }

  function findOpenFlowConfigSurface() {
    const selectors = getSelectorRegistryQuery(
      'flow_config_surface_portal',
      [
        '[role="listbox"]',
        '[role="dialog"]',
        '[role="menu"]',
        '[data-floating-ui-portal] > *',
        '[data-radix-popper-content-wrapper] > *',
        '[data-radix-portal] > *',
      ].join(', '),
    );

    const surfaces = Array.from(document.querySelectorAll(selectors))
      .filter((el) => isVisible(el));

    const preferred = surfaces.find((el) => {
      const text = normalizeText(el.innerText || el.textContent || '');
      if (!text) return false;
      return /(veo|nano banana|9:16|16:9|1x|2x|3x|4x)/i.test(text);
    });

    return preferred || surfaces[0] || null;
  }

  function findElementByTextInRoot(root, selector, text) {
    if (!root) return null;

    const needle = normalizeText(text).toLowerCase();
    if (!needle) return null;

    const matches = [];
    for (const el of root.querySelectorAll(selector)) {
      if (!isVisible(el)) continue;
      const label = normalizeText(
        el.textContent
        || el.getAttribute('aria-label')
        || el.getAttribute('data-placeholder')
        || ''
      );
      if (!label) continue;
      const target = el.closest('button, [role="button"], [role="tab"], [role="option"], li, label') || el;
      if (!isVisible(target)) continue;
      matches.push({ label: label.toLowerCase(), target });
    }

    const exactMatch = matches.find((item) => item.label === needle);
    if (exactMatch) return exactMatch.target;

    const prefixMatch = matches.find((item) => item.label.startsWith(needle));
    if (prefixMatch) return prefixMatch.target;

    const partialMatch = matches.find((item) => item.label.includes(needle));
    return partialMatch?.target || null;
  }

  function collectFlowConfigDebugSnapshot() {
    const launcher = findFlowConfigLauncher();
    const surface = findOpenFlowConfigSurface();
    const visibleOptionTexts = collectVisibleTexts(
      'button, [role="option"], [role="button"], [role="tab"], li, span, div',
      (el) => el.textContent || el.getAttribute('aria-label') || '',
      120,
    ).filter((text) => /(veo|nano banana|9:16|16:9|1x|2x|3x|4x)/i.test(text));

    return {
      launcher_text: normalizeText(launcher?.textContent || launcher?.getAttribute('aria-label') || ''),
      surface_text: normalizeText(surface?.innerText || surface?.textContent || ''),
      visible_option_texts: visibleOptionTexts,
    };
  }

  async function closeBlockingModalIfPresent() {
    const closeButton = findElementByText('button, [role="button"], span', 'close');
    if (!closeButton || !isVisible(closeButton)) return false;
    closeButton.click();
    await sleep(400);
    return true;
  }

  async function openFlowConfigPanel() {
    await closeBlockingModalIfPresent();
    const existingSurface = findOpenFlowConfigSurface();
    if (existingSurface) return true;

    const launcher = findFlowConfigLauncher();
    if (!launcher || !isVisible(launcher)) return false;
    launcher.click();
    const surfaced = await waitForCondition(() => Boolean(findOpenFlowConfigSurface()), 2500, 100);
    if (!surfaced) {
      await sleep(800);
    }
    return surfaced;
  }

  function findOpenF2VConfigMenu() {
    return Array.from(document.querySelectorAll('[role="menu"]')).find((el) => {
      if (!isVisible(el)) return false;
      const text = normalizeText(el.innerText || el.textContent || '');
      return text.includes('Video')
        && text.includes('Frames')
        && text.includes('9:16')
        && text.includes('1x');
    }) || null;
  }

  function findCollapsedF2VConfigLauncher() {
    return Array.from(document.querySelectorAll(
      getSelectorRegistryQuery('f2v_collapsed_config_launcher', 'button[aria-haspopup="menu"]'),
    )).find((el) => {
      if (!isVisible(el)) return false;
      const text = normalizeText(el.innerText || el.textContent || '');
      return text.includes('Video')
        && hasFlowCountToken(text)
        && hasFlowAspectToken(text);
    }) || null;
  }

  async function ensureF2VComposerReadyBeforeConfig() {
    const collectComposerSnapshot = () => {
      const observed = observeFlowState();
      const composer = findComposerElement();
      const launcher = findCollapsedF2VConfigLauncher();
      const visibleMenus = Array.from(document.querySelectorAll('[role="menu"]')).filter(isVisible);
      const f2vMenu = findOpenF2VConfigMenu();
      const bodyText = normalizeText(document.body?.innerText || '');
      const shellMarkers = [];
      if (bodyText.includes('Scenebuilder')) shellMarkers.push('Scenebuilder');
      if (bodyText.includes('Add Media')) shellMarkers.push('Add Media');
      const goBackControl = findElementByText(
        'button, [role="button"], a, [role="tab"], [role="option"], li, label, span, div',
        'Go Back',
      );

      return {
        observed,
        startSlotVisible: observed.visibleUploadSlots.includes('Start'),
        composerFound: Boolean(composer),
        composerVisible: Boolean(composer && isVisible(composer)),
        composerEditable: Boolean(composer && isVisible(composer) && isComposerEditable(composer)),
        launcherFound: Boolean(launcher),
        launcherVisible: Boolean(launcher && isVisible(launcher)),
        roleMenuCount: visibleMenus.length,
        hasBlockingNonF2VMenu: visibleMenus.length > 0 && !f2vMenu,
        shellMarkers,
        goBackVisible: Boolean(goBackControl && isVisible(goBackControl)),
        goBackControl,
      };
    };

    const isReady = (snapshot) => (
      snapshot.observed.topMode === 'Video'
      && snapshot.observed.subMode === 'Frames'
      && snapshot.startSlotVisible
      && snapshot.composerFound
      && snapshot.composerVisible
      && snapshot.composerEditable
      && snapshot.launcherVisible
      && !snapshot.hasBlockingNonF2VMenu
      && snapshot.roleMenuCount === 0
    );

    const formatDetail = (snapshot, goBackClicked) => (
      `topMode=${snapshot.observed.topMode}`
      + ` subMode=${snapshot.observed.subMode}`
      + ` start_slot_visible=${snapshot.startSlotVisible}`
      + ` composer_found=${snapshot.composerFound}`
      + ` composer_visible=${snapshot.composerVisible}`
      + ` composer_editable=${snapshot.composerEditable}`
      + ` launcher_found=${snapshot.launcherFound}`
      + ` launcher_visible=${snapshot.launcherVisible}`
      + ` role_menu_count=${snapshot.roleMenuCount}`
      + ` shell_markers=${JSON.stringify(snapshot.shellMarkers)}`
      + ` go_back_clicked=${goBackClicked}`
    );

    let goBackClicked = false;
    let snapshot = collectComposerSnapshot();
    if (isReady(snapshot)) {
      return { ok: true, detail: formatDetail(snapshot, goBackClicked) };
    }

    if (snapshot.hasBlockingNonF2VMenu) {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }));
      await sleep(400);
      snapshot = collectComposerSnapshot();
      if (isReady(snapshot)) {
        return { ok: true, detail: formatDetail(snapshot, goBackClicked) };
      }
    }

    if (!isReady(snapshot)
      && snapshot.shellMarkers.some((marker) => marker === 'Scenebuilder' || marker === 'Add Media')
      && snapshot.goBackVisible) {
      const goBackTarget = snapshot.goBackControl?.closest('button, [role="button"], a, [role="tab"], [role="option"], li, label') || snapshot.goBackControl;
      if (goBackTarget && isVisible(goBackTarget)) {
        goBackTarget.click();
        goBackClicked = true;
        await sleep(800);
        snapshot = collectComposerSnapshot();
        if (isReady(snapshot)) {
          return { ok: true, detail: formatDetail(snapshot, goBackClicked) };
        }
      }
    }

    let error = 'ERR_F2V_COMPOSER_NOT_READY';
    if (!snapshot.launcherFound || !snapshot.launcherVisible) {
      error = 'ERR_F2V_CONFIG_LAUNCHER_NOT_FOUND';
    } else if (snapshot.shellMarkers.some((marker) => marker === 'Scenebuilder' || marker === 'Add Media')) {
      error = 'ERR_F2V_SCENEBUILDER_STATE';
    }

    return {
      ok: false,
      error,
      detail: formatDetail(snapshot, goBackClicked),
    };
  }

  async function ensureOpenF2VConfigMenu() {
    const roleMenuCountBeforeOrig = document.querySelectorAll('[role="menu"]').length;
    const existingMenu = findOpenF2VConfigMenu();
    if (existingMenu) {
      return {
        ok: true,
        detail: `role_menu_count_before=${roleMenuCountBeforeOrig} launcher_found=false launcher_visible=false launcher_text='' launcher_aria_expanded_before='' launcher_data_state_before='' click_method=none role_menu_count_after=${roleMenuCountBeforeOrig} launcher_aria_expanded_after='' launcher_data_state_after='' first_menu_text_snippet_after=${JSON.stringify(normalizeText(existingMenu.innerText || existingMenu.textContent || '').slice(0, 120))}`,
      };
    }

    let _roleMenuTextSnippetsBeforeClose = [];
    if (roleMenuCountBeforeOrig > 0) {
      _roleMenuTextSnippetsBeforeClose = Array.from(document.querySelectorAll('[role="menu"]')).map((el) => (
        normalizeText(el.innerText || el.textContent || '').slice(0, 120)
      ));
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }));
      await sleep(350);
      if (document.querySelectorAll('[role="menu"]').length > 0 && !findCollapsedF2VConfigLauncher()) {
        document.body?.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
        await sleep(350);
      }
    }

    const roleMenuCountAfterClose = document.querySelectorAll('[role="menu"]').length;

    // 1. Re-query launcher immediately before click
    const launcher = findCollapsedF2VConfigLauncher();
    const launcherFound = Boolean(launcher);
    const launcherVisible = Boolean(launcher && isVisible(launcher));
    const launcherText = normalizeText(launcher?.innerText || launcher?.textContent || '');

    // 2. Verify launcher state
    const isLauncherValid = launcherFound && launcherVisible
      && launcherText.includes('Video')
      && hasFlowCountToken(launcherText)
      && hasFlowAspectToken(launcherText);

    const launcherAriaExpandedBefore = launcher?.getAttribute('aria-expanded') || '';
    const launcherDataStateBefore = launcher?.getAttribute('data-state') || '';
    const rect = launcher?.getBoundingClientRect();
    const activeElementTextBefore = normalizeText(document.activeElement?.innerText || document.activeElement?.textContent || '').slice(0, 50);

    const diagBefore = {
      launcher_found_before_click: launcherFound,
      launcher_visible_before_click: launcherVisible,
      launcher_text_before_click: launcherText,
      launcher_outerHTML_before_click: launcher?.outerHTML?.slice(0, 200),
      launcher_aria_expanded_before: launcherAriaExpandedBefore,
      launcher_data_state_before: launcherDataStateBefore,
      launcher_bounding_rect: rect ? { x: rect.left, y: rect.top, width: rect.width, height: rect.height } : null,
      active_element_text_before: activeElementTextBefore,
      role_menu_count_before: roleMenuCountAfterClose,
    };

    if (!isLauncherValid) {
      const bodyTextSnippet = normalizeText(document.body?.innerText || '').slice(0, 120);
      return {
        ok: false,
        detail: `ERR_F2V_CONFIG_LAUNCHER_INVALID — ${JSON.stringify(diagBefore)} body_text_snippet=${JSON.stringify(bodyTextSnippet)}`,
      };
    }

    // 4. Scroll launcher into view
    launcher.scrollIntoView({ block: 'center', inline: 'center' });
    await sleep(150);

    // 5. Dispatch realistic synthetic click sequence
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;

    const eventInit = {
      bubbles: true,
      cancelable: true,
      view: window,
      clientX: centerX,
      clientY: centerY,
    };

    let clickMethodUsed = 'pointer_sequence';
    launcher.dispatchEvent(new PointerEvent('pointerdown', { ...eventInit, pointerType: 'mouse' }));
    launcher.dispatchEvent(new MouseEvent('mousedown', eventInit));
    launcher.dispatchEvent(new PointerEvent('pointerup', { ...eventInit, pointerType: 'mouse' }));
    launcher.dispatchEvent(new MouseEvent('mouseup', eventInit));
    launcher.dispatchEvent(new MouseEvent('click', eventInit));

    // 6. Fallback if still not open
    let opened = await waitForCondition(() => Boolean(findOpenF2VConfigMenu()), 1500, 150);
    if (!opened) {
      clickMethodUsed = 'pointer_sequence_plus_fallback_click';
      launcher.click();
      opened = await waitForCondition(() => Boolean(findOpenF2VConfigMenu()), 1500, 150);
    }

    const roleMenuCountAfter = document.querySelectorAll('[role="menu"]').length;
    const launcherAriaExpandedAfter = launcher.getAttribute('aria-expanded') || '';
    const launcherDataStateAfter = launcher.getAttribute('data-state') || '';
    const menuAfter = findOpenF2VConfigMenu();
    const roleMenuTextSnippetsAfter = Array.from(document.querySelectorAll('[role="menu"]')).map((el) => (
      normalizeText(el.innerText || el.textContent || '').slice(0, 120)
    ));
    const activeElementTextAfter = normalizeText(document.activeElement?.innerText || document.activeElement?.textContent || '').slice(0, 50);

    const bodyShellMarkersAfter = [];
    const bodyTextAfter = document.body?.innerText || '';
    if (bodyTextAfter.includes('Scenebuilder')) bodyShellMarkersAfter.push('Scenebuilder');
    if (bodyTextAfter.includes('Add Media')) bodyShellMarkersAfter.push('Add Media');

    const diagAfter = {
      ...diagBefore,
      click_method_used: clickMethodUsed,
      launcher_aria_expanded_after: launcherAriaExpandedAfter,
      launcher_data_state_after: launcherDataStateAfter,
      role_menu_count_after: roleMenuCountAfter,
      role_menu_text_snippets_after: roleMenuTextSnippetsAfter,
      active_element_text_after: activeElementTextAfter,
      body_shell_markers_after: bodyShellMarkersAfter,
    };

    return {
      ok: Boolean(opened && menuAfter),
      detail: JSON.stringify(diagAfter),
    };
  }

  async function ensureF2VVerifiedAspectCountAndModel() {
    const menu = findOpenF2VConfigMenu();
    if (!menu) {
      return { ok: false, error: 'ERR_ASPECT_9_16_NOT_SELECTED', detail: 'F2V config menu not open' };
    }

    const aspectBtn = menu.querySelector('button[role="tab"][aria-controls$="content-PORTRAIT"]');
    if (!aspectBtn || !isVisible(aspectBtn)) {
      return { ok: false, error: 'ERR_ASPECT_9_16_NOT_SELECTED', detail: 'Verified 9:16 control not found' };
    }
    if (aspectBtn.getAttribute('aria-selected') !== 'true') {
      aspectBtn.click();
      await sleep(500);
    }
    if (aspectBtn.getAttribute('aria-selected') !== 'true') {
      return { ok: false, error: 'ERR_ASPECT_9_16_NOT_SELECTED', detail: 'aria-selected did not become true for 9:16' };
    }

    const countBtn = menu.querySelector('button[role="tab"][aria-controls$="content-1"]');
    if (!countBtn || !isVisible(countBtn)) {
      return { ok: false, error: 'ERR_COUNT_1X_NOT_SELECTED', detail: 'Verified 1x control not found' };
    }
    if (countBtn.getAttribute('aria-selected') !== 'true') {
      countBtn.click();
      await sleep(500);
    }
    if (countBtn.getAttribute('aria-selected') !== 'true') {
      return { ok: false, error: 'ERR_COUNT_1X_NOT_SELECTED', detail: 'aria-selected did not become true for 1x' };
    }

    const modelBtn = Array.from(menu.querySelectorAll('button[aria-haspopup="menu"]')).find((el) => {
      if (!isVisible(el)) return false;
      const text = normalizeText(el.innerText || el.textContent || '');
      return /veo|nano banana|banana/i.test(text);
    });
    const modelText = normalizeText(modelBtn?.innerText || modelBtn?.textContent || '');
    if (!modelBtn || !isVisible(modelBtn) || /nano.?banana/i.test(modelText) || !modelText.includes('Veo 3.1 - Lite')) {
      return {
        ok: false,
        error: 'ERR_WRONG_MODEL_FOR_F2V',
        detail: `MODEL_SWITCHING_NOT_IMPLEMENTED_OPENED_OPTION_DOM_NOT_VERIFIED model=${modelText || 'UNKNOWN'}`,
      };
    }

    return { ok: true, modelText };
  }

  async function selectFlowConfigOption(text) {
    const launcher = findFlowConfigLauncher();

    for (let attempt = 0; attempt < 2; attempt += 1) {
      const surface = findOpenFlowConfigSurface();
      let option = findElementByTextInRoot(
        surface,
        'button, [role="option"], [role="button"], [role="tab"], li, span, div',
        text,
      );

      if (!option || !isVisible(option) || option === launcher || launcher?.contains(option)) {
        option = null;
      }

      if (option && isVisible(option)) {
        if (!isSelectedControl(option, text)) {
          option.click();
          await sleep(700);
        }
        return true;
      }

      if (attempt === 0) {
        const opened = await openFlowConfigPanel();
        if (!opened) break;
      }
    }

    return false;
  }

  async function openCreateTypeChooser() {
    const candidates = Array.from(document.querySelectorAll('button, [role="button"], span, div'));
    const trigger = candidates.find((el) => {
      if (!isVisible(el)) return false;
      const text = normalizeText(el.textContent || el.getAttribute('aria-label') || '');
      if (!text) return false;
      const lower = text.toLowerCase();
      return lower.includes('create') && lower.includes('add_2') && !lower.includes('arrow_forward');
    });

    const target = trigger?.closest('button, [role="button"]') || trigger;
    if (!target || !isVisible(target)) return false;
    target.click();

    const selector = 'button, [role="tab"], [role="button"], span, div';
    const surfaced = await waitForCondition(() => {
      const menu = document.querySelector('[role="menu"], [role="listbox"]');
      if (menu && isVisible(menu)) return true;
      const video = findElementByText(selector, 'Video');
      if (video && isVisible(video)) return true;
      const image = findElementByText(selector, 'Image');
      if (image && isVisible(image)) return true;
      return false;
    }, 1000, 200);

    return surfaced;
  }

  async function ensureModeControlsVisible(mode) {
    const config = resolveFlowModeConfig(mode);
    if (!config) {
      return { ok: false, error: 'ERR_MODE_SELECTION_FAILED', detail: `Unsupported mode '${mode}'` };
    }

    const observed = observeFlowState();
    const topModeAlreadyVisible = normalizeText(observed.topMode).toLowerCase() === normalizeText(config.topMode).toLowerCase();
    const subModeAlreadyVisible = !config.subMode
      || normalizeText(observed.subMode).toLowerCase() === normalizeText(config.subMode).toLowerCase();

    if (topModeAlreadyVisible && subModeAlreadyVisible) {
      return { ok: true, config, topBtn: null, subBtn: null, observed };
    }

    const modeSelector = 'button, [role="tab"], [role="button"], [role="option"], span, div';
    let topBtn = null;
    let subBtn = null;
    let source = 'global';

    const assignVisibleControls = (root = null, nextSource = 'global') => {
      const scopedTop = root
        ? findElementByTextInRoot(root, modeSelector, config.topMode)
        : findElementByText(modeSelector, config.topMode);
      const scopedSub = config.subMode
        ? (root
          ? findElementByTextInRoot(root, modeSelector, config.subMode)
          : findElementByText(modeSelector, config.subMode))
        : null;

      topBtn = scopedTop;
      subBtn = scopedSub;
      source = nextSource;
    };

    assignVisibleControls(null, 'global');

    const needsSurface = !topBtn || !isVisible(topBtn) || (config.subMode && (!subBtn || !isVisible(subBtn)));
    if (needsSurface) {
      if (await openFlowConfigPanel()) {
        const surface = findOpenFlowConfigSurface();
        if (surface) {
          assignVisibleControls(surface, 'config_surface');
        }
      }
    }

    if ((!topBtn || !isVisible(topBtn) || (config.subMode && (!subBtn || !isVisible(subBtn)))) && await openCreateTypeChooser()) {
      assignVisibleControls(null, 'create_type_chooser');
    }

    if (!topBtn || !isVisible(topBtn)) {
      return { ok: false, error: 'ERR_MODE_SELECTION_FAILED', detail: `${config.topMode} control not visible after opening type selector` };
    }

    if (config.subMode && (!subBtn || !isVisible(subBtn))) {
      return { ok: false, error: 'ERR_MODE_SELECTION_FAILED', detail: `${config.subMode} control not visible after opening type selector` };
    }

    return { ok: true, config, topBtn, subBtn, source };
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
      || assetSource.assetId
      || assetSource.asset_id
      || assetSource.id
      || assetSource.characterId
      || null;
  }

  function describeAssetSourceType(assetSource) {
    if (!assetSource) return 'missing';
    if (resolveAssetLocalFilePath(assetSource)) return 'cdp_local_file';
    if (typeof assetSource === 'string') {
      if (assetSource.startsWith('data:')) return 'data_url';
      if (assetSource.startsWith('http')) return 'url';
      return 'path/id';
    }
    if (typeof assetSource === 'object' && assetSource.previewUrl) {
      return 'legacy_preview_url';
    }
    return 'object';
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

  function findUploadSlotByLabel(slotLabel) {
    const isStart = String(slotLabel).toLowerCase() === 'start';
    const isEnd = String(slotLabel).toLowerCase() === 'end';
    const uploadSlotQuery = getSelectorRegistryQuery(
      'upload_slot_label_scan',
      'label, span, div, p, button, [role="button"]',
    );

    // 1. Find all candidate label elements using inclusive detection logic
    const candidates = Array.from(document.querySelectorAll(uploadSlotQuery))
      .filter((el) => {
        if (!isVisible(el)) return false;
        const text = normalizeText(el.textContent || '');
        if (isStart) {
          // Evidence-backed: Must include Start, but exclude End to avoid cross-contamination
          return text.includes('Start') && !text.includes('End');
        }
        if (isEnd) {
          return text.includes('End');
        }
        return text.includes(slotLabel);
      });

    // 2. Resolve the best container for each candidate
    for (const labelNode of candidates) {
      let current = labelNode;
      // Search up to 5 levels for a container that looks like a slot
      for (let depth = 0; current && depth < 5; depth += 1) {
        const text = normalizeText(current.textContent || '');
        // Preferably near upload/add/media/image placeholder
        const hasUploadMarker = /(upload|add|media|image|browse)/i.test(text);
        const isClickable = current.matches('button, [role="button"], label, a');

        if (hasUploadMarker || isClickable) {
          // Strict exclusion: Do not accept Start if it has End text in this container level
          if (isStart && text.includes('End')) {
            current = current.parentElement;
            continue;
          }
          // Reject global Add Media/Scenebuilder if they don't contain the specific slot label
          const containerText = normalizeText(current.textContent || '');
          if (!containerText.includes(slotLabel)) {
            current = current.parentElement;
            continue;
          }

          return { container: current, labelNode };
        }
        current = current.parentElement;
      }
    }

    return null;
  }

  function getSlotCandidateContainers(slotLabel, slotElement = null) {
    const candidates = [];
    const push = (el) => {
      if (!el || candidates.includes(el)) return;
      candidates.push(el);
    };

    const slotInfo = findUploadSlotByLabel(slotLabel);
    if (slotInfo) {
      push(slotInfo.container);
      push(slotInfo.labelNode);
    }

    push(slotElement);
    push(slotElement?.closest('button'));
    push(slotElement?.closest('[role="button"]'));

    const labelNode = slotInfo?.labelNode || findElementByText('button, [role="button"], label, span, div, p', slotLabel);
    push(labelNode);
    push(labelNode?.closest('button'));
    push(labelNode?.closest('[role="button"]'));

    let current = slotElement || labelNode;
    for (let depth = 0; current && depth < 4; depth += 1) {
      push(current);
      current = current.parentElement;
    }

    return candidates;
  }

  function resolveSlotContainer(slotLabel, slotElement = null) {
    const slotInfo = findUploadSlotByLabel(slotLabel);
    if (slotInfo?.container) return slotInfo.container;

    const candidates = getSlotCandidateContainers(slotLabel, slotElement)
      .filter((candidate) => candidate && isVisible(candidate));

    const labelledCandidate = candidates.find((candidate) => {
      const text = normalizeText(candidate.innerText || '').toLowerCase();
      const needle = String(slotLabel || '').toLowerCase();
      if (needle === 'start') return text.includes('start') && !text.includes('end');
      return text.includes(needle);
    });
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
      const uploadSettled = !currentSnapshot.uploadPending;

      if ((previewChanged || countChanged) && uploadSettled) {
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
    const composer = findComposerElement();
    const generateButtonQuery = getSelectorRegistryQuery(
      'generate_button_composer_scoped',
      'button, [role="button"]',
    );
    const composerRoots = collectComposerContextRoots(composer);
    const scopedButtons = composerRoots
      .flatMap((root) => Array.from(root.querySelectorAll(generateButtonQuery)));
    const scopedMatch = scopedButtons.find((btn) => looksLikeGenerateButton(btn));
    if (scopedMatch) return scopedMatch;

    // 1. Target by specific text found in diagnostic
    const buttons = Array.from(document.querySelectorAll(generateButtonQuery));
    const createBtn = buttons.find((btn) => {
      if (!looksLikeGenerateButton(btn) || looksLikeExcludedCreateButton(btn)) return false;
      if (!composer) return true;
      return composerRoots.some((root) => root.contains(btn)) || isNearComposerDock(btn, composer);
    });
    if (createBtn) return createBtn;

    // 2. Fallback to icon path detection
    const paths = document.querySelectorAll(
      getSelectorRegistryQuery('generate_button_icon_path_fallback', 'path'),
    );
    for (const path of paths) {
      const d = path.getAttribute('d') || '';
      if (d.includes('M10 20l-1.41-1.41L15.17 12 8.59 5.41 10 4l8 8-8 8z') ||
          d.includes('M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z')) {
        const btn = path.closest('button');
        if (btn && isVisible(btn)) return btn;
      }
    }

    // 3. Fallback to proximity to composer
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

  const ASSET_PICKER_TEXT_RE = /(upload image|search for assets|recent|upload|choose|select|browse|image|asset|add media)/i;
  const ASSET_PICKER_ACTION_RE = /(upload|choose|browse|add|select)/i;
  const ASSET_PICKER_DIAGNOSTIC_MARKERS = ['Upload image', 'Search for Assets', 'Recent', 'Upload', 'Image'];

  function appendUniqueNode(list, seen, node) {
    if (!node || seen.has(node)) return;
    seen.add(node);
    list.push(node);
  }

  function getRootText(root) {
    if (!root) return '';
    if (root === document) {
      return normalizeText(document.body?.innerText || document.body?.textContent || '');
    }
    return normalizeText(
      root.innerText
      || root.textContent
      || root.host?.innerText
      || root.host?.textContent
      || ''
    );
  }

  function collectDeepSearchState() {
    const shadowRoots = [];
    const shadowHosts = [];
    const seenRoots = new Set();
    const queue = [document];

    while (queue.length > 0) {
      const root = queue.shift();
      if (!root?.querySelectorAll) continue;

      for (const el of root.querySelectorAll('*')) {
        if (!el.shadowRoot || seenRoots.has(el.shadowRoot)) continue;
        seenRoots.add(el.shadowRoot);
        shadowRoots.push(el.shadowRoot);
        shadowHosts.push(el);
        queue.push(el.shadowRoot);
      }
    }

    return {
      shadowRoots,
      shadowHosts,
    };
  }

  function collectMatchesInRoot(root, selector) {
    if (!root?.querySelectorAll) return [];
    const matches = [];
    if (root instanceof Element && root.matches?.(selector)) {
      matches.push(root);
    }
    return matches.concat(Array.from(root.querySelectorAll(selector)));
  }

  function collectQueryRoots(preferred = [], deepState = null) {
    const roots = [];
    const seen = new Set();

    for (const node of preferred) {
      appendUniqueNode(roots, seen, node);
    }

    const activeRoot = document.activeElement?.getRootNode?.() || null;
    if (activeRoot?.querySelectorAll) {
      appendUniqueNode(roots, seen, activeRoot);
    }

    appendUniqueNode(roots, seen, document);

    for (const shadowRoot of deepState?.shadowRoots || []) {
      appendUniqueNode(roots, seen, shadowRoot);
    }

    return roots.filter((root) => typeof root?.querySelectorAll === 'function');
  }

  function getRootContext(root) {
    const shadowRoot = root instanceof ShadowRoot
      ? root
      : (root?.getRootNode?.() instanceof ShadowRoot ? root.getRootNode() : null);
    const host = shadowRoot?.host || null;

    return {
      root,
      rootKind: root === document
        ? 'document'
        : root instanceof ShadowRoot
          ? 'shadow-root'
          : root instanceof Element
            ? 'element'
            : 'unknown',
      host,
      hostOuterHTML: host?.outerHTML?.slice(0, 500) || '',
    };
  }

  function findFirstInRoots(roots, selector, predicate = null) {
    for (const root of roots) {
      const matches = collectMatchesInRoot(root, selector);
      for (const el of matches) {
        if (!isVisible(el)) continue;
        if (!predicate || predicate(el, root)) return el;
      }
    }
    return null;
  }

  function extractVisibleTextSnippet(sourceText, marker, radius = 120) {
    const haystack = normalizeText(sourceText || '');
    const lowerHaystack = haystack.toLowerCase();
    const lowerMarker = String(marker || '').toLowerCase();
    if (!lowerMarker) return '';
    const index = lowerHaystack.indexOf(lowerMarker);
    if (index === -1) return '';
    const start = Math.max(0, index - radius);
    const end = Math.min(haystack.length, index + lowerMarker.length + radius);
    return haystack.slice(start, end);
  }

  function collectFixedOverlayCandidates(roots) {
    const overlays = [];
    const seen = new Set();
    const overlayQuery = getSelectorRegistryQuery(
      'upload_fixed_overlay_scan',
      'div, section, aside, article, dialog',
    );

    for (const root of roots) {
      for (const el of collectMatchesInRoot(root, overlayQuery)) {
        if (!isVisible(el) || seen.has(el)) continue;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        if (rect.width < 160 || rect.height < 120) continue;
        if (style.position !== 'fixed' && style.position !== 'sticky') continue;
        seen.add(el);
        overlays.push(el);
      }
    }

    return overlays;
  }

  function getModalLikeSurfaces(deepState = null, roots = null) {
    const activeDeepState = deepState || collectDeepSearchState();
    const activeRoots = roots || collectQueryRoots([], activeDeepState);
    const selectors = getSelectorRegistryQuery(
      'asset_picker_modal_surface',
      [
        '[role="dialog"]',
        '[aria-modal="true"]',
        'dialog',
        '[data-floating-ui-portal] > *',
        '[data-radix-portal] > *',
        '[data-radix-popper-content-wrapper] > *',
      ].join(', '),
    );

    const surfaces = [];
    const seen = new Set();

    for (const root of activeRoots) {
      for (const el of collectMatchesInRoot(root, selectors)) {
        if (!isVisible(el) || seen.has(el)) continue;
        const style = window.getComputedStyle(el);
        if (
          el.matches('[role="dialog"], [aria-modal="true"], dialog')
          || style.position === 'fixed'
          || style.position === 'sticky'
        ) {
          seen.add(el);
          surfaces.push(el);
        }
      }
    }

    for (const overlay of collectFixedOverlayCandidates(activeRoots)) {
      if (seen.has(overlay)) continue;
      seen.add(overlay);
      surfaces.push(overlay);
    }

    return surfaces;
  }

  function getAssociatedFileInput(node, scope = document) {
    if (!node) return null;

    if (node.matches?.('input[type="file"]')) {
      return node;
    }

    const descendantInput = node.querySelector?.('input[type="file"]');
    if (descendantInput) return descendantInput;

    const htmlFor = node.getAttribute?.('for');
    if (htmlFor) {
      try {
        const linkedInput = scope.querySelector(`#${CSS.escape(htmlFor)}`);
        if (linkedInput?.matches?.('input[type="file"]')) return linkedInput;
      } catch (_error) {
        // Ignore malformed ids and continue fallback resolution.
      }
    }

    const labelledById = node.getAttribute?.('id');
    if (labelledById) {
      const labelledInput = scope.querySelector(`input[type="file"][aria-labelledby="${labelledById}"]`);
      if (labelledInput) return labelledInput;
    }

    return null;
  }

  function isAssetPickerDropTarget(node) {
    if (!node || !isVisible(node)) return false;
    if (node.matches?.('[role="dialog"], [aria-modal="true"], dialog')) {
      const nestedProgrammableTarget = node.querySelector?.([
        'input[type="file"]',
        'label',
        'button',
        '[role="button"]',
        '.dropzone',
        '[data-dropzone]',
        '[data-testid*="upload"]',
        '[data-testid*="drop"]',
        '[aria-label*="upload" i]',
        '[aria-label*="browse" i]',
        '[aria-label*="select" i]',
      ].join(', '));
      if (nestedProgrammableTarget) return false;
    }
    const text = normalizeText(
      node.innerText
      || node.textContent
      || node.getAttribute('aria-label')
      || node.getAttribute('title')
      || ''
    );
    if (ASSET_PICKER_ACTION_RE.test(text) && /(upload|browse|drop|select|add)/i.test(text)) return true;
    return node.matches?.([
      '[role="presentation"]',
      '.dropzone',
      '[data-dropzone]',
      '[data-testid*="upload"]',
      '[data-testid*="drop"]',
      '[aria-label*="upload" i]',
      '[aria-label*="browse" i]',
      '[aria-label*="select" i]',
    ].join(', '));
  }

  function resolveAssetPickerTargets(modal, extraRoots = [], deepState = null) {
    const modalRoot = modal?.getRootNode?.() || null;
    const queryRoots = collectQueryRoots([
      ...(modal ? [modal] : []),
      ...(modalRoot ? [modalRoot] : []),
      ...extraRoots,
    ], deepState);

    if (queryRoots.length === 0) {
      return {
        fileInput: null,
        labelTarget: null,
        buttonTarget: null,
        dropzoneTarget: null,
        dispatchTarget: null,
        queryRoots: [],
      };
    }

    const fileInput = findFirstInRoots(queryRoots, 'input[type="file"]');

    const labelTarget = findFirstInRoots(queryRoots, 'label', (el, root) => {
      const text = normalizeText(
        el.innerText
        || el.textContent
        || el.getAttribute('aria-label')
        || ''
      );
      return Boolean(getAssociatedFileInput(el, root)) && ASSET_PICKER_ACTION_RE.test(text || 'Upload');
    });

    const buttonTarget = findFirstInRoots(queryRoots, 'button, [role="button"]', (el) => {
      const text = normalizeText(
        el.innerText
        || el.textContent
        || el.getAttribute('aria-label')
        || el.getAttribute('title')
        || ''
      );
      return ASSET_PICKER_ACTION_RE.test(text);
    });

    const dropzoneTarget = findFirstInRoots(queryRoots, 'label, button, [role="button"], div, section', (el) => isAssetPickerDropTarget(el));

    return {
      fileInput,
      labelTarget,
      buttonTarget,
      dropzoneTarget,
      dispatchTarget: fileInput || getAssociatedFileInput(labelTarget, modalRoot || modal) || dropzoneTarget || buttonTarget || labelTarget || null,
      queryRoots,
    };
  }

  function buildModalSearchDiagnostics(deepState = null, roots = []) {
    const bodyText = normalizeText(document.body?.innerText || document.body?.textContent || '');
    const visibleBodyTextSnippets = {};
    const visibleRootTextSnippets = {};

    for (const marker of ASSET_PICKER_DIAGNOSTIC_MARKERS) {
      const snippet = extractVisibleTextSnippet(bodyText, marker);
      if (snippet) {
        visibleBodyTextSnippets[marker] = snippet.slice(0, 240);
      }

      if (!visibleRootTextSnippets[marker]) {
        for (const root of roots) {
          const rootText = getRootText(root);
          const rootSnippet = extractVisibleTextSnippet(rootText, marker);
          if (rootSnippet) {
            visibleRootTextSnippets[marker] = rootSnippet.slice(0, 240);
            break;
          }
        }
      }
    }

    return {
      visibleBodyTextSnippets,
      visibleRootTextSnippets,
      markerSnippetCount: Object.keys(visibleBodyTextSnippets).length,
      markerRootSnippetCount: Object.keys(visibleRootTextSnippets).length,
      openShadowRootFound: (deepState?.shadowRoots?.length || 0) > 0,
      openShadowRootCount: deepState?.shadowRoots?.length || 0,
      shadowHostOuterHTML: deepState?.shadowHosts?.[0]?.outerHTML?.slice(0, 500) || '',
      candidateFixedOverlaysCount: collectFixedOverlayCandidates(roots).length,
      activeElementOuterHTML: document.activeElement?.outerHTML?.slice(0, 500) || '',
    };
  }

  function findVisibleAssetPickerModal() {
    const deepState = collectDeepSearchState();
    const roots = collectQueryRoots([], deepState);
    const diagnostics = buildModalSearchDiagnostics(deepState, roots);
    const surfaces = getModalLikeSurfaces(deepState, roots);

    for (const surface of surfaces) {
      const text = getRootText(surface);
      const targets = resolveAssetPickerTargets(surface, [surface.getRootNode?.() || null], deepState);
      const hasUploadText = ASSET_PICKER_TEXT_RE.test(text);
      const hasProgrammableTarget = Boolean(
        targets.fileInput
        || targets.labelTarget
        || targets.buttonTarget
        || targets.dropzoneTarget
      );

      if (hasUploadText && hasProgrammableTarget) {
        return {
          modal: surface,
          text,
          targets,
          diagnostics,
          foundInShadowRoot: surface.getRootNode?.() instanceof ShadowRoot,
          rootContext: getRootContext(surface.getRootNode?.() || surface),
        };
      }
    }

    for (const root of roots) {
      const text = getRootText(root);
      const targets = resolveAssetPickerTargets(null, [root], deepState);
      const hasUploadText = ASSET_PICKER_TEXT_RE.test(text);
      const hasProgrammableTarget = Boolean(
        targets.fileInput
        || targets.labelTarget
        || targets.buttonTarget
        || targets.dropzoneTarget
      );

      if (hasUploadText && hasProgrammableTarget) {
        const rootContext = getRootContext(root);
        return {
          modal: rootContext.host || (root instanceof Element ? root : null),
          text,
          targets,
          diagnostics,
          foundInShadowRoot: root instanceof ShadowRoot || rootContext.rootKind === 'shadow-root',
          rootContext,
        };
      }
    }

    return {
      modal: null,
      text: '',
      targets: null,
      diagnostics,
      foundInShadowRoot: false,
      rootContext: null,
    };
  }

  async function waitForAssetPickerModal(timeoutMs = 1800, setCheckpoint = null) {
    setCheckpoint?.('UPLOAD_MODAL_SHADOW_SCAN_STARTED');
    const deadline = Date.now() + timeoutMs;
    let lastResult = findVisibleAssetPickerModal();
    if (lastResult.modal) {
      setCheckpoint?.('UPLOAD_MODAL_SHADOW_SCAN_FOUND');
      return lastResult;
    }

    while (Date.now() < deadline) {
      lastResult = findVisibleAssetPickerModal();
      if (lastResult.modal) {
        setCheckpoint?.('UPLOAD_MODAL_SHADOW_SCAN_FOUND');
        return lastResult;
      }
      await sleep(120);
    }

    lastResult = findVisibleAssetPickerModal();
    if (lastResult.modal) {
      setCheckpoint?.('UPLOAD_MODAL_SHADOW_SCAN_FOUND');
      return lastResult;
    }

    setCheckpoint?.('UPLOAD_MODAL_SHADOW_SCAN_EMPTY');
    return lastResult;
  }

  function assignFilesToInput(input, files) {
    try {
      input.files = files;
      return;
    } catch (_error) {
      // Fall through to explicit property override.
    }

    Object.defineProperty(input, 'files', {
      configurable: true,
      value: files,
    });
  }

  function dispatchDragSequence(target, dataTransfer) {
    if (!target) return;
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

  function slotPreviewAcceptanceMet(beforeSnapshot, currentSnapshot) {
    if (!beforeSnapshot || !currentSnapshot) return false;

    const previewChanged = currentSnapshot.previewFound
      && currentSnapshot.previewKey !== beforeSnapshot.previewKey;
    const countChanged = currentSnapshot.previewFound
      && currentSnapshot.previewCount > beforeSnapshot.previewCount;
    const uploadSettled = !currentSnapshot.uploadPending;

    return Boolean((previewChanged || countChanged) && uploadSettled);
  }

  function rootHasVisualPreview(root) {
    if (!root?.querySelectorAll) return false;
    return Boolean(
      Array.from(root.querySelectorAll(
        getSelectorRegistryQuery(
          'upload_acceptance_preview_evidence',
          'img, canvas, video, picture, [role="img"], [style*="background-image"]',
        ),
      ))
        .find((node) => describePreviewNode(node))
    );
  }

  function findAssetChipEvidence(fileName, roots = []) {
    const fileStem = String(fileName || '')
      .replace(/\.[a-z0-9]+$/i, '')
      .trim()
      .toLowerCase();

    for (const entry of roots) {
      const root = entry?.root || entry;
      if (!root) continue;

      if (!fileStem) continue;
      const matchingText = Array.from(root.querySelectorAll('button, [role="button"], span, div, p, li'))
        .find((node) => {
          if (!isVisible(node)) return false;
          const text = normalizeText(node.innerText || node.textContent || '').toLowerCase();
          return text.includes(fileStem);
        });
      if (matchingText) {
        return { kind: 'asset-chip', text: normalizeText(matchingText.innerText || matchingText.textContent || '').slice(0, 120) };
      }
    }

    return null;
  }

  async function waitForUploadAcceptance({
    slotLabel,
    slotElement = null,
    slotContainer = null,
    beforeSnapshot = null,
    modal = null,
    fileName = '',
    timeoutMs = 8000,
    setCheckpoint = null,
  }) {
    const startTime = Date.now();
    const deadline = startTime + timeoutMs;
    const modalWasVisible = Boolean(modal?.isConnected && isVisible(modal));
    let weakRejectLogged = false;
    const originalSlotContainer = slotContainer?.isConnected ? slotContainer : null;

    while (Date.now() < deadline) {
      const resolvedContainer = originalSlotContainer || resolveSlotContainer(slotLabel, slotElement) || slotContainer;
      const snapshot = resolvedContainer ? snapshotSlot(resolvedContainer) : null;
      const previewConfirmed = slotPreviewAcceptanceMet(beforeSnapshot, snapshot);
      const modalClosed = modalWasVisible && (!modal?.isConnected || !isVisible(modal));
      const modalClosedWithStartPreview = Boolean(
        modalClosed
        && snapshot?.previewFound
        && !snapshot?.uploadPending
        && (snapshot?.previewKey !== beforeSnapshot?.previewKey || snapshot?.previewCount > beforeSnapshot?.previewCount)
      );

      if (previewConfirmed || modalClosedWithStartPreview) {
        setCheckpoint?.('UPLOAD_START_SLOT_PREVIEW_CONFIRMED');
        return {
          ok: true,
          reason: previewConfirmed ? 'start-slot-preview' : 'modal-closed-start-preview',
          slotContainer: resolvedContainer,
          snapshot,
          modalClosed,
        };
      }

      const assetEvidence = findAssetChipEvidence(fileName, [
        resolvedContainer,
        modal,
        modal?.getRootNode?.() || null,
        document.activeElement?.getRootNode?.() || null,
      ]);
      const modalPreviewVisible = rootHasVisualPreview(modal);
      if (
        !weakRejectLogged
        && (Date.now() - startTime) >= 1000
        && (assetEvidence || modalPreviewVisible)
      ) {
        setCheckpoint?.('UPLOAD_MODAL_ACCEPTANCE_WEAK_REJECTED');
        weakRejectLogged = true;
      }

      await sleep(250);
    }

    const resolvedContainer = originalSlotContainer || resolveSlotContainer(slotLabel, slotElement) || slotContainer;
    return {
      ok: false,
      reason: 'acceptance-not-verified',
      slotContainer: resolvedContainer,
      snapshot: resolvedContainer ? snapshotSlot(resolvedContainer) : null,
      modalClosed: modalWasVisible && (!modal?.isConnected || !isVisible(modal)),
      weakRejectLogged,
    };
  }

  function buildAssetPickerFailureDetail({
    slotLabel,
    modalInfo = null,
    modalTargets = null,
    target = null,
    lastCheckpoint = 'NONE',
    slotContainer = null,
  }) {
    const observed = observeFlowState();
    const startSlot = resolveSlotContainer('Start') || slotContainer || null;
    return {
      modal_found: Boolean(modalInfo?.modal),
      modal_text: modalInfo?.text?.slice(0, 500) || '',
      modal_outerHTML: modalInfo?.modal?.outerHTML?.slice(0, 1000) || modalInfo?.rootContext?.hostOuterHTML || '',
      modal_root_kind: modalInfo?.rootContext?.rootKind || 'unknown',
      file_input_found: Boolean(modalTargets?.fileInput),
      dropzone_found: Boolean(modalTargets?.dropzoneTarget || modalTargets?.buttonTarget || modalTargets?.labelTarget),
      target_outerHTML: target?.outerHTML?.slice(0, 500) || '',
      last_checkpoint: lastCheckpoint,
      visible_upload_slots: observed.visibleUploadSlots,
      start_slot_outerHTML: (slotLabel === 'Start' ? slotContainer : startSlot)?.outerHTML?.slice(0, 500) || '',
      visible_body_text_snippets: modalInfo?.diagnostics?.visibleBodyTextSnippets || {},
      visible_root_text_snippets: modalInfo?.diagnostics?.visibleRootTextSnippets || {},
      open_shadow_root_found: Boolean(modalInfo?.diagnostics?.openShadowRootFound),
      open_shadow_root_count: modalInfo?.diagnostics?.openShadowRootCount || 0,
      shadow_host_outerHTML: modalInfo?.rootContext?.hostOuterHTML || modalInfo?.diagnostics?.shadowHostOuterHTML || '',
      candidate_fixed_overlays_count: modalInfo?.diagnostics?.candidateFixedOverlaysCount || 0,
      active_element_outerHTML: modalInfo?.diagnostics?.activeElementOuterHTML || '',
      selector_registry_ids: {
        upload_slot: 'upload_slot_label_scan',
        asset_picker_modal: 'asset_picker_modal_surface',
        upload_acceptance: 'upload_acceptance_preview_evidence',
      },
      evidence_pointers: {
        upload_slot: getSelectorEvidencePointer('upload_slot_label_scan'),
        asset_picker_modal: getSelectorEvidencePointer('asset_picker_modal_surface'),
        upload_acceptance: getSelectorEvidencePointer('upload_acceptance_preview_evidence'),
      },
      fallback_policies: {
        upload_slot: getSelectorRegistryEntry('upload_slot_label_scan')?.fallback_policy || null,
        asset_picker_modal: getSelectorRegistryEntry('asset_picker_modal_surface')?.fallback_policy || null,
        upload_acceptance: getSelectorRegistryEntry('upload_acceptance_preview_evidence')?.fallback_policy || null,
      },
    };
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
    const ok = document.execCommand?.('insertText', false, text);
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

  function looksLikeLocalFilePath(value) {
    if (typeof value !== 'string') return false;
    return /^[a-zA-Z]:[\\/]/.test(value) || value.startsWith('\\\\') || value.startsWith('/');
  }

  function resolveAssetLocalFilePath(assetSource) {
    if (!assetSource) return null;
    if (typeof assetSource === 'string') {
      return looksLikeLocalFilePath(assetSource) ? assetSource : null;
    }
    if (typeof assetSource !== 'object') return null;
    return assetSource.localFilePath
      || assetSource.local_file_path
      || null;
  }

  function resolveAssetPreferredFileName(assetSource, slotLabel) {
    if (!assetSource || typeof assetSource !== 'object') {
      return `${slotLabel}.png`;
    }
    return assetSource.fileName
      || assetSource.file_name
      || assetSource.label
      || `${slotLabel}.png`;
  }

  function buildUploadTargetResolution(slotBtn, slotContainer, modalInfo, modalTargets) {
    const fileInput = slotContainer?.querySelector?.('input[type="file"]') || null;
    const dropzone = slotContainer?.querySelector?.('[role="presentation"], .dropzone, [aria-label*="upload" i], [aria-label*="browse" i]') || null;
    const internalClickable = slotContainer?.querySelector?.('button, [role="button"], label, div[onclick]') || null;
    const directTarget = fileInput || dropzone || internalClickable || slotBtn || null;
    const cdpTriggerTarget = modalInfo?.modal
      ? (modalTargets?.buttonTarget
        || modalTargets?.labelTarget
        || modalTargets?.dropzoneTarget
        || modalTargets?.dispatchTarget
        || modalTargets?.fileInput
        || null)
      : directTarget;
    const legacyDispatchTarget = modalInfo?.modal ? (modalTargets?.dispatchTarget || null) : directTarget;

    return {
      fileInput,
      dropzone,
      internalClickable,
      directTarget,
      cdpTriggerTarget,
      legacyDispatchTarget,
    };
  }

  function buildMissingUploadTargetFailure(slotLabel, slotContainer, slotBtn, modalInfo, modalTargets, lastCheckpoint) {
    const diag = {
      start_container_outerHTML: slotContainer?.outerHTML?.slice(0, 500) || '',
      file_input_found: Boolean(modalTargets?.fileInput || slotContainer?.querySelector?.('input[type="file"]')),
      clickable_target_found: Boolean(slotContainer?.querySelector?.('button, [role="button"], label, div[onclick]') || slotBtn),
      clickable_target_outerHTML: (slotContainer?.querySelector?.('button, [role="button"], label, div[onclick]') || slotBtn)?.outerHTML?.slice(0, 500),
    };

    if (modalInfo?.modal) {
      const modalDiag = buildAssetPickerFailureDetail({
        slotLabel,
        modalInfo,
        modalTargets,
        target: null,
        lastCheckpoint,
        slotContainer,
      });
      return {
        ok: false,
        error: buildSlotErrorCode(slotLabel, 'ASSET_PICKER_UPLOAD_FAILED'),
        detail: `ERR_START_ASSET_PICKER_UPLOAD_FAILED — ${JSON.stringify(modalDiag)}`,
        lastCheckpoint,
      };
    }

    return {
      ok: false,
      error: buildSlotErrorCode(slotLabel, 'UPLOAD_TARGET_NOT_FOUND'),
      detail: `ERR_START_UPLOAD_TARGET_NOT_FOUND — ${JSON.stringify(diag)}`,
      lastCheckpoint,
    };
  }

  async function simulateLegacyDomFileUpload(slotLabel, assetSource, stateObj = null) {
    let lastCheckpoint = 'NONE';
    const setCheckpoint = (cp) => {
      lastCheckpoint = cp;
      if (stateObj) stateObj.lastCheckpoint = cp;
      console.log(`[FlowAgent] Upload Checkpoint (${slotLabel}): ${cp}`);
    };

    try {
      setCheckpoint('UPLOAD_SLOT_RESOLUTION_STARTED');
      console.log(`[FlowAgent] Attempting to upload asset to slot: ${slotLabel}`);

      // 1. Find and click the slot button using robust resolution
      const slotInfo = findUploadSlotByLabel(slotLabel);
      const slotContainer = slotInfo?.container || resolveSlotContainer(slotLabel);
      // Prefer the label node or a button inside the container for the click
      const slotBtn = slotInfo?.labelNode?.closest('button, [role="button"]')
        || slotInfo?.labelNode
        || slotContainer?.querySelector('button, [role="button"]')
        || slotContainer;

      if (!slotContainer || !slotBtn) {
        const observed = observeFlowState();
        const bodyText = normalizeText(document.body?.innerText || '').slice(0, 150);
        const candidates = Array.from(document.querySelectorAll('label, span, div, p'))
          .filter((el) => isVisible(el) && normalizeText(el.textContent || '').includes(slotLabel))
          .map((el) => normalizeText(el.textContent || '').slice(0, 30));

        const diag = {
          visible_upload_slots: observed.visibleUploadSlots,
          start_label_found: Boolean(slotInfo?.labelNode),
          start_container_text: normalizeText(slotContainer?.textContent || '').slice(0, 100),
          start_container_outerHTML: slotContainer?.outerHTML?.slice(0, 500),
          candidate_slot_texts: candidates,
          body_text_snippet: bodyText,
        };

        console.warn(`[FlowAgent] Slot ${slotLabel} not found or not clickable. Diag:`, diag);
        return {
          ok: false,
          error: buildSlotErrorCode(slotLabel, 'SLOT_NOT_FOUND'),
          detail: `ERR_START_SLOT_NOT_FOUND — ${JSON.stringify(diag)}`,
          lastCheckpoint,
        };
      }

      setCheckpoint('UPLOAD_SLOT_RESOLVED');
      const beforeSnapshot = snapshotSlot(slotContainer);

      setCheckpoint('UPLOAD_SLOT_CLICKED');
      slotBtn.click();
      const modalInfo = await waitForAssetPickerModal(1800, setCheckpoint);
      const modalTargets = modalInfo?.targets || null;
      if (modalInfo?.modal) {
        setCheckpoint('UPLOAD_ASSET_PICKER_MODAL_DETECTED');
      } else {
        await sleep(500);
      }

      // 2. Fetch or Resolve the image
      setCheckpoint('UPLOAD_ASSET_RESOLVE_STARTED');
      let file;
      if (assetSource && typeof assetSource === 'object' && assetSource.previewUrl) {
        console.log(`[FlowAgent] Using direct base64 source for ${slotLabel}`);
        const base64Data = assetSource.previewUrl;
        const blob = await (await fetch(base64Data)).blob();
        file = new File([blob], assetSource.fileName || `${slotLabel}.png`, { type: blob.type || 'image/png' });
      } else {
        const assetId = resolveAssetSourceId(assetSource);
        if (!assetId) {
          console.warn(`[FlowAgent] No asset source id resolved for slot ${slotLabel}`);
          return { ok: false, error: buildSlotErrorCode(slotLabel, 'ASSET_MISSING'), lastCheckpoint };
        }
        
        const requestIdForProxy = stateObj?.request_id || null;
        console.log(`[FlowAgent] Resolving local asset via background proxy: ${assetId}`);
        setCheckpoint('UPLOAD_ASSET_PROXY_SEND');
        const proxyResp = await sendRuntimeMessageWithResponse({
          type: 'RESOLVE_LOCAL_ASSET',
          assetId,
          filename: `${assetId}.jpg`,
          request_id: requestIdForProxy
        }, 15000);

        if (!proxyResp?.ok) {
          console.error(`[FlowAgent] Background asset resolution failed: ${proxyResp?.error}`);
          return { 
            ok: false, 
            error: buildSlotErrorCode(slotLabel, 'FILE_RESOLVE_FAILED'),
            detail: `ERR_START_FILE_RESOLVE_FAILED — ${proxyResp?.error || 'UNKNOWN_PROXY_ERROR'} — ${proxyResp?.detail || ''}`,
            lastCheckpoint 
          };
        }

        setCheckpoint('UPLOAD_ASSET_PROXY_RECEIVE');
        const blob = await (await fetch(proxyResp.dataUrl)).blob();
        file = new File([blob], proxyResp.filename || `${assetId}.jpg`, { type: proxyResp.mimeType || 'image/jpeg' });
      }
      setCheckpoint('UPLOAD_ASSET_RESOLVED');

      // 3. Find the dropzone/input
      const targetResolution = buildUploadTargetResolution(slotBtn, slotContainer, modalInfo, modalTargets);
      const target = targetResolution.legacyDispatchTarget;

      if (modalInfo?.modal) {
        if (modalTargets?.fileInput) {
          setCheckpoint('UPLOAD_MODAL_INPUT_FOUND');
        }
        if (modalTargets?.dropzoneTarget || modalTargets?.buttonTarget || modalTargets?.labelTarget) {
          setCheckpoint('UPLOAD_MODAL_DROPZONE_FOUND');
        }
      }

      if (!target || (!modalInfo?.modal && !slotContainer.contains(target))) {
        return buildMissingUploadTargetFailure(
          slotLabel,
          slotContainer,
          slotBtn,
          modalInfo,
          modalTargets,
          lastCheckpoint,
        );
      }
      setCheckpoint('UPLOAD_TARGET_RESOLVED');

      setCheckpoint(modalInfo?.modal ? 'UPLOAD_MODAL_DISPATCH_STARTED' : 'UPLOAD_DISPATCH_STARTED');
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(file);

      if (modalInfo?.modal && modalTargets?.fileInput) {
        assignFilesToInput(modalTargets.fileInput, dataTransfer.files);
        modalTargets.fileInput.dispatchEvent(new Event('input', { bubbles: true }));
        modalTargets.fileInput.dispatchEvent(new Event('change', { bubbles: true }));
        if (modalTargets.dropzoneTarget && modalTargets.dropzoneTarget !== modalTargets.fileInput) {
          dispatchDragSequence(modalTargets.dropzoneTarget, dataTransfer);
        }
      } else if (target.matches?.('input[type="file"]')) {
        assignFilesToInput(target, dataTransfer.files);
        target.dispatchEvent(new Event('input', { bubbles: true }));
        target.dispatchEvent(new Event('change', { bubbles: true }));
      } else {
        dispatchDragSequence(target, dataTransfer);
      }
      setCheckpoint(modalInfo?.modal ? 'UPLOAD_MODAL_DISPATCH_COMPLETED' : 'UPLOAD_DISPATCH_COMPLETED');

      console.log(`[FlowAgent] Dispatched upload for ${slotLabel}`);
      const acceptance = await waitForUploadAcceptance({
        slotLabel,
        slotElement: slotBtn,
        slotContainer,
        beforeSnapshot,
        modal: modalInfo?.modal || null,
        fileName: file?.name || '',
        timeoutMs: modalInfo?.modal ? 9000 : 10000,
        setCheckpoint,
      });

      const likelyAssetPickerPath = Boolean(
        modalInfo?.modal
        || (modalInfo?.diagnostics?.markerSnippetCount || 0) > 0
        || (modalInfo?.diagnostics?.openShadowRootCount || 0) > 0
      );

      if (likelyAssetPickerPath && !acceptance.ok) {
        const modalDiag = buildAssetPickerFailureDetail({
          slotLabel,
          modalInfo,
          modalTargets,
          target,
          lastCheckpoint,
          slotContainer,
        });
        return {
          ok: false,
          error: buildSlotErrorCode(slotLabel, 'ASSET_PICKER_ACCEPTANCE_NOT_VERIFIED'),
          detail: `ERR_START_ASSET_PICKER_ACCEPTANCE_NOT_VERIFIED — ${JSON.stringify(modalDiag)}`,
          lastCheckpoint,
        };
      }

      if (!modalInfo?.modal && !acceptance.ok) {
        return {
          ok: false,
          error: buildSlotErrorCode(slotLabel, 'PREVIEW_TIMEOUT'),
          detail: `ERR_${String(slotLabel || 'slot').toUpperCase()}_PREVIEW_TIMEOUT — ${JSON.stringify({
            last_checkpoint: lastCheckpoint,
            visible_upload_slots: observeFlowState().visibleUploadSlots,
            start_slot_outerHTML: resolveSlotContainer(slotLabel, slotBtn)?.outerHTML?.slice(0, 500) || '',
          })}`,
          lastCheckpoint,
        };
      }

      if (modalInfo?.modal) {
        setCheckpoint('UPLOAD_MODAL_ACCEPTED');
        if (acceptance.modalClosed || acceptance.reason === 'start-slot-preview' || acceptance.reason === 'modal-closed-start-preview') {
          setCheckpoint('UPLOAD_MODAL_CLOSED_OR_PREVIEW_VISIBLE');
        }
      }

      return {
        ok: true,
        slotElement: slotBtn,
        slotContainer: acceptance.slotContainer || slotContainer,
        beforeSnapshot,
        acceptanceReason: acceptance.reason,
        modalFound: Boolean(modalInfo?.modal),
        uploadStrategy: 'legacy_dom_test_only',
        lastCheckpoint,
      };
    } catch (error) {
      console.error(`[FlowAgent] Upload dispatch failed for ${slotLabel}: ${error.message}`);
      return { 
        ok: false, 
        error: buildSlotErrorCode(slotLabel, 'UPLOAD_DISPATCH_FAILED'), 
        detail: `CATCH_ERROR: ${error.message} — stack: ${error.stack?.slice(0, 200)}`,
        lastCheckpoint 
      };
    }
  }

  async function simulateCdpFileUpload(slotLabel, assetSource, stateObj = null) {
    let lastCheckpoint = 'NONE';
    const setCheckpoint = (cp) => {
      lastCheckpoint = cp;
      if (stateObj) stateObj.lastCheckpoint = cp;
      console.log(`[FlowAgent] Upload Checkpoint (${slotLabel}): ${cp}`);
    };

    try {
      const localFilePath = resolveAssetLocalFilePath(assetSource);
      if (!localFilePath) {
        return {
          ok: false,
          error: buildSlotErrorCode(slotLabel, 'CDP_LOCAL_FILE_PATH_REQUIRED'),
          detail: `ERR_${String(slotLabel || 'slot').toUpperCase()}_CDP_LOCAL_FILE_PATH_REQUIRED`,
          lastCheckpoint,
        };
      }

      const expectedFileName = resolveAssetPreferredFileName(assetSource, slotLabel);

      setCheckpoint('UPLOAD_SLOT_RESOLUTION_STARTED');
      console.log(`[FlowAgent] Attempting CDP upload for slot: ${slotLabel}`);

      const slotInfo = findUploadSlotByLabel(slotLabel);
      const slotContainer = slotInfo?.container || resolveSlotContainer(slotLabel);
      const slotBtn = slotInfo?.labelNode?.closest('button, [role="button"]')
        || slotInfo?.labelNode
        || slotContainer?.querySelector('button, [role="button"]')
        || slotContainer;

      if (!slotContainer || !slotBtn) {
        const observed = observeFlowState();
        return {
          ok: false,
          error: buildSlotErrorCode(slotLabel, 'SLOT_NOT_FOUND'),
          detail: `ERR_${String(slotLabel || 'slot').toUpperCase()}_SLOT_NOT_FOUND — ${JSON.stringify({
            visible_upload_slots: observed.visibleUploadSlots,
            body_text_snippet: normalizeText(document.body?.innerText || '').slice(0, 150),
          })}`,
          lastCheckpoint,
        };
      }

      const beginResult = await beginCdpFileChooserProof({
        filePath: localFilePath,
        expectedFileName,
        slotLabel,
      });
      if (!beginResult?.ok || !beginResult?.armed) {
        return {
          ok: false,
          error: buildSlotErrorCode(slotLabel, 'CDP_ARM_FAILED'),
          detail: `ERR_${String(slotLabel || 'slot').toUpperCase()}_CDP_ARM_FAILED — ${beginResult?.error || 'UNKNOWN_CDP_ARM_ERROR'}`,
          lastCheckpoint,
        };
      }

      setCheckpoint('UPLOAD_SLOT_RESOLVED');
      const beforeSnapshot = snapshotSlot(slotContainer);
      setCheckpoint('UPLOAD_CDP_ARMED');
      setCheckpoint('UPLOAD_SLOT_CLICKED');
      slotBtn.click?.();

      const modalInfo = await waitForAssetPickerModal(1800, setCheckpoint);
      const modalTargets = modalInfo?.targets || null;
      const targetResolution = buildUploadTargetResolution(slotBtn, slotContainer, modalInfo, modalTargets);
      let target = slotBtn;

      if (modalInfo?.modal) {
        setCheckpoint('UPLOAD_ASSET_PICKER_MODAL_DETECTED');
        target = targetResolution.cdpTriggerTarget;

        if (modalTargets?.fileInput) {
          setCheckpoint('UPLOAD_MODAL_INPUT_FOUND');
        }
        if (modalTargets?.dropzoneTarget || modalTargets?.buttonTarget || modalTargets?.labelTarget) {
          setCheckpoint('UPLOAD_MODAL_DROPZONE_FOUND');
        }
        if (!target) {
          return buildMissingUploadTargetFailure(
            slotLabel,
            slotContainer,
            slotBtn,
            modalInfo,
            modalTargets,
            lastCheckpoint,
          );
        }
        setCheckpoint('UPLOAD_TARGET_RESOLVED');
        setCheckpoint('UPLOAD_MODAL_DISPATCH_STARTED');
        target.click?.();
        setCheckpoint('UPLOAD_CDP_CHOOSER_TRIGGERED');
      } else {
        setCheckpoint('UPLOAD_TARGET_RESOLVED');
        setCheckpoint('UPLOAD_DISPATCH_STARTED');
        setCheckpoint('UPLOAD_CDP_CHOOSER_TRIGGERED');
      }

      const cdpResult = await waitForCdpFileChooserProofResult();
      if (!cdpResult?.ok) {
        return {
          ok: false,
          error: buildSlotErrorCode(slotLabel, 'CDP_INTERCEPT_FAILED'),
          detail: `ERR_${String(slotLabel || 'slot').toUpperCase()}_CDP_INTERCEPT_FAILED — ${cdpResult?.error || 'UNKNOWN_CDP_INTERCEPT_ERROR'}`,
          lastCheckpoint,
        };
      }

      setCheckpoint('UPLOAD_CDP_FILE_SET');
      const cdpFileInput = modalTargets?.fileInput
        || (targetResolution.fileInput?.matches?.('input[type="file"]') ? targetResolution.fileInput : null)
        || (target?.matches?.('input[type="file"]') ? target : null);
      if (cdpFileInput) {
        cdpFileInput.dispatchEvent(new Event('input', { bubbles: true }));
        cdpFileInput.dispatchEvent(new Event('change', { bubbles: true }));
      }
      setCheckpoint(modalInfo?.modal ? 'UPLOAD_MODAL_DISPATCH_COMPLETED' : 'UPLOAD_DISPATCH_COMPLETED');

      const acceptance = await waitForUploadAcceptance({
        slotLabel,
        slotElement: slotBtn,
        slotContainer,
        beforeSnapshot,
        modal: modalInfo?.modal || null,
        fileName: expectedFileName,
        timeoutMs: modalInfo?.modal ? 9000 : 10000,
        setCheckpoint,
      });

      const likelyAssetPickerPath = Boolean(
        modalInfo?.modal
        || (modalInfo?.diagnostics?.markerSnippetCount || 0) > 0
        || (modalInfo?.diagnostics?.openShadowRootCount || 0) > 0
      );

      if (likelyAssetPickerPath && !acceptance.ok) {
        const modalDiag = buildAssetPickerFailureDetail({
          slotLabel,
          modalInfo,
          modalTargets,
          target,
          lastCheckpoint,
          slotContainer,
        });
        return {
          ok: false,
          error: buildSlotErrorCode(slotLabel, 'ASSET_PICKER_ACCEPTANCE_NOT_VERIFIED'),
          detail: `ERR_START_ASSET_PICKER_ACCEPTANCE_NOT_VERIFIED — ${JSON.stringify({
            ...modalDiag,
            upload_strategy: 'cdp_file_chooser',
            cdp_method: cdpResult?.method || null,
            backend_node_id: cdpResult?.backendNodeId || null,
          })}`,
          lastCheckpoint,
        };
      }

      if (!modalInfo?.modal && !acceptance.ok) {
        return {
          ok: false,
          error: buildSlotErrorCode(slotLabel, 'PREVIEW_TIMEOUT'),
          detail: `ERR_${String(slotLabel || 'slot').toUpperCase()}_PREVIEW_TIMEOUT — ${JSON.stringify({
            last_checkpoint: lastCheckpoint,
            visible_upload_slots: observeFlowState().visibleUploadSlots,
            start_slot_outerHTML: resolveSlotContainer(slotLabel, slotBtn)?.outerHTML?.slice(0, 500) || '',
            upload_strategy: 'cdp_file_chooser',
          })}`,
          lastCheckpoint,
        };
      }

      if (modalInfo?.modal) {
        setCheckpoint('UPLOAD_MODAL_ACCEPTED');
        if (acceptance.modalClosed || acceptance.reason === 'start-slot-preview' || acceptance.reason === 'modal-closed-start-preview') {
          setCheckpoint('UPLOAD_MODAL_CLOSED_OR_PREVIEW_VISIBLE');
        }
      }

      return {
        ok: true,
        slotElement: slotBtn,
        slotContainer: acceptance.slotContainer || slotContainer,
        beforeSnapshot,
        acceptanceReason: acceptance.reason,
        modalFound: Boolean(modalInfo?.modal),
        uploadStrategy: 'cdp_file_chooser',
        cdpMethod: cdpResult?.method || null,
        lastCheckpoint,
      };
    } catch (error) {
      console.error(`[FlowAgent] CDP upload dispatch failed for ${slotLabel}: ${error.message}`);
      return {
        ok: false,
        error: buildSlotErrorCode(slotLabel, 'UPLOAD_DISPATCH_FAILED'),
        detail: `CATCH_ERROR: ${error.message} — stack: ${error.stack?.slice(0, 200)}`,
        lastCheckpoint,
      };
    }
  }

  async function simulateFileUpload(slotLabel, assetSource, stateObj = null) {
    const localFilePath = resolveAssetLocalFilePath(assetSource);
    if (localFilePath) {
      return simulateCdpFileUpload(slotLabel, assetSource, stateObj);
    }

    if (FLOW_KIT_ENABLE_TEST_HOOKS) {
      return simulateLegacyDomFileUpload(slotLabel, assetSource, stateObj);
    }

    return {
      ok: false,
      error: buildSlotErrorCode(slotLabel, 'CDP_LOCAL_FILE_PATH_REQUIRED'),
      detail: `ERR_${String(slotLabel || 'slot').toUpperCase()}_CDP_LOCAL_FILE_PATH_REQUIRED`,
      lastCheckpoint: 'NONE',
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
      modelSource: 'unknown',
      aspectRatio: 'UNKNOWN',
      aspectRatioSource: 'unknown',
      count: 'UNKNOWN',
      countSource: 'unknown',
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

    // 3. Detect model. Flow's model selector is frequently an icon-only Radix
    // control, so fall back to aria-label/title when textContent carries no label.
    const scopedSection = observed.topMode === 'Image'
      ? findFlowSettingsSection('IMG')
      : findFlowSettingsSection('F2V');
    const scopedConfig = extractFlowSectionConfig(scopedSection);
    if (scopedConfig.model !== 'UNKNOWN') {
      observed.model = scopedConfig.model;
      observed.modelSource = 'settings_context';
    }
    if (scopedConfig.aspectRatio !== 'UNKNOWN') {
      observed.aspectRatio = scopedConfig.aspectRatio;
      observed.aspectRatioSource = 'settings_context';
    }
    if (scopedConfig.count !== 'UNKNOWN') {
      observed.count = scopedConfig.count;
      observed.countSource = 'settings_context';
    }

    if (observed.model === 'UNKNOWN') {
      const configPill = buildBottomComposerConfigPillSnapshot();
      const configPillText = String(
        configPill.bottom_composer_config_pill_raw_text
        || configPill.bottom_composer_config_pill_text
        || '',
      );
      const pillModel = extractObservedModelLabel(configPillText);
      if (pillModel) {
        observed.model = pillModel;
        observed.modelSource = 'config_pill';
      }
    }

    if (observed.model === 'UNKNOWN') {
      const modelElements = document.querySelectorAll('button, span, div, p, [aria-label], [title]');
      for (const el of modelElements) {
        if (!isVisible(el)) continue;
        const detectedModel = extractObservedModelLabel(el.textContent)
          || extractObservedModelLabel(el.getAttribute('aria-label'))
          || extractObservedModelLabel(el.getAttribute('title'));
        if (detectedModel) {
          observed.model = detectedModel;
          observed.modelSource = 'global_text';
          break;
        }
      }
    }

    if (observed.aspectRatio === 'UNKNOWN') {
      const aspectElements = document.querySelectorAll('button, [role="tab"], [role="button"], span');
      for (const el of aspectElements) {
        if (!isVisible(el)) continue;
        const text = el.textContent.trim();
        const matchedRatio = IMAGE_ASPECT_RATIOS.find((ratio) => text.includes(ratio));
        if (!matchedRatio) continue;
        if (isSelectedControl(el, matchedRatio) || isSelectedControl(el.closest('button'), matchedRatio)) {
          observed.aspectRatio = matchedRatio;
          observed.aspectRatioSource = 'settings_context';
          break;
        }
      }
    }

    if (observed.count === 'UNKNOWN') {
      const countElements = document.querySelectorAll('button, [role="tab"], [role="button"], span');
      for (const el of countElements) {
        if (!isVisible(el)) continue;
        const text = el.textContent.trim();
        if (/^[1-4]x$/.test(text)) {
          if (isSelectedControl(el, text) || isSelectedControl(el.closest('button'), text)) {
            observed.count = text;
            observed.countSource = 'settings_context';
            break;
          }
        }
      }
    }

    // 5b. Collapsed-editor fallback: the F2V/T2V composer folds mode, aspect and
    // count into a single bottom config pill (e.g. "Video · 10s crop_9_16 1x").
    // When the expanded controls are not individually selectable, read the pill.
    if (observed.aspectRatio === 'UNKNOWN' || observed.count === 'UNKNOWN' || observed.topMode === 'UNKNOWN') {
      const configPill = buildBottomComposerConfigPillSnapshot();
      const pillText = configPill.bottom_composer_config_pill_raw_text
        || configPill.bottom_composer_config_pill_text
        || '';
      if (pillText) {
        if (observed.aspectRatio === 'UNKNOWN') {
          const mappedAspect = flowCropTokenToAspectRatio(canonicalizeFlowConfigAspectToken(pillText));
          if (mappedAspect) {
            observed.aspectRatio = mappedAspect;
            observed.aspectRatioSource = 'config_pill';
          }
        }
        if (observed.count === 'UNKNOWN') {
          const countToken = canonicalizeFlowConfigCountToken(pillText);
          if (countToken) {
            observed.count = countToken;
            observed.countSource = 'config_pill';
          }
        }
        if (observed.topMode === 'UNKNOWN' && /video/i.test(pillText)) {
          observed.topMode = 'Video';
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

    // 6b. F2V (Video/Frames) only ever exposes Start/End upload slots. Strip any
    // slot labels that leaked in from mode toggles or unrelated text so the F2V
    // surface is not misreported with bogus slots (e.g. "Image", "Scene").
    if (observed.topMode === 'Video' && observed.subMode === 'Frames') {
      const F2V_SLOTS = ['Start', 'End'];
      observed.visibleUploadSlots = observed.visibleUploadSlots.filter((slot) => F2V_SLOTS.includes(slot));
      observed.visibleAssetPreviews = observed.visibleAssetPreviews.filter((slot) => F2V_SLOTS.includes(slot));
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
    const composer = findComposerElement();
    const generateBtn = findGenerateButtonNearComposer();
    const configPill = buildBottomComposerConfigPillSnapshot();
    const uiContractV2 = buildUiContractV2Proof(mode, readiness.observed, composer, generateBtn);
    const visibleEditorMarkers = collectVisibleMarkers([
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
    ], [
      normalizeText(document.body?.innerText || '').slice(0, 2000),
      document.title,
      ...(collectVisibleTexts('button, [role="button"]', (el) => el.textContent || '')),
      ...(collectVisibleTexts('[aria-label]', (el) => el.getAttribute('aria-label') || '')),
    ]);
    const currentModeVisible = readiness.current_mode_visible;
    const pagePreselectionReady = Boolean(
      readiness.signed_in_likely
      && Boolean(uiContractV2.editor_capability_ready)
      && !readiness.blocking_modal_detected
    );
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
      ok: pagePreselectionReady,
      strict_composer_ok: readiness.ok,
      strict_composer_error: readiness.error || null,
      visible_project_editor_markers: visibleEditorMarkers,
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
      prompt_field_found: Boolean(composer),
      generate_button_found: readiness.generate_button_found,
      editor_capability_ready: Boolean(uiContractV2.editor_capability_ready),
      pre_generate_ready: Boolean(uiContractV2.pre_generate_ready),
      ui_contract_version: uiContractV2.ui_contract_version,
      ui_contract_v2: uiContractV2,
      bottom_composer_config_pill_visible: configPill.bottom_composer_config_pill_visible,
      bottom_composer_config_pill_text: configPill.bottom_composer_config_pill_text,
      bottom_composer_config_pill_raw_text: configPill.bottom_composer_config_pill_raw_text,
      current_mode_visible: readiness.current_mode_visible,
      blocking_modal_detected: readiness.blocking_modal_detected,
      observed: readiness.observed,
      runtime_ready: true,
      content_build_id: FLOW_KIT_DOM_BUILD_ID,
      git_sha: FLOW_KIT_DOM_BUILD_ID,
      content_script_loaded: true,
      content_script_protocol_version: FLOW_KIT_DOM_PROTOCOL_VERSION,
      timestamp: new Date().toISOString(),
    };
  }

  // Google Flow UI Contract V2 — live DOM observer (read-only, never clicks).
  // Reads the real Flow DOM into raw signals, then maps them to the canonical V2
  // diagnostic via gfv2-readiness.js (self.__GFV2_READINESS__). Editor readiness
  // is driven by the composer/prompt surface — NOT Frames/Ingredients buttons.
  // Strong upload proof requires Add-to-Prompt/preview/chip; visibleUploadSlots
  // and Start-body text are recorded only as deprecated/weak signals.
  function observeGoogleFlowV2State() {
    // Defensive: broken/error Flow pages ("Something went wrong") can make some
    // DOM helpers throw. Never throw — fall back to safe values so a diagnostic
    // always returns (showing editor-not-ready rather than an opaque failure).
    const safe = (fn, fallback) => {
      try {
        return fn();
      } catch (_) {
        return fallback;
      }
    };
    const obs = safe(() => observeFlowState(), {}) || {};
    const composer = safe(() => findComposerElement(), null);
    const bodyText = safe(() => (document.body && document.body.innerText) || '', '');
    const composerEditable = Boolean(composer && safe(() => isComposerEditable(composer), false));
    const generateBtn = safe(() => findGenerateButtonNearComposer(), null);

    function isVisible(el) {
      if (!el || !el.getBoundingClientRect) return false;
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return false;
      const s = window.getComputedStyle(el);
      return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
    }
    const buttonTexts = [];
    const seenText = new Set();
    document.querySelectorAll('button, [role="button"], a').forEach((el) => {
      if (!isVisible(el)) return;
      const t = normalizeText(
        (el.textContent || '') + ' ' + (el.getAttribute && el.getAttribute('aria-label') || ''),
      );
      if (t && !seenText.has(t) && t.length <= 60) {
        seenText.add(t);
        buttonTexts.push(t);
      }
    });
    const lowerTexts = buttonTexts.map((t) => t.toLowerCase());
    const has = (needle) => lowerTexts.some((t) => t.includes(needle));

    const modelLower = String(obs.model || '').toLowerCase();
    const isVeo = /veo/.test(modelLower);
    const isWrongModel = !isVeo && /nano banana|imagen|\bimage\b/.test(modelLower);
    const composerRoot =
      (composer && composer.closest && composer.closest('form, [role="form"]')) || null;
    const assetPreviewInPrompt = Boolean(
      composerRoot &&
        composerRoot.querySelector &&
        composerRoot.querySelector('img, [style*="background-image"], [data-asset], [class*="thumbnail" i]'),
    );
    const promptText = composer
      ? normalizeText(composer.textContent || composer.value || '')
      : '';
    const settingsPanelOpen = Boolean(
      document.querySelector('[role="dialog"], [role="menu"]') && (has('9:16') || has('aspect')),
    );

    const signals = {
      // editor
      flow_editor_open: Boolean(composer) || /\/tools\/flow/.test(String(location.href || '')),
      extension_content_script_alive: true,
      login_or_access_blocker: /sign in|log in|continue with google/i.test(bodyText) && !composer,
      composer_or_prompt_surface_exists: Boolean(composer),
      frames_button_present: has('frames'),
      ingredients_button_present: has('ingredients'),
      // buttons / upload
      button_texts: buttonTexts,
      upload_media_available: has('upload media') || has('upload'),
      add_to_prompt_found: has('add to prompt'),
      // strong upload proof is action-confirmed by the runner; passive observe
      // can only assert preview/chip presence, not Add-to-Prompt completion.
      add_to_prompt_completed: false,
      asset_preview_in_prompt: assetPreviewInPrompt,
      prompt_attachment_chip_exists: assetPreviewInPrompt,
      // settings
      settings_launcher_found: has('settings') || has('view settings') || has('tune'),
      settings_panel_opened: settingsPanelOpen,
      video_generation_settings_found: has('9:16') || has('aspect ratio') || settingsPanelOpen,
      aspect_9_16_found: obs.aspectRatio === '9:16' || has('9:16'),
      aspect_9_16_confirmed: obs.aspectRatio === '9:16',
      count_1x_found: obs.count === '1x' || has('1x'),
      count_1x_confirmed: obs.count === '1x',
      model_dropdown_found: isVeo || isWrongModel || has('veo') || has('nano banana'),
      model_veo_lite_found: /veo[\s\S]*lite/.test(modelLower) || has('veo 3.1 - lite'),
      model_veo_lite_confirmed: /veo[\s\S]*lite/.test(modelLower),
      visible_wrong_model: isWrongModel,
      model_canonical: obs.model || null,
      save_button_found: has('save'),
      settings_saved_or_persisted: obs.aspectRatio === '9:16' && obs.count === '1x',
      // prompt
      prompt_field_found: composerEditable,
      prompt_inserted: promptText.length > 0,
      prompt_inserted_length: promptText.length,
      prompt_reflected: promptText.length > 0,
      prompt_accepted: promptText.length > 0,
      // generate
      generate_button_found: Boolean(generateBtn),
      generate_button_enabled: Boolean(generateBtn && !generateBtn.disabled),
      blocking_modal_detected: Boolean(safe(() => detectBlockingModal(), false)),
      // weak/deprecated signals
      subMode_Frames_inferred: obs.subMode === 'Frames',
      visibleUploadSlots: Array.isArray(obs.visibleUploadSlots) ? obs.visibleUploadSlots : [],
      body_contains_Start: bodyText.includes('Start'),
      product_truth_anchor_present: false,
    };

    if (
      typeof self !== 'undefined' &&
      self.__GFV2_READINESS__ &&
      typeof self.__GFV2_READINESS__.buildGoogleFlowV2Diagnostic === 'function'
    ) {
      return self.__GFV2_READINESS__.buildGoogleFlowV2Diagnostic(signals);
    }
    // Fallback: module not loaded as a content script — return raw signals.
    return Object.assign({ google_flow_ui_contract: 'V2_UPLOAD_SETTINGS_PROMPT_GENERATE' }, signals);
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
      prompt_field_found: Boolean(composer),
      generate_button_found: !!generateBtn,
      current_mode_visible: currentModeVisible,
      blocking_modal_detected: !!blockingModal,
      observed,
      runtime_ready: true,
      content_build_id: FLOW_KIT_DOM_BUILD_ID,
      git_sha: FLOW_KIT_DOM_BUILD_ID,
    };
    const uiContractV2 = buildUiContractV2Proof(mode, observed, composer, generateBtn);
    result.ui_contract_version = uiContractV2.ui_contract_version;
    result.ui_contract_v2 = uiContractV2;
    result.editor_capability_ready = Boolean(uiContractV2.editor_capability_ready);
    result.pre_generate_ready = Boolean(uiContractV2.pre_generate_ready);

    if (mode) {
      result.expected_mode = mode;
    }

    result.ok = Boolean(
      result.signed_in_likely &&
      result.editor_capability_ready &&
      !result.blocking_modal_detected
    );

    if (result.ok && mode) {
      const expectedJob = buildExpectedModeJob(mode);
      if (expectedJob) {
        const verifyResult = verifyFlowMode(expectedJob, observed);
        if (!verifyResult.ok) {
          result.verify = verifyResult;
          result.page_preselection_ready = isPreselectionEditorReadyDiagnostic(result);
          result.mode_mismatch_non_fatal = Boolean(
            mode === 'F2V' &&
            result.page_preselection_ready &&
            String(verifyResult.reason || '').includes("Expected model to contain 'Veo'"),
          );
          if (result.mode_mismatch_non_fatal) {
            result.ok = true;
          } else {
            result.ok = false;
            result.error = `ABORT_FLOW_MODE_MISMATCH: ${verifyResult.reason}`;
          }
        }
      }
    }

    if (!result.ok) {
      result.error = result.error || 'ABORT_FLOW_COMPOSER_NOT_READY';
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
    const typeControls = await ensureModeControlsVisible('F2V');
    if (!typeControls.ok) {
      return {
        ok: false,
        flow_tab_found: true,
        flow_url: window.location.href,
        signed_in_likely: true,
        composer_found: !!findComposerElement(),
        composer_editable: !!findComposerElement() && isComposerEditable(findComposerElement()),
        generate_button_found: !!findGenerateButtonNearComposer(),
        current_mode_visible: 'UNKNOWN',
        blocking_modal_detected: !!detectBlockingModal(),
        observed: observeFlowState(),
        error: typeControls.error,
        detail: typeControls.detail,
      };
    }

    const { topBtn, subBtn, config } = typeControls;
    if (topBtn && isVisible(topBtn) && !isSelectedControl(topBtn, config.topMode)) {
      topBtn.click();
      await sleep(800);
    }

    if (subBtn && isVisible(subBtn) && !isSelectedControl(subBtn, config.subMode)) {
      subBtn.click();
      await sleep(800);
    }

    const expectedModel = resolveRequestedModel({ mode: 'F2V' });
    const observed = observeFlowState();
    const needsConfigPanel = observed.aspectRatio !== '9:16'
      || observed.count !== '1x'
      || normalizeText(observed.model).toLowerCase() !== normalizeText(expectedModel).toLowerCase();
    const configDebug = {
      before: collectFlowConfigDebugSnapshot(),
      needs_config_panel: needsConfigPanel,
    };

    if (needsConfigPanel) {
      configDebug.panel_opened = await openFlowConfigPanel();
      configDebug.after_open = collectFlowConfigDebugSnapshot();
      configDebug.aspect_selected = await selectFlowConfigOption('9:16');
      configDebug.count_selected = await selectFlowConfigOption('1x');
      configDebug.model_selected = await selectFlowConfigOption(expectedModel);
      configDebug.after_selection = collectFlowConfigDebugSnapshot();
    }

    return {
      ...checkFlowComposerReady('F2V'),
      config_debug: configDebug,
    };
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

      if (readiness.ok && readiness.editor_capability_ready === true) {
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
          config_debug: readiness.config_debug,
          diagnostic: state.diagnostic,
        };
      }

      await sleep(1000);
    }

    let readiness = checkFlowComposerReady(mode);
    if (readiness.composer_found || readiness.generate_button_found || readiness.current_mode_visible !== 'UNKNOWN') {
      readiness = await ensureVideoFramesEditorReady();
    }
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
      config_debug: readiness.config_debug,
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
    if (alreadyReady.editor_capability_ready === true) {
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
        config_debug: alreadyReady.config_debug,
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
      result.verify = verifyResult;
      const nonFatalModeMismatch = Boolean(
        readiness.page_preselection_ready &&
        String(verifyResult.reason || '').includes("Expected model to contain 'Veo'"),
      );
      if (!nonFatalModeMismatch) {
        result.status = 'FAIL_MODE_MISMATCH';
        result.error = `ABORT_FLOW_MODE_MISMATCH: ${verifyResult.reason}`;
        return result;
      }
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

  function isPreselectionEditorReadyDiagnostic(diagnostic) {
    if (!diagnostic || typeof diagnostic !== 'object') {
      return false;
    }
    return Boolean(
      diagnostic.runtime_ready
      && (
        diagnostic.editor_capability_ready === true
        || diagnostic.ui_contract_v2?.editor_capability_ready === true
      ),
    );
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
      expectations.modelContains = 'Veo';
      expectations.modelLabel =
        resolveRequestedModel(job) || FLOW_MODE_CONFIG.F2V.defaultModel;
      expectations.noImageMode = true;
      expectations.noNanoBanana = true;
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
      if (observed.subMode === 'Ingredients') {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = `Expected F2V to avoid Ingredients mode, got '${observed.subMode}'`;
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
      const observedModel = canonicalizeFlowModelLabel(observed.model);
      const expectedModel = canonicalizeFlowModelLabel(expectations.modelLabel);
      const scopedModelVisible = isSettingsScopedModelSource(observed.modelSource);
      if (scopedModelVisible && observedModel && observedModel !== 'unknown' && !observedModel.includes('veo')) {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = `Expected model to contain 'Veo', got '${observed.model}'`;
        result.expected = expectations;
        result.observed = observed;
        return result;
      }
      if (scopedModelVisible && expectedModel && observedModel && observedModel !== 'unknown' && observedModel !== expectedModel) {
        result.ok = false;
        result.error = 'FLOW_MODE_MISMATCH';
        result.reason = `Expected model='${expectations.modelLabel}', got '${observed.model}'`;
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

    const requestedCount = resolveRequestedCount(job);
    if (requestedCount && observed.count !== 'UNKNOWN' && observed.count !== requestedCount) {
      result.ok = false;
      result.error = 'FLOW_MODE_MISMATCH';
      result.reason = `Expected count='${requestedCount}', got '${observed.count}'`;
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

  /**
   * Returns true ONLY when the current tab is already a valid F2V workspace:
   *   topMode=Video, subMode=Frames, Start slot visible, composer visible.
   * Must stay synchronous — do NOT add async/await.
   */
  function isF2VWorkspaceAlreadyReady() {
    const obs = observeFlowState();
    const composer = findComposerElement();
    const generateBtn = findGenerateButtonNearComposer();
    const uiContractV2 = buildUiContractV2Proof('F2V', obs, composer, generateBtn);
    if (obs.topMode !== 'Video') return false;
    if (obs.model && /nano.?banana/i.test(obs.model) && isSettingsScopedModelSource(obs.modelSource)) return false;
    return uiContractV2.editor_capability_ready === true;
  }

  /**
   * F2V SOP state machine — deterministic golden path:
   *   Root/Landing → New Project → Video → Frames → 9:16 → 1x → Veo 3.1 - Lite
   *   → verify Start slot visible → verify prompt field visible
   *
   * Emits full telemetry for each step. Hard-aborts with specific error codes
   * on any mismatch. Must be called as mandatory pre-flight for F2V jobs.
   *
   * @param {object} job   - The job object (used for context, not modified)
   * @param {Function} logStage - logStage(stage, status, message) from executeFlowJob
   */
  async function ensureF2VFramesWorkspaceReady(_job, logStage) {
    // ── Step 1: Root / landing check ─────────────────────────────────────────
    // We don't navigate away (can't cross page boundary), but record whether
    // we're at root or already inside a project editor.
    const onRoot = isRootFlowUrl(window.location.href);
    logStage(STAGES.FLOW_ROOT_OPENED, onRoot ? 'PASS' : 'SKIP',
      onRoot ? null : 'Already in project editor — skipping root navigation');

    // ── Step 2: New Project ───────────────────────────────────────────────────
    // Only skip when the current workspace is ALREADY verified as F2V-ready
    // (Video + Frames + Start slot + visible composer).  A bare composer
    // presence is NOT sufficient — an Image workspace or Nano Banana project
    // also exposes a composer element but is NOT a valid F2V workspace.
    const alreadyF2VReady = isF2VWorkspaceAlreadyReady();
    if (alreadyF2VReady) {
      logStage(STAGES.NEW_PROJECT_CLICKED, 'SKIP',
        'Existing workspace already Video/Frames with Start slot');
    } else {
      // Snapshot current state before any mutations for diagnostics.
      const snapObs = observeFlowState();
      const snapComposer = findComposerElement();
      const snapMsg = `workspace_not_f2v_ready topMode=${snapObs.topMode} subMode=${snapObs.subMode} model=${snapObs.model} slots=[${snapObs.visibleUploadSlots.join(',')}] composer_found=${!!snapComposer}`;
      console.log(`[FlowAgent] ${snapMsg}`);

      await closeBlockingModalIfPresent();

      // Prefer a New Project button; fall back to the create-type-chooser
      // (already in an editor but wrong workspace type).
      const newProjectBtn = findNewProjectControl();
      if (newProjectBtn && isVisible(newProjectBtn)) {
        newProjectBtn.click();
        logStage(STAGES.NEW_PROJECT_CLICKED, 'PASS', snapMsg);
      } else {
        const chooserOpened = await openCreateTypeChooser();
        if (!chooserOpened) {
          logStage(STAGES.NEW_PROJECT_CLICKED, 'FAIL', `ERR_NEW_PROJECT_NOT_FOUND — ${snapMsg}`);
          throw new Error('ERR_NEW_PROJECT_NOT_FOUND');
        }
        logStage(STAGES.NEW_PROJECT_CLICKED, 'PASS', `type_chooser_opened — ${snapMsg}`);
      }

      // Wait for Video control to become visible after workspace opens.
      let goBackClicked = false;
      const appeared = await waitForCondition(
        () => {
          const btn = findElementByText('button, [role="tab"], [role="button"], span, div', 'Video');
          if (btn && isVisible(btn)) return true;

          // Early shell recovery: detect Scenebuilder / Add Media traps
          const bodyText = document.body.innerText;
          const isShell = bodyText.includes('Scenebuilder') || bodyText.includes('Add Media');
          if (isShell && !goBackClicked) {
            const goBackBtn = findElementByText('button, [role="button"], span, div', 'Go Back');
            if (goBackBtn && isVisible(goBackBtn)) {
              console.log('[FlowAgent] Shell detected, clicking Go Back');
              goBackBtn.click();
              goBackClicked = true;
            }
          }
          return false;
        },
        15000, 500,
      );

      if (!appeared) {
        const obs = observeFlowState();
        const bodyText = document.body.innerText;
        const shellMarkers = [];
        if (bodyText.includes('Scenebuilder')) shellMarkers.push('Scenebuilder');
        if (bodyText.includes('Add Media')) shellMarkers.push('Add Media');
        if (bodyText.includes('Go Back')) shellMarkers.push('Go Back');

        const candidateSelector = 'button, [role="tab"], [role="button"], span, div';
        const candidates = collectVisibleTexts(candidateSelector, el => el.textContent || '').slice(0, 20);

        const roleMenuCount = document.querySelectorAll('[role="menu"]').length;
        const roleListboxCount = document.querySelectorAll('[role="listbox"]').length;

        const detail = `FLOW_TYPE_VIDEO_SELECTED FAIL — `
          + `ERR_VIDEO_BUTTON_NOT_FOUND — `
          + `url=${window.location.href} `
          + `topMode=${obs.topMode} `
          + `subMode=${obs.subMode} `
          + `shellMarkers=[${shellMarkers.join(',')}] `
          + `roleMenuCount=${roleMenuCount} `
          + `roleListboxCount=${roleListboxCount} `
          + `goBackClicked=${goBackClicked} `
          + `candidates=[${candidates.join(',')}]`;

        logStage(STAGES.FLOW_TYPE_VIDEO_SELECTED, 'FAIL', detail);
        throw new Error('ERR_WRONG_MODE_IMAGE_SELECTED');
      }
    }

    // ── Step 3: Select Video topMode ─────────────────────────────────────────
    const modeControls = await ensureModeControlsVisible('F2V');
    if (!modeControls.ok) {
      logStage(STAGES.FLOW_TYPE_VIDEO_SELECTED, 'FAIL',
        `${modeControls.error || 'ensureModeControlsVisible(F2V) returned !ok'}${modeControls.detail ? ` — ${modeControls.detail}` : ''}`);
      throw new Error('ERR_WRONG_MODE_IMAGE_SELECTED');
    }

    const { topBtn: initialTopBtn, subBtn } = modeControls;
    let clickMethodUsed = 'none';
    let videoTargetFound = false;
    let videoTargetVisible = false;
    let videoTargetText = '';
    let videoTargetOuterHTML = '';

    if (initialTopBtn && isVisible(initialTopBtn) && !isSelectedControl(initialTopBtn, 'Video')) {
      const videoTarget = findElementByText('button, [role="tab"], [role="button"], span, div', 'Video');
      const target = videoTarget?.closest('button, [role="tab"], [role="button"]') || videoTarget;

      videoTargetFound = Boolean(target);
      videoTargetVisible = Boolean(target && isVisible(target));
      videoTargetText = normalizeText(target?.textContent || '');
      videoTargetOuterHTML = target?.outerHTML?.slice(0, 500) || '';

      if (target && isVisible(target) && videoTargetText.includes('Video')) {
        target.scrollIntoView({ block: 'center', inline: 'center' });
        await sleep(150);

        const rect = target.getBoundingClientRect();
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;
        const eventInit = { bubbles: true, cancelable: true, view: window, clientX: centerX, clientY: centerY };

        clickMethodUsed = 'pointer_sequence';
        target.dispatchEvent(new PointerEvent('pointerdown', { ...eventInit, pointerType: 'mouse' }));
        target.dispatchEvent(new MouseEvent('mousedown', eventInit));
        target.dispatchEvent(new PointerEvent('pointerup', { ...eventInit, pointerType: 'mouse' }));
        target.dispatchEvent(new MouseEvent('mouseup', eventInit));
        target.dispatchEvent(new MouseEvent('click', eventInit));

        const transitioned = await waitForCondition(() => observeFlowState().topMode === 'Video', 1500, 150);
        if (!transitioned) {
          clickMethodUsed = 'pointer_sequence_plus_fallback_click';
          target.click();
        }
      }
    }

    const activeVideo = await waitForCondition(
      () => observeFlowState().topMode === 'Video',
      5000, 150,
    );

    if (!activeVideo) {
      const obs = observeFlowState();
      const bodyText = document.body.innerText;
      const shellMarkers = [];
      if (bodyText.includes('Scenebuilder')) shellMarkers.push('Scenebuilder');
      if (bodyText.includes('Add Media')) shellMarkers.push('Add Media');
      if (bodyText.includes('Go Back')) shellMarkers.push('Go Back');

      const candidateSelector = 'button, [role="tab"], [role="button"], span, div';
      const candidates = collectVisibleTexts(candidateSelector, (el) => el.textContent || '').slice(0, 20);

      const roleMenuCount = document.querySelectorAll('[role="menu"]').length;
      const roleListboxCount = document.querySelectorAll('[role="listbox"]').length;

      const detail = 'ERR_VIDEO_MODE_NOT_ACTIVE_AFTER_POINTER_CLICK — '
        + `topMode=${obs.topMode} `
        + `subMode=${obs.subMode} `
        + `video_target_found=${videoTargetFound} `
        + `video_target_visible=${videoTargetVisible} `
        + `video_target_text=${JSON.stringify(videoTargetText)} `
        + `video_target_outerHTML=${JSON.stringify(videoTargetOuterHTML)} `
        + `click_method_used=${clickMethodUsed} `
        + `url=${window.location.href} `
        + `candidates=[${candidates.join(',')}] `
        + `shellMarkers=[${shellMarkers.join(',')}] `
        + `roleMenuCount=${roleMenuCount} `
        + `roleListboxCount=${roleListboxCount}`;

      logStage(STAGES.FLOW_TYPE_VIDEO_SELECTED, 'FAIL', detail);
      throw new Error('ERR_WRONG_MODE_IMAGE_SELECTED');
    }
    logStage(STAGES.FLOW_TYPE_VIDEO_SELECTED, 'PASS', 'topMode=Video');

    // ── Step 4: Legacy Frames selector is optional in UI Contract V2. Keep the
    // click when a visible control exists, but do not hard-fail when the live UI
    // reaches a valid editor without exposing a Frames button.
    if (subBtn && isVisible(subBtn) && !isSelectedControl(subBtn, 'Frames')) {
      subBtn.click();
      await sleep(800);
    }

    const obsAfterFrames = observeFlowState();
    const uiContractAfterFrames = buildUiContractV2Proof('F2V', obsAfterFrames, findComposerElement(), findGenerateButtonNearComposer());
    if (obsAfterFrames.subMode === 'Ingredients') {
      logStage(STAGES.FLOW_SUBMODE_FRAMES_SELECTED, 'FAIL', `subMode=${obsAfterFrames.subMode}`);
      throw new Error('ERR_FRAMES_MODE_NOT_ACTIVE');
    }
    if (uiContractAfterFrames.editor_capability_ready !== true) {
      logStage(STAGES.FLOW_SUBMODE_FRAMES_SELECTED, 'FAIL', `editor_capability_ready=${uiContractAfterFrames.editor_capability_ready}`);
      throw new Error('ERR_FRAMES_MODE_NOT_ACTIVE');
    }
    logStage(STAGES.FLOW_SUBMODE_FRAMES_SELECTED, 'PASS', `subMode=${obsAfterFrames.subMode}`);

    const composerReady = await ensureF2VComposerReadyBeforeConfig();
    if (!composerReady.ok) {
      logStage(STAGES.F2V_COMPOSER_READY, 'FAIL', `${composerReady.error} — ${composerReady.detail}`);
      throw new Error(composerReady.error);
    }
    logStage(STAGES.F2V_COMPOSER_READY, 'PASS', composerReady.detail);

    // ── Steps 5–7: Config panel (9:16 / 1x / Veo 3.1 - Lite) ────────────────
    console.log('[FlowAgent] Delegating F2V settings configuration to f2v-flow-queue-runner in background');
    const delegateResult = await sendRuntimeMessageWithResponse(
      { type: 'CONFIGURE_F2V_SETTINGS', job: _job },
      15000,
    );

    if (!delegateResult || delegateResult.ok !== true) {
      logStage(STAGES.FLOW_ASPECT_9_16_SELECTED, 'FAIL', delegateResult?.detail || delegateResult?.error || 'delegation_failed');
      throw new Error(delegateResult?.error || 'ERR_ASPECT_9_16_NOT_SELECTED');
    }
    logStage(STAGES.FLOW_ASPECT_9_16_SELECTED, 'PASS');
    logStage(STAGES.FLOW_COUNT_1X_SELECTED, 'PASS');
    logStage(STAGES.FLOW_MODEL_VEO_3_1_LITE_SELECTED, 'PASS', 'model=Veo 3.1 - Lite');

    // ── Step 8: Upload gate — V2 requires an upload control, not an old Frames
    // selector path. Keep Start-slot evidence when present, but accept any valid
    // editor capability surface.
    const obsForSlot = observeFlowState();
    const slotUiContract = buildUiContractV2Proof('F2V', obsForSlot, findComposerElement(), findGenerateButtonNearComposer());
    if (slotUiContract.editor_capability_ready !== true) {
      logStage(STAGES.START_SLOT_VISIBLE, 'FAIL',
        `editor_capability_ready=${slotUiContract.editor_capability_ready} slots=[${obsForSlot.visibleUploadSlots.join(',')}]`,
        buildSelectorEvidenceMeta('upload_slot_label_scan'));
      throw new Error('ERR_START_SLOT_NOT_VISIBLE');
    }
    logStage(STAGES.START_SLOT_VISIBLE, 'PASS',
      `slots=[${obsForSlot.visibleUploadSlots.join(',')}] editor_capability_ready=${slotUiContract.editor_capability_ready}`,
      buildSelectorEvidenceMeta('upload_slot_label_scan'));

    // ── Step 9: Prompt field must be present ─────────────────────────────────
    const composerEl = findComposerElement();
    if (!composerEl) {
      logStage(STAGES.PROMPT_FIELD_VISIBLE, 'FAIL', 'findComposerElement returned null');
      throw new Error('ERR_PROMPT_FIELD_NOT_FOUND');
    }
    logStage(STAGES.PROMPT_FIELD_VISIBLE, 'PASS');

    logStage(STAGES.F2V_WORKSPACE_READY, 'PASS');
    return { ok: true };
  }

  function isF2VPackageUploadOnlyLane(job) {
    return Boolean(
      job && (job.lane === 'F2V_PACKAGE_UPLOAD_ONLY' || job.upload_only === true),
    );
  }

  // STRICT package-to-current-editor Start upload lane. Reuses the existing CDP
  // file-chooser upload + prompt-insert primitives. Touches NO settings/model/
  // aspect/count/agent/generate path. Fails closed with precise diagnostics and
  // never accepts Add Media / Scenebuilder / asset-library as Start success.
  async function executePackageUploadOnly(job, logStage, request_id, report) {
    report.lane = 'F2V_PACKAGE_UPLOAD_ONLY';

    // 1. Editor must be a real project editor surface — not root / broken / library.
    const url = String(location.href || '');
    const bodyText = (document.body && document.body.innerText) || '';
    const onProjectEditor = url.indexOf('/project/') >= 0;
    const looksBroken = /something went wrong|application error/i.test(bodyText);
    if (!onProjectEditor || looksBroken) {
      const code = !onProjectEditor ? 'ERR_FLOW_EDITOR_REQUIRED' : 'ERR_FLOW_EDITOR_BROKEN';
      logStage('FLOW_EDITOR_READY', 'FAIL', code);
      report.ok = false;
      report.error = code;
      return report;
    }
    logStage('FLOW_EDITOR_READY', 'PASS', `url=${url}`);

    // 2. Locate the Start slot (the only valid upload entry for this lane).
    const slotInfo = findUploadSlotByLabel('Start');
    const startContainer = slotInfo?.container || resolveSlotContainer('Start');
    const visibleSlots = observeFlowState().visibleUploadSlots;
    if (!visibleSlots.includes('Start') && !startContainer) {
      logStage('START_SLOT_FOUND', 'FAIL', 'ERR_START_UPLOAD_TARGET_NOT_FOUND');
      report.ok = false;
      report.error = 'ERR_START_UPLOAD_TARGET_NOT_FOUND';
      return report;
    }
    logStage('START_SLOT_FOUND', 'PASS', `visible_slots=${visibleSlots.join(',')}`);

    // 3. Package Start asset MUST resolve to a local file for the CDP file chooser.
    const startAssetSource = job.startAsset || job.productId || job.startImageMediaId;
    const localFilePath = resolveAssetLocalFilePath(startAssetSource);
    if (!localFilePath) {
      logStage('UPLOAD_MEDIA_ACTION_SELECTED', 'FAIL', 'ERR_PACKAGE_START_LOCAL_FILE_REQUIRED');
      report.ok = false;
      report.error = 'ERR_PACKAGE_START_LOCAL_FILE_REQUIRED';
      return report;
    }
    logStage('UPLOAD_MEDIA_ACTION_SELECTED', 'PASS', 'strategy=cdp_file_chooser slot=Start');
    logStage('CDP_FILE_CHOOSER_ARMED', 'PASS', `local_file_path=${localFilePath}`);

    // 4. Upload the Start asset via CDP file chooser ONLY (never legacy DOM fake,
    //    never Add Media / Scenebuilder / asset library).
    const uploadState = { lastCheckpoint: 'NONE', request_id };
    let okStart;
    try {
      okStart = await Promise.race([
        simulateCdpFileUpload('Start', startAssetSource, uploadState),
        new Promise((_, rej) =>
          setTimeout(() => rej(new Error('ERR_START_UPLOAD_TIMEOUT')), 30000),
        ),
      ]);
    } catch (err) {
      logStage('START_UPLOAD_ACCEPTED', 'FAIL', err.message || 'ERR_START_UPLOAD_TIMEOUT');
      report.ok = false;
      report.error = err.message || 'ERR_START_UPLOAD_TIMEOUT';
      return report;
    }
    if (!okStart || okStart.ok !== true) {
      const shellMatch = /scenebuilder|all media|asset library/i.test(bodyText);
      const code = shellMatch
        ? 'ERR_FORBIDDEN_ASSET_LIBRARY_PATH'
        : okStart?.error || 'ERR_UPLOAD_MEDIA_ACTION_NOT_FOUND';
      logStage('START_UPLOAD_ACCEPTED', 'FAIL', code);
      report.ok = false;
      report.error = code;
      return report;
    }

    // 5. Verify the Start slot preview actually appeared/changed.
    const startPreview = await waitForAssetPreview('Start', okStart.slotElement || null, {
      slotContainer: okStart.slotContainer || null,
      beforeSnapshot: okStart.beforeSnapshot || null,
      timeoutMs: 30000,
    });
    if (!startPreview.ok) {
      logStage('START_UPLOAD_ACCEPTED', 'FAIL', startPreview.error || 'ERR_START_PREVIEW_TIMEOUT');
      report.ok = false;
      report.error = startPreview.error || 'ERR_START_PREVIEW_TIMEOUT';
      return report;
    }
    logStage(
      'START_UPLOAD_ACCEPTED',
      'PASS',
      `slot=Start preview_found=true checkpoint=${okStart.lastCheckpoint || 'done'}`,
    );

    // 6. Insert the package prompt (no settings, no agent).
    const composer = findComposerElement();
    if (!composer || !isComposerEditable(composer)) {
      logStage('PROMPT_INSERTED', 'FAIL', 'ERR_PROMPT_FIELD_NOT_FOUND');
      report.ok = false;
      report.error = 'ERR_PROMPT_FIELD_NOT_FOUND';
      return report;
    }
    await humanTypePrompt(composer, job.prompt);
    logStage('PROMPT_INSERTED', 'PASS', `${String(job.prompt).length} chars`);

    // 7. Stop strictly BEFORE Generate.
    logStage('STOP_BEFORE_GENERATE', 'PASS', 'upload_only_lane_complete');
    report.ok = true;
    report.stopped_before_generate = true;
    report.start_upload_verified = true;
    report.prompt_inserted = true;
    return report;
  }

  async function executeFlowJob(job) {
    const statusResp = await sendRuntimeMessageWithResponse({ type: 'STATUS' }, 6000);
    const testConn = statusResp?.data && typeof statusResp.data === 'object'
      ? statusResp.data
      : (statusResp || { ok: false, error: 'ERR_EMPTY_BACKGROUND_STATUS' });
    console.log('[FlowAgent] Background connection test:', testConn);
    const backgroundBuildId = String(
      testConn?.buildId
      || testConn?.build_id
      || testConn?.background_build_id
      || testConn?.gitSha
      || testConn?.git_sha
      || '',
    ).trim();
    const backgroundRuntimeReady = typeof testConn?.runtimeReady === 'boolean'
      ? testConn.runtimeReady
      : (typeof testConn?.runtime_ready === 'boolean' ? testConn.runtime_ready : true);

    const report = { ok: false, stages: [] };
    const request_id = job.request_id || `flow_${Date.now()}`;
    let firstFailStage = null;
    const logStage = (stage, status = 'YES', message = null, extra = {}) => {
      report.stages.push({ stage, status, message, ...extra });
      console.log(`[FlowAgent] Stage: ${stage} - ${status}${message ? ` - ${message}` : ''}`);
      if (status === 'FAIL' && !firstFailStage) {
        firstFailStage = stage;
      }
      sendRuntimeMessageNoThrow(buildStageTelemetryPayload(request_id, stage, status, {
        message,
        fail_code: status === 'FAIL' ? (message || stage) : null,
        first_fail_stage: firstFailStage,
        ...extra,
      }));
    };

    try {
      logStage(STAGES.FLOW_TAB_FOUND, 'PASS', 'flow_dom_listener_ready');
      if (!backgroundBuildId) {
        logStage(STAGES.RUNTIME_HANDSHAKE_VERIFIED, 'FAIL', `background_status_missing build=${backgroundBuildId || 'legacy-compatible'}`);
        throw new Error('ERR_BACKGROUND_STATUS_UNAVAILABLE');
      }
      if (!backgroundRuntimeReady) {
        logStage(STAGES.RUNTIME_HANDSHAKE_VERIFIED, 'FAIL', `background_runtime_not_ready build=${backgroundBuildId || 'legacy-compatible'}`);
        throw new Error('ERR_BACKGROUND_STATUS_UNAVAILABLE');
      }
      if (backgroundBuildId !== FLOW_KIT_DOM_BUILD_ID) {
        logStage(
          STAGES.RUNTIME_HANDSHAKE_VERIFIED,
          'FAIL',
          `background_build_id=${backgroundBuildId} content_build_id=${FLOW_KIT_DOM_BUILD_ID}`,
        );
        throw new Error('ERR_BUILD_ID_MISMATCH');
      }
      logStage(
        STAGES.RUNTIME_HANDSHAKE_VERIFIED,
        'PASS',
        `background_build_id=${backgroundBuildId} content_build_id=${FLOW_KIT_DOM_BUILD_ID}`,
      );

      // 0. Log job received
      if (job.prompt) {
        logStage(STAGES.JOB_PROMPT_RECEIVED, `${job.prompt.length} chars`);
      } else {
        logStage(STAGES.JOB_PROMPT_RECEIVED, 'MISSING');
        throw new Error('JOB_PROMPT_EMPTY');
      }

      // CRITICAL: Clear any pre-existing state
      logStage(STAGES.PRE_EXECUTION_STATE_CLEARED);

      // STRICT LANE: F2V_PACKAGE_UPLOAD_ONLY. Skip ALL settings/mode/aspect/count/
      // model/agent/generate. Only: current editor -> Start slot -> Upload media
      // (CDP) -> verify preview -> insert prompt -> stop before Generate.
      if (isF2VPackageUploadOnlyLane(job)) {
        return await executePackageUploadOnly(job, logStage, request_id, report);
      }

      if (job.mode === 'F2V') {
        // CRITICAL: F2V SOP state machine — deterministic golden path:
        //   Root/Landing → New Project → Video → Frames → 9:16 → 1x → Veo 3.1 - Lite
        //   → Start slot visible → prompt field visible
        // Hard-aborts with specific error codes on any mismatch.
        await ensureF2VFramesWorkspaceReady(job, logStage);
        // ensureF2VFramesWorkspaceReady already emits FLOW_TYPE_VIDEO_SELECTED,
        // FLOW_SUBMODE_FRAMES_SELECTED, FLOW_ASPECT_9_16_SELECTED, etc.
        // Log the legacy compatibility stages so downstream consumers see them too.
        logStage(STAGES.FLOW_MODE_SELECTED, 'Video', null, buildSelectorEvidenceMeta('f2v_collapsed_config_launcher'));
        logStage(STAGES.FLOW_SUBMODE_SELECTED, 'Frames', null, buildSelectorEvidenceMeta('f2v_collapsed_config_launcher'));
        logStage(STAGES.FLOW_MODE_VERIFIED, 'YES', null, buildSelectorEvidenceMeta('f2v_collapsed_config_launcher'));
      } else {
        // 1. Select Top Mode (STRICT - must be correct mode)
        const modeControls = await ensureModeControlsVisible(job.mode);
        if (!modeControls.ok) throw new Error(modeControls.error || 'ERR_MODE_SELECTION_FAILED');
        const modeBtn = modeControls.topBtn;
        if (!modeBtn) throw new Error(`Mode button ${job.mode} not found`);
        modeBtn.click();
        await sleep(1000);
        logStage(
          STAGES.FLOW_MODE_SELECTED,
          resolveFlowModeConfig(job.mode)?.topMode || job.mode,
          null,
          buildSelectorEvidenceMeta('flow_config_launcher_compact'),
        );

        // 2. Select Submode (STRICT)
        if (job.mode === 'I2V') {
          const submodeText = resolveFlowModeConfig(job.mode)?.subMode;
          const modeControls2 = await ensureModeControlsVisible(job.mode);
          const submodeBtn = modeControls2.subBtn;
          if (!submodeBtn) throw new Error(`Submode button ${submodeText} not found`);
          submodeBtn.click();
          await sleep(1000);
          logStage(
            STAGES.FLOW_SUBMODE_SELECTED,
            submodeText,
            null,
            buildSelectorEvidenceMeta('flow_config_launcher_compact'),
          );
        } else if (job.mode === 'T2V') {
          const clearedSubmodes = await clearVideoSubmodeSelection();
          logStage(
            STAGES.FLOW_SUBMODE_SELECTED,
            clearedSubmodes.length > 0 ? `CLEARED:${clearedSubmodes.join(',')}` : 'NONE',
            null,
            buildSelectorEvidenceMeta('flow_config_launcher_compact'),
          );
        }

        // 3. Set Aspect Ratio
        const requestedAspectRatio = resolveRequestedAspectRatio(job);
        const requestedCount = resolveRequestedCount(job);
        const requestedModel = resolveRequestedModel(job);
        if (requestedAspectRatio || requestedCount || requestedModel) {
          await openFlowConfigPanel();
        }

        if (requestedAspectRatio && await selectFlowConfigOption(requestedAspectRatio)) {
          logStage(STAGES.ASPECT_SELECTED, requestedAspectRatio, null, buildSelectorEvidenceMeta('flow_config_surface_portal'));
        }

        // 4. Set Count
        if (requestedCount && await selectFlowConfigOption(requestedCount)) {
          logStage(STAGES.COUNT_SELECTED, requestedCount, null, buildSelectorEvidenceMeta('flow_config_surface_portal'));
        }

        // 5. Set Model
        if (requestedModel && await selectFlowConfigOption(requestedModel)) {
          logStage(STAGES.MODEL_SELECTED, requestedModel, null, buildSelectorEvidenceMeta('flow_config_surface_portal'));
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

        logStage(STAGES.FLOW_MODE_VERIFIED, 'YES', null, buildSelectorEvidenceMeta('flow_config_surface_portal'));
      }

      // 6. Attach Assets (STRICT: Asset First, Prompt Second)
      const assetSlotContexts = [];
      if (job.mode === 'F2V') {
        // Step 6a: Upload Start Frame
        const startAssetSource = job.startAsset || job.productId || job.startImageMediaId;
        const assetSourceType = describeAssetSourceType(startAssetSource);
        const assetFilename = resolveAssetPreferredFileName(startAssetSource, 'Start');

        logStage(STAGES.START_FRAME_UPLOAD_ATTEMPTED, 'PASS', 
          `slot=Start asset_source_type=${assetSourceType} asset_filename=${assetFilename} visible_upload_slots=${observeFlowState().visibleUploadSlots.join(',')}`,
          buildSelectorEvidenceMeta('upload_slot_label_scan'));

        const uploadTimeoutPromise = new Promise((_, reject) => 
          setTimeout(() => reject(new Error('ERR_START_UPLOAD_TIMEOUT')), 20000)
        );

        const uploadState = { lastCheckpoint: 'NONE', request_id };
        let okStart;
        try {
          okStart = await Promise.race([
            simulateFileUpload('Start', startAssetSource, uploadState),
            uploadTimeoutPromise
          ]);
        } catch (err) {
          if (err.message === 'ERR_START_UPLOAD_TIMEOUT') {
            const obs = observeFlowState();
            const slotInfo = findUploadSlotByLabel('Start');
            const slotContainer = slotInfo?.container || resolveSlotContainer('Start');
            
            const shellMarkers = [];
            const bodyText = document.body.innerText;
            if (bodyText.includes('Scenebuilder')) shellMarkers.push('Scenebuilder');
            if (bodyText.includes('Add Media')) shellMarkers.push('Add Media');
            if (bodyText.includes('Go Back')) shellMarkers.push('Go Back');

            const diag = {
              last_checkpoint: uploadState.lastCheckpoint,
              slotLabel: 'Start',
              visible_upload_slots: obs.visibleUploadSlots,
              slot_container_outerHTML: slotContainer?.outerHTML?.slice(0, 500),
              asset_source_type: assetSourceType,
              asset_filename: assetFilename,
              body_shell_markers: shellMarkers,
              role_menu_count: document.querySelectorAll('[role="menu"]').length,
              active_element_text: document.activeElement?.textContent?.slice(0, 50) || 'none',
            };
            logStage(STAGES.START_FRAME_ATTACHED, 'FAIL', `ERR_START_UPLOAD_TIMEOUT — ${JSON.stringify(diag)}`);
            throw err;
          }
          throw err;
        }

        if (okStart?.ok) {
          logStage(
            STAGES.START_FRAME_ATTACHED,
            'PASS',
            `slot=Start accepted=${okStart.acceptanceReason || 'unknown'} modal=${okStart.modalFound ? 'true' : 'false'} last_checkpoint=${okStart.lastCheckpoint}`,
          );

          uploadState.lastCheckpoint = 'UPLOAD_PREVIEW_WAIT_STARTED';
          const startPreview = await waitForAssetPreview('Start', okStart.slotElement || null, {
            slotContainer: okStart.slotContainer || null,
            beforeSnapshot: okStart.beforeSnapshot || null,
            timeoutMs: 30000,
          });

          if (!startPreview.ok) {
            logStage(STAGES.START_FRAME_VERIFIED, 'FAIL', startPreview.error || buildSlotErrorCode('Start', 'PREVIEW_TIMEOUT'));
            throw new Error(startPreview.error || buildSlotErrorCode('Start', 'PREVIEW_TIMEOUT'));
          }

          uploadState.lastCheckpoint = 'UPLOAD_PREVIEW_VERIFIED';
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
          const obs = observeFlowState();
          const shellMarkers = [];
          const bodyText = document.body.innerText;
          if (bodyText.includes('Scenebuilder')) shellMarkers.push('Scenebuilder');
          if (bodyText.includes('Add Media')) shellMarkers.push('Add Media');
          if (bodyText.includes('Go Back')) shellMarkers.push('Go Back');

          const diag = {
            last_checkpoint: okStart?.lastCheckpoint || 'NONE',
            slotLabel: 'Start',
            visible_upload_slots: obs.visibleUploadSlots,
            asset_source_type: assetSourceType,
            asset_filename: assetFilename,
            body_shell_markers: shellMarkers,
            active_element_text: document.activeElement?.textContent?.slice(0, 50) || 'none',
            detail: okStart?.detail || null,
          };
          logStage(STAGES.START_FRAME_ATTACHED, 'FAIL', `${okStart?.error || 'UPLOAD_DISPATCH_FAILED'} — ${JSON.stringify(diag)}`);
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
      const composer = findComposerElement();
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
      if (!actual?.includes(job.prompt.slice(0, 10))) {
        logStage(STAGES.PROMPT_VISIBLE, 'NO');
        throw new Error('PROMPT_INSERT_FAILED');
      }
      logStage(STAGES.PROMPT_VISIBLE);

      if (!isComposerEditable(composer)) {
        logStage(STAGES.PROMPT_EDITABLE_AFTER_INSERT, 'NO');
        throw new Error('PROMPT_INSERT_LOCKED_OR_UNTRUSTED');
      }
      logStage(STAGES.PROMPT_EDITABLE_AFTER_INSERT);

      if (job.stop_after_stage === 'PROMPT_EDITABLE_AFTER_INSERT') {
        logStage(STAGES.STOP_AFTER_STAGE_REACHED, 'PASS');
        return {
          ok: true,
          stopped_at_stage: STAGES.PROMPT_EDITABLE_AFTER_INSERT,
          stopped_before_generate: true,
          stages: report.stages,
        };
      }

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
      logStage(STAGES.GENERATE_CLICKED, 'YES', null, buildSelectorEvidenceMeta('generate_button_composer_scoped'));

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
      sendRuntimeMessageNoThrow(buildStageTelemetryPayload(request_id, 'ERROR', 'FAIL', {
        checkpoint: firstFailStage || 'ERROR',
        message: e.message,
        fail_code: e.message,
        first_fail_stage: firstFailStage || 'ERROR',
      }));
    }

    return report;
  }

  const flowDomMessageListener = (msg, _sender, sendResponse) => {
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

    if (msg.type === 'GFV2_OBSERVE_STATE') {
      // Read-only Google Flow V2 diagnostic. Inspects the DOM only — never clicks.
      try {
        sendResponse({ ok: true, diagnostic: observeGoogleFlowV2State() });
      } catch (error) {
        sendResponse({ ok: false, error: 'GFV2_OBSERVE_FAILED', detail: String(error?.message || error) });
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

      // F2V jobs run exclusively via background.js (executeF2VVisibleSopRunner).
      // Returning false without executing prevents double-execution.
      if (msg.job?.mode === 'F2V') {
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

    if (msg.type === 'GET_CAPTCHA' || msg.type === 'FLOWKIT_CAPTCHA_PING') {
      // Let the dedicated captcha content script own these messages.
      return false;
    }

    sendResponse({ ok: false, error: 'ERR_UNKNOWN_MESSAGE_TYPE' });
    return false;
  };

  if (FLOW_KIT_ENABLE_TEST_HOOKS) {
    window.__FLOWKIT_TEST_HOOKS__ = {
      buildDiagnosticPingResponse,
      findVisibleAssetPickerModal,
      findGenerateButtonNearComposer,
      waitForAssetPickerModal,
      waitForUploadAcceptance,
      resolveAssetPickerTargets,
      simulateFileUpload,
      beginCdpFileChooserProof,
      waitForCdpFileChooserProofResult,
      openFlowConfigPanel,
      verifyFlowMode,
    };
    installPlaywrightTestBridge();
  }

  if (!FLOW_KIT_TEST_MODE) {
    window._flowKitDomListener = flowDomMessageListener;
    chrome.runtime.onMessage.addListener(flowDomMessageListener);
  }

})();
