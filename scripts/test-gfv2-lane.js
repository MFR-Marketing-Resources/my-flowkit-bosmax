"use strict";

// Unit tests for the GFV2 lane decision logic extracted from extension/background.js:
//   - isGfv2Lane(job)
//   - gfv2ClassifySurface(tab, capture)   (stale c240ebbd / something-went-wrong / editor)
//   - GFV2_STAGE_MAP (SOP -> GFV2 stage mapping)
// Pure logic — no live Flow tab required.

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const assert = (cond, msg) => {
	if (!cond) throw new Error(`ASSERTION_FAILED: ${msg}`);
};

const SRC = fs.readFileSync(
	path.join(__dirname, "..", "extension", "background.js"),
	"utf8",
);

function extractFunctionSource(source, name) {
	const markers = [`function ${name}(`, `async function ${name}(`];
	const start = markers
		.map((m) => source.indexOf(m))
		.filter((i) => i >= 0)
		.sort((a, b) => a - b)[0];
	assert(start >= 0, `missing ${name} in background.js`);
	const firstBrace = source.indexOf("{", source.indexOf("(", start));
	let depth = 0;
	for (let i = firstBrace; i < source.length; i += 1) {
		if (source[i] === "{") depth += 1;
		else if (source[i] === "}") {
			depth -= 1;
			if (depth === 0) return source.slice(start, i + 1);
		}
	}
	throw new Error(`unbalanced braces for ${name}`);
}

function extractConstObject(source, name) {
	const start = source.indexOf(`const ${name} = Object.freeze({`);
	assert(start >= 0, `missing ${name}`);
	const firstBrace = source.indexOf("{", start);
	let depth = 0;
	for (let i = firstBrace; i < source.length; i += 1) {
		if (source[i] === "{") depth += 1;
		else if (source[i] === "}") {
			depth -= 1;
			if (depth === 0) return source.slice(start, source.indexOf(";", i) + 1);
		}
	}
	throw new Error(`unbalanced ${name}`);
}

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(
	[
		extractConstObject(SRC, "GFV2_STAGE_MAP"),
		extractFunctionSource(SRC, "isGfv2Lane"),
		extractFunctionSource(SRC, "gfv2ClassifySurface"),
		"this.__t = { GFV2_STAGE_MAP, isGfv2Lane, gfv2ClassifySurface };",
	].join("\n"),
	sandbox,
);
const { GFV2_STAGE_MAP, isGfv2Lane, gfv2ClassifySurface } = sandbox.__t;

const tests = [];
const test = (n, f) => tests.push([n, f]);

test("isGfv2Lane: lane flag and gfv2 flag activate; others do not", () => {
	assert(isGfv2Lane({ lane: "GFV2_UPLOAD_SETTINGS_PROMPT_GENERATE" }) === true, "lane flag");
	assert(isGfv2Lane({ gfv2: true }) === true, "gfv2 flag");
	assert(isGfv2Lane({ lane: "F2V_PACKAGE_UPLOAD_ONLY" }) === false, "old lane is not GFV2");
	assert(isGfv2Lane({ mode: "F2V" }) === false, "plain F2V not GFV2");
	assert(isGfv2Lane(null) === false, "null not GFV2");
});

test("gfv2ClassifySurface: stale c240ebbd is never a valid surface", () => {
	const r = gfv2ClassifySurface(
		{ url: "https://labs.google/fx/tools/flow/project/c240ebbd-x" },
		{ ok: true, evaluation: { proofs: { editor: { ok: true } } }, diagnostic: {} },
	);
	assert(r.healthy === false && r.reason === "stale_stored_project", "c240ebbd must be rejected even if editor reads ok");
});

test("gfv2ClassifySurface: 'Back to projects' + no editor = something_went_wrong", () => {
	const r = gfv2ClassifySurface(
		{ url: "https://labs.google/fx/tools/flow/project/abc" },
		{
			ok: true,
			evaluation: { proofs: { editor: { ok: false } } },
			diagnostic: { button_texts: ["arrow_backBack to projects"] },
		},
	);
	assert(r.healthy === false && r.reason === "something_went_wrong", "error page must be rejected");
});

test("gfv2ClassifySurface: login blocker rejected", () => {
	const r = gfv2ClassifySurface(
		{ url: "https://labs.google/fx/tools/flow" },
		{ ok: true, evaluation: { proofs: { editor: { ok: false } } }, diagnostic: { login_or_access_blocker: true } },
	);
	assert(r.healthy === false && r.reason === "login_or_access_blocker", "login blocker must be rejected");
});

test("gfv2ClassifySurface: healthy editor surface (no Frames/project required)", () => {
	const r = gfv2ClassifySurface(
		{ url: "https://labs.google/fx/tools/flow" }, // root, NOT /project/
		{
			ok: true,
			evaluation: { proofs: { editor: { ok: true } } },
			diagnostic: { button_texts: ["Upload media", "Settings"] },
		},
	);
	assert(r.healthy === true && r.reason === "ok", "a composer/editor surface must pass without /project/ or Frames");
});

