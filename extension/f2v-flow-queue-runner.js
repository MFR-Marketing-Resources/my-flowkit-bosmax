/**
 * extension/f2v-flow-queue-runner.js
 *
 * Lightweight F2V runner inspired by flow-queue v0.4.0-beta.
 *
 * Why this exists
 * ───────────────
 * The legacy F2V state machine in content-flow-dom.js (observeFlowState
 * + ensureF2VFramesWorkspaceReady + ensureModeControlsVisible +
 * configureVisibleF2VComposerSettings) has reached its design ceiling.
 * Across manual_8e432a34, manual_fa0d11f4, manual_da996ef1,
 * manual_7a1b96bf, and manual_a0b853bb, the same failure surfaces:
 * inference gates (topMode/subMode/model) make terminal decisions
 * BEFORE the visible composer settings panel is even opened, so the
 * automation cannot recover from minified DOM or icon-fused labels.
 *
 * flow-queue's v0.4.0-beta solved an analogous Google Flow submission
 * problem with a much smaller surface:
 *
 *   1. Content script discovers visible textbox/buttons by exact text.
 *   2. Content script INSERTS the prompt by addressing the textarea
 *      directly — no React-internal tricks for plain inputs.
 *   3. For the generate submit, content script marks the target button
 *      with a data attribute, then asks the service worker to run a
 *      chrome.scripting.executeScript({ world: "MAIN" }) helper.
 *   4. The MAIN-world helper walks __reactFiber$… / __reactInternalInstance$…
 *      back through fiber.return until it finds the React props with
 *      onSubmit / onClick handlers, then calls them DIRECTLY. This
 *      bypasses event.isTrusted gating that ordinarily makes synthetic
 *      clicks bounce off React's own handlers.
 *   5. Old click()/Enter fallback only fires when MAIN-world handler
 *      lookup fails.
 *   6. Every strategy is logged distinctly — no silent retries.
 *
 * This runner transplants the same shape into BOSMAX. It runs in the
 * service worker, uses chrome.scripting.executeScript({ world: "MAIN" })
 * for the DOM probes + the React fiber submit, and emits the exact
 * telemetry stages the operator spec'd:
 *
 *   F2V_SOP_NEW_PROJECT_READY
 *   F2V_SOP_SETTINGS_PANEL_OPENED
 *   F2V_SOP_VIDEO_CLICKED
 *   F2V_SOP_FRAMES_CLICKED
 *   F2V_SOP_RATIO_9_16_CLICKED
 *   F2V_SOP_COUNT_1X_CLICKED
 *   F2V_SOP_MODEL_VEO_CLICKED
 *   F2V_SOP_SETTINGS_CONFIGURED
 *   F2V_SOP_PROMPT_INSERTED
 *   F2V_SOP_START_CLICKED
 *   F2V_SOP_UPLOAD_CLICKED
 *   F2V_SOP_UPLOAD_WAIT_DONE
 *   F2V_SOP_GENERATE_SUBMITTED
 *
 * Strict order. No inference gate. Each click probes for the visible
 * candidate; missing candidate fails with a specific error code AND
 * a list of visible candidates for forensics.
 *
 * Dependency-injected: accepts a `scripting` adapter exposing
 *   {
 *     executeScript({ tabId, func, args, world })  → Promise<{result}[]>,
 *   }
 * Real background.js wires it to chrome.scripting; unit tests wire it
 * to a mock that records calls. No chrome.* APIs are referenced
 * directly in this file so tests stay pure.
 *
 * Authority: AGENTS.md → CHROME_EXTENSION_MV3_DEBUG_CONTRACT.md →
 * operator runtime brief manual_a0b853bb +
 * flow-queue/johneadams88 v0.4.0-beta architecture reference.
 *
 * Branch: spike/f2v-flow-queue-runner — NOT merged.
 */

'use strict';

