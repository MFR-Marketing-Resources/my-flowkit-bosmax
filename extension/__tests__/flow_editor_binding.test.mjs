/**
 * Provider-free unit tests for the pure Flow editor-binding decision logic.
 *
 * ZERO provider ops, ZERO credit, ZERO network — these exercise only the pure
 * functions in ../flow-editor-binding.js. Run with:
 *   node --test extension/__tests__/flow_editor_binding.test.mjs
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const binding = require("../flow-editor-binding.js");

const {
	resolveAuthoritativeEditorUrl,
	reconcileFlowLocation,
	selectAuthoritativeEditorTab,
	isProjectEditorUrl,
	isRootFlowUrl,
} = binding;

const ROOT = "https://labs.google/fx/tools/flow";
const PROJECT_A = "https://labs.google/fx/tools/flow/project/aaaa-1111";
const PROJECT_B = "https://labs.google/fx/tools/flow/project/bbbb-2222";

// A. root Tab.url + live location_href=project  =>  authoritative = project (bound true).
test("A: stale root Tab.url with live project href resolves to the project", () => {
	const r = resolveAuthoritativeEditorUrl({
		tabUrl: ROOT,
		liveLocationHref: PROJECT_A,
	});
	assert.equal(r.source, "live");
	assert.equal(r.isEditor, true);
	assert.equal(r.url, PROJECT_A);
	assert.equal(r.projectId, "aaaa-1111");
});

// B. replaceState-style change reflected via live location_href wins.
test("B: replaceState-driven live href wins over stale Tab.url", () => {
	// Tab.url still at project A, but the SPA replaceState'd to project B.
	const r = resolveAuthoritativeEditorUrl({
		tabUrl: PROJECT_A,
		liveLocationHref: PROJECT_B,
	});
	assert.equal(r.source, "live");
	assert.equal(r.url, PROJECT_B);
	assert.equal(r.projectId, "bbbb-2222");
});

// C. live location_href back to root  =>  not-a-project (bound false), even if
//    Tab.url is a stale editor.
test("C: live href back to root is not a project even with stale editor Tab.url", () => {
	const r = resolveAuthoritativeEditorUrl({
		tabUrl: PROJECT_A, // stale
		liveLocationHref: ROOT, // live: user navigated back to root
	});
	assert.equal(r.source, "live");
	assert.equal(r.isEditor, false);
	assert.equal(r.isRoot, true);
	const classified = reconcileFlowLocation({ url: r.url });
	assert.equal(classified.action, "CLEAR_EDITOR");
});

// D. stale Tab.url=root + content location_href=project  =>  LIVE wins.
test("D: content live href beats stale root Tab.url", () => {
	const r = resolveAuthoritativeEditorUrl({
		tabUrl: ROOT,
		liveLocationHref: PROJECT_A,
		storedProjectUrl: null,
	});
	assert.equal(r.isEditor, true);
	assert.equal(r.source, "live");
});

// E. stale stored flow_project_url cannot override a focused live project editor.
test("E: stored project URL cannot override a live editor", () => {
	const r = resolveAuthoritativeEditorUrl({
		tabUrl: ROOT,
		liveLocationHref: PROJECT_B, // focused live editor
		storedProjectUrl: PROJECT_A, // stale stored preference
	});
	assert.equal(r.url, PROJECT_B);
	assert.equal(r.source, "live");

	// And in multi-tab selection, focus wins over the stored preference.
	const selection = selectAuthoritativeEditorTab(
		[
			{ tabId: 1, tabUrl: ROOT, liveLocationHref: PROJECT_B, focusedActive: true },
			{ tabId: 2, tabUrl: PROJECT_A, liveLocationHref: PROJECT_A, focusedActive: false },
		],
		{ storedProjectUrl: PROJECT_A },
	);
	assert.equal(selection.ok, true);
	assert.equal(selection.ambiguous, false);
	assert.equal(selection.tabId, 1);
	assert.equal(selection.reason, "FOCUSED_ACTIVE_EDITOR");
});

// F. multiple tabs  =>  focused live editor wins safely.
test("F: focused live editor wins among multiple tabs", () => {
	const selection = selectAuthoritativeEditorTab([
		{ tabId: 10, tabUrl: ROOT, liveLocationHref: ROOT, focusedActive: false },
		{ tabId: 11, tabUrl: ROOT, liveLocationHref: PROJECT_A, focusedActive: true },
		{ tabId: 12, tabUrl: PROJECT_B, liveLocationHref: PROJECT_B, focusedActive: false },
	]);
	assert.equal(selection.ok, true);
	assert.equal(selection.ambiguous, false);
	assert.equal(selection.tabId, 11);
	assert.equal(selection.reason, "FOCUSED_ACTIVE_EDITOR");
});

// G. genuinely ambiguous DIFFERENT live projects  =>  fail-closed (no silent pick).
test("G: two different live editors with no disambiguator fail closed", () => {
	const selection = selectAuthoritativeEditorTab([
		{ tabId: 20, tabUrl: PROJECT_A, liveLocationHref: PROJECT_A, focusedActive: false },
		{ tabId: 21, tabUrl: PROJECT_B, liveLocationHref: PROJECT_B, focusedActive: false },
	]);
	assert.equal(selection.ok, false);
	assert.equal(selection.ambiguous, true);
	assert.equal(selection.selected, null);
	assert.equal(selection.reason, "AMBIGUOUS_MULTIPLE_LIVE_EDITORS");
});

// G2. same project across two tabs is NOT ambiguous (safe to pick).
test("G2: same live project across two tabs is not ambiguous", () => {
	const selection = selectAuthoritativeEditorTab([
		{ tabId: 30, tabUrl: PROJECT_A, liveLocationHref: PROJECT_A, focusedActive: false },
		{ tabId: 31, tabUrl: ROOT, liveLocationHref: PROJECT_A, focusedActive: false },
	]);
	assert.equal(selection.ok, true);
	assert.equal(selection.ambiguous, false);
	assert.equal(selection.reason, "SINGLE_LIVE_EDITOR");
});

// H. reconnect rediscovery: given an already-open live editor, reconciliation
//    yields the editor identity (pure reconcile fn).
test("H: reconnect reconcile of an open editor yields editor identity", () => {
	const classified = reconcileFlowLocation({ url: PROJECT_A });
	assert.equal(classified.action, "BIND_EDITOR");
	assert.equal(classified.isEditor, true);
	assert.equal(classified.projectId, "aaaa-1111");
	assert.equal(classified.normalized, PROJECT_A);
});

// I. no project editor anywhere  =>  NO_OPEN_EDITOR preserved.
test("I: no editor tabs anywhere preserves NO_OPEN_EDITOR", () => {
	const selection = selectAuthoritativeEditorTab([]);
	assert.equal(selection.ok, false);
	assert.equal(selection.ambiguous, false);
	assert.equal(selection.reason, "NO_OPEN_EDITOR");

	// A lone root tab is a non-editor fallback, still not a bound editor.
	const rootOnly = selectAuthoritativeEditorTab([
		{ tabId: 40, tabUrl: ROOT, liveLocationHref: ROOT, focusedActive: true },
	]);
	assert.equal(rootOnly.ok, false);
	assert.equal(rootOnly.reason, "ROOT_NON_EDITOR_FALLBACK");

	const r = resolveAuthoritativeEditorUrl({ tabUrl: ROOT, liveLocationHref: ROOT });
	assert.equal(r.isEditor, false);
});

// I2. content genuinely unavailable => fall back to Tab.url.
test("I2: falls back to Tab.url only when live href is absent", () => {
	const r = resolveAuthoritativeEditorUrl({
		tabUrl: PROJECT_A,
		liveLocationHref: null,
	});
	assert.equal(r.source, "tab");
	assert.equal(r.isEditor, true);
	assert.equal(r.url, PROJECT_A);
});

// J. the logic performs ZERO network/provider/credit operations (pure functions).
test("J: pure — no network/provider/credit side effects", () => {
	const originalFetch = globalThis.fetch;
	const originalChrome = globalThis.chrome;
	const originalXHR = globalThis.XMLHttpRequest;
	let touched = false;
	const tripwire = () => {
		touched = true;
		throw new Error("SIDE_EFFECT_ATTEMPTED");
	};
	// Any attempt to reach the network / extension API must throw AND be recorded.
	globalThis.fetch = tripwire;
	globalThis.XMLHttpRequest = function () {
		tripwire();
	};
	globalThis.chrome = new Proxy(
		{},
		{
			get() {
				return tripwire();
			},
		},
	);
	try {
		resolveAuthoritativeEditorUrl({ tabUrl: ROOT, liveLocationHref: PROJECT_A });
		reconcileFlowLocation({ url: PROJECT_A });
		reconcileFlowLocation({ url: ROOT });
		selectAuthoritativeEditorTab([
			{ tabId: 1, tabUrl: ROOT, liveLocationHref: PROJECT_A, focusedActive: true },
			{ tabId: 2, tabUrl: PROJECT_B, liveLocationHref: PROJECT_B, focusedActive: false },
		]);
		isProjectEditorUrl(PROJECT_A);
		isRootFlowUrl(ROOT);
	} finally {
		globalThis.fetch = originalFetch;
		globalThis.chrome = originalChrome;
		globalThis.XMLHttpRequest = originalXHR;
	}
	assert.equal(touched, false, "pure functions must not touch fetch/chrome/XHR");
});
