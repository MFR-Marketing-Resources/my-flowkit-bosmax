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
 *   F2V_SOP_START_CLICKED
 *   F2V_SOP_UPLOAD_CLICKED
 *   F2V_SOP_UPLOAD_WAIT_DONE
 *   F2V_SOP_PROMPT_INSERTED
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

const F2V_FLOW_QUEUE_RUNNER_BUILD_ID = 'flowkit-f2v-runner-audit-2026-06-15a';
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
  ADD_TO_PROMPT_NOT_FOUND: 'ERR_F2V_ADD_TO_PROMPT_NOT_FOUND',
  NEW_PROJECT_FAILED: 'ERR_F2V_NEW_PROJECT_FAILED',
  EXECUTION_THREW: 'ERR_F2V_SOP_RUNNER_THREW',
  GFV2_SUBMIT_ARROW_NOT_FOUND: 'GFV2_SUBMIT_ARROW_NOT_FOUND',
  GFV2_OUTPUT_NOT_READY: 'GFV2_OUTPUT_NOT_READY',
  GFV2_PROJECT_MENU_NOT_FOUND: 'GFV2_PROJECT_MENU_NOT_FOUND',
  GFV2_DOWNLOAD_PROJECT_NOT_FOUND: 'GFV2_DOWNLOAD_PROJECT_NOT_FOUND',
  GFV2_DOWNLOAD_NOT_CONFIRMED: 'GFV2_DOWNLOAD_NOT_CONFIRMED',
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
  function collectAll(root, selector) {
    var out = [];
    var queue = [root || document];
    var seenRoots = new Set();
    while (queue.length > 0) {
      var curr = queue.shift();
      if (!curr || seenRoots.has(curr)) continue;
      seenRoots.add(curr);
      if (curr.querySelectorAll) {
        var direct = curr.querySelectorAll(selector);
        for (var idx = 0; idx < direct.length; idx++) out.push(direct[idx]);
        var descendants = curr.querySelectorAll('*');
        for (var jdx = 0; jdx < descendants.length; jdx++) {
          if (descendants[jdx].shadowRoot && !seenRoots.has(descendants[jdx].shadowRoot)) {
            queue.push(descendants[jdx].shadowRoot);
          }
        }
      }
    }
    return out;
  }
  function findSectionRootByHeading(headingText) {
    var heading = normalize(headingText || '').toLowerCase();
    if (!heading) return null;
    var nodes = collectAll(document, 'h1, h2, h3, h4, h5, h6, label, p, span, div, button');
    var best = null;
    for (var idx2 = 0; idx2 < nodes.length; idx2++) {
      var node = nodes[idx2];
      if (!isVisible(node)) continue;
      var text = normalize(node.textContent || node.getAttribute && node.getAttribute('aria-label') || '').toLowerCase();
      if (text.indexOf(heading) === -1) continue;
      var current = node;
      var depth = 0;
      while (current && depth < 8) {
        if (current === document.body || current === document.documentElement) break;
        if (isVisible(current)) {
          var scopeText = normalize(current.innerText || current.textContent || '').toLowerCase();
          if (
            scopeText.indexOf(heading) >= 0
            && (scopeText.indexOf('1x') >= 0 || scopeText.indexOf('16:9') >= 0 || scopeText.indexOf('9:16') >= 0 || scopeText.indexOf('veo') >= 0 || scopeText.indexOf('omni flash') >= 0)
          ) {
            var rect = current.getBoundingClientRect();
            var area = rect.width * rect.height;
            if (!best || area < best.area) {
              best = { el: current, area: area };
            }
          }
        }
        current = current.parentElement || null;
        depth += 1;
      }
    }
    return best ? best.el : null;
  }
  function isWithinScope(node, scopeRoot) {
    if (!node || !scopeRoot) return false;
    var current = node;
    while (current) {
      if (current === scopeRoot) return true;
      current = current.parentElement || null;
    }
    return false;
  }

  var needle = normalize(targetLabel).toLowerCase();
  var aliasNeedles = (aliases || []).map(function (s) { return normalize(s).toLowerCase(); });
  var preferred = Array.isArray(preferredRoles) && preferredRoles.length > 0 ? preferredRoles : null;
  var videoSectionRoot = findSectionRootByHeading('Video generation default');
  var configScopedNeedle = /^(9:16|16:9|4:3|3:4|1:1|1x|2x|3x|4x)$/i.test(needle)
    || needle.indexOf('veo') >= 0
    || needle.indexOf('omni flash') >= 0;

  var matches = [];
  var visibleCandidates = [];
  var all = collectAll(document,
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
  if (configScopedNeedle && videoSectionRoot) {
    matches.sort(function (a, b) {
      var aScore = isWithinScope(a.el, videoSectionRoot) ? 0 : 1;
      var bScore = isWithinScope(b.el, videoSectionRoot) ? 0 : 1;
      return aScore - bScore;
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
      selected: Boolean(
        m.el.getAttribute && (
          m.el.getAttribute('aria-selected') === 'true'
          || m.el.getAttribute('aria-pressed') === 'true'
          || m.el.getAttribute('data-state') === 'active'
        )
      ),
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
  function findStamped(root) {
    var queue = [root || document];
    var seenRoots = new Set();
    while (queue.length > 0) {
      var curr = queue.shift();
      if (!curr || seenRoots.has(curr)) continue;
      seenRoots.add(curr);
      if (curr.querySelector) {
        var found = curr.querySelector('[' + stampAttr + '="' + stampId + '"]');
        if (found) return found;
      }
      if (curr.querySelectorAll) {
        var descendants = curr.querySelectorAll('*');
        for (var idx = 0; idx < descendants.length; idx++) {
          if (descendants[idx].shadowRoot && !seenRoots.has(descendants[idx].shadowRoot)) {
            queue.push(descendants[idx].shadowRoot);
          }
        }
      }
    }
    return null;
  }
  var el = findStamped(document);
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
    function matchesPromptMarker(value) {
      var label = lower(value || '');
      return label.indexOf('what do you want to create') >= 0
        || label.indexOf('what do you want') >= 0
        || label.indexOf('editable text') >= 0
        || label.indexOf('create') >= 0
        || label.indexOf('generate') >= 0;
    }
    var promptLikeNodes = document.querySelectorAll('textarea, [contenteditable="true"], [role="textbox"], [aria-label="Editable text"], input[type="text"]');
    for (var e0 = 0; e0 < promptLikeNodes.length; e0++) {
      if (!isVisible(promptLikeNodes[e0])) continue;
      if ((promptLikeNodes[e0].getAttribute && promptLikeNodes[e0].getAttribute('aria-label')) === 'Editable text') {
        return promptLikeNodes[e0];
      }
    }
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
        if (matchesPromptMarker(label)) {
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
      if (!matchesPromptMarker(markerText)) continue;
      var owner = toInteractive(placeholderNodes[k2]) || (placeholderNodes[k2].closest && placeholderNodes[k2].closest('[data-slate-editor="true"], [contenteditable="true"], [role="textbox"], [aria-label="Editable text"], textarea, input, form, section, article, div'));
      if (owner && isVisible(owner)) return owner;
      return placeholderNodes[k2];
    }
    var inputs = document.querySelectorAll('textarea, [contenteditable="true"], [role="textbox"], [aria-label="Editable text"], input[type="text"]');
    for (var m2 = 0; m2 < inputs.length; m2++) {
      if (!isVisible(inputs[m2])) continue;
      var probe = lower([
        inputs[m2].getAttribute && (inputs[m2].getAttribute('placeholder') || ''),
        inputs[m2].getAttribute && (inputs[m2].getAttribute('aria-label') || ''),
        inputs[m2].textContent || '',
      ].join(' '));
      if (matchesPromptMarker(probe)) return inputs[m2];
    }
    for (var n2 = 0; n2 < inputs.length; n2++) {
      if (isVisible(inputs[n2])) return inputs[n2];
    }
    return null;
  }
  function getComposerRoot() {
    var prompt = getPromptField();
    if (!prompt || !prompt.closest) return prompt;
    var formOwner = prompt.closest('form, [role="form"]');
    if (formOwner && formOwner.getBoundingClientRect) return formOwner;
    var best = prompt;
    var promptRect = prompt.getBoundingClientRect ? prompt.getBoundingClientRect() : null;
    var current = prompt.parentElement || null;
    var depth = 0;
    while (current && depth < 6) {
      if (current === document.body || current === document.documentElement) break;
      if (current.getBoundingClientRect && isVisible(current)) {
        var rect = current.getBoundingClientRect();
        var hasControls = current.querySelector && current.querySelector('button, [role="button"], [aria-label="Editable text"], [role="textbox"], textarea, [contenteditable="true"]');
        if (
          hasControls
          && rect.width >= ((promptRect && promptRect.width) || 0)
          && rect.height >= ((promptRect && promptRect.height) || 0)
          && rect.width <= 960
          && rect.height <= 520
        ) {
          best = current;
          if (rect.width >= 240 && rect.height >= 120) break;
        }
      }
      current = current.parentElement || null;
      depth += 1;
    }
    return best;
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
  function isProjectEditorUrl(url) {
    return /^https:\/\/labs\.google\/fx(?:\/[^/]+)?\/tools\/flow\/project\/[^/?#]+(?:[/?#]|$)/.test(String(url || ''));
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
    function findSectionSurfaceByHeading(headingText) {
      var heading = lower(headingText || '');
      if (!heading) return null;
      var nodes = collectAll(document, 'h1, h2, h3, h4, h5, h6, label, p, span, div, button');
      var best = null;
      for (var hIdx = 0; hIdx < nodes.length; hIdx++) {
        var node = nodes[hIdx];
        if (!isVisible(node)) continue;
        var text = lower(node.textContent || node.getAttribute && node.getAttribute('aria-label') || '');
        if (text.indexOf(heading) === -1) continue;
        var current = node;
        var depth = 0;
        while (current && depth < 8) {
          if (current === document.body || current === document.documentElement) break;
          if (isVisible(current)) {
            var scopeText = lower(current.innerText || current.textContent || '');
            if (
              scopeText.indexOf(heading) >= 0
              && (scopeText.indexOf('1x') >= 0 || scopeText.indexOf('16:9') >= 0 || scopeText.indexOf('9:16') >= 0 || scopeText.indexOf('veo') >= 0 || scopeText.indexOf('omni flash') >= 0)
            ) {
              var rect = current.getBoundingClientRect();
              var area = rect.width * rect.height;
              if (!best || area < best.area) {
                best = { el: current, area: area };
              }
            }
          }
          current = current.parentElement || null;
          depth += 1;
        }
      }
      return best ? best.el : null;
    }
    var drawerSurface = findSectionSurfaceByHeading('Video generation default')
      || findSectionSurfaceByHeading('Image generation default');
    if (drawerSurface) {
      return {
        el: drawerSurface,
        hits: 4,
        markers: ['generation default', '1x'],
        role: drawerSurface.getAttribute('role') || null,
        distance_to_composer: distanceBetween(drawerSurface, getComposerRoot()),
      };
    }
    var surfaces = collectAll(document, '[role="menu"], [role="listbox"], [role="dialog"], div.settings-panel, div[class*="settings"], div[class*="menu"], div[class*="dropdown"], div[class*="modal"], aside, section, div[role="presentation"]');
    var best = null;
    var composer = getComposerRoot();
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
      var distanceToComposer = distanceBetween(surface, composer);
      var nearComposer = Boolean(composer) && distanceToComposer <= 680;
      if (!nearComposer && composer) continue;
      if (hits > 0 && (!best || hits > best.hits || (hits === best.hits && distanceToComposer < best.distance_to_composer))) {
        best = {
          el: surface,
          hits: hits,
          markers: markers,
          role: surface.getAttribute('role') || null,
          distance_to_composer: distanceToComposer,
        };
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
      has_view_settings: /\bview\s+settings\b/i.test(combined),
      has_plain_settings: /(^|\s)settings(\s|$)/i.test(combined),
      has_model_text: /(veo|nano\s*banana|gemini|imagen|model)/i.test(combined),
      has_model: /(veo|nano\s*banana|gemini|imagen|model)/i.test(combined) || /(veo|nano\s*banana|gemini|imagen)/i.test(containerText),
      has_settings: /(settings|view\s+settings|config|configure|tune|sliders)/i.test(combined + ' ' + containerText),
      has_agent_panel_context: /(develop a storyboard|build a visual moodboard|generate concept art|agent instructions|editable text|create|settings)/i.test(containerText),
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
    if (strategyId === 'view_settings_button') {
      return candidates.filter(function (c) {
        return c.has_view_settings && c.distance_to_composer <= 520;
      });
    }
    if (strategyId === 'composer_settings_button') {
      return candidates.filter(function (c) {
        return (c.near_composer || c.distance_to_composer <= 680) && c.has_plain_settings && !c.has_view_settings;
      });
    }
    if (strategyId === 'agent_panel_settings_button') {
      return candidates.filter(function (c) {
        return (c.has_plain_settings || String(c.combined_lower || '') === 'settings')
          && !c.has_view_settings
          && c.has_agent_panel_context
          && !/^(more|more options|go back|search|sort & filter|add media|product help)$/i.test(String(c.combined_lower || ''))
          && (c.near_composer || c.distance_to_composer <= 2200);
      });
    }
    if (strategyId === 'secret_settings_icon') {
      return candidates.filter(function (c) {
        return c.has_agent_panel_context
          && !String(c.combined || '').trim()
          && Number(c.width || 0) <= 64
          && Number(c.height || 0) <= 64
          && c.bbox
          && Number(c.bbox.x || 0) >= 1400;
      });
    }
    if (strategyId === 'model_chip') {
      return candidates.filter(function (c) {
        return c.has_model_text && (c.popup || c.near_composer || c.has_model_context);
      });
    }
    if (strategyId === 'dropdown_adjacent') {
      return candidates.filter(function (c) {
        if (!((c.popup || c.role === 'combobox' || c.has_arrow) && (c.near_composer || c.has_model_context))) {
          return false;
        }
        var combined = String(c.combined_lower || '');
        if (/^(create|agent|agent instructions|more|more options|search|sort & filter)$/.test(combined)) {
          return false;
        }
        return true;
      });
    }
    if (strategyId === 'config_pill') {
      return candidates.filter(function (c) {
        return c.near_composer && (c.combo_hits >= 2 || ((c.has_ratio || c.has_count) && (c.has_mode || c.has_model)));
      });
    }
    if (strategyId === 'settings_icon') {
      return candidates.filter(function (c) {
        var selfSignal = /(settings|view\s+settings|config|configure|tune|sliders)/i.test(
          String(c.combined || '') + ' ' + String(c.icon_text || ''),
        );
        return c.near_composer
          && !c.has_count
          && !c.has_ratio
          && !c.has_model
          && !c.has_mode
          && (selfSignal || (c.has_arrow && c.has_agent_panel_context));
      });
    }
    return candidates.filter(function (c) {
      var label = String(c.combined_lower || '');
      if (/^(more|more options|go back|search|sort & filter|add media|product help|all media|characters|view scenes|tools|view trash)$/i.test(label)) {
        return false;
      }
      return c.near_composer && (c.combo_hits >= 2 || c.has_model || c.has_settings);
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
    { id: 'composer_settings_button', label: 'plain settings button near composer' },
    { id: 'agent_panel_settings_button', label: 'agent panel settings button' },
    { id: 'secret_settings_icon', label: 'secret settings icon in agent panel' },
    { id: 'settings_icon', label: 'settings/sliders icon near composer' },
    { id: 'bottom_composer_config_pill', label: 'bottom composer config pill' },
    { id: 'model_chip', label: 'current model chip' },
    { id: 'config_pill', label: 'config pill near composer' },
    { id: 'dropdown_adjacent', label: 'dropdown adjacent to model label' },
    { id: 'view_settings_button', label: 'view settings button near composer' },
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
  function findStamped(root) {
    var queue = [root || document];
    var seenRoots = new Set();
    while (queue.length > 0) {
      var curr = queue.shift();
      if (!curr || seenRoots.has(curr)) continue;
      seenRoots.add(curr);
      if (curr.querySelector) {
        var found = curr.querySelector('[' + stampAttr + '="' + stampId + '"]');
        if (found) return found;
      }
      if (curr.querySelectorAll) {
        var descendants = curr.querySelectorAll('*');
        for (var idx = 0; idx < descendants.length; idx++) {
          if (descendants[idx].shadowRoot && !seenRoots.has(descendants[idx].shadowRoot)) {
            queue.push(descendants[idx].shadowRoot);
          }
        }
      }
    }
    return null;
  }
  var el = findStamped(document);
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
  function findSectionSurfaceByHeading(headingText) {
    var heading = String(headingText || '').replace(/\s+/g, ' ').trim().toLowerCase();
    if (!heading) return null;
    var nodes = collectAll(document, 'h1, h2, h3, h4, h5, h6, label, p, span, div, button');
    var best = null;
    for (var hIdx = 0; hIdx < nodes.length; hIdx++) {
      var node = nodes[hIdx];
      if (!isVisible(node)) continue;
      var text = String(node.textContent || node.getAttribute && node.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().toLowerCase();
      if (text.indexOf(heading) === -1) continue;
      var current = node;
      var depth = 0;
      while (current && depth < 8) {
        if (current === document.body || current === document.documentElement) break;
        if (isVisible(current)) {
          var scopeText = String(current.innerText || current.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
          if (
            scopeText.indexOf(heading) >= 0
            && (scopeText.indexOf('1x') >= 0 || scopeText.indexOf('16:9') >= 0 || scopeText.indexOf('9:16') >= 0 || scopeText.indexOf('veo') >= 0 || scopeText.indexOf('omni flash') >= 0)
          ) {
            var rect = current.getBoundingClientRect();
            var area = rect.width * rect.height;
            if (!best || area < best.area) {
              best = { el: current, area: area };
            }
          }
        }
        current = current.parentElement || null;
        depth += 1;
      }
    }
    return best ? best.el : null;
  }
  function isProjectEditorUrl(url) {
    return /^https:\/\/labs\.google\/fx(?:\/[^/]+)?\/tools\/flow\/project\/[^/?#]+(?:[/?#]|$)/.test(String(url || ''));
  }
  function getPromptField() {
    var candidates = document.querySelectorAll('[aria-label="Editable text"], [role="textbox"], [data-slate-editor="true"][contenteditable="true"], textarea, [contenteditable="true"]');
    var visible = [];
    for (var i2 = 0; i2 < candidates.length; i2++) {
      if (!isVisible(candidates[i2])) continue;
      visible.push(candidates[i2]);
    }
    if (visible.length) {
      visible.sort(function (a, b) { return b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom; });
      for (var j2 = 0; j2 < visible.length; j2++) {
        if ((visible[j2].getAttribute && visible[j2].getAttribute('aria-label')) === 'Editable text') {
          return visible[j2];
        }
      }
      return visible[0];
    }
    return null;
  }
  function getComposerRoot() {
    var prompt = getPromptField();
    if (!prompt || !prompt.closest) return prompt;
    var formOwner = prompt.closest('form, [role="form"]');
    if (formOwner && formOwner.getBoundingClientRect) return formOwner;
    var best = prompt;
    var promptRect = prompt.getBoundingClientRect ? prompt.getBoundingClientRect() : null;
    var current = prompt.parentElement || null;
    var depth = 0;
    while (current && depth < 6) {
      if (current === document.body || current === document.documentElement) break;
      if (current.getBoundingClientRect && isVisible(current)) {
        var rect = current.getBoundingClientRect();
        var hasControls = current.querySelector && current.querySelector('button, [role="button"], [aria-label="Editable text"], [role="textbox"], textarea, [contenteditable="true"]');
        if (
          hasControls
          && rect.width >= ((promptRect && promptRect.width) || 0)
          && rect.height >= ((promptRect && promptRect.height) || 0)
          && rect.width <= 960
          && rect.height <= 520
        ) {
          best = current;
          if (rect.width >= 240 && rect.height >= 120) break;
        }
      }
      current = current.parentElement || null;
      depth += 1;
    }
    return best;
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
  var currentUrl = String(window.location && window.location.href || '');
  if (!isProjectEditorUrl(currentUrl)) {
    return { ok: false, reason: 'not_project_editor', current_url: currentUrl, found_markers: [] };
  }
  var drawerSurface = findSectionSurfaceByHeading('Video generation default')
    || findSectionSurfaceByHeading('Image generation default');
  if (drawerSurface) {
    return {
      ok: true,
      role: drawerSurface.getAttribute('role') || 'drawer',
      marker_hits: 2,
      found_markers: ['generation default', '1x'],
      distance_to_composer: distanceBetween(drawerSurface, getComposerRoot()),
      current_url: currentUrl,
    };
  }
  var composer = getComposerRoot();
  if (!composer) {
    return { ok: false, reason: 'composer_not_visible', current_url: currentUrl, found_markers: [] };
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
    var distanceToComposer = distanceBetween(surfaces[i], composer);
    if (distanceToComposer > 680) continue;
    // Require at least 1 marker hit to prevent matching random workspace wrappers
    if (markerHits >= 1 && (!best || markerHits > best.marker_hits || (markerHits === best.marker_hits && distanceToComposer < best.distance_to_composer))) {
      best = {
        role: surfaces[i].getAttribute('role'),
        marker_hits: markerHits,
        found_markers: foundMarkers,
        distance_to_composer: distanceToComposer,
      };
    }
  }
  if (best) return { ok: true, role: best.role, marker_hits: best.marker_hits, found_markers: best.found_markers || [], distance_to_composer: best.distance_to_composer };
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
  function matchesPromptMarker(value) {
    var label = normalize(value).toLowerCase();
    return label.indexOf('what do you want to create') >= 0
      || label.indexOf('what do you want') >= 0
      || label.indexOf('editable text') >= 0
      || label.indexOf('create') >= 0
      || label.indexOf('generate') >= 0;
  }
  function findSlatePromptEditor() {
    var exactEditable = document.querySelectorAll('[aria-label="Editable text"], [role="textbox"]');
    for (var e0 = 0; e0 < exactEditable.length; e0++) {
      if (!isVisible(exactEditable[e0])) continue;
      var exactProbe = normalize([
        exactEditable[e0].getAttribute && (exactEditable[e0].getAttribute('aria-label') || exactEditable[e0].getAttribute('placeholder') || ''),
        exactEditable[e0].textContent || '',
      ].join(' '));
      if (matchesPromptMarker(exactProbe)) return exactEditable[e0];
    }
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
    if (!candidates.length) {
      var fallbackEditors = document.querySelectorAll('textarea, [contenteditable="true"], [role="textbox"], [aria-label="Editable text"], input[type="text"]');
      for (var f = 0; f < fallbackEditors.length; f++) {
        if (!isVisible(fallbackEditors[f])) continue;
        candidates.push(fallbackEditors[f]);
      }
    }
    if (!candidates.length) return null;
    var withPlaceholder = candidates.filter(function (el) {
      var ph = el.querySelector && el.querySelector('[data-slate-placeholder]');
      var label = normalize([
        ph && ph.textContent || '',
        el.getAttribute && (el.getAttribute('placeholder') || el.getAttribute('aria-label') || '') || '',
        el.textContent || '',
      ].join(' '));
      return matchesPromptMarker(label);
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
    var inputs = document.querySelectorAll('textarea, [contenteditable="true"], [role="textbox"], [aria-label="Editable text"], input[type="text"]');
    for (var n = 0; n < inputs.length; n++) {
      var el = inputs[n];
      if (!isVisible(el)) continue;
      var ph = (el.getAttribute && el.getAttribute('placeholder')) || '';
      var al = (el.getAttribute && el.getAttribute('aria-label')) || '';
      var probe = normalize(ph + ' ' + al + ' ' + (el.textContent || ''));
      if (matchesPromptMarker(probe)) { target = el; break; }
    }
    if (!target) {
      for (var p = 0; p < inputs.length; p++) {
        if (isVisible(inputs[p])) { target = inputs[p]; break; }
      }
    }
  }
  if (!target) return { ok: false, reason: 'no_prompt_field_visible' };

  try { target.scrollIntoView({ block: 'center' }); } catch (e) { /* noop */ }
  var isSlate = (target.getAttribute && target.getAttribute('data-slate-editor') === 'true')
    || (target.getAttribute && target.getAttribute('role') === 'textbox')
    || (target.getAttribute && target.getAttribute('aria-label') === 'Editable text')
    || Boolean(target.isContentEditable);
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
      var icon = btn.querySelector('i.google-symbols, .google-symbols, .material-symbols-outlined, .material-symbols-rounded, .material-symbols-sharp, .material-icons, [class*="material-symbol"]');
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
  var composer = document.querySelector('[aria-label="Editable text"], [role="textbox"], [data-slate-editor="true"][contenteditable="true"], textarea[placeholder*="What do you want"], textarea, [contenteditable="true"]');
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
        disabled: Boolean(b.disabled || b.getAttribute('aria-disabled') === 'true'),
      };
    }
  }
  return { ok: false, reason: 'no_generate_button_visible' };
}

/**
 * MAIN-world: locate the visible composer-side asset-picker launcher.
 * Live Flow renders this as the left-side "+ / add_2 Create" button near
 * the prompt composer. It must be distinguished from the right-side
 * arrow_forward Create / Generate submit button.
 */
function MAIN_stampAssetPickerLauncher(stampAttr) {
  function normalize(s) {
    return String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  }
  function lower(s) {
    return normalize(s).toLowerCase();
  }
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  function collectAll(root, selector) {
    var out = [];
    var queue = [root || document];
    var seen = new Set();
    while (queue.length > 0) {
      var curr = queue.shift();
      if (!curr || seen.has(curr)) continue;
      seen.add(curr);
      if (curr.querySelectorAll) {
        var direct = curr.querySelectorAll(selector);
        for (var i = 0; i < direct.length; i++) out.push(direct[i]);
        var descendants = curr.querySelectorAll('*');
        for (var j = 0; j < descendants.length; j++) {
          if (descendants[j].shadowRoot && !seen.has(descendants[j].shadowRoot)) {
            queue.push(descendants[j].shadowRoot);
          }
        }
      }
    }
    return out;
  }
  function findComposer() {
    function matchesPromptMarker(value) {
      var label = lower(value || '');
      return label.indexOf('what do you want to create') >= 0
        || label.indexOf('what do you want') >= 0
        || label.indexOf('editable text') >= 0
        || label.indexOf('create') >= 0
        || label.indexOf('generate') >= 0;
    }
    var nodes = document.querySelectorAll('[aria-label="Editable text"], [role="textbox"], [data-slate-editor="true"][contenteditable="true"], textarea, [contenteditable="true"], input[type="text"]');
    var scored = [];
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      if (!isVisible(node)) continue;
      var text = normalize(node.textContent || '');
      var ariaLabel = normalize(node.getAttribute && node.getAttribute('aria-label') || '');
      var placeholder = normalize(node.getAttribute && node.getAttribute('placeholder') || '');
      var probe = text + ' ' + ariaLabel + ' ' + placeholder;
      var rect = node.getBoundingClientRect();
      var score = 0;
      if (ariaLabel === 'Editable text') score += 120;
      if (matchesPromptMarker(probe)) score += 100;
      if (node.getAttribute && node.getAttribute('role') === 'textbox') score += 35;
      if (node.getAttribute && node.getAttribute('contenteditable') === 'true') score += 25;
      if (rect.bottom >= (window.innerHeight * 0.55)) score += 20;
      scored.push({ el: node, score: score, bottom: rect.bottom });
    }
    if (scored.length === 0) return null;
    scored.sort(function (a, b) {
      if (b.score !== a.score) return b.score - a.score;
      return b.bottom - a.bottom;
    });
    return scored[0].el;
  }
  function collectComposerRoots(composer) {
    var roots = [];
    var seen = new Set();
    var current = composer;
    for (var depth = 0; current && depth < 5; depth++) {
      if (!seen.has(current)) {
        roots.push(current);
        seen.add(current);
      }
      current = current.parentElement;
    }
    return roots;
  }
  function looksExcluded(btnText) {
    return btnText.indexOf('create with flow') >= 0
      || btnText.indexOf('create new project') >= 0
      || btnText === 'create new'
      || btnText.indexOf('create project') >= 0
      || btnText.indexOf('arrow_forward') >= 0
      || btnText.indexOf('generate') >= 0;
  }
  function scoreCandidate(el, composerRect, inComposerRoot) {
    var text = lower(el.textContent || el.getAttribute('aria-label') || '');
    if (!text || looksExcluded(text)) return null;
    var hasAddMediaLabel = text.indexOf('add media') >= 0 || text.indexOf('upload media') >= 0;
    var hasDropMediaLabel = text.indexOf('drop media') >= 0 || text.indexOf('start creating') >= 0;
    var hasAddGlyph = text.indexOf('add_2') >= 0 || text.indexOf(' add ') >= 0 || text === 'add' || text === 'add_2';
    var hasCreateLabel = text.indexOf('create') >= 0;
    var hasPlusGlyph = normalize(el.textContent || '') === '+';
    if (!hasAddMediaLabel && !hasDropMediaLabel && !hasAddGlyph && !hasCreateLabel && !hasPlusGlyph) return null;
    var rect = el.getBoundingClientRect();
    var score = 0;
    if (inComposerRoot) score += 40;
    if (hasDropMediaLabel) score += 80;
    if (hasAddMediaLabel) score += 70;
    if (hasAddGlyph || hasPlusGlyph) score += 25;
    if (hasCreateLabel) score += 10;
    if (composerRect) {
      var composerMidX = composerRect.left + (composerRect.width / 2);
      var launcherMidY = rect.top + (rect.height / 2);
      var composerMidY = composerRect.top + (composerRect.height / 2);
      if (rect.left <= composerMidX) score += 20;
      score -= Math.abs(launcherMidY - composerMidY) / 20;
      score -= Math.abs(rect.left - composerRect.left) / 40;
    }
    return {
      el: el,
      rect: rect,
      score: score,
      text: normalize(el.textContent || el.getAttribute('aria-label') || ''),
      strategy: hasDropMediaLabel
        ? 'start_drop_media_launcher'
        : hasAddMediaLabel
          ? 'add_media_launcher'
          : hasAddGlyph || hasPlusGlyph
            ? 'add_create_launcher'
            : 'create_launcher',
    };
  }

  var composer = findComposer();
  var composerRect = composer && composer.getBoundingClientRect ? composer.getBoundingClientRect() : null;
  var roots = composer ? collectComposerRoots(composer) : [];
  roots.push(document);

  var candidates = [];
  var seenEls = new Set();
  for (var r = 0; r < roots.length; r++) {
    var root = roots[r];
    var buttons = collectAll(root, 'button, [role="button"]');
    for (var b = 0; b < buttons.length; b++) {
      var btn = buttons[b];
      if (!isVisible(btn) || seenEls.has(btn)) continue;
      seenEls.add(btn);
      var scored = scoreCandidate(btn, composerRect, root !== document);
      if (scored) candidates.push(scored);
    }
  }
  if (!candidates.length) return { ok: false, reason: 'no_asset_picker_launcher_visible' };
  candidates.sort(function (a, b) {
    if (b.score !== a.score) return b.score - a.score;
    if (a.rect.left !== b.rect.left) return a.rect.left - b.rect.left;
    return a.rect.top - b.rect.top;
  });
  var best = candidates[0];
  var attr = String(stampAttr || 'data-bosmax-option');
  var id = attr + '-asset-launcher-' + Date.now();
  best.el.setAttribute(attr, id);
  return {
    ok: true,
    stamp_id: id,
    stamp_attr: attr,
    text: best.text,
    strategy: best.strategy,
    bbox: {
      x: best.rect.left,
      y: best.rect.top,
      width: best.rect.width,
      height: best.rect.height,
    },
  };
}

/**
 * MAIN-world: strict B.2A composer-scoped add-media launcher scan.
 * Returns either:
 *   - ok:true with composer-scoped launcher evidence
 *   - ok:false reason=wrong_scope when only non-composer add candidates exist
 *   - ok:false reason=not_found when no viable add-media candidate exists
 */
function MAIN_findComposerAddMediaLauncher(stampAttr) {
  function normalize(s) {
    return String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  }
  function lower(s) {
    return normalize(s).toLowerCase();
  }
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  function collectAll(root, selector) {
    var out = [];
    var queue = [root || document];
    var seen = new Set();
    while (queue.length > 0) {
      var curr = queue.shift();
      if (!curr || seen.has(curr)) continue;
      seen.add(curr);
      if (curr.querySelectorAll) {
        var direct = curr.querySelectorAll(selector);
        for (var i = 0; i < direct.length; i++) out.push(direct[i]);
        var descendants = curr.querySelectorAll('*');
        for (var j = 0; j < descendants.length; j++) {
          if (descendants[j].shadowRoot && !seen.has(descendants[j].shadowRoot)) {
            queue.push(descendants[j].shadowRoot);
          }
        }
      }
    }
    return out;
  }
  function distanceBetweenRects(a, b) {
    if (!a || !b) return Number.MAX_SAFE_INTEGER;
    var ax = a.left + (a.width / 2);
    var ay = a.top + (a.height / 2);
    var bx = b.left + (b.width / 2);
    var by = b.top + (b.height / 2);
    var dx = ax - bx;
    var dy = ay - by;
    return Math.sqrt((dx * dx) + (dy * dy));
  }
  function findComposer() {
    return document.querySelector('[aria-label="Editable text"], [role="textbox"], [data-slate-editor="true"][contenteditable="true"], textarea[placeholder*="What do you want"], textarea, [contenteditable="true"]');
  }
  function findComposerRoot(composer) {
    if (!composer || !composer.closest) return composer;
    var formOwner = composer.closest('form, [role="form"]');
    if (formOwner && formOwner.getBoundingClientRect) return formOwner;
    var best = composer;
    var promptRect = composer.getBoundingClientRect ? composer.getBoundingClientRect() : null;
    var current = composer.parentElement || null;
    var depth = 0;
    while (current && depth < 6) {
      if (current === document.body || current === document.documentElement) break;
      if (current.getBoundingClientRect && isVisible(current)) {
        var rect = current.getBoundingClientRect();
        var hasControls = current.querySelector && current.querySelector('button, [role="button"], [aria-label="Editable text"], [role="textbox"], textarea, [contenteditable="true"]');
        if (
          hasControls
          && rect.width >= ((promptRect && promptRect.width) || 0)
          && rect.height >= ((promptRect && promptRect.height) || 0)
          && rect.width <= 960
          && rect.height <= 520
        ) {
          best = current;
          if (rect.width >= 240 && rect.height >= 120) break;
        }
      }
      current = current.parentElement || null;
      depth += 1;
    }
    return best;
  }
  function findGenerateButton(composer) {
    if (!composer) return null;
    var roots = [];
    var current = composer;
    for (var depth = 0; current && depth < 6; depth++) {
      roots.push(current);
      current = current.parentElement;
    }
    var seen = new Set();
    for (var r = 0; r < roots.length; r++) {
      var buttons = roots[r].querySelectorAll ? roots[r].querySelectorAll('button, [role="button"]') : [];
      for (var i = 0; i < buttons.length; i++) {
        var btn = buttons[i];
        if (!isVisible(btn) || seen.has(btn)) continue;
        seen.add(btn);
        var combined = lower(
          (btn.textContent || '')
          + ' '
          + (btn.getAttribute && btn.getAttribute('aria-label') || '')
          + ' '
          + (btn.getAttribute && btn.getAttribute('title') || '')
        );
        if (combined.indexOf('arrow_forward') >= 0 || combined.indexOf('generate') >= 0 || combined.indexOf('create') >= 0) {
          return btn;
        }
      }
    }
    return null;
  }
  function isRejectedText(text) {
    return text.indexOf('create with flow') >= 0
      || text.indexOf('create new project') >= 0
      || text.indexOf('create project') >= 0
      || text.indexOf('arrow_forward') >= 0
      || text.indexOf('generate') >= 0;
  }
  function isLibraryScoped(el) {
    var current = el;
    for (var depth = 0; current && depth < 8; depth++) {
      var joined = lower(
        (current.id || '')
        + ' '
        + (current.className || '')
        + ' '
        + (current.getAttribute && current.getAttribute('aria-label') || '')
        + ' '
        + (current.getAttribute && current.getAttribute('data-testid') || '')
      );
      var text = lower(current.textContent || '');
      var hasEditorToolbarPeers = text.indexOf('sort & filter') >= 0
        || text.indexOf('product help') >= 0
        || text.indexOf('view settings') >= 0;
      if (hasEditorToolbarPeers && text.indexOf('add media') >= 0) {
        return false;
      }
      if (
        joined.indexOf('asset-library') >= 0
        || joined.indexOf('sidebar') >= 0
        || joined.indexOf('library') >= 0
        || joined.indexOf('drawer') >= 0
        || text.indexOf('all media') >= 0
        || text.indexOf('uploads') >= 0
        || text.indexOf('recent') >= 0
        || text.indexOf('characters') >= 0
        || text.indexOf('tools') >= 0
        || text.indexOf('view trash') >= 0
      ) {
        return true;
      }
      current = current.parentElement;
    }
    return false;
  }
  function buildEvidence(candidate, accepted) {
    var rect = candidate.el.getBoundingClientRect();
    return {
      ok: Boolean(accepted),
      stamp_id: candidate.id,
      stamp_attr: candidate.attr,
      text: candidate.text || null,
      aria_label: candidate.aria_label || null,
      role: candidate.role || null,
      tag: candidate.tag || null,
      bbox: {
        x: rect.left,
        y: rect.top,
        width: rect.width,
        height: rect.height,
      },
      near_composer: Boolean(candidate.near_composer),
      near_prompt_field: Boolean(candidate.near_prompt_field),
      near_generate_button: Boolean(candidate.near_generate_button),
      candidate_source: 'composer_scoped_scan',
    };
  }

  var composer = findComposer();
  if (!composer || !isVisible(composer)) {
    return { ok: false, reason: 'editor_not_opened' };
  }
  var composerRect = composer.getBoundingClientRect();
  var promptRect = composerRect;
  var composerRoot = findComposerRoot(composer);
  var generate = findGenerateButton(composer);
  var generateRect = generate && generate.getBoundingClientRect ? generate.getBoundingClientRect() : null;

  var nodes = collectAll(document, 'button, [role="button"], [aria-label], [title]');
  var accepted = [];
  var rejected = [];
  var seen = new Set();
  var attr = String(stampAttr || 'data-bosmax-option');

  for (var i = 0; i < nodes.length; i++) {
    var el = nodes[i];
    if (!el || seen.has(el) || !isVisible(el)) continue;
    seen.add(el);
    var text = normalize(el.textContent || '');
    var ariaLabel = normalize(el.getAttribute && el.getAttribute('aria-label') || '');
    var title = normalize(el.getAttribute && el.getAttribute('title') || '');
    var combined = lower(text + ' ' + ariaLabel + ' ' + title);
    if (!combined || isRejectedText(combined)) continue;

    var hasAddMedia = combined.indexOf('add media') >= 0 || combined.indexOf('upload media') >= 0;
    var hasAddSignal = combined === 'add' || combined === 'add_2' || combined.indexOf('add ') >= 0 || combined.indexOf(' add') >= 0;
    var hasPlusSignal = text === '+' || ariaLabel === '+' || title === '+';
    var hasComposerCreate = combined.indexOf('create') >= 0 && (combined.indexOf('add_2') >= 0 || combined.indexOf('add') >= 0 || hasPlusSignal);
    if (!hasAddMedia && !hasAddSignal && !hasPlusSignal && !hasComposerCreate) continue;

    var rect = el.getBoundingClientRect();
    var inComposerRoot = Boolean(composerRoot && composerRoot.contains && composerRoot.contains(el));
    var nearComposer = distanceBetweenRects(rect, composerRect) <= 420;
    var nearPromptField = distanceBetweenRects(rect, promptRect) <= 420;
    var nearGenerateButton = generateRect ? distanceBetweenRects(rect, generateRect) <= 420 : false;
    var libraryScoped = isLibraryScoped(el);

    var score = 0;
    if (hasAddMedia) score += 120;
    if (hasAddSignal || hasPlusSignal) score += 30;
    if (hasComposerCreate) score += 10;
    if (inComposerRoot) score += 90;
    if (nearComposer) score += 70;
    if (nearPromptField) score += 40;
    if (nearGenerateButton) score += 20;
    if (rect.left <= (composerRect.left + (composerRect.width / 2))) score += 20;
    if (libraryScoped) score -= 260;

    var id = attr + '-b2a-launcher-' + Date.now() + '-' + i;
    el.setAttribute(attr, id);
    var candidate = {
      el: el,
      id: id,
      attr: attr,
      text: text || ariaLabel || title || null,
      aria_label: ariaLabel || null,
      role: (el.getAttribute && el.getAttribute('role')) || null,
      tag: String(el.tagName || '').toLowerCase(),
      has_add_media: hasAddMedia,
      near_composer: nearComposer,
      near_prompt_field: nearPromptField,
      near_generate_button: nearGenerateButton,
      score: score,
    };
    // A valid B.2A launcher MUST be composer-local. The top-toolbar "Add Media"
    // button matches hasAddMedia but sits far from the composer (all proximity
    // signals false) — clicking it opens the asset-library surface, not the
    // composer upload picker. So hasAddMedia is NOT sufficient on its own:
    // every candidate must be inside the composer root or within proximity of
    // the composer / prompt field / generate button. Candidates whose proximity
    // signals are all false (e.g. the top-toolbar Add Media) are rejected as
    // wrong scope. Live evidence: bbox y≈22 (page top), near_composer=false.
    var composerLocal =
      inComposerRoot || nearComposer || nearPromptField || nearGenerateButton;
    var isAccepted = !libraryScoped && composerLocal;
    if (isAccepted) accepted.push(candidate);
    else rejected.push(candidate);
  }

  function sortCandidates(a, b) {
    if (Boolean(b.has_add_media) !== Boolean(a.has_add_media)) {
      return Boolean(b.has_add_media) ? 1 : -1;
    }
    if (b.score !== a.score) return b.score - a.score;
    var ar = a.el.getBoundingClientRect();
    var br = b.el.getBoundingClientRect();
    if (ar.left !== br.left) return ar.left - br.left;
    return ar.top - br.top;
  }

  if (accepted.length > 0) {
    accepted.sort(sortCandidates);
    var bestAccepted = accepted[0];
    return buildEvidence(bestAccepted, true);
  }
  if (rejected.length > 0) {
    rejected.sort(sortCandidates);
    var bestRejected = rejected[0];
    var rejectedEvidence = buildEvidence(bestRejected, false);
    rejectedEvidence.reason = 'wrong_scope';
    return rejectedEvidence;
  }
  return { ok: false, reason: 'not_found' };
}

/**
 * MAIN-world: verify the upload picker/modal is open and discover the
 * upload action without clicking it.
 */
// READ-ONLY diagnostic: enumerate every visible clickable element's label text /
// aria-label / role. Used only when the upload menu item is not matched, so the
// telemetry reveals the REAL Google Flow V2 add-menu labels (no clicks performed).
function MAIN_dumpVisibleClickableTexts() {
  function norm(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); }
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  function collectAll(selector) {
    var out = [];
    var queue = [document];
    var seen = new Set();
    while (queue.length > 0) {
      var curr = queue.shift();
      if (!curr || seen.has(curr)) continue;
      seen.add(curr);
      if (curr.querySelectorAll) {
        var direct = curr.querySelectorAll(selector);
        for (var i = 0; i < direct.length; i++) out.push(direct[i]);
        var all = curr.querySelectorAll('*');
        for (var j = 0; j < all.length; j++) {
          if (all[j].shadowRoot && !seen.has(all[j].shadowRoot)) queue.push(all[j].shadowRoot);
        }
      }
    }
    return out;
  }
  var els = collectAll('button, [role="button"], [role="menuitem"], [role="option"], a, li');
  var items = [];
  var seenLabel = new Set();
  for (var i = 0; i < els.length && items.length < 40; i++) {
    var el = els[i];
    if (!isVisible(el)) continue;
    var label = norm(
      (el.textContent || '') + ' | ' +
      ((el.getAttribute && el.getAttribute('aria-label')) || '') + ' | ' +
      ((el.getAttribute && el.getAttribute('title')) || '')
    ).replace(/\s*\|\s*$/, '');
    var key = label + '::' + ((el.getAttribute && el.getAttribute('role')) || el.tagName);
    if (!label || seenLabel.has(key)) continue;
    seenLabel.add(key);
    items.push({
      text: norm(el.textContent || '').slice(0, 60) || null,
      aria: norm((el.getAttribute && el.getAttribute('aria-label')) || '') || null,
      role: (el.getAttribute && el.getAttribute('role')) || null,
      tag: String(el.tagName || '').toLowerCase(),
    });
  }
  return { ok: true, count: items.length, items: items };
}

function MAIN_getUploadPickerStateForB2A() {
  function normalize(s) {
    return String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  }
  function lower(s) {
    return normalize(s).toLowerCase();
  }
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  function collectAll(root, selector) {
    var out = [];
    var queue = [root || document];
    var seen = new Set();
    while (queue.length > 0) {
      var curr = queue.shift();
      if (!curr || seen.has(curr)) continue;
      seen.add(curr);
      if (curr.querySelectorAll) {
        var direct = curr.querySelectorAll(selector);
        for (var i = 0; i < direct.length; i++) out.push(direct[i]);
        var descendants = curr.querySelectorAll('*');
        for (var j = 0; j < descendants.length; j++) {
          if (descendants[j].shadowRoot && !seen.has(descendants[j].shadowRoot)) {
            queue.push(descendants[j].shadowRoot);
          }
        }
      }
    }
    return out;
  }
  function isUploadActionText(text) {
    var value = lower(text);
    return value.indexOf('upload media') >= 0
      || value.indexOf('upload from device') >= 0
      || value === 'upload'
      || value.indexOf(' upload ') >= 0
      || value === 'add media';
  }
  function actionEvidence(el) {
    var rect = el.getBoundingClientRect();
    return {
      upload_media_found: true,
      text: normalize(el.textContent || '') || null,
      aria_label: normalize(el.getAttribute && el.getAttribute('aria-label') || '') || null,
      role: (el.getAttribute && el.getAttribute('role')) || null,
      tag: String(el.tagName || '').toLowerCase(),
      inside_modal: true,
      bbox: {
        x: rect.left,
        y: rect.top,
        width: rect.width,
        height: rect.height,
      },
    };
  }

  var surfaces = collectAll(document, '[role="dialog"], [aria-modal="true"], dialog, [role="menu"], [role="listbox"], [data-floating-ui-portal] > *, [data-radix-portal] > *, [data-radix-popper-content-wrapper] > *, section, aside, div[role="presentation"]');
  var best = null;
  for (var i = 0; i < surfaces.length; i++) {
    var surface = surfaces[i];
    if (!isVisible(surface)) continue;
    var text = normalize(surface.innerText || surface.textContent || '');
    var textLower = lower(text);
    if (!textLower) continue;
    var hasPickerMarkers =
      textLower.indexOf('upload') >= 0
      || textLower.indexOf('search for assets') >= 0
      || textLower.indexOf('all media') >= 0
      || textLower.indexOf('recent') >= 0
      || textLower.indexOf('uploads') >= 0
      || textLower.indexOf('characters') >= 0
      || textLower.indexOf('images') >= 0
      || textLower.indexOf('videos') >= 0;
    if (!hasPickerMarkers) continue;

    var buttons = collectAll(surface, 'button, [role="button"], [role="menuitem"], [role="option"]');
    var candidates = [];
    var uploadAction = null;
    for (var j = 0; j < buttons.length; j++) {
      var btn = buttons[j];
      if (!isVisible(btn)) continue;
      var combined = normalize(
        (btn.textContent || '')
        + ' '
        + (btn.getAttribute && btn.getAttribute('aria-label') || '')
        + ' '
        + (btn.getAttribute && btn.getAttribute('title') || '')
      );
      if (!combined) continue;
      if (isUploadActionText(combined)) {
        candidates.push(combined);
        if (!uploadAction) uploadAction = btn;
      }
    }

    var role = String(surface.getAttribute && surface.getAttribute('role') || '').toLowerCase();
    var dialogRoleFound = role === 'dialog' || surface.getAttribute && surface.getAttribute('aria-modal') === 'true';
    var score = candidates.length * 100;
    if (dialogRoleFound) score += 40;
    if (textLower.indexOf('upload media') >= 0) score += 60;
    if (textLower.indexOf('search for assets') >= 0) score += 25;
    if (!best || score > best.score) {
      best = {
        score: score,
        surface: surface,
        dialog_role_found: dialogRoleFound,
        modal_text_sample: text.slice(0, 240),
        upload_action_candidates: Array.from(new Set(candidates)).slice(0, 8),
        upload_action: uploadAction,
      };
    }
  }

  if (!best) {
    return {
      ok: false,
      modal_found: false,
      dialog_role_found: false,
      modal_text_sample: null,
      upload_action_candidates: [],
      upload_media_found: false,
    };
  }
  return {
    ok: true,
    modal_found: true,
    dialog_role_found: Boolean(best.dialog_role_found),
    modal_text_sample: best.modal_text_sample || null,
    upload_action_candidates: best.upload_action_candidates || [],
    upload_media_found: Boolean(best.upload_action),
    upload_action: best.upload_action ? actionEvidence(best.upload_action) : null,
  };
}

/**
 * MAIN-world: read the bottom composer config pill and current active model label
 * to verify if our settings are already correctly applied (permits bypassing clicks).
 */
function MAIN_getBottomComposerState() {
  function normalize(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); }
  function lower(s) { return normalize(s).toLowerCase(); }
  function collectAll(root, selector) {
    var out = [];
    var queue = [root || document];
    var seenRoots = new Set();
    while (queue.length > 0) {
      var curr = queue.shift();
      if (!curr || seenRoots.has(curr)) continue;
      seenRoots.add(curr);
      if (curr.querySelectorAll) {
        var direct = curr.querySelectorAll(selector);
        for (var idx = 0; idx < direct.length; idx++) out.push(direct[idx]);
        var descendants = curr.querySelectorAll('*');
        for (var jdx = 0; jdx < descendants.length; jdx++) {
          if (descendants[jdx].shadowRoot && !seenRoots.has(descendants[jdx].shadowRoot)) {
            queue.push(descendants[jdx].shadowRoot);
          }
        }
      }
    }
    return out;
  }
  
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
    // Glued-token fallback. Live Flow renders the bottom config pill as a SINGLE
    // button whose textContent concatenates its icon/label spans with no
    // whitespace, e.g. "Videocrop_9_161x". The \b-anchored patterns above cannot
    // isolate the trailing "1x" because it abuts the ratio's "16" (…161x has no
    // word boundary before the count digit). Match a 1–4 count digit immediately
    // followed by x that is not part of a longer word/number.
    var m3 = s.match(/([1-4])\s*[x×](?![a-z0-9])/);
    if (m3) return m3[1] + 'x';
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
  function getComposerRootLocal() {
    var prompts = collectAll(document, '[aria-label="Editable text"], [role="textbox"], [data-slate-editor="true"][contenteditable="true"], textarea, [contenteditable="true"], input[type="text"]');
    for (var pIdx = 0; pIdx < prompts.length; pIdx++) {
      if (!isVisibleNode(prompts[pIdx])) continue;
      var placeholder = normalize(
        (prompts[pIdx].getAttribute && (prompts[pIdx].getAttribute('placeholder') || prompts[pIdx].getAttribute('aria-label') || ''))
        || prompts[pIdx].textContent
        || '',
      ).toLowerCase();
      if (
        placeholder.indexOf('what do you want to create') >= 0
        || placeholder.indexOf('what do you want') >= 0
        || placeholder.indexOf('editable text') >= 0
      ) {
        return prompts[pIdx].closest && prompts[pIdx].closest('form, [role="form"], section, article, main, div') || prompts[pIdx];
      }
    }
    return prompts.length ? prompts[0].closest && prompts[0].closest('form, [role="form"], section, article, main, div') || prompts[0] : null;
  }
  function distanceToComposer(el) {
    var composer = getComposerRootLocal();
    if (!composer || !composer.getBoundingClientRect || !el || !el.getBoundingClientRect) return Number.MAX_SAFE_INTEGER;
    var a = composer.getBoundingClientRect();
    var b = el.getBoundingClientRect();
    var ax = a.left + (a.width / 2);
    var ay = a.top + (a.height / 2);
    var bx = b.left + (b.width / 2);
    var by = b.top + (b.height / 2);
    return Math.round(Math.sqrt(Math.pow(ax - bx, 2) + Math.pow(ay - by, 2)));
  }

  var els = collectAll(document, 'button, [role="button"], [role="tab"], [aria-haspopup], [data-state], [aria-label], span, div');
  var pillText = '';
  var pillRatio = null;
  var pillCount = null;
  var modelText = '';
  var bestModelCanon = '';
  var bestPillScore = -1;
  var pillCandidates = [];

  for (var i = 0; i < els.length; i++) {
    var el = els[i];
    if (!isVisibleNode(el)) continue;
    var txt = normalize(el.textContent || el.getAttribute('aria-label') || '');
    if (!txt || txt.length > 160) continue;
    var lc = txt.toLowerCase();
    var r = ratioFromText(txt);
    var c = countFromText(txt);
    var mc = modelCanonFromText(txt);
    var dist = distanceToComposer(el);
    var compact = txt.length <= 120;

    // Pill candidate: any compact chip carrying a ratio AND/OR count token.
    // Score favors chips bundling ratio+count(+model); ties → shortest text.
    if (r || c) {
      var score = (r ? 4 : 0) + (c ? 4 : 0) + (mc ? 2 : 0) + (compact ? 1 : 0) + (dist <= 520 ? 1 : 0);
      pillCandidates.push({ txt: txt, ratio: r, count: c, modelCanon: mc, dist: dist, score: score });
      if (score > bestPillScore || (score === bestPillScore && (!pillText || txt.length < pillText.length))) {
        bestPillScore = score;
        pillText = txt;
        // Sticky tokens: a shorter / equal-scoring chip that lacks a ratio or
        // count must NOT erase one already discovered on another chip. Split
        // layouts place the ratio and count on separate adjacent chips, so a
        // later "1x" chip winning the tie-break previously clobbered the
        // already-found ratio back to null.
        if (r) pillRatio = r;
        if (c) pillCount = c;
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
  if ((!pillRatio || !pillCount) && pillCandidates.length) {
    pillCandidates.sort(function (a, b) {
      if (a.score !== b.score) return b.score - a.score;
      if (a.dist !== b.dist) return a.dist - b.dist;
      return a.txt.length - b.txt.length;
    });
    var ratioCandidate = null;
    var countCandidate = null;
    var modelCandidate = null;
    for (var p = 0; p < pillCandidates.length; p++) {
      if (!ratioCandidate && pillCandidates[p].ratio) ratioCandidate = pillCandidates[p];
      if (!countCandidate && pillCandidates[p].count) countCandidate = pillCandidates[p];
      if (!modelCandidate && pillCandidates[p].modelCanon) modelCandidate = pillCandidates[p];
      if (ratioCandidate && countCandidate && modelCandidate) break;
    }
    pillRatio = pillRatio || (ratioCandidate && ratioCandidate.ratio) || null;
    pillCount = pillCount || (countCandidate && countCandidate.count) || null;
    if (!bestModelCanon && modelCandidate && modelCandidate.modelCanon) {
      bestModelCanon = modelCandidate.modelCanon;
      if (!modelText || modelText.length > modelCandidate.txt.length) modelText = modelCandidate.txt;
    }
    if ((!pillText || pillText === pillCount || pillText === pillRatio) && (ratioCandidate || countCandidate || modelCandidate)) {
      var stitched = [];
      if (modelCandidate && stitched.indexOf(modelCandidate.txt) === -1) stitched.push(modelCandidate.txt);
      if (ratioCandidate && stitched.indexOf(ratioCandidate.txt) === -1) stitched.push(ratioCandidate.txt);
      if (countCandidate && stitched.indexOf(countCandidate.txt) === -1) stitched.push(countCandidate.txt);
      pillText = stitched.join(' ').trim() || pillText;
    }
  }

  // Region-text fallback. When per-element chip scanning cannot isolate the
  // ratio/count — split or icon-only chips, the only carrier being a single
  // >160-char container, or a pill occluded by an open settings panel — recover
  // the tokens from the visible composer-region text and, last, from body text.
  // This mirrors the DOM diagnostic lane (content-flow-dom collectVisibleMarkers)
  // which reads these tokens reliably from aggregate text. It is the deterministic
  // cure for the runner-vs-diagnostic mismatch that produced a degraded "1x" pill
  // and ERR_F2V_OPTION_RATIO_9_16_NOT_FOUND on an editor already at 9:16.
  if (!pillRatio || !pillCount) {
    var fallbackTexts = [];
    var composerRegion = getComposerRootLocal();
    if (composerRegion) {
      var regionText = normalize(composerRegion.innerText || composerRegion.textContent || '');
      if (regionText) fallbackTexts.push(regionText);
    }
    var bodyFallbackText = normalize((document.body && (document.body.innerText || document.body.textContent)) || '');
    if (bodyFallbackText) fallbackTexts.push(bodyFallbackText);
    for (var ft = 0; ft < fallbackTexts.length; ft++) {
      if (!pillRatio) {
        var fbRatio = ratioFromText(fallbackTexts[ft]);
        if (fbRatio) pillRatio = fbRatio;
      }
      if (!pillCount) {
        var fbCount = countFromText(fallbackTexts[ft]);
        if (fbCount) pillCount = fbCount;
      }
      if (pillRatio && pillCount) break;
    }
    // Keep pillText informative for telemetry when it had degraded to a single
    // partial token (e.g. "1x") but structured data is now available.
    if ((pillRatio || pillCount) && (!pillText || pillText.length <= 3)) {
      var rebuilt = [];
      if (modelText) rebuilt.push(modelText);
      if (pillRatio) rebuilt.push(pillRatio === '9:16' ? 'crop_9_16' : (pillRatio === '16:9' ? 'crop_16_9' : pillRatio));
      if (pillCount) rebuilt.push(pillCount);
      if (rebuilt.length) pillText = rebuilt.join(' ');
    }
  }

  var modelCanonical = bestModelCanon;
  var modelFamily = familyOf(bestModelCanon);

  // Detect top level active mode trigger
  var topMode = 'UNKNOWN';
  var buttons = collectAll(document, 'button, [role="tab"], [role="button"]');
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
  
  function collectAll(root, selector) {
    var out = [];
    var queue = [root || document];
    var seenRoots = new Set();
    while (queue.length > 0) {
      var curr = queue.shift();
      if (!curr || seenRoots.has(curr)) continue;
      seenRoots.add(curr);
      if (curr.querySelectorAll) {
        var direct = curr.querySelectorAll(selector);
        for (var idx = 0; idx < direct.length; idx++) out.push(direct[idx]);
        var descendants = curr.querySelectorAll('*');
        for (var jdx = 0; jdx < descendants.length; jdx++) {
          if (descendants[jdx].shadowRoot && !seenRoots.has(descendants[jdx].shadowRoot)) {
            queue.push(descendants[jdx].shadowRoot);
          }
        }
      }
    }
    return out;
  }
  var surfaces = collectAll(document, '[role="menu"], [role="listbox"], [role="dialog"]');
  var panel = null;
  for (var i = 0; i < surfaces.length; i++) {
    if (isVisible(surfaces[i])) {
      panel = surfaces[i];
      break;
    }
  }
  if (!panel) return null;
  
  var nodes = collectAll(panel, 'button, [role="button"], [role="combobox"], [aria-haspopup], [data-state], [tabindex], div, span');
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
 * MAIN-world: find a setting launcher AND stamp it in one self-contained execution.
 * This function is passed directly to chrome.scripting.executeScript as `func` and
 * must be fully self-contained — no references to outer-scope symbols are allowed,
 * because executeScript serializes via .toString() and the closure is lost.
 */
function MAIN_findAndStampSettingLauncher(settingType, stampAttr) {
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  function lower(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim().toLowerCase(); }

  function collectAll(root, selector) {
    var out = [];
    var queue = [root || document];
    var seenRoots = new Set();
    while (queue.length > 0) {
      var curr = queue.shift();
      if (!curr || seenRoots.has(curr)) continue;
      seenRoots.add(curr);
      if (curr.querySelectorAll) {
        var direct = curr.querySelectorAll(selector);
        for (var idx = 0; idx < direct.length; idx++) out.push(direct[idx]);
        var descendants = curr.querySelectorAll('*');
        for (var jdx = 0; jdx < descendants.length; jdx++) {
          if (descendants[jdx].shadowRoot && !seenRoots.has(descendants[jdx].shadowRoot)) {
            queue.push(descendants[jdx].shadowRoot);
          }
        }
      }
    }
    return out;
  }
  function findSectionPanel(headingText) {
    var heading = lower(headingText || '');
    if (!heading) return null;
    var nodes = collectAll(document, 'h1, h2, h3, h4, h5, h6, label, p, span, div, button');
    var best = null;
    for (var idx2 = 0; idx2 < nodes.length; idx2++) {
      var node = nodes[idx2];
      if (!isVisible(node)) continue;
      var text = lower(node.textContent || node.getAttribute('aria-label') || '');
      if (text.indexOf(heading) === -1) continue;
      var current = node;
      var depth = 0;
      while (current && depth < 8) {
        if (current === document.body || current === document.documentElement) break;
        if (isVisible(current)) {
          var scopeText = lower(current.innerText || current.textContent || '');
          if (
            scopeText.indexOf(heading) >= 0
            && (scopeText.indexOf('1x') >= 0 || scopeText.indexOf('16:9') >= 0 || scopeText.indexOf('9:16') >= 0 || scopeText.indexOf('veo') >= 0 || scopeText.indexOf('omni flash') >= 0)
          ) {
            var rect = current.getBoundingClientRect();
            var area = rect.width * rect.height;
            if (!best || area < best.area) {
              best = { el: current, area: area };
            }
          }
        }
        current = current.parentElement || null;
        depth += 1;
      }
    }
    return best ? best.el : null;
  }
  var preferredPanel = findSectionPanel('Video generation default');
  var surfaces = preferredPanel
    ? [preferredPanel]
    : collectAll(document, '[role="menu"], [role="listbox"], [role="dialog"]');
  var panel = null;
  for (var i = 0; i < surfaces.length; i++) {
    if (isVisible(surfaces[i])) { panel = surfaces[i]; break; }
  }
  if (!panel) return null;

  var nodes = collectAll(panel, 'button, [role="button"], [role="combobox"], [aria-haspopup], [data-state], [tabindex], div, span');
  var el = null;
  for (var j = 0; j < nodes.length; j++) {
    var node = nodes[j];
    if (!isVisible(node)) continue;
    var text = lower(node.textContent || node.getAttribute('aria-label') || '');
    var match = false;
    if (settingType === 'aspect') {
      match = text.indexOf('crop') >= 0 || text.indexOf('16:9') >= 0 || text.indexOf('9:16') >= 0 || text.indexOf('aspect') >= 0 || text.indexOf('ratio') >= 0 || text.indexOf('portrait') >= 0 || text.indexOf('landscape') >= 0;
    } else if (settingType === 'count') {
      match = text.indexOf('variation') >= 0 || text.indexOf('1x') >= 0 || text.indexOf('2x') >= 0 || text.indexOf('x2') >= 0 || text.indexOf('x1') >= 0 || text.indexOf('count') >= 0 || text.indexOf('quantity') >= 0;
    } else if (settingType === 'model') {
      match = text.indexOf('veo') >= 0 || text.indexOf('imagen') >= 0 || text.indexOf('gemini') >= 0 || text.indexOf('model') >= 0 || text.indexOf('lite') >= 0 || text.indexOf('nano') >= 0 || text.indexOf('banana') >= 0 || text.indexOf('pro') >= 0;
    }
    if (match) {
      el = node;
      if (node.closest) {
        var interactive = node.closest('button, [role="button"], [role="combobox"], [aria-haspopup], [tabindex]');
        if (interactive && isVisible(interactive)) el = interactive;
      }
      break;
    }
  }
  if (!el) return null;
  var id = stampAttr + '-' + Date.now();
  el.setAttribute(stampAttr, id);
  var rect = el.getBoundingClientRect();
  return { stamp_id: id, stamp_attr: stampAttr, text: el.textContent, bbox: { x: rect.left, y: rect.top, width: rect.width, height: rect.height } };
}

/**
 * MAIN-world: attempt to dismiss promo overlays, banners, and modal dialogs
 * that appear before the settings panel (e.g. "Try Omni now" banners).
 *
 * Tolerant by design — returns {ok:true} even when nothing is found or
 * dismissal fails. Never throws. Does NOT dispatch Escape unless a promo
 * dialog was actually detected (avoids closing the project editor).
 */

/**
 * MAIN-world: keyword-based model option scanner.
 * Scans all visible interactive elements for any option whose text contains
 * the target model family keyword. Used as a fallback when exact label
 * matching fails due to Google Flow UI renames or reformats.
 *
 * Family keyword contract (per user spec):
 *   'veo'         → video model  (match anything containing 'veo')
 *   'nano banana' → image model  (match anything containing 'nano' or 'banana')
 *   'imagen'      → image model  (match anything containing 'imagen')
 */
function MAIN_findVisibleModelByKeyword(familyKeyword, stampAttr) {
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  function lower(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim().toLowerCase(); }
  function collectAll(root, selector) {
    var out = [];
    var queue = [root || document];
    var seenRoots = new Set();
    while (queue.length > 0) {
      var curr = queue.shift();
      if (!curr || seenRoots.has(curr)) continue;
      seenRoots.add(curr);
      if (curr.querySelectorAll) {
        var direct = curr.querySelectorAll(selector);
        for (var idx = 0; idx < direct.length; idx++) out.push(direct[idx]);
        var descendants = curr.querySelectorAll('*');
        for (var jdx = 0; jdx < descendants.length; jdx++) {
          if (descendants[jdx].shadowRoot && !seenRoots.has(descendants[jdx].shadowRoot)) {
            queue.push(descendants[jdx].shadowRoot);
          }
        }
      }
    }
    return out;
  }
  var kw = lower(familyKeyword || '');
  var tokens = [];
  if (kw.indexOf('veo') >= 0) {
    tokens = ['veo'];
  } else if (kw.indexOf('nano banana') >= 0 || kw.indexOf('nano') >= 0) {
    tokens = ['nano banana', 'nano', 'banana'];
  } else if (kw.indexOf('imagen') >= 0) {
    tokens = ['imagen'];
  } else if (kw) {
    tokens = [kw];
  }
  if (!tokens.length) return null;
  var nodes = collectAll(document,
    '[role="option"], [role="menuitem"], [role="menuitemradio"], [role="radio"], button, [role="button"]'
  );
  for (var i = 0; i < nodes.length; i++) {
    var el = nodes[i];
    if (!isVisible(el)) continue;
    var text = lower(el.textContent || el.getAttribute('aria-label') || '');
    for (var t = 0; t < tokens.length; t++) {
      if (text.indexOf(tokens[t]) >= 0) {
        var id = stampAttr + '-kw-' + Date.now();
        el.setAttribute(stampAttr, id);
        var rect = el.getBoundingClientRect();
        return { stamp_id: id, stamp_attr: stampAttr, text: el.textContent, bbox: { x: rect.left, y: rect.top, width: rect.width, height: rect.height } };
      }
    }
  }
  return null;
}

/**
 * MAIN-world: resolve a visible upload slot by semantic label instead of
 * exact equality. Flow commonly renders the Start slot as
 * "Start creating or drop media", which exact label scanning misses.
 */
function MAIN_findUploadSlotByLabel(slotLabel, stampAttr) {
  function normalize(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); }
  function lower(s) { return normalize(s).toLowerCase(); }
  function looksLikeNeedle(text, needleText) {
    if (!text) return false;
    if (needleText === 'start') {
      return text.indexOf('start creating') >= 0
        || text.indexOf('drop media') >= 0
        || /^start\b/.test(text)
        || text.indexOf('start frame') >= 0;
    }
    return text.indexOf(needleText) >= 0;
  }
  function looksLikeOpposingSlot(text, needleText) {
    if (!text || needleText !== 'start') return false;
    if (looksLikeNeedle(text, needleText)) return false;
    return /\bend\b/.test(text) || text.indexOf('last frame') >= 0;
  }
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var style = window.getComputedStyle(el);
    return Boolean(style && style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) !== 0);
  }
  function isInteractive(el) {
    if (!el || !el.tagName) return false;
    var tag = String(el.tagName || '').toLowerCase();
    if (tag === 'button' || tag === 'a' || tag === 'input' || tag === 'label') return true;
    var role = el.getAttribute && el.getAttribute('role');
    if (role && ['button', 'option', 'tab', 'menuitem', 'menuitemradio'].indexOf(role) >= 0) return true;
    return Boolean(el.hasAttribute && (
      el.hasAttribute('aria-haspopup')
      || el.hasAttribute('aria-expanded')
      || el.hasAttribute('aria-selected')
      || el.hasAttribute('aria-pressed')
      || el.hasAttribute('data-state')
      || el.hasAttribute('tabindex')
    ));
  }
  function nextParent(node) {
    if (!node) return null;
    if (node.parentElement) return node.parentElement;
    if (node.getRootNode) {
      var root = node.getRootNode();
      if (root && root.host) return root.host;
    }
    return null;
  }
  function collectAll(root, selector) {
    var out = [];
    var queue = [root || document];
    var seenRoots = new Set();
    while (queue.length > 0) {
      var curr = queue.shift();
      if (!curr || seenRoots.has(curr)) continue;
      seenRoots.add(curr);
      if (curr.querySelectorAll) {
        var direct = curr.querySelectorAll(selector);
        for (var idx = 0; idx < direct.length; idx++) out.push(direct[idx]);
        var descendants = curr.querySelectorAll('*');
        for (var jdx = 0; jdx < descendants.length; jdx++) {
          if (descendants[jdx].shadowRoot && !seenRoots.has(descendants[jdx].shadowRoot)) {
            queue.push(descendants[jdx].shadowRoot);
          }
        }
      }
    }
    return out;
  }
  function stamp(el) {
    var attr = stampAttr || 'data-bosmax-option';
    var id = attr + '-slot-' + Date.now();
    el.setAttribute(attr, id);
    var rect = el.getBoundingClientRect();
    return {
      stamp_id: id,
      stamp_attr: attr,
      text: normalize(el.textContent || el.getAttribute && el.getAttribute('aria-label') || '').slice(0, 160),
      role: (el.getAttribute && el.getAttribute('role')) || String(el.tagName || '').toLowerCase(),
      bbox: { x: rect.left, y: rect.top, width: rect.width, height: rect.height },
    };
  }
  function scoreCandidate(target, labelLower, labelText, needleText) {
    if (!target || !target.el || !isVisible(target.el)) return null;
    var targetText = normalize(target.el.textContent || target.el.getAttribute && target.el.getAttribute('aria-label') || '');
    var targetLower = targetText.toLowerCase();
    if (looksLikeOpposingSlot(targetLower, needleText)) return null;
    var rect = target.el.getBoundingClientRect();
    var score = 0;
    if (labelLower.indexOf('start creating') >= 0) score += 120;
    if (labelLower.indexOf('drop media') >= 0) score += 90;
    if (/^start\b/.test(labelLower)) score += 70;
    if (labelText === 'Start') score += 40;
    if (target.source === 'label_closest_button') score += 80;
    if (target.source === 'container_button') score += 50;
    if (target.source === 'container') score += 40;
    if (target.source === 'label_node') score += 25;
    if (looksLikeNeedle(targetLower, needleText)) score += 35;
    if (targetLower.indexOf('upload') >= 0 || targetLower.indexOf('add media') >= 0) score += 20;
    if (rect.width >= 160 && rect.height >= 40) score += 15;
    if (rect.width >= 220 && rect.height >= 48) score += 10;
    if (rect.width >= 500) score -= 40;
    if (rect.width >= 800) score -= 80;
    if (rect.height >= 100) score -= 25;
    score -= Number(target.depth || 0) * 12;
    return {
      el: target.el,
      source: target.source,
      depth: Number(target.depth || 0),
      score: score,
    };
  }
  function buildTargets(labelNode, container, depth) {
    var targets = [];
    function push(el, source) {
      if (!el || !isVisible(el)) return;
      if (targets.some(function (item) { return item.el === el; })) return;
      targets.push({ el: el, source: source, depth: depth });
    }
    push(labelNode && labelNode.closest && labelNode.closest('button, [role="button"]'), 'label_closest_button');
    push(labelNode, 'label_node');
    push(container && container.querySelector && container.querySelector('button, [role="button"]'), 'container_button');
    push(container, 'container');
    return targets;
  }

  var needle = lower(slotLabel || '');
  var labelCandidates = collectAll(document, 'label, span, div, p, button, [role="button"], a');
  var resolvedCandidates = [];
  for (var i = 0; i < labelCandidates.length; i++) {
    var labelNode = labelCandidates[i];
    if (!isVisible(labelNode)) continue;
    var labelText = normalize(labelNode.textContent || labelNode.getAttribute && labelNode.getAttribute('aria-label') || '');
    var labelLower = labelText.toLowerCase();
    if (!labelLower) continue;
    if (!looksLikeNeedle(labelLower, needle)) {
      continue;
    }

    var current = labelNode;
    for (var depth = 0; current && depth < 8; depth++) {
      if (isVisible(current)) {
        var currentText = normalize(current.textContent || current.getAttribute && current.getAttribute('aria-label') || '');
        var currentLower = currentText.toLowerCase();
        var hasUploadMarker = /(upload|add|media|image|browse|drop|create)/i.test(currentText);
        var isClickableContainer = isInteractive(current) || Boolean(current.matches && current.matches('button, [role="button"], label, a'));
        var currentMatchesNeedle = looksLikeNeedle(currentLower, needle) || current === labelNode || Boolean(current.contains && current.contains(labelNode));
        if ((hasUploadMarker || isClickableContainer || current === labelNode) && currentMatchesNeedle) {
          var targets = buildTargets(labelNode, current, depth);
          for (var t = 0; t < targets.length; t++) {
            var scored = scoreCandidate(targets[t], labelLower, labelText, needle);
            if (scored) resolvedCandidates.push(scored);
          }
        }
      }
      current = nextParent(current);
    }
  }
  if (!resolvedCandidates.length) return null;
  resolvedCandidates.sort(function (a, b) {
    if (b.score !== a.score) return b.score - a.score;
    var aRect = a.el.getBoundingClientRect();
    var bRect = b.el.getBoundingClientRect();
    if (aRect.top !== bRect.top) return aRect.top - bRect.top;
    return aRect.left - bRect.left;
  });
  var best = resolvedCandidates[0];
  var stamped = stamp(best.el);
  if (stamped) {
    stamped.target_source = best.source;
    stamped.score = best.score;
    return stamped;
  }
  return null;
}

/**
 * MAIN-world: find an upload entry-point by aria-label or icon symbol.
 * Fallback for when exact-label matching fails because the button shows
 * only a Material Icon glyph (+/add/drive_folder_upload) with no text.
 *
 * Priority:
 *   1. aria-label/title containing "upload" or "add media" (strongest signal)
 *   2. Button whose full text is a known upload-icon token
 *   3. Pure add/add_2 icon button that lives inside a panel whose ancestor
 *      text references "upload" or "start frame" (context-gated + weak)
 */
function MAIN_findUploadBySymbol(stampAttr) {
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  function lower(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim().toLowerCase(); }
  function stamp(el) {
    var id = (stampAttr || 'data-bosmax-option') + '-sym-' + Date.now();
    el.setAttribute(stampAttr || 'data-bosmax-option', id);
    var r = el.getBoundingClientRect();
    return { stamp_id: id, stamp_attr: stampAttr || 'data-bosmax-option', text: el.textContent, bbox: { x: Math.round(r.left), y: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) } };
  }
  var UPLOAD_ICONS = ['drive_folder_upload', 'file_upload', 'upload_file', 'upload'];
  var ADD_ICONS = ['add_2', 'add'];
  var nodes = document.querySelectorAll('button, [role="button"], [role="menuitem"], [role="option"]');
  var addCandidates = [];
  for (var i = 0; i < nodes.length; i++) {
    var el = nodes[i];
    if (!isVisible(el)) continue;
    // Priority 1: aria-label
    var ariaLabel = lower(el.getAttribute('aria-label') || el.getAttribute('title') || '');
    if (ariaLabel.indexOf('upload') >= 0 || ariaLabel.indexOf('add media') >= 0) return stamp(el);
    var text = lower(el.textContent || '');
    if (text.indexOf('add media') >= 0) return stamp(el);
    // Priority 2: known upload icon glyphs
    for (var u = 0; u < UPLOAD_ICONS.length; u++) {
      if (text === UPLOAD_ICONS[u] || text.indexOf(UPLOAD_ICONS[u] + ' ') === 0 || text.indexOf(' ' + UPLOAD_ICONS[u]) >= 0) {
        return stamp(el);
      }
    }
    // Collect pure add-icon buttons for context-gated check below
    for (var a = 0; a < ADD_ICONS.length; a++) {
      if (text === ADD_ICONS[a]) { addCandidates.push(el); break; }
    }
  }
  // Priority 3: pure + icon inside upload/media panel context
  for (var c = 0; c < addCandidates.length; c++) {
    var parent = addCandidates[c].parentElement;
    for (var depth = 0; depth < 8 && parent; depth++, parent = parent.parentElement) {
      var panelText = lower(parent.textContent || '');
      if (panelText.indexOf('upload') >= 0 || panelText.indexOf('add media') >= 0 || panelText.indexOf('start frame') >= 0) {
        return stamp(addCandidates[c]);
      }
    }
  }
  return null;
}

/**
 * MAIN-world: find the confirmation button inside the asset picker after the
 * upload finishes. Live Flow currently labels this button "Add to Prompt".
 */
function MAIN_findAddToPromptButton(stampAttr) {
  function normalize(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); }
  function lower(s) { return normalize(s).toLowerCase(); }
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  function collectAll(root, selector) {
    var out = [];
    var queue = [root || document];
    var seen = new Set();
    while (queue.length > 0) {
      var curr = queue.shift();
      if (!curr || seen.has(curr)) continue;
      seen.add(curr);
      if (curr.querySelectorAll) {
        var direct = curr.querySelectorAll(selector);
        for (var idx = 0; idx < direct.length; idx++) out.push(direct[idx]);
        var descendants = curr.querySelectorAll('*');
        for (var jdx = 0; jdx < descendants.length; jdx++) {
          if (descendants[jdx].shadowRoot && !seen.has(descendants[jdx].shadowRoot)) {
            queue.push(descendants[jdx].shadowRoot);
          }
        }
      }
    }
    return out;
  }
  function isClickableLike(el) {
    if (!el || !el.tagName) return false;
    var tag = String(el.tagName || '').toLowerCase();
    if (tag === 'button' || tag === 'a' || tag === 'input' || tag === 'label') return true;
    var role = el.getAttribute && el.getAttribute('role');
    if (role && ['button', 'menuitem', 'option', 'tab'].indexOf(role) >= 0) return true;
    if (typeof el.onclick === 'function') return true;
    if (typeof el.tabIndex === 'number' && el.tabIndex >= 0) return true;
    var style = window.getComputedStyle(el);
    return Boolean(style && style.cursor === 'pointer');
  }
  function toClickable(el) {
    var current = el;
    while (current) {
      if (isClickableLike(current)) return current;
      current = current.parentElement || null;
    }
    return el;
  }
  var nodes = collectAll(document, 'button, [role="button"], [role="menuitem"], [role="option"], [tabindex], div, span');
  for (var i = 0; i < nodes.length; i++) {
    var el = toClickable(nodes[i]);
    if (!el || !isVisible(el) || !isClickableLike(el)) continue;
    var txt = lower(el.textContent || el.getAttribute('aria-label') || '');
    if (txt === 'add to prompt' || txt === 'add prompt' || txt.indexOf('add to prompt') >= 0) {
      var attr = String(stampAttr || 'data-bosmax-option');
      var id = attr + '-add-to-prompt-' + Date.now();
      el.setAttribute(attr, id);
      var r = el.getBoundingClientRect();
      return {
        ok: true,
        stamp_id: id,
        stamp_attr: attr,
        text: normalize(el.textContent || el.getAttribute('aria-label') || ''),
        bbox: { x: Math.round(r.left), y: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) },
      };
    }
  }
  return { ok: false, reason: 'no_add_to_prompt_button_visible' };
}

function MAIN_selectAssetPickerCandidate(stampAttr) {
  function normalize(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); }
  function lower(s) { return normalize(s).toLowerCase(); }
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  function collectAll(root, selector) {
    var out = [];
    var queue = [root || document];
    var seen = new Set();
    while (queue.length > 0) {
      var curr = queue.shift();
      if (!curr || seen.has(curr)) continue;
      seen.add(curr);
      if (curr.querySelectorAll) {
        var direct = curr.querySelectorAll(selector);
        for (var idx = 0; idx < direct.length; idx++) out.push(direct[idx]);
        var descendants = curr.querySelectorAll('*');
        for (var jdx = 0; jdx < descendants.length; jdx++) {
          if (descendants[jdx].shadowRoot && !seen.has(descendants[jdx].shadowRoot)) {
            queue.push(descendants[jdx].shadowRoot);
          }
        }
      }
    }
    return out;
  }
  function looksLikeAssetSurface(el) {
    if (!isVisible(el)) return false;
    var r = el.getBoundingClientRect();
    if (r.width < 260 || r.height < 180) return false;
    var text = lower(el.textContent || '');
    return (
      text.indexOf('upload media') >= 0 ||
      text.indexOf('search assets') >= 0 ||
      text.indexOf('recent') >= 0 ||
      text.indexOf('add to prompt') >= 0 ||
      (text.indexOf('all') >= 0 && (text.indexOf('images') >= 0 || text.indexOf('uploads') >= 0))
    );
  }
  function isClickableLike(el) {
    if (!el || !el.tagName) return false;
    var tag = String(el.tagName || '').toLowerCase();
    if (tag === 'button' || tag === 'a' || tag === 'input' || tag === 'label') return true;
    var role = el.getAttribute && el.getAttribute('role');
    if (role && ['button', 'option', 'menuitem', 'tab'].indexOf(role) >= 0) return true;
    if (typeof el.onclick === 'function') return true;
    if (typeof el.tabIndex === 'number' && el.tabIndex >= 0) return true;
    var style = window.getComputedStyle(el);
    return Boolean(style && style.cursor === 'pointer');
  }
  function toClickable(el, stopAt) {
    var current = el;
    while (current) {
      if (isClickableLike(current)) return current;
      if (stopAt && current === stopAt) break;
      current = current.parentElement || null;
    }
    return el;
  }
  var dialogs = collectAll(document, '[role="dialog"], [role="menu"], [role="listbox"]');
  var panel = null;
  var firstVisibleDialog = null;
  for (var d = 0; d < dialogs.length; d++) {
    if (!isVisible(dialogs[d])) continue;
    if (!firstVisibleDialog) firstVisibleDialog = dialogs[d];
    var dialogText = lower(dialogs[d].textContent || '');
    if (dialogText.indexOf('upload media') >= 0 || dialogText.indexOf('search assets') >= 0 || dialogText.indexOf('recent') >= 0) {
      panel = dialogs[d];
      break;
    }
  }
  if (!panel) {
    var surfaces = collectAll(document, 'section, article, div');
    for (var s = 0; s < surfaces.length; s++) {
      if (looksLikeAssetSurface(surfaces[s])) {
        panel = surfaces[s];
        break;
      }
    }
  }
  if (!panel) panel = firstVisibleDialog;
  if (!panel) return { ok: false, reason: 'asset_picker_panel_not_found' };
  var candidates = collectAll(panel, 'button, [role="button"], [role="option"], [tabindex], article, li, div');
  for (var i = 0; i < candidates.length; i++) {
    var el = candidates[i];
    if (!isVisible(el)) continue;
    var clickable = toClickable(el, panel);
    if (!clickable || !isVisible(clickable)) continue;
    if (!isClickableLike(clickable)) continue;
    var text = lower(clickable.textContent || clickable.getAttribute('aria-label') || '');
    if (!text) continue;
    if (text.indexOf('upload media') >= 0 || text.indexOf('add to prompt') >= 0 || text === 'all' || text === 'images' || text === 'videos' || text === 'voices' || text === 'characters' || text === 'avatar' || text === 'uploads' || text === 'recent') {
      continue;
    }
    var hasPreview = Boolean(clickable.querySelector && clickable.querySelector('img, canvas, video, picture'));
    var fileLike = /\.(png|jpe?g|webp|gif|bmp)\b/i.test(text) || text.indexOf('generated-') >= 0 || text.indexOf('image-') >= 0;
    if (!hasPreview && !fileLike && text.length < 12) continue;
    var attr = String(stampAttr || 'data-bosmax-option');
    var id = attr + '-asset-card-' + Date.now();
    clickable.setAttribute(attr, id);
    var r = clickable.getBoundingClientRect();
    return {
      ok: true,
      stamp_id: id,
      stamp_attr: attr,
      text: normalize(clickable.textContent || clickable.getAttribute('aria-label') || '').slice(0, 120),
      bbox: { x: Math.round(r.left), y: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) },
    };
  }
  return { ok: false, reason: 'asset_picker_candidate_not_found' };
}

function MAIN_getUploadSlotPreviewState(slotLabel) {
  function normalize(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); }
  function lower(s) { return normalize(s).toLowerCase(); }
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  function describePreviewNode(node) {
    if (!node || !isVisible(node)) return null;
    var rect = node.getBoundingClientRect();
    if (rect.width < 24 || rect.height < 24) return null;
    var tagName = String(node.tagName || '').toLowerCase();
    if (tagName === 'picture') {
      var nestedImg = node.querySelector && node.querySelector('img');
      return nestedImg ? describePreviewNode(nestedImg) : null;
    }
    if (tagName === 'img') {
      var src = node.currentSrc || node.src || node.getAttribute('src') || '';
      if (!src) return null;
      return { tagName: tagName, identity: src, rect: rect };
    }
    if (tagName === 'canvas') {
      return { tagName: tagName, identity: 'canvas', rect: rect };
    }
    if (tagName === 'video') {
      return { tagName: tagName, identity: node.currentSrc || node.getAttribute('src') || 'video', rect: rect };
    }
    var style = window.getComputedStyle(node);
    var bg = style && style.backgroundImage;
    if (bg && bg !== 'none') {
      return { tagName: tagName || 'styled', identity: bg, rect: rect };
    }
    return null;
  }
  function collectCandidateContainers(slot) {
    var out = [];
    var seen = new Set();
    function push(el) {
      if (!el || seen.has(el) || !isVisible(el)) return;
      seen.add(el);
      out.push(el);
    }
    var slotInfo = MAIN_findUploadSlotByLabel(slot, 'data-bosmax-preview-probe');
    var stamped = null;
    if (slotInfo && slotInfo.stamp_id) {
      stamped = document.querySelector('[' + slotInfo.stamp_attr + '="' + slotInfo.stamp_id + '"]');
    }
    var current = stamped;
    for (var depth = 0; current && depth < 5; depth++) {
      push(current);
      current = current.parentElement || null;
    }
    return out;
  }
  function collectVisiblePreviewNodes(root) {
    var nodes = root && root.querySelectorAll
      ? root.querySelectorAll('img, canvas, video, picture, [style*="background-image"]')
      : [];
    var out = [];
    for (var i = 0; i < nodes.length; i++) {
      var described = describePreviewNode(nodes[i]);
      if (described) out.push(described);
    }
    return out;
  }
  var containers = collectCandidateContainers(slotLabel || 'Start');
  for (var i = 0; i < containers.length; i++) {
    var container = containers[i];
    var previews = collectVisiblePreviewNodes(container);
    var text = lower(container.textContent || '');
    var uploadPending = text.indexOf('uploading') >= 0 || text.indexOf('processing') >= 0 || text.indexOf('loading') >= 0;
    var fileLikeText = /\.(png|jpe?g|webp|gif|bmp)\b/i.test(text)
      || text.indexOf('generated-') >= 0
      || text.indexOf('image-') >= 0
      || text.indexOf('replace') >= 0
      || text.indexOf('remove') >= 0;
    if (previews.length > 0 || (!uploadPending && fileLikeText && text.indexOf('drop media') === -1)) {
      var rect = container.getBoundingClientRect();
      return {
        ok: true,
        slot_found: true,
        preview_found: previews.length > 0 || fileLikeText,
        preview_count: previews.length,
        upload_pending: uploadPending,
        text: normalize(container.textContent || '').slice(0, 200),
        bbox: { x: Math.round(rect.left), y: Math.round(rect.top), width: Math.round(rect.width), height: Math.round(rect.height) },
        strategy: 'slot_preview_probe',
      };
    }
  }
  return { ok: false, slot_found: containers.length > 0, preview_found: false };
}

function MAIN_getComposerAssetPreviewState() {
  function normalize(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); }
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    var s = window.getComputedStyle(el);
    return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
  }
  function findComposer() {
    return document.querySelector('[aria-label="Editable text"], [role="textbox"], [data-slate-editor="true"][contenteditable="true"], textarea[placeholder*="What do you want"], textarea, [contenteditable="true"]');
  }
  function collectRoots(composer) {
    var roots = [];
    var seen = new Set();
    var current = composer;
    var depth = 0;
    while (current && depth <= 5) {
      if (!seen.has(current)) {
        roots.push(current);
        seen.add(current);
      }
      current = current.parentElement || null;
      depth += 1;
    }
    return roots;
  }
  function collectPreviewNodes(root) {
    if (!root || !root.querySelectorAll) return [];
    var nodes = root.querySelectorAll('img, canvas, video, picture, [style*="background-image"]');
    var out = [];
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      if (!isVisible(node)) continue;
      var rect = node.getBoundingClientRect();
      if (rect.width < 24 || rect.height < 24) continue;
      out.push({
        node: node,
        rect: rect,
        text: normalize(node.getAttribute && (node.getAttribute('aria-label') || node.getAttribute('title')) || ''),
      });
    }
    return out;
  }
  var composer = findComposer();
  if (!composer || !isVisible(composer)) {
    return { ok: false, preview_found: false, scope: 'composer_surface' };
  }
  var composerRect = composer.getBoundingClientRect();
  var roots = collectRoots(composer);
  for (var rIdx = 0; rIdx < roots.length; rIdx++) {
    var previews = collectPreviewNodes(roots[rIdx]);
    for (var pIdx = 0; pIdx < previews.length; pIdx++) {
      var rect = previews[pIdx].rect;
      var horizontallyNear = rect.right >= (composerRect.left - 160) && rect.left <= (composerRect.right + 220);
      var verticallyNear = Math.abs((rect.top + rect.height / 2) - (composerRect.top + composerRect.height / 2))
        <= Math.max(composerRect.height * 2.5, 220);
      if (!horizontallyNear || !verticallyNear) continue;
      return {
        ok: true,
        preview_found: true,
        scope: 'composer_surface',
        strategy: 'composer_surface_preview',
        bbox: {
          x: Math.round(rect.left),
          y: Math.round(rect.top),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        },
      };
    }
  }
  return { ok: true, preview_found: false, scope: 'composer_surface' };
}