// ─── IIFE wrapper ────────────────────────────────────────────────────────
//
// MUST stay wrapped. f2v-flow-queue-runner.js is loaded into the service-
// worker global scope via importScripts() alongside cdp-visible-clicker.js.
// Both files originally declared a top-level `const ERR = {...}` — those
// collided at runtime with:
//
//   SyntaxError: Failed to execute 'importScripts' on
//   'WorkerGlobalScope': Identifier 'ERR' has already been declared
//
// Wrapping the entire file body in an IIFE makes every top-level const /
// let / function module-scoped instead of worker-global. We expose exactly
// one symbol — `self.__BOSMAX_F2V_FLOW_QUEUE_RUNNER__` — so the rest of
// background.js has a stable entry-point. CommonJS `module.exports` is
// preserved so Node tests can `require()` the file unchanged.
(function () {

// ───────────────────────────────────────────────────────────────────────
// Constants
// ───────────────────────────────────────────────────────────────────────

const F2V_FLOW_QUEUE_RUNNER_BUILD_ID = 'flowkit-f2v-runner-adaptive-pill-2026-06-10';
const SOP_DEFAULT_SETTLE_MS = 300;
const SOP_DEFAULT_OPEN_PANEL_TIMEOUT_MS = 4000;
const SOP_DEFAULT_UPLOAD_WAIT_MS = 10000;

/**
 * Each SOP step maps a user-visible label to:
 *   - stage           : the telemetry stage key
 *   - errorCode       : the structured failure code emitted on absence
 *   - aliases         : alternative spellings (Veo 3.1 - Lite vs Lite)
 *   - preferredRoles  : ARIA roles to prefer when disambiguating
 */
const SOP_SEQUENCE = Object.freeze([
  {
    label: 'Video',
    aliases: [],
    preferredRoles: ['tab', 'option', 'menuitem', 'button'],
    stage: 'F2V_SOP_VIDEO_CLICKED',
    errorCode: 'ERR_F2V_OPTION_VIDEO_NOT_FOUND',
  },
  {
    label: 'Frames',
    aliases: [],
    preferredRoles: ['tab', 'option', 'menuitem', 'button'],
    stage: 'F2V_SOP_FRAMES_CLICKED',
    errorCode: 'ERR_F2V_OPTION_FRAMES_NOT_FOUND',
  },
  {
    label: '9:16',
    aliases: ['9 : 16', 'Portrait 9:16', 'crop_9_16', 'crop-9-16', 'crop 9:16', 'crop_9:16', 'crop_9_16 Portrait 9:16', 'crop_9_16 Portrait', 'crop_9_16 9:16'],
    preferredRoles: ['option', 'menuitemradio', 'menuitem', 'tab'],
    stage: 'F2V_SOP_RATIO_9_16_CLICKED',
    errorCode: 'ERR_F2V_OPTION_RATIO_9_16_NOT_FOUND',
  },
  {
    label: '1x',
    aliases: ['1×', '1 variation', '1 x', 'x1', '1x 1 variation', '1x 1'],
    preferredRoles: ['option', 'menuitemradio', 'menuitem', 'tab'],
    stage: 'F2V_SOP_COUNT_1X_CLICKED',
    errorCode: 'ERR_F2V_OPTION_COUNT_1X_NOT_FOUND',
  },
  {
    label: 'Veo 3.1 - Lite',
    aliases: ['Veo 3.1 Lite', 'Veo 3.1-Lite', 'Veo 3.1 — Lite', 'Veo 3.1', 'Veo', 'Veo 3.1 Lite (F2V)', 'Veo 3.1 - Lite (F2V)', 'Veo Lite'],
    preferredRoles: ['option', 'menuitemradio', 'menuitem'],
    stage: 'F2V_SOP_MODEL_VEO_CLICKED',
    errorCode: 'ERR_F2V_OPTION_VEO_3_1_LITE_NOT_FOUND',
  },
]);

const ERR = Object.freeze({
  FLOW_TAB_NOT_TARGETED: 'ERR_FLOW_TAB_NOT_TARGETED',
  SETTINGS_PANEL_NOT_OPEN: 'ERR_F2V_SETTINGS_PANEL_NOT_OPEN',
  SETTINGS_NOT_CONFIGURED_BEFORE_UPLOAD: 'ERR_F2V_SETTINGS_NOT_CONFIGURED_BEFORE_UPLOAD',
  GENERATE_PRECONDITION_FAILED: 'ERR_F2V_GENERATE_PRECONDITION_FAILED',
  MAIN_WORLD_SUBMIT_HANDLER_NOT_FOUND: 'ERR_MAIN_WORLD_SUBMIT_HANDLER_NOT_FOUND',
  PROMPT_FIELD_NOT_FOUND: 'ERR_F2V_PROMPT_FIELD_NOT_FOUND',
  START_BUTTON_NOT_FOUND: 'ERR_F2V_START_BUTTON_NOT_FOUND',
  UPLOAD_MEDIA_NOT_FOUND: 'ERR_F2V_UPLOAD_MEDIA_NOT_FOUND',
  NEW_PROJECT_FAILED: 'ERR_F2V_NEW_PROJECT_FAILED',
  EXECUTION_THREW: 'ERR_F2V_SOP_RUNNER_THREW',
});

const F2V_SOP_STAGE_CONTRACT = Object.freeze([
  'F2V_SOP_SETTINGS_EXPLORER_STARTED',
  'F2V_SOP_SETTINGS_LAUNCHER_FOUND',
  'F2V_SOP_SETTINGS_PANEL_OPENED',
  'F2V_SOP_SETTING_CANDIDATES_SCANNED',
  'F2V_SOP_VIDEO_CLICKED',
  'F2V_SOP_VIDEO_CONFIRMED',
  'F2V_SOP_FRAMES_CLICKED',
  'F2V_SOP_FRAMES_CONFIRMED',
  'F2V_SOP_RATIO_9_16_CLICKED',
  'F2V_SOP_RATIO_9_16_CONFIRMED',
  'F2V_SOP_COUNT_1X_CLICKED',
  'F2V_SOP_COUNT_1X_CONFIRMED',
  'F2V_SOP_MODEL_VEO_CLICKED',
  'F2V_SOP_MODEL_VEO_CONFIRMED',
  'F2V_SOP_SETTINGS_CONFIGURED'
]);

// ───────────────────────────────────────────────────────────────────────
// MAIN-world helpers
// ───────────────────────────────────────────────────────────────────────
//
// These functions are SERIALISED and re-evaluated inside the target tab
// via chrome.scripting.executeScript({ world: "MAIN" }). They MUST be
// pure (no closures over outer scope; all dependencies passed via args)
// and self-contained (no imports — JSDOM testing reads them as plain
// functions).

/**
 * MAIN-world: enumerate all visible interactive elements with an
 * accessible name matching `label` (exact, optionally also alias).
 *
 * Returns an array of click descriptors. Each descriptor has a
 * stable temporary id stamped onto the element so the caller can
 * dispatch a follow-up click by id without rescanning.
 *
 * Selector logic deliberately avoids:
 *   - asset-library "videocamVideos" / "imageImages" prefix-match
 *     traps (we strip Material-Icon-snake_case prefixes BEFORE
 *     comparing to the target label)
 *   - inner-text matches that resolve to non-interactive wrapper divs
 */
function MAIN_findVisibleCandidatesByExactLabel(targetLabel, aliases, preferredRoles, stampAttr) {
  const ICON_TOKENS = new Set([
    'add_2', 'add', 'arrow_back', 'arrow_drop_down', 'arrow_forward',
    'accessibility_new', 'apps_spark_2', 'category', 'check', 'close',
    'collections', 'dashboard', 'delete', 'drive_folder_upload',
    'edit', 'expand_more', 'face', 'filter_list', 'help', 'image',
    'imagesmode', 'left_panel_close', 'movie', 'more_vert',
    'play_circle', 'search', 'settings', 'settings_2', 'spark',
    'subdirectory_arrow_right', 'tune', 'upload', 'videocam',
    'view_module', 'voice_selection', 'crop_free', 'chrome_extension',
  ]);
  function stripIcon(s) {
    var trimmed = String(s == null ? '' : s).trim();
    if (!trimmed) return '';
    var m = /^([a-z][a-z0-9_]*)\s*([A-Z0-9].*)$/.exec(trimmed);
    if (m && ICON_TOKENS.has(m[1])) return m[2].trim();
    return trimmed;
  }
  function normalize(s) {
    return String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  }
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var style = window.getComputedStyle(el);
    if (!style) return false;
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) {
      return false;
    }
    return true;
  }
  function isInteractive(el) {
    if (!el || !el.tagName) return false;
    var tag = el.tagName.toLowerCase();
    if (tag === 'button' || tag === 'a' || tag === 'input' || tag === 'textarea') return true;
    var role = el.getAttribute && el.getAttribute('role');
    if (role && ['tab', 'button', 'option', 'menuitem', 'menuitemradio', 'menuitemcheckbox', 'link', 'checkbox', 'radio', 'switch'].indexOf(role) >= 0) return true;
    if (el.hasAttribute && (el.hasAttribute('aria-selected') || el.hasAttribute('aria-pressed') || el.hasAttribute('data-state'))) return true;
    return false;
  }

  var needle = normalize(targetLabel).toLowerCase();
  var aliasNeedles = (aliases || []).map(function (s) { return normalize(s).toLowerCase(); });
  var preferred = Array.isArray(preferredRoles) && preferredRoles.length > 0 ? preferredRoles : null;

  var matches = [];
  var visibleCandidates = [];
  var all = document.querySelectorAll(
    'button, a, input, textarea, [role], [aria-selected], [aria-pressed], [data-state], li, span, div, label',
  );

  for (var i = 0; i < all.length; i++) {
    var el = all[i];
    if (!isVisible(el)) continue;
    // BLACKLIST: never interact with navigation anchors that redirect away from the editor.
    var _blTag = el.tagName ? el.tagName.toLowerCase() : '';
    if (_blTag === 'a') {
      var _blHref = (el.getAttribute && el.getAttribute('href')) || '';
      if (_blHref && (_blHref.indexOf('/fx/tools/flow') >= 0 || (_blHref.indexOf('/fx/') >= 0 && _blHref.indexOf('flow') >= 0))) continue;
      var _blAria = ((el.getAttribute && el.getAttribute('aria-label')) || '').replace(/\s+/g, ' ').trim().toLowerCase();
      var _blTxt  = (el.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
      if (_blTxt === 'google flow' || _blAria === 'google flow') continue;
    }
    var raw = normalize(el.textContent || el.getAttribute('aria-label') || el.value || '');
    if (!raw) continue;
    var rawLower = raw.toLowerCase();
    var stripped = stripIcon(raw).toLowerCase();
    var isMatch = rawLower === needle || stripped === needle;
    if (!isMatch && aliasNeedles.length > 0) {
      for (var k = 0; k < aliasNeedles.length; k++) {
        if (rawLower === aliasNeedles[k] || stripped === aliasNeedles[k]) {
          isMatch = true;
          break;
        }
      }
    }
    if (!isMatch) {
      // Track interactive candidates for forensics even if non-matching.
      if (isInteractive(el) && visibleCandidates.length < 30) {
        var truncated = raw.length > 60 ? raw.slice(0, 60) : raw;
        visibleCandidates.push({ text: truncated, role: el.getAttribute && el.getAttribute('role') || el.tagName.toLowerCase() });
      }
      continue;
    }

    // Normalise to nearest interactive ancestor.
    var target = el;
    if (!isInteractive(el) && el.closest) {
      var ancestor = el.closest(
        'button, [role="tab"], [role="button"], [role="option"], [role="menuitem"], [role="menuitemradio"], [aria-selected], [aria-pressed], [data-state], a',
      );
      if (ancestor && isVisible(ancestor) && isInteractive(ancestor)) {
        // BLACKLIST: never resolve to a dangerous navigation anchor.
        var _anTag  = ancestor.tagName ? ancestor.tagName.toLowerCase() : '';
        var _anHref = (ancestor.getAttribute && ancestor.getAttribute('href')) || '';
        var _isDangerousAnchor = _anTag === 'a' && _anHref && (_anHref.indexOf('/fx/tools/flow') >= 0 || (_anHref.indexOf('/fx/') >= 0 && _anHref.indexOf('flow') >= 0));
        if (!_isDangerousAnchor) target = ancestor;
      }
    }
    if (!isInteractive(target)) continue;
    if (!isVisible(target)) continue;
    // BLACKLIST: final guard on the resolved target element.
    var _tgTag  = target.tagName ? target.tagName.toLowerCase() : '';
    var _tgHref = (target.getAttribute && target.getAttribute('href')) || '';
    if (_tgTag === 'a' && _tgHref && (_tgHref.indexOf('/fx/tools/flow') >= 0 || (_tgHref.indexOf('/fx/') >= 0 && _tgHref.indexOf('flow') >= 0))) continue;

    var role = (target.getAttribute && target.getAttribute('role')) || target.tagName.toLowerCase();
    var rect = target.getBoundingClientRect();
    matches.push({
      el: target,
      role: role,
      bbox: { x: rect.left, y: rect.top, width: rect.width, height: rect.height },
      text: raw,
    });
  }

  // Prefer roles requested by the caller (e.g. option/menuitem over the
  // launcher button when the same label appears twice).
  if (preferred) {
    matches.sort(function (a, b) {
      var aIdx = preferred.indexOf(a.role);
      var bIdx = preferred.indexOf(b.role);
      if (aIdx === -1) aIdx = 9999;
      if (bIdx === -1) bIdx = 9999;
      return aIdx - bIdx;
    });
  }

  // Stamp + serialise to a plain JSON-safe shape.
  var stampPrefix = String(stampAttr || 'data-bosmax-target');
  var out = [];
  for (var j = 0; j < matches.length; j++) {
    var m = matches[j];
    var id = stampPrefix + '-' + Date.now() + '-' + j + '-' + Math.floor(Math.random() * 1e6);
    m.el.setAttribute(stampPrefix, id);
    out.push({
      stamp_id: id,
      stamp_attr: stampPrefix,
      role: m.role,
      bbox: m.bbox,
      text: m.text.slice(0, 80),
    });
  }
  return { ok: true, matches: out, visible_candidates: visibleCandidates };
}

/**
 * MAIN-world: click a previously-stamped element. Dispatches a real
 * MouseEvent (not synthetic) so React + Radix register the click.
 * Returns the post-click semantic state (aria-selected / data-state /
 * aria-pressed) so the runner can decide whether to retry.
 */
function MAIN_clickStampedElement(stampAttr, stampId) {
  var el = document.querySelector('[' + stampAttr + '="' + stampId + '"]');
  if (!el) return { ok: false, reason: 'stamp_not_found' };
  try { el.scrollIntoView({ block: 'center', inline: 'center' }); } catch (e) { /* noop */ }
  // Dispatch pointer + mouse + click; React picks up the click event,
  // Radix often listens on pointer events too.
  var rect = el.getBoundingClientRect();
  var ix = rect.left + rect.width / 2;
  var iy = rect.top + rect.height / 2;
  var common = { bubbles: true, cancelable: true, view: window, clientX: ix, clientY: iy, button: 0 };
  try { el.dispatchEvent(new PointerEvent('pointerdown', Object.assign({ pointerType: 'mouse' }, common))); } catch (e) { /* noop */ }
  try { el.dispatchEvent(new MouseEvent('mousedown', common)); } catch (e) { /* noop */ }
  try { el.dispatchEvent(new PointerEvent('pointerup', Object.assign({ pointerType: 'mouse' }, common))); } catch (e) { /* noop */ }
  try { el.dispatchEvent(new MouseEvent('mouseup', common)); } catch (e) { /* noop */ }
  try { el.dispatchEvent(new MouseEvent('click', common)); } catch (e) { /* noop */ }
  try { el.click(); } catch (e) { /* noop */ }
  return {
    ok: true,
    post_state: {
      aria_selected: el.getAttribute && el.getAttribute('aria-selected'),
      aria_pressed: el.getAttribute && el.getAttribute('aria-pressed'),
      data_state: el.getAttribute && el.getAttribute('data-state'),
      class_name: el.className && String(el.className).slice(0, 200),
    },
  };
}

/**
 * MAIN-world: locate the composer settings/model launcher and click it
 * if the panel is not already open. Returns ok+already_open or ok+clicked
 * or {ok:false} with visible candidates.
 *
 * Launcher heuristic (matches flow-queue's looser scope):
 *   - aria-haspopup="menu" OR role="combobox"
 *   - visible text contains a model family token (Veo / Nano Banana /
 *     Imagen / Gemini / Wan / Seedance / Hailuo / Kling / Sora) OR
 *     "Settings" / "View Settings"
 *   - excluded: any element whose text matches the asset-library
 *     navigation signature ("All Media", "Images", "Videos", "Voices",
 *     "Avatar", "Uploads", "Recent")
 */
function MAIN_openComposerSettingsPanel(stampAttr) {
  var ICON_TOKENS = new Set([
    'add_2', 'add', 'arrow_back', 'arrow_drop_down', 'arrow_forward',
    'accessibility_new', 'apps_spark_2', 'category', 'check', 'close',
    'collections', 'dashboard', 'delete', 'drive_folder_upload',
    'edit', 'expand_more', 'face', 'filter_list', 'help', 'image',
    'imagesmode', 'left_panel_close', 'movie', 'more_vert',
    'play_circle', 'search', 'settings', 'settings_2', 'spark',
    'subdirectory_arrow_right', 'tune', 'upload', 'videocam',
    'view_module', 'voice_selection', 'crop_free', 'chrome_extension',
  ]);
  function normalize(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); }
  function lower(s) { return normalize(s).toLowerCase(); }
  function stripIcon(s) {
    var trimmed = normalize(s);
    if (!trimmed) return '';
    var m = /^([a-z][a-z0-9_]*)\s*([A-Z0-9].*)$/.exec(trimmed);
    if (m && ICON_TOKENS.has(m[1])) return normalize(m[2]);
    return trimmed;
  }
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  function getRect(el) {
    if (!el || !el.getBoundingClientRect) return null;
    var r = el.getBoundingClientRect();
    return {
      x: Math.round(r.left),
      y: Math.round(r.top),
      width: Math.round(r.width),
      height: Math.round(r.height),
      right: Math.round(r.right),
      bottom: Math.round(r.bottom),
    };
  }
  function getText(el) {
    if (!el) return '';
    var textParts = [];
    function walk(node) {
      if (!node) return;
      if (node.nodeType === 3) {
        var value = normalize(node.nodeValue || '');
        if (value) textParts.push(value);
        return;
      }
      if (!node.childNodes || !node.childNodes.length) return;
      for (var idx = 0; idx < node.childNodes.length; idx++) {
        walk(node.childNodes[idx]);
      }
    }
    walk(el);
    return stripIcon([
      textParts.join(' '),
      el.getAttribute ? (el.getAttribute('aria-label') || '') : '',
      el.getAttribute ? (el.getAttribute('title') || '') : '',
    ].join(' '));
  }
  function getIconText(el) {
    if (!el || !el.querySelectorAll) return '';
    var nodes = el.querySelectorAll('[data-icon], svg title, .material-symbols-outlined, .material-icons');
    var out = [];
    for (var i = 0; i < nodes.length; i++) {
      if (!isVisible(nodes[i])) continue;
      var t = normalize(nodes[i].textContent || nodes[i].getAttribute && nodes[i].getAttribute('data-icon') || '');
      if (t) out.push(t);
    }
    return normalize(out.join(' '));
  }
  function isInteractive(el) {
    if (!el || !el.tagName) return false;
    var tag = String(el.tagName || '').toLowerCase();
    if (tag === 'button' || tag === 'a' || tag === 'input' || tag === 'textarea') return true;
    var role = el.getAttribute && el.getAttribute('role');
    if (role && ['button', 'tab', 'option', 'combobox', 'menuitem', 'menuitemradio'].indexOf(role) >= 0) return true;
    return Boolean(el.hasAttribute && (
      el.hasAttribute('aria-haspopup')
      || el.hasAttribute('aria-expanded')
      || el.hasAttribute('aria-selected')
      || el.hasAttribute('aria-pressed')
      || el.hasAttribute('data-state')
    ));
  }
  function isClickableLike(el) {
    if (!el || !el.tagName) return false;
    if (isInteractive(el)) return true;
    if (typeof el.onclick === 'function') return true;
    if (typeof el.tabIndex === 'number' && el.tabIndex >= 0) return true;
    var style = window.getComputedStyle(el);
    if (style && style.cursor === 'pointer') return true;
    return Boolean(el.hasAttribute && (
      el.hasAttribute('tabindex')
      || el.hasAttribute('onclick')
      || el.hasAttribute('data-state')
      || el.hasAttribute('aria-haspopup')
      || el.hasAttribute('aria-expanded')
    ));
  }
  function toInteractive(el, stopAt) {
    if (!el) return null;
    var current = el;
    while (current) {
      if (isClickableLike(current)) return current;
      if (stopAt && current === stopAt) break;
      current = current.parentElement || null;
    }
    return el.closest ? el.closest('button, [role="button"], [role="tab"], [role="option"], [role="combobox"], [aria-haspopup], [aria-expanded], [aria-selected], [aria-pressed], [data-state], [tabindex]') : null;
  }
  function getPromptField() {
    var slateEditors = document.querySelectorAll('[data-slate-editor="true"][contenteditable="true"]');
    var slateCandidates = [];
    for (var i2 = 0; i2 < slateEditors.length; i2++) {
      if (!isVisible(slateEditors[i2])) continue;
      slateCandidates.push(slateEditors[i2]);
    }
    if (slateCandidates.length) {
      var withPlaceholder = [];
      for (var j2 = 0; j2 < slateCandidates.length; j2++) {
        var placeholder = slateCandidates[j2].querySelector && slateCandidates[j2].querySelector('[data-slate-placeholder]');
        var label = lower(placeholder && placeholder.textContent || '');
        if (label.indexOf('what do you want') >= 0 || label.indexOf('create') >= 0 || label.indexOf('generate') >= 0) {
          withPlaceholder.push(slateCandidates[j2]);
        }
      }
      var pool = withPlaceholder.length ? withPlaceholder : slateCandidates;
      pool.sort(function (a, b) { return b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom; });
      return pool[0];
    }
    var placeholderNodes = document.querySelectorAll('[data-slate-placeholder], [placeholder], [aria-label], span, div, p');
    for (var k2 = 0; k2 < placeholderNodes.length; k2++) {
      if (!isVisible(placeholderNodes[k2])) continue;
      var markerText = lower([
        placeholderNodes[k2].textContent || '',
        placeholderNodes[k2].getAttribute ? (placeholderNodes[k2].getAttribute('placeholder') || '') : '',
        placeholderNodes[k2].getAttribute ? (placeholderNodes[k2].getAttribute('aria-label') || '') : '',
      ].join(' '));
      if (markerText.indexOf('what do you want to create') === -1) continue;
      var owner = toInteractive(placeholderNodes[k2]) || (placeholderNodes[k2].closest && placeholderNodes[k2].closest('[data-slate-editor="true"], [contenteditable="true"], textarea, input, form, section, article, div'));
      if (owner && isVisible(owner)) return owner;
      return placeholderNodes[k2];
    }
    var inputs = document.querySelectorAll('textarea, [contenteditable="true"], input[type="text"]');
    for (var m2 = 0; m2 < inputs.length; m2++) {
      if (!isVisible(inputs[m2])) continue;
      var probe = lower([
        inputs[m2].getAttribute && (inputs[m2].getAttribute('placeholder') || ''),
        inputs[m2].getAttribute && (inputs[m2].getAttribute('aria-label') || ''),
      ].join(' '));
      if (probe.indexOf('what do you want to create') >= 0) return inputs[m2];
    }
    for (var n2 = 0; n2 < inputs.length; n2++) {
      if (isVisible(inputs[n2])) return inputs[n2];
    }
    return null;
  }
  function getComposerRoot() {
    var prompt = getPromptField();
    if (!prompt || !prompt.closest) return prompt;
    var owner = prompt.closest('form, [role="form"], section, article, main, div') || prompt;
    if (!owner || !owner.getBoundingClientRect) return owner;
    var rect = owner.getBoundingClientRect();
    if (rect.width >= 240 && rect.height >= 120) return owner;
    return owner.parentElement || owner;
  }
  function distanceToComposer(el) {
    var composer = getComposerRoot();
    if (!composer || !composer.getBoundingClientRect || !el || !el.getBoundingClientRect) return Number.MAX_SAFE_INTEGER;
    var a = composer.getBoundingClientRect();
    var b = el.getBoundingClientRect();
    var ax = a.left + (a.width / 2);
    var ay = a.top + (a.height / 2);
    var bx = b.left + (b.width / 2);
    var by = b.top + (b.height / 2);
    return Math.round(Math.sqrt(Math.pow(ax - bx, 2) + Math.pow(ay - by, 2)));
  }
  function distanceBetween(aEl, bEl) {
    if (!aEl || !bEl || !aEl.getBoundingClientRect || !bEl.getBoundingClientRect) return Number.MAX_SAFE_INTEGER;
    var a = aEl.getBoundingClientRect();
    var b = bEl.getBoundingClientRect();
    var ax = a.left + (a.width / 2);
    var ay = a.top + (a.height / 2);
    var bx = b.left + (b.width / 2);
    var by = b.top + (b.height / 2);
    return Math.round(Math.sqrt(Math.pow(ax - bx, 2) + Math.pow(ay - by, 2)));
  }
  function getGenerateArrow() {
    var composer = getComposerRoot();
    if (!composer || !composer.querySelectorAll) return null;
    var nodes = composer.querySelectorAll('button, [role="button"], [aria-label], [data-state], [aria-haspopup], [tabindex]');
    var best = null;
    for (var i3 = 0; i3 < nodes.length; i3++) {
      var node = toInteractive(nodes[i3], composer) || nodes[i3];
      if (!node || !isVisible(node)) continue;
      var combined = lower((getText(node) + ' ' + getIconText(node)).trim());
      if (combined.indexOf('arrow_forward') === -1 && combined.indexOf('generate') === -1 && combined.indexOf('create') === -1) continue;
      var rect = node.getBoundingClientRect();
      var score = Math.round(rect.left + rect.top + rect.width + rect.height);
      if (!best || score > best.score) {
        best = { el: node, score: score };
      }
    }
    return best ? best.el : null;
  }
  function summarizeTextList(selector, mapper) {
    var nodes = document.querySelectorAll(selector);
    var seen = Object.create(null);
    var out = [];
    for (var i4 = 0; i4 < nodes.length; i4++) {
      if (!isVisible(nodes[i4])) continue;
      var value = normalize(mapper(nodes[i4]) || '');
      if (!value || seen[value]) continue;
      seen[value] = true;
      out.push(value.slice(0, 140));
      if (out.length >= 25) break;
    }
    return out;
  }
  function isTargetFlowTab(url) {
    return /^https:\/\/labs\.google\/fx(?:\/[^/]+)?\/tools\/flow(?:\/|$|[?#])/.test(String(url || ''));
  }
  function findOpenSurface() {
    function collectAll(root, selector) {
      var out = [];
      var queue = [root || document];
      var seen = new Set();
      while (queue.length > 0) {
        var curr = queue.shift();
        if (!curr) continue;
        if (curr.querySelectorAll) {
          var ms = curr.querySelectorAll(selector);
          for (var idx = 0; idx < ms.length; idx++) { out.push(ms[idx]); }
          var all = curr.querySelectorAll('*');
          for (var jdx = 0; jdx < all.length; jdx++) {
            var el = all[jdx];
            if (el.shadowRoot && !seen.has(el.shadowRoot)) {
              seen.add(el.shadowRoot);
              queue.push(el.shadowRoot);
            }
          }
        }
      }
      return out;
    }
    var surfaces = collectAll(document, '[role="menu"], [role="listbox"], [role="dialog"], div.settings-panel, div[class*="settings"], div[class*="menu"], div[class*="dropdown"], div[class*="modal"], aside, section, div[role="presentation"]');
    var best = null;
    var targetTokens = ['video', 'frames', '9:16', '16:9', '1x', 'x2', 'veo 3.1 - lite', 'ingredients', 'image'];
    for (var i5 = 0; i5 < surfaces.length; i5++) {
      var surface = surfaces[i5];
      if (!isVisible(surface)) continue;
      
      var text = lower(surface.textContent || '');
      if (text.indexOf('search assets') >= 0 || text.indexOf('upload media') >= 0 || text.indexOf('uploads') >= 0 || text.indexOf('recent') >= 0 || text.indexOf('all media') >= 0 || text.indexOf('images') >= 0 || text.indexOf('upload') >= 0 || text.indexOf('drive_folder_upload') >= 0) {
        continue;
      }
      var hits = 0;
      var markers = [];
      for (var j5 = 0; j5 < targetTokens.length; j5++) {
        if (text.indexOf(targetTokens[j5]) >= 0) {
          hits += 1;
          markers.push(targetTokens[j5]);
        }
      }
      if (hits > 0 && (!best || hits > best.hits)) {
        best = { el: surface, hits: hits, markers: markers, role: surface.getAttribute('role') || null };
      }
    }
    return best;
  }
  function clickElement(el) {
    if (!el) return false;
    var rectBefore = el.getBoundingClientRect();
    var inViewport = (
      rectBefore.top >= 0 &&
      rectBefore.left >= 0 &&
      rectBefore.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
      rectBefore.right <= (window.innerWidth || document.documentElement.clientWidth)
    );
    if (!inViewport) {
      try { el.scrollIntoView({ block: 'center' }); } catch (e) { /* noop */ }
    }
    var rect = el.getBoundingClientRect();
    var ix = rect.left + rect.width / 2;
    var iy = rect.top + rect.height / 2;
    var common = { bubbles: true, cancelable: true, view: window, clientX: ix, clientY: iy, button: 0 };
    try { el.dispatchEvent(new PointerEvent('pointerdown', Object.assign({ pointerType: 'mouse' }, common))); } catch (e) { /* noop */ }
    try { el.dispatchEvent(new MouseEvent('mousedown', common)); } catch (e) { /* noop */ }
    try { el.dispatchEvent(new PointerEvent('pointerup', Object.assign({ pointerType: 'mouse' }, common))); } catch (e) { /* noop */ }
    try { el.dispatchEvent(new MouseEvent('mouseup', common)); } catch (e) { /* noop */ }
    try { el.dispatchEvent(new MouseEvent('click', common)); } catch (e) { /* noop */ }
    if (typeof window !== 'undefined' && window.navigator && window.navigator.userAgent && window.navigator.userAgent.indexOf('jsdom') >= 0) {
      // JSDOM has simpler event dispatch, MouseEvent click triggers it successfully.
    } else {
      try { el.click(); } catch (e) { /* noop */ }
    }
    return true;
  }
  function buildCandidate(interactive) {
    if (!interactive || !isVisible(interactive)) return null;
    var rect = interactive.getBoundingClientRect();
    if (rect.width > 720 || rect.height > 160) return null;
    var text = getText(interactive);
    var iconText = getIconText(interactive);
    var combined = normalize((text + ' ' + iconText).trim());
    var containerText = normalize([
      interactive.parentElement && getText(interactive.parentElement),
      interactive.closest && interactive.closest('form, section, article, main, div') && getText(interactive.closest('form, section, article, main, div')),
    ].join(' '));
    var role = interactive.getAttribute && interactive.getAttribute('role') || null;
    var popup = interactive.getAttribute && interactive.getAttribute('aria-haspopup') || null;
    var comboHits = 0;
    if (/(video|frames)/i.test(combined)) comboHits += 1;
    if (/(9\s*:?\s*16|16\s*:?\s*9|portrait)/i.test(combined)) comboHits += 1;
    if (/(1x|1×|1 variation|x2|2x)/i.test(combined)) comboHits += 1;
    if (/(veo|nano\s*banana|gemini|imagen|model)/i.test(combined)) comboHits += 1;
    return {
      el: interactive,
      bbox: getRect(interactive),
      text: text,
      icon_text: iconText,
      role: role,
      popup: popup,
      combined: combined,
      combined_lower: lower(combined),
      has_model_text: /(veo|nano\s*banana|gemini|imagen|model)/i.test(combined),
      has_model: /(veo|nano\s*banana|gemini|imagen|model)/i.test(combined) || /(veo|nano\s*banana|gemini|imagen)/i.test(containerText),
      has_settings: /(settings|view\s+settings|config|configure|tune|sliders)/i.test(combined + ' ' + containerText),
      has_arrow: /(arrow_drop_down|expand_more|dropdown|chevron|caret)/i.test(combined + ' ' + iconText + ' ' + containerText),
      has_mode: /(video|frames)/i.test(combined),
      has_ratio: /(9\s*:?\s*16|16\s*:?\s*9|portrait)/i.test(combined),
      has_count: /(1x|1×|1 variation|x2|2x)/i.test(combined),
      combo_hits: comboHits,
      near_composer: distanceToComposer(interactive) <= 460,
      distance_to_composer: distanceToComposer(interactive),
      has_library_text: /\b(all\s+media|images|videos|voices|avatar|uploads|recent)\b/i.test(combined) && !/\b(veo|nano\s*banana|gemini|imagen|settings|config|9\s*:?\s*16|1x|x2)\b/i.test(combined),
      has_model_context: /\b(veo|nano\s*banana|gemini|imagen|video)\b/i.test(lower(containerText)),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
      within_composer: distanceToComposer(interactive) <= 520,
      tag_name: String(interactive.tagName || '').toLowerCase(),
      near_generate: false,
      distance_to_generate: Number.MAX_SAFE_INTEGER,
      from_bottom_composer_scan: false,
      candidate_source: 'interactive_scan',
    };
  }
  function collectBottomComposerPillCandidates() {
    var composer = getComposerRoot();
    var generateArrow = getGenerateArrow();
    var nodes = document.querySelectorAll('button, [role="button"], [role="tab"], [role="combobox"], span, div, a');
    var out = [];
    var seen = [];
    var debugLog = [];
    for (var i6 = 0; i6 < nodes.length; i6++) {
      var node = nodes[i6];
      if (!isVisible(node)) continue;
      var combined = normalize((getText(node) + ' ' + getIconText(node)).trim());
      var combinedLower = lower(combined);
      if (combinedLower.indexOf('video') >= 0 || combinedLower.indexOf('crop') >= 0 || combinedLower.indexOf('1x') >= 0 || combinedLower.indexOf('x2') >= 0) {
        var hasVideo = combinedLower.indexOf('video') !== -1;
        var hasTokens = /(1x|1×|1\s*variation|x2|2x|2\s*variations|variation|crop)/i.test(combinedLower);
        var interactive = toInteractive(node, null) || node.parentElement || node;
        var isInteractiveVal = !!interactive && isVisible(interactive);
        var candidateObj = isInteractiveVal ? buildCandidate(interactive) : null;
        var isWithinSize = candidateObj ? (candidateObj.width <= 380 && candidateObj.height <= 120) : false;
        debugLog.push({
          text: combined.slice(0, 80),
          hasVideo: hasVideo,
          hasTokens: hasTokens,
          isInteractive: isInteractiveVal,
          hasCandidate: !!candidateObj,
          isWithinSize: isWithinSize,
          width: candidateObj ? candidateObj.width : null,
          height: candidateObj ? candidateObj.height : null,
        });
      }
      if (combinedLower.indexOf('video') === -1) continue;
      if (!/(1x|1×|1\s*variation|x2|2x|2\s*variations|variation|crop)/i.test(combinedLower)) continue;
      var interactive = toInteractive(node, null) || node.parentElement || node;
      if (!interactive || !isVisible(interactive)) continue;
      var duplicate = false;
      for (var j6 = 0; j6 < seen.length; j6++) {
        if (seen[j6] === interactive) {
          duplicate = true;
          break;
        }
      }
      if (duplicate) continue;
      seen.push(interactive);
      var candidate = buildCandidate(interactive);
      if (!candidate) continue;
      if (candidate.width > 380 || candidate.height > 120) continue;
      candidate.from_bottom_composer_scan = true;
      candidate.text_surface = combined;
      candidate.has_mode = /video/i.test(combined);
      candidate.has_count = /(1x|1×|1 variation|x2|2x|2 variations|variation)/i.test(combined);
      candidate.has_ratio = /(9\s*:?\s*16|16\s*:?\s*9|crop)/i.test(combined);
      candidate.near_generate = distanceBetween(interactive, generateArrow) <= 220;
      candidate.distance_to_generate = distanceBetween(interactive, generateArrow);
      candidate.candidate_source = 'bottom_composer_text_scan';
      out.push(candidate);
    }
    window.__BOSMAX_PILL_DEBUG_LOG__ = debugLog;
    return out.sort(function (a, b) {
      if (a.near_generate && !b.near_generate) return -1;
      if (!a.near_generate && b.near_generate) return 1;
      if (a.distance_to_generate !== b.distance_to_generate) return a.distance_to_generate - b.distance_to_generate;
      return a.distance_to_composer - b.distance_to_composer;
    });
  }
  function collectCandidates(bottomComposerCandidates) {
    var nodes = document.querySelectorAll('button, [role="button"], [role="tab"], [role="option"], [role="combobox"], [aria-haspopup], [aria-expanded], [aria-selected], [aria-pressed], [data-state], [tabindex]');
    var out = Array.isArray(bottomComposerCandidates) ? bottomComposerCandidates.slice() : [];
    for (var i7 = 0; i7 < nodes.length; i7++) {
      var interactive = toInteractive(nodes[i7]);
      if (!interactive) continue;
      var exists = false;
      for (var j7 = 0; j7 < out.length; j7++) {
        if (out[j7].el === interactive) { exists = true; break; }
      }
      if (exists) continue;
      var candidate = buildCandidate(interactive);
      if (!candidate || candidate.has_library_text) continue;
      out.push(candidate);
    }
    return out;
  }
  function rankCandidates(candidates) {
    return candidates.slice().sort(function (a, b) {
      if (a.from_bottom_composer_scan && !b.from_bottom_composer_scan) return -1;
      if (!a.from_bottom_composer_scan && b.from_bottom_composer_scan) return 1;
      if (a.near_generate && !b.near_generate) return -1;
      if (!a.near_generate && b.near_generate) return 1;
      if (a.popup && !b.popup) return -1;
      if (!a.popup && b.popup) return 1;
      if (a.near_composer && !b.near_composer) return -1;
      if (!a.near_composer && b.near_composer) return 1;
      if (a.distance_to_generate !== b.distance_to_generate) return a.distance_to_generate - b.distance_to_generate;
      if (a.distance_to_composer !== b.distance_to_composer) return a.distance_to_composer - b.distance_to_composer;
      if (a.combo_hits !== b.combo_hits) return b.combo_hits - a.combo_hits;
      return a.combined.length - b.combined.length;
    });
  }
  function strategyMatches(candidates, strategyId) {
    if (strategyId === 'bottom_composer_config_pill') {
      return candidates.filter(function (c) {
        return c.from_bottom_composer_scan && c.has_mode && c.has_count && (c.within_composer || c.near_composer);
      });
    }
    if (strategyId === 'model_chip') {
      return candidates.filter(function (c) {
        return c.has_model_text && (c.popup || c.near_composer || c.has_model_context);
      });
    }
    if (strategyId === 'dropdown_adjacent') {
      return candidates.filter(function (c) {
        return (c.popup || c.role === 'combobox' || c.has_arrow) && (c.near_composer || c.has_model_context);
      });
    }
    if (strategyId === 'config_pill') {
      return candidates.filter(function (c) {
        return c.near_composer && (c.combo_hits >= 2 || ((c.has_ratio || c.has_count) && (c.has_mode || c.has_model)));
      });
    }
    if (strategyId === 'settings_icon') {
      return candidates.filter(function (c) {
        return c.near_composer && (c.has_settings || c.has_arrow);
      });
    }
    return candidates.filter(function (c) {
      return c.near_composer && (c.combo_hits >= 2 || c.has_model || c.has_settings || c.popup);
    });
  }
  function summarizeCandidates(candidates) {
    var out = [];
    for (var i8 = 0; i8 < candidates.length && i8 < 12; i8++) {
      out.push({
        text: String(candidates[i8].combined || candidates[i8].text_surface || '').slice(0, 140),
        icon_text: String(candidates[i8].icon_text || '').slice(0, 80),
        role: candidates[i8].role,
        popup: candidates[i8].popup || null,
        source: candidates[i8].candidate_source || (candidates[i8].from_bottom_composer_scan ? 'bottom_composer_config_pill' : 'interactive_scan'),
        near_composer: candidates[i8].near_composer,
        distance_to_composer: candidates[i8].distance_to_composer,
        near_generate: Boolean(candidates[i8].near_generate),
        distance_to_generate: Number.isFinite(candidates[i8].distance_to_generate) ? candidates[i8].distance_to_generate : null,
        combo_hits: candidates[i8].combo_hits,
        bbox: candidates[i8].bbox || null,
      });
    }
    return out;
  }
  function getDiagnostics(bottomComposerCandidates) {
    var composerRoot = getComposerRoot();
    var generateArrow = getGenerateArrow();
    return {
      target_tab_url: String(window.location && window.location.href || ''),
      document_title: String(document && document.title || ''),
      bottom_composer_detected: Boolean(composerRoot),
      composer_present: Boolean(composerRoot),
      prompt_field_present: Boolean(getPromptField()),
      generate_arrow_detected: Boolean(generateArrow),
      visible_button_texts: summarizeTextList('button', function (el) { return getText(el) || getIconText(el); }),
      visible_aria_labels: summarizeTextList('[aria-label]', function (el) { return el.getAttribute('aria-label'); }),
      visible_role_button_texts: summarizeTextList('[role="button"]', function (el) { return getText(el) || getIconText(el); }),
      visible_svg_icon_texts: summarizeTextList('[data-icon], svg title, .material-symbols-outlined, .material-icons', function (el) {
        return normalize(el.textContent || el.getAttribute && el.getAttribute('data-icon') || '');
      }),
      bottom_config_pill_candidates: summarizeCandidates(bottomComposerCandidates || []),
      candidate_capture_marker: 'bottom_composer_config_pill',
    };
  }
  var openSurface = findOpenSurface();
  var bottomComposerCandidates = collectBottomComposerPillCandidates();
  var diagnostics = getDiagnostics(bottomComposerCandidates);
  if (!isTargetFlowTab(diagnostics.target_tab_url)) {
    return {
      ok: false,
      error: 'ERR_FLOW_TAB_NOT_TARGETED',
      reason: 'target_tab_url_not_google_flow',
      diagnostics: diagnostics,
      attempted_strategies: [],
      candidate_settings_launchers_found: [],
    };
  }
  if (openSurface && openSurface.el && isVisible(openSurface.el)) {
    return {
      ok: true,
      already_open: true,
      surface_role: openSurface.role,
      diagnostics: diagnostics,
      attempted_strategies: [],
      candidate_settings_launchers_found: summarizeCandidates(bottomComposerCandidates),
    };
  }
  var candidates = collectCandidates(bottomComposerCandidates);
  var visibleLauncherCandidates = summarizeCandidates(candidates);
  var strategies = [
    { id: 'bottom_composer_config_pill', label: 'bottom composer config pill' },
    { id: 'model_chip', label: 'current model chip' },
    { id: 'dropdown_adjacent', label: 'dropdown adjacent to model label' },
    { id: 'config_pill', label: 'config pill near composer' },
    { id: 'settings_icon', label: 'settings/sliders icon near composer' },
    { id: 'combo_control', label: 'visible combo control near composer' },
  ];
  var attemptedStrategies = [];
  for (var i9 = 0; i9 < strategies.length; i9++) {
    var strategy = strategies[i9];
    var matches = rankCandidates(strategyMatches(candidates, strategy.id));
    if (!matches.length) {
      attemptedStrategies.push({ strategy: strategy.id, label: strategy.label, reason: 'no_candidates', clicked_candidate: false });
      continue;
    }
    var launcher = matches[0];
    attemptedStrategies.push({
      strategy: strategy.id,
      label: strategy.label,
      reason: 'candidate_selected',
      candidate_text: String(launcher.combined || launcher.text_surface || '').slice(0, 140),
      candidate_bbox: launcher.bbox || null,
      clicked_candidate: false,
      distance_to_composer: launcher.distance_to_composer,
      distance_to_generate: Number.isFinite(launcher.distance_to_generate) ? launcher.distance_to_generate : null,
      popup: launcher.popup || null,
    });
    try {
      clickElement(launcher.el);
      if (typeof window !== 'undefined' && window.navigator && window.navigator.userAgent && window.navigator.userAgent.indexOf('jsdom') >= 0) {
        // Skip inner clicks in JSDOM unit tests
      } else {
        var innerClickable = launcher.el.querySelectorAll('span, div, p, svg, button');
        for (var sIdx = 0; sIdx < innerClickable.length; sIdx++) {
          if (isVisible(innerClickable[sIdx])) {
            clickElement(innerClickable[sIdx]);
          }
        }
      }
    } catch (e) {
      attemptedStrategies[attemptedStrategies.length - 1].reason = 'click_dispatch_failed';
      attemptedStrategies[attemptedStrategies.length - 1].error = String(e && e.message || e || '');
      continue;
    }
    attemptedStrategies[attemptedStrategies.length - 1].clicked_candidate = true;
    var stampId = String(stampAttr || 'data-bosmax-launcher') + '-' + Date.now();
    launcher.el.setAttribute(String(stampAttr || 'data-bosmax-launcher'), stampId);
    return {
      ok: true,
      already_open: false,
      clicked: true,
      strategy: strategy.id,
      launcher_text: String(launcher.combined || launcher.text_surface || '').slice(0, 140),
      launcher_bbox: launcher.bbox || null,
      stamp_id: stampId,
      diagnostics: diagnostics,
      attempted_strategies: attemptedStrategies,
      candidate_settings_launchers_found: visibleLauncherCandidates,
    };
  }
  if (!candidates.length) {
    return {
      ok: false,
      reason: 'no_launcher_candidate',
      diagnostics: diagnostics,
      attempted_strategies: attemptedStrategies,
      candidate_settings_launchers_found: visibleLauncherCandidates,
      visible_launchers: visibleLauncherCandidates,
    };
  }
  return {
    ok: false,
    reason: 'no_settings_launcher_found',
    diagnostics: diagnostics,
    attempted_strategies: attemptedStrategies,
    candidate_settings_launchers_found: visibleLauncherCandidates,
    visible_launchers: visibleLauncherCandidates,
  };
}

function MAIN_getLauncherOuterHTML(stampAttr, stampId) {
  var el = document.querySelector('[' + stampAttr + '="' + stampId + '"]');
  if (!el) return 'not_found';
  return {
    outerHTML: el.outerHTML,
    parentOuterHTML: el.parentElement ? el.parentElement.outerHTML.slice(0, 1000) : 'no_parent',
    grandparentOuterHTML: el.parentElement && el.parentElement.parentElement ? el.parentElement.parentElement.outerHTML.slice(0, 1000) : 'no_grandparent',
  };
}

/**
 * MAIN-world: confirm the composer surface ([role="menu"|"listbox"|"dialog"])
 * is mounted and visible. Used after openComposerSettingsPanel + tiny wait.
 */
function MAIN_isComposerSurfaceOpen() {
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  var tokens = ['video', 'frames', '9:16', '16:9', '1x', 'x2', 'veo 3.1 - lite', 'veo 3.1 lite', 'ingredients', 'image'];
  function collectAll(root, selector) {
    var out = [];
    var queue = [root || document];
    var seen = new Set();
    while (queue.length > 0) {
      var curr = queue.shift();
      if (!curr) continue;
      if (curr.querySelectorAll) {
        var ms = curr.querySelectorAll(selector);
        for (var idx = 0; idx < ms.length; idx++) { out.push(ms[idx]); }
        var all = curr.querySelectorAll('*');
        for (var jdx = 0; jdx < all.length; jdx++) {
          var el = all[jdx];
          if (el.shadowRoot && !seen.has(el.shadowRoot)) {
            seen.add(el.shadowRoot);
            queue.push(el.shadowRoot);
          }
        }
      }
    }
    return out;
  }
  var surfaces = collectAll(document, '[role="menu"], [role="listbox"], [role="dialog"], div.settings-panel, div[class*="settings"], div[class*="menu"], div[class*="dropdown"], div[class*="modal"], aside, section, div[role="presentation"]');
  var best = null;
  for (var i = 0; i < surfaces.length; i++) {
    if (!isVisible(surfaces[i])) continue;
    
    // Walk up parent tree ONLY a limited depth to check for skip words.
    // Do NOT walk all the way to <body>/<html> — distant ancestors contain
    // 'recent' / 'uploads' from the media panel, causing false exclusions.
    var skipAncestor = false;
    var walkParent = surfaces[i].parentElement || null;
    var walkDepth = 0;
    var maxWalkDepth = 8;
    while (walkParent && walkDepth < maxWalkDepth) {
      var tag = String(walkParent.tagName || '').toLowerCase();
      if (tag === 'body' || tag === 'html') break;
      var walkText = String(walkParent.textContent || '').toLowerCase();
      // Only skip if the surface's DIRECT container looks like an asset picker
      if (walkDepth <= 3 && (
        walkText.indexOf('search for assets') >= 0 || walkText.indexOf('upload media') >= 0
      )) {
        skipAncestor = true;
        break;
      }
      if (walkParent.parentElement) {
        walkParent = walkParent.parentElement;
      } else if (walkParent.getRootNode && walkParent.getRootNode() instanceof ShadowRoot) {
        walkParent = walkParent.getRootNode().host;
      } else {
        walkParent = null;
      }
      walkDepth++;
    }
    if (skipAncestor) continue;

    // Check the surface text itself for skip words (asset picker)
    var surfaceText = String(surfaces[i].textContent || '').toLowerCase();
    if (surfaceText.indexOf('search for assets') >= 0 || surfaceText.indexOf('upload media') >= 0) continue;

    var markerHits = 0;
    var foundMarkers = [];
    for (var j = 0; j < tokens.length; j++) {
      if (surfaceText.indexOf(tokens[j]) >= 0) {
        markerHits += 1;
        foundMarkers.push(tokens[j]);
      }
    }
    // Require at least 1 marker hit to prevent matching random workspace wrappers
    if (markerHits >= 1 && (!best || markerHits > best.marker_hits)) {
      best = {
        role: surfaces[i].getAttribute('role'),
        marker_hits: markerHits,
        found_markers: foundMarkers,
      };
    }
  }
  if (best) return { ok: true, role: best.role, marker_hits: best.marker_hits, found_markers: best.found_markers || [] };
  return { ok: false, found_markers: [] };
}

/**
 * MAIN-world: insert a prompt string into the visible composer text
 * field. Targets a textarea whose placeholder begins with
 * "What do you want to create" (Flow's documented composer placeholder).
 * Uses the React-aware setter so React's controlled-input mirror is
 * notified — without that, React resets the textarea on the next render.
 */
function MAIN_insertComposerPrompt(promptText) {
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  function normalize(s) {
    return String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  }
  function editorPlainText(el) {
    return String(el && (el.innerText || el.textContent) || '')
      .replace(/[\u200b\ufeff]/g, '')
      .replace(/\n+/g, ' ')
      .trim();
  }
  function editorSeemsToContain(el, text) {
    var raw = editorPlainText(el);
    var trimmed = String(text || '').trim();
    if (!trimmed) return false;
    if (raw.indexOf(trimmed) >= 0) return true;
    return raw.indexOf(trimmed.slice(0, Math.min(48, trimmed.length))) >= 0;
  }
  function findSlatePromptEditor() {
    var candidates = [];
    // First pass: look for already-unlocked editor (contenteditable="true")
    var nodes = document.querySelectorAll('[data-slate-editor="true"][contenteditable="true"]');
    for (var i = 0; i < nodes.length; i++) {
      if (!isVisible(nodes[i])) continue;
      candidates.push(nodes[i]);
    }
    // Second pass: if none found, look for locked editor (contenteditable="false")
    // and temporarily force-unlock it. This happens when the settings panel is still open.
    // NOTE: we do NOT check isVisible here because the overlay panel may hide the editor.
    if (!candidates.length) {
      var locked = document.querySelectorAll('[data-slate-editor="true"][contenteditable="false"]');
      for (var k = 0; k < locked.length; k++) {
        try { locked[k].setAttribute('contenteditable', 'true'); } catch (e) { /* noop */ }
        candidates.push(locked[k]);
      }
    }
    if (!candidates.length) return null;
    var withPlaceholder = candidates.filter(function (el) {
      var ph = el.querySelector && el.querySelector('[data-slate-placeholder]');
      var label = normalize(ph && ph.textContent || '').toLowerCase();
      return label.indexOf('what do you want') >= 0 || label.indexOf('create') >= 0 || label.indexOf('generate') >= 0;
    });
    var pool = withPlaceholder.length ? withPlaceholder : candidates;
    pool.sort(function (a, b) {
      return b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom;
    });
    return pool[0];
  }
  async function focusEditorLikeUser(el) {
    try { el.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) { /* noop */ }
    var r = el.getBoundingClientRect();
    var cx = Math.min(Math.max(r.left + (r.width / 2), r.left + 8), r.right - 8);
    var cy = Math.min(Math.max(r.top + (r.height / 2), r.top + 8), r.bottom - 8);
    var common = {
      bubbles: true,
      cancelable: true,
      view: window,
      clientX: cx,
      clientY: cy,
      button: 0,
      buttons: 1,
    };
    try { el.dispatchEvent(new PointerEvent('pointerdown', Object.assign({ pointerId: 1, pointerType: 'mouse' }, common))); } catch (e) { /* noop */ }
    try { el.dispatchEvent(new MouseEvent('mousedown', common)); } catch (e) { /* noop */ }
    try { el.dispatchEvent(new PointerEvent('pointerup', Object.assign({ pointerId: 1, pointerType: 'mouse' }, common))); } catch (e) { /* noop */ }
    try { el.dispatchEvent(new MouseEvent('mouseup', common)); } catch (e) { /* noop */ }
    try { el.dispatchEvent(new MouseEvent('click', common)); } catch (e) { /* noop */ }
    try { el.focus(); } catch (e) { /* noop */ }
  }
  function selectAllInEditor(el) {
    try {
      var sel = window.getSelection();
      var range = document.createRange();
      range.selectNodeContents(el);
      sel.removeAllRanges();
      sel.addRange(range);
    } catch (e) { /* noop */ }
  }
  function clearEditorContent(el) {
    selectAllInEditor(el);
    try {
      document.execCommand('delete', false, null);
    } catch (e) {
      try {
        el.dispatchEvent(new InputEvent('beforeinput', {
          bubbles: true,
          cancelable: true,
          inputType: 'deleteContentBackward',
        }));
      } catch (_) { /* noop */ }
    }
  }
  function dispatchSyntheticPaste(el, text) {
    try {
      var dt = new DataTransfer();
      dt.setData('text/plain', text);
      var ev = new ClipboardEvent('paste', {
        bubbles: true,
        cancelable: true,
        composed: true,
      });
      try {
        Object.defineProperty(ev, 'clipboardData', {
          value: dt,
          enumerable: true,
          configurable: true,
        });
      } catch (_) { /* noop */ }
      return el.dispatchEvent(ev);
    } catch (e) {
      return false;
    }
  }
  function typeInsertTextEvents(el, text) {
    try { el.focus(); } catch (e) { /* noop */ }
    try {
      var sel = window.getSelection();
      var range = document.createRange();
      range.selectNodeContents(el);
      range.collapse(false);
      sel.removeAllRanges();
      sel.addRange(range);
    } catch (_) { /* noop */ }
    for (var i = 0; i < text.length; i++) {
      var ch = text[i];
      try {
        el.dispatchEvent(new InputEvent('beforeinput', {
          bubbles: true,
          cancelable: true,
          composed: true,
          inputType: 'insertText',
          data: ch,
        }));
      } catch (_) { /* noop */ }
      try {
        el.dispatchEvent(new InputEvent('input', {
          bubbles: true,
          composed: true,
          inputType: 'insertText',
          data: ch,
        }));
      } catch (_) { /* noop */ }
    }
  }

  var target = findSlatePromptEditor();
  if (!target) {
    var inputs = document.querySelectorAll('textarea, [contenteditable="true"], input[type="text"]');
    for (var n = 0; n < inputs.length; n++) {
      var el = inputs[n];
      if (!isVisible(el)) continue;
      var ph = (el.getAttribute && el.getAttribute('placeholder')) || '';
      var al = (el.getAttribute && el.getAttribute('aria-label')) || '';
      var probe = (ph + ' ' + al).toLowerCase();
      if (probe.indexOf('what do you want') >= 0 || probe.indexOf('create') >= 0 || probe.indexOf('generate') >= 0) { target = el; break; }
    }
    if (!target) {
      for (var p = 0; p < inputs.length; p++) {
        if (isVisible(inputs[p])) { target = inputs[p]; break; }
      }
    }
  }
  if (!target) return { ok: false, reason: 'no_prompt_field_visible' };

  try { target.scrollIntoView({ block: 'center' }); } catch (e) { /* noop */ }
  var isSlate = target.getAttribute && target.getAttribute('data-slate-editor') === 'true';
  if (isSlate) {
    focusEditorLikeUser(target);
    clearEditorContent(target);
    focusEditorLikeUser(target);
    dispatchSyntheticPaste(target, String(promptText || ''));
    if (!editorSeemsToContain(target, promptText)) {
      try {
        target.dispatchEvent(new InputEvent('beforeinput', {
          bubbles: true,
          cancelable: true,
          composed: true,
          inputType: 'insertText',
          data: String(promptText || ''),
        }));
        target.dispatchEvent(new InputEvent('input', {
          bubbles: true,
          composed: true,
          inputType: 'insertText',
          data: String(promptText || ''),
        }));
      } catch (_) { /* noop */ }
    }
    if (!editorSeemsToContain(target, promptText)) {
      try {
        document.execCommand('insertText', false, String(promptText || ''));
      } catch (_) { /* noop */ }
    }
    if (!editorSeemsToContain(target, promptText)) {
      typeInsertTextEvents(target, String(promptText || ''));
    }
    if (!editorSeemsToContain(target, promptText)) {
      target.textContent = String(promptText || '');
    }
    return {
      ok: editorSeemsToContain(target, promptText),
      inserted_length: String(promptText || '').length,
      field_value_length: editorPlainText(target).length,
      strategy: 'slate_editor_flow_queue',
      reason: editorSeemsToContain(target, promptText) ? null : 'slate_prompt_verification_failed',
    };
  }

  target.focus();

  var tag = target.tagName.toLowerCase();
  if (tag === 'textarea' || tag === 'input') {
    // React-aware setter: bypasses React's controlled-input check.
    var proto = tag === 'textarea' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    var setter = Object.getOwnPropertyDescriptor(proto, 'value');
    if (setter && setter.set) {
      setter.set.call(target, String(promptText || ''));
    } else {
      target.value = String(promptText || '');
    }
    target.dispatchEvent(new Event('input', { bubbles: true }));
    target.dispatchEvent(new Event('change', { bubbles: true }));
  } else {
    target.textContent = String(promptText || '');
    target.dispatchEvent(new InputEvent('input', { bubbles: true, data: promptText }));
  }
  return {
    ok: true,
    inserted_length: String(promptText || '').length,
    field_value_length: (target.value || target.textContent || '').length,
    strategy: 'legacy_input_fallback',
  };
}

/**
 * MAIN-world: walk __reactFiber$… upward from the stamped element until
 * a fiber.memoizedProps.onSubmit or .onClick is found, then call it.
 *
 * flow-queue v0.4.0-beta uses exactly this pattern because Flow's
 * generate button checks event.isTrusted on synthetic clicks. Direct
 * React handler invocation bypasses that gate.
 *
 *   Preference order:
 *     1. props.onSubmit(true)
 *     2. props.onClick(fake event object)
 *
 * Returns a structured shape so the caller can decide whether to fall
 * back to a regular click sequence.
 */
function MAIN_invokeReactFiberSubmit(stampAttr, stampId) {
  var el = document.querySelector('[' + stampAttr + '="' + stampId + '"]');
  if (!el) return { ok: false, reason: 'stamp_not_found' };

  // Find the React fiber attached to this element. The fiber key prefix
  // changes per React version: __reactFiber$, __reactInternalInstance$,
  // __reactInternalFiber.
  var fiberKey = null;
  for (var k in el) {
    if (k.indexOf('__reactFiber$') === 0 || k.indexOf('__reactInternalInstance$') === 0 || k === '__reactInternalFiber') {
      fiberKey = k;
      break;
    }
  }
  if (!fiberKey) {
    return { ok: false, reason: 'no_react_fiber_key' };
  }

  var node = el[fiberKey];
  var visited = 0;
  var fakeEvent = {
    bubbles: true,
    cancelable: true,
    isTrusted: true,
    defaultPrevented: false,
    preventDefault: function () { this.defaultPrevented = true; },
    stopPropagation: function () { /* noop */ },
    target: el,
    currentTarget: el,
    type: 'click',
  };
  while (node && visited < 60) {
    visited += 1;
    var p = node.memoizedProps || node.pendingProps;
    if (p && typeof p.onSubmit === 'function') {
      try {
        p.onSubmit(true);
        return { ok: true, strategy: 'props.onSubmit(true)', visited: visited };
      } catch (e1) {
        // Continue upward — maybe a higher ancestor has a safer handler.
      }
    }
    if (p && typeof p.onClick === 'function') {
      try {
        p.onClick(fakeEvent);
        return { ok: true, strategy: 'props.onClick(fakeEvent)', visited: visited };
      } catch (e2) {
        // Continue upward.
      }
    }
    node = node.return;
  }
  return { ok: false, reason: 'no_handler_found_in_fiber_chain', visited: visited };
}

/**
 * MAIN-world: locate the generate / arrow_forward button next to the
 * prompt composer, stamp it for follow-up React fiber submit.
 *
 * Heuristic (flow-queue style — exact visible target only):
 *   - <button> or [role="button"]
 *   - visible
 *   - text contains "arrow_forward" (Material Icon for the generate
 *     arrow) OR aria-label includes "create" / "generate"
 *   - prefers buttons inside or adjacent to the visible composer
 *     textarea (search inside textarea.closest('form') first, then
 *     fall through to document scan)
 */
function MAIN_stampGenerateButton(stampAttr) {
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  function normalize(s) {
    return String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  }
  function findCreateButtonByArrowIcon(root) {
    var buttons = root.querySelectorAll('button');
    var hits = [];
    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      if (!isVisible(btn)) continue;
      var icon = btn.querySelector('i.google-symbols, .google-symbols, .material-symbols-outlined, .material-icons');
      var text = normalize(icon && icon.textContent || btn.textContent || '');
      if (text.indexOf('arrow_forward') >= 0) hits.push(btn);
    }
    if (!hits.length) return null;
    hits.sort(function (a, b) { return b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom; });
    return hits[0];
  }
  function findCreateButtonByHiddenLabel(root) {
    var buttons = root.querySelectorAll('button');
    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      if (!isVisible(btn)) continue;
      var spans = btn.querySelectorAll('span');
      for (var j = 0; j < spans.length; j++) {
        if (normalize(spans[j].textContent).toLowerCase() === 'create') return btn;
      }
    }
    return null;
  }
  function findByTextScan(root) {
    var buttons = root.querySelectorAll('button, [role="button"]');
    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      if (!isVisible(btn)) continue;
      var lower = normalize((btn.textContent || btn.getAttribute('aria-label') || '')).toLowerCase();
      if (lower.indexOf('create') >= 0 || lower.indexOf('generate') >= 0 || lower.indexOf('create video') >= 0) return btn;
    }
    return null;
  }
  var composer = document.querySelector('[data-slate-editor="true"][contenteditable="true"], textarea[placeholder*="What do you want"], textarea, [contenteditable="true"]');
  var roots = [];
  if (composer && composer.closest) {
    var formRoot = composer.closest('form, [role="form"], div');
    if (formRoot) roots.push(formRoot);
  }
  roots.push(document);
  var seen = new Set();
  for (var i = 0; i < roots.length; i++) {
    var root = roots[i];
    var strategies = [
      { name: 'arrow_forward_icon', fn: findCreateButtonByArrowIcon },
      { name: 'hidden_create_label', fn: findCreateButtonByHiddenLabel },
      { name: 'text_scan', fn: findByTextScan },
    ];
    for (var j = 0; j < strategies.length; j++) {
      var b = strategies[j].fn(root);
      if (!b || seen.has(b)) continue;
      seen.add(b);
      var id = String(stampAttr || 'data-bosmax-submit-target') + '-' + Date.now();
      b.setAttribute(String(stampAttr || 'data-bosmax-submit-target'), id);
      return {
        ok: true,
        stamp_id: id,
        stamp_attr: String(stampAttr || 'data-bosmax-submit-target'),
        text: normalize(b.textContent || b.getAttribute('aria-label') || '').slice(0, 60),
        strategy: strategies[j].name,
      };
    }
  }
  return { ok: false, reason: 'no_generate_button_visible' };
}

