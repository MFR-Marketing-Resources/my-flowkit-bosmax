const assert = require("node:assert/strict");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const RUNNER_PATH = path.join(__dirname, "..", "extension", "f2v-flow-queue-runner.js");
const runner = require(RUNNER_PATH);

function installDom(html) {
	const dom = new JSDOM(html, {
		url: "https://labs.google/fx/tools/flow",
		pretendToBeVisual: true,
	});
	const { window } = dom;
	global.window = window;
	global.document = window.document;
	global.HTMLElement = window.HTMLElement;
	global.Element = window.Element;
	global.Node = window.Node;
	global.Event = window.Event;
	global.MouseEvent = window.MouseEvent;
	global.PointerEvent = window.PointerEvent || window.MouseEvent;
	global.navigator = window.navigator;
	global.getComputedStyle = window.getComputedStyle.bind(window);
	if (!global.CSS) {
		global.CSS = {};
	}
	if (!global.CSS.escape) {
		global.CSS.escape = (value) => String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
	}
	return dom;
}

function setVisibleRect(node, left, top, width, height) {
	node.style.display = "block";
	node.style.visibility = "visible";
	node.style.opacity = "1";
	Object.defineProperty(node, "getBoundingClientRect", {
		configurable: true,
		value: () => ({
			x: left,
			y: top,
			top,
			left,
			width,
			height,
			right: left + width,
			bottom: top + height,
			toJSON() {
				return { x: left, y: top, width, height };
			},
		}),
	});
	return node;
}

function baseComposerHtml(extra = "") {
	return `
		<!doctype html>
		<html>
			<body>
				<div id="asset-library">${extra}</div>
				<form id="composer">
					<div id="start-chip">Start</div>
					<div id="end-chip">End</div>
					<textarea id="prompt" placeholder="What do you want to create?"></textarea>
					<div id="footer">
						<button id="agent-btn" type="button">Agent</button>
						<div id="config-wrap"></div>
						<button id="generate-btn" type="button" aria-label="Generate">
							<span class="material-symbols-outlined">arrow_forward</span>
						</button>
					</div>
				</form>
			</body>
		</html>
	`;
}

function applyCommonRects(document) {
	setVisibleRect(document.body, 0, 0, 1280, 900);
	setVisibleRect(document.getElementById("composer"), 360, 760, 560, 130);
	setVisibleRect(document.getElementById("prompt"), 390, 815, 470, 26);
	setVisibleRect(document.getElementById("footer"), 380, 848, 520, 40);
	setVisibleRect(document.getElementById("agent-btn"), 382, 850, 70, 24);
	setVisibleRect(document.getElementById("generate-btn"), 864, 848, 32, 32);
}

function createScriptingAdapter() {
	return {
		async executeScript({ func, args }) {
			return [{ result: func.apply(null, args || []) }];
		},
	};
}

async function testBottomComposerConfigPillOpensPanel() {
	installDom(baseComposerHtml('<button id="library-video" type="button">Video</button>'));
	applyCommonRects(document);
	setVisibleRect(document.getElementById("library-video"), 20, 120, 90, 28);

	const launcher = document.createElement("div");
	launcher.id = "video-pill";
	launcher.setAttribute("role", "button");
	launcher.setAttribute("aria-haspopup", "menu");
	launcher.innerHTML = '<span>Video</span><span class="material-symbols-outlined">movie</span><span>1x</span>';
	launcher.addEventListener("click", () => {
		const panel = document.createElement("div");
		panel.setAttribute("role", "dialog");
		panel.textContent = "Video Frames 9:16 1x Veo 3.1 - Lite";
		document.body.appendChild(panel);
		setVisibleRect(panel, 720, 620, 240, 220);
	});
	document.getElementById("config-wrap").appendChild(launcher);
	setVisibleRect(launcher, 774, 848, 86, 32);

	const result = runner.MAIN_openComposerSettingsPanel("data-test-launcher");
	assert.equal(result.ok, true);
	assert.equal(result.strategy, "bottom_composer_config_pill");
	assert.equal(result.clicked, true);
	assert.ok(
		result.candidate_settings_launchers_found.some((candidate) =>
			String(candidate.text || "").includes("Video"),
		),
	);
}