function MAIN_closeComposerSettingsPanel() {
  function normalize(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); }
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
  function collectAll(root, selector) {
    var out = [];
    var queue = [root || document];
    var seen = new Set();
    while (queue.length > 0) {
      var curr = queue.shift();
      if (!curr || seen.has(curr)) continue;
      seen.add(curr);
      if (curr.querySelectorAll) {
        var direct = curr.querySelectorAll(selector);
        for (var idx = 0; idx < direct.length; idx++) out.push(direct[idx]);
        var descendants = curr.querySelectorAll('*');
        for (var jdx = 0; jdx < descendants.length; jdx++) {
          if (descendants[jdx].shadowRoot && !seen.has(descendants[jdx].shadowRoot)) {
            queue.push(descendants[jdx].shadowRoot);
          }
        }
      }
    }
    return out;
  }
  var slateEditors = collectAll(document, '[data-slate-editor="true"]');
  var editorCount = slateEditors.length;
  var editorCE = [];
  for (var e0 = 0; e0 < slateEditors.length; e0++) editorCE.push(slateEditors[e0].getAttribute('contenteditable'));

  var buttons = collectAll(document, 'button, [role="button"], [aria-expanded]');
  for (var i = 0; i < buttons.length; i++) {
    var btn = buttons[i];
    if (!isVisible(btn)) continue;
    var raw = normalize(btn.textContent || btn.getAttribute('aria-label') || '');
    var lower = raw.toLowerCase();
    if (!raw || raw.length > 200) continue;
    if (/crop_9_16/i.test(raw) || /crop_free/i.test(raw) ||
        (/video/i.test(raw) && /1x/i.test(raw)) ||
        (/frames/i.test(raw) && /1x/i.test(raw)) ||
        ((lower === 'video' || lower.indexOf('video ') === 0) && btn.getAttribute('aria-expanded') === 'true')) {
      clickEl(btn);
      return { action: 'pill_closed_pass1', editor_count: editorCount, editor_ce: editorCE, btn_text: raw.slice(0, 80) };
    }
  }
  for (var e2 = 0; e2 < buttons.length; e2++) {
    if (buttons[e2].getAttribute && buttons[e2].getAttribute('aria-expanded') === 'true' && isVisible(buttons[e2])) {
      clickEl(buttons[e2]);
      return { action: 'pill_closed_expanded', editor_count: editorCount, editor_ce: editorCE };
    }
  }
  var focused = document.activeElement;
  if (focused && focused !== document.body) {
    var escEvent = new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, which: 27, bubbles: true, cancelable: true });
    focused.dispatchEvent(escEvent);
    document.dispatchEvent(escEvent);
    return { action: 'escape_on_focused', editor_count: editorCount, editor_ce: editorCE };
  }
  return { action: 'no_close_action_taken', editor_count: editorCount, editor_ce: editorCE };
}

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

  // Strategy 4: close Flow help/support panel if it is open and focus-trapping.
  // Live telemetry shows "Help Panel" can stay mounted after prior recovery
  // attempts, which interferes with composer-local settings clicks.
  if (!dismissed) {
    var helpPanelVisible = false;
    var helpNodes = document.querySelectorAll('[aria-label], [role="dialog"], [role="complementary"], aside, section');
    for (var h = 0; h < helpNodes.length; h++) {
      if (!isVisible(helpNodes[h])) continue;
      var helpText = lower(
        (helpNodes[h].getAttribute && helpNodes[h].getAttribute('aria-label') || '') + ' ' +
        (helpNodes[h].textContent || '')
      );
      if (helpText.indexOf('help panel') >= 0 || helpText.indexOf('product help') >= 0) {
        helpPanelVisible = true;
        break;
      }
    }
    if (helpPanelVisible) {
      try {
        var focused2 = document.activeElement;
        var escTarget2 = (focused2 && focused2 !== document.body) ? focused2 : document;
        escTarget2.dispatchEvent(new KeyboardEvent('keydown', {
          key: 'Escape', code: 'Escape', keyCode: 27, which: 27, bubbles: true, cancelable: true,
        }));
        dismissed = true;
        method = 'help_panel_escape';
      } catch (e) {}
    }
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

async function _runB2AUploadPickerOpenOnly(scripting, tabId, opts, stages, recordStage) {
  const settle = Math.max(150, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS));
  const editorState = await _runMainWorld(scripting, tabId, function () {
    function isVisible(el) {
      if (!el || !el.getBoundingClientRect) return false;
      var r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return false;
      var s = window.getComputedStyle(el);
      return Boolean(s && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0);
    }
    var composer = document.querySelector('[aria-label="Editable text"], [role="textbox"], [data-slate-editor="true"][contenteditable="true"], textarea[placeholder*="What do you want"], textarea, [contenteditable="true"]');
    var ok = Boolean(composer && isVisible(composer) && String(window.location.href || '').indexOf('/project/') >= 0);
    return {
      ok: ok,
      current_url: String(window.location.href || ''),
      composer_found: Boolean(composer && isVisible(composer)),
      prompt_field_found: Boolean(composer),
    };
  }, []);
  if (!editorState || editorState.ok !== true) {
    recordStage('F2V_V2A_PROJECT_EDITOR_OPENED', 'FAIL', 'FLOW_EDITOR_NOT_OPENED');
    return {
      ok: false,
      error: 'FLOW_EDITOR_NOT_OPENED',
      detail: editorState || null,
      stages: stages.map(function (item) { return item.stage; }),
      stage_events: stages,
    };
  }
  recordStage('F2V_V2A_PROJECT_EDITOR_OPENED', 'PASS', JSON.stringify({
    current_url: editorState.current_url || null,
    composer_found: Boolean(editorState.composer_found),
    prompt_field_found: Boolean(editorState.prompt_field_found),
  }));

  const launcher = await _runMainWorld(scripting, tabId, MAIN_findComposerAddMediaLauncher, ['data-bosmax-b2a']);
  if (!launcher || launcher.ok !== true) {
    var launcherError = launcher && launcher.reason === 'wrong_scope'
      ? 'FLOW_ADD_MEDIA_LAUNCHER_WRONG_SCOPE'
      : launcher && launcher.reason === 'editor_not_opened'
        ? 'FLOW_EDITOR_NOT_OPENED'
        : 'FLOW_ADD_MEDIA_LAUNCHER_NOT_FOUND';
    var launcherMessage = launcherError;
    if (launcher && typeof launcher === 'object') {
      launcherMessage += ' detail=' + JSON.stringify({
        text: launcher.text || null,
        aria_label: launcher.aria_label || null,
        role: launcher.role || null,
        tag: launcher.tag || null,
        bbox: launcher.bbox || null,
        near_composer: launcher.near_composer,
        near_prompt_field: launcher.near_prompt_field,
        near_generate_button: launcher.near_generate_button,
        candidate_source: launcher.candidate_source || null,
        reason: launcher.reason || null,
      });
    }
    recordStage('F2V_V2A_ADD_MEDIA_LAUNCHER_FOUND', 'FAIL', launcherMessage);
    return {
      ok: false,
      error: launcherError,
      detail: launcher || null,
      stages: stages.map(function (item) { return item.stage; }),
      stage_events: stages,
    };
  }
  recordStage('F2V_V2A_ADD_MEDIA_LAUNCHER_FOUND', 'PASS', JSON.stringify({
    text: launcher.text || null,
    aria_label: launcher.aria_label || null,
    role: launcher.role || null,
    tag: launcher.tag || null,
    bbox: launcher.bbox || null,
    near_composer: Boolean(launcher.near_composer),
    near_prompt_field: Boolean(launcher.near_prompt_field),
    near_generate_button: Boolean(launcher.near_generate_button),
    candidate_source: launcher.candidate_source || 'composer_scoped_scan',
  }));

  const reactClickResult = await _runMainWorld(scripting, tabId, MAIN_invokeReactFiberSubmit, [launcher.stamp_attr, launcher.stamp_id]);
  const clickResult = reactClickResult && reactClickResult.ok === true
    ? Object.assign({ click_method: 'react_fiber' }, reactClickResult)
    : await _runMainWorld(scripting, tabId, MAIN_clickStampedElement, [launcher.stamp_attr, launcher.stamp_id]);
  if (!clickResult || clickResult.ok !== true) {
    recordStage('F2V_V2A_ADD_MEDIA_LAUNCHER_CLICKED', 'FAIL', 'FLOW_ADD_MEDIA_LAUNCHER_CLICK_FAILED');
    return {
      ok: false,
        error: 'FLOW_ADD_MEDIA_LAUNCHER_CLICK_FAILED',
        detail: clickResult || null,
      stages: stages.map(function (item) { return item.stage; }),
      stage_events: stages,
    };
  }
  recordStage('F2V_V2A_ADD_MEDIA_LAUNCHER_CLICKED', 'PASS', JSON.stringify({
    text: launcher.text || null,
    role: launcher.role || null,
    tag: launcher.tag || null,
    click_method: clickResult && clickResult.click_method || clickResult && clickResult.strategy || 'dom_click',
  }));

  await _sleep(settle);
  const pickerState = await _runMainWorld(scripting, tabId, MAIN_getUploadPickerStateForB2A, []);
  if (!pickerState || pickerState.ok !== true || pickerState.modal_found !== true) {
    recordStage('F2V_V2A_UPLOAD_PICKER_OPENED', 'FAIL', 'FLOW_UPLOAD_PICKER_NOT_OPENED');
    return {
      ok: false,
      error: 'FLOW_UPLOAD_PICKER_NOT_OPENED',
      detail: pickerState || null,
      stages: stages.map(function (item) { return item.stage; }),
      stage_events: stages,
    };
  }
  recordStage('F2V_V2A_UPLOAD_PICKER_OPENED', 'PASS', JSON.stringify({
    modal_found: true,
    dialog_role_found: Boolean(pickerState.dialog_role_found),
    modal_text_sample: pickerState.modal_text_sample || null,
    upload_action_candidates: pickerState.upload_action_candidates || [],
  }));

  if (pickerState.upload_media_found !== true || !pickerState.upload_action) {
    recordStage('F2V_V2A_UPLOAD_MEDIA_ACTION_FOUND', 'FAIL', 'FLOW_UPLOAD_MEDIA_ACTION_NOT_FOUND');
    return {
      ok: false,
      error: 'FLOW_UPLOAD_MEDIA_ACTION_NOT_FOUND',
      detail: pickerState || null,
      stages: stages.map(function (item) { return item.stage; }),
      stage_events: stages,
    };
  }
  recordStage('F2V_V2A_UPLOAD_MEDIA_ACTION_FOUND', 'PASS', JSON.stringify({
    upload_media_found: true,
    text: pickerState.upload_action.text || null,
    aria_label: pickerState.upload_action.aria_label || null,
    role: pickerState.upload_action.role || null,
    tag: pickerState.upload_action.tag || null,
    inside_modal: true,
  }));
  recordStage('F2V_V2A_STOPPED_BEFORE_FILE_UPLOAD', 'PASS', JSON.stringify({
    stopped_at: 'UPLOAD_PICKER_OPENED',
    file_upload_attempted: false,
    add_to_prompt_attempted: false,
    settings_attempted: false,
    prompt_injection_attempted: false,
    generate_attempted: false,
  }));

  return {
    ok: true,
    stopped_at: 'UPLOAD_PICKER_OPENED',
    stages: stages.map(function (item) { return item.stage; }),
    stage_events: stages,
    file_upload_attempted: false,
    add_to_prompt_attempted: false,
    settings_attempted: false,
    prompt_injection_attempted: false,
    generate_attempted: false,
  };
}