test("gfv2ClassifySurface: editor not ready rejected", () => {
	const r = gfv2ClassifySurface(
		{ url: "https://labs.google/fx/tools/flow" },
		{ ok: true, evaluation: { proofs: { editor: { ok: false } } }, diagnostic: { button_texts: [] } },
	);
	assert(r.healthy === false && r.reason === "no_editor_surface", "no editor surface must be rejected");
});

test("GFV2_STAGE_MAP maps the SOP stages to the V2 contract stages", () => {
	assert(GFV2_STAGE_MAP.F2V_SOP_START_CLICKED === "GFV2_UPLOAD_MEDIA_OPENED", "upload media");
	assert(GFV2_STAGE_MAP.F2V_SOP_UPLOAD_WAIT_DONE === "GFV2_ADD_TO_PROMPT_CLICKED", "add to prompt");
	assert(GFV2_STAGE_MAP.F2V_SOP_PROMPT_INSERTED === "GFV2_PROMPT_INSERTED", "prompt inserted");
	assert(GFV2_STAGE_MAP.F2V_SOP_RATIO_9_16_CONFIRMED === "GFV2_RATIO_9_16_CONFIRMED", "ratio");
	assert(GFV2_STAGE_MAP.F2V_SOP_COUNT_1X_CONFIRMED === "GFV2_COUNT_1X_CONFIRMED", "count");
});

// --- Surface-acquisition source contract (GFV2_ENSURE_SURFACE fix) ---
const ENSURE_SRC = extractFunctionSource(SRC, "gfv2EnsureSurface");
const HANDLE_SRC = extractFunctionSource(SRC, "handleGfv2Job");

test("ENSURE_SURFACE opens a brand-new root tab (not a reused/stale tab)", () => {
	assert(/openTabInNormalWindow\(\s*GFV2_FLOW_ROOT_URL\s*\)/.test(ENSURE_SRC), "must open a fresh tab to Flow root");
	assert(SRC.includes('const GFV2_FLOW_ROOT_URL = "https://labs.google/fx/tools/flow"'), "root URL constant");
});