async function testSplitSpansResolveToInteractiveAncestor() {
	installDom(baseComposerHtml());
	applyCommonRects(document);

	let clickCount = 0;
	const launcher = document.createElement("div");
	launcher.id = "split-pill";
	launcher.setAttribute("data-state", "closed");
	launcher.innerHTML = '<span class="label">Video</span><span class="count">1x</span>';
	launcher.addEventListener("click", () => {
		clickCount += 1;
		const panel = document.createElement("div");
		panel.setAttribute("role", "dialog");
		panel.textContent = "Video Frames 9:16 1x Veo 3.1 - Lite";
		document.body.appendChild(panel);
		setVisibleRect(panel, 700, 620, 260, 220);
	});
	document.getElementById("config-wrap").appendChild(launcher);
	setVisibleRect(launcher, 778, 848, 78, 32);

	const result = runner.MAIN_openComposerSettingsPanel("data-test-launcher");
	assert.equal(result.ok, true);
	assert.equal(result.strategy, "bottom_composer_config_pill");
	assert.equal(clickCount, 1);
}

async function testAssetLibraryVideoIgnored() {
	installDom(baseComposerHtml('<div id="asset-video" role="button">Video</div>'));
	applyCommonRects(document);
	setVisibleRect(document.getElementById("asset-video"), 42, 200, 100, 30);

	const launcher = document.createElement("button");
	launcher.type = "button";
	launcher.innerHTML = '<span>Video</span><span>1x</span>';
	launcher.addEventListener("click", () => {
		const panel = document.createElement("div");
		panel.setAttribute("role", "dialog");
		panel.textContent = "Video Frames 9:16 1x Veo 3.1 - Lite";
		document.body.appendChild(panel);
		setVisibleRect(panel, 690, 620, 250, 220);
	});
	document.getElementById("config-wrap").appendChild(launcher);
	setVisibleRect(launcher, 770, 848, 92, 32);

	const result = runner.MAIN_openComposerSettingsPanel("data-test-launcher");
	assert.equal(result.ok, true);
	assert.equal(result.strategy, "bottom_composer_config_pill");
	assert.ok(
		result.attempted_strategies[0].candidate_text.includes("Video"),
	);
}

async function testMissingOpenerReturnsStructuredDiagnostics() {
	installDom(baseComposerHtml());
	applyCommonRects(document);

	const panel = await runner._openComposerSettingsPanel(createScriptingAdapter(), 777, {});
	assert.equal(panel.ok, false);
	assert.equal(panel.error, runner.ERR.SETTINGS_PANEL_NOT_OPEN);

	const detail = JSON.parse(panel.detail);
	assert.equal(detail.bottom_composer_detected, true);
	assert.equal(detail.prompt_field_present, true);
	assert.equal(detail.generate_arrow_detected, true);
	assert.ok(Array.isArray(detail.bottom_config_pill_candidates));
	assert.ok(
		detail.attempted_strategies.some((item) => item.strategy === "bottom_composer_config_pill"),
	);
}

// ───────────────────────────────────────────────────────────────────────
// Adaptive-pill regression suite — reproduces the LIVE reality reported by
// the operator: the composer pill reads "🍌 Nano Banana Pro crop_9_16 1x"
// (model-agnostic, no "video" token). The runner must read aspect + count +
// model directly off the pill, confirm them WITHOUT opening the settings
// panel, and reach generate-ready.
// ───────────────────────────────────────────────────────────────────────

function configuredPillHtml() {
	return `
		<!doctype html>
		<html>
			<body>
				<div id="mode-row">
					<button id="video-mode" type="button" data-state="active">Video</button>
					<button id="image-mode" type="button">Image</button>
					<button id="frames-mode" type="button" data-state="active">Frames</button>
					<button id="ingredients-mode" type="button">Ingredients</button>
				</div>
				<form id="composer">
					<button id="start-chip" type="button" aria-label="Start">Start</button>
					<textarea id="prompt" placeholder="What do you want to create?"></textarea>
					<div id="footer">
						<button id="config-pill" type="button" aria-haspopup="menu">🍌 Nano Banana Pro crop_9_16 1x</button>
						<button id="generate-btn" type="button" aria-label="Generate">
							<span class="material-symbols-outlined">arrow_forward</span>
						</button>
					</div>
				</form>
			</body>
		</html>
	`;
}

function applyConfiguredPillRects(document) {
	setVisibleRect(document.body, 0, 0, 1280, 900);
	setVisibleRect(document.getElementById("mode-row"), 360, 80, 400, 30);
	setVisibleRect(document.getElementById("video-mode"), 360, 80, 70, 28);
	setVisibleRect(document.getElementById("image-mode"), 440, 80, 70, 28);
	setVisibleRect(document.getElementById("frames-mode"), 520, 80, 80, 28);
	setVisibleRect(document.getElementById("ingredients-mode"), 610, 80, 110, 28);
	setVisibleRect(document.getElementById("composer"), 360, 760, 560, 130);
	setVisibleRect(document.getElementById("start-chip"), 380, 770, 70, 26);
	setVisibleRect(document.getElementById("prompt"), 390, 815, 470, 26);
	setVisibleRect(document.getElementById("footer"), 380, 848, 520, 40);
	setVisibleRect(document.getElementById("config-pill"), 600, 848, 220, 32);
	setVisibleRect(document.getElementById("generate-btn"), 864, 848, 32, 32);
}

