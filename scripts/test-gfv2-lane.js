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
const CONTENT_SRC = fs.readFileSync(
	path.join(__dirname, "..", "extension", "content-flow-dom.js"),
	"utf8",
);
const BACKGROUND_BUILD_ID = SRC.match(
	/const BUILD_ID = ["']([^"']+)["']/,
)?.[1];
assert(BACKGROUND_BUILD_ID, "missing BUILD_ID in background.js");

function extractFunctionSource(source, name) {
	const markers = [`function ${name}(`, `async function ${name}(`];
	const start = markers
		.map((m) => source.indexOf(m))
		.filter((i) => i >= 0)
		.sort((a, b) => a - b)[0];
	assert(start >= 0, `missing ${name} in background.js`);
	const firstParen = source.indexOf("(", start);
	let parenDepth = 0;
	let closingParen = -1;
	for (let i = firstParen; i < source.length; i += 1) {
		if (source[i] === "(") parenDepth += 1;
		else if (source[i] === ")") {
			parenDepth -= 1;
			if (parenDepth === 0) {
				closingParen = i;
				break;
			}
		}
	}
	assert(closingParen >= 0, `unbalanced parameters for ${name}`);
	const firstBrace = source.indexOf("{", closingParen);
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
		`const BUILD_ID = ${JSON.stringify(BACKGROUND_BUILD_ID)};`,
		extractConstObject(SRC, "GFV2_STAGE_MAP"),
		extractFunctionSource(SRC, "buildStageTelemetryPayload"),
		extractFunctionSource(SRC, "isProjectEditorUrl"),
		extractFunctionSource(SRC, "isRootFlowUrl"),
		extractFunctionSource(SRC, "isGfv2Lane"),
		extractFunctionSource(SRC, "isGfv2PostSubmitOutputOnly"),
		extractFunctionSource(SRC, "gfv2ClassifySurface"),
		extractFunctionSource(SRC, "gfv2DecideBuildProof"),
		extractFunctionSource(SRC, "gfv2DecideSettingsProof"),
		extractFunctionSource(SRC, "gfv2ClassifyAssetSource"),
		"this.__t = { GFV2_STAGE_MAP, buildStageTelemetryPayload, isGfv2Lane, isGfv2PostSubmitOutputOnly, gfv2ClassifySurface, gfv2DecideBuildProof, gfv2DecideSettingsProof, gfv2ClassifyAssetSource };",
	].join("\n"),
	sandbox,
);
const { GFV2_STAGE_MAP, buildStageTelemetryPayload, isGfv2Lane, isGfv2PostSubmitOutputOnly, gfv2ClassifySurface, gfv2DecideBuildProof, gfv2DecideSettingsProof, gfv2ClassifyAssetSource } = sandbox.__t;

// Helpers for the settings-proof decision tests.
const stagesOf = (r) => r.emissions.map((e) => `${e.stage}:${e.status}`);
const FULL_OK_PROOF = {
	settings_panel_opened: true,
	ratio_9_16_confirmed: true,
	count_1x_confirmed: true,
	model_visible_wrong: false,
	model_veo_lite_confirmed: true,
	model_state: "correct",
	save_button_found: false,
};

const tests = [];
const test = (n, f) => tests.push([n, f]);

test("isGfv2Lane: lane flag and gfv2 flag activate; others do not", () => {
	assert(isGfv2Lane({ lane: "GFV2_UPLOAD_SETTINGS_PROMPT_GENERATE" }) === true, "lane flag");
	assert(isGfv2Lane({ lane: "GFV2_POST_SUBMIT_DOWNLOAD" }) === true, "post-submit lane flag");
	assert(isGfv2Lane({ lane: "GFV2_POST_SUBMIT_OUTPUT_ONLY" }) === true, "output-only lane flag");
	assert(isGfv2Lane({ gfv2: true }) === true, "gfv2 flag");
	assert(isGfv2Lane({ postSubmitDownload: true }) === true, "postSubmitDownload flag");
	assert(isGfv2Lane({ postSubmitOutputOnly: true }) === true, "postSubmitOutputOnly flag");
	assert(isGfv2Lane({ lane: "F2V_PACKAGE_UPLOAD_ONLY" }) === false, "old lane is not GFV2");
	assert(isGfv2Lane({ mode: "F2V" }) === false, "plain F2V not GFV2");
	assert(isGfv2Lane(null) === false, "null not GFV2");
});