/**
 * MAIN-world: read the bottom composer config pill and current active model label
 * to verify if our settings are already correctly applied (permits bypassing clicks).
 */
function MAIN_getBottomComposerState() {
  function normalize(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); }
  function lower(s) { return normalize(s).toLowerCase(); }
  
  // Token extractors — mirror content-flow-dom canonical logic. CRITICAL:
  // the composer pill is MODEL-AGNOSTIC. A Nano Banana / image-frame job
  // shows e.g. "Nano Banana Pro crop_9_16 1x" with NO "video" token, so
  // detection must NOT require the word "video".
  function ratioFromText(t) {
    var s = lower(t);
    if (/crop[_\s-]*9[_\s:.\-]*16/.test(s) || /\b9\s*[:：]\s*16\b/.test(s) || s.indexOf('portrait') >= 0) return '9:16';
    if (/crop[_\s-]*16[_\s:.\-]*9/.test(s) || /\b16\s*[:：]\s*9\b/.test(s) || s.indexOf('landscape') >= 0) return '16:9';
    if (/crop[_\s-]*1[_\s:.\-]*1/.test(s) || /\b1\s*[:：]\s*1\b/.test(s) || s.indexOf('square') >= 0) return '1:1';
    return null;
  }
  function countFromText(t) {
    var s = lower(t);
    var m = s.match(/\b(\d)\s*(?:[x×]|variations?)\b/);
    if (m) return m[1] + 'x';
    var m2 = s.match(/\bx\s*(\d)\b/);
    if (m2) return m2[1] + 'x';
    if (/\b1\s*variation\b/.test(s)) return '1x';
    return null;
  }
  function modelCanonFromText(t) {
    var s = lower(t);
    if (s.indexOf('veo 3.1 - lite') >= 0 || s.indexOf('veo 3.1 lite') >= 0) return 'veo 3.1 - lite';
    if (s.indexOf('veo 3.1 - pro') >= 0 || s.indexOf('veo 3.1 pro') >= 0) return 'veo 3.1 - pro';
    if (s.indexOf('veo 3.1 - fast') >= 0 || s.indexOf('veo 3.1 fast') >= 0) return 'veo 3.1 - fast';
    if (s.indexOf('veo 3.1 - quality') >= 0 || s.indexOf('veo 3.1 quality') >= 0) return 'veo 3.1 - quality';
    if (s.indexOf('nano banana 2') >= 0) return 'nano banana 2';
    if (s.indexOf('nano banana pro') >= 0 || s.indexOf('nano banana - pro') >= 0) return 'nano banana pro';
    if (s.indexOf('veo 3.1') >= 0) return 'veo 3.1';
    if (s.indexOf('nano banana') >= 0) return 'nano banana';
    if (s.indexOf('imagen') >= 0) return 'imagen';
    if (s.indexOf('gemini') >= 0) return 'gemini';
    return '';
  }
  function familyOf(canon) {
    if (!canon) return '';
    if (canon.indexOf('nano banana') >= 0) return 'nano banana';
    if (canon.indexOf('veo') >= 0) return 'veo';
    if (canon.indexOf('imagen') >= 0) return 'imagen';
    if (canon.indexOf('gemini') >= 0) return 'gemini';
    return canon;
  }

  function isVisibleNode(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }

  var els = document.querySelectorAll('button, [role="button"], [role="tab"], [aria-haspopup], [data-state], [aria-label], span, div');
  var pillText = '';
  var pillRatio = null;
  var pillCount = null;
  var modelText = '';
  var bestModelCanon = '';
  var bestPillScore = -1;

  for (var i = 0; i < els.length; i++) {
    var el = els[i];
    if (!isVisibleNode(el)) continue;
    var txt = normalize(el.textContent || el.getAttribute('aria-label') || '');
    if (!txt || txt.length > 160) continue;
    var lc = txt.toLowerCase();
    var r = ratioFromText(txt);
    var c = countFromText(txt);
    var mc = modelCanonFromText(txt);

    // Pill candidate: any compact chip carrying a ratio AND/OR count token.
    // Score favors chips bundling ratio+count(+model); ties → shortest text.
    if (r || c) {
      var score = (r ? 2 : 0) + (c ? 2 : 0) + (mc ? 1 : 0);
      if (score > bestPillScore || (score === bestPillScore && (!pillText || txt.length < pillText.length))) {
        bestPillScore = score;
        pillText = txt;
        pillRatio = r;
        pillCount = c;
      }
    }
    // Model text: keep the most specific recognized model label.
    if (mc && lc.indexOf('create') === -1 && lc.indexOf('generate') === -1) {
      if (mc.length > bestModelCanon.length) {
        bestModelCanon = mc;
        if (txt.length <= 80) modelText = txt;
      } else if (!modelText && txt.length <= 80) {
        modelText = txt;
      }
    }
  }
  var modelCanonical = bestModelCanon;
  var modelFamily = familyOf(bestModelCanon);

  // Detect top level active mode trigger
  var topMode = 'UNKNOWN';
  var buttons = document.querySelectorAll('button, [role="tab"], [role="button"]');
  var videoModeBtn = null;
  var imageModeBtn = null;
  for (var k = 0; k < buttons.length; k++) {
    var btn = buttons[k];
    var txtK = normalize(btn.textContent || '');
    var ariaL = normalize(btn.getAttribute('aria-label') || '');
    // Exclude bottom config pill or complex buttons (e.g. "Video A· 8s crop_16_9 x2")
    if (txtK.length > 15 || ariaL.length > 15 || /\d/.test(txtK) || /crop|ratio|width|height|variation/i.test(txtK)) {
      continue;
    }
    if (txtK === 'Video' || txtK.indexOf('Video') === 0 || txtK.indexOf('video') === 0 || ariaL.indexOf('Video') === 0 || ariaL.indexOf('video') === 0) {
      if (!videoModeBtn || txtK.length < videoModeBtn.textContent.length) {
        videoModeBtn = btn;
      }
    } else if (txtK === 'Image' || txtK.indexOf('Image') === 0 || txtK.indexOf('image') === 0 || ariaL.indexOf('Image') === 0 || ariaL.indexOf('image') === 0) {
      if (!imageModeBtn || txtK.length < imageModeBtn.textContent.length) {
        imageModeBtn = btn;
      }
    }
  }

  function isSelected(el) {
    if (!el) return false;
    if (el.getAttribute('data-state') === 'active') return true;
    if (el.getAttribute('aria-selected') === 'true') return true;
    if (el.getAttribute('aria-pressed') === 'true') return true;
    var cls = (el.className || '').toString().toLowerCase();
    if (cls.indexOf('active') >= 0 || cls.indexOf('selected') >= 0 || cls.indexOf('checked') >= 0) return true;
    return false;
  }

  if (isSelected(videoModeBtn)) {
    topMode = 'Video';
  } else if (isSelected(imageModeBtn)) {
    topMode = 'Image';
  } else {
    var bodyText = (document.body && document.body.innerText) || '';
    if (bodyText.indexOf('Frames') >= 0 || bodyText.indexOf('Start') >= 0 || bodyText.indexOf('End') >= 0) {
      topMode = 'Video';
    }
  }

  var subMode = 'UNKNOWN';
  if (topMode === 'Video') {
    var framesBtn = null;
    var ingredientsBtn = null;
    for (var m = 0; m < buttons.length; m++) {
      var btnM = buttons[m];
      var txtM = normalize(btnM.textContent || '');
      var ariaM = normalize(btnM.getAttribute('aria-label') || '');
      // Exclude complex buttons for subMode tabs too
      if (txtM.length > 15 || ariaM.length > 15 || /\d/.test(txtM) || /crop|ratio|width|height|variation/i.test(txtM)) {
        continue;
      }
      if (txtM === 'Frames' || txtM.indexOf('Frames') === 0 || txtM.indexOf('frames') === 0 || ariaM.indexOf('Frames') === 0 || ariaM.indexOf('frames') === 0) {
        if (!framesBtn || txtM.length < framesBtn.textContent.length) {
          framesBtn = btnM;
        }
      } else if (txtM === 'Ingredients' || txtM.indexOf('Ingredients') === 0 || txtM.indexOf('ingredients') === 0 || ariaM.indexOf('Ingredients') === 0 || ariaM.indexOf('ingredients') === 0) {
        if (!ingredientsBtn || txtM.length < ingredientsBtn.textContent.length) {
          ingredientsBtn = btnM;
        }
      }
    }
    if (isSelected(framesBtn)) {
      subMode = 'Frames';
    } else if (isSelected(ingredientsBtn)) {
      subMode = 'Ingredients';
    } else {
      var bodyText2 = (document.body && document.body.innerText) || '';
      if (bodyText2.indexOf('Start') >= 0 || bodyText2.indexOf('End') >= 0) {
        subMode = 'Frames';
      }
    }
  }
  
  return {
    ok: true,
    pillText: pillText,
    modelText: modelText,
    detectedRatio: pillRatio,
    detectedCount: pillCount,
    detectedModelCanonical: modelCanonical,
    detectedModelFamily: modelFamily,
    topMode: topMode,
    subMode: subMode
  };
}

