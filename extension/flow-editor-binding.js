/**
 * Flow Kit — pure editor-binding decision logic.
 *
 * This module is DEPENDENCY-FREE (no `chrome`, no DOM, no network). It exists so
 * the editor-identity decisions can be unit-tested under `node --test` without a
 * browser, while `background.js` consumes the exact same logic at runtime.
 *
 * Loaded two ways:
 *   1. MV3 service worker  — `importScripts("flow-editor-binding.js")` attaches
 *      the API to `self.FlowEditorBinding`.
 *   2. Node unit tests     — `require("../flow-editor-binding.js")` returns the
 *      API via `module.exports`.
 *
 * Root cause it addresses: Google Flow is an SPA. Navigating from the Flow root
 * (`/fx/tools/flow`) into a project editor (`/fx/tools/flow/project/<id>`) uses
 * `history.pushState`, and `chrome.tabs.Tab.url` can stay STALE at the root.
 * The content script's live `window.location.href` is therefore AUTHORITATIVE
 * over `chrome.tabs.Tab.url` for editor identity.
 *
 * NOTE: the four URL predicates below are kept byte-for-byte in sync with the
 * copies in `background.js` (isProjectEditorUrl/isRootFlowUrl/
 * normalizeFlowProjectUrl/extractFlowProjectId). They are pure and must not
 * diverge.
 */