async function testBottomComposerStateDetectsNanoBananaPill() {
	installDom(configuredPillHtml());
	applyConfiguredPillRects(document);
	const state = runner.MAIN_getBottomComposerState();
	assert.equal(state.ok, true);
	assert.equal(state.detectedRatio, "9:16", "should detect 9:16 from crop_9_16 (no 'video' token present)");
	assert.equal(state.detectedCount, "1x", "should detect 1x count");
	assert.equal(state.detectedModelFamily, "nano banana", "should detect the Nano Banana family");
	assert.equal(state.topMode, "Video", "Frames lives under the Video top mode");
	assert.equal(state.subMode, "Frames");
}

async function testRunnerConfirmsAlreadyConfiguredPill() {
	installDom(configuredPillHtml());
	applyConfiguredPillRects(document);
	const deps = { scripting: createScriptingAdapter(), telemetry: () => {} };
	const result = await runner.executeF2VVisibleSopRunner(
		deps,
		4242,
		{ mode: "F2V", modelLabel: "Nano Banana 2", prompt: "hero product shot" },
		{ settleMs: 0, uploadWaitMs: 0, skipUpload: true, skipGenerate: true },
	);
	assert.equal(
		result.ok,
		true,
		"runner should reach generate-ready: " + JSON.stringify(result.error || result.detail || ""),
	);
	assert.equal(result.stage_results.settings_configured, true, "settings must be configured");
	assert.equal(result.stage_results.prompt_inserted, true, "prompt must be inserted");
	const failStages = result.stages.filter((s) => s.status === "FAIL");
	assert.equal(failStages.length, 0, "no FAIL stages expected: " + JSON.stringify(failStages));
	assert.ok(
		result.stages.some((s) => /tier_one_pill_confirmed/.test(String(s.message || ""))),
		"settings should be confirmed from the pill without opening the panel",
	);
}

async function testRunnerAcceptsCurrentModelWhenUnspecified() {
	installDom(configuredPillHtml());
	applyConfiguredPillRects(document);
	const deps = { scripting: createScriptingAdapter(), telemetry: () => {} };
	const result = await runner.executeF2VVisibleSopRunner(
		deps,
		4243,
		{ mode: "F2V", prompt: "hero product shot" }, // no model specified → accept current
		{ settleMs: 0, uploadWaitMs: 0, skipUpload: true, skipGenerate: true },
	);
	assert.equal(
		result.ok,
		true,
		"accept-current-model path should succeed: " + JSON.stringify(result.error || result.detail || ""),
	);
	assert.equal(result.stage_results.settings_configured, true);
}

async function testNavLogoIsBlacklisted() {
	installDom(baseComposerHtml('<a id="flow-logo" href="/fx/tools/flow" role="link">Google Flow</a>'));
	applyCommonRects(document);
	setVisibleRect(document.getElementById("flow-logo"), 12, 12, 120, 30);
	// Even though the logo text would loosely relate to navigation, the exact
	// finder must never return the dangerous /fx/tools/flow anchor.
	const found = runner.MAIN_findVisibleCandidatesByExactLabel(
		"Google Flow",
		[],
		["link"],
		"data-test-blacklist",
	);
	assert.equal(found.ok, true);
	assert.equal(found.matches.length, 0, "the Google Flow home link must be blacklisted from candidates");
}

async function main() {
	await testBottomComposerConfigPillOpensPanel();
	await testSplitSpansResolveToInteractiveAncestor();
	await testAssetLibraryVideoIgnored();
	await testMissingOpenerReturnsStructuredDiagnostics();
	await testBottomComposerStateDetectsNanoBananaPill();
	await testRunnerConfirmsAlreadyConfiguredPill();
	await testRunnerAcceptsCurrentModelWhenUnspecified();
	await testNavLogoIsBlacklisted();
	console.log("PASS test-f2v-flow-queue-runner");
}

main().catch((error) => {
	console.error("FAIL test-f2v-flow-queue-runner");
	console.error(error && error.stack ? error.stack : error);
	process.exitCode = 1;
});