function _buildSettingsPanelFailureDetail(reason, payload) {
  const data = payload || {};
  return JSON.stringify({
    reason: reason || null,
    target_tab_url: data.target_tab_url || null,
    document_title: data.document_title || null,
    current_url: data.current_url || null,
    surface_check_reason: data.surface_check_reason || null,
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
    launcher_dom_info: data.launcher_dom_info || null,
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
  diagnostics.surface_check_reason = surfaceCheck?.reason || null;
  diagnostics.current_url = surfaceCheck?.current_url || diagnostics.target_tab_url || null;
  if (!surfaceCheck || surfaceCheck.ok !== true) {
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
        strategy: result.strategy || 'launcher',
        label: result.strategy || 'launcher',
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
        diagnostics.surface_check_reason = surfaceCheck?.reason || null;
        diagnostics.current_url = surfaceCheck?.current_url || diagnostics.target_tab_url || null;
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
  var settingCategory = null;
  const explicitModelStep = (step.kind || _stepKind(step)) === 'model' && !step.acceptCurrent;
  function _pillShowsRatio(rawText, target) {
    const s = String(rawText || '').toLowerCase();
    if (target === '9:16') return /crop[_\s-]*9[_\s:.\-]*16/.test(s) || /\b9\s*[:：]\s*16\b/.test(s) || s.indexOf('portrait') >= 0;
    if (target === '16:9') return /crop[_\s-]*16[_\s:.\-]*9/.test(s) || /\b16\s*[:：]\s*9\b/.test(s) || s.indexOf('landscape') >= 0;
    if (target === '1:1') return /crop[_\s-]*1[_\s:.\-]*1/.test(s) || /\b1\s*[:：]\s*1\b/.test(s) || s.indexOf('square') >= 0;
    return false;
  }
  function _pillShowsCount(rawText, target) {
    const s = String(rawText || '').toLowerCase();
    if (target === '1x') return /\b1\s*(?:x|×|variation)\b/.test(s) || /\bx\s*1\b/.test(s) || s.indexOf('1x') >= 0;
    if (target === '2x') return /\b2\s*(?:x|×|variations)\b/.test(s) || /\bx\s*2\b/.test(s) || s.indexOf('2x') >= 0;
    return false;
  }
  
  // 1. Semantic Verification — check if the setting is already applied.
  // Uses structured pill tokens (detectedRatio/Count/ModelFamily) so it works
  // even when the pill is model-agnostic (e.g. "Nano Banana Pro crop_9_16 1x"
  // with no "video" token). Ratio/count/model do NOT hard-require topMode to
  // be 'Video' — the presence of the token on the pill is the proof; we only
  // exclude an explicit Image-mode workspace.
  const compState = await _runMainWorld(scripting, tabId, MAIN_getBottomComposerState, []);
  if (compState && compState.ok === true) {
    const kind = step.kind || _stepKind(step);
    const rawPillText = String(compState.pillText || '');
    let alreadyApplied = false;
    if (kind === 'mode') {
      alreadyApplied = compState.topMode === 'Video';
    } else if (kind === 'submode') {
      alreadyApplied = (compState.topMode === 'Video') && (compState.subMode === 'Frames');
    } else if (kind === 'ratio') {
      alreadyApplied = (compState.detectedRatio === '9:16') || _pillShowsRatio(rawPillText, '9:16');
    } else if (kind === 'count') {
      alreadyApplied = (compState.detectedCount === '1x') || _pillShowsCount(rawPillText, '1x');
    } else if (kind === 'model') {
      const obsFamily = compState.detectedModelFamily || '';
      const obsCanon = compState.detectedModelCanonical || '';
      if (step.acceptCurrent) {
        // No specific model requested — always skip immediately.
        // Pill detection is unreliable when the settings panel is open (pill
        // is occluded), so never scan DOM for a model we don't need to change.
        alreadyApplied = true;
      } else {
        const wantFamily = step.modelFamily || '';
        const wantCanon = step.modelCanonical || '';
        // Family-level match: any Veo variant satisfies 'veo' family request,
        // any Nano Banana variant satisfies 'nano banana' family request.
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

  if (explicitModelStep) {
    const surfaceState = await _runMainWorld(scripting, tabId, MAIN_isComposerSurfaceOpen, []);
    if (!surfaceState || surfaceState.ok !== true) {
      console.log("[FlowAgent] Explicit model requested. Opening settings panel before model scan.");
      await _openComposerSettingsPanel(scripting, tabId, opts);
    }
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
    const _stepK = step.kind || _stepKind(step);
    if (_stepK === 'ratio') settingCategory = 'aspect';
    else if (_stepK === 'count') settingCategory = 'count';
    else if (_stepK === 'model') settingCategory = 'model';
    
    if (settingCategory) {
      console.log(`[FlowAgent] Option ${step.label} not directly visible. Searching for launcher for: ${settingCategory}`);
      // Find launcher inside settings panel
      const launcherInfo = await _runMainWorld(
        scripting, tabId,
        MAIN_findAndStampSettingLauncher,
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
        // Keyword fallback: exact label not found after sub-launcher click.
        // Scan for ANY option containing the target model family keyword.
        // Handles Google Flow UI renames (e.g. 'Veo 3.2', 'Veo Fast', etc.)
        if (settingCategory === 'model' && (!findResult || !findResult.ok || !Array.isArray(findResult.matches) || !findResult.matches.length)) {
          const kw = step.modelFamily || '';
          if (kw) {
            const kwFind = await _runMainWorld(scripting, tabId, MAIN_findVisibleModelByKeyword, [kw, stampAttr]);
            if (kwFind) {
              findResult = { ok: true, matches: [kwFind] };
              console.log(`[FlowAgent] Model keyword fallback after sub-launcher: family='${kw}' matched '${kwFind.text}'`);
            }
          }
        }
      } else if (settingCategory === 'model') {
        console.log("[FlowAgent] Model launcher not found in settings panel. Trying keyword scan for model family.");
        const kw = step.modelFamily || (step.acceptCurrent ? '' : 'veo');
        if (kw) {
          const kwFind = await _runMainWorld(scripting, tabId, MAIN_findVisibleModelByKeyword, [kw, stampAttr]);
          if (kwFind) {
            findResult = { ok: true, matches: [kwFind] };
            console.log(`[FlowAgent] Model keyword direct scan: family='${kw}' matched '${kwFind.text}'`);
          }
        }
        if (!findResult?.matches?.length) {
          console.log("[FlowAgent] No model option found. Bypassing model step — current model is accepted.");
          return { ok: true, label: step.label, role: 'defaulted', bbox: null, skipped: true, visible_candidates: [] };
        }
      }
    }
  }

  // Keyword fallback for model step before error path: scan entire visible DOM.
  if (settingCategory === 'model' && (!findResult || !findResult.ok || !Array.isArray(findResult.matches) || !findResult.matches.length)) {
    const kw = step.modelFamily || '';
    if (kw) {
      const kwFind = await _runMainWorld(scripting, tabId, MAIN_findVisibleModelByKeyword, [kw, stampAttr]);
      if (kwFind) {
        findResult = { ok: true, matches: [kwFind] };
        console.log(`[FlowAgent] Model keyword last-resort scan: family='${kw}' matched '${kwFind.text}'`);
      }
    }
    // If still nothing found, bypass gracefully if acceptCurrent
    if ((!findResult || !findResult.matches?.length) && step.acceptCurrent) {
      console.log('[FlowAgent] Model not found but acceptCurrent=true — bypassing model step.');
      return { ok: true, label: step.label, role: 'defaulted', bbox: null, skipped: true, visible_candidates: [] };
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
    const failKind = step.kind || _stepKind(step);
    let verifiedFromPill = false;
    const rawFailPillText = String(failState?.pillText || '');
    if (failState && failState.ok === true) {
      if (failKind === 'ratio') {
        verifiedFromPill = (failState.detectedRatio === '9:16') || _pillShowsRatio(rawFailPillText, '9:16');
      } else if (failKind === 'count') {
        verifiedFromPill = (failState.detectedCount === '1x') || _pillShowsCount(rawFailPillText, '1x');
      } else if (failKind === 'model') {
        verifiedFromPill = step.acceptCurrent
          ? Boolean(failState.detectedModelCanonical || failState.detectedModelFamily)
          : (Boolean(step.modelFamily) && failState.detectedModelFamily === step.modelFamily);
      }
    }
    if (verifiedFromPill) {
      console.log(`[FlowAgent] Setting ${step.label} confirmed from composer pill after menu scan failure — accepting current state.`);
      return {
        ok: true,
        label: step.label,
        role: 'pill_confirmed_after_scan_failure',
        bbox: null,
        skipped: true,
        visible_candidates: findResult?.visible_candidates || [],
      };
    }
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
  function pillShowsRatio(rawText, target) {
    const s = String(rawText || '').toLowerCase();
    if (target === '9:16') return /crop[_\s-]*9[_\s:.\-]*16/.test(s) || /\b9\s*[:：]\s*16\b/.test(s) || s.indexOf('portrait') >= 0;
    return false;
  }
  function pillShowsCount(rawText, target) {
    const s = String(rawText || '').toLowerCase();
    if (target === '1x') return /\b1\s*(?:x|×|variation)\b/.test(s) || /\bx\s*1\b/.test(s) || s.indexOf('1x') >= 0;
    return false;
  }
  const results = {};
  const seq = Array.isArray(sequence) && sequence.length ? sequence : SOP_SEQUENCE;
  const stampAttr = opts?.stampAttr || 'data-bosmax-option';
  for (const step of seq) {
    const found = await _runMainWorld(
      scripting, tabId, MAIN_findVisibleCandidatesByExactLabel,
      [step.label, step.aliases || [], step.preferredRoles || [], stampAttr],
    );
    if (found?.ok && Array.isArray(found.matches) && found.matches.length > 0) {
      results[step.label] = {
        found: true,
        role: found.matches[0].role,
        selected: found.matches[0].selected === true,
      };
    } else {
      results[step.label] = { found: false };
    }
  }
  let saveVisible = false;
  let saveClicked = false;
  const saveButton = await _runMainWorld(
    scripting,
    tabId,
    MAIN_findVisibleCandidatesByExactLabel,
    ['Save', [], ['button', 'menuitem'], stampAttr],
  );
  if (saveButton?.ok && Array.isArray(saveButton.matches) && saveButton.matches.length > 0) {
    saveVisible = true;
    const saveClick = await _runMainWorld(
      scripting,
      tabId,
      MAIN_clickStampedElement,
      [saveButton.matches[0].stamp_attr, saveButton.matches[0].stamp_id],
    );
    saveClicked = Boolean(saveClick?.ok);
    await _sleep(Math.max(300, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));
  }

  const closeResult = await _runMainWorld(scripting, tabId, MAIN_closeComposerSettingsPanel, []);
  await _sleep(Math.max(500, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));
  const collapsedState = await _runMainWorld(scripting, tabId, MAIN_getBottomComposerState, []);
  const desiredModel = _resolveDesiredModel(opts?.job || null);
  const desiredModelCanonical = desiredModel?.canon || '';
  const desiredModelFamily = desiredModel?.family || '';
  const ratioStep = seq.find(function (step) { return step && step.label === '9:16'; }) || null;
  const countStep = seq.find(function (step) { return step && step.label === '1x'; }) || null;
  const collapsedRatioOk = Boolean(collapsedState && (
    collapsedState.detectedRatio === '9:16' || pillShowsRatio(collapsedState.pillText || '', '9:16')
  ));
  const collapsedCountOk = Boolean(collapsedState && (
    collapsedState.detectedCount === '1x' || pillShowsCount(collapsedState.pillText || '', '1x')
  ));
  const collapsedModelCanonical = String(collapsedState?.detectedModelCanonical || '').toLowerCase();
  const collapsedModelFamily = String(collapsedState?.detectedModelFamily || '').toLowerCase();
  const collapsedModelMatchesDesiredFamily = Boolean(
    desiredModelFamily &&
    collapsedModelFamily &&
    collapsedModelFamily === desiredModelFamily
  );
  let ratioProof = {
    visible: collapsedRatioOk,
    passed: collapsedRatioOk,
    source: collapsedRatioOk ? 'collapsed_config_pill' : null,
  };
  let countProof = {
    visible: collapsedCountOk,
    passed: collapsedCountOk,
    source: collapsedCountOk ? 'collapsed_config_pill' : null,
  };
  const visibleWrongModelInSettingsContext = Boolean(
    desiredModelCanonical
    && collapsedModelCanonical
    && collapsedModelCanonical !== desiredModelCanonical
    && !collapsedModelMatchesDesiredFamily
  );
  let modelProof = {
    visible: Boolean(collapsedModelCanonical || collapsedModelFamily),
    passed:
      !desiredModelCanonical ||
      !collapsedModelCanonical ||
      collapsedModelCanonical === desiredModelCanonical ||
      collapsedModelMatchesDesiredFamily,
    source: collapsedModelCanonical ? 'collapsed_config_pill' : null,
  };

  const needsReopenVerification = Boolean(
    !ratioProof.passed ||
    !countProof.passed ||
    (!modelProof.visible && desiredModelCanonical)
  );
  if (needsReopenVerification) {
    const reopenPanel = await _openComposerSettingsPanel(scripting, tabId, opts);
    if (reopenPanel?.ok) {
      if (!ratioProof.passed && ratioStep) {
        const exactRatio = await _runMainWorld(
          scripting,
          tabId,
          MAIN_findVisibleCandidatesByExactLabel,
          [ratioStep.label, ratioStep.aliases || [], ratioStep.preferredRoles || [], stampAttr],
        );
        if (exactRatio?.ok && Array.isArray(exactRatio.matches) && exactRatio.matches.length > 0) {
          ratioProof = {
            visible: true,
            passed: exactRatio.matches[0].selected === true,
            source: 'reopened_settings_panel',
          };
        }
      }
      if (!countProof.passed && countStep) {
        const exactCount = await _runMainWorld(
          scripting,
          tabId,
          MAIN_findVisibleCandidatesByExactLabel,
          [countStep.label, countStep.aliases || [], countStep.preferredRoles || [], stampAttr],
        );
        if (exactCount?.ok && Array.isArray(exactCount.matches) && exactCount.matches.length > 0) {
          countProof = {
            visible: true,
            passed: exactCount.matches[0].selected === true,
            source: 'reopened_settings_panel',
          };
        }
      }
      if (!modelProof.visible && desiredModelCanonical) {
        const exactModel = await _runMainWorld(
          scripting,
          tabId,
          MAIN_findVisibleCandidatesByExactLabel,
          [desiredModel.label, desiredModel.aliases || [], ['button', 'option', 'menuitemradio', 'menuitem'], stampAttr],
        );
        if (exactModel?.ok && Array.isArray(exactModel.matches) && exactModel.matches.length > 0) {
          modelProof = {
            visible: true,
            passed: exactModel.matches[0].selected === true,
            source: 'reopened_settings_panel',
          };
        } else {
          const familyModel = desiredModelFamily
            ? await _runMainWorld(scripting, tabId, MAIN_findVisibleModelByKeyword, [desiredModelFamily, stampAttr])
            : null;
          if (familyModel) {
            modelProof = {
              visible: true,
              passed: true,
              source: 'reopened_settings_panel_family_visible',
            };
          }
        }
      }
      await _runMainWorld(scripting, tabId, MAIN_closeComposerSettingsPanel, []);
      await _sleep(Math.max(400, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));
    }
  }

  const persistenceVerified = Boolean(
    ratioProof.passed
    && countProof.passed
    && !visibleWrongModelInSettingsContext
    && modelProof.passed
    && (!saveVisible || saveClicked)
  );
  return {
    ok: persistenceVerified,
    results,
    save_visible: saveVisible,
    save_clicked: saveClicked,
    close_result: closeResult || null,
    ratio_9_16_persisted: ratioProof.passed,
    count_1x_persisted: countProof.passed,
    ratio_proof: ratioProof,
    count_proof: countProof,
    model_proof: modelProof,
    visible_wrong_model_in_settings_context: visibleWrongModelInSettingsContext,
    persistence_verified: persistenceVerified,
    persistence_source:
      ratioProof.source ||
      countProof.source ||
      modelProof.source ||
      'collapsed_config_pill',
  };
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
 * Upload lane helpers.
 *
 * The current source-of-truth F2V path is:
 *   Start -> Upload media -> wait -> Add to Prompt -> prompt -> arrow.
 * A composer-side "+ / add_2 Create" launcher is kept only as a last-resort
 * fallback when the Start slot is genuinely unavailable in the live DOM.
 */
async function _clickStartEntryPoint(scripting, tabId, opts) {
  await _runMainWorld(scripting, tabId, MAIN_closeComposerSettingsPanel, []);
  await _sleep(Math.max(300, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));

  const startSlot = await _clickStart(scripting, tabId, opts);
  if (startSlot.ok) {
    return startSlot;
  }

  const stampAttr = opts?.stampAttr || 'data-bosmax-option';
  const launcher = await _runMainWorld(
    scripting,
    tabId,
    MAIN_stampAssetPickerLauncher,
    [stampAttr],
  );
  if (launcher && launcher.ok === true && launcher.stamp_id) {
    const click = await _runMainWorld(
      scripting,
      tabId,
      MAIN_clickStampedElement,
      [launcher.stamp_attr, launcher.stamp_id],
    );
    if (click && click.ok === true) {
      return {
        ok: true,
        label: 'Start',
        role: launcher.strategy || 'asset_picker_launcher_fallback',
        bbox: launcher.bbox || null,
        visible_candidates: [],
      };
    }
  }
  return startSlot;
}

async function _clickStart(scripting, tabId, opts) {
  const trustedCoordinateClick = opts?.preferTrustedStartClick === true
    ? (opts?.cdpCoordinateClick || opts?.coordinateClick || null)
    : null;
  if (typeof trustedCoordinateClick === 'function') {
    const stampAttr = opts?.stampAttr || 'data-bosmax-option';
    const findResult = await _runMainWorld(
      scripting, tabId, MAIN_findVisibleCandidatesByExactLabel,
      ['Start', ['Start frame', '+ Add start frame', 'Add start frame'], ['button', 'option'], stampAttr],
    );
    if (findResult && findResult.ok === true && Array.isArray(findResult.matches) && findResult.matches.length > 0) {
      const top = findResult.matches[0];
      if (top && top.bbox) {
        const coordinateResult = await trustedCoordinateClick({
          tabId,
          strategy: 'start_slot',
          text: top.text || 'Start',
          bbox: top.bbox,
          x: Math.round(top.bbox.x + (top.bbox.width / 2)),
          y: Math.round(top.bbox.y + (top.bbox.height / 2)),
        });
        if (coordinateResult && coordinateResult.ok === true) {
          await _sleep(Math.max(150, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));
          return {
            ok: true,
            label: 'Start',
            role: top.role || 'start_slot',
            bbox: top.bbox,
            visible_candidates: findResult.visible_candidates || [],
            click_method: 'cdp_visible_coordinate',
          };
        }
      }
    }
  }
  const step = {
    label: 'Start',
    aliases: ['Start frame', '+ Add start frame', 'Add start frame'],
    preferredRoles: ['button', 'option'],
    errorCode: ERR.START_BUTTON_NOT_FOUND,
    stage: 'F2V_SOP_START_CLICKED',
  };
  const result = await _clickVisibleOptionExact(scripting, tabId, step, opts);
  if (result.ok) return result;
  const stampAttr = opts?.stampAttr || 'data-bosmax-option';
  console.log('[FlowAgent] Start slot: exact label not found. Trying semantic slot fallback.');
  const slot = await _runMainWorld(scripting, tabId, MAIN_findUploadSlotByLabel, ['Start', stampAttr]);
  if (slot && slot.stamp_id) {
    if (typeof trustedCoordinateClick === 'function' && slot.bbox) {
      const coordinateResult = await trustedCoordinateClick({
        tabId,
        strategy: 'start_slot_fallback',
        text: slot.text || 'Start',
        bbox: slot.bbox,
        x: Math.round(slot.bbox.x + (slot.bbox.width / 2)),
        y: Math.round(slot.bbox.y + (slot.bbox.height / 2)),
      });
      if (coordinateResult && coordinateResult.ok === true) {
        await _sleep(Math.max(150, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));
        return {
          ok: true,
          label: 'Start',
          role: slot.role || 'slot_fallback',
          bbox: slot.bbox || null,
          visible_candidates: [],
          click_method: 'cdp_visible_coordinate',
        };
      }
    }
    const click = await _runMainWorld(scripting, tabId, MAIN_clickStampedElement, [slot.stamp_attr, slot.stamp_id]);
    if (click && click.ok === true) {
      return { ok: true, label: 'Start', role: slot.role || 'slot_fallback', bbox: slot.bbox || null, visible_candidates: [] };
    }
  }
  return result;
}

async function _clickVisibleActionExact(scripting, tabId, step, opts) {
  const stampAttr = opts?.stampAttr || 'data-bosmax-option';
  const findResult = await _runMainWorld(
    scripting, tabId, MAIN_findVisibleCandidatesByExactLabel,
    [step.label, step.aliases || [], step.preferredRoles || [], stampAttr],
  );
  if (!findResult || findResult.ok !== true || !Array.isArray(findResult.matches) || findResult.matches.length === 0) {
    return {
      ok: false,
      error: step.errorCode,
      detail: 'visible_action_not_found',
      label: step.label,
      visible_candidates: findResult?.visible_candidates || [],
    };
  }
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
      visible_candidates: findResult?.visible_candidates || [],
    };
  }
  await _sleep(Math.max(150, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));
  return {
    ok: true,
    label: step.label,
    role: top.role,
    bbox: top.bbox,
    visible_candidates: findResult?.visible_candidates || [],
  };
}

async function _clickUploadMedia(scripting, tabId, opts) {
  const strictUploadAction = opts?.strictUploadAction === true;
  const trustedCoordinateClick = opts?.preferTrustedUploadClick === true
    ? (opts?.cdpCoordinateClick || opts?.coordinateClick || null)
    : null;
  let pickerState = null;
  if (strictUploadAction) {
    const deadline = Date.now() + Math.max(0, Number(opts?.uploadActionWaitMs ?? 2500));
    do {
      pickerState = await _runMainWorld(scripting, tabId, MAIN_getUploadPickerStateForB2A, []);
      if (pickerState && pickerState.ok === true && pickerState.upload_media_found === true) {
        break;
      }
      if (Date.now() >= deadline) break;
      await _sleep(150);
    } while (true);
    if (
      pickerState &&
      pickerState.ok === true &&
      pickerState.upload_media_found === true &&
      pickerState.upload_action &&
      pickerState.upload_action.bbox &&
      typeof trustedCoordinateClick === 'function'
    ) {
      const bbox = pickerState.upload_action.bbox;
      const coordinateResult = await trustedCoordinateClick({
        tabId,
        strategy: 'upload_media_picker_action',
        text: pickerState.upload_action.text || 'Upload media',
        bbox,
        x: Math.round(bbox.x + (bbox.width / 2)),
        y: Math.round(bbox.y + (bbox.height / 2)),
      });
      if (coordinateResult && coordinateResult.ok === true) {
        await _sleep(Math.max(150, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));
        return {
          ok: true,
          label: 'Upload media',
          role: pickerState.upload_action.role || 'picker_upload_action',
          bbox,
          visible_candidates: pickerState.upload_action_candidates || [],
          click_method: 'cdp_visible_coordinate',
        };
      }
    }
  }
  // Google Flow V2's add/upload control is labelled "Add Media" (Material icon
  // ligature renders the textContent as "addAdd Media"; the matcher's stripIcon
  // reduces it to "Add Media"). Older builds used "Upload media" / "Upload from
  // device" / "Upload from computer". The strict (CDP) path previously omitted
  // "Add Media", so the item was never matched, the native chooser never opened,
  // and the CDP wait failed with ERR_CDP_FILE_CHOOSER_TIMEOUT (gfv2_live_2/3/4 —
  // live dump showed "addAdd Media" / "dashboardAll Media", no "Upload media").
  // In V2 the add/upload control is "Add Media", which opens a nested submenu whose
  // item is "Upload from computer" (it, in turn, opens the native chooser). The first
  // pass clicks "Add Media"; the nested pass (opts.uploadSubmenu) targets the upload
  // item and deliberately EXCLUDES "Add Media" to avoid re-clicking the parent.
  const uploadAliases = opts?.uploadSubmenu
    ? ['Upload from computer', 'upload Upload from computer', 'Upload media', 'upload Upload media', 'Upload from device', 'Upload', 'Upload from gallery']
    : ['Add Media', 'add Add Media', 'upload Upload media', 'Upload', 'Upload from device', 'Upload from computer', 'upload Upload from computer'];
  if (typeof trustedCoordinateClick === 'function') {
    const stampAttr = opts?.stampAttr || 'data-bosmax-option';
    const findResult = await _runMainWorld(
      scripting, tabId, MAIN_findVisibleCandidatesByExactLabel,
      ['Upload media', uploadAliases, ['button', 'option', 'menuitem'], stampAttr],
    );
    if (findResult && findResult.ok === true && Array.isArray(findResult.matches) && findResult.matches.length > 0) {
      const top = findResult.matches[0];
      if (top && top.bbox) {
        const coordinateResult = await trustedCoordinateClick({
          tabId,
          strategy: 'upload_media',
          text: top.text || 'Upload media',
          bbox: top.bbox,
          x: Math.round(top.bbox.x + (top.bbox.width / 2)),
          y: Math.round(top.bbox.y + (top.bbox.height / 2)),
        });
        if (coordinateResult && coordinateResult.ok === true) {
          await _sleep(Math.max(150, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));
          return {
            ok: true,
            label: 'Upload media',
            role: top.role || 'upload_media',
            bbox: top.bbox,
            visible_candidates: findResult.visible_candidates || [],
            click_method: 'cdp_visible_coordinate',
          };
        }
      }
    }
  }
  const step = {
    label: 'Upload media',
    aliases: uploadAliases,
    preferredRoles: ['button', 'option', 'menuitem'],
    errorCode: ERR.UPLOAD_MEDIA_NOT_FOUND,
    stage: 'F2V_SOP_UPLOAD_CLICKED',
  };
  const result = await _clickVisibleActionExact(scripting, tabId, step, opts);
  if (result.ok) return result;
  if (strictUploadAction) {
    return {
      ...result,
      detail: pickerState && pickerState.modal_found === true
        ? 'strict_picker_upload_action_not_found'
        : result.detail,
    };
  }
  // Symbol fallback: exact label failed — try aria-label / icon-only detection.
  // Covers the case where Google Flow shows only a + (add) icon with no text label.
  const stampAttr = opts?.stampAttr || 'data-bosmax-option';
  console.log('[FlowAgent] Upload media: exact label not found. Trying symbol/aria-label fallback.');
  const sym = await _runMainWorld(scripting, tabId, MAIN_findUploadBySymbol, [stampAttr]);
  if (sym && sym.stamp_id) {
    console.log(`[FlowAgent] Upload media: symbol match — "${String(sym.text || '').trim()}". Clicking.`);
    if (typeof trustedCoordinateClick === 'function' && sym.bbox) {
      const coordinateResult = await trustedCoordinateClick({
        tabId,
        strategy: 'upload_media_symbol_fallback',
        text: sym.text || 'Upload media',
        bbox: sym.bbox,
        x: Math.round(sym.bbox.x + (sym.bbox.width / 2)),
        y: Math.round(sym.bbox.y + (sym.bbox.height / 2)),
      });
      if (coordinateResult && coordinateResult.ok === true) {
        await _sleep(Math.max(150, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));
        return { ok: true, label: 'Upload media', role: 'symbol_fallback', bbox: sym.bbox, click_method: 'cdp_visible_coordinate' };
      }
    }
    const click = await _runMainWorld(scripting, tabId, MAIN_clickStampedElement, [sym.stamp_attr, sym.stamp_id]);
    if (click && click.ok === true) {
      return { ok: true, label: 'Upload media', role: 'symbol_fallback', bbox: sym.bbox };
    }
  }
  console.log('[FlowAgent] Upload media: symbol fallback failed. Trying direct start/add-media surfaces.');
  const slot = await _runMainWorld(scripting, tabId, MAIN_findUploadSlotByLabel, ['Start', stampAttr]);
  if (slot && slot.stamp_id) {
    if (typeof trustedCoordinateClick === 'function' && slot.bbox) {
      const coordinateResult = await trustedCoordinateClick({
        tabId,
        strategy: 'upload_media_start_slot_fallback',
        text: slot.text || 'Start',
        bbox: slot.bbox,
        x: Math.round(slot.bbox.x + (slot.bbox.width / 2)),
        y: Math.round(slot.bbox.y + (slot.bbox.height / 2)),
      });
      if (coordinateResult && coordinateResult.ok === true) {
        await _sleep(Math.max(150, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));
        return { ok: true, label: 'Upload media', role: 'start_slot_upload_fallback', bbox: slot.bbox, click_method: 'cdp_visible_coordinate' };
      }
    }
    const slotClick = await _runMainWorld(scripting, tabId, MAIN_clickStampedElement, [slot.stamp_attr, slot.stamp_id]);
    if (slotClick && slotClick.ok === true) {
      return { ok: true, label: 'Upload media', role: 'start_slot_upload_fallback', bbox: slot.bbox };
    }
  }
  const launcher = await _runMainWorld(scripting, tabId, MAIN_stampAssetPickerLauncher, [stampAttr]);
  if (launcher && launcher.ok === true && launcher.stamp_id) {
    if (typeof trustedCoordinateClick === 'function' && launcher.bbox) {
      const coordinateResult = await trustedCoordinateClick({
        tabId,
        strategy: 'upload_media_asset_picker_launcher',
        text: launcher.text || 'Add Media',
        bbox: launcher.bbox,
        x: Math.round(launcher.bbox.x + (launcher.bbox.width / 2)),
        y: Math.round(launcher.bbox.y + (launcher.bbox.height / 2)),
      });
      if (coordinateResult && coordinateResult.ok === true) {
        await _sleep(Math.max(150, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));
        return { ok: true, label: 'Upload media', role: launcher.strategy || 'asset_picker_launcher_fallback', bbox: launcher.bbox, click_method: 'cdp_visible_coordinate' };
      }
    }
    const launcherClick = await _runMainWorld(scripting, tabId, MAIN_clickStampedElement, [launcher.stamp_attr, launcher.stamp_id]);
    if (launcherClick && launcherClick.ok === true) {
      return { ok: true, label: 'Upload media', role: launcher.strategy || 'asset_picker_launcher_fallback', bbox: launcher.bbox };
    }
  }
  return result;
}

async function _clickAddToPrompt(scripting, tabId, opts) {
  const step = {
    label: 'Add to Prompt',
    aliases: ['Add Prompt'],
    preferredRoles: ['button', 'option', 'menuitem'],
    errorCode: ERR.ADD_TO_PROMPT_NOT_FOUND,
    stage: 'F2V_SOP_UPLOAD_WAIT_DONE',
  };
  const stampAttr = opts?.stampAttr || 'data-bosmax-option';
  const deadline = Date.now() + Math.max(0, Number(opts?.addToPromptWaitMs ?? 12000));
  let lastResult = { ok: false, error: step.errorCode, detail: 'visible_action_not_found' };
  while (Date.now() <= deadline) {
    const result = await _clickVisibleActionExact(scripting, tabId, step, opts);
    if (result.ok) return result;
    lastResult = result;
    const assetCard = await _runMainWorld(scripting, tabId, MAIN_selectAssetPickerCandidate, [stampAttr]);
    if (assetCard && assetCard.ok === true && assetCard.stamp_id) {
      const selectClick = await _runMainWorld(scripting, tabId, MAIN_clickStampedElement, [assetCard.stamp_attr, assetCard.stamp_id]);
      if (selectClick && selectClick.ok === true) {
        await _sleep(Math.max(250, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));
        const retryResult = await _clickVisibleActionExact(scripting, tabId, step, opts);
        if (retryResult.ok) {
          return {
            ...retryResult,
            role: retryResult.role || 'asset_card_then_add_to_prompt',
          };
        }
        lastResult = retryResult;
      }
    }
    const addPrompt = await _runMainWorld(scripting, tabId, MAIN_findAddToPromptButton, [stampAttr]);
    if (addPrompt && addPrompt.ok === true && addPrompt.stamp_id) {
      const click = await _runMainWorld(scripting, tabId, MAIN_clickStampedElement, [addPrompt.stamp_attr, addPrompt.stamp_id]);
      if (click && click.ok === true) {
        return { ok: true, label: 'Add to Prompt', role: 'add_to_prompt_fallback', bbox: addPrompt.bbox || null };
      }
    }
    const composerPreviewState = await _runMainWorld(scripting, tabId, MAIN_getComposerAssetPreviewState, []);
    if (composerPreviewState && composerPreviewState.ok === true && composerPreviewState.preview_found === true) {
      return {
        ok: true,
        label: 'Add to Prompt',
        role: 'composer_prompt_bound_preview_present',
        skipped: true,
        bbox: composerPreviewState.bbox || null,
      };
    }
    await _sleep(500);
  }
  return lastResult;
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
  if (stamp.disabled === true) {
    return { ok: false, error: ERR.GENERATE_PRECONDITION_FAILED, detail: 'generate_button_disabled', button_text: stamp.text || null };
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

function MAIN_getPostSubmitOutputState() {
  function normalize(value) {
    return String(value == null ? '' : value).replace(/\s+/g, ' ').trim();
  }
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    var style = window.getComputedStyle(el);
    return Boolean(style && style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) !== 0);
  }
  function getComposerRoot() {
    var prompt = document.querySelector('[aria-label="Editable text"], [role="textbox"], [data-slate-editor="true"][contenteditable="true"], textarea, [contenteditable="true"], input[type="text"]');
    if (prompt && prompt.closest) {
      return prompt.closest('form, [role="form"], section, article, main, div') || prompt;
    }
    return document.querySelector('form, [role="form"]');
  }
  function isInsideComposer(el, composerRoot) {
    if (!el || !composerRoot) return false;
    var current = el;
    while (current) {
      if (current === composerRoot) return true;
      current = current.parentElement || null;
    }
    return false;
  }
  function extractFilename(text) {
    var match = String(text || '').match(/\b([a-z0-9][a-z0-9._-]*\.(?:mp4|mov|webm|png|jpe?g|webp|gif))\b/i);
    return match ? match[1] : null;
  }
  // Output-ready requires GENUINE render evidence — a rendered <video>, a real
  // media filename, or media co-present with an explicit project/render signal.
  // A bare menu/dropdown (e.g. the "Veo 3.1 - Lite" model selector) is NOT an
  // output and must never satisfy output_ready. Regression: the previous version
  // declared output_ready as soon as ANY menu-like control existed, so
  // GFV2_OUTPUT_READY fired ~1s after Generate, before the video rendered.
  function hasRenderedVideo(root) {
    if (!root || !root.querySelectorAll) return false;
    var vids = root.querySelectorAll('video');
    for (var i = 0; i < vids.length; i++) {
      var v = vids[i];
      if (!isVisible(v)) continue;
      if (v.currentSrc || v.src || (v.querySelector && v.querySelector('source[src]'))) return true;
      var r = v.getBoundingClientRect();
      if (r.width > 80 && r.height > 80) return true;
    }
    return false;
  }

  var composerRoot = getComposerRoot();
  var containers = document.querySelectorAll('article, section, div, li, figure, aside');
  var best = null;
  for (var idx = 0; idx < containers.length; idx++) {
    var container = containers[idx];
    if (!isVisible(container) || isInsideComposer(container, composerRoot)) continue;
    var text = normalize(container.textContent || '');
    var filename = extractFilename(text);
    var video = hasRenderedVideo(container);
    var hasMedia = Boolean(container.querySelector && container.querySelector('img, video, canvas'));
    var hasProjectSignal = /download project|generated-|render(?:ed|ing)?|\.mp4\b|\.mov\b|\.webm\b|\.png\b|\.jpe?g\b|\.webp\b|\.gif\b/i.test(text);
    var qualifies = Boolean(video || filename || (hasMedia && hasProjectSignal));
    if (!qualifies) continue;
    var rect = container.getBoundingClientRect();
    var score = 0;
    if (video) score += 200;
    if (filename) score += 120;
    if (hasMedia) score += 60;
    if (hasProjectSignal) score += 50;
    if (rect.top < 700) score += 40;
    score += Math.round(rect.left / 10);
    if (!best || score > best.score) {
      best = {
        score: score,
        text: text,
        filename: filename,
        has_video: video,
        has_media: hasMedia,
      };
    }
  }

  if (!best) {
    return {
      ok: true,
      output_ready: false,
      menu_found: false,
      filename: null,
      menu_text: null,
      output_text_excerpt: '',
    };
  }

  return {
    ok: true,
    output_ready: true,
    menu_found: false,
    filename: best.filename,
    menu_text: null,
    has_video: Boolean(best.has_video),
    output_text_excerpt: String(best.text || '').slice(0, 200),
  };
}

function MAIN_stampProjectMenuButton(stampAttr) {
  function normalize(value) {
    return String(value == null ? '' : value).replace(/\s+/g, ' ').trim();
  }
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    var style = window.getComputedStyle(el);
    return Boolean(style && style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) !== 0);
  }
  function getComposerRoot() {
    var prompt = document.querySelector('[aria-label="Editable text"], [role="textbox"], [data-slate-editor="true"][contenteditable="true"], textarea, [contenteditable="true"], input[type="text"]');
    if (prompt && prompt.closest) {
      return prompt.closest('form, [role="form"], section, article, main, div') || prompt;
    }
    return document.querySelector('form, [role="form"]');
  }
  function isInsideComposer(el, composerRoot) {
    if (!el || !composerRoot) return false;
    var current = el;
    while (current) {
      if (current === composerRoot) return true;
      current = current.parentElement || null;
    }
    return false;
  }

  var composerRoot = getComposerRoot();
  // Many composer controls expose aria-haspopup="menu" (the model selector,
  // settings openers, aspect/count chips, the agent panel). NONE of them is the
  // project/output three-dot menu. Reject them and require a genuine "more
  // options" affordance, so Download Project is searched in the correct menu.
  // Regression: the previous version accepted any aria-haspopup="menu", so the
  // "Veo 3.1 - Lite ▾" model dropdown was opened and Download Project was absent.
  var DISALLOW = [
    'arrow_drop_down', 'veo', 'nano banana', 'sora', 'kling', 'imagen', 'flux',
    'view settings', 'settings_2', 'tune', 'agent', 'crop_', 'aspect', 'generate', 'model',
  ];
  var nodes = document.querySelectorAll('button, [role="button"], [aria-haspopup="menu"]');
  var best = null;
  for (var i = 0; i < nodes.length; i++) {
    var node = nodes[i];
    if (!isVisible(node) || isInsideComposer(node, composerRoot)) continue;
    var ariaLabel = (node.getAttribute && (node.getAttribute('aria-label') || '')) || '';
    var title = (node.getAttribute && (node.getAttribute('title') || '')) || '';
    var combined = normalize((node.textContent || '') + ' ' + ariaLabel + ' ' + title).toLowerCase();
    if (combined.indexOf('download project') >= 0) continue;
    var labelLc = normalize(ariaLabel).toLowerCase();
    var isMoreOptions =
      combined.indexOf('more_vert') >= 0 ||
      combined.indexOf('more options') >= 0 ||
      labelLc === 'more' ||
      labelLc === 'more options' ||
      labelLc === 'project options';
    if (!isMoreOptions) continue;
    var disallowed = false;
    for (var d = 0; d < DISALLOW.length; d++) {
      if (combined.indexOf(DISALLOW[d]) >= 0) { disallowed = true; break; }
    }
    if (disallowed) continue;
    var rect = node.getBoundingClientRect();
    var score = 0;
    if (combined.indexOf('more_vert') >= 0) score += 300;
    if (node.getAttribute && node.getAttribute('aria-haspopup') === 'menu') score += 60;
    if (rect.top < 700) score += 60;
    score += Math.round(rect.left);
    if (!best || score > best.score) {
      best = { el: node, score: score, text: combined };
    }
  }
  if (!best || !best.el) return { ok: false, reason: 'project_menu_not_found' };
  var attr = String(stampAttr || 'data-bosmax-project-menu');
  var id = attr + '-' + Date.now();
  best.el.setAttribute(attr, id);
  return {
    ok: true,
    stamp_attr: attr,
    stamp_id: id,
    text: normalize(best.el.textContent || best.el.getAttribute && (best.el.getAttribute('aria-label') || best.el.getAttribute('title')) || ''),
  };
}

function MAIN_getDownloadObservableState() {
  function normalize(value) {
    return String(value == null ? '' : value).replace(/\s+/g, ' ').trim();
  }
  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    var style = window.getComputedStyle(el);
    return Boolean(style && style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) !== 0);
  }
  var nodes = document.querySelectorAll('[role="status"], [aria-live], button, [role="button"], div, span');
  for (var i = 0; i < nodes.length; i++) {
    var node = nodes[i];
    if (!isVisible(node)) continue;
    var text = normalize(node.textContent || node.getAttribute && (node.getAttribute('aria-label') || node.getAttribute('title')) || '');
    if (!text) continue;
    if (/download|downloading|saved/i.test(text)) {
      return { ok: true, observable: true, text: text.slice(0, 200) };
    }
  }
  return { ok: true, observable: false, text: null };
}

async function _submitGenerateArrow(scripting, tabId, opts) {
  const stampAttr = opts?.submitStampAttr || 'data-bosmax-submit-target';
  const stamp = await _runMainWorld(scripting, tabId, MAIN_stampGenerateButton, [stampAttr]);
  if (!stamp || stamp.ok !== true) {
    return { ok: false, error: ERR.GFV2_SUBMIT_ARROW_NOT_FOUND, detail: 'generate_button_not_visible' };
  }
  if (stamp.disabled === true) {
    return { ok: false, error: ERR.GENERATE_PRECONDITION_FAILED, detail: 'generate_button_disabled', button_text: stamp.text || null, stamp };
  }
  const fiber = await _runMainWorld(scripting, tabId, MAIN_invokeReactFiberSubmit, [stamp.stamp_attr, stamp.stamp_id]);
  if (fiber && fiber.ok === true) {
    return { ok: true, strategy: fiber.strategy, fiber_visited: fiber.visited, button_text: stamp.text, stamp };
  }
  if (opts?.allowFallbackClick === true) {
    const click = await _runMainWorld(scripting, tabId, MAIN_clickStampedElement, [stamp.stamp_attr, stamp.stamp_id]);
    if (click && click.ok === true) {
      return { ok: true, strategy: 'fallback_synthetic_click', fiber_visited: fiber?.visited || 0, button_text: stamp.text, stamp };
    }
  }
  return {
    ok: false,
    error: ERR.MAIN_WORLD_SUBMIT_HANDLER_NOT_FOUND,
    detail: fiber?.reason || 'react_handler_not_found',
    fiber_visited: fiber?.visited || 0,
    button_text: stamp.text || null,
    stamp,
  };
}

async function _waitForPostSubmitOutput(scripting, tabId, opts) {
  const timeoutMs = Math.max(1000, Number(opts?.outputWaitTimeoutMs ?? 30000));
  const pollMs = Math.max(100, Number(opts?.outputWaitPollMs ?? 400));
  const deadline = Date.now() + timeoutMs;
  let lastState = null;
  do {
    lastState = await _runMainWorld(scripting, tabId, MAIN_getPostSubmitOutputState, []);
    if (lastState && lastState.ok === true && lastState.output_ready === true) {
      return { ok: true, state: lastState };
    }
    if (Date.now() >= deadline) break;
    await _sleep(pollMs);
  } while (true);
  return { ok: false, error: ERR.GFV2_OUTPUT_NOT_READY, detail: lastState || 'output_not_ready' };
}

async function _openProjectMenu(scripting, tabId, opts) {
  const stampAttr = opts?.projectMenuStampAttr || 'data-bosmax-project-menu';
  const menu = await _runMainWorld(scripting, tabId, MAIN_stampProjectMenuButton, [stampAttr]);
  if (!menu || menu.ok !== true) {
    return { ok: false, error: ERR.GFV2_PROJECT_MENU_NOT_FOUND, detail: menu?.reason || 'project_menu_not_found' };
  }
  const click = await _runMainWorld(scripting, tabId, MAIN_clickStampedElement, [menu.stamp_attr, menu.stamp_id]);
  if (!click || click.ok !== true) {
    return { ok: false, error: ERR.GFV2_PROJECT_MENU_NOT_FOUND, detail: click?.reason || 'project_menu_click_failed', menu };
  }
  await _sleep(Math.max(150, Number(opts?.settleMs ?? SOP_DEFAULT_SETTLE_MS)));
  return { ok: true, menu };
}

async function _clickDownloadProjectAction(scripting, tabId, opts) {
  const result = await _clickVisibleActionExact(scripting, tabId, {
    label: 'Download Project',
    aliases: [],
    preferredRoles: ['button', 'menuitem'],
    errorCode: ERR.GFV2_DOWNLOAD_PROJECT_NOT_FOUND,
  }, opts);
  if (!result.ok) return result;
  const observed = await _runMainWorld(scripting, tabId, MAIN_getDownloadObservableState, []);
  return {
    ok: true,
    label: result.label,
    role: result.role,
    bbox: result.bbox,
    observable: Boolean(observed && observed.observable),
    observable_text: observed && observed.observable ? observed.text : null,
  };
}

async function executeGfv2PostSubmitDownloadContinuation(deps, tabId, job, opts = {}) {
  const scripting = deps && deps.scripting;
  if (!scripting || typeof scripting.executeScript !== 'function') {
    return { ok: false, error: ERR.EXECUTION_THREW, detail: 'scripting_adapter_missing', stages: [] };
  }
  const telemetry = deps && deps.telemetry;
  const stages = [];
  const recordStage = (stage, status, message) => {
    stages.push({ stage, status, message });
    _emitStage(telemetry, stage, status, message);
  };
  const stageResults = {
    prompt_ready: false,
    submit_arrow_found: false,
    submit_clicked: false,
    output_ready: false,
    output_proof: null,
    project_menu_opened: false,
    project_menu_proof: null,
    download_clicked: false,
    download_proof: null,
  };

  try {
    const promptProof = opts?.promptProof || null;
    if (!promptProof || promptProof.passed !== true) {
      recordStage('GFV2_PROMPT_READY_FOR_SUBMIT', 'FAIL', 'prompt_proof_missing');
      return { ok: false, error: ERR.GENERATE_PRECONDITION_FAILED, detail: 'prompt_proof_missing', stages, stage_results: stageResults };
    }
    stageResults.prompt_ready = true;
    recordStage(
      'GFV2_PROMPT_READY_FOR_SUBMIT',
      'PASS',
      `inserted_length=${Number(promptProof.inserted_length || 0)} field_value_length=${Number(promptProof.field_value_length || 0)}`,
    );

    const preGenerateSettleMs = Math.max(0, Number(opts?.preGenerateSettleMs ?? 1200));
    if (preGenerateSettleMs > 0) {
      await _sleep(preGenerateSettleMs);
    }
    await _runMainWorld(scripting, tabId, MAIN_dismissPromoOverlays, []);

    const submit = await _submitGenerateArrow(scripting, tabId, { ...opts, allowFallbackClick: true });
    if (!submit.ok) {
      if (submit.error === ERR.GFV2_SUBMIT_ARROW_NOT_FOUND) {
        recordStage('GFV2_SUBMIT_ARROW_NOT_FOUND', 'FAIL', submit.detail);
      }
      return { ok: false, error: submit.error, detail: submit.detail, stages, stage_results: stageResults };
    }
    stageResults.submit_arrow_found = true;
    stageResults.submit_clicked = true;
    recordStage('GFV2_SUBMIT_ARROW_FOUND', 'PASS', `button=${JSON.stringify(submit.button_text || null)}`);
    recordStage('GFV2_SUBMIT_ARROW_CLICKED', 'PASS', `strategy=${submit.strategy} fiber_visited=${submit.fiber_visited || 0}`);
    recordStage('GFV2_GENERATE_SUBMITTED', 'PASS', `strategy=${submit.strategy}`);

    recordStage(
      'GFV2_OUTPUT_WAIT_STARTED',
      'PASS',
      `timeout_ms=${Math.max(1000, Number(opts?.outputWaitTimeoutMs ?? 30000))} poll_ms=${Math.max(100, Number(opts?.outputWaitPollMs ?? 400))}`,
    );
    const output = await _waitForPostSubmitOutput(scripting, tabId, opts);
    if (!output.ok) {
      recordStage('GFV2_OUTPUT_NOT_READY', 'FAIL', JSON.stringify(output.detail || null));
      return { ok: false, error: output.error, detail: output.detail, stages, stage_results: stageResults };
    }
    stageResults.output_ready = true;
    stageResults.output_proof = output.state;
    recordStage(
      'GFV2_OUTPUT_READY',
      'PASS',
      `menu_found=${Boolean(output.state && output.state.menu_found)} filename=${output.state && output.state.filename ? output.state.filename : ''}`.trim(),
    );

    const menu = await _openProjectMenu(scripting, tabId, opts);
    if (!menu.ok) {
      recordStage('GFV2_PROJECT_MENU_NOT_FOUND', 'FAIL', menu.detail);
      return { ok: false, error: menu.error, detail: menu.detail, stages, stage_results: stageResults };
    }
    stageResults.project_menu_opened = true;
    stageResults.project_menu_proof = {
      button_text: menu.menu && menu.menu.text ? menu.menu.text : null,
    };
    recordStage('GFV2_PROJECT_MENU_FOUND', 'PASS', `button=${JSON.stringify(menu.menu?.text || null)}`);
    recordStage('GFV2_PROJECT_MENU_OPENED', 'PASS', `button=${JSON.stringify(menu.menu?.text || null)}`);

    const download = await _clickDownloadProjectAction(scripting, tabId, opts);
    if (!download.ok) {
      recordStage('GFV2_DOWNLOAD_PROJECT_NOT_FOUND', 'FAIL', download.detail);
      return { ok: false, error: download.error, detail: download.detail, stages, stage_results: stageResults };
    }
    const timestamp = new Date().toISOString();
    stageResults.download_clicked = true;
    stageResults.download_proof = {
      clicked: true,
      timestamp,
      filename: output.state && output.state.filename ? output.state.filename : null,
      browser_ui_evidence: download.observable_text || null,
      observable: Boolean(download.observable),
    };
    recordStage('GFV2_DOWNLOAD_PROJECT_CLICKED', 'PASS', `role=${download.role || 'button'}`);
    recordStage(
      'GFV2_DOWNLOAD_STARTED',
      'PASS',
      `timestamp=${timestamp} filename=${stageResults.download_proof.filename || ''} observable=${Boolean(download.observable)}`,
    );
    recordStage(
      'GFV2_OUTPUT_RETURNED_TO_SYSTEM',
      'PASS',
      JSON.stringify({
        timestamp,
        filename: stageResults.download_proof.filename || null,
        browser_ui_evidence: stageResults.download_proof.browser_ui_evidence || null,
      }),
    );

    return {
      ok: true,
      stages,
      stage_results: stageResults,
      summary: {
        download_clicked: true,
        timestamp,
        filename: stageResults.download_proof.filename || null,
        browser_ui_evidence: stageResults.download_proof.browser_ui_evidence || null,
      },
    };
  } catch (err) {
    recordStage('GFV2_OUTPUT_RETURNED_TO_SYSTEM', 'FAIL', `ERR_F2V_POST_SUBMIT_THREW: ${String(err?.message || err || '')}`);
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

function _shouldTrustWorkspacePackageSettings(job) {
  if (!job || job.mode !== 'F2V') return false;
  const hasWorkspaceAuthority = Boolean(
    job.workspace_execution_package_id ||
    job.prompt_package_snapshot_id ||
    job.prompt_fingerprint
  );
  const startAsset = job.startAsset;
  const hasResolvedStartAsset = Boolean(
    startAsset &&
    (
      startAsset.localFilePath ||
      startAsset.downloadUrl ||
      startAsset.previewUrl ||
      startAsset.mediaId ||
      startAsset.assetId
    )
  );
  return hasWorkspaceAuthority && hasResolvedStartAsset;
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
    settings_proof: null,
    prompt_inserted: false,
    prompt_proof: null,
    start_clicked: false,
    media_attached: false,
    upload_proof: null,
    add_to_prompt_proof: null,
    generate_proof: null,
    generate_submitted: false,
  };

  try {
    if (String(opts?.stopAfter || job?.stopAfter || '') === 'UPLOAD_PICKER_OPENED') {
      return await _runB2AUploadPickerOpenOnly(scripting, tabId, opts, stages, recordStage);
    }

    // Step 1 — new project / resume. The caller passes newProjectFn so
    // navigation resume / recursion guard stays in the existing path.
    // When absent, we trust the tab is already on a project editor.
    if (typeof deps.newProjectFn === 'function') {
      const np = await deps.newProjectFn(tabId, job);
      if (!np || np.ok !== true) {
        recordStage('F2V_SOP_NEW_PROJECT_READY', 'FAIL', np?.error || 'new_project_failed');
        return { ok: false, error: ERR.NEW_PROJECT_FAILED, detail: np?.error || null, stages };
      }
      const settledTabId = Number(np.flow_tab_id || np.tabId || 0);
      if (settledTabId > 0) {
        tabId = settledTabId;
      }
    }
    recordStage('F2V_SOP_NEW_PROJECT_READY', 'PASS', null);

    // Resolve the requested model (Nano Banana, Veo, …). When the job does not
    // name a model we accept whatever the editor already shows on the pill —
    // the live reality is "🍌 Nano Banana Pro crop_9_16 1x".
    const desiredModel = _resolveDesiredModel(job);
    let effectiveSequence = _buildEffectiveSequence(desiredModel);
    // Google Flow V2 has NO 'Video'/'Frames' mode controls (BOSMAX-internal labels
    // only). For GFV2 settings, drop the mode steps and configure ratio/count/model
    // directly — clicking a non-existent Video/Frames option is ERR_F2V_OPTION_*_NOT_FOUND.
    if (opts?.gfv2SkipModeSteps === true) {
      effectiveSequence = effectiveSequence.filter((s) => s.label !== 'Video' && s.label !== 'Frames');
    }
    recordStage('F2V_SOP_MODEL_TARGET_RESOLVED', 'PASS',
      `desired=${desiredModel ? desiredModel.canon : 'accept_current'} family=${desiredModel ? desiredModel.family : 'any'}`);

    // GFV2 demands granular DOM-confirmed settings proof, so the GFV2 lane forces
    // the DOM settings path (opts.gfv2ForceDomSettings) instead of trusting package
    // defaults — the authority shortcut applies/proves nothing granularly.
    if (_shouldTrustWorkspacePackageSettings(job) && opts?.gfv2ForceDomSettings !== true) {
      const packageSettingSummary = {
        authority: 'workspace_package',
        orientation: job?.orientation || null,
        model: desiredModel ? desiredModel.canon : (job?.model || null),
        count: Number(job?.count || 0) || null,
        workspace_execution_package_id: job?.workspace_execution_package_id || null,
        start_asset_present: Boolean(job?.startAsset),
      };
      recordStage('F2V_SOP_SETTINGS_EXPLORER_STARTED', 'PASS',
        `source=workspace_package_authority summary=${JSON.stringify(packageSettingSummary)}`);
      stageResults.settings_proof = {
        ok: true,
        authority: 'workspace_package',
        bypassed: true,
        summary: packageSettingSummary,
      };
      stageResults.settings_configured = true;
      recordStage('F2V_SOP_SETTINGS_CONFIGURED', 'PASS',
        `source=workspace_package_authority summary=${JSON.stringify(packageSettingSummary)}`);
    } else {
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
          const modelReadable = Boolean(preState && preState.detectedModelCanonical);
          const modelOk = Boolean(preState && (desiredModel
            ? (preState.detectedModelFamily === desiredModel.family || preState.detectedModelCanonical === desiredModel.canon)
            : modelReadable));
          const modelNonFatal = ratioOk && countOk && !modelReadable;

          if (ratioOk && countOk && (modelOk || modelNonFatal)) {
            const confirmReason = modelOk
              ? 'tier_one_pill_confirmed'
              : 'tier_one_pill_confirmed_model_nonfatal';
            console.log(`[FlowAgent] Tier One: aspect + count${modelOk ? ' + model' : ' (model accepted as current — not on pill)'} already configured — no panel needed.`);
            recordStage('F2V_SOP_SETTINGS_LAUNCHER_FOUND', 'PASS', `launcher=${confirmReason}`);
            recordStage('F2V_SOP_SETTINGS_PANEL_OPENED', 'PASS',
              `strategy=${confirmReason} pill=${JSON.stringify(String(preState.pillText || '').slice(0, 80))}`);
          } else {
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

        recordStage('F2V_SOP_SETTING_CANDIDATES_SCANNED', 'PASS', `label=${step.label} count=${clickRes.visible_candidates?.length || 0}`);
        let stageName = step.stage;
        if (clickRes.skipped) {
          stageName = step.stage.replace('_CLICKED', '_CONFIRMED');
        }
        recordStage(stageName, 'PASS', `role=${clickRes.role}`);
        if (!clickRes.skipped && step.stage.indexOf('_CLICKED') >= 0) {
          const confirmedStage = step.stage.replace('_CLICKED', '_CONFIRMED');
          recordStage(confirmedStage, 'PASS', `role=${clickRes.role}`);
        }
      }

      const verify = await _verifySettingsPanelApplied(scripting, tabId, { ...opts, job }, effectiveSequence);
      stageResults.settings_proof = verify;
      stageResults.settings_configured = Boolean(verify?.ok);
      if (!verify?.ok) {
        recordStage('F2V_SOP_SETTINGS_CONFIGURED', 'FAIL', `results=${JSON.stringify(verify || {})}`);
        return {
          ok: false,
          error: ERR.SETTINGS_NOT_CONFIGURED_BEFORE_UPLOAD,
          detail: 'ui_contract_v2_settings_persistence_failed',
          stages,
          stage_results: stageResults,
        };
      }
      recordStage('F2V_SOP_SETTINGS_CONFIGURED', 'PASS', `results=${JSON.stringify(verify.results || {})} save_visible=${Boolean(verify.save_visible)} save_clicked=${Boolean(verify.save_clicked)} persistence_source=${verify.persistence_source || 'unknown'}`);
    }

    // GFV2 granular settings proof hook — runs AFTER settings are applied and BEFORE
    // upload, so the V2 contract's granular settings stages (panel opened, 9:16, 1x,
    // model veo/hidden-soft-pass/wrong-model, persisted) are DOM-confirmed IN ORDER.
    // No-op for non-GFV2 callers. A false `proceed` hard-fails the lane.
    if (typeof opts?.gfv2SettingsVerify === 'function') {
      const sv = await opts.gfv2SettingsVerify({ tabId });
      if (sv && sv.proceed === false) {
        return {
          ok: false,
          error: sv.error || 'GFV2_SETTINGS_NOT_VERIFIED',
          detail: sv.detail || null,
          stages,
          stage_results: stageResults,
        };
      }
    }

    // Step 9/10/11 — upload lane.
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
      // GFV2 contract telemetry (no-op for non-GFV2 callers).
      opts?.gfv2Stage?.('GFV2_CDP_FILE_CHOOSER_ARMED', 'PASS', `file=${armRes.expectedFileName || ''}`);
      if (armRes.materialized === true) {
        opts?.gfv2Stage?.(
          'GFV2_ASSET_MATERIALIZED',
          'PASS',
          `source_type=${armRes.sourceType || 'unknown'} name=${armRes.materializedName || armRes.expectedFileName || '?'} dir=${armRes.materializedDirLabel || 'flowkit-upload-staging'}`,
        );
      }
    }

    // Step 10 — open the upload entrypoint. Primary DOM flow clicks the
    // visible Start slot first, then continues into Upload media.
    const startResult = _useCdpUpload
      ? await _clickStartEntryPoint(scripting, tabId, { ...opts, preferTrustedStartClick: true })
      : await _clickStartEntryPoint(scripting, tabId, opts);
    if (!startResult.ok) {
      recordStage('F2V_SOP_START_CLICKED', 'FAIL', `${startResult.error} ${startResult.detail}`);
      return { ok: false, error: startResult.error, detail: startResult.detail, stages, stage_results: stageResults };
    }
    stageResults.start_clicked = true;
    recordStage('F2V_SOP_START_CLICKED', 'PASS', `role=${startResult.role}`);
    opts?.gfv2Stage?.('GFV2_UPLOAD_LAUNCHER_CLICKED', 'PASS', `role=${startResult.role}`);

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
      const startToUploadWaitMs = Math.max(0, Number(opts?.startToUploadWaitMs ?? 1000));
      const uploadWaitMs = Math.max(0, Number(opts?.uploadWaitMs ?? SOP_DEFAULT_UPLOAD_WAIT_MS));
      const postAddToPromptWaitMs = Math.max(0, Number(opts?.postAddToPromptWaitMs ?? 500));
      await _sleep(startToUploadWaitMs);
      // Step 11 (CDP) — Google Flow can expose either:
      //   1. a direct native chooser on Start, or
      //   2. a modal Upload media button after Start.
      // Arm the chooser before Start, then opportunistically click Upload media.
      // If the chooser already opened directly from Start, the upload button will
      // simply be absent and we continue waiting for the armed chooser event.
      const uploadResult = await _clickUploadMedia(
        scripting,
        tabId,
        { ...opts, preferTrustedUploadClick: true, strictUploadAction: true },
      );
      // GFV2 contract telemetry: the add/create launcher opening a menu is NOT the
      // same as the file chooser opening — the in-menu "Upload media" / "Upload from
      // computer" item must be clicked first. Emit the menu-item events explicitly so
      // a launcher click alone is never mistaken for an opened chooser.
      if (uploadResult?.ok) {
        opts?.gfv2Stage?.('GFV2_UPLOAD_MENU_OPENED', 'PASS', `role=${uploadResult.role || 'menu'}`);
        opts?.gfv2Stage?.('GFV2_UPLOAD_MEDIA_ITEM_FOUND', 'PASS', `label=${uploadResult.label || 'Upload media'} role=${uploadResult.role || ''}`);
        opts?.gfv2Stage?.('GFV2_UPLOAD_MEDIA_ITEM_CLICKED', 'PASS', `click_method=${uploadResult.click_method || 'dom'}`);
        // V2 nests: "Add Media" opens a submenu with "Upload from computer", which
        // opens the native chooser. Try the nested upload item (harmless if the
        // chooser already opened directly — the find simply misses and CDP still waits).
        await _sleep(Math.max(300, Number(opts?.uploadSubmenuWaitMs ?? 700)));
        let nestedMenuDump = '';
        try {
          const dump = await _runMainWorld(scripting, tabId, MAIN_dumpVisibleClickableTexts, []);
          nestedMenuDump = (dump?.items || []).map((it) => it.text || it.aria).filter(Boolean).slice(0, 24).join(' / ').slice(0, 400);
        } catch (_) {}
        const nested = await _clickUploadMedia(scripting, tabId, { ...opts, preferTrustedUploadClick: true, strictUploadAction: true, uploadSubmenu: true });
        if (nested?.ok) {
          opts?.gfv2Stage?.('GFV2_UPLOAD_MEDIA_ITEM_CLICKED', 'PASS', `nested_item=${nested.label || 'Upload from computer'} click_method=${nested.click_method || 'dom'}`);
        } else {
          opts?.gfv2Stage?.('GFV2_UPLOAD_SUBMENU_ITEMS', 'WAITING_FLOW', `nested_probe=${nested?.error || 'not_visible'} visible_items=[${nestedMenuDump}]`);
        }
      } else {
        // READ-ONLY: dump the real visible add-menu labels so we learn the V2 text.
        let menuDumpStr = '';
        try {
          const dump = await _runMainWorld(scripting, tabId, MAIN_dumpVisibleClickableTexts, []);
          menuDumpStr = (dump?.items || [])
            .map((it) => it.text || it.aria)
            .filter(Boolean)
            .slice(0, 24)
            .join(' / ')
            .slice(0, 400);
        } catch (_) {}
        opts?.gfv2Stage?.('GFV2_UPLOAD_MEDIA_ITEM_FOUND', 'FAIL', `upload_probe=${uploadResult?.error || 'not_visible'} visible_items=[${menuDumpStr}]`);
      }
      const fedRes = await opts.cdpFileChooserUpload({ phase: 'wait', tabId });
      if (!fedRes || fedRes.ok !== true) {
        const canRecoverViaDomFallback =
          (fedRes?.error === 'ERR_CDP_FILE_CHOOSER_TIMEOUT' ||
            fedRes?.error === 'ERR_CDP_FILE_CHOOSER_NOT_ARMED' ||
            String(fedRes?.error || '').indexOf('ERR_CDP_DEBUGGER_DETACHED:') === 0) &&
          typeof opts?.domUploadFallback === 'function';
        if (canRecoverViaDomFallback) {
          const fallbackRes = await opts.domUploadFallback({
            tabId,
            slotLabel: 'Start',
            assetSource: job?.startAsset || job?.productId || job?.startImageMediaId || null,
          });
          if (fallbackRes?.ok === true) {
            recordStage(
              'F2V_SOP_CDP_FILE_CHOOSER_FED',
              'SKIP',
              `recovered_via=dom_upload_fallback error=${fedRes.error} strategy=${fallbackRes.uploadStrategy || 'unknown'}`,
            );
            opts?.gfv2Stage?.('GFV2_CDP_FILE_CHOOSER_FED', 'PASS', `recovered_via=dom_upload_fallback strategy=${fallbackRes.uploadStrategy || 'dom_input'}`);
            recordStage(
              'F2V_SOP_UPLOAD_CLICKED',
              'PASS',
              `strategy=dom_upload_fallback role=${uploadResult?.role || 'button'} click_method=${uploadResult?.click_method || 'dom'} waited_ms=${startToUploadWaitMs}`,
            );
            await _sleep(uploadWaitMs);
            const addPromptResult = await _clickAddToPrompt(scripting, tabId, opts);
            if (!addPromptResult.ok) {
              recordStage('F2V_SOP_UPLOAD_WAIT_DONE', 'FAIL', `${addPromptResult.error} ${addPromptResult.detail}`);
              return { ok: false, error: addPromptResult.error, detail: addPromptResult.detail, stages, stage_results: stageResults };
            }
            stageResults.media_attached = true;
            stageResults.add_to_prompt_proof = {
              passed: true,
              role: addPromptResult.role || null,
              prompt_bound_media_preview: addPromptResult.role === 'composer_prompt_bound_preview_present',
            };
            stageResults.upload_proof = {
              passed: true,
              media_attached: true,
              via: 'dom_upload_fallback',
            };
            await _sleep(postAddToPromptWaitMs);
            recordStage(
              'F2V_SOP_UPLOAD_WAIT_DONE',
              'PASS',
              `waited_ms=${uploadWaitMs} add_to_prompt_role=${addPromptResult.role} post_wait_ms=${postAddToPromptWaitMs} strategy=dom_upload_fallback`,
            );
          } else {
            const uploadHint = uploadResult?.ok
              ? `upload_role=${uploadResult.role || 'unknown'}`
              : `upload_probe=${uploadResult?.error || 'not_visible'}`;
            recordStage('F2V_SOP_CDP_FILE_CHOOSER_FED', 'FAIL', `${fedRes?.error || ERR.UPLOAD_MEDIA_NOT_FOUND} ${fedRes?.detail || ''}`.trim());
            recordStage(
              'F2V_SOP_UPLOAD_CLICKED',
              'FAIL',
              `${fallbackRes?.error || fedRes?.error || ERR.UPLOAD_MEDIA_NOT_FOUND} strategy=dom_upload_fallback ${uploadHint}`.trim(),
            );
            return { ok: false, error: fallbackRes?.error || fedRes?.error || ERR.UPLOAD_MEDIA_NOT_FOUND, detail: fallbackRes?.detail || fedRes?.detail || null, stages, stage_results: stageResults };
          }
        } else {
        const uploadHint = uploadResult?.ok
          ? `upload_role=${uploadResult.role || 'unknown'}`
          : `upload_probe=${uploadResult?.error || 'not_visible'}`;
        recordStage('F2V_SOP_CDP_FILE_CHOOSER_FED', 'FAIL', `${fedRes?.error || ERR.UPLOAD_MEDIA_NOT_FOUND} ${fedRes?.detail || ''}`.trim());
        recordStage('F2V_SOP_UPLOAD_CLICKED', 'FAIL', `${fedRes?.error || ERR.UPLOAD_MEDIA_NOT_FOUND} strategy=cdp_file_chooser ${uploadHint}`.trim());
        // GFV2: when the chooser never opened AND no in-menu upload item was found/
        // clicked, the precise blocker is a missing menu item, not a generic timeout.
        if (!uploadResult?.ok) {
          opts?.gfv2Stage?.('GFV2_UPLOAD_MEDIA_ITEM_NOT_FOUND', 'FAIL', `upload_probe=${uploadResult?.error || 'not_visible'} chooser=${fedRes?.error || 'timeout'}`);
        } else {
          opts?.gfv2Stage?.('GFV2_CDP_FILE_CHOOSER_FED', 'FAIL', `${fedRes?.error || 'chooser_failed'}`);
        }
        const gfv2UploadError = !uploadResult?.ok ? 'GFV2_UPLOAD_MEDIA_ITEM_NOT_FOUND' : (fedRes?.error || ERR.UPLOAD_MEDIA_NOT_FOUND);
        return { ok: false, error: opts?.gfv2Stage ? gfv2UploadError : (fedRes?.error || ERR.UPLOAD_MEDIA_NOT_FOUND), detail: fedRes?.detail || null, stages, stage_results: stageResults };
        }
      }
      if (stageResults.media_attached !== true) {
        recordStage('F2V_SOP_CDP_FILE_CHOOSER_FED', 'PASS', `file=${fedRes.filePath || ''} backendNodeId=${fedRes.backendNodeId || ''}`);
        opts?.gfv2Stage?.('GFV2_CDP_FILE_CHOOSER_FED', 'PASS', `file=${fedRes.filePath || ''}`);
        recordStage(
          'F2V_SOP_UPLOAD_CLICKED',
          'PASS',
          uploadResult?.ok
            ? `strategy=cdp_file_chooser role=${uploadResult.role || 'unknown'} click_method=${uploadResult.click_method || 'dom'} waited_ms=${startToUploadWaitMs}`
            : `strategy=cdp_file_chooser role=direct_start click_method=start_slot waited_ms=${startToUploadWaitMs}`,
        );
        // Step 12 — wait for media attachment.
        await _sleep(uploadWaitMs);
        stageResults.media_attached = true;
        stageResults.upload_proof = {
          passed: true,
          media_attached: true,
          via: 'cdp_file_chooser',
        };
        stageResults.add_to_prompt_proof = {
          passed: true,
          role: 'media_attached',
          prompt_bound_media_preview: false,
        };
        recordStage('F2V_SOP_UPLOAD_WAIT_DONE', 'PASS', `waited_ms=${uploadWaitMs} strategy=cdp_file_chooser`);
      }
    } else {
      const startToUploadWaitMs = Math.max(0, Number(opts?.startToUploadWaitMs ?? 1000));
      await _sleep(startToUploadWaitMs);
      // Step 11 — click Upload media in the asset picker.
      const uploadResult = await _clickUploadMedia(scripting, tabId, opts);
      if (!uploadResult.ok) {
        recordStage('F2V_SOP_UPLOAD_CLICKED', 'FAIL', `${uploadResult.error} ${uploadResult.detail}`);
        return { ok: false, error: uploadResult.error, detail: uploadResult.detail, stages, stage_results: stageResults };
      }
      recordStage('F2V_SOP_UPLOAD_CLICKED', 'PASS', `role=${uploadResult.role} waited_ms=${startToUploadWaitMs}`);
      // Step 12 — wait for the upload card to settle, then confirm it into the prompt.
      const waitMs = Math.max(0, Number(opts?.uploadWaitMs ?? SOP_DEFAULT_UPLOAD_WAIT_MS));
      await _sleep(waitMs);
      const addPromptResult = await _clickAddToPrompt(scripting, tabId, opts);
      if (!addPromptResult.ok) {
        recordStage('F2V_SOP_UPLOAD_WAIT_DONE', 'FAIL', `${addPromptResult.error} ${addPromptResult.detail}`);
        return { ok: false, error: addPromptResult.error, detail: addPromptResult.detail, stages, stage_results: stageResults };
      }
      stageResults.media_attached = true;
      stageResults.add_to_prompt_proof = {
        passed: true,
        role: addPromptResult.role || null,
        prompt_bound_media_preview: addPromptResult.role === 'composer_prompt_bound_preview_present',
      };
      stageResults.upload_proof = {
        passed: true,
        media_attached: true,
        via: 'dom_upload_lane',
      };
      const postAddToPromptWaitMs = Math.max(0, Number(opts?.postAddToPromptWaitMs ?? 500));
      await _sleep(postAddToPromptWaitMs);
      recordStage('F2V_SOP_UPLOAD_WAIT_DONE', 'PASS', `waited_ms=${waitMs} add_to_prompt_role=${addPromptResult.role} post_wait_ms=${postAddToPromptWaitMs}`);
    }

    // Step 12 — insert prompt after asset upload confirmation.
    const promptResult = await _insertPrompt(scripting, tabId, job?.prompt || '');
    if (!promptResult.ok) {
      recordStage('F2V_SOP_PROMPT_INSERTED', 'FAIL', `${promptResult.error} ${promptResult.detail}`);
      return { ok: false, error: promptResult.error, detail: promptResult.detail, stages, stage_results: stageResults };
    }
    stageResults.prompt_inserted = true;
    stageResults.prompt_proof = {
      passed: true,
      inserted_length: promptResult.inserted_length,
      field_value_length: promptResult.field_value_length,
    };
    recordStage('F2V_SOP_PROMPT_INSERTED', 'PASS',
      `inserted_length=${promptResult.inserted_length} field_value_length=${promptResult.field_value_length}`);

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
    const preGenerateSettleMs = Math.max(0, Number(opts?.preGenerateSettleMs ?? 1200));
    if (preGenerateSettleMs > 0) {
      await _sleep(preGenerateSettleMs);
    }
    await _runMainWorld(scripting, tabId, MAIN_dismissPromoOverlays, []);
    let gen = await _invokeGenerate(scripting, tabId, { ...opts, allowFallbackClick: true });
    if (!gen.ok && gen.detail === 'generate_button_not_visible') {
      await _sleep(Math.max(500, Number(opts?.retryGenerateSettleMs ?? 1000)));
      await _runMainWorld(scripting, tabId, MAIN_dismissPromoOverlays, []);
      gen = await _invokeGenerate(scripting, tabId, { ...opts, allowFallbackClick: true });
    }
    if (!gen.ok) {
      recordStage('F2V_SOP_GENERATE_SUBMITTED', 'FAIL', `${gen.error} ${gen.detail}`);
      return { ok: false, error: gen.error, detail: gen.detail, stages, stage_results: stageResults };
    }
    stageResults.generate_proof = {
      passed: true,
      enabled: true,
      button_found: true,
    };
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
  executeGfv2PostSubmitDownloadContinuation,
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
  MAIN_getPostSubmitOutputState,
  MAIN_stampProjectMenuButton,
  MAIN_getDownloadObservableState,
  MAIN_stampAssetPickerLauncher,
  MAIN_findComposerAddMediaLauncher,
  MAIN_getUploadPickerStateForB2A,
  MAIN_dumpVisibleClickableTexts,
  MAIN_getBottomComposerState,
  MAIN_dismissPromoOverlays,
  MAIN_findVisibleModelByKeyword,
  MAIN_findUploadSlotByLabel,
  MAIN_findUploadBySymbol,
  MAIN_findAddToPromptButton,
  MAIN_selectAssetPickerCandidate,
  MAIN_getUploadSlotPreviewState,
  MAIN_getComposerAssetPreviewState,
  MAIN_closeComposerSettingsPanel,
  // Internal helpers (exported for unit tests)
  _openComposerSettingsPanel,
  _clickVisibleOptionExact,
  _verifySettingsPanelApplied,
  _insertPrompt,
  _clickStartEntryPoint,
  _clickStart,
  _clickUploadMedia,
  _clickAddToPrompt,
  _invokeGenerate,
  _submitGenerateArrow,
  _waitForPostSubmitOutput,
  _openProjectMenu,
  _clickDownloadProjectAction,
  _runB2AUploadPickerOpenOnly,
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
