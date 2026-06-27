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
		result.attempted_strategies.some((item) =>
			String(item.candidate_text || "").includes("Video"),
		),
	);
}

async function testViewSettingsLauncherPreferredNearComposer() {
	installDom(baseComposerHtml());
	applyCommonRects(document);

	let wrongChipClicks = 0;
	const countChip = document.createElement("button");
	countChip.type = "button";
	countChip.textContent = "1x";
	countChip.setAttribute("aria-haspopup", "menu");
	countChip.addEventListener("click", () => {
		wrongChipClicks += 1;
	});
	document.getElementById("config-wrap").appendChild(countChip);
	setVisibleRect(countChip, 700, 848, 48, 32);

	const viewSettings = document.createElement("button");
	viewSettings.type = "button";
	viewSettings.textContent = "settings_2 View Settings";
	viewSettings.addEventListener("click", () => {
		const panel = document.createElement("div");
		panel.setAttribute("role", "dialog");
		panel.textContent = "Video Frames 9:16 1x Veo 3.1 - Lite";
		document.body.appendChild(panel);
		setVisibleRect(panel, 690, 620, 250, 220);
	});
	document.getElementById("config-wrap").appendChild(viewSettings);
	setVisibleRect(viewSettings, 754, 848, 140, 32);

	const result = runner.MAIN_openComposerSettingsPanel("data-test-launcher");
	assert.equal(result.ok, true);
	assert.equal(result.strategy, "settings_icon");
	assert.equal(wrongChipClicks, 0, "standalone count chip must not be used as the settings opener");
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

async function testUploadMediaAcceptsAddMediaButton() {
	installDom(baseComposerHtml());
	applyCommonRects(document);
	let clicked = 0;
	const addMedia = document.createElement("button");
	addMedia.type = "button";
	addMedia.textContent = "add Add Media";
	addMedia.addEventListener("click", () => {
		clicked += 1;
	});
	document.getElementById("footer").appendChild(addMedia);
	setVisibleRect(addMedia, 700, 848, 140, 32);

	const result = await runner._clickUploadMedia(createScriptingAdapter(), 9001, {});
	assert.equal(result.ok, true, "Add Media button should be accepted as upload entry point");
	assert.ok(clicked >= 1, "Add Media button should be triggered at least once");
}

async function testAssetPickerLauncherPrefersComposerAddCreateButton() {
	installDom(baseComposerHtml());
	applyCommonRects(document);

	const createLauncher = document.createElement("button");
	createLauncher.type = "button";
	createLauncher.textContent = "add_2 Create";
	document.getElementById("footer").appendChild(createLauncher);
	setVisibleRect(createLauncher, 382, 848, 94, 32);

	const stamped = runner.MAIN_stampAssetPickerLauncher("data-test-asset-launcher");
	assert.equal(stamped.ok, true, "asset picker launcher should be resolved");
	assert.equal(stamped.strategy, "add_create_launcher");
	assert.match(String(stamped.text || ""), /Create/);
}

async function testCloseComposerSettingsPanelTraversesShadowRoots() {
	installDom(baseComposerHtml());
	applyCommonRects(document);

	const host = document.createElement("div");
	document.body.appendChild(host);
	setVisibleRect(host, 580, 840, 220, 40);
	const shadow = host.attachShadow({ mode: "open" });
	const button = document.createElement("button");
	button.type = "button";
	button.textContent = "Video 1x";
	let clicked = 0;
	button.addEventListener("click", () => {
		clicked += 1;
	});
	shadow.appendChild(button);
	setVisibleRect(button, 600, 848, 120, 32);

	const result = runner.MAIN_closeComposerSettingsPanel();
	assert.equal(result.action, "pill_closed_pass1");
	assert.ok(clicked >= 1, "shadow-root config pill should be clicked");
}

async function testStartSlotFallbackAcceptsCreateOrDropMediaLabel() {
	installDom(baseComposerHtml());
	applyCommonRects(document);
	let clicked = 0;
	const startSlot = document.createElement("div");
	startSlot.setAttribute("role", "button");
	startSlot.textContent = "Start creating or drop media";
	startSlot.addEventListener("click", () => {
		clicked += 1;
	});
	document.getElementById("composer").appendChild(startSlot);
	setVisibleRect(startSlot, 380, 770, 220, 56);

	const result = await runner._clickStart(createScriptingAdapter(), 9000, {});
	assert.equal(result.ok, true, "semantic Start-slot fallback should succeed");
	assert.ok(clicked >= 1, "Start slot fallback should dispatch to the visible slot control");
}

async function testStartSlotFallbackTraversesShadowHostContainer() {
	installDom(baseComposerHtml());
	applyCommonRects(document);
	let clicked = 0;
	const host = document.createElement("div");
	host.setAttribute("role", "button");
	host.addEventListener("click", () => {
		clicked += 1;
	});
	document.getElementById("composer").appendChild(host);
	setVisibleRect(host, 380, 770, 240, 56);

	const shadow = host.attachShadow({ mode: "open" });
	const label = document.createElement("span");
	label.textContent = "Start creating or drop media";
	shadow.appendChild(label);
	setVisibleRect(label, 390, 780, 200, 24);

	const result = await runner._clickStart(createScriptingAdapter(), 9002, {});
	assert.equal(result.ok, true, "semantic Start-slot fallback should cross shadow-host boundaries");
	assert.ok(clicked >= 1, "shadow-host Start slot fallback should click the real host container");
}

async function testStartSlotFallbackUsesLabelNodeWhenContainerOwnsClick() {
	installDom(baseComposerHtml());
	applyCommonRects(document);
	let clicked = 0;
	const container = document.createElement("div");
	container.addEventListener("click", () => {
		clicked += 1;
	});
	document.getElementById("composer").appendChild(container);
	setVisibleRect(container, 380, 770, 240, 56);

	const label = document.createElement("span");
	label.textContent = "Start creating or drop media";
	container.appendChild(label);
	setVisibleRect(label, 390, 780, 200, 24);

	const result = await runner._clickStart(createScriptingAdapter(), 9003, {});
	assert.equal(result.ok, true, "semantic Start-slot fallback should use a non-button label node when needed");
	assert.ok(clicked >= 1, "label-node Start fallback should bubble into the owning container");
}

async function testStartEntryPointPrefersVisibleStartSlotOverCreateLauncher() {
	installDom(baseComposerHtml());
	applyCommonRects(document);

	let startClicks = 0;
	const startButton = document.createElement("button");
	startButton.type = "button";
	startButton.textContent = "Start";
	startButton.addEventListener("click", () => {
		startClicks += 1;
	});
	document.getElementById("composer").appendChild(startButton);
	setVisibleRect(startButton, 380, 770, 70, 26);

	let createClicks = 0;
	const createLauncher = document.createElement("button");
	createLauncher.type = "button";
	createLauncher.textContent = "add_2 Create";
	createLauncher.addEventListener("click", () => {
		createClicks += 1;
	});
	document.getElementById("footer").appendChild(createLauncher);
	setVisibleRect(createLauncher, 382, 848, 94, 32);

	const result = await runner._clickStartEntryPoint(createScriptingAdapter(), 9004, { settleMs: 0 });
	assert.equal(result.ok, true, "start entrypoint should succeed");
	assert.ok(startClicks >= 1, "visible Start button must be preferred");
	assert.equal(createClicks, 0, "composer create launcher must stay fallback-only when Start exists");
}

async function testRunnerUploadsBeforePromptInsertionViaStartSlotFlow() {
	installDom(`
		<!doctype html>
		<html>
			<body>
				<div id="mode-row">
					<button id="video-mode" type="button" data-state="active">Video</button>
					<button id="frames-mode" type="button" data-state="active">Frames</button>
				</div>
				<form id="composer">
					<button id="start-slot" type="button">Start</button>
					<textarea id="prompt" placeholder="What do you want to create?"></textarea>
					<div id="footer">
						<button id="create-launcher" type="button">add_2 Create</button>
						<button id="config-pill" type="button" aria-haspopup="menu">Video crop_9_16 1x</button>
						<button id="generate-btn" type="button" aria-label="Generate">
							<span class="material-symbols-outlined">arrow_forward</span>
						</button>
					</div>
				</form>
			</body>
		</html>
	`);
	setVisibleRect(document.body, 0, 0, 1280, 900);
	setVisibleRect(document.getElementById("mode-row"), 360, 80, 240, 30);
	setVisibleRect(document.getElementById("video-mode"), 360, 80, 70, 28);
	setVisibleRect(document.getElementById("frames-mode"), 440, 80, 80, 28);
	setVisibleRect(document.getElementById("composer"), 360, 760, 560, 130);
	setVisibleRect(document.getElementById("start-slot"), 380, 770, 70, 26);
	setVisibleRect(document.getElementById("prompt"), 390, 815, 470, 26);
	setVisibleRect(document.getElementById("footer"), 380, 848, 520, 40);
	setVisibleRect(document.getElementById("create-launcher"), 382, 848, 94, 32);
	setVisibleRect(document.getElementById("config-pill"), 600, 848, 180, 32);
	setVisibleRect(document.getElementById("generate-btn"), 864, 848, 32, 32);

	const events = [];
	let startCaptured = false;
	let createClickCaptured = false;
	let uploadClickCaptured = false;
	let addToPromptCaptured = false;
	let promptInputCaptured = false;
	const prompt = document.getElementById("prompt");
	prompt.addEventListener("input", () => {
		if (!promptInputCaptured) {
			events.push("prompt-inserted");
			promptInputCaptured = true;
		}
	});

	const startSlot = document.getElementById("start-slot");
	startSlot.addEventListener("click", () => {
		if (!startCaptured) {
			events.push("start-clicked");
			startCaptured = true;
		}
		const modal = document.createElement("div");
		modal.id = "asset-modal";
		modal.setAttribute("role", "dialog");
		modal.innerHTML = `
			<button id="upload-media" type="button">Upload media</button>
		`;
		document.body.appendChild(modal);
		setVisibleRect(modal, 40, 60, 640, 420);
		const uploadMedia = document.getElementById("upload-media");
		setVisibleRect(uploadMedia, 60, 420, 140, 32);
		uploadMedia.addEventListener("click", () => {
			if (!uploadClickCaptured) {
				events.push("upload-media-clicked");
				uploadClickCaptured = true;
			}
			modal.innerHTML = `
				<div id="asset-card">generated-image-178138</div>
				<button id="add-to-prompt" type="button">Add to Prompt</button>
			`;
			setVisibleRect(document.getElementById("asset-card"), 220, 100, 180, 60);
			const addToPrompt = document.getElementById("add-to-prompt");
			setVisibleRect(addToPrompt, 220, 360, 180, 36);
			addToPrompt.addEventListener("click", () => {
				if (!addToPromptCaptured) {
					events.push("add-to-prompt-clicked");
					addToPromptCaptured = true;
				}
				modal.remove();
			});
		});
	});

	const createLauncher = document.getElementById("create-launcher");
	createLauncher.addEventListener("click", () => {
		if (!createClickCaptured) {
			events.push("create-launcher-clicked");
			createClickCaptured = true;
		}
	});

	const deps = { scripting: createScriptingAdapter(), telemetry: () => {} };
	const result = await runner.executeF2VVisibleSopRunner(
		deps,
		9004,
		{ mode: "F2V", prompt: "hero product shot" },
		{ settleMs: 0, startToUploadWaitMs: 0, uploadWaitMs: 0, postAddToPromptWaitMs: 0, skipGenerate: true },
	);
	assert.equal(result.ok, true, "asset picker upload path should succeed: " + JSON.stringify(result.error || result.detail || ""));
	assert.deepEqual(
		events.slice(0, 4),
		["start-clicked", "upload-media-clicked", "add-to-prompt-clicked", "prompt-inserted"],
		"runner must use Start first, then upload and confirm the asset before inserting the prompt",
	);
	assert.equal(createClickCaptured, false, "create launcher must not be used when Start exists");
	assert.equal(result.stage_results.media_attached, true);
	assert.equal(result.stage_results.prompt_inserted, true);
	const uploadWaitIndex = result.stages.findIndex((stage) => stage.stage === "F2V_SOP_UPLOAD_WAIT_DONE" && stage.status === "PASS");
	const promptStageIndex = result.stages.findIndex((stage) => stage.stage === "F2V_SOP_PROMPT_INSERTED" && stage.status === "PASS");
	assert.ok(uploadWaitIndex >= 0, "upload wait stage must pass");
	assert.ok(promptStageIndex > uploadWaitIndex, "prompt insertion must happen after upload wait completes");
}

async function testAddToPromptFallbackClicksAssetCardFirst() {
	installDom(baseComposerHtml());
	applyCommonRects(document);

	const modal = document.createElement("div");
	modal.setAttribute("role", "dialog");
	modal.innerHTML = `
		<div id="picker-shell">
			<button id="asset-card" type="button"><img id="asset-img" alt="asset" />generated-image-178138</button>
		</div>
	`;
	document.body.appendChild(modal);
	setVisibleRect(modal, 40, 60, 640, 420);
	setVisibleRect(document.getElementById("picker-shell"), 60, 90, 240, 220);
	const assetCard = document.getElementById("asset-card");
	setVisibleRect(assetCard, 80, 120, 180, 140);
	setVisibleRect(document.getElementById("asset-img"), 90, 130, 120, 90);

	let selected = false;
	assetCard.addEventListener("click", () => {
		if (selected) return;
		selected = true;
		const addButton = document.createElement("button");
		addButton.id = "add-after-select";
		addButton.type = "button";
		addButton.textContent = "Add to Prompt";
		modal.appendChild(addButton);
		setVisibleRect(addButton, 220, 360, 180, 36);
	});

	const result = await runner._clickAddToPrompt(createScriptingAdapter(), 9005, {});
	assert.equal(result.ok, true, "asset-card fallback should recover Add to Prompt");
	assert.equal(selected, true, "asset card must be selected first");
}

async function testShadowRootRatioOptionIsFoundAndClickable() {
	installDom(baseComposerHtml());
	applyCommonRects(document);

	const host = document.createElement("div");
	host.id = "shadow-host";
	document.body.appendChild(host);
	setVisibleRect(host, 680, 610, 260, 240);

	const shadow = host.attachShadow({ mode: "open" });
	const panel = document.createElement("div");
	panel.setAttribute("role", "dialog");
	shadow.appendChild(panel);
	setVisibleRect(panel, 690, 620, 240, 220);

	let clicked = 0;
	const option = document.createElement("button");
	option.type = "button";
	option.textContent = "crop_9_16 Portrait 9:16";
	option.addEventListener("click", () => {
		clicked += 1;
	});
	panel.appendChild(option);
	setVisibleRect(option, 710, 660, 150, 32);

	const found = runner.MAIN_findVisibleCandidatesByExactLabel(
		"9:16",
		["crop_9_16 Portrait 9:16", "Portrait 9:16"],
		["button", "option"],
		"data-test-shadow",
	);
	assert.equal(found.ok, true);
	assert.equal(found.matches.length, 1, "shadow-root option should be discoverable");

	const clickResult = runner.MAIN_clickStampedElement(found.matches[0].stamp_attr, found.matches[0].stamp_id);
	assert.equal(clickResult.ok, true, "stamped shadow-root option should be clickable");
	assert.ok(clicked >= 1, "shadow-root option click should dispatch to the real element");
}

// ───────────────────────────────────────────────────────────────────────
// Split-chip / region-text regression suite — reproduces the LIVE failure
// (F2V_SOP_RATIO_9_16_CLICKED → ERR_F2V_OPTION_RATIO_9_16_NOT_FOUND with a
// degraded "1x" pill and top_mode=UNKNOWN). The editor was already at 9:16/1x,
// but the ratio lived on a separate chip / in aggregate region text, so the
// runner could not confirm it and opened a panel that then failed.
// ───────────────────────────────────────────────────────────────────────

function splitChipsHtml() {
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
						<button id="ratio-chip" type="button" aria-haspopup="menu">crop_9_16</button>
						<button id="count-chip" type="button" aria-haspopup="menu">1x</button>
						<button id="model-chip" type="button" aria-haspopup="menu">Veo 3.1 - Lite</button>
						<button id="generate-btn" type="button" aria-label="Generate">
							<span class="material-symbols-outlined">arrow_forward</span>
						</button>
					</div>
				</form>
			</body>
		</html>
	`;
}

function applySplitChipsRects(document) {
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
	setVisibleRect(document.getElementById("ratio-chip"), 600, 848, 70, 32);
	setVisibleRect(document.getElementById("count-chip"), 680, 848, 40, 32);
	setVisibleRect(document.getElementById("model-chip"), 730, 848, 120, 32);
	setVisibleRect(document.getElementById("generate-btn"), 864, 848, 32, 32);
}

async function testBottomComposerStateSplitChipsDoNotCollapseTo1x() {
	installDom(splitChipsHtml());
	applySplitChipsRects(document);
	const state = runner.MAIN_getBottomComposerState();
	assert.equal(state.ok, true);
	assert.equal(
		state.detectedRatio,
		"9:16",
		"ratio chip must not be clobbered by the shorter '1x' count chip",
	);
	assert.equal(state.detectedCount, "1x", "count must remain detected alongside the ratio");
	assert.equal(state.detectedModelFamily, "veo", "model on a separate chip must still be detected");
	assert.equal(state.topMode, "Video");
	assert.equal(state.subMode, "Frames");
	assert.ok(
		/9_16|9:16/.test(String(state.pillText || "")),
		"pillText must not degrade to a bare partial token when ratio is co-present",
	);
}

async function testBottomComposerStateRecoversRatioFromRegionText() {
	// The bottom pill exposes ONLY a count chip ("1x"); the 9:16 ratio is present
	// solely inside a large container whose textContent exceeds the 160-char
	// compact-chip cap, so the per-element pill scan cannot isolate it. This is the
	// exact runner-vs-diagnostic mismatch from the live failure.
	const filler = "Project ready. Composer editable. Generate available. ".repeat(4);
	installDom(`
		<!doctype html>
		<html>
			<body>
				<div id="mode-row">
					<button id="video-mode" type="button" data-state="active">Video</button>
					<button id="frames-mode" type="button" data-state="active">Frames</button>
				</div>
				<form id="composer">
					<button id="start-chip" type="button" aria-label="Start">Start</button>
					<textarea id="prompt" placeholder="What do you want to create?"></textarea>
					<div id="status-banner">${filler} Video Frames 9:16 1x ${filler}</div>
					<div id="footer">
						<button id="count-chip" type="button" aria-haspopup="menu">1x</button>
						<button id="generate-btn" type="button" aria-label="Generate">
							<span class="material-symbols-outlined">arrow_forward</span>
						</button>
					</div>
				</form>
			</body>
		</html>
	`);
	setVisibleRect(document.body, 0, 0, 1280, 900);
	setVisibleRect(document.getElementById("mode-row"), 360, 80, 400, 30);
	setVisibleRect(document.getElementById("video-mode"), 360, 80, 70, 28);
	setVisibleRect(document.getElementById("frames-mode"), 520, 80, 80, 28);
	setVisibleRect(document.getElementById("composer"), 360, 720, 560, 170);
	setVisibleRect(document.getElementById("start-chip"), 380, 730, 70, 26);
	setVisibleRect(document.getElementById("prompt"), 390, 815, 470, 26);
	setVisibleRect(document.getElementById("count-chip"), 680, 848, 40, 32);
	setVisibleRect(document.getElementById("generate-btn"), 864, 848, 32, 32);

	const state = runner.MAIN_getBottomComposerState();
	assert.equal(state.ok, true);
	assert.equal(
		state.detectedRatio,
		"9:16",
		"ratio must be recovered from composer-region text when no compact ratio chip exists",
	);
	assert.equal(state.detectedCount, "1x");
}

async function testRunnerConfirmsSplitChipConfigWithoutOpeningPanel() {
	installDom(splitChipsHtml());
	applySplitChipsRects(document);
	const deps = { scripting: createScriptingAdapter(), telemetry: () => {} };
	const result = await runner.executeF2VVisibleSopRunner(
		deps,
		5151,
		{ mode: "F2V", prompt: "hero product shot" }, // accept current model on the pill
		{ settleMs: 0, uploadWaitMs: 0, skipUpload: true, skipGenerate: true },
	);
	assert.equal(
		result.ok,
		true,
		"split-chip 9:16/1x must confirm without a failing scan: " +
			JSON.stringify(result.error || result.detail || ""),
	);
	const failStages = result.stages.filter((s) => s.status === "FAIL");
	assert.equal(failStages.length, 0, "no FAIL stages expected: " + JSON.stringify(failStages));
	assert.ok(
		result.stages.some((s) => /tier_one_pill_confirmed/.test(String(s.message || ""))),
		"split-chip config must be confirmed from the pill without opening the settings panel",
	);
	assert.ok(
		!result.stages.some((s) => s.stage === "F2V_SOP_RATIO_9_16_CLICKED" && s.status === "FAIL"),
		"the ratio step must never reach the not-found failure on an already-9:16 editor",
	);
}

// ───────────────────────────────────────────────────────────────────────
// LIVE-pill regression — reproduces the exact DOM the agent self-test reported
// from the real signed-in tab: the bottom config pill is a SINGLE button whose
// textContent concatenates its spans with no whitespace ("Videocrop_9_161x"),
// and the pill carries NO model (model is UNKNOWN even on a correct editor).
// Pre-fix this made detectedCount=null → Tier One opened the settings panel →
// the pill was swapped out → ratio step failed ERR_F2V_OPTION_RATIO_9_16_NOT_FOUND.
// ───────────────────────────────────────────────────────────────────────

function liveGluedPillHtml() {
	// NOTE: the three pill spans MUST have no whitespace between them so the
	// button's textContent is exactly "Videocrop_9_161x", matching the live DOM.
	return `
		<!doctype html>
		<html>
			<body>
				<div id="mode-row">
					<button id="video-mode" type="button" data-state="active">Video</button>
					<button id="image-mode" type="button">Image</button>
					<button id="frames-mode" type="button" data-state="active">Frames</button>
				</div>
				<form id="composer">
					<button id="start-chip" type="button" aria-label="Start">Start</button>
					<textarea id="prompt" placeholder="What do you want to create?"></textarea>
					<div id="footer">
						<button id="config-pill" type="button" aria-haspopup="menu"><span>Video</span><span>crop_9_16</span><span>1x</span></button>
						<button id="generate-btn" type="button" aria-label="Generate">
							<span class="material-symbols-outlined">arrow_forward</span>
						</button>
					</div>
				</form>
			</body>
		</html>
	`;
}

function applyLiveGluedPillRects(document) {
	setVisibleRect(document.body, 0, 0, 1280, 900);
	setVisibleRect(document.getElementById("mode-row"), 360, 80, 400, 30);
	setVisibleRect(document.getElementById("video-mode"), 360, 80, 70, 28);
	setVisibleRect(document.getElementById("image-mode"), 440, 80, 70, 28);
	setVisibleRect(document.getElementById("frames-mode"), 520, 80, 80, 28);
	setVisibleRect(document.getElementById("composer"), 360, 760, 560, 130);
	setVisibleRect(document.getElementById("start-chip"), 380, 770, 70, 26);
	setVisibleRect(document.getElementById("prompt"), 390, 815, 470, 26);
	setVisibleRect(document.getElementById("footer"), 380, 848, 520, 40);
	setVisibleRect(document.getElementById("config-pill"), 600, 848, 220, 32);
	setVisibleRect(document.getElementById("generate-btn"), 864, 848, 32, 32);
}

async function testBottomComposerStateGluedLivePillDetectsCount() {
	installDom(liveGluedPillHtml());
	applyLiveGluedPillRects(document);
	assert.equal(
		document.getElementById("config-pill").textContent,
		"Videocrop_9_161x",
		"fixture must reproduce the glued live pill textContent",
	);
	const state = runner.MAIN_getBottomComposerState();
	assert.equal(state.ok, true);
	assert.equal(state.detectedRatio, "9:16", "ratio must parse from the glued pill");
	assert.equal(
		state.detectedCount,
		"1x",
		"count must parse from the glued '...161x' tail (regression: returned null pre-fix)",
	);
	assert.equal(state.topMode, "Video");
	assert.equal(state.subMode, "Frames");
}

async function testRunnerConfirmsGluedPillModelUnknownWithoutOpeningPanel() {
	installDom(liveGluedPillHtml());
	applyLiveGluedPillRects(document);
	const deps = { scripting: createScriptingAdapter(), telemetry: () => {} };
	const result = await runner.executeF2VVisibleSopRunner(
		deps,
		6262,
		{ mode: "F2V", modelLabel: "Veo 3.1 - Lite", prompt: "hero product shot" },
		{ settleMs: 0, uploadWaitMs: 0, skipUpload: true, skipGenerate: true },
	);
	assert.equal(
		result.ok,
		true,
		"live glued pill (9:16/1x, model UNKNOWN) must confirm without a failing scan: " +
			JSON.stringify(result.error || result.detail || ""),
	);
	const failStages = result.stages.filter((s) => s.status === "FAIL");
	assert.equal(failStages.length, 0, "no FAIL stages expected: " + JSON.stringify(failStages));
	assert.ok(
		!result.stages.some((s) => s.stage === "F2V_SOP_RATIO_9_16_CLICKED" && s.status === "FAIL"),
		"ratio step must not fail on an already-9:16 editor whose pill is model-less",
	);
	assert.ok(
		result.stages.some((s) => /tier_one_pill_confirmed/.test(String(s.message || ""))),
		"model-UNKNOWN must be treated as non-fatal so the panel is never opened",
	);
}

async function main() {
	await testBottomComposerConfigPillOpensPanel();
	await testSplitSpansResolveToInteractiveAncestor();
	await testAssetLibraryVideoIgnored();
	await testViewSettingsLauncherPreferredNearComposer();
	await testMissingOpenerReturnsStructuredDiagnostics();
	await testBottomComposerStateDetectsNanoBananaPill();
	await testRunnerConfirmsAlreadyConfiguredPill();
	await testRunnerAcceptsCurrentModelWhenUnspecified();
	await testNavLogoIsBlacklisted();
	await testUploadMediaAcceptsAddMediaButton();
	await testAssetPickerLauncherPrefersComposerAddCreateButton();
	await testCloseComposerSettingsPanelTraversesShadowRoots();
	await testStartSlotFallbackAcceptsCreateOrDropMediaLabel();
	await testStartSlotFallbackTraversesShadowHostContainer();
	await testStartSlotFallbackUsesLabelNodeWhenContainerOwnsClick();
	await testStartEntryPointPrefersVisibleStartSlotOverCreateLauncher();
	await testRunnerUploadsBeforePromptInsertionViaStartSlotFlow();
	await testAddToPromptFallbackClicksAssetCardFirst();
	await testShadowRootRatioOptionIsFoundAndClickable();
	await testBottomComposerStateSplitChipsDoNotCollapseTo1x();
	await testBottomComposerStateRecoversRatioFromRegionText();
	await testRunnerConfirmsSplitChipConfigWithoutOpeningPanel();
	await testBottomComposerStateGluedLivePillDetectsCount();
	await testRunnerConfirmsGluedPillModelUnknownWithoutOpeningPanel();
	console.log("PASS test-f2v-flow-queue-runner");
}

main().catch((error) => {
	console.error("FAIL test-f2v-flow-queue-runner");
	console.error(error && error.stack ? error.stack : error);
	process.exitCode = 1;
});