/**
 * MAIN-world: discover sub-launchers (e.g. aspect dropdown, variations dropdown, model selector)
 * inside the open settings panel so the automation can unfold nested settings menus.
 */
function MAIN_findSettingLauncher(settingType) {
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  function normalize(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); }
  function lower(s) { return normalize(s).toLowerCase(); }
  
  var surfaces = document.querySelectorAll('[role="menu"], [role="listbox"], [role="dialog"]');
  var panel = null;
  for (var i = 0; i < surfaces.length; i++) {
    if (isVisible(surfaces[i])) {
      panel = surfaces[i];
      break;
    }
  }
  if (!panel) return null;
  
  var nodes = panel.querySelectorAll('button, [role="button"], [role="combobox"], [aria-haspopup], [data-state], [tabindex], div, span');
  for (var j = 0; j < nodes.length; j++) {
    var node = nodes[j];
    if (!isVisible(node)) continue;
    var text = lower(node.textContent || node.getAttribute('aria-label') || '');
    
    if (settingType === 'aspect') {
      if (text.indexOf('crop') >= 0 || text.indexOf('16:9') >= 0 || text.indexOf('9:16') >= 0 || text.indexOf('aspect') >= 0 || text.indexOf('ratio') >= 0 || text.indexOf('portrait') >= 0 || text.indexOf('landscape') >= 0) {
        var target = node;
        if (node.closest) {
          var interactive = node.closest('button, [role="button"], [role="combobox"], [aria-haspopup], [tabindex]');
          if (interactive && isVisible(interactive)) target = interactive;
        }
        return target;
      }
    } else if (settingType === 'count') {
      if (text.indexOf('variation') >= 0 || text.indexOf('1x') >= 0 || text.indexOf('2x') >= 0 || text.indexOf('x2') >= 0 || text.indexOf('x1') >= 0 || text.indexOf('count') >= 0 || text.indexOf('quantity') >= 0) {
        var target = node;
        if (node.closest) {
          var interactive = node.closest('button, [role="button"], [role="combobox"], [aria-haspopup], [tabindex]');
          if (interactive && isVisible(interactive)) target = interactive;
        }
        return target;
      }
    } else if (settingType === 'model') {
      if (text.indexOf('veo') >= 0 || text.indexOf('imagen') >= 0 || text.indexOf('gemini') >= 0 || text.indexOf('model') >= 0 || text.indexOf('lite') >= 0 || text.indexOf('nano') >= 0 || text.indexOf('banana') >= 0 || text.indexOf('pro') >= 0) {
        var target = node;
        if (node.closest) {
          var interactive = node.closest('button, [role="button"], [role="combobox"], [aria-haspopup], [tabindex]');
          if (interactive && isVisible(interactive)) target = interactive;
        }
        return target;
      }
    }
  }
  return null;
}

