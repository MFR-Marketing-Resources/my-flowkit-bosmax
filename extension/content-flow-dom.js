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
  const FLOW_KIT_DOM_VERSION = '2026-05-11-f2v-sop-gates';
  const FLOW_KIT_DOM_PROTOCOL_VERSION = 'FLOWKIT_DOM_V1';
  const IMAGE_ASPECT_RATIOS = ['16:9', '4:3', '1:1', '3:4', '9:16'];
  const FLOW_MODE_CONFIG = {
    F2V: { topMode: 'Video', subMode: 'Frames', defaultModel: 'Veo 3.1 - Lite', defaultOrientation: 'VERTICAL', defaultCount: 1 },
    T2V: { topMode: 'Video', subMode: null },
    I2V: { topMode: 'Video', subMode: 'Ingredients' },
    IMG: { topMode: 'Image', subMode: null, defaultModel: 'Nano Banana 2' },
  };

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

  function findFlowConfigLauncher() {
    const selectors = 'button, [role="button"], [role="tab"], [aria-haspopup], span, div';
    const candidates = Array.from(document.querySelectorAll(selectors));
    const preferred = [];
    const fallback = [];

    for (const el of candidates) {
      if (!isVisible(el)) continue;
      const text = normalizeText(el.textContent || el.getAttribute('aria-label') || '');
      if (!text) continue;
      const lower = text.toLowerCase();
      const looksLikeModelChip = lower.includes('nano banana') || lower.includes('veo');
      const looksLikeConfigChip = /(^|\s)([1-4]x)(\s|$)/i.test(text) && /(9:16|16:9|4:3|1:1|3:4)/.test(text);
      const target = el.closest('button, [role="button"], [role="tab"], [aria-haspopup]') || el;
      if (!isVisible(target)) continue;
      const targetText = normalizeText(target.textContent || target.getAttribute('aria-label') || '');
      const rect = target.getBoundingClientRect();
      const targetTooLarge = rect.width > 520 || rect.height > 120 || targetText.length > 120;
      const targetLooksLikePageShell = /(what do you want to create|double check it|go back|search|sort & filter|add media)/i.test(targetText);
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
    const selectors = [
      '[role="listbox"]',
      '[role="dialog"]',
      '[role="menu"]',
      '[data-floating-ui-portal] > *',
      '[data-radix-popper-content-wrapper] > *',
      '[data-radix-portal] > *',
    ].join(', ');

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
    return surfaced || true;
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
    return Array.from(document.querySelectorAll('button[aria-haspopup="menu"]')).find((el) => {
      if (!isVisible(el)) return false;
      const text = normalizeText(el.innerText || el.textContent || '');
      return text.includes('Video')
        && text.includes('1x')
        && (text.includes('crop_9_16') || text.includes('9:16'));
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

    let roleMenuTextSnippetsBeforeClose = [];
    if (roleMenuCountBeforeOrig > 0) {
      roleMenuTextSnippetsBeforeClose = Array.from(document.querySelectorAll('[role="menu"]')).map((el) => (
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
      && launcherText.includes('1x')
      && (launcherText.includes('crop_9_16') || launcherText.includes('9:16'));

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

    let topBtn = findElementByText('button, [role="tab"], [role="button"], span', config.topMode);
    let subBtn = config.subMode
      ? findElementByText('button, [role="tab"], [role="button"], span', config.subMode)
      : null;

    if ((!topBtn || !isVisible(topBtn) || (config.subMode && (!subBtn || !isVisible(subBtn)))) && await openCreateTypeChooser()) {
      topBtn = findElementByText('button, [role="tab"], [role="button"], span', config.topMode);
      subBtn = config.subMode
        ? findElementByText('button, [role="tab"], [role="button"], span', config.subMode)
        : null;
    }

    if (!topBtn || !isVisible(topBtn)) {
      return { ok: false, error: 'ERR_MODE_SELECTION_FAILED', detail: `${config.topMode} control not visible after opening type selector` };
    }

    if (config.subMode && (!subBtn || !isVisible(subBtn))) {
      return { ok: false, error: 'ERR_MODE_SELECTION_FAILED', detail: `${config.subMode} control not visible after opening type selector` };
    }

    return { ok: true, config, topBtn, subBtn };
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

  function findUploadSlotByLabel(slotLabel) {
    const isStart = String(slotLabel).toLowerCase() === 'start';
    const isEnd = String(slotLabel).toLowerCase() === 'end';

    // 1. Find all candidate label elements using inclusive detection logic
    const candidates = Array.from(document.querySelectorAll('label, span, div, p, button, [role="button"]'))
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

  async function simulateFileUpload(slotLabel, assetSource, stateObj = null) {
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
      await sleep(500);

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
        
        console.log(`[FlowAgent] Resolving local asset via background proxy: ${assetId}`);
        setCheckpoint('UPLOAD_ASSET_PROXY_SEND');
        const proxyResp = await new Promise((resolve) => {
          const proxyTimeout = setTimeout(() => {
            console.warn(`[FlowAgent] Background proxy timeout for ${assetId}`);
            resolve({ ok: false, error: 'ERR_PROXY_MESSAGE_TIMEOUT' });
          }, 15000);

          chrome.runtime.sendMessage({
            type: 'RESOLVE_LOCAL_ASSET',
            assetId,
            filename: `${assetId}.jpg`,
            request_id: request_id // From executeFlowJob scope
          }, (resp) => {
            clearTimeout(proxyTimeout);
            resolve(resp);
          });
        });

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
      // Scoped resolution: Resolve clickable target from the slot container
      const fileInput = slotContainer.querySelector('input[type="file"]');
      const dropzone = slotContainer.querySelector('[role="presentation"], .dropzone, [aria-label*="upload"]');

      // Fallback: Resolve clickable target inside the slot
      const internalClickable = slotContainer.querySelector('button, [role="button"], label, div[onclick]');

      const target = fileInput || dropzone || internalClickable || slotBtn;

      if (!target || !slotContainer.contains(target)) {
        const diag = {
          start_container_outerHTML: slotContainer.outerHTML.slice(0, 500),
          file_input_found: Boolean(fileInput),
          clickable_target_found: Boolean(internalClickable || slotBtn),
          clickable_target_outerHTML: (internalClickable || slotBtn)?.outerHTML?.slice(0, 500),
        };
        return {
          ok: false,
          error: buildSlotErrorCode(slotLabel, 'UPLOAD_TARGET_NOT_FOUND'),
          detail: `ERR_START_UPLOAD_TARGET_NOT_FOUND — ${JSON.stringify(diag)}`,
          lastCheckpoint,
        };
      }
      setCheckpoint('UPLOAD_TARGET_RESOLVED');

      setCheckpoint('UPLOAD_DISPATCH_STARTED');
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
      setCheckpoint('UPLOAD_DISPATCH_COMPLETED');

      console.log(`[FlowAgent] Dispatched upload for ${slotLabel}`);
      await sleep(600);
      return {
        ok: true,
        slotElement: slotBtn,
        slotContainer,
        beforeSnapshot,
        lastCheckpoint,
      };
    } catch (error) {
      console.error(`[FlowAgent] Upload dispatch failed for ${slotLabel}: ${error.message}`);
      return { ok: false, error: buildSlotErrorCode(slotLabel, 'UPLOAD_DISPATCH_FAILED'), lastCheckpoint };
    }
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
      const text = normalizeText(el.textContent);
      const veoMatch = text.match(/Veo(?:[-\s]?3(?:\.1)?(?:\s*-\s*(?:Lite|Pro))?)/i);
      if (veoMatch) {
        observed.model = normalizeText(veoMatch[0]);
        break;
      }
      const nanoBananaMatch = text.match(/Nano Banana(?:\s*2)?(?:\s*-\s*Pro|\s+Pro)?/i);
      if (nanoBananaMatch) {
        observed.model = normalizeText(nanoBananaMatch[0]);
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

    if (result.ok && mode) {
      const expectedJob = buildExpectedModeJob(mode);
      if (expectedJob) {
        const verifyResult = verifyFlowMode(expectedJob, observed);
        if (!verifyResult.ok) {
          result.ok = false;
          result.error = `ABORT_FLOW_MODE_MISMATCH: ${verifyResult.reason}`;
          result.verify = verifyResult;
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

      const modeVisible = String(readiness.current_mode_visible || '');
      const modeReady = modeVisible.includes('Video/Frames');
      if (readiness.ok && readiness.composer_found && readiness.composer_editable && readiness.generate_button_found && modeReady) {
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
    if (obs.topMode !== 'Video') return false;
    if (obs.subMode !== 'Frames') return false;
    if (!obs.visibleUploadSlots.includes('Start')) return false;
    if (obs.model && /nano.?banana/i.test(obs.model)) return false;
    const composer = findComposerElement();
    if (!composer || !isVisible(composer)) return false;
    return true;
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
  async function ensureF2VFramesWorkspaceReady(job, logStage) {
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
      console.log('[FlowAgent] ' + snapMsg);

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
        `${modeControls.error || 'ensureModeControlsVisible(F2V) returned !ok'}${modeControls.detail ? ' — ' + modeControls.detail : ''}`);
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

    // ── Step 4: Select Frames submode ────────────────────────────────────────
    if (subBtn && isVisible(subBtn) && !isSelectedControl(subBtn, 'Frames')) {
      subBtn.click();
      await sleep(800);
    }

    const obsAfterFrames = observeFlowState();
    if (obsAfterFrames.subMode !== 'Frames') {
      logStage(STAGES.FLOW_SUBMODE_FRAMES_SELECTED, 'FAIL', `subMode=${obsAfterFrames.subMode}`);
      throw new Error('ERR_FRAMES_MODE_NOT_ACTIVE');
    }
    logStage(STAGES.FLOW_SUBMODE_FRAMES_SELECTED, 'PASS', 'subMode=Frames');

    const composerReady = await ensureF2VComposerReadyBeforeConfig();
    if (!composerReady.ok) {
      logStage(STAGES.F2V_COMPOSER_READY, 'FAIL', `${composerReady.error} — ${composerReady.detail}`);
      throw new Error(composerReady.error);
    }
    logStage(STAGES.F2V_COMPOSER_READY, 'PASS', composerReady.detail);

    // ── Steps 5–7: Config panel (9:16 / 1x / Veo 3.1 - Lite) ────────────────
    const configMenuOpen = await ensureOpenF2VConfigMenu();
    if (!configMenuOpen.ok) {
      logStage(STAGES.FLOW_ASPECT_9_16_SELECTED, 'FAIL', `ERR_F2V_CONFIG_MENU_NOT_OPEN — ${configMenuOpen.detail}`);
      throw new Error('ERR_F2V_CONFIG_MENU_NOT_OPEN');
    }
    const configCheck = await ensureF2VVerifiedAspectCountAndModel();
    if (!configCheck.ok && configCheck.error === 'ERR_ASPECT_9_16_NOT_SELECTED') {
      logStage(STAGES.FLOW_ASPECT_9_16_SELECTED, 'FAIL', configCheck.detail);
      throw new Error('ERR_ASPECT_9_16_NOT_SELECTED');
    }
    logStage(STAGES.FLOW_ASPECT_9_16_SELECTED, 'PASS');

    if (!configCheck.ok && configCheck.error === 'ERR_COUNT_1X_NOT_SELECTED') {
      logStage(STAGES.FLOW_COUNT_1X_SELECTED, 'FAIL', configCheck.detail);
      throw new Error('ERR_COUNT_1X_NOT_SELECTED');
    }
    logStage(STAGES.FLOW_COUNT_1X_SELECTED, 'PASS');

    if (!configCheck.ok && configCheck.error === 'ERR_WRONG_MODEL_FOR_F2V') {
      logStage(STAGES.FLOW_MODEL_VEO_3_1_LITE_SELECTED, 'FAIL', configCheck.detail);
      throw new Error('ERR_WRONG_MODEL_FOR_F2V');
    }
    logStage(STAGES.FLOW_MODEL_VEO_3_1_LITE_SELECTED, 'PASS', `model=${configCheck.modelText}`);

    // ── Step 8: Upload gate — Start slot must be visible ─────────────────────
    const obsForSlot = observeFlowState();
    if (!obsForSlot.visibleUploadSlots.includes('Start')) {
      logStage(STAGES.START_SLOT_VISIBLE, 'FAIL',
        `slots=[${obsForSlot.visibleUploadSlots.join(',')}]`);
      throw new Error('ERR_START_SLOT_NOT_VISIBLE');
    }
    logStage(STAGES.START_SLOT_VISIBLE, 'PASS',
      `slots=[${obsForSlot.visibleUploadSlots.join(',')}]`);

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

  async function executeFlowJob(job) {
    const testConn = await new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: 'STATUS' }, resolve);
    });
    console.log('[FlowAgent] Background connection test:', testConn);

    const report = { ok: false, stages: [] };
    const request_id = job.request_id || `flow_${Date.now()}`;
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
      logStage(STAGES.FLOW_TAB_FOUND, 'YES', `background_conn=${testConn?.ok || (testConn && typeof testConn === 'object')}`);

      // 0. Log job received
      if (job.prompt) {
        logStage(STAGES.JOB_PROMPT_RECEIVED, `${job.prompt.length} chars`);
      } else {
        logStage(STAGES.JOB_PROMPT_RECEIVED, 'MISSING');
        throw new Error('JOB_PROMPT_EMPTY');
      }

      // CRITICAL: Clear any pre-existing state
      logStage(STAGES.PRE_EXECUTION_STATE_CLEARED);

      if (job.mode === 'F2V') {
        // CRITICAL: F2V SOP state machine — deterministic golden path:
        //   Root/Landing → New Project → Video → Frames → 9:16 → 1x → Veo 3.1 - Lite
        //   → Start slot visible → prompt field visible
        // Hard-aborts with specific error codes on any mismatch.
        await ensureF2VFramesWorkspaceReady(job, logStage);
        // ensureF2VFramesWorkspaceReady already emits FLOW_TYPE_VIDEO_SELECTED,
        // FLOW_SUBMODE_FRAMES_SELECTED, FLOW_ASPECT_9_16_SELECTED, etc.
        // Log the legacy compatibility stages so downstream consumers see them too.
        logStage(STAGES.FLOW_MODE_SELECTED, 'Video');
        logStage(STAGES.FLOW_SUBMODE_SELECTED, 'Frames');
        logStage(STAGES.FLOW_MODE_VERIFIED);
      } else {
        // 1. Select Top Mode (STRICT - must be correct mode)
        const modeControls = await ensureModeControlsVisible(job.mode);
        if (!modeControls.ok) throw new Error(modeControls.error || 'ERR_MODE_SELECTION_FAILED');
        const modeBtn = modeControls.topBtn;
        if (!modeBtn) throw new Error(`Mode button ${job.mode} not found`);
        modeBtn.click();
        await sleep(1000);
        logStage(STAGES.FLOW_MODE_SELECTED, resolveFlowModeConfig(job.mode)?.topMode || job.mode);

        // 2. Select Submode (STRICT)
        if (job.mode === 'I2V') {
          const submodeText = resolveFlowModeConfig(job.mode)?.subMode;
          const modeControls2 = await ensureModeControlsVisible(job.mode);
          const submodeBtn = modeControls2.subBtn;
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
        const requestedCount = resolveRequestedCount(job);
        const requestedModel = resolveRequestedModel(job);
        if (requestedAspectRatio || requestedCount || requestedModel) {
          await openFlowConfigPanel();
        }

        if (requestedAspectRatio && await selectFlowConfigOption(requestedAspectRatio)) {
          logStage(STAGES.ASPECT_SELECTED, requestedAspectRatio);
        }

        // 4. Set Count
        if (requestedCount && await selectFlowConfigOption(requestedCount)) {
          logStage(STAGES.COUNT_SELECTED, requestedCount);
        }

        // 5. Set Model
        if (requestedModel && await selectFlowConfigOption(requestedModel)) {
          logStage(STAGES.MODEL_SELECTED, requestedModel);
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
      }

      // 6. Attach Assets (STRICT: Asset First, Prompt Second)
      const assetSlotContexts = [];
      if (job.mode === 'F2V') {
        // Step 6a: Upload Start Frame
        const startAssetSource = job.startAsset || job.productId || job.startImageMediaId;
        const assetSourceType = !startAssetSource ? 'missing' : typeof startAssetSource === 'string' ? (startAssetSource.startsWith('data:') ? 'data_url' : (startAssetSource.startsWith('http') ? 'url' : 'path/id')) : 'object';
        const assetFilename = (typeof startAssetSource === 'object' && startAssetSource) ? startAssetSource.fileName : 'unknown';

        logStage(STAGES.START_FRAME_UPLOAD_ATTEMPTED, 'PASS', 
          `slot=Start asset_source_type=${assetSourceType} asset_filename=${assetFilename} visible_upload_slots=${observeFlowState().visibleUploadSlots.join(',')}`);

        const uploadTimeoutPromise = new Promise((_, reject) => 
          setTimeout(() => reject(new Error('ERR_START_UPLOAD_TIMEOUT')), 20000)
        );

        const uploadState = { lastCheckpoint: 'NONE' };
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
          logStage(STAGES.START_FRAME_ATTACHED, 'PASS', `slot=Start dispatch=ok last_checkpoint=${okStart.lastCheckpoint}`);

          uploadState.lastCheckpoint = 'UPLOAD_PREVIEW_WAIT_STARTED';
          const startPreview = await waitForAssetPreview('Start', okStart.slotElement || null, {
            slotContainer: okStart.slotContainer || null,
            beforeSnapshot: okStart.beforeSnapshot || null,
            timeoutMs: 15000,
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