test("isGfv2PostSubmitOutputOnly activates only for the reduced MVP lane flags", () => {
	assert(isGfv2PostSubmitOutputOnly({ lane: "GFV2_POST_SUBMIT_OUTPUT_ONLY" }) === true, "lane flag");
	assert(isGfv2PostSubmitOutputOnly({ postSubmitOutputOnly: true }) === true, "explicit output-only flag");
	assert(isGfv2PostSubmitOutputOnly({ stopAfterOutputDetected: true }) === true, "terminal stop flag");
	assert(isGfv2PostSubmitOutputOnly({ lane: "GFV2_POST_SUBMIT_DOWNLOAD" }) === false, "download lane is not output-only");
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

test("gfv2ClassifySurface: root landing nav only is rejected", () => {
	const r = gfv2ClassifySurface(
		{ url: "https://labs.google/fx/tools/flow" },
		{
			ok: true,
			evaluation: { proofs: { editor: { ok: false } } },
			diagnostic: {
				root_flow_url: true,
				landing_nav_only: true,
				button_texts: [
					"Flow TV",
					"Help Center",
					"Learn More",
					"Go to banner 1",
					"New project",
				],
			},
		},
	);
	assert(r.healthy === false && r.reason === "landing_nav_only", "landing-only root must be rejected");
});

test("gfv2ClassifySurface: strict composer proof may pass on root after editor entry", () => {
	const r = gfv2ClassifySurface(
		{ url: "https://labs.google/fx/tools/flow" },
		{
			ok: true,
			evaluation: { proofs: { editor: { ok: true } } },
			diagnostic: {
				root_flow_url: true,
				landing_nav_only: false,
				composer_found: true,
				composer_editable: true,
				generate_button_found: true,
				bottom_composer_config_pill_visible: true,
				current_mode_visible: "Video/Frames",
				button_texts: ["Upload media", "Settings"],
			},
		},
	);
	assert(r.healthy === true && r.reason === "ok", "strict composer/editor proof must pass");
});

test("gfv2ClassifySurface: editor not ready rejected", () => {
	const r = gfv2ClassifySurface(
		{ url: "https://labs.google/fx/tools/flow" },
		{ ok: true, evaluation: { proofs: { editor: { ok: false } } }, diagnostic: { button_texts: [] } },
	);
	assert(r.healthy === false && r.reason === "no_editor_surface", "no editor surface must be rejected");
});

test("GFV2_STAGE_MAP maps upload/prompt SOP stages (settings owned by the hook)", () => {
	assert(GFV2_STAGE_MAP.F2V_SOP_START_CLICKED === "GFV2_UPLOAD_MEDIA_OPENED", "upload media");
	assert(GFV2_STAGE_MAP.F2V_SOP_UPLOAD_WAIT_DONE === "GFV2_ADD_TO_PROMPT_CLICKED", "add to prompt");
	assert(GFV2_STAGE_MAP.F2V_SOP_PROMPT_INSERTED === "GFV2_PROMPT_INSERTED", "prompt inserted");
	// Settings stages must NOT be in the map — they come from gfv2VerifySettings so the
	// proof is DOM-confirmed (not silently mapped from the authority shortcut).
	assert(GFV2_STAGE_MAP.F2V_SOP_RATIO_9_16_CONFIRMED === undefined, "ratio not auto-mapped");
	assert(GFV2_STAGE_MAP.F2V_SOP_COUNT_1X_CONFIRMED === undefined, "count not auto-mapped");
	assert(GFV2_STAGE_MAP.F2V_SOP_SETTINGS_CONFIGURED === undefined, "persisted not auto-mapped");
});

test("GFV2 build proof fails closed when background, runner, and content IDs mismatch", () => {
	const result = gfv2DecideBuildProof({
		background_build_id: "build-current",
		runner_build_id: "build-current",
		page_diagnostic: {
			content_build_id: "build-stale",
			content_script_loaded: true,
			content_script_alive: true,
			runtime_ready: true,
			build_match: false,
		},
	});
	assert(result.proceed === false, "mismatched content executor must not proceed");
	assert(result.error === "GFV2_BUILD_MISMATCH", "mismatch must use the named fail-closed code");
});

test("GFV2 build proof fails closed when real page/content proof is unavailable", () => {
	const result = gfv2DecideBuildProof({
		background_build_id: "build-current",
		runner_build_id: "build-current",
		page_diagnostic: null,
	});
	assert(result.proceed === false, "missing page proof must not proceed");
	assert(result.error === "GFV2_CONTENT_BUILD_UNAVAILABLE", "missing proof must use the named unavailable code");
});

test("GFV2 build proof passes only with matching IDs and live page/content proof", () => {
	const result = gfv2DecideBuildProof({
		background_build_id: "build-current",
		runner_build_id: "build-current",
		page_diagnostic: {
			content_build_id: "build-current",
			content_script_loaded: true,
			content_script_alive: true,
			runtime_ready: true,
			build_match: true,
		},
	});
	assert(result.proceed === true, "matching live proof must proceed");
	assert(result.build_match === true, "three-party match must be explicit");
});

test("background-only telemetry cannot claim content build alignment", () => {
	const payload = buildStageTelemetryPayload({
		request_id: "req-build-proof",
		stage: "GFV2_LANE_ACCEPTED",
		status: "WAITING_FLOW",
		build_match: true,
	});
	assert(
		payload.content_build_id === "CONTENT_BUILD_UNAVAILABLE",
		"missing content proof must be explicit",
	);
	assert(payload.build_match === false, "background-only build_match must be false");
});

test("telemetry reports build_match only from live matching content health", () => {
	const payload = buildStageTelemetryPayload(
		{
			request_id: "req-build-proof",
			stage: "GFV2_BUILD_ALIGNMENT_VERIFIED",
			status: "PASS",
		},
		{
			content_build_id: BACKGROUND_BUILD_ID,
			runtime_ready: true,
		},
	);
	assert(payload.content_build_id === BACKGROUND_BUILD_ID, "real content ID retained");
	assert(payload.build_match === true, "matching live content health may pass");
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
	assert(ENSURE_SRC.includes('"GFV2_EDITOR_ENTRY_FAILED"'), "named editor-entry blocker");
	assert(ENSURE_SRC.includes('"GFV2_EDITOR_NOT_READY_LANDING_NAV_ONLY"'), "named landing-only blocker");
	assert(ENSURE_SRC.includes('"GFV2_ROOT_LOAD_TIMEOUT"'), "named root-load blocker");
});

test("OPEN_FLOW_NEW_PROJECT listener uses a dedicated long async timeout budget", () => {
	assert(
		CONTENT_SRC.includes(
			"const OPEN_FLOW_NEW_PROJECT_RESPOND_ASYNC_TIMEOUT_MS = 60000;",
		),
		"new-project listener must declare a long timeout budget",
	);
	assert(
		/if \(msg\.type === 'OPEN_FLOW_NEW_PROJECT'\) \{[\s\S]*OPEN_FLOW_NEW_PROJECT_RESPOND_ASYNC_TIMEOUT_MS[\s\S]*\}/.test(
			CONTENT_SRC,
		),
		"new-project listener must use the dedicated timeout budget",
	);
});

test("runner still uses skipGenerate:true and stops before generate", () => {
	assert(/skipGenerate:\s*true/.test(HANDLE_SRC), "skipGenerate must be true");
	assert(HANDLE_SRC.includes('"GFV2_STOP_BEFORE_GENERATE"'), "must emit GFV2_STOP_BEFORE_GENERATE");
	assert(HANDLE_SRC.includes("executeGfv2PostSubmitDownloadContinuation"), "opt-in continuation is wired separately");
});

test("post-submit lane is gated behind settings success and does not replace the default STOP lane", () => {
	const settingsFailIdx = HANDLE_SRC.indexOf('if (!settings.proceed)');
	const promptAcceptedIdx = HANDLE_SRC.indexOf('GFV2_PROMPT_ACCEPTED", "PASS"');
	const continuationIdx = HANDLE_SRC.indexOf("executeGfv2PostSubmitDownloadContinuation");
	const stopIdx = HANDLE_SRC.indexOf('GFV2_STOP_BEFORE_GENERATE", "PASS"');
	assert(settingsFailIdx >= 0 && promptAcceptedIdx >= 0 && continuationIdx >= 0 && stopIdx >= 0, "all control points present");
	assert(settingsFailIdx < continuationIdx, "continuation only runs after settings gate");
	assert(promptAcceptedIdx < continuationIdx, "continuation only runs after prompt accepted proof");
	assert(/requiresPostSubmitContinuation\s*=\s*postSubmitDownload\s*\|\|\s*postSubmitOutputOnly/.test(HANDLE_SRC), "continuation is opt-in only");
	assert(/if \(requiresPostSubmitContinuation\)/.test(HANDLE_SRC), "continuation is gated behind the combined post-submit modes");
	assert(/requireSaveTransition:\s*requiresPostSubmitContinuation/.test(HANDLE_SRC), "post-submit requires verified Save transition");
	assert(/stopAfterOutputDetected:\s*postSubmitOutputOnly/.test(HANDLE_SRC), "output-only must pass the terminal stop flag into continuation");
	assert(continuationIdx < stopIdx, "default STOP lane remains in the non-post-submit branch");
});

test("post-submit settings require verified Save exit before continuation", () => {
	assert(
		/gfv2DriveSettingsVerify\(\s*flowTab,\s*emit,\s*\{[\s\S]*requireSaveTransition:\s*requiresPostSubmitContinuation[\s\S]*expectedPrompt:\s*job\?\.prompt/.test(
			HANDLE_SRC,
		),
		"post-submit must require Save transition and accepted prompt reflection",
	);
	assert(
		SRC.includes('"GFV2_SETTINGS_SAVE_VERIFIED"'),
		"verified Save transition stage is required",
	);
	assert(
		!/emit\(\s*saveButtonFound \? "GFV2_SETTINGS_SAVE_CLICKED"[\s\S]*"PASS"/.test(
			HANDLE_SRC,
		),
		"Save click attempt must not be emitted as PASS",
	);
});

// --- Upload-menu contract (ERR_CDP_FILE_CHOOSER_TIMEOUT fix) ---
const RUNNER_SRC = fs.readFileSync(
	path.join(__dirname, "..", "extension", "f2v-flow-queue-runner.js"),
	"utf8",
);
const MANIFEST = JSON.parse(
	fs.readFileSync(
		path.join(__dirname, "..", "extension", "manifest.json"),
		"utf8",
	),
);

test("post-submit download proof is wired to chrome.downloads", () => {
	assert(
		MANIFEST.permissions.includes("downloads"),
		"manifest downloads permission is required",
	);
	assert(
		HANDLE_SRC.includes("createChromeDownloadsAdapter"),
		"background must pass the chrome.downloads adapter to the runner",
	);
	assert(
		RUNNER_SRC.includes("GFV2_DOWNLOAD_NOT_CONFIRMED"),
		"missing completed-download evidence must fail closed",
	);
});

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

// --- Granular GFV2 settings proof (audit contract) ---
test("settings: full valid proof emits all granular stages and proceeds", () => {
	const r = gfv2DecideSettingsProof(FULL_OK_PROOF, "veo 3.1 - lite");
	assert(r.proceed === true, "proceeds");
	const s = stagesOf(r);
	for (const stage of ["GFV2_SETTINGS_OPENED", "GFV2_RATIO_9_16_CONFIRMED", "GFV2_COUNT_1X_CONFIRMED", "GFV2_MODEL_VEO_LITE_CONFIRMED", "GFV2_SETTINGS_SAVED_OR_PERSISTED"]) {
		assert(s.includes(`${stage}:PASS`), `${stage} emitted PASS`);
	}
});

test("settings: GFV2_SETTINGS_OPENED only when panel open OR pill (ratio+count) readable", () => {
	const noSurface = gfv2DecideSettingsProof({ settings_panel_opened: false, ratio_9_16_confirmed: false, count_1x_confirmed: false }, null);
	assert(noSurface.proceed === false && noSurface.error === "GFV2_SETTINGS_PANEL_NOT_FOUND", "no surface -> panel not found");
	assert(stagesOf(noSurface).includes("GFV2_SETTINGS_PANEL_NOT_FOUND:FAIL"), "blocker emitted");
	// pill-confirmed (ratio+count) counts as opened even without a panel signal
	const pill = gfv2DecideSettingsProof({ settings_panel_opened: false, ratio_9_16_confirmed: true, count_1x_confirmed: true, model_veo_lite_confirmed: true }, null);
	assert(stagesOf(pill)[0] === "GFV2_SETTINGS_OPENED:PASS", "pill-confirmed opens settings");
});

test("settings: 9:16 confirmation is required", () => {
	const r = gfv2DecideSettingsProof({ ...FULL_OK_PROOF, ratio_9_16_confirmed: false, count_1x_confirmed: false, settings_panel_opened: true }, null);
	assert(r.proceed === false && r.error === "GFV2_RATIO_9_16_NOT_CONFIRMED", "ratio required");
});

test("settings: 1x confirmation is required", () => {
	const r = gfv2DecideSettingsProof({ ...FULL_OK_PROOF, count_1x_confirmed: false }, null);
	assert(r.proceed === false && r.error === "GFV2_COUNT_1X_NOT_CONFIRMED", "count required");
});

test("settings: visible WRONG model hard-fails (never soft-passed)", () => {
	const r = gfv2DecideSettingsProof({ ...FULL_OK_PROOF, model_visible_wrong: true, model_veo_lite_confirmed: false, model_state: "wrong", model_canonical: "nano banana" }, "nano banana");
	assert(r.proceed === false && r.error === "GFV2_VISIBLE_WRONG_MODEL", "wrong model hard fail");
	assert(!stagesOf(r).some((x) => x.startsWith("GFV2_MODEL_HIDDEN_SOFT_PASS")), "must NOT soft-pass a visible wrong model");
});

test("settings: hidden/UNKNOWN model soft-passes ONLY with 9:16+1x and no wrong model", () => {
	const hidden = gfv2DecideSettingsProof({ settings_panel_opened: true, ratio_9_16_confirmed: true, count_1x_confirmed: true, model_visible_wrong: false, model_veo_lite_confirmed: false, model_state: "unknown" }, null);
	assert(hidden.proceed === true, "hidden soft-pass proceeds");
	assert(stagesOf(hidden).includes("GFV2_MODEL_HIDDEN_SOFT_PASS:PASS"), "hidden soft-pass emitted");
	// without ratio/count it never reaches the model step (fails earlier) — soft-pass not reachable on weak proof
	const weak = gfv2DecideSettingsProof({ settings_panel_opened: true, ratio_9_16_confirmed: false, count_1x_confirmed: false, model_state: "unknown" }, null);
	assert(!stagesOf(weak).some((x) => x.startsWith("GFV2_MODEL_HIDDEN_SOFT_PASS")), "no soft-pass without ratio/count");
});

test("settings: persisted is the last gate before the lane proceeds to upload/prompt", () => {
	const r = gfv2DecideSettingsProof(FULL_OK_PROOF, null);
	const s = stagesOf(r);
	assert(s[s.length - 1] === "GFV2_SETTINGS_SAVED_OR_PERSISTED:PASS", "persisted is last + proceed");
	assert(r.proceed === true, "only then proceeds");
});

test("GFV2 settings proof runs POST-upload (V2 SOP) and is a real hard gate", () => {
	// V2 renders generation settings only after media is in the composer, so the proof
	// runs after GFV2_ASSET_BOUND_TO_PROMPT and gates STOP.
	const boundIdx = HANDLE_SRC.indexOf('GFV2_ASSET_BOUND_TO_PROMPT", "PASS"');
	const driveIdx = HANDLE_SRC.indexOf("await gfv2DriveSettingsVerify(flowTab, emit,");
	const stopIdx = HANDLE_SRC.indexOf('GFV2_STOP_BEFORE_GENERATE", "PASS"');
	assert(boundIdx >= 0 && driveIdx >= 0 && stopIdx >= 0, "all three present");
	assert(boundIdx < driveIdx, "settings proof runs AFTER asset bound to prompt");
	assert(driveIdx < stopIdx, "settings proof gates BEFORE stop-before-generate");
	assert(/if \(!settings\.proceed\)/.test(HANDLE_SRC), "settings is a hard gate (blocks STOP on failure)");
	// must NOT force the V2-incompatible legacy DOM settings path
	assert(!/gfv2ForceDomSettings:\s*true/.test(HANDLE_SRC), "lane must NOT force the broken DOM settings path");
});

test("post-upload settings driver is a real gate (no report-only bypass)", () => {
	const DRIVE_SRC = extractFunctionSource(SRC, "gfv2DriveSettingsVerify");
	assert(/if \(!decision\.proceed\)/.test(DRIVE_SRC), "any blocker fails");
	assert(/return \{ proceed: false, error: err/.test(DRIVE_SRC), "returns the named blocker, not proceed:true");
	assert(!/GFV2_SETTINGS_PROOF_UNVERIFIED/.test(DRIVE_SRC), "no report-only bypass post-upload");
	assert(/requireVisibleVeo: true/.test(DRIVE_SRC), "video lane requires Veo (no hidden soft-pass)");
});

// --- GFV2 asset source: must be the system job asset, never a Desktop/manual pick ---
test("asset: workspace package Start (remote URL) resolves as system asset", () => {
	const r = gfv2ClassifyAssetSource({ workspace_execution_package_id: "wep_x", startAsset: { fileName: "start.jpg", downloadUrl: "https://s.500fd.com/tt_product/abc123~tplv.jpeg" } });
	assert(r.ok && r.source_type === "workspace_package_start", "workspace package start");
	assert(r.safe_name && !/[\\/]/.test(r.safe_name), "safe_name is a basename, no path");
});

test("asset: ref_flowkit-only fails closed as unwired", () => {
	const r = gfv2ClassifyAssetSource({ ref_flowkit: "ref_flowkit_start.png" });
	assert(r.ok === false && r.error === "GFV2_ASSET_SOURCE_UNWIRED", "ref_flowkit must not false-pass");
});

test("asset: image_ref-only fails closed as unwired", () => {
	const r = gfv2ClassifyAssetSource({ image_ref: "image_ref_start.png" });
	assert(r.ok === false && r.error === "GFV2_ASSET_SOURCE_UNWIRED", "image_ref must not false-pass");
});

test("asset: backend-materialized staging temp file resolves as materialized_temp_file", () => {
	const r = gfv2ClassifyAssetSource({ startAsset: { localFilePath: "C:/Users/USER/AppData/Local/Temp/flowkit-upload-staging/77aea8.jpg" } });
	assert(r.ok && r.source_type === "materialized_temp_file" && r.materialized === true, "materialized temp");
	assert(r.safe_name === "77aea8.jpg", "safe basename/hash only (no private dir)");
});

test("asset: existing Flow media id resolves as existing_flow_media", () => {
	const r = gfv2ClassifyAssetSource({ startAsset: { mediaId: "media_abc", fileName: "x.png" } });
	assert(r.ok && r.source_type === "existing_flow_media", "existing flow media");
});

test("asset: NO system asset fails closed with GFV2_ASSET_SOURCE_NOT_FOUND", () => {
	assert(gfv2ClassifyAssetSource({}).error === "GFV2_ASSET_SOURCE_NOT_FOUND", "empty job");
	assert(gfv2ClassifyAssetSource(null).error === "GFV2_ASSET_SOURCE_NOT_FOUND", "null job");
});

test("asset: untrusted Desktop/local path (not in staging) fails closed — no Desktop pick", () => {
	const desktop = gfv2ClassifyAssetSource({ startAsset: { localFilePath: "C:/Users/USER/Desktop/screenshot.png" } });
	assert(desktop.ok === false && desktop.error === "GFV2_ASSET_SOURCE_NOT_FOUND", "Desktop path rejected");
	const dl = gfv2ClassifyAssetSource({ startAsset: "C:/Users/USER/Downloads/pic.png" });
	assert(dl.ok === false, "Downloads string path rejected");
});

test("asset: lane fails closed on missing source (no Desktop picker) + emits source telemetry", () => {
	assert(/GFV2_ASSET_SOURCE_NOT_FOUND/.test(HANDLE_SRC), "fail-closed stage");
	assert(/GFV2_ASSET_SOURCE_UNWIRED/.test(HANDLE_SRC), "unwired-source blocker");
	assert(/GFV2_ASSET_SOURCE_RESOLVED/.test(HANDLE_SRC), "resolved stage");
	assert(/GFV2_ASSET_MATERIALIZED/.test(RUNNER_SRC), "materialized stage is emitted from the real CDP arm path");
	assert(/GFV2_ASSET_UPLOADED_OR_SELECTED/.test(HANDLE_SRC), "uploaded/selected stage");
	// no Desktop/Downloads/hard-coded path anywhere in the lane's executable code
	// (comments may explain the rule; strip them before asserting).
	const code = HANDLE_SRC.replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
	assert(
		!/(?:[A-Z]:[\\/]|\/Users\/|[\\/]Desktop[\\/]|[\\/]Downloads[\\/])/i.test(
			code,
		),
		"no Desktop/Downloads path dependency in lane code",
	);
	assert(!/assetSrc\.source_type === "workspace_package_start"|assetSrc\.source_type === "ref_flowkit"/.test(code), "materialized telemetry must not be pre-emitted before real staging");
});

// --- V2 settings read/interaction primitive (content-flow-dom.js) ---
const CFD_SRC = fs.readFileSync(
	path.join(__dirname, "..", "extension", "content-flow-dom.js"),
	"utf8",
);
const SRC_BLOCK = extractFunctionSource;

test("background, runner, and content executor source build IDs are aligned", () => {
	const backgroundBuild = SRC.match(/const BUILD_ID = ["']([^"']+)["']/)?.[1];
	const runnerBuild = RUNNER_SRC.match(
		/const F2V_FLOW_QUEUE_RUNNER_BUILD_ID = ["']([^"']+)["']/,
	)?.[1];
	const contentBuild = CFD_SRC.match(
		/const FLOW_KIT_DOM_BUILD_ID = ["']([^"']+)["']/,
	)?.[1];
	assert(backgroundBuild, "background build ID missing");
	assert(runnerBuild, "runner build ID missing");
	assert(contentBuild, "content executor build ID missing");
	assert(backgroundBuild === runnerBuild, "background and runner build IDs differ");
	assert(backgroundBuild === contentBuild, "background and content build IDs differ");
});

test("GFV2 build gate runs before the visible SOP runner", () => {
	const gateIdx = HANDLE_SRC.indexOf("gfv2VerifyRuntimeBuildAlignment");
	const runnerIdx = HANDLE_SRC.indexOf(
		"await runnerApi.executeF2VVisibleSopRunner",
	);
	assert(gateIdx >= 0, "GFV2 runtime build gate is missing");
	assert(runnerIdx >= 0, "visible SOP runner call is missing");
	assert(gateIdx < runnerIdx, "build gate must run before runner execution");
});

test("content: V2 settings primitives exist (open/read/apply, discovery)", () => {
	assert(/async function gfv2ApplySettings\(/.test(CFD_SRC), "gfv2ApplySettings present");
	assert(/async function gfv2DiscoverSettings\(/.test(CFD_SRC), "gfv2DiscoverSettings present");
	assert(/function _gfv2FindSettingsLauncher\(/.test(CFD_SRC), "launcher finder present");
	assert(/'GFV2_APPLY_SETTINGS'/.test(CFD_SRC), "GFV2_APPLY_SETTINGS message handled");
});

test("content: settings launcher prefers tune (generation), not Video/Frames/Ingredients", () => {
	const lf = SRC_BLOCK(CFD_SRC, "_gfv2FindSettingsLauncher");
	assert(/tune/.test(lf), "tune scored");
	// must NOT key off legacy mode controls
	assert(!/\bvideo\b/i.test(lf), "no Video control dependency");
	assert(!/\bframes\b/i.test(lf), "no Frames control dependency");
	assert(!/\bingredients\b/i.test(lf), "no Ingredients control dependency");
});

test("content: settings primitive is SECTION-SCOPED to Video generation default", () => {
	const ap = SRC_BLOCK(CFD_SRC, "gfv2ApplySettings");
	assert(/_gfv2VideoBand\(\)/.test(ap), "builds the Video generation default band");
	assert(/_gfv2FindOptionInBand/.test(ap), "selects 9:16/1x scoped to the video band");
	assert(/_gfv2FindModelTriggerInBand/.test(ap), "video model trigger scoped to the band");
	assert(/video_generation_default_section_not_found/.test(ap), "fails if the video section is absent");
	const band = SRC_BLOCK(CFD_SRC, "_gfv2VideoBand");
	assert(/video generation default/.test(band), "band keyed off the 'Video generation default' label");
});

test("content: video model — Veo Lite target; Omni Flash wrong; Nano Banana NOT in video classification", () => {
	const ap = SRC_BLOCK(CFD_SRC, "gfv2ApplySettings");
	assert(/veo 3\.1 - lite/.test(ap), "selects Veo 3.1 - Lite");
	assert(/omni flash\|imagen/.test(ap) || /omni flash/.test(ap), "Omni Flash (video) classified wrong");
	// Nano Banana lives in the IMAGE section (above the band) — must NOT appear in the
	// video model classification logic.
	assert(!/nano banana/.test(ap), "Nano Banana is not part of the video-section model logic");
	assert(/GFV2_MODEL_VEO_LITE_NOT_FOUND/.test(ap), "named blocker when Veo Lite unavailable");
});

test("decide: video lane (requireVisibleVeo) — hidden model fails VEO_LITE_NOT_FOUND, not soft-pass", () => {
	const hidden = { settings_panel_opened: true, ratio_9_16_confirmed: true, count_1x_confirmed: true, model_visible_wrong: false, model_veo_lite_confirmed: false, model_state: "unknown" };
	const r = gfv2DecideSettingsProof(hidden, null, { requireVisibleVeo: true });
	assert(r.proceed === false && r.error === "GFV2_MODEL_VEO_LITE_NOT_FOUND", "no soft-pass for the video lane");
	assert(!stagesOf(r).some((x) => x.startsWith("GFV2_MODEL_HIDDEN_SOFT_PASS")), "must not soft-pass");
	// confirmed Veo passes
	const ok = gfv2DecideSettingsProof({ ...hidden, model_veo_lite_confirmed: true, model_state: "correct" }, "veo 3.1 - lite", { requireVisibleVeo: true });
	assert(ok.proceed === true && stagesOf(ok).includes("GFV2_MODEL_VEO_LITE_CONFIRMED:PASS"), "Veo Lite passes");
});

test("decide: visible wrong VIDEO model (Omni Flash) hard-fails; persistence false fails", () => {
	const wrong = gfv2DecideSettingsProof({ settings_panel_opened: true, ratio_9_16_confirmed: true, count_1x_confirmed: true, model_visible_wrong: true, model_veo_lite_confirmed: false, model_state: "wrong", model_canonical: "omni flash" }, "omni flash", { requireVisibleVeo: true });
	assert(wrong.proceed === false && wrong.error === "GFV2_VISIBLE_WRONG_MODEL", "omni flash (video) hard-fail");
	const notPersist = gfv2DecideSettingsProof({ settings_panel_opened: true, ratio_9_16_confirmed: true, count_1x_confirmed: true, model_veo_lite_confirmed: true, model_state: "correct", settings_persisted: false }, "veo 3.1 - lite", { requireVisibleVeo: true });
	assert(notPersist.proceed === false && notPersist.error === "GFV2_SETTINGS_NOT_PERSISTED", "explicit non-persist fails");
});

test("decide: Nano Banana is NOT passed into the video decision (image-section ignored upstream)", () => {
	// The driver builds proof from the VIDEO-section primitive result only; image-section
	// Nano Banana never sets model_visible_wrong. Simulate a clean video proof:
	const r = gfv2DecideSettingsProof({ settings_panel_opened: true, ratio_9_16_confirmed: true, count_1x_confirmed: true, model_veo_lite_confirmed: true, model_state: "correct", settings_persisted: true }, "veo 3.1 - lite", { requireVisibleVeo: true });
	assert(r.proceed === true, "image-section Nano Banana irrelevant — video proof passes");
});

test("content: selection truthiness reads aria-selected / aria-checked / data-state", () => {
	const sel = SRC_BLOCK(CFD_SRC, "_gfv2IsSelected");
	assert(/aria-pressed/.test(sel) && /aria-checked/.test(sel) && /aria-selected/.test(sel), "aria states");
	assert(/data-state/.test(sel), "data-state");
});

test("content: extractFlowSectionConfig is now DEFINED (red-gate fix)", () => {
	assert(/function extractFlowSectionConfig\(/.test(CFD_SRC), "function defined");
	// normalises crop_9_16 -> 9:16 for the V2 signal comparisons
	assert(/crop_9_16:\s*'9:16'/.test(CFD_SRC), "aspect normalised to colon form");
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