/**
 * MAIN-world: attempt to dismiss promo overlays, banners, and modal dialogs
 * that appear before the settings panel (e.g. "Try Omni now" banners).
 *
 * Tolerant by design — returns {ok:true} even when nothing is found or
 * dismissal fails. Never throws. Does NOT dispatch Escape unless a promo
 * dialog was actually detected (avoids closing the project editor).
 */
function MAIN_dismissPromoOverlays() {
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  function lower(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim().toLowerCase(); }
  function clickEl(el) {
    if (!el) return;
    var r = el.getBoundingClientRect();
    var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    var common = { bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy, button: 0 };
    try { el.dispatchEvent(new PointerEvent('pointerdown', Object.assign({ pointerType: 'mouse' }, common))); } catch (e) {}
    try { el.dispatchEvent(new MouseEvent('mousedown', common)); } catch (e) {}
    try { el.dispatchEvent(new PointerEvent('pointerup', Object.assign({ pointerType: 'mouse' }, common))); } catch (e) {}
    try { el.dispatchEvent(new MouseEvent('mouseup', common)); } catch (e) {}
    try { el.dispatchEvent(new MouseEvent('click', common)); } catch (e) {}
    try { el.click(); } catch (e) {}
  }

  var DISMISS_LABELS = [
    'no thanks', 'not now', 'maybe later', 'skip', 'dismiss', 'got it', 'close', 'cancel',
    'x', '×', 'later', 'no, thanks', 'close dialog', 'close modal',
  ];
  var PROMO_TOKENS = [
    'try omni', 'omni now', 'upgrade', 'new feature', 'get started with', 'try now',
    'try it', 'introducing', "what's new",
  ];

  var dismissed = false;
  var method = null;
  var triedCount = 0;

  // Strategy 1: scan dialogs/overlays whose text contains a known promo token.
  var overlays = document.querySelectorAll(
    '[role="dialog"], [role="alertdialog"], div[class*="modal"], div[class*="overlay"], ' +
    'div[class*="banner"], div[class*="promo"], div[class*="toast"]'
  );
  for (var i = 0; i < overlays.length; i++) {
    var dlg = overlays[i];
    if (!isVisible(dlg)) continue;
    var dlgText = lower(dlg.textContent || '');
    var isPromo = false;
    for (var p = 0; p < PROMO_TOKENS.length; p++) {
      if (dlgText.indexOf(PROMO_TOKENS[p]) >= 0) { isPromo = true; break; }
    }
    if (!isPromo) continue;
    triedCount++;
    var btns = dlg.querySelectorAll('button, [role="button"], a');
    for (var b = 0; b < btns.length; b++) {
      var btn = btns[b];
      if (!isVisible(btn)) continue;
      var btnText = lower(btn.textContent || btn.getAttribute('aria-label') || '');
      var matched = false;
      for (var d = 0; d < DISMISS_LABELS.length; d++) {
        if (btnText === DISMISS_LABELS[d] || btnText.indexOf(DISMISS_LABELS[d]) >= 0) {
          matched = true;
          break;
        }
      }
      if (matched) {
        clickEl(btn);
        dismissed = true;
        method = 'promo_dialog_button:' + btnText.slice(0, 40);
        break;
      }
      // Small button in the top-right corner of the dialog → likely a close icon.
      if (!matched) {
        var bRect = btn.getBoundingClientRect();
        var dRect = dlg.getBoundingClientRect();
        var nearTopRight = bRect.right >= dRect.right - 72 && bRect.top <= dRect.top + 72;
        var smallArea   = bRect.width * bRect.height > 0 && bRect.width * bRect.height < 2500;
        if (nearTopRight && smallArea) {
          clickEl(btn);
          dismissed = true;
          method = 'promo_dialog_close_icon';
          break;
        }
      }
    }
    if (dismissed) break;
  }

  // Strategy 2: standalone banner/dismiss buttons whose sibling text contains a promo token.
  if (!dismissed) {
    var allBtns = document.querySelectorAll('button, [role="button"]');
    for (var j = 0; j < allBtns.length; j++) {
      var ab = allBtns[j];
      if (!isVisible(ab)) continue;
      var abText = lower(ab.textContent || ab.getAttribute('aria-label') || '');
      var parent = ab.parentElement;
      var siblingText = parent ? lower(parent.textContent || '') : '';
      var sibIsPromo = false;
      for (var q = 0; q < PROMO_TOKENS.length; q++) {
        if (siblingText.indexOf(PROMO_TOKENS[q]) >= 0) { sibIsPromo = true; break; }
      }
      if (!sibIsPromo) continue;
      for (var d2 = 0; d2 < DISMISS_LABELS.length; d2++) {
        if (abText === DISMISS_LABELS[d2] || abText.indexOf(DISMISS_LABELS[d2]) >= 0) {
          clickEl(ab);
          dismissed = true;
          method = 'sibling_dismiss_button:' + abText.slice(0, 40);
          break;
        }
      }
      if (dismissed) break;
    }
  }

  // Strategy 3: Escape on the focused element — ONLY when a promo overlay was detected.
  if (!dismissed && triedCount > 0) {
    try {
      var focused = document.activeElement;
      var escTarget = (focused && focused !== document.body) ? focused : document;
      escTarget.dispatchEvent(new KeyboardEvent('keydown', {
        key: 'Escape', code: 'Escape', keyCode: 27, which: 27, bubbles: true, cancelable: true,
      }));
      dismissed = true;
      method = 'escape_key_fallback';
    } catch (e) {}
  }

  return { ok: true, dismissed: dismissed, method: method, tried: triedCount };
}

// ───────────────────────────────────────────────────────────────────────
// Service-worker side
// ───────────────────────────────────────────────────────────────────────
//
// The runner orchestrates MAIN-world helpers via the injected `scripting`
// adapter. Each step:
//   1. invoke a MAIN_* helper via scripting.executeScript({ world:'MAIN' })
//   2. interpret the structured result
//   3. emit telemetry
//   4. fail with a structured error or advance to the next step

/**
 * Helper: run a MAIN-world function and return its primary result.
 * The scripting adapter contract mirrors chrome.scripting.executeScript:
 *   adapter.executeScript({ tabId, func, args, world }) → Promise<[{result}]>
 */
async function _runMainWorld(scripting, tabId, func, args) {
  const out = await scripting.executeScript({
    target: { tabId },
    func,
    args: args || [],
    world: 'MAIN',
  });
  // Chrome returns one entry per injected frame. We use the primary
  // frame's result (first entry); callers don't currently care about
  // sub-frame variants.
  if (!Array.isArray(out) || out.length === 0) {
    return null;
  }
  return out[0]?.result ?? null;
}

function _emitStage(telemetry, stage, status, message) {
  if (telemetry && typeof telemetry === 'function') {
    try { telemetry({ stage, status, message }); } catch (_) { /* noop */ }
  }
}

function _sleep(ms) {
  return new Promise((r) => setTimeout(r, Math.max(0, Number(ms || 0))));
}

function _buildSettingsPanelFailureDetail(reason, payload) {
  const data = payload || {};
  return JSON.stringify({
    reason: reason || null,
    target_tab_url: data.target_tab_url || null,
    document_title: data.document_title || null,
    visible_button_texts: Array.isArray(data.visible_button_texts) ? data.visible_button_texts : [],
    visible_aria_labels: Array.isArray(data.visible_aria_labels) ? data.visible_aria_labels : [],
    visible_role_button_texts: Array.isArray(data.visible_role_button_texts) ? data.visible_role_button_texts : [],
    visible_svg_icon_texts: Array.isArray(data.visible_svg_icon_texts) ? data.visible_svg_icon_texts : [],
    bottom_composer_detected: Boolean(data.bottom_composer_detected),
    composer_present: Boolean(data.composer_present),
    prompt_field_present: Boolean(data.prompt_field_present),
    generate_arrow_detected: Boolean(data.generate_arrow_detected),
    bottom_config_pill_candidates: Array.isArray(data.bottom_config_pill_candidates) ? data.bottom_config_pill_candidates : [],
    candidate_settings_launchers_found: Array.isArray(data.candidate_settings_launchers_found) ? data.candidate_settings_launchers_found : [],
    attempted_strategies: Array.isArray(data.attempted_strategies) ? data.attempted_strategies : [],
    clicked_candidate: data.clicked_candidate || null,
    post_click_panel_markers_found: Boolean(data.post_click_panel_markers_found),
    post_click_panel_markers: Array.isArray(data.post_click_panel_markers) ? data.post_click_panel_markers : [],
    candidate_capture_marker: data.candidate_capture_marker || null,
  });
}