(function (globalScope) {
	"use strict";

	function isProjectEditorUrl(url) {
		const value = String(url || "");
		return (
			value.includes("/project/") ||
			value.includes("/edit/") ||
			/^https:\/\/labs\.google\/fx(?:\/[^/]+)?\/tools\/flow\/[^?#/]+(?:[/?#].*)?$/.test(
				value,
			)
		);
	}

	function isRootFlowUrl(url) {
		const value = String(url || "");
		return /^https:\/\/labs\.google\/fx(?:\/[^/]+)?\/tools\/flow\/?(?:[#?].*)?$/.test(
			value,
		);
	}

	function normalizeFlowProjectUrl(url) {
		const value = String(url || "").trim();
		if (!value) {
			return null;
		}
		try {
			const parsed = new URL(value);
			const normalizedPath = parsed.pathname.replace(/\/+$/, "");
			return `${parsed.origin}${normalizedPath}`;
		} catch (_) {
			return value.replace(/[?#].*$/, "").replace(/\/+$/, "") || null;
		}
	}

	function extractFlowProjectId(url) {
		const value = String(url || "").trim();
		const match = value.match(/\/project\/([^/?#]+)/i);
		return match?.[1] || null;
	}

	function describeUrl(url, source) {
		const value = String(url || "").trim();
		if (!value) {
			return {
				url: null,
				source: "none",
				isEditor: false,
				isRoot: false,
				projectId: null,
				normalized: null,
			};
		}
		return {
			url: value,
			source,
			isEditor: isProjectEditorUrl(value) && !isRootFlowUrl(value),
			isRoot: isRootFlowUrl(value),
			projectId: extractFlowProjectId(value),
			normalized: normalizeFlowProjectUrl(value),
		};
	}

	/**
	 * Decide the authoritative editor URL for a single tab.
	 *
	 * Priority is STRICTLY by trust in the source, not by "which one looks like an
	 * editor": the content script's live `location_href` wins whenever it is
	 * present (even when it reports the root — that is a real backward navigation
	 * we must honour). `chrome.tabs.Tab.url` is used ONLY when the live href is
	 * genuinely unavailable (content script not reachable). A stored project URL
	 * is the last resort and can never override a live signal.
	 *
	 * @param {{tabUrl?: string, liveLocationHref?: string, storedProjectUrl?: string}} input
	 * @returns {{url: string|null, source: string, isEditor: boolean, isRoot: boolean, projectId: string|null, normalized: string|null}}
	 */
	function resolveAuthoritativeEditorUrl(input) {
		const src = input || {};
		const live = String(src.liveLocationHref || "").trim();
		if (live) {
			return describeUrl(live, "live");
		}
		const tab = String(src.tabUrl || "").trim();
		if (tab) {
			return describeUrl(tab, "tab");
		}
		const stored = String(src.storedProjectUrl || "").trim();
		if (stored) {
			return describeUrl(stored, "stored");
		}
		return describeUrl(null, "none");
	}

	/**
	 * Classify a live SPA location change into a reconciliation action.
	 *   - BIND_EDITOR : url is a real project editor  -> (re)bind editor identity
	 *   - CLEAR_EDITOR: url is the Flow root          -> drop any bound state
	 *   - IGNORE      : anything else (non-Flow url)  -> no change
	 *
	 * @param {{url?: string}} input
	 */
	function reconcileFlowLocation(input) {
		const url = String((input && input.url) || "").trim();
		const isEditor = Boolean(url) && isProjectEditorUrl(url) && !isRootFlowUrl(url);
		const isRoot = Boolean(url) && isRootFlowUrl(url);
		let action = "IGNORE";
		if (isEditor) {
			action = "BIND_EDITOR";
		} else if (isRoot) {
			action = "CLEAR_EDITOR";
		}
		return {
			url: url || null,
			isEditor,
			isRoot,
			projectId: isEditor ? extractFlowProjectId(url) : null,
			normalized: isEditor ? normalizeFlowProjectUrl(url) : null,
			action,
		};
	}

	/**
	 * Select the authoritative editor tab out of several live Flow tabs.
	 *
	 * Priority (MULTI-TAB LAW):
	 *   1. the focused/active tab whose LIVE url is a project editor
	 *   2. the stored preferred project, only if a live editor confirms it
	 *   3. any single live-confirmed editor
	 *   4. a root Flow tab, as a non-editor fallback only
	 *
	 * FAIL-CLOSED: when two genuinely DIFFERENT live project editors are eligible
	 * and nothing disambiguates them, this returns `ambiguous:true` and selects
	 * nothing — it never silently picks one.
	 *
	 * @param {Array<{tabId:any, tabUrl?:string, liveLocationHref?:string, focusedActive?:boolean}>} candidates
	 * @param {{storedProjectUrl?: string}} [options]
	 */
	function selectAuthoritativeEditorTab(candidates, options) {
		const opts = options || {};
		const normStored = normalizeFlowProjectUrl(opts.storedProjectUrl || null);
		const list = (Array.isArray(candidates) ? candidates : [])
			.filter(Boolean)
			.map((candidate) => {
				const resolved = resolveAuthoritativeEditorUrl({
					tabUrl: candidate.tabUrl,
					liveLocationHref: candidate.liveLocationHref,
				});
				return {
					tabId: candidate.tabId != null ? candidate.tabId : null,
					focusedActive: Boolean(candidate.focusedActive),
					authoritativeUrl: resolved.url,
					isEditor: resolved.isEditor,
					isRoot: resolved.isRoot,
					projectId: resolved.projectId,
					normalized: resolved.normalized,
					storedPreferred: Boolean(
						normStored && resolved.normalized && resolved.normalized === normStored,
					),
				};
			});

		const editors = list.filter((entry) => entry.isEditor);
		const distinctProjects = (entries) => {
			const seen = new Set();
			for (const entry of entries) {
				if (entry.projectId) {
					seen.add(entry.projectId);
				}
			}
			return seen;
		};
		const win = (entry, reason) => ({
			ok: true,
			ambiguous: false,
			reason,
			tabId: entry.tabId,
			selected: entry,
		});
		const ambiguousOf = (entries) => ({
			ok: false,
			ambiguous: true,
			reason: "AMBIGUOUS_MULTIPLE_LIVE_EDITORS",
			tabId: null,
			selected: null,
			candidates: entries.map((entry) => ({
				tabId: entry.tabId,
				projectId: entry.projectId,
			})),
		});

		// (1) focused active live editor
		const focused = editors.filter((entry) => entry.focusedActive);
		if (focused.length === 1) {
			return win(focused[0], "FOCUSED_ACTIVE_EDITOR");
		}
		if (focused.length > 1) {
			return distinctProjects(focused).size <= 1
				? win(focused[0], "FOCUSED_ACTIVE_EDITOR")
				: ambiguousOf(focused);
		}

		// (2) stored preferred project, live-confirmed
		const preferred = editors.filter((entry) => entry.storedPreferred);
		if (preferred.length >= 1) {
			return distinctProjects(preferred).size <= 1
				? win(preferred[0], "STORED_PREFERRED_EDITOR")
				: ambiguousOf(preferred);
		}

		// (3) any live-confirmed editor — fail closed on genuine ambiguity
		if (editors.length === 1) {
			return win(editors[0], "SINGLE_LIVE_EDITOR");
		}
		if (editors.length > 1) {
			return distinctProjects(editors).size <= 1
				? win(editors[0], "SINGLE_LIVE_EDITOR")
				: ambiguousOf(editors);
		}

		// (4) root-only fallback (non-editor)
		const root = list.find((entry) => entry.isRoot);
		if (root) {
			return {
				ok: false,
				ambiguous: false,
				reason: "ROOT_NON_EDITOR_FALLBACK",
				tabId: root.tabId,
				selected: root,
			};
		}
		return {
			ok: false,
			ambiguous: false,
			reason: "NO_OPEN_EDITOR",
			tabId: null,
			selected: null,
		};
	}

	const api = {
		isProjectEditorUrl,
		isRootFlowUrl,
		normalizeFlowProjectUrl,
		extractFlowProjectId,
		resolveAuthoritativeEditorUrl,
		reconcileFlowLocation,
		selectAuthoritativeEditorTab,
	};

	// Node / CommonJS (unit tests).
	if (typeof module !== "undefined" && module.exports) {
		module.exports = api;
	}
	// Service worker / browser global (importScripts).
	if (globalScope) {
		globalScope.FlowEditorBinding = api;
	}
})(
	typeof self !== "undefined"
		? self
		: typeof globalThis !== "undefined"
			? globalThis
			: this,
);