test("ENSURE_SURFACE does NOT use openPreferredFlowProjectOrNewProject for fallback", () => {
	// the call form `openPreferredFlowProjectOrNewProject(` must be absent (a comment
	// mentioning the name with a space before '(' is allowed).
	assert(!/openPreferredFlowProjectOrNewProject\(/.test(ENSURE_SRC), "must not CALL openPreferredFlowProjectOrNewProject");
	assert(!/settleFlowProjectAfterOpen\(/.test(ENSURE_SRC), "must not reuse settleFlowProjectAfterOpen path that settled on c240ebbd");
});

test("ENSURE_SURFACE never reads/writes the stored project URL", () => {
	assert(!/setStoredFlowProjectUrl\(/.test(ENSURE_SRC), "must not write stored project URL");
	assert(!/getStoredFlowProjectUrl\(/.test(ENSURE_SRC), "must not read stored project URL");
	// c240ebbd appears only in an explanatory comment, never in navigation code:
	const code = ENSURE_SRC.replace(/\/\/[^\n]*/g, "");
	assert(!/c240ebbd/.test(code), "must not reference c240ebbd in executable code");
});

test("ENSURE_SURFACE automates New/Create and emits named blockers", () => {
	assert(/OPEN_FLOW_NEW_PROJECT/.test(ENSURE_SRC), "automates the New/Create click");
	assert(ENSURE_SRC.includes('"GFV2_LOGIN_REQUIRED"'), "named login blocker");
	assert(ENSURE_SRC.includes('"GFV2_CREATE_SESSION_NOT_FOUND"'), "named create-session blocker");
	assert(ENSURE_SRC.includes('"GFV2_ROOT_LOAD_TIMEOUT"'), "named root-load blocker");
	assert(ENSURE_SRC.includes('"GFV2_SURFACE_NOT_READY"'), "named generic surface blocker");
});

test("runner still uses skipGenerate:true and stops before generate", () => {
	assert(/skipGenerate:\s*true/.test(HANDLE_SRC), "skipGenerate must be true");
	assert(HANDLE_SRC.includes('"GFV2_STOP_BEFORE_GENERATE"'), "must emit GFV2_STOP_BEFORE_GENERATE");
	assert(!/"GENERATE_CLICKED"|invokeGenerate/.test(HANDLE_SRC), "must not click generate");
});

// --- Upload-menu contract (ERR_CDP_FILE_CHOOSER_TIMEOUT fix) ---
const RUNNER_SRC = fs.readFileSync(
	path.join(__dirname, "..", "extension", "f2v-flow-queue-runner.js"),
	"utf8",
);

test("upload alias list includes the V2 'Upload from computer' menu item", () => {
	assert(RUNNER_SRC.includes("'Upload from computer'"), "must match the V2 'Upload from computer' label");
	assert(RUNNER_SRC.includes("'Upload from device'"), "keeps legacy 'Upload from device'");
	assert(RUNNER_SRC.includes("'upload Upload media'"), "keeps 'Upload media'");
});

test("launcher click alone is NOT treated as the file chooser opening", () => {
	// The add/create launcher (F2V_SOP_START_CLICKED) and the in-menu item are
	// distinct: _clickUploadMedia must run BEFORE the CDP chooser wait.
	const startIdx = RUNNER_SRC.indexOf("F2V_SOP_START_CLICKED', 'PASS'");
	const clickUploadIdx = RUNNER_SRC.indexOf("await _clickUploadMedia(\n        scripting");
	const waitIdx = RUNNER_SRC.indexOf("cdpFileChooserUpload({ phase: 'wait'");
	assert(startIdx >= 0 && clickUploadIdx >= 0 && waitIdx >= 0, "all three steps present");
	assert(startIdx < clickUploadIdx, "launcher click precedes upload-media click");
	assert(clickUploadIdx < waitIdx, "upload-media click precedes the CDP chooser wait");
});

test("runner emits the GFV2 upload-menu telemetry sequence", () => {
	for (const stage of [
		"GFV2_CDP_FILE_CHOOSER_ARMED",
		"GFV2_UPLOAD_LAUNCHER_CLICKED",
		"GFV2_UPLOAD_MENU_OPENED",
		"GFV2_UPLOAD_MEDIA_ITEM_FOUND",
		"GFV2_UPLOAD_MEDIA_ITEM_CLICKED",
		"GFV2_CDP_FILE_CHOOSER_FED",
	]) {
		assert(RUNNER_SRC.includes(`'${stage}'`), `runner must emit ${stage}`);
	}
});

test("missing upload menu item returns named blocker GFV2_UPLOAD_MEDIA_ITEM_NOT_FOUND", () => {
	assert(RUNNER_SRC.includes("'GFV2_UPLOAD_MEDIA_ITEM_NOT_FOUND'"), "named menu-item blocker emitted");
	assert(/gfv2UploadError\s*=\s*!uploadResult\?\.ok\s*\?\s*'GFV2_UPLOAD_MEDIA_ITEM_NOT_FOUND'/.test(RUNNER_SRC), "returns the named blocker when the item was never found/clicked");
});

test("GFV2 lane wires gfv2Stage into the runner", () => {
	assert(/gfv2Stage:\s*\(stage, status, message\) =>\s*emit\(stage, status, message\)/.test(HANDLE_SRC), "handleGfv2Job passes gfv2Stage to the runner");
	assert(/opts\?\.gfv2Stage\?\.\(/.test(RUNNER_SRC), "runner invokes opts.gfv2Stage (no-op for non-GFV2 callers)");
});

test("V2 'Add Media' nests: runner attempts the nested upload-submenu item", () => {
	assert(RUNNER_SRC.includes("uploadSubmenu: true"), "second pass targets the nested submenu");
	assert(/opts\?\.uploadSubmenu/.test(RUNNER_SRC), "alias list switches for the submenu pass");
	assert(RUNNER_SRC.includes("'Upload from computer'"), "submenu aliases include 'Upload from computer'");
	assert(RUNNER_SRC.includes("'Add Media'"), "first pass aliases include 'Add Media'");
});

test("CDP chooser timeout recovers via direct input[type=file] feed", () => {
	const BG_SRC = fs.readFileSync(path.join(__dirname, "..", "extension", "background.js"), "utf8");
	assert(/async function tryDirectFileInputFeed\(/.test(BG_SRC), "direct-input helper exists");
	assert(BG_SRC.includes('"DOM.querySelectorAll"') && BG_SRC.includes("input[type=file]"), "queries file inputs");
	assert(BG_SRC.includes('"DOM.setFileInputFiles"'), "feeds via DOM.setFileInputFiles");
	// must be invoked from the chooser timeout (additive — does not change the proven
	// fileChooserOpened path).
	const timeoutIdx = BG_SRC.indexOf("run.timeoutId = setTimeout(async");
	assert(timeoutIdx >= 0, "timeout handler is async");
	assert(BG_SRC.indexOf("await tryDirectFileInputFeed(debuggee, filePath)", timeoutIdx) > timeoutIdx, "timeout calls the direct feed before failing");
});

test("broken DOM-message fallback is NOT wired into the GFV2 lane", () => {
	assert(!/domUploadFallback:/.test(HANDLE_SRC), "must not wire the unimplemented FLOWKIT_SIMULATE_FILE_UPLOAD fallback");
});

let failed = 0;
for (const [name, fn] of tests) {
	try {
		fn();
		console.log(`PASS ${name}`);
	} catch (err) {
		failed += 1;
		console.error(`FAIL ${name}\n  ${err.message}`);
	}
}
if (failed > 0) {
	console.error(`\n${failed} failing case(s)`);
	process.exit(1);
}
console.log("\nPASS test-gfv2-lane");