function _buildSettingsOpenerScanMessage(panel) {
  const diagnostics = panel?.diagnostics || {};
  const launchers = diagnostics.candidate_settings_launchers_found || panel?.visible_launchers || [];
  const attempted = panel?.attempted_strategies || diagnostics.attempted_strategies || [];
  return JSON.stringify({
    target_tab_url: diagnostics.target_tab_url || null,
    document_title: diagnostics.document_title || null,
    bottom_composer_detected: Boolean(diagnostics.bottom_composer_detected),
    composer_present: Boolean(diagnostics.composer_present),
    prompt_field_present: Boolean(diagnostics.prompt_field_present),
    generate_arrow_detected: Boolean(diagnostics.generate_arrow_detected),
    bottom_config_pill_candidates: Array.isArray(diagnostics.bottom_config_pill_candidates) ? diagnostics.bottom_config_pill_candidates.length : 0,
    candidate_settings_launchers_found: Array.isArray(launchers) ? launchers.length : 0,
    attempted_strategies: Array.isArray(attempted) ? attempted.map((item) => item?.strategy || item?.label || null) : [],
  });
}

/**
 * Step 2 — open the composer settings panel via the MAIN-world helper.
 * Returns { ok: true } on success or a structured failure with visible
 * launcher candidates.
 */
async function _openComposerSettingsPanel(scripting, tabId, opts) {
  const stampAttr = opts?.stampAttr || 'data-bosmax-launcher';
  const result = await _runMainWorld(
    scripting, tabId, MAIN_openComposerSettingsPanel, [stampAttr],
  );
  const diagnostics = {
    ...(result?.diagnostics || {}),
    candidate_settings_launchers_found: result?.candidate_settings_launchers_found || result?.visible_launchers || [],
    attempted_strategies: result?.attempted_strategies || [],
  };
  if (result?.error === ERR.FLOW_TAB_NOT_TARGETED || result?.reason === 'target_tab_url_not_google_flow') {
    return {
      ok: false,
      error: ERR.FLOW_TAB_NOT_TARGETED,
      detail: _buildSettingsPanelFailureDetail(result?.reason || 'target_tab_url_not_google_flow', diagnostics),
      diagnostics,
      visible_launchers: diagnostics.candidate_settings_launchers_found,
      attempted_strategies: diagnostics.attempted_strategies,
    };
  }
  if (!result || result.ok !== true) {
    return {
      ok: false,
      error: ERR.SETTINGS_PANEL_NOT_OPEN,
      detail: _buildSettingsPanelFailureDetail(result?.reason || 'launcher_not_resolved', diagnostics),
      diagnostics,
      visible_launchers: diagnostics.candidate_settings_launchers_found,
      attempted_strategies: diagnostics.attempted_strategies,
    };
  }
  // If we just clicked the launcher, wait a brief moment + verify the
  // surface mounted.
  if (!result.already_open) {
    const settle = Math.max(150, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS));
    await _sleep(settle);
  }
  let surfaceCheck = await _runMainWorld(
    scripting, tabId, MAIN_isComposerSurfaceOpen, [],
  );

  let retryAttempts = 0;
  while ((!surfaceCheck || surfaceCheck.ok !== true) && retryAttempts < 3 && !result.already_open) {
    retryAttempts++;
    await _sleep(400 * retryAttempts);
    const retryResult = await _runMainWorld(
      scripting, tabId, MAIN_openComposerSettingsPanel, [stampAttr],
    );
    if (retryResult && retryResult.ok === true) {
      await _sleep(400);
      surfaceCheck = await _runMainWorld(
        scripting, tabId, MAIN_isComposerSurfaceOpen, [],
      );
    }
  }

  diagnostics.clicked_candidate = result.clicked ? {
    strategy: result.strategy || null,
    text: result.launcher_text || null,
    bbox: result.launcher_bbox || null,
    click_method: 'dom',
  } : null;
  diagnostics.post_click_panel_markers_found = Boolean(surfaceCheck && surfaceCheck.ok === true);
  diagnostics.post_click_panel_markers = surfaceCheck?.found_markers || [];
  if ((!surfaceCheck || surfaceCheck.ok !== true) && result.strategy === 'bottom_composer_config_pill') {
    const coordinateClick = opts?.coordinateClick || opts?.cdpCoordinateClick || null;
    if (typeof coordinateClick === 'function' && result.launcher_bbox) {
      const cdpResult = await coordinateClick({
        tabId,
        strategy: result.strategy,
        text: result.launcher_text || null,
        bbox: result.launcher_bbox,
        x: Math.round(result.launcher_bbox.x + (result.launcher_bbox.width / 2)),
        y: Math.round(result.launcher_bbox.y + (result.launcher_bbox.height / 2)),
      });
      diagnostics.attempted_strategies = (diagnostics.attempted_strategies || []).concat([{
        strategy: 'bottom_composer_config_pill',
        label: 'bottom composer config pill',
        reason: 'cdp_fallback_invoked',
        clicked_candidate: Boolean(cdpResult && cdpResult.ok === true),
        click_method: 'cdp_visible_coordinate',
        candidate_text: result.launcher_text || null,
        candidate_bbox: result.launcher_bbox || null,
      }]);
      if (cdpResult && cdpResult.ok === true) {
        // After CDP hardware click, give React more time to mount the panel.
        // 800ms is needed because the settings panel animates in and React
        // may batch-render the menu items after the initial mount tick.
        const settle = Math.max(800, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS));
        await _sleep(settle);
        surfaceCheck = await _runMainWorld(
          scripting, tabId, MAIN_isComposerSurfaceOpen, [],
        );
        diagnostics.clicked_candidate = {
          strategy: result.strategy || null,
          text: result.launcher_text || null,
          bbox: result.launcher_bbox || null,
          click_method: 'cdp_visible_coordinate',
        };
        diagnostics.post_click_panel_markers_found = Boolean(surfaceCheck && surfaceCheck.ok === true);
        diagnostics.post_click_panel_markers = surfaceCheck?.found_markers || [];
      }
    }
  }
  let launcherDomInfo = null;
  if (result && result.stamp_id) {
    try {
      launcherDomInfo = await _runMainWorld(scripting, tabId, MAIN_getLauncherOuterHTML, [stampAttr, result.stamp_id]);
    } catch (_) {}
  }
  diagnostics.launcher_dom_info = launcherDomInfo;

  if (!surfaceCheck || surfaceCheck.ok !== true) {
    return {
      ok: false,
      error: ERR.SETTINGS_PANEL_NOT_OPEN,
      detail: _buildSettingsPanelFailureDetail('surface_not_mounted_after_click', diagnostics),
      diagnostics,
      launcher_text: result.launcher_text || null,
      strategy: result.strategy || null,
      visible_launchers: diagnostics.candidate_settings_launchers_found,
      attempted_strategies: diagnostics.attempted_strategies,
    };
  }
  return {
    ok: true,
    already_open: Boolean(result.already_open),
    surface_role: surfaceCheck.role,
    strategy: result.strategy || null,
    click_method: diagnostics.clicked_candidate?.click_method || (result.already_open ? 'already_open' : 'dom'),
    diagnostics,
  };
}

/**
 * Steps 3–7 — click each visible option exactly. Stamps the matched
 * element, then clicks via a follow-up MAIN-world script that targets
 * by stamp id. If the setting is already visually correct in the composer,
 * it is verified and skipped. If the option is hidden in nested menus,
 * it discovers and opens the nested sub-launcher panel first.
 */
async function _clickVisibleOptionExact(scripting, tabId, step, opts) {
  const stampAttr = opts?.stampAttr || 'data-bosmax-option';
  
  // 1. Semantic Verification — check if the setting is already applied.
  // Uses structured pill tokens (detectedRatio/Count/ModelFamily) so it works
  // even when the pill is model-agnostic (e.g. "Nano Banana Pro crop_9_16 1x"
  // with no "video" token). Ratio/count/model do NOT hard-require topMode to
  // be 'Video' — the presence of the token on the pill is the proof; we only
  // exclude an explicit Image-mode workspace.
  const compState = await _runMainWorld(scripting, tabId, MAIN_getBottomComposerState, []);
  if (compState && compState.ok === true) {
    const kind = step.kind || _stepKind(step);
    const notImageMode = compState.topMode !== 'Image';
    let alreadyApplied = false;
    if (kind === 'mode') {
      alreadyApplied = compState.topMode === 'Video';
    } else if (kind === 'submode') {
      alreadyApplied = (compState.topMode === 'Video') && (compState.subMode === 'Frames');
    } else if (kind === 'ratio') {
      alreadyApplied = notImageMode && (compState.detectedRatio === '9:16');
    } else if (kind === 'count') {
      alreadyApplied = notImageMode && (compState.detectedCount === '1x');
    } else if (kind === 'model') {
      const obsFamily = compState.detectedModelFamily || '';
      const obsCanon = compState.detectedModelCanonical || '';
      if (step.acceptCurrent) {
        // No explicit model requested → any recognized model on the pill is fine.
        alreadyApplied = Boolean(obsCanon || obsFamily);
      } else {
        const wantFamily = step.modelFamily || '';
        const wantCanon = step.modelCanonical || '';
        // Family-level match so Nano Banana Pro / 2 / plain all satisfy a
        // "Nano Banana" request without needless model-switching.
        alreadyApplied = Boolean((wantFamily && obsFamily === wantFamily) || (wantCanon && obsCanon === wantCanon));
      }
    }

    if (alreadyApplied) {
      console.log(`[FlowAgent] Setting ${step.label} (kind=${kind}) already applied — confirming, no click.`);
      return {
        ok: true,
        label: step.label,
        role: 'already_selected',
        bbox: null,
        skipped: true,
        visible_candidates: [],
      };
    }
  }

  if (step.label === 'Video' || step.label === 'Frames') {
    await _runMainWorld(scripting, tabId, function() {
      var escEvent = new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, which: 27, bubbles: true, cancelable: true });
      document.dispatchEvent(escEvent);
    }, []);
    await _sleep(300);
  }

  // 2. Try to find direct option first
  let findResult = await _runMainWorld(
    scripting, tabId, MAIN_findVisibleCandidatesByExactLabel,
    [step.label, step.aliases || [], step.preferredRoles || [], stampAttr],
  );
  
  // If not visible, check if we are stuck in a sub-menu and click "Go Back"
  if (!findResult || findResult.ok !== true || !Array.isArray(findResult.matches) || findResult.matches.length === 0) {
    const clickedGoBack = await _runMainWorld(scripting, tabId, function() {
      function isVisible(el) {
        if (!el || !el.getBoundingClientRect) return false;
        var r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return false;
        var s = window.getComputedStyle(el);
        return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
      }
      var candidates = document.querySelectorAll('button, [role="button"]');
      for (var i = 0; i < candidates.length; i++) {
        var el = candidates[i];
        if (isVisible(el)) {
          var txt = (el.textContent || '').toLowerCase();
          if (txt.indexOf('go back') >= 0 || txt.indexOf('arrow_back') >= 0) {
            var clickable = el;
            if (el.closest) {
              var ancestor = el.closest('button, [role="button"]');
              if (ancestor && isVisible(ancestor)) {
                clickable = ancestor;
              }
            }
            // Multi-event click dispatch
            var rect = clickable.getBoundingClientRect();
            var ix = rect.left + rect.width / 2;
            var iy = rect.top + rect.height / 2;
            var common = { bubbles: true, cancelable: true, view: window, clientX: ix, clientY: iy, button: 0 };
            try { clickable.dispatchEvent(new PointerEvent('pointerdown', Object.assign({ pointerType: 'mouse' }, common))); } catch (e) {}
            try { clickable.dispatchEvent(new MouseEvent('mousedown', common)); } catch (e) {}
            try { clickable.dispatchEvent(new PointerEvent('pointerup', Object.assign({ pointerType: 'mouse' }, common))); } catch (e) {}
            try { clickable.dispatchEvent(new MouseEvent('mouseup', common)); } catch (e) {}
            try { clickable.dispatchEvent(new MouseEvent('click', common)); } catch (e) {}
            try { clickable.click(); } catch (e) {}
            return true;
          }
        }
      }
      return false;
    }, []);
    
    if (clickedGoBack) {
      console.log("[FlowAgent] Stuck in sub-menu. Clicked 'Go Back' to return to main settings menu.");
      await _sleep(Math.max(300, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));
      
      // Check if surface closed. If so, re-open it!
      let surfaceCheck = await _runMainWorld(scripting, tabId, MAIN_isComposerSurfaceOpen, []);
      if (!surfaceCheck || surfaceCheck.ok !== true) {
        console.log("[FlowAgent] Settings drawer closed after clicking Go Back. Re-opening...");
        await _openComposerSettingsPanel(scripting, tabId, opts);
      }
      
      // Re-scan for direct option first after going back
      findResult = await _runMainWorld(
        scripting, tabId, MAIN_findVisibleCandidatesByExactLabel,
        [step.label, step.aliases || [], step.preferredRoles || [], stampAttr],
      );
    }
  }

  // If not visible, let's explore launchers for aspect/count/model settings
  if (!findResult || findResult.ok !== true || !Array.isArray(findResult.matches) || findResult.matches.length === 0) {
    let settingCategory = null;
    const _stepK = step.kind || _stepKind(step);
    if (_stepK === 'ratio') settingCategory = 'aspect';
    else if (_stepK === 'count') settingCategory = 'count';
    else if (_stepK === 'model') settingCategory = 'model';
    
    if (settingCategory) {
      console.log(`[FlowAgent] Option ${step.label} not directly visible. Searching for launcher for: ${settingCategory}`);
      // Find launcher inside settings panel
      const launcherInfo = await _runMainWorld(
        scripting, tabId,
        function (category, attr) {
          var el = MAIN_findSettingLauncher(category);
          if (!el) return null;
          var id = attr + '-' + Date.now();
          el.setAttribute(attr, id);
          var rect = el.getBoundingClientRect();
          return { stamp_id: id, stamp_attr: attr, text: el.textContent, bbox: { x: rect.left, y: rect.top, width: rect.width, height: rect.height } };
        },
        [settingCategory, 'data-bosmax-sublauncher']
      );
      
      if (launcherInfo) {
        console.log(`[FlowAgent] Found sub-launcher for ${settingCategory}: ${launcherInfo.text}. Clicking it to open nested menu.`);
        // Click the sub-launcher to open portal/sub-menu
        const clickLauncher = await _runMainWorld(
          scripting, tabId, MAIN_clickStampedElement,
          [launcherInfo.stamp_attr, launcherInfo.stamp_id]
        );
        
        await _sleep(Math.max(300, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));
        
        // Now try finding the option again (it should be visible in portal/menu)
        findResult = await _runMainWorld(
          scripting, tabId, MAIN_findVisibleCandidatesByExactLabel,
          [step.label, step.aliases || [], step.preferredRoles || [], stampAttr],
        );
      } else if (settingCategory === 'model') {
        console.log("[FlowAgent] Model launcher not found on Tier One. Veo 3.1 - Lite is already the default/only model. Bypassing selection with success.");
        return {
          ok: true,
          label: step.label,
          role: 'defaulted',
          bbox: null,
          skipped: true,
          visible_candidates: [],
        };
      }
    }
  }

  // 3. Fallback/Error if option still not visible — capture a DOM snapshot before failing.
  if (!findResult || findResult.ok !== true || !Array.isArray(findResult.matches) || findResult.matches.length === 0) {
    let failState = null;
    let failUrl = null;
    try { failState = await _runMainWorld(scripting, tabId, MAIN_getBottomComposerState, []); } catch (_) {}
    try {
      const urlSnap = await _runMainWorld(scripting, tabId, function () {
        return { url: String(window.location.href || ''), title: String(document.title || '') };
      }, []);
      failUrl = urlSnap;
    } catch (_) {}
    const diagnostics = {
      current_bottom_pill_before: compState?.pillText || 'unknown',
      current_bottom_pill_at_fail: failState?.pillText || 'unknown',
      current_url: failUrl?.url || 'unknown',
      current_title: failUrl?.title || 'unknown',
      top_mode: failState?.topMode || 'unknown',
      sub_mode: failState?.subMode || 'unknown',
      panel_opened: true,
      panel_candidate_count: findResult?.visible_candidates?.length || 0,
      visible_candidates: findResult?.visible_candidates || [],
      clicked_aspect_candidate: null,
      clicked_candidate_bbox: null,
      click_method: 'DOM',
      post_click_bottom_pill: 'unknown',
      post_click_detected_aspect: 'unknown',
      whether_panel_closed: false,
    };
    return {
      ok: false,
      error: step.errorCode,
      detail: JSON.stringify(diagnostics),
      label: step.label,
      visible_candidates: findResult?.visible_candidates || [],
    };
  }

  // 4. Stamp and click the matched option
  const top = findResult.matches[0];
  const clickResult = await _runMainWorld(
    scripting, tabId, MAIN_clickStampedElement,
    [top.stamp_attr, top.stamp_id],
  );
  if (!clickResult || clickResult.ok !== true) {
    return {
      ok: false,
      error: step.errorCode,
      detail: clickResult?.reason || 'click_failed',
      label: step.label,
    };
  }
  
  // Settle wait
  await _sleep(Math.max(150, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));

  // 4b. Coordinate-click fallback — if the DOM-dispatched click did NOT change
  // the observed setting, retry once via a real hardware-level CDP click at the
  // element center. This rescues cases where React/Radix ignore synthetic
  // events (isTrusted gating). Only for config settings that surface on the pill.
  const _kindForFallback = step.kind || _stepKind(step);
  const _coordClick = opts?.cdpCoordinateClick || opts?.coordinateClick || null;
  if (typeof _coordClick === 'function' && top.bbox &&
      (_kindForFallback === 'ratio' || _kindForFallback === 'count' || _kindForFallback === 'model')) {
    const verifyState = await _runMainWorld(scripting, tabId, MAIN_getBottomComposerState, []);
    let applied = false;
    if (verifyState && verifyState.ok === true) {
      if (_kindForFallback === 'ratio') applied = verifyState.detectedRatio === '9:16';
      else if (_kindForFallback === 'count') applied = verifyState.detectedCount === '1x';
      else if (_kindForFallback === 'model') {
        applied = step.acceptCurrent
          ? Boolean(verifyState.detectedModelCanonical)
          : (Boolean(step.modelFamily) && verifyState.detectedModelFamily === step.modelFamily);
      }
    }
    if (!applied) {
      console.log(`[FlowAgent] DOM click for ${step.label} did not register — retrying via CDP coordinate click.`);
      try {
        await _coordClick({
          tabId,
          strategy: `option_${_kindForFallback}`,
          text: top.text || step.label,
          bbox: top.bbox,
          x: Math.round(top.bbox.x + (top.bbox.width / 2)),
          y: Math.round(top.bbox.y + (top.bbox.height / 2)),
        });
        await _sleep(Math.max(200, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));
      } catch (_) { /* tolerant — coordinate click is best-effort */ }
    }
  }

  // 5. Recover if panel closed after click!
  // If the surface closed, we reopen the settings panel for subsequent steps
  const panelOpen = await _runMainWorld(scripting, tabId, MAIN_isComposerSurfaceOpen, []);
  if (!panelOpen || panelOpen.ok !== true) {
    console.log(`[FlowAgent] Settings surface closed after selecting ${step.label}. Re-opening launcher.`);
    await _openComposerSettingsPanel(scripting, tabId, opts);
  }

  return {
    ok: true,
    label: step.label,
    role: top.role,
    bbox: top.bbox,
    post_state: clickResult.post_state || null,
    visible_candidates: findResult?.visible_candidates || [],
    skipped: false,
  };
}

/**
 * Step 8 — verify all 5 options applied. We re-probe each step with
 * the exact-match helper; success = first match has aria-selected=true
 * OR data-state=active. Failure here only DOWNGRADES success — it
 * doesn't fail the runner — because some UIs use class-only state.
 */
async function _verifySettingsPanelApplied(scripting, tabId, opts, sequence) {
  const results = {};
  const seq = Array.isArray(sequence) && sequence.length ? sequence : SOP_SEQUENCE;
  for (const step of seq) {
    const found = await _runMainWorld(
      scripting, tabId, MAIN_findVisibleCandidatesByExactLabel,
      [step.label, step.aliases || [], step.preferredRoles || [], opts?.stampAttr || 'data-bosmax-option'],
    );
    if (found?.ok && Array.isArray(found.matches) && found.matches.length > 0) {
      // We can't easily fetch the live aria-selected after stamping
      // without another script roundtrip; record presence + first match.
      results[step.label] = { found: true, role: found.matches[0].role };
    } else {
      results[step.label] = { found: false };
    }
  }
  return { ok: true, results };
}

/**
 * Step 9 — insert the operator-provided prompt into the composer.
 */
async function _insertPrompt(scripting, tabId, promptText) {
  // Defensive Drawer Closer: Close the settings drawer/panel BEFORE inserting the prompt.
  // When the settings popover is open, Google Flow sets contenteditable="false" on the Slate
  // editor, so we must close it first. The settings panel is opened by clicking the bottom
  // composer pill button — clicking it again closes it (toggle). We also try Escape as a
  // fallback. We do NOT fire Escape if nothing is open (avoids closing the project).
  await _runMainWorld(scripting, tabId, function() {
    function isVisible(el) {
      if (!el || !el.getBoundingClientRect) return false;
      var r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return false;
      var s = window.getComputedStyle(el);
      return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
    }
    function clickEl(el) {
      var r = el.getBoundingClientRect();
      var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      var common = { bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy, button: 0, buttons: 1 };
      try { el.dispatchEvent(new PointerEvent('pointerdown', Object.assign({ pointerId: 1, pointerType: 'mouse' }, common))); } catch (e) {}
      try { el.dispatchEvent(new MouseEvent('mousedown', common)); } catch (e) {}
      try { el.dispatchEvent(new PointerEvent('pointerup', Object.assign({ pointerId: 1, pointerType: 'mouse' }, common))); } catch (e) {}
      try { el.dispatchEvent(new MouseEvent('mouseup', common)); } catch (e) {}
      try { el.dispatchEvent(new MouseEvent('click', common)); } catch (e) {}
      try { el.click(); } catch (e) {}
    }
    // Strategy 1: Check if any open surface (menu/listbox/dialog) is visible
    var surfaces = document.querySelectorAll('[role="menu"], [role="listbox"], [role="dialog"], [data-radix-popper-content-wrapper]');
    var panelOpen = false;
    for (var j = 0; j < surfaces.length; j++) {
      if (isVisible(surfaces[j])) { panelOpen = true; break; }
    }
    if (!panelOpen) {
      // Also check for a visible aside/section that looks like a settings drawer
      var asides = document.querySelectorAll('aside, section');
      for (var a = 0; a < asides.length; a++) {
        if (isVisible(asides[a]) && asides[a].textContent && asides[a].textContent.length > 30) { panelOpen = true; break; }
      }
    }
    if (!panelOpen) return false;

    // Strategy 2: Try to find the bottom composer settings pill button (toggle) and click it to close
    var buttons = document.querySelectorAll('button, [role="button"]');
    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      if (!isVisible(btn)) continue;
      var txt = (btn.textContent || '').replace(/\s+/g, ' ').trim();
      // The pill text contains mode info like "Video • 10s" + aspect info like "crop_9_16" + count "1x"
      if (/video|frames|crop_|9:16|1x|portrait/i.test(txt) && txt.length > 3 && txt.length < 120) {
        clickEl(btn);
        return 'pill_toggle_clicked';
      }
    }

    // Strategy 3: Fire Escape on the focused element (safest — targets open popovers)
    var focused = document.activeElement || document.body;
    var escEvent = new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, which: 27, bubbles: true, cancelable: true });
    focused.dispatchEvent(escEvent);
    document.dispatchEvent(escEvent);
    return 'escape_dispatched';
  }, []);
  await _sleep(600);

  let attempt = 0;
  let result = null;
  while (attempt < 15) {
    result = await _runMainWorld(scripting, tabId, MAIN_insertComposerPrompt, [promptText || '']);
    if (result && result.ok === true) {
      return { ok: true, inserted_length: result.inserted_length, field_value_length: result.field_value_length };
    }
    if (result && result.reason === 'slate_prompt_verification_failed') {
      return { ok: false, error: ERR.PROMPT_FIELD_NOT_FOUND, detail: result.reason };
    }
    attempt++;
    await _sleep(300);
  }
  return { ok: false, error: ERR.PROMPT_FIELD_NOT_FOUND, detail: result?.reason || 'prompt_field_not_found' };
}

/**
 * Steps 10/11 — click Start, then click Upload media. Both use the
 * exact-label finder. If the SOP runner is called WITHOUT a media
 * asset (smoke test), the caller can pass opts.skipUpload = true.
 */
async function _clickStart(scripting, tabId, opts) {
  const step = {
    label: 'Start',
    aliases: ['Start frame', '+ Add start frame', 'Add start frame'],
    preferredRoles: ['button', 'option'],
    errorCode: ERR.START_BUTTON_NOT_FOUND,
    stage: 'F2V_SOP_START_CLICKED',
  };
  return _clickVisibleOptionExact(scripting, tabId, step, opts);
}
async function _clickUploadMedia(scripting, tabId, opts) {
  const step = {
    label: 'Upload media',
    aliases: ['upload Upload media', 'Upload', 'Upload from device'],
    preferredRoles: ['button', 'option', 'menuitem'],
    errorCode: ERR.UPLOAD_MEDIA_NOT_FOUND,
    stage: 'F2V_SOP_UPLOAD_CLICKED',
  };
  return _clickVisibleOptionExact(scripting, tabId, step, opts);
}

/**
 * Step 13 — invoke generate via MAIN-world React fiber submit. Falls
 * back to a plain click sequence only when the fiber-handler lookup
 * fails AND opts.allowFallbackClick === true.
 */
async function _invokeGenerate(scripting, tabId, opts) {
  const stampAttr = opts?.submitStampAttr || 'data-bosmax-submit-target';
  const stamp = await _runMainWorld(scripting, tabId, MAIN_stampGenerateButton, [stampAttr]);
  if (!stamp || stamp.ok !== true) {
    return { ok: false, error: ERR.MAIN_WORLD_SUBMIT_HANDLER_NOT_FOUND, detail: 'generate_button_not_visible' };
  }
  const fiber = await _runMainWorld(scripting, tabId, MAIN_invokeReactFiberSubmit, [stamp.stamp_attr, stamp.stamp_id]);
  if (fiber && fiber.ok === true) {
    return { ok: true, strategy: fiber.strategy, fiber_visited: fiber.visited, button_text: stamp.text };
  }
  // Fallback path — only attempted when caller opts in.
  if (opts?.allowFallbackClick === true) {
    const click = await _runMainWorld(scripting, tabId, MAIN_clickStampedElement, [stamp.stamp_attr, stamp.stamp_id]);
    if (click && click.ok === true) {
      return { ok: true, strategy: 'fallback_synthetic_click', button_text: stamp.text, fiber_fail_reason: fiber?.reason || null };
    }
  }
  return {
    ok: false,
    error: ERR.MAIN_WORLD_SUBMIT_HANDLER_NOT_FOUND,
    detail: fiber?.reason || 'react_handler_not_found',
    fiber_visited: fiber?.visited || 0,
    button_text: stamp.text || null,
  };
}

// ───────────────────────────────────────────────────────────────────────
// Public orchestrator
// ───────────────────────────────────────────────────────────────────────

/**
 * @param {object} deps      — { scripting, telemetry?, newProjectFn? }
 *                              scripting.executeScript({ tabId, func, args, world })
 *                              telemetry({ stage, status, message })
 *                              newProjectFn(tabId, job) → Promise<{ok}>
 *                              (when omitted, runner assumes the tab is
 *                              already on a project editor)
 * @param {number} tabId
 * @param {object} job       — operator-submitted job payload
 * @param {object} [opts]
 * @returns {Promise<{ok, error?, detail?, stages, stage_results, summary?}>}
 */
// ── Model + step-kind resolution (service-worker side) ──────────────────
// Mirrors content-flow-dom.js canonicalizeFlowModelLabel so the runner agrees
// with the rest of the repo on what "Nano Banana" / "Veo" mean.
function _canonicalModel(value) {
  const s = String(value == null ? '' : value).replace(/\s+/g, ' ').trim().toLowerCase();
  if (!s) return '';
  if (s.indexOf('veo 3.1 - lite') >= 0 || s.indexOf('veo 3.1 lite') >= 0) return 'veo 3.1 - lite';
  if (s.indexOf('veo 3.1 - pro') >= 0 || s.indexOf('veo 3.1 pro') >= 0) return 'veo 3.1 - pro';
  if (s.indexOf('veo 3.1 - fast') >= 0 || s.indexOf('veo 3.1 fast') >= 0) return 'veo 3.1 - fast';
  if (s.indexOf('veo 3.1 - quality') >= 0 || s.indexOf('veo 3.1 quality') >= 0) return 'veo 3.1 - quality';
  if (s.indexOf('nano banana 2') >= 0) return 'nano banana 2';
  if (s.indexOf('nano banana pro') >= 0 || s.indexOf('nano banana - pro') >= 0) return 'nano banana pro';
  if (s.indexOf('veo 3.1') >= 0) return 'veo 3.1';
  if (s.indexOf('nano banana') >= 0) return 'nano banana';
  if (s.indexOf('imagen') >= 0) return 'imagen';
  if (s.indexOf('gemini') >= 0) return 'gemini';
  return s;
}
function _modelFamily(canon) {
  const c = String(canon || '');
  if (!c) return '';
  if (c.indexOf('nano banana') >= 0) return 'nano banana';
  if (c.indexOf('veo') >= 0) return 'veo';
  if (c.indexOf('imagen') >= 0) return 'imagen';
  if (c.indexOf('gemini') >= 0) return 'gemini';
  return c;
}
function _modelAliases(canon, rawLabel) {
  const fam = _modelFamily(canon);
  const out = new Set();
  if (rawLabel) out.add(String(rawLabel));
  if (canon) out.add(canon);
  if (fam === 'nano banana') {
    ['Nano Banana', 'Nano Banana Pro', 'Nano Banana 2', 'Nano Banana - Pro', 'Nano Banana Pro (Image)', '🍌 Nano Banana Pro'].forEach((a) => out.add(a));
  } else if (fam === 'veo') {
    ['Veo 3.1 - Lite', 'Veo 3.1 Lite', 'Veo 3.1', 'Veo', 'Veo 3.1 - Pro', 'Veo 3.1 - Fast', 'Veo 3.1 - Quality'].forEach((a) => out.add(a));
  }
  return Array.from(out);
}
/**
 * Resolve the desired model from the job. Returns null when the job does not
 * request a specific model — in that case the runner ACCEPTS whatever model
 * the editor already shows on the composer pill (no needless switching).
 */
function _resolveDesiredModel(job) {
  const raw = job && (job.modelLabel || job.model || job.model_label || job.modelName);
  if (!raw) return null;
  const canon = _canonicalModel(raw);
  return { label: String(raw), canon, family: _modelFamily(canon), aliases: _modelAliases(canon, raw) };
}
function _stepKind(step) {
  if (!step) return 'other';
  if (step.kind) return step.kind;
  const label = String(step.label || '');
  if (label === 'Video') return 'mode';
  if (label === 'Frames') return 'submode';
  if (label === '9:16') return 'ratio';
  if (label === '1x') return 'count';
  if (/veo|nano\s*banana|imagen|gemini/i.test(label)) return 'model';
  return 'other';
}
/**
 * Build the effective step sequence for this job. The model step (frozen as
 * "Veo 3.1 - Lite" in SOP_SEQUENCE) is rewritten to target the job's requested
 * model, or marked acceptCurrent when none was requested. Stage keys are left
 * unchanged so the telemetry contract stays stable.
 */
function _buildEffectiveSequence(desiredModel) {
  return SOP_SEQUENCE.map((s) => {
    const kind = _stepKind(s);
    if (kind !== 'model') return Object.assign({}, s, { kind });
    if (!desiredModel) return Object.assign({}, s, { kind, acceptCurrent: true });
    return Object.assign({}, s, {
      kind,
      acceptCurrent: false,
      label: desiredModel.label,
      aliases: desiredModel.aliases,
      modelFamily: desiredModel.family,
      modelCanonical: desiredModel.canon,
    });
  });
}

async function executeF2VVisibleSopRunner(deps, tabId, job, opts = {}) {
  const scripting = deps && deps.scripting;
  if (!scripting || typeof scripting.executeScript !== 'function') {
    return { ok: false, error: ERR.EXECUTION_THREW, detail: 'scripting_adapter_missing', stages: [] };
  }
  const telemetry = deps && deps.telemetry;
  const settle = Math.max(150, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS));
  const stages = [];
  const recordStage = (stage, status, message) => {
    stages.push({ stage, status, message });
    _emitStage(telemetry, stage, status, message);
  };

  const stageResults = {
    settings_configured: false,
    prompt_inserted: false,
    start_clicked: false,
    media_attached: false,
    generate_submitted: false,
  };

  try {
    // Step 1 — new project / resume. The caller passes newProjectFn so
    // navigation resume / recursion guard stays in the existing path.
    // When absent, we trust the tab is already on a project editor.
    if (typeof deps.newProjectFn === 'function') {
      const np = await deps.newProjectFn(tabId, job);
      if (!np || np.ok !== true) {
        recordStage('F2V_SOP_NEW_PROJECT_READY', 'FAIL', np?.error || 'new_project_failed');
        return { ok: false, error: ERR.NEW_PROJECT_FAILED, detail: np?.error || null, stages };
      }
    }
    recordStage('F2V_SOP_NEW_PROJECT_READY', 'PASS', null);

    // Resolve the requested model (Nano Banana, Veo, …). When the job does not
    // name a model we accept whatever the editor already shows on the pill —
    // the live reality is "🍌 Nano Banana Pro crop_9_16 1x".
    const desiredModel = _resolveDesiredModel(job);
    const effectiveSequence = _buildEffectiveSequence(desiredModel);
    recordStage('F2V_SOP_MODEL_TARGET_RESOLVED', 'PASS',
      `desired=${desiredModel ? desiredModel.canon : 'accept_current'} family=${desiredModel ? desiredModel.family : 'any'}`);

    // Steps 3-7 — configure each visible option.
    for (const step of effectiveSequence) {
      if (step.kind === 'ratio') {
        // SETTINGS GATE. Read the composer pill FIRST. If aspect + count + model
        // are already correct (the Tier One reality), CONFIRM them without ever
        // opening the settings panel — clicking an already-correct chip risks
        // toggling it off. Only when something is wrong do we dismiss overlays
        // and open the panel (Tier Two).
        recordStage('F2V_SOP_SETTINGS_EXPLORER_STARTED', 'PASS', `build=${F2V_FLOW_QUEUE_RUNNER_BUILD_ID}`);

        const preState = await _runMainWorld(scripting, tabId, MAIN_getBottomComposerState, []);
        const ratioOk = Boolean(preState && preState.detectedRatio === '9:16');
        const countOk = Boolean(preState && preState.detectedCount === '1x');
        const modelOk = Boolean(preState && (desiredModel
          ? (preState.detectedModelFamily === desiredModel.family || preState.detectedModelCanonical === desiredModel.canon)
          : Boolean(preState.detectedModelCanonical)));

        if (ratioOk && countOk && modelOk) {
          console.log('[FlowAgent] Tier One: aspect + count + model already configured on the pill — no panel needed.');
          recordStage('F2V_SOP_SETTINGS_LAUNCHER_FOUND', 'PASS', 'launcher=tier_one_pill_confirmed');
          recordStage('F2V_SOP_SETTINGS_PANEL_OPENED', 'PASS',
            `strategy=tier_one_pill_confirmed pill=${JSON.stringify(String(preState.pillText || '').slice(0, 80))}`);
          // Fall through: each ratio/count/model step semantic-skips below.
        } else {
          // Tier Two — dismiss promo overlays, then open the settings panel.
          const dismissRes = await _runMainWorld(scripting, tabId, MAIN_dismissPromoOverlays, []);
          if (dismissRes && dismissRes.dismissed) {
            console.log(`[FlowAgent] Overlay dismissed via: ${dismissRes.method || 'unknown'}`);
            await _sleep(350);
          }
          const panel = await _openComposerSettingsPanel(scripting, tabId, opts);
          recordStage('F2V_SOP_SETTINGS_OPENER_SCAN', 'PASS', _buildSettingsOpenerScanMessage(panel));
          if (!panel.ok) {
            recordStage('F2V_SOP_SETTINGS_PANEL_OPENED', 'FAIL',
              `${panel.error} detail=${panel.detail} launchers=${JSON.stringify(panel.visible_launchers || [])} strategies=${JSON.stringify(panel.attempted_strategies || [])}`);
            return {
              ok: false,
              error: panel.error,
              detail: panel.detail,
              stages,
              visible_launchers: panel.visible_launchers || [],
              attempted_strategies: panel.attempted_strategies || [],
              diagnostics: panel.diagnostics || null,
            };
          }
          recordStage('F2V_SOP_SETTINGS_LAUNCHER_FOUND', 'PASS', `launcher=${panel.launcher_text || 'already_open'}`);
          recordStage('F2V_SOP_SETTINGS_PANEL_OPENED', 'PASS',
            `already_open=${Boolean(panel.already_open)} strategy=${panel.strategy || 'already_open'}`);
        }
      }

      const clickRes = await _clickVisibleOptionExact(scripting, tabId, step, opts);
      if (!clickRes.ok) {
        recordStage(step.stage, 'FAIL',
          `${clickRes.error} detail=${clickRes.detail} candidates=${JSON.stringify(clickRes.visible_candidates || [])}`);
        return {
          ok: false,
          error: clickRes.error,
          detail: clickRes.detail,
          stages,
          stage_results: stageResults,
          visible_candidates: clickRes.visible_candidates || [],
        };
      }

      // Emit candidate scanned stage
      recordStage('F2V_SOP_SETTING_CANDIDATES_SCANNED', 'PASS', `label=${step.label} count=${clickRes.visible_candidates?.length || 0}`);

      // Emit explicit CLICKED or CONFIRMED stages
      let stageName = step.stage;
      if (clickRes.skipped) {
        stageName = step.stage.replace('_CLICKED', '_CONFIRMED');
      }
      recordStage(stageName, 'PASS', `role=${clickRes.role}`);

      // If we clicked or confirmed, also emit the corresponding CONFIRMED step for the UAT trail contract
      if (!clickRes.skipped && step.stage.indexOf('_CLICKED') >= 0) {
        const confirmedStage = step.stage.replace('_CLICKED', '_CONFIRMED');
        recordStage(confirmedStage, 'PASS', `role=${clickRes.role}`);
      }
    }

    // Step 8 — verify settings applied (soft check — informational).
    const verify = await _verifySettingsPanelApplied(scripting, tabId, opts, effectiveSequence);
    stageResults.settings_configured = true;
    recordStage('F2V_SOP_SETTINGS_CONFIGURED', 'PASS', `results=${JSON.stringify(verify.results || {})}`);

    // Step 8b: Unconditionally close the settings panel before inserting the prompt.
    // Google Flow sets contenteditable="false" on the Slate editor when the settings panel
    // is open. Close the panel by re-clicking the bottom composer config pill (toggle button).
    // We do this unconditionally because the panel may be open even when all settings were
    // already_selected (no click was needed, so the panel was never explicitly closed).
    const panelCloseResult = await _runMainWorld(scripting, tabId, function() {
      function isVisible(el) {
        if (!el || !el.getBoundingClientRect) return false;
        var r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return false;
        var s = window.getComputedStyle(el);
        return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
      }
      function clickEl(el) {
        var r = el.getBoundingClientRect();
        var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
        var common = { bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy, button: 0, buttons: 1 };
        try { el.dispatchEvent(new PointerEvent('pointerdown', Object.assign({ pointerId: 1, pointerType: 'mouse' }, common))); } catch (e) {}
        try { el.dispatchEvent(new MouseEvent('mousedown', common)); } catch (e) {}
        try { el.dispatchEvent(new PointerEvent('pointerup', Object.assign({ pointerId: 1, pointerType: 'mouse' }, common))); } catch (e) {}
        try { el.dispatchEvent(new MouseEvent('mouseup', common)); } catch (e) {}
        try { el.dispatchEvent(new MouseEvent('click', common)); } catch (e) {}
        try { el.click(); } catch (e) {}
      }
      var slateEditors = document.querySelectorAll('[data-slate-editor="true"]');
      var editorCount = slateEditors.length;
      var editorCE = [];
      for (var e0 = 0; e0 < slateEditors.length; e0++) {
        editorCE.push(slateEditors[e0].getAttribute('contenteditable'));
      }
      var buttons = document.querySelectorAll('button, [role="button"]');
      // Pass 1: bottom composer pill by content signature (crop_9_16, video+1x, frames+1x)
      for (var i = 0; i < buttons.length; i++) {
        var btn = buttons[i];
        if (!isVisible(btn)) continue;
        var raw = btn.textContent || '';
        if (raw.length > 3 && raw.length < 200) {
          if (/crop_9_16/i.test(raw) || /crop_free/i.test(raw) ||
              (/video/i.test(raw) && /1x/i.test(raw)) ||
              (/frames/i.test(raw) && /1x/i.test(raw))) {
            clickEl(btn);
            return { action: 'pill_closed_pass1', editor_count: editorCount, editor_ce: editorCE, btn_text: raw.slice(0, 80) };
          }
        }
      }
      // Pass 2: look for aria-expanded="true" button (the open settings toggle)
      var expanded = document.querySelectorAll('button[aria-expanded="true"], [role="button"][aria-expanded="true"]');
      for (var e2 = 0; e2 < expanded.length; e2++) {
        if (isVisible(expanded[e2])) {
          clickEl(expanded[e2]);
          return { action: 'pill_closed_expanded', editor_count: editorCount, editor_ce: editorCE };
        }
      }
      // Pass 3: press Escape on the focused element only
      var focused = document.activeElement;
      if (focused && focused !== document.body) {
        var escEvent = new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, which: 27, bubbles: true, cancelable: true });
        focused.dispatchEvent(escEvent);
        return { action: 'escape_on_focused', editor_count: editorCount, editor_ce: editorCE };
      }
      return { action: 'no_close_action_taken', editor_count: editorCount, editor_ce: editorCE };
    }, []);
    recordStage('F2V_SOP_SETTINGS_PANEL_CLOSE_ATTEMPT', 'PASS', JSON.stringify(panelCloseResult || {}));
    await _sleep(800);

    // Step 9 — insert prompt.
    const promptResult = await _insertPrompt(scripting, tabId, job?.prompt || '');
    if (!promptResult.ok) {
      recordStage('F2V_SOP_PROMPT_INSERTED', 'FAIL', `${promptResult.error} ${promptResult.detail}`);
      return { ok: false, error: promptResult.error, detail: promptResult.detail, stages, stage_results: stageResults };
    }
    stageResults.prompt_inserted = true;
    recordStage('F2V_SOP_PROMPT_INSERTED', 'PASS',
      `inserted_length=${promptResult.inserted_length} field_value_length=${promptResult.field_value_length}`);

    // Step 10/11 — Start-slot click + media attach.
    // CDP upload (Phase 2, opt-in via opts.cdpFileChooserUpload) must ARM file-chooser
    // interception BEFORE the Start-slot click, because that click opens the native OS
    // file chooser (there is no in-DOM "Upload media" control — confirmed by live UAT).
    // When the dep is absent, the proven DOM `_clickUploadMedia` path runs unchanged.
    const _useCdpUpload = typeof opts?.cdpFileChooserUpload === 'function' && opts?.skipUpload !== true;
    if (_useCdpUpload) {
      const armRes = await opts.cdpFileChooserUpload({
        phase: 'arm',
        tabId,
        slotLabel: 'Start',
        assetSource: job?.startAsset || job?.productId || job?.startImageMediaId || null,
      });
      if (!armRes || armRes.ok !== true) {
        recordStage('F2V_SOP_CDP_FILE_CHOOSER_ARMED', 'FAIL', `${armRes?.error || 'ERR_CDP_ARM_FAILED'} ${armRes?.detail || ''}`);
        return { ok: false, error: armRes?.error || 'ERR_CDP_ARM_FAILED', detail: armRes?.detail || null, stages, stage_results: stageResults };
      }
      recordStage('F2V_SOP_CDP_FILE_CHOOSER_ARMED', 'PASS', `slot=Start file=${armRes.expectedFileName || ''}`);
    }

    // Step 10 — click Start (frame slot). In CDP mode this opens the native file chooser.
    const startResult = await _clickStart(scripting, tabId, opts);
    if (!startResult.ok) {
      recordStage('F2V_SOP_START_CLICKED', 'FAIL', `${startResult.error} ${startResult.detail}`);
      return { ok: false, error: startResult.error, detail: startResult.detail, stages, stage_results: stageResults };
    }
    stageResults.start_clicked = true;
    recordStage('F2V_SOP_START_CLICKED', 'PASS', `role=${startResult.role}`);

    // HARD GATE before upload — operator-specified.
    if (stageResults.settings_configured !== true) {
      recordStage('F2V_SOP_UPLOAD_CLICKED', 'FAIL', ERR.SETTINGS_NOT_CONFIGURED_BEFORE_UPLOAD);
      return {
        ok: false,
        error: ERR.SETTINGS_NOT_CONFIGURED_BEFORE_UPLOAD,
        detail: 'gate_settings_configured_false',
        stages,
        stage_results: stageResults,
      };
    }

    if (opts?.skipUpload === true) {
      recordStage('F2V_SOP_UPLOAD_CLICKED', 'SKIP', 'opts.skipUpload=true');
      recordStage('F2V_SOP_UPLOAD_WAIT_DONE', 'SKIP', 'opts.skipUpload=true');
    } else if (_useCdpUpload) {
      // Step 11 (CDP) — the Start click opened the native chooser; CDP feeds the local
      // file via DOM.setFileInputFiles (background-owned chrome.debugger).
      const fedRes = await opts.cdpFileChooserUpload({ phase: 'wait', tabId });
      if (!fedRes || fedRes.ok !== true) {
        recordStage('F2V_SOP_CDP_FILE_CHOOSER_FED', 'FAIL', `${fedRes?.error || ERR.UPLOAD_MEDIA_NOT_FOUND} ${fedRes?.detail || ''}`);
        recordStage('F2V_SOP_UPLOAD_CLICKED', 'FAIL', `${fedRes?.error || ERR.UPLOAD_MEDIA_NOT_FOUND} strategy=cdp_file_chooser`);
        return { ok: false, error: fedRes?.error || ERR.UPLOAD_MEDIA_NOT_FOUND, detail: fedRes?.detail || null, stages, stage_results: stageResults };
      }
      recordStage('F2V_SOP_CDP_FILE_CHOOSER_FED', 'PASS', `file=${fedRes.filePath || ''} backendNodeId=${fedRes.backendNodeId || ''}`);
      recordStage('F2V_SOP_UPLOAD_CLICKED', 'PASS', 'strategy=cdp_file_chooser');
      // Step 12 — wait for media attachment.
      const waitMs = Math.max(0, Number(opts?.uploadWaitMs ?? SOP_DEFAULT_UPLOAD_WAIT_MS));
      await _sleep(waitMs);
      stageResults.media_attached = true;
      recordStage('F2V_SOP_UPLOAD_WAIT_DONE', 'PASS', `waited_ms=${waitMs} strategy=cdp_file_chooser`);
    } else {
      // Step 11 — click Upload media (proven DOM path; default).
      const uploadResult = await _clickUploadMedia(scripting, tabId, opts);
      if (!uploadResult.ok) {
        recordStage('F2V_SOP_UPLOAD_CLICKED', 'FAIL', `${uploadResult.error} ${uploadResult.detail}`);
        return { ok: false, error: uploadResult.error, detail: uploadResult.detail, stages, stage_results: stageResults };
      }
      recordStage('F2V_SOP_UPLOAD_CLICKED', 'PASS', `role=${uploadResult.role}`);
      // Step 12 — wait 10 seconds for media attachment.
      const waitMs = Math.max(0, Number(opts?.uploadWaitMs ?? SOP_DEFAULT_UPLOAD_WAIT_MS));
      await _sleep(waitMs);
      stageResults.media_attached = true;
      recordStage('F2V_SOP_UPLOAD_WAIT_DONE', 'PASS', `waited_ms=${waitMs}`);
    }

    // HARD GATE before generate — operator-specified.
    if (stageResults.prompt_inserted !== true || (opts?.skipUpload !== true && stageResults.media_attached !== true)) {
      recordStage('F2V_SOP_GENERATE_SUBMITTED', 'FAIL', ERR.GENERATE_PRECONDITION_FAILED);
      return {
        ok: false,
        error: ERR.GENERATE_PRECONDITION_FAILED,
        detail: `prompt_inserted=${stageResults.prompt_inserted} media_attached=${stageResults.media_attached}`,
        stages,
        stage_results: stageResults,
      };
    }

    // Step 13 — invoke generate via React fiber submit (MAIN-world).
    if (opts?.skipGenerate === true) {
      recordStage('F2V_SOP_GENERATE_SUBMITTED', 'SKIP', 'opts.skipGenerate=true');
      return { ok: true, stages, stage_results: stageResults, summary: { generated: false, reason: 'skip_generate_opt_in' } };
    }
    const gen = await _invokeGenerate(scripting, tabId, opts);
    if (!gen.ok) {
      recordStage('F2V_SOP_GENERATE_SUBMITTED', 'FAIL', `${gen.error} ${gen.detail}`);
      return { ok: false, error: gen.error, detail: gen.detail, stages, stage_results: stageResults };
    }
    stageResults.generate_submitted = true;
    recordStage('F2V_SOP_GENERATE_SUBMITTED', 'PASS',
      `strategy=${gen.strategy} fiber_visited=${gen.fiber_visited || 0} button=${JSON.stringify(gen.button_text || null)}`);

    return {
      ok: true,
      stages,
      stage_results: stageResults,
      summary: {
        generated: true,
        submit_strategy: gen.strategy,
        fiber_visited: gen.fiber_visited || 0,
      },
    };
  } catch (err) {
    recordStage('F2V_SOP_GENERATE_SUBMITTED', 'FAIL', `ERR_F2V_SOP_RUNNER_THREW: ${String(err?.message || err || '')}`);
    return {
      ok: false,
      error: ERR.EXECUTION_THREW,
      detail: String(err?.message || err || ''),
      stages,
      stage_results: stageResults,
    };
  }
}

// ───────────────────────────────────────────────────────────────────────
// Adapter factory + export
// ───────────────────────────────────────────────────────────────────────

function createChromeScriptingAdapter(chromeApi) {
  if (!chromeApi || !chromeApi.scripting) {
    throw new Error('createChromeScriptingAdapter: chrome.scripting is required');
  }
  return {
    executeScript(params) {
      return chromeApi.scripting.executeScript(params);
    },
  };
}

const _api = {
  // Public orchestrator
  executeF2VVisibleSopRunner,
  // Adapter factory
  createChromeScriptingAdapter,
  // MAIN-world helpers (exported for unit tests)
  MAIN_findVisibleCandidatesByExactLabel,
  MAIN_clickStampedElement,
  MAIN_openComposerSettingsPanel,
  MAIN_isComposerSurfaceOpen,
  MAIN_getLauncherOuterHTML,
  MAIN_insertComposerPrompt,
  MAIN_invokeReactFiberSubmit,
  MAIN_stampGenerateButton,
  MAIN_getBottomComposerState,
  MAIN_dismissPromoOverlays,
  // Internal helpers (exported for unit tests)
  _openComposerSettingsPanel,
  _clickVisibleOptionExact,
  _verifySettingsPanelApplied,
  _insertPrompt,
  _clickStart,
  _clickUploadMedia,
  _invokeGenerate,
  // Constants
  F2V_FLOW_QUEUE_RUNNER_BUILD_ID,
  SOP_SEQUENCE,
  ERR,
  F2V_SOP_STAGE_CONTRACT,
  SOP_DEFAULT_SETTLE_MS,
  SOP_DEFAULT_UPLOAD_WAIT_MS,
};

// Dual export: Node test path uses CommonJS module.exports;
// service-worker path picks up `self.__BOSMAX_F2V_FLOW_QUEUE_RUNNER__`.
// `self` is the worker global in MV3 service workers; in Node it is
// typically undefined, so the worker-global assignment is harmless there.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = _api;
}
if (typeof self !== 'undefined') {
  self.__BOSMAX_F2V_FLOW_QUEUE_RUNNER__ = _api;
  try {
    // Visible import-success marker so the operator can confirm the
    // runner loaded before the first F2V job is dispatched.
    // eslint-disable-next-line no-console
    console.log('[BOSMAX_F2V_FLOW_QUEUE_RUNNER] import_ok api_keys=' + Object.keys(_api).length);
  } catch (_) { /* console may be missing in non-worker environments */ }
} else if (typeof globalThis !== 'undefined') {
  // Fallback for environments where `self` is absent but globalThis is
  // present (e.g. some Node test harnesses); keeps direct access viable.
  globalThis.__BOSMAX_F2V_FLOW_QUEUE_RUNNER__ = _api;
}

})(); // end IIFE wrapper
