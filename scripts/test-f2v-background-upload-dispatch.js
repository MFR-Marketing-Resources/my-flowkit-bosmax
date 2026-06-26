const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const BACKGROUND_PATH = path.join(__dirname, "..", "extension", "background.js");

function assert(condition, message) {
	if (!condition) {
		throw new Error(`ASSERTION_FAILED: ${message}`);
	}
}

function extractFunctionSource(source, functionName) {
	const markers = [`async function ${functionName}(`, `function ${functionName}(`];
	const startIdx = markers
		.map((marker) => source.indexOf(marker))
		.find((idx) => idx >= 0);
	assert(startIdx >= 0, `missing ${functionName} in background.js`);
	const signatureStart = source.indexOf("(", startIdx);
	assert(signatureStart > startIdx, `missing signature start for ${functionName}`);
	let parenDepth = 0;
	let firstBrace = -1;
	let inSingle = false;
	let inDouble = false;
	let inTemplate = false;
	let inLineComment = false;
	let inBlockComment = false;
	let escaped = false;
	for (let i = signatureStart; i < source.length; i += 1) {
		const ch = source[i];
		const next = source[i + 1];
		if (inLineComment) {
			if (ch === "\n") inLineComment = false;
			continue;
		}
		if (inBlockComment) {
			if (ch === "*" && next === "/") {
				inBlockComment = false;
				i += 1;
			}
			continue;
		}
		if (inSingle) {
			if (!escaped && ch === "'") inSingle = false;
			escaped = !escaped && ch === "\\";
			continue;
		}
		if (inDouble) {
			if (!escaped && ch === '"') inDouble = false;
			escaped = !escaped && ch === "\\";
			continue;
		}
		if (inTemplate) {
			if (!escaped && ch === "`") inTemplate = false;
			escaped = !escaped && ch === "\\";
			continue;
		}
		escaped = false;
		if (ch === "/" && next === "/") {
			inLineComment = true;
			i += 1;
			continue;
		}
		if (ch === "/" && next === "*") {
			inBlockComment = true;
			i += 1;
			continue;
		}
		if (ch === "'") {
			inSingle = true;
			continue;
		}
		if (ch === '"') {
			inDouble = true;
			continue;
		}
		if (ch === "`") {
			inTemplate = true;
			continue;
		}
		if (ch === "(") {
			parenDepth += 1;
			continue;
		}
		if (ch === ")") {
			parenDepth -= 1;
			continue;
		}
		if (parenDepth === 0 && ch === "{") {
			firstBrace = i;
			break;
		}
	}
	assert(firstBrace > startIdx, `missing body brace for ${functionName}`);
	let depth = 0;
	let endIdx = -1;
	for (let i = firstBrace; i < source.length; i += 1) {
		const ch = source[i];
		if (ch === "{") depth += 1;
		else if (ch === "}") {
			depth -= 1;
			if (depth === 0) {
				endIdx = i;
				break;
			}
		}
	}
	assert(endIdx > firstBrace, `unbalanced braces for ${functionName}`);
	return source.slice(startIdx, endIdx + 1);
}

function loadHelpers() {
	const source = fs.readFileSync(BACKGROUND_PATH, "utf8");
	const sandbox = {
		console,
		URL,
		BUILD_ID: "test-build-id",
		openPreferredFlowProjectOrNewProject: async () => ({ ok: false }),
		settleFlowProjectAfterOpen: async () => null,
		focusTab: async (tab) => tab,
		getFlowTabs: async () => [],
		getTabSafe: async () => null,
		waitForTabComplete: async (_tabId) => null,
		probeFlowEditorCandidate: async () => ({ ok: false }),
		buildActiveFlowTabPreflight: async () => ({ ok: false }),
	};
	vm.createContext(sandbox);
	vm.runInContext(
		[
			extractFunctionSource(source, "resolveF2VUploadAssetSource"),
			extractFunctionSource(source, "resolveF2VDomFallbackAssetSource"),
			extractFunctionSource(source, "shouldUseF2VCdpUpload"),
			extractFunctionSource(source, "isF2VPackageUploadOnly"),
			extractFunctionSource(source, "validateF2VPackageUploadOnlyJob"),
			extractFunctionSource(source, "isProjectEditorUrl"),
			extractFunctionSource(source, "isRootFlowUrl"),
			extractFunctionSource(source, "normalizeFlowProjectUrl"),
			extractFunctionSource(source, "isSameFlowProjectUrl"),
			extractFunctionSource(source, "flowTabLooksBroken"),
			extractFunctionSource(source, "findFocusedActiveFlowEditorTab"),
			extractFunctionSource(source, "summarizeFlowTab"),
			extractFunctionSource(source, "extractFlowProjectId"),
			extractFunctionSource(source, "determineFlowBootstrapStartState"),
			extractFunctionSource(source, "rankFlowBootstrapEditorCandidates"),
			extractFunctionSource(source, "mapFlowBootstrapBindingFailureCode"),
			extractFunctionSource(source, "mapOpenFlowNewProjectFailureCode"),
			extractFunctionSource(source, "selectBestFlowTab"),
			extractFunctionSource(source, "buildFlowTabSelectionBinding"),
			extractFunctionSource(source, "isActualFlowEditorProbe"),
			extractFunctionSource(source, "buildUniqueFlowProbeCandidates"),
			extractFunctionSource(source, "isFlowContentScriptReadyForActiveTab"),
			extractFunctionSource(source, "isActiveTabAddMediaLauncherReady"),
			extractFunctionSource(source, "evaluateActiveFlowTabPreflight"),
			extractFunctionSource(source, "resolveExistingProjectEditorAuthority"),
			extractFunctionSource(source, "recoverStrictActiveFlowTabTarget"),
			extractFunctionSource(source, "bootstrapFlowProjectEditorForB2A0"),
			"this.__helpers = { resolveF2VUploadAssetSource, resolveF2VDomFallbackAssetSource, shouldUseF2VCdpUpload, isF2VPackageUploadOnly, validateF2VPackageUploadOnlyJob, normalizeFlowProjectUrl, extractFlowProjectId, determineFlowBootstrapStartState, rankFlowBootstrapEditorCandidates, mapFlowBootstrapBindingFailureCode, mapOpenFlowNewProjectFailureCode, selectBestFlowTab, buildFlowTabSelectionBinding, isActualFlowEditorProbe, buildUniqueFlowProbeCandidates, isFlowContentScriptReadyForActiveTab, isActiveTabAddMediaLauncherReady, evaluateActiveFlowTabPreflight, resolveExistingProjectEditorAuthority, recoverStrictActiveFlowTabTarget, bootstrapFlowProjectEditorForB2A0 };",
		].join("\n"),
		sandbox,
	);
	return { source, __sandbox: sandbox, ...sandbox.__helpers };
}

function loadCdpLifecycleHelpers() {
	const source = fs.readFileSync(BACKGROUND_PATH, "utf8");
	const sandbox = {
		Map,
		setTimeout,
		clearTimeout,
		Promise,
		console,
	};
	vm.createContext(sandbox);
	vm.runInContext(
		[
			"const cdpFileChooserProofRuns = new Map();",
			"const cdpFileChooserProofResults = new Map();",
			"const cdpFileChooserProofAliases = new Map();",
			"async function cleanupCdpFileChooserProofRun(tabId) { cdpFileChooserProofRuns.delete(tabId); for (const [aliasTabId, targetTabId] of Array.from(cdpFileChooserProofAliases.entries())) { if (aliasTabId === tabId || targetTabId === tabId) { cdpFileChooserProofAliases.delete(aliasTabId); } } }",
			extractFunctionSource(source, "settleCdpFileChooserProofRun"),
			extractFunctionSource(source, "resolveCdpFileChooserProofTabId"),
			extractFunctionSource(source, "waitForCdpFileChooserProof"),
			"this.__helpers = { cdpFileChooserProofRuns, cdpFileChooserProofResults, cdpFileChooserProofAliases, settleCdpFileChooserProofRun, resolveCdpFileChooserProofTabId, waitForCdpFileChooserProof };",
		].join("\n"),
		sandbox,
	);
	return { source, ...sandbox.__helpers };
}

function testAssetSourceResolution(resolveF2VUploadAssetSource) {
	assert(
		resolveF2VUploadAssetSource({
			startAsset: { localFilePath: "C:\\tmp\\hero.png", downloadUrl: "https://bad.example/ignored.png" },
		}) === "C:\\tmp\\hero.png",
		"localFilePath must be authoritative",
	);
	assert(
		resolveF2VUploadAssetSource({ startAsset: { downloadUrl: "https://cdn.example/hero.png" } }) ===
			"https://cdn.example/hero.png",
		"downloadUrl must resolve",
	);
	assert(
		resolveF2VUploadAssetSource({ startAsset: { previewUrl: "https://cdn.example/preview.png" } }) ===
			"https://cdn.example/preview.png",
		"previewUrl must resolve",
	);
	assert(
		resolveF2VUploadAssetSource({ startAsset: { mediaId: "media_123" } }) === "media_123",
		"mediaId must resolve",
	);
	assert(
		resolveF2VUploadAssetSource({ startAsset: { assetId: "asset_123" } }) === "asset_123",
		"assetId must resolve",
	);
	assert(
		resolveF2VUploadAssetSource({ startAsset: "https://cdn.example/direct.png" }) ===
			"https://cdn.example/direct.png",
		"string startAsset must resolve",
	);
	assert(
		resolveF2VUploadAssetSource({ product_id: "prod_snake" }) === "prod_snake",
		"snake_case product_id must resolve",
	);
	assert(
		resolveF2VUploadAssetSource({ productId: "prodCamel" }) === "prodCamel",
		"camelCase productId must resolve",
	);
	assert(
		resolveF2VUploadAssetSource({ startImageMediaId: "img_777" }) === "img_777",
		"startImageMediaId must resolve",
	);
	assert(
		resolveF2VUploadAssetSource({}) === null,
		"jobs with no upload asset must remain on the DOM lane",
	);
}

function testPackageUploadOnlyLaneDetection(isF2VPackageUploadOnly) {
	assert(
		isF2VPackageUploadOnly({ lane: "F2V_PACKAGE_UPLOAD_ONLY" }) === true,
		"lane flag must activate the package-upload-only lane",
	);
	assert(
		isF2VPackageUploadOnly({ upload_only: true }) === true,
		"upload_only flag must activate the package-upload-only lane",
	);
	assert(
		isF2VPackageUploadOnly({ mode: "F2V" }) === false,
		"a normal F2V job must NOT be treated as the upload-only lane",
	);
	assert(
		isF2VPackageUploadOnly(null) === false,
		"null job must not activate the lane",
	);
}

function testPackageUploadOnlyValidation(validateF2VPackageUploadOnlyJob) {
	const goodJob = {
		request_id: "req_1",
		workspace_execution_package_id: "pkg_1",
		mode: "F2V",
		prompt: "hero product shot",
		startAsset: { localFilePath: "C:\\tmp\\start.png" },
	};
	assert(
		validateF2VPackageUploadOnlyJob(goodJob).ok === true,
		"a complete package job must validate",
	);
	// Missing local file path → ERR_PACKAGE_START_LOCAL_FILE_REQUIRED.
	const noLocal = validateF2VPackageUploadOnlyJob({
		...goodJob,
		startAsset: { downloadUrl: "https://cdn.example/start.png" },
	});
	assert(
		noLocal.ok === false &&
			noLocal.error === "ERR_PACKAGE_START_LOCAL_FILE_REQUIRED",
		"start asset without local_file_path must fail closed",
	);
	// local_file_path (snake_case) is also accepted.
	assert(
		validateF2VPackageUploadOnlyJob({
			...goodJob,
			startAsset: { local_file_path: "C:\\tmp\\start.png" },
		}).ok === true,
		"snake_case local_file_path must be accepted",
	);
	// Each missing required field fails closed with ERR_PACKAGE_REQUIRED.
	for (const drop of [
		"request_id",
		"workspace_execution_package_id",
		"prompt",
		"startAsset",
	]) {
		const j = { ...goodJob };
		delete j[drop];
		const r = validateF2VPackageUploadOnlyJob(j);
		assert(
			r.ok === false && r.error === "ERR_PACKAGE_REQUIRED",
			`missing ${drop} must fail closed with ERR_PACKAGE_REQUIRED`,
		);
	}
	// Wrong mode must fail closed (lane is F2V-only).
	assert(
		validateF2VPackageUploadOnlyJob({ ...goodJob, mode: "I2V" }).ok === false,
		"non-F2V mode must fail closed",
	);
}

function testCdpDispatchGate(shouldUseF2VCdpUpload) {
	assert(
		shouldUseF2VCdpUpload({ startAsset: { localFilePath: "C:\\tmp\\hero.png" } }, "C:\\tmp\\hero.png") === true,
		"resolvable asset must default to CDP upload",
	);
	assert(
		shouldUseF2VCdpUpload({ product_id: "prod_123" }, "prod_123") === true,
		"product_id fallback must default to CDP upload",
	);
	assert(
		shouldUseF2VCdpUpload({ startAsset: { localFilePath: "C:\\tmp\\hero.png" }, skipUpload: true }, "C:\\tmp\\hero.png") === false,
		"skipUpload=true must disable CDP upload",
	);
	assert(
		shouldUseF2VCdpUpload({ startAsset: { localFilePath: "C:\\tmp\\hero.png" }, use_cdp_upload: false }, "C:\\tmp\\hero.png") === false,
		"explicit opt-out must disable CDP upload",
	);
	assert(
		shouldUseF2VCdpUpload({ use_cdp_upload: true }, null) === true,
		"explicit opt-in must preserve the CDP lane",
	);
	assert(
		shouldUseF2VCdpUpload({}, null) === false,
		"jobs without upload assets must not be forced onto CDP upload",
	);
}

function testDomFallbackAssetResolution(resolveF2VDomFallbackAssetSource) {
	const previewAsset = resolveF2VDomFallbackAssetSource({
		startAsset: {
			previewUrl: "data:image/png;base64,abc",
			localFilePath: "C:\\tmp\\hero.png",
			fileName: "hero.png",
		},
	});
	assert(
		previewAsset &&
			previewAsset.previewUrl === "data:image/png;base64,abc" &&
			previewAsset.fileName === "hero.png",
		"DOM fallback must prefer previewUrl payload over localFilePath",
	);
	assert(
		resolveF2VDomFallbackAssetSource({
			startAsset: { downloadUrl: "https://cdn.example/hero.png", fileName: "hero.png" },
		}).previewUrl === "https://cdn.example/hero.png",
		"downloadUrl must be normalized into a previewUrl payload for DOM fallback",
	);
	assert(
		resolveF2VDomFallbackAssetSource({ product_id: "prod_123" }) === "prod_123",
		"product_id fallback must stay usable for DOM upload recovery",
	);
	assert(
		resolveF2VDomFallbackAssetSource({
			startAsset: { localFilePath: "C:\\tmp\\hero.png" },
		}) === null,
		"bare localFilePath cannot be reused by the DOM fallback lane",
	);
}

function testStaticDispatchWiring(source) {
	assert(
		source.includes("const f2vWantsCdpUpload = shouldUseF2VCdpUpload("),
		"handleExecuteFlowJob must use shouldUseF2VCdpUpload helper",
	);
	assert(
		source.includes("assetSource: f2vUploadAssetSource || req?.assetSource"),
		"CDP dispatch must override runner assetSource with authoritative job asset",
	);
	assert(
		source.includes("const f2vDomFallbackAssetSource ="),
		"handleExecuteFlowJob must resolve a DOM fallback asset source",
	);
	assert(
		source.includes("domUploadFallback:"),
		"runner deps must expose the DOM upload fallback helper",
	);
	assert(
		source.includes('type: "FLOWKIT_SIMULATE_FILE_UPLOAD"'),
		"background fallback must dispatch the targeted content upload message",
	);
	assert(
		source.includes('"[FlowAgent] F2V upload lane:"'),
		"dispatch must emit the F2V upload lane log line",
	);
	assert(
		source.includes("skipUpload: job?.skipUpload === true"),
		"manual F2V dispatch must forward skipUpload to the runner",
	);
	assert(
		source.includes("skipGenerate: job?.skipGenerate === true"),
		"manual F2V dispatch must forward skipGenerate to the runner",
	);
	assert(
		source.includes("const canFastTrackSelectedEditor ="),
		"target resolution must fast-track a healthy non-root editor tab before broad probing",
	);
	assert(
		source.includes("const fastDiagnostic = await pingFlowDomScript(selectedTab);"),
		"fast-track editor selection must verify content health before execution",
	);
	assert(
		source.includes("const preferredProbeTab ="),
		"resolver must not prepend a root tab when non-root editor probes are available",
	);
	assert(
		source.includes("settledTab?.id && isProjectEditorUrl(settledTab?.url)"),
		"newProjectFn must reject settled root tabs that never reached a project editor URL",
	);
	assert(
		source.includes("resolveExistingProjectEditorAuthority(") &&
			source.includes('open_strategy: "already_on_editor_authority"'),
		"newProjectFn must reuse a live current project editor as authority before opening another project",
	);
	assert(
		source.includes("ok: Boolean(openFlowResult?.ok && settledProbe?.ok)"),
		"newProjectFn must only pass when the settled editor probe succeeds",
	);
	assert(
		source.includes('const strictActiveBinding =') &&
			source.includes('String(job?.mode || "").trim().toUpperCase() === "F2V"'),
		"F2V execution must enable strict active-tab binding",
	);
	assert(
		source.includes('reason: "active_flow_tab_preflight_failed"'),
		"target resolution must fail closed when active-tab preflight fails",
	);
	assert(
		source.includes("const allowProjectOpenRecovery = options?.allowProjectOpenRecovery === true;") &&
			source.includes("const allowFreshProjectRecovery = options?.allowFreshProjectRecovery === true;"),
		"diagnostic gates must keep project-open recovery opt-in instead of auto-opening by default",
	);
	assert(
		source.includes("allowProjectOpenRecovery: attemptOpenProject === true") &&
			source.includes("allowFreshProjectRecovery: attemptOpenProject === true"),
		"runtime self-test must be the only path that explicitly opts diagnostic recovery back in",
	);
	assert(
		source.includes("active_tab_preflight: activeTabPreflight?.preflight || null"),
		"runtime self-test must expose the active-tab preflight payload",
	);
	assert(
		source.includes('msg.method === "BOOTSTRAP_FLOW_PROJECT_EDITOR"') &&
			source.includes("handleBootstrapFlowProjectEditor(msg.params?.mode)"),
		"background websocket dispatcher must expose the B.2A.0 bootstrap method",
	);
	assert(
		source.includes('msg.type === "BOOTSTRAP_FLOW_PROJECT_EDITOR"') &&
			source.includes("return await handleBootstrapFlowProjectEditor(msg.mode);"),
		"runtime message dispatcher must expose the B.2A.0 bootstrap method",
	);
	assert(
		source.includes("async function bootstrapFlowProjectEditorForB2A0("),
		"background must define a dedicated B.2A.0 bootstrap orchestrator",
	);
	assert(
		source.includes("recoverStrictActiveFlowTabTarget(") &&
			source.includes("focus_recovery_succeeded") &&
			source.includes("bootstrap_recovery_succeeded"),
		"strict F2V target resolution must attempt inactive-editor focus recovery before failing closed",
	);
}

function testF2VEditorProbeGate(isActualFlowEditorProbe) {
	assert(
		isActualFlowEditorProbe(
			{
				ok: true,
				flow_tab_found: true,
				signed_in_likely: true,
				current_mode_visible: "Video/Frames",
				observed: { visibleUploadSlots: ["Start", "End"] },
			},
			"F2V",
		) === true,
		"real Frames editor must pass the F2V probe gate",
	);
	assert(
		isActualFlowEditorProbe(
			{
				ok: true,
				flow_tab_found: true,
				signed_in_likely: true,
				current_mode_visible: "UNKNOWN",
				observed: { visibleUploadSlots: [] },
			},
			"F2V",
		) === false,
		"generic Flow root composer must not pass as an F2V editor",
	);
}

function testUniqueFlowProbeCandidates(buildUniqueFlowProbeCandidates) {
	const tabs = [
		{ id: 10, url: "https://labs.google/fx/tools/flow", title: "Flow Root" },
		{ id: 11, url: "https://labs.google/fx/tools/flow/project/a", title: "Editor A" },
		{
			id: 12,
			url: "https://labs.google/fx/tools/flow/project/a?dup=1",
			title: "Editor A Duplicate",
			active: true,
			status: "complete",
		},
		{ id: 13, url: "https://labs.google/fx/tools/flow/project/b", title: "Editor B" },
	];
	const ordered = buildUniqueFlowProbeCandidates(tabs, tabs[0]);
	assert(
		Array.isArray(ordered) && ordered.map((tab) => tab.id).join(",") === "10,12,13",
		"probe candidates must prefer the active duplicate editor tab for the same project URL",
	);
}

function testSelectBestFlowTabPrefersActiveDuplicate(
	selectBestFlowTab,
	normalizeFlowProjectUrl,
) {
	const preferredUrl = "https://labs.google/fx/tools/flow/project/e941c015-0221-4316-a135-d04cf3d7862a";
	const tabs = [
		{
			id: 873075507,
			url: `${preferredUrl}?usp=stale`,
			title: "Google Flow - Jun 25, 11:56 PM",
			active: false,
			status: "complete",
		},
		{
			id: 873075578,
			url: preferredUrl,
			title: "Google Flow - Jun 25, 11:56 PM",
			active: true,
			status: "complete",
		},
	];
	assert(
		normalizeFlowProjectUrl(tabs[0].url) === normalizeFlowProjectUrl(preferredUrl),
		"duplicate editor test requires matching normalized project URLs",
	);
	assert(
		selectBestFlowTab(tabs, preferredUrl)?.id === 873075578,
		"active editor tab in the focused window must win over a stale inactive duplicate",
	);
}

function testStaleSelectedTabRebind(buildFlowTabSelectionBinding) {
	const preferredUrl = "https://labs.google/fx/tools/flow/project/e941c015-0221-4316-a135-d04cf3d7862a";
	const staleTab = {
		id: 873075507,
		url: `${preferredUrl}?usp=stale`,
		title: "Google Flow - Jun 25, 11:56 PM",
		active: false,
		status: "complete",
		windowId: 5,
	};
	const activeTab = {
		id: 873075578,
		url: preferredUrl,
		title: "Google Flow - Jun 25, 11:56 PM",
		active: true,
		status: "complete",
		windowId: 5,
	};
	const binding = buildFlowTabSelectionBinding(
		[staleTab, activeTab],
		preferredUrl,
		activeTab,
		staleTab,
	);
	assert(
		binding.selectedTab?.id === 873075578 &&
			binding.activeEditorTab?.id === 873075578 &&
			binding.reboundToActiveEditorTab === true,
		"stale selected tab must be rebound to the active editor tab for the same project",
	);
}

function testNoActiveEditorTabFailsClosed(
	buildFlowTabSelectionBinding,
	evaluateActiveFlowTabPreflight,
) {
	const tabs = [
		{
			id: 200,
			url: "https://labs.google/fx/tools/flow/project/no-active",
			title: "Google Flow - inactive only",
			active: false,
			status: "complete",
		},
	];
	const binding = buildFlowTabSelectionBinding(
		tabs,
		tabs[0].url,
		{ id: 999, url: "https://example.com", active: true },
	);
	const preflight = evaluateActiveFlowTabPreflight(binding, null, null, null, "F2V");
	assert(
		preflight.ok === false &&
			preflight.error === "FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND",
		"missing active Flow editor tab must fail with FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND",
	);
}

function testActiveTabContentScriptNotReadyFailsClosed(
	buildFlowTabSelectionBinding,
	evaluateActiveFlowTabPreflight,
) {
	const activeTab = {
		id: 873075578,
		url: "https://labs.google/fx/tools/flow/project/e941c015-0221-4316-a135-d04cf3d7862a",
		title: "Google Flow - Jun 25, 11:56 PM",
		active: true,
		status: "complete",
	};
	const binding = buildFlowTabSelectionBinding([activeTab], activeTab.url, activeTab);
	const preflight = evaluateActiveFlowTabPreflight(
		binding,
		{
			content_script_loaded: false,
			content_script_alive: false,
			runtime_ready: false,
			build_match: false,
			raw_error: "ERR_NO_RECEIVER",
		},
		null,
		null,
		"F2V",
	);
	assert(
		preflight.ok === false &&
			preflight.error === "FLOW_ACTIVE_TAB_CONTENT_SCRIPT_NOT_READY",
		"active editor must fail closed when the content script is not ready",
	);
}

function testActiveTabMissingLauncherFailsClosed(
	buildFlowTabSelectionBinding,
	evaluateActiveFlowTabPreflight,
) {
	const activeTab = {
		id: 873075578,
		url: "https://labs.google/fx/tools/flow/project/e941c015-0221-4316-a135-d04cf3d7862a",
		title: "Google Flow - Jun 25, 11:56 PM",
		active: true,
		status: "complete",
	};
	const binding = buildFlowTabSelectionBinding([activeTab], activeTab.url, activeTab);
	const preflight = evaluateActiveFlowTabPreflight(
		binding,
		{
			content_script_loaded: true,
			content_script_alive: true,
			runtime_ready: true,
			build_match: true,
			content_build_id: "test-build-id",
		},
		{
			editor_capability_ready: false,
			ui_contract_v2: { editor_capability_ready: false },
			observed: { visibleUploadSlots: [] },
			blocking_modal_detected: false,
			strict_composer_ok: false,
		},
		{
			editor_capability_ready: false,
			ui_contract_v2: { editor_capability_ready: false },
			observed: { visibleUploadSlots: [] },
			blocking_modal_detected: false,
			strict_composer_ok: false,
		},
		"F2V",
	);
	assert(
		preflight.ok === false &&
			preflight.error === "FLOW_ACTIVE_TAB_ADD_MEDIA_LAUNCHER_NOT_FOUND",
		"active editor without a visible launcher must fail with FLOW_ACTIVE_TAB_ADD_MEDIA_LAUNCHER_NOT_FOUND",
	);
}

function testBrokenEditorPageRejectedAsAuthority(
	buildFlowTabSelectionBinding,
	evaluateActiveFlowTabPreflight,
) {
	// A broken Flow project page keeps a valid-looking editor URL and a clean tab
	// title, but the page renders "Something went wrong" (visible_error_markers).
	// It must NOT be accepted as runtime authority: the preflight must reject it
	// as FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND (so strict recovery looks elsewhere),
	// flag broken_target_rejected, and force safe_to_click_active_tab=false.
	const activeTab = {
		id: 873079083,
		url: "https://labs.google/fx/tools/flow/project/f959e409-64c4-4475-b967-4b4f81b36cc3",
		title: "Google Flow - AI Creative Studio for Video, Images & Custom Tools",
		active: true,
		status: "complete",
	};
	const binding = buildFlowTabSelectionBinding([activeTab], activeTab.url, activeTab);
	const preflight = evaluateActiveFlowTabPreflight(
		binding,
		{
			content_script_loaded: true,
			content_script_alive: true,
			runtime_ready: true,
			build_match: true,
			content_build_id: "test-build-id",
		},
		{
			visible_error_markers: ["Something went wrong"],
			observed: { visibleUploadSlots: [] },
			composer_found: true,
			composer_editable: true,
			editor_capability_ready: false,
		},
		null,
		"F2V",
	);
	assert(
		preflight.ok === false &&
			preflight.error === "FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND",
		"broken editor page must be rejected as authority with FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND",
	);
	assert(
		preflight.brokenTargetRejected === true &&
			preflight.preflight.broken_target_rejected === true,
		"preflight must flag broken_target_rejected",
	);
	assert(
		preflight.preflight.safe_to_click_active_tab === false,
		"a broken editor surface must never be safe to click",
	);
	assert(
		preflight.brokenTargetUrl === activeTab.url,
		"preflight must surface the rejected broken target URL as evidence",
	);
}

async function testResolveExistingProjectEditorAuthorityAcceptsLiveEditor(
	resolveExistingProjectEditorAuthority,
	sandbox,
) {
	let pageDiagnosticCalls = 0;
	sandbox.getTabSafe = async (tabId) => ({
		id: Number(tabId),
		active: true,
		url: "https://labs.google/fx/tools/flow/project/live-authority",
		title: "Live Authority Editor",
	});
	sandbox.ensureFlowDomScript = async () => {};
	sandbox.pingFlowDomScript = async () => ({
		content_script_loaded: true,
		content_script_alive: true,
		runtime_ready: true,
		build_match: true,
		content_build_id: "test-build-id",
		raw_error: null,
	});
	sandbox.sendTabMessageSafe = async (_tabId, msg) => {
		if (msg.type === "FLOW_PAGE_STATE_DIAGNOSTIC") {
			pageDiagnosticCalls += 1;
			return {
				signed_in_likely: true,
				composer_found: true,
				composer_editable: true,
				current_mode_visible: "Video/Frames",
				visible_error_markers: [],
				observed: { visibleUploadSlots: ["Start"] },
			};
		}
		return { ok: false, error: "ERR_UNEXPECTED_MESSAGE" };
	};
	const result = await resolveExistingProjectEditorAuthority(
		{
			id: 991,
			active: true,
			url: "https://labs.google/fx/tools/flow/project/live-authority",
			title: "Live Authority Editor",
		},
		"F2V",
	);
	assert(
		result.ok === true,
		"existing live project editor must be accepted as authority even before strict launcher-readiness turns green",
	);
	assert(
		pageDiagnosticCalls === 1,
		"existing-editor authority must collect page diagnostic evidence before reusing the current tab",
	);
}

async function testResolveExistingProjectEditorAuthorityRejectsBrokenEditor(
	resolveExistingProjectEditorAuthority,
	sandbox,
) {
	sandbox.getTabSafe = async (tabId) => ({
		id: Number(tabId),
		active: true,
		url: "https://labs.google/fx/tools/flow/project/broken-authority",
		title: "Broken Authority Editor",
	});
	sandbox.ensureFlowDomScript = async () => {};
	sandbox.pingFlowDomScript = async () => ({
		content_script_loaded: true,
		content_script_alive: true,
		runtime_ready: true,
		build_match: true,
		content_build_id: "test-build-id",
		raw_error: null,
	});
	sandbox.sendTabMessageSafe = async () => ({
		signed_in_likely: true,
		composer_found: true,
		composer_editable: true,
		current_mode_visible: "Video/Frames",
		visible_error_markers: ["Something went wrong"],
	});
	const result = await resolveExistingProjectEditorAuthority(
		{
			id: 992,
			active: true,
			url: "https://labs.google/fx/tools/flow/project/broken-authority",
			title: "Broken Authority Editor",
		},
		"F2V",
	);
	assert(
		result.ok === false &&
			result.error === "FLOW_EDITOR_AUTHORITY_BROKEN",
		"existing-editor authority must reject project editors with visible error markers",
	);
}

function createBootstrapDeps(overrides = {}) {
	const rootUrl = "https://labs.google/fx/tools/flow";
	const projectUrl =
		"https://labs.google/fx/tools/flow/project/generated-project-123";
	const state = {
		flowTabs: overrides.flowTabs
			? overrides.flowTabs.map((tab) => ({ ...tab }))
			: [],
		pageDiagnostics: overrides.pageDiagnostics || {},
		preflightByTabId: overrides.preflightByTabId || {},
		probeByTabId: overrides.probeByTabId || {},
		focusedTabId: overrides.focusedTabId || null,
	};
	const api = {
		getStoredFlowProjectUrl: async () => overrides.preferredUrl || null,
		getFlowTabs: async () => state.flowTabs.map((tab) => ({ ...tab })),
		getFocusedActiveBrowserTab: async () => {
			if (state.focusedTabId != null) {
				return state.flowTabs.find((tab) => tab.id === state.focusedTabId) || null;
			}
			return state.flowTabs.find((tab) => tab.active) || null;
		},
		getFlowTab: async () =>
			state.flowTabs.find((tab) => tab.active) || state.flowTabs[0] || null,
		getTabSafe: async (tabId) =>
			state.flowTabs.find((tab) => Number(tab.id) === Number(tabId)) || null,
		focusTab: async (tab) => {
			state.flowTabs = state.flowTabs.map((item) => ({
				...item,
				active: Number(item.id) === Number(tab.id),
			}));
			state.focusedTabId = Number(tab.id);
			return state.flowTabs.find((item) => Number(item.id) === Number(tab.id)) || tab;
		},
		openTabInNormalWindow: async (url) => {
			const rootTab = {
				id: 101,
				windowId: 1,
				active: true,
				status: "complete",
				url,
				title: "Google Flow Root",
			};
			state.flowTabs = [rootTab];
			state.focusedTabId = rootTab.id;
			return rootTab;
		},
		waitForTabComplete: async (tabId) =>
			state.flowTabs.find((tab) => Number(tab.id) === Number(tabId)) || null,
		ensureFlowDomScript: async () => {},
		pingFlowDomScript: async (tab) =>
			overrides.pingByTabId?.[tab.id] || {
				content_script_loaded: true,
				content_script_alive: true,
				runtime_ready: true,
				build_match: true,
				content_build_id: "test-build-id",
				raw_error: null,
			},
		sendTabMessageSafe: async (tabId, msg) => {
			if (msg.type === "FLOW_PAGE_STATE_DIAGNOSTIC") {
				return (
					state.pageDiagnostics[tabId] || {
						flow_url:
							state.flowTabs.find((tab) => Number(tab.id) === Number(tabId))?.url ||
							rootUrl,
						visible_login_markers: [],
					}
				);
			}
			if (msg.type === "CHECK_FLOW_COMPOSER_READY") {
				return (
					overrides.composerDiagnosticsByTabId?.[tabId] || {
						ok: true,
						flow_tab_found: true,
						signed_in_likely: true,
						current_mode_visible: "Video/Frames",
						observed: { visibleUploadSlots: ["Start", "End"] },
					}
				);
			}
			return { ok: false, error: "ERR_UNKNOWN_MESSAGE_TYPE" };
		},
		buildActiveFlowTabPreflight: async (_mode, options = {}) => {
			const selectedTab =
				options.selectedTabOverride ||
				state.flowTabs.find((tab) => tab.active) ||
				state.flowTabs[0] ||
				null;
			if (
				selectedTab?.id != null &&
				state.preflightByTabId[selectedTab.id] != null
			) {
				return state.preflightByTabId[selectedTab.id];
			}
			return {
				ok: true,
				preflight: {
					selected_tab_id: selectedTab?.id || 0,
					active_editor_tab_id: selectedTab?.id || 0,
					selected_tab_active: Boolean(selectedTab?.active),
					same_project_url: true,
					content_script_alive_on_active_tab: true,
					safe_to_click_active_tab: true,
				},
				selectedTab: selectedTab || null,
				selectedTabUrl: selectedTab?.url || null,
				activeEditorTab: selectedTab || null,
				activeEditorTabUrl: selectedTab?.url || null,
				reboundToActiveEditorTab: false,
			};
		},
		probeFlowEditorCandidate: async (tab) =>
			state.probeByTabId[tab.id] || {
				ok: true,
				tab,
				readiness: { ok: true },
				diagnostic: { raw_error: null },
			},
		handleOpenFlowNewProject: async () => {
			if (typeof overrides.handleOpenFlowNewProject === "function") {
				return await overrides.handleOpenFlowNewProject(state);
			}
			const projectTab = {
				id: 202,
				windowId: 1,
				active: true,
				status: "complete",
				url: projectUrl,
				title: "Google Flow Project",
			};
			state.flowTabs = [projectTab];
			state.focusedTabId = projectTab.id;
			return {
				ok: true,
				open_flow_root: true,
				project_list_or_landing_detected: true,
				new_project_clicked: true,
				editor_ready: true,
				flow_tab_id: projectTab.id,
				flow_url_after: projectTab.url,
				flow_url: projectTab.url,
			};
		},
		settleFlowProjectAfterOpen: async (openFlowResult) => {
			if (typeof overrides.settleFlowProjectAfterOpen === "function") {
				return await overrides.settleFlowProjectAfterOpen(openFlowResult, state);
			}
			return (
				state.flowTabs.find((tab) => Number(tab.id) === Number(openFlowResult?.flow_tab_id)) ||
				state.flowTabs.find((tab) => tab.active) ||
				state.flowTabs[0] ||
				null
			);
		},
		classifyAuthStateFromDiagnostic: (_url, diagnostic) =>
			Array.isArray(diagnostic?.visible_login_markers) &&
			diagnostic.visible_login_markers.length > 0
				? "AUTH_REQUIRED"
				: "LIKELY_AUTHENTICATED",
	};
	return api;
}

async function testBootstrapOpensFlowRootAndCreatesProject(
	bootstrapFlowProjectEditorForB2A0,
) {
	const result = await bootstrapFlowProjectEditorForB2A0(
		"F2V",
		createBootstrapDeps(),
	);
	assert(result.ok === true, "no Flow tab bootstrap must succeed");
	assert(result.started_from === "NO_FLOW_TAB", "bootstrap must classify no-tab start");
	assert(result.created_new_project === true, "bootstrap must mark new project creation");
	assert(
		JSON.stringify(result.stages) ===
			JSON.stringify([
				"F2V_V2A0_FLOW_ENTRY_OPENED_OR_FOUND",
				"F2V_V2A0_FLOW_AUTHENTICATED",
				"F2V_V2A0_ROOT_PAGE_DETECTED_OR_SKIPPED",
				"F2V_V2A0_CREATE_PROJECT_CONTROL_FOUND",
				"F2V_V2A0_CREATE_PROJECT_CLICKED",
				"F2V_V2A0_PROJECT_EDITOR_URL_CONFIRMED",
				"F2V_V2A0_PROJECT_EDITOR_TAB_BOUND",
				"F2V_V2A0_CONTENT_SCRIPT_READY",
				"F2V_V2A0_EDITOR_SURFACE_READY",
				"F2V_V2A0_STOPPED_BEFORE_ADD_MEDIA",
			]),
		"no Flow tab bootstrap must emit the full B.2A.0 stage sequence",
	);
	assert(
		result.safe_to_run_b2a === true && result.stopped_before_add_media === true,
		"B.2A.0 bootstrap must stop before Add Media while leaving B.2A safe to run",
	);
}

async function testBootstrapCreatesProjectFromRootFlowPage(
	bootstrapFlowProjectEditorForB2A0,
) {
	const result = await bootstrapFlowProjectEditorForB2A0(
		"F2V",
		createBootstrapDeps({
			flowTabs: [
				{
					id: 111,
					windowId: 1,
					active: true,
					status: "complete",
					url: "https://labs.google/fx/tools/flow",
					title: "Google Flow Root",
				},
			],
			focusedTabId: 111,
			pageDiagnostics: {
				111: {
					flow_url: "https://labs.google/fx/tools/flow",
					visible_login_markers: [],
				},
			},
		}),
	);
	assert(result.ok === true, "root Flow page bootstrap must succeed");
	assert(
		result.started_from === "ROOT_FLOW_PAGE",
		"bootstrap must classify root page start",
	);
}

async function testBootstrapBindsExistingProjectEditor(
	bootstrapFlowProjectEditorForB2A0,
) {
	const result = await bootstrapFlowProjectEditorForB2A0(
		"F2V",
		createBootstrapDeps({
			flowTabs: [
				{
					id: 210,
					windowId: 3,
					active: true,
					status: "complete",
					url: "https://labs.google/fx/tools/flow/project/existing-editor",
					title: "Existing Editor",
				},
			],
			focusedTabId: 210,
		}),
	);
	assert(result.ok === true, "existing project editor bootstrap must succeed");
	assert(
		JSON.stringify(result.stages) ===
			JSON.stringify([
				"F2V_V2A0_EXISTING_PROJECT_EDITOR_FOUND",
				"F2V_V2A0_PROJECT_EDITOR_TAB_BOUND",
				"F2V_V2A0_CONTENT_SCRIPT_READY",
				"F2V_V2A0_EDITOR_SURFACE_READY",
				"F2V_V2A0_STOPPED_BEFORE_ADD_MEDIA",
			]),
		"existing editor bootstrap must use the shortcut stage sequence",
	);
	assert(result.created_new_project === false, "existing editor path must not create a project");
}

async function testBootstrapFocusesMostRecentUsableInactiveEditor(
	bootstrapFlowProjectEditorForB2A0,
) {
	const result = await bootstrapFlowProjectEditorForB2A0(
		"F2V",
		createBootstrapDeps({
			flowTabs: [
				{
					id: 220,
					windowId: 4,
					active: false,
					status: "complete",
					url: "https://labs.google/fx/tools/flow/project/older-editor",
					title: "Older Editor",
				},
				{
					id: 330,
					windowId: 4,
					active: false,
					status: "complete",
					url: "https://labs.google/fx/tools/flow/project/newer-editor",
					title: "Newer Editor",
				},
			],
			probeByTabId: {
				220: { ok: true, readiness: { ok: true }, diagnostic: { raw_error: null } },
				330: { ok: true, readiness: { ok: true }, diagnostic: { raw_error: null } },
			},
		}),
	);
	assert(result.ok === true, "usable inactive editor bootstrap must succeed");
	assert(
		result.selected_tab_id_after === 330,
		"bootstrap must focus and bind the most recent usable inactive editor tab",
	);
}

async function testBootstrapDuplicateTabsPreferFocusedActiveEditor(
	bootstrapFlowProjectEditorForB2A0,
) {
	const result = await bootstrapFlowProjectEditorForB2A0(
		"F2V",
		createBootstrapDeps({
			flowTabs: [
				{
					id: 440,
					windowId: 7,
					active: true,
					status: "complete",
					url: "https://labs.google/fx/tools/flow/project/shared-editor",
					title: "Shared Editor Active",
				},
				{
					id: 441,
					windowId: 7,
					active: false,
					status: "complete",
					url: "https://labs.google/fx/tools/flow/project/shared-editor",
					title: "Shared Editor Duplicate",
				},
			],
			focusedTabId: 440,
		}),
	);
	assert(result.ok === true, "duplicate editor bootstrap must succeed");
	assert(
		result.selected_tab_id_after === 440,
		"bootstrap must prefer the active/focused duplicate project editor tab",
	);
}

async function testBootstrapFailsWhenLoginRequired(
	bootstrapFlowProjectEditorForB2A0,
) {
	const result = await bootstrapFlowProjectEditorForB2A0(
		"F2V",
		createBootstrapDeps({
			flowTabs: [
				{
					id: 510,
					windowId: 1,
					active: true,
					status: "complete",
					url: "https://labs.google/fx/tools/flow",
					title: "Google Flow Login",
				},
			],
			focusedTabId: 510,
			pageDiagnostics: {
				510: {
					flow_url: "https://accounts.google.com/signin",
					visible_login_markers: ["Sign in"],
				},
			},
		}),
	);
	assert(
		result.ok === false && result.error === "FLOW_LOGIN_REQUIRED",
		"unauthenticated bootstrap must fail with FLOW_LOGIN_REQUIRED",
	);
}

async function testBootstrapFailsOnProjectUrlTimeout(
	bootstrapFlowProjectEditorForB2A0,
) {
	const result = await bootstrapFlowProjectEditorForB2A0(
		"F2V",
		createBootstrapDeps({
			handleOpenFlowNewProject: async (state) => {
				const rootTab = {
					id: 611,
					windowId: 1,
					active: true,
					status: "complete",
					url: "https://labs.google/fx/tools/flow",
					title: "Google Flow Root",
				};
				state.flowTabs = [rootTab];
				return {
					ok: true,
					project_list_or_landing_detected: true,
					new_project_clicked: true,
					editor_ready: false,
					flow_tab_id: rootTab.id,
					flow_url_after: rootTab.url,
					flow_url: rootTab.url,
				};
			},
		}),
	);
	assert(
		result.ok === false && result.error === "FLOW_PROJECT_EDITOR_URL_TIMEOUT",
		"bootstrap must fail with FLOW_PROJECT_EDITOR_URL_TIMEOUT when project URL never appears",
	);
}

async function testBootstrapFailsWhenContentScriptIsMissing(
	bootstrapFlowProjectEditorForB2A0,
) {
	const result = await bootstrapFlowProjectEditorForB2A0(
		"F2V",
		createBootstrapDeps({
			flowTabs: [
				{
					id: 710,
					windowId: 1,
					active: true,
					status: "complete",
					url: "https://labs.google/fx/tools/flow/project/content-missing",
					title: "Content Missing",
				},
			],
			focusedTabId: 710,
			preflightByTabId: {
				710: {
					ok: false,
					error: "FLOW_ACTIVE_TAB_CONTENT_SCRIPT_NOT_READY",
					preflight: {
						selected_tab_id: 710,
						active_editor_tab_id: 710,
						selected_tab_active: true,
						same_project_url: true,
						content_script_alive_on_active_tab: false,
						safe_to_click_active_tab: false,
					},
					selectedTab: {
						id: 710,
						active: true,
						url: "https://labs.google/fx/tools/flow/project/content-missing",
					},
					selectedTabUrl:
						"https://labs.google/fx/tools/flow/project/content-missing",
				},
			},
		}),
	);
	assert(
		result.ok === false && result.error === "FLOW_PROJECT_CONTENT_SCRIPT_NOT_READY",
		"bootstrap must map active-tab content failure to FLOW_PROJECT_CONTENT_SCRIPT_NOT_READY",
	);
}

async function testBootstrapFailsWhenEditorSurfaceIsMissing(
	bootstrapFlowProjectEditorForB2A0,
) {
	const result = await bootstrapFlowProjectEditorForB2A0(
		"F2V",
		createBootstrapDeps({
			flowTabs: [
				{
					id: 810,
					windowId: 1,
					active: true,
					status: "complete",
					url: "https://labs.google/fx/tools/flow/project/editor-surface-missing",
					title: "Editor Surface Missing",
				},
			],
			focusedTabId: 810,
			preflightByTabId: {
				810: {
					ok: false,
					error: "FLOW_ACTIVE_TAB_ADD_MEDIA_LAUNCHER_NOT_FOUND",
					preflight: {
						selected_tab_id: 810,
						active_editor_tab_id: 810,
						selected_tab_active: true,
						same_project_url: true,
						content_script_alive_on_active_tab: true,
						safe_to_click_active_tab: false,
					},
					selectedTab: {
						id: 810,
						active: true,
						url: "https://labs.google/fx/tools/flow/project/editor-surface-missing",
					},
					selectedTabUrl:
						"https://labs.google/fx/tools/flow/project/editor-surface-missing",
				},
			},
		}),
	);
	assert(
		result.ok === false && result.error === "FLOW_PROJECT_EDITOR_SURFACE_NOT_READY",
		"bootstrap must map missing editor surface to FLOW_PROJECT_EDITOR_SURFACE_NOT_READY",
	);
}

async function testStrictRecoveryFocusesUsableInactiveEditor(
	recoverStrictActiveFlowTabTarget,
) {
	const deps = createBootstrapDeps({
		flowTabs: [
			{
				id: 910,
				windowId: 9,
				active: false,
				status: "complete",
				url: "https://labs.google/fx/tools/flow/project/inactive-older",
				title: "Inactive Older Editor",
			},
			{
				id: 911,
				windowId: 9,
				active: false,
				status: "complete",
				url: "https://labs.google/fx/tools/flow/project/inactive-newer",
				title: "Inactive Newer Editor",
			},
		],
		probeByTabId: {
			911: { ok: true, readiness: { ok: true }, diagnostic: { raw_error: null } },
		},
	});
	deps.buildActiveFlowTabPreflight = async (_mode, options = {}) => {
		const currentTabs = await deps.getFlowTabs();
		const activeTab =
			options.selectedTabOverride ||
			currentTabs.find((tab) => tab.active) ||
			null;
		if (!activeTab) {
			return {
				ok: false,
				error: "FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND",
				preflight: {
					selected_tab_id: currentTabs[0]?.id || 0,
					active_editor_tab_id: 0,
					selected_tab_active: false,
					same_project_url: false,
					content_script_alive_on_active_tab: true,
					safe_to_click_active_tab: false,
				},
				selectedTab: currentTabs[0] || null,
				selectedTabUrl: currentTabs[0]?.url || null,
				activeEditorTab: null,
				activeEditorTabUrl: null,
				reboundToActiveEditorTab: false,
			};
		}
		return {
			ok: true,
			preflight: {
				selected_tab_id: activeTab.id,
				active_editor_tab_id: activeTab.id,
				selected_tab_active: true,
				same_project_url: true,
				content_script_alive_on_active_tab: true,
				safe_to_click_active_tab: true,
			},
			selectedTab: activeTab,
			selectedTabUrl: activeTab.url,
			activeEditorTab: activeTab,
			activeEditorTabUrl: activeTab.url,
			reboundToActiveEditorTab: false,
		};
	};
	const result = await recoverStrictActiveFlowTabTarget(
		"F2V",
		{
			preferredUrl:
				"https://labs.google/fx/tools/flow/project/inactive-newer",
			tabs: await deps.getFlowTabs(),
		},
		deps,
	);
	assert(result.ok === true, "strict recovery must succeed when a usable inactive editor exists");
	assert(
		result.focus_recovery_attempted === true &&
			result.focus_recovery_succeeded === true &&
			result.focused_editor_tab_id === 911,
		"strict recovery must focus the preferred usable inactive editor tab",
	);
	assert(
		result.activeTabPreflight?.preflight?.selected_tab_id === 911 &&
			result.activeTabPreflight?.preflight?.active_editor_tab_id === 911,
		"strict recovery must return the focused active editor as the bound target",
	);
}

async function testStrictRecoveryFocusesAliveInactiveEditorBeforeBootstrap(
	recoverStrictActiveFlowTabTarget,
) {
	let openProjectCalls = 0;
	const deps = createBootstrapDeps({
		flowTabs: [
			{
				id: 912,
				windowId: 9,
				active: false,
				status: "complete",
				url: "https://labs.google/fx/tools/flow/project/inactive-alive-not-green",
				title: "Inactive Alive Editor",
			},
		],
		probeByTabId: {
			912: {
				ok: false,
				readiness: {
					ok: false,
					error: "FLOW_ACTIVE_TAB_ADD_MEDIA_LAUNCHER_NOT_FOUND",
				},
				diagnostic: {
					content_script_loaded: true,
					content_script_alive: true,
					runtime_ready: true,
					build_match: true,
					content_build_id: "test-build-id",
					raw_error: null,
				},
			},
		},
	});
	let preflightCalls = 0;
	deps.buildActiveFlowTabPreflight = async (_mode, options = {}) => {
		const currentTabs = await deps.getFlowTabs();
		const activeTab =
			options.selectedTabOverride ||
			currentTabs.find((tab) => tab.active) ||
			null;
		preflightCalls += 1;
		if (preflightCalls === 1 || !activeTab) {
			return {
				ok: false,
				error: "FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND",
				preflight: {
					selected_tab_id: currentTabs[0]?.id || 0,
					active_editor_tab_id: 0,
					selected_tab_active: false,
					same_project_url: false,
					content_script_alive_on_active_tab: true,
					safe_to_click_active_tab: false,
				},
				selectedTab: currentTabs[0] || null,
				selectedTabUrl: currentTabs[0]?.url || null,
				activeEditorTab: null,
				activeEditorTabUrl: null,
				reboundToActiveEditorTab: false,
			};
		}
		return {
			ok: true,
			preflight: {
				selected_tab_id: activeTab.id,
				active_editor_tab_id: activeTab.id,
				selected_tab_active: true,
				same_project_url: true,
				content_script_alive_on_active_tab: true,
				safe_to_click_active_tab: true,
			},
			selectedTab: activeTab,
			selectedTabUrl: activeTab.url,
			activeEditorTab: activeTab,
			activeEditorTabUrl: activeTab.url,
			reboundToActiveEditorTab: false,
		};
	};
	deps.openFlowProjectFn = async () => {
		openProjectCalls += 1;
		return {
			ok: true,
			flow_tab_id: 999,
			flow_url: "https://labs.google/fx/tools/flow/project/should-not-open",
		};
	};
	const result = await recoverStrictActiveFlowTabTarget(
		"F2V",
		{
			preferredUrl:
				"https://labs.google/fx/tools/flow/project/inactive-alive-not-green",
			tabs: await deps.getFlowTabs(),
		},
		deps,
	);
	assert(
		openProjectCalls === 0,
		"strict recovery must not bootstrap when an inactive editor is alive enough to refocus",
	);
	assert(
		result.ok === true &&
			result.focus_recovery_attempted === true &&
			result.focus_recovery_succeeded === true &&
			result.focused_editor_tab_id === 912,
		"strict recovery must focus an alive inactive editor before considering bootstrap",
	);
}

async function testStrictRecoveryFailsClosedWhenNoUsableEditor(
	recoverStrictActiveFlowTabTarget,
) {
	const deps = createBootstrapDeps({
		flowTabs: [
			{
				id: 920,
				windowId: 9,
				active: false,
				status: "complete",
				url: "https://labs.google/fx/tools/flow/project/inactive-unusable",
				title: "Inactive Unusable Editor",
			},
		],
		probeByTabId: {
			920: { ok: false, readiness: { ok: false }, diagnostic: { raw_error: "ERR_NO_RECEIVER" } },
		},
	});
	deps.buildActiveFlowTabPreflight = async () => ({
		ok: false,
		error: "FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND",
		preflight: {
			selected_tab_id: 920,
			active_editor_tab_id: 0,
			selected_tab_active: false,
			same_project_url: false,
			content_script_alive_on_active_tab: true,
			safe_to_click_active_tab: false,
		},
		selectedTab: {
			id: 920,
			active: false,
			url: "https://labs.google/fx/tools/flow/project/inactive-unusable",
		},
		selectedTabUrl:
			"https://labs.google/fx/tools/flow/project/inactive-unusable",
		activeEditorTab: null,
		activeEditorTabUrl: null,
		reboundToActiveEditorTab: false,
	});
	const result = await recoverStrictActiveFlowTabTarget(
		"F2V",
		{
			preferredUrl:
				"https://labs.google/fx/tools/flow/project/inactive-unusable",
			tabs: await deps.getFlowTabs(),
		},
		deps,
	);
	assert(
		result.ok === false &&
			result.activeTabPreflight?.error === "FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND",
		"strict recovery must remain fail-closed when no usable inactive editor can be promoted",
	);
	assert(
		result.focus_recovery_attempted === true &&
			result.focus_recovery_succeeded === false,
		"strict recovery must report that focus recovery was attempted but failed",
	);
}

async function testStrictRecoveryReadOnlyDoesNotBootstrapFromRootPage(
	recoverStrictActiveFlowTabTarget,
) {
	let openProjectCalls = 0;
	const state = {
		flowTabs: [
			{
				id: 935,
				windowId: 11,
				active: false,
				status: "complete",
				url: "https://labs.google/fx/tools/flow",
				title: "Google Flow Root",
			},
		],
	};
	const deps = {
		getFlowTabs: async () => state.flowTabs.map((tab) => ({ ...tab })),
		getTabSafe: async (tabId) =>
			state.flowTabs.find((tab) => Number(tab.id) === Number(tabId)) || null,
		focusTab: async (tab) => {
			state.flowTabs = state.flowTabs.map((item) => ({
				...item,
				active: Number(item.id) === Number(tab.id),
			}));
			return state.flowTabs.find((item) => Number(item.id) === Number(tab.id)) || tab;
		},
		waitForTabComplete: async (tabId) =>
			state.flowTabs.find((tab) => Number(tab.id) === Number(tabId)) || null,
		probeFlowEditorCandidate: async () => ({
			ok: false,
			readiness: { ok: false },
			diagnostic: { raw_error: "ERR_NO_RECEIVER" },
		}),
	};
	deps.buildActiveFlowTabPreflight = async () => ({
		ok: false,
		error: "FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND",
		preflight: {
			selected_tab_id: 935,
			active_editor_tab_id: 0,
			selected_tab_active: false,
			same_project_url: false,
			content_script_alive_on_active_tab: true,
			safe_to_click_active_tab: false,
		},
		selectedTab: {
			id: 935,
			active: false,
			url: "https://labs.google/fx/tools/flow",
		},
		selectedTabUrl: "https://labs.google/fx/tools/flow",
		activeEditorTab: null,
		activeEditorTabUrl: null,
		reboundToActiveEditorTab: false,
	});
	deps.openFlowProjectFn = async () => {
		openProjectCalls += 1;
		return {
			ok: true,
			flow_tab_id: 936,
			flow_url: "https://labs.google/fx/tools/flow/project/should-not-open",
		};
	};
	const result = await recoverStrictActiveFlowTabTarget(
		"F2V",
		{
			preferredUrl: "https://labs.google/fx/tools/flow/project/should-not-open",
			tabs: await deps.getFlowTabs(),
			allowBootstrapRecovery: false,
		},
		deps,
	);
	assert(
		openProjectCalls === 0,
		"read-only strict recovery must not bootstrap or open a project from Flow root",
	);
	assert(
		result.ok === false &&
			result.bootstrap_recovery_attempted === false &&
			result.bootstrap_recovery_succeeded === false &&
			result.bootstrap_recovery_blocked === true,
		"read-only strict recovery must fail closed with bootstrap blocked",
	);
	assert(
		result.activeTabPreflight?.error === "FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND",
		"read-only strict recovery must preserve the original active-editor-not-found failure",
	);
}

async function testStrictRecoveryBootstrapsEditorFromRootPage(
	recoverStrictActiveFlowTabTarget,
) {
	const state = {
		flowTabs: [
			{
				id: 930,
				windowId: 11,
				active: false,
				status: "complete",
				url: "https://labs.google/fx/tools/flow",
				title: "Google Flow Root",
			},
		],
	};
	const deps = {
		getFlowTabs: async () => state.flowTabs.map((tab) => ({ ...tab })),
		getTabSafe: async (tabId) =>
			state.flowTabs.find((tab) => Number(tab.id) === Number(tabId)) || null,
		focusTab: async (tab) => {
			state.flowTabs = state.flowTabs.map((item) => ({
				...item,
				active: Number(item.id) === Number(tab.id),
			}));
			return state.flowTabs.find((item) => Number(item.id) === Number(tab.id)) || tab;
		},
		waitForTabComplete: async (tabId) =>
			state.flowTabs.find((tab) => Number(tab.id) === Number(tabId)) || null,
		probeFlowEditorCandidate: async () => ({
			ok: false,
			readiness: { ok: false },
			diagnostic: { raw_error: "ERR_NO_RECEIVER" },
		}),
	};
	deps.buildActiveFlowTabPreflight = async (_mode, options = {}) => {
		const currentTabs = await deps.getFlowTabs();
		const activeTab =
			options.selectedTabOverride ||
			currentTabs.find((tab) => tab.active) ||
			null;
		if (!activeTab || /\/tools\/flow$/i.test(String(activeTab.url || ""))) {
			return {
				ok: false,
				error: "FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND",
				preflight: {
					selected_tab_id: currentTabs[0]?.id || 0,
					active_editor_tab_id: 0,
					selected_tab_active: false,
					same_project_url: false,
					content_script_alive_on_active_tab: true,
					safe_to_click_active_tab: false,
				},
				selectedTab: currentTabs[0] || null,
				selectedTabUrl: currentTabs[0]?.url || null,
				activeEditorTab: null,
				activeEditorTabUrl: null,
				reboundToActiveEditorTab: false,
			};
		}
		return {
			ok: true,
			preflight: {
				selected_tab_id: activeTab.id,
				active_editor_tab_id: activeTab.id,
				selected_tab_active: true,
				same_project_url: true,
				content_script_alive_on_active_tab: true,
				safe_to_click_active_tab: true,
			},
			selectedTab: activeTab,
			selectedTabUrl: activeTab.url,
			activeEditorTab: activeTab,
			activeEditorTabUrl: activeTab.url,
			reboundToActiveEditorTab: false,
		};
	};
	deps.openFlowProjectFn = async () => {
		const projectTab = {
			id: 931,
			windowId: 11,
			active: true,
			status: "complete",
			url: "https://labs.google/fx/tools/flow/project/bootstrapped-editor",
			title: "Bootstrapped Editor",
		};
		state.flowTabs = [projectTab];
		return {
			ok: true,
			flow_tab_id: 931,
			flow_url: projectTab.url,
			flow_url_after: projectTab.url,
		};
	};
	deps.settleFlowProjectAfterOpen = async () => ({
		id: 931,
		windowId: 11,
		active: true,
		status: "complete",
		url: "https://labs.google/fx/tools/flow/project/bootstrapped-editor",
		title: "Bootstrapped Editor",
	});
	const result = await recoverStrictActiveFlowTabTarget(
		"F2V",
		{
			preferredUrl: "https://labs.google/fx/tools/flow/project/bootstrapped-editor",
			tabs: await deps.getFlowTabs(),
		},
		deps,
	);
	assert(
		result.ok === true &&
			result.bootstrap_recovery_attempted === true &&
			result.bootstrap_recovery_succeeded === true &&
			result.bootstrapped_editor_tab_id === 931,
		"strict recovery must bootstrap a fresh project editor when only Flow root is open",
	);
}

async function testStrictRecoverySuppressesReopenWhenEditorIsAlive(
	recoverStrictActiveFlowTabTarget,
) {
	// A live project editor is already open (probe OK) but its post-focus
	// active-tab preflight gate never turns green (e.g. launcher-readiness race).
	// Strict recovery must NOT open/create a second project — it must fail closed
	// with FLOW_PROJECT_REOPEN_LOOP and never call openFlowProjectFn.
	let openProjectCalls = 0;
	const deps = createBootstrapDeps({
		flowTabs: [
			{
				id: 940,
				windowId: 12,
				active: false,
				status: "complete",
				url: "https://labs.google/fx/tools/flow/project/live-but-not-green",
				title: "Live Editor (gate not green)",
			},
		],
		probeByTabId: {
			940: {
				ok: false,
				readiness: {
					ok: false,
					error: "FLOW_ACTIVE_TAB_ADD_MEDIA_LAUNCHER_NOT_FOUND",
				},
				diagnostic: {
					content_script_loaded: true,
					content_script_alive: true,
					runtime_ready: true,
					build_match: true,
					content_build_id: "test-build-id",
					raw_error: null,
				},
			},
		},
	});
	// Live scenario: the editor is open but in a BACKGROUND tab, so the FIRST
	// (initial) preflight returns FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND — this is the
	// only error that enters the focus-recovery + bootstrap path. After the editor
	// tab is focused, the gate STILL fails (launcher-readiness race), so every
	// subsequent preflight returns FLOW_ACTIVE_TAB_ADD_MEDIA_LAUNCHER_NOT_FOUND.
	let preflightCalls = 0;
	deps.buildActiveFlowTabPreflight = async (_mode, options = {}) => {
		const currentTabs = await deps.getFlowTabs();
		const selected =
			options.selectedTabOverride || currentTabs[0] || null;
		preflightCalls += 1;
		if (preflightCalls === 1) {
			return {
				ok: false,
				error: "FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND",
				preflight: {
					selected_tab_id: selected?.id || 0,
					active_editor_tab_id: 0,
					selected_tab_active: false,
					same_project_url: false,
					content_script_alive_on_active_tab: true,
					safe_to_click_active_tab: false,
				},
				selectedTab: selected,
				selectedTabUrl: selected?.url || null,
				activeEditorTab: null,
				activeEditorTabUrl: null,
				reboundToActiveEditorTab: false,
			};
		}
		return {
			ok: false,
			error: "FLOW_ACTIVE_TAB_ADD_MEDIA_LAUNCHER_NOT_FOUND",
			preflight: {
				selected_tab_id: selected?.id || 0,
				active_editor_tab_id: selected?.id || 0,
				selected_tab_active: true,
				same_project_url: true,
				content_script_alive_on_active_tab: true,
				safe_to_click_active_tab: false,
			},
			selectedTab: selected,
			selectedTabUrl: selected?.url || null,
			activeEditorTab: selected,
			activeEditorTabUrl: selected?.url || null,
			reboundToActiveEditorTab: false,
		};
	};
	deps.openFlowProjectFn = async () => {
		openProjectCalls += 1;
		return { ok: true, flow_tab_id: 999, flow_url: "https://labs.google/fx/tools/flow/project/should-not-open" };
	};
	const result = await recoverStrictActiveFlowTabTarget(
		"F2V",
		{
			preferredUrl:
				"https://labs.google/fx/tools/flow/project/live-but-not-green",
			tabs: await deps.getFlowTabs(),
		},
		deps,
	);
	assert(
		openProjectCalls === 0,
		"strict recovery must NOT open/create a second project when a live editor is already open",
	);
	assert(
		result.ok === false &&
			result.error === "FLOW_PROJECT_REOPEN_LOOP" &&
			result.reopen_suppressed === true,
		"strict recovery must fail closed with FLOW_PROJECT_REOPEN_LOOP when reopen is suppressed",
	);
	assert(
		result.bootstrap_recovery_attempted === false &&
			result.focus_recovery_attempted === true &&
			result.focus_recovery_succeeded === false,
		"strict recovery must record that focus was attempted and bootstrap was suppressed",
	);
	assert(
		result.activeTabPreflight?.error ===
			"FLOW_ACTIVE_TAB_ADD_MEDIA_LAUNCHER_NOT_FOUND",
		"strict recovery must surface the real underlying preflight blocker as evidence",
	);
}

async function testSettledCdpResultSurvivesCleanup() {
	const {
		cdpFileChooserProofRuns,
		cdpFileChooserProofResults,
		settleCdpFileChooserProofRun,
		waitForCdpFileChooserProof,
	} = loadCdpLifecycleHelpers();
	let resolvedPayload = null;
	cdpFileChooserProofRuns.set(7, {
		settled: false,
		resolve(payload) {
			resolvedPayload = payload;
		},
	});

	const payload = {
		ok: false,
		error: "ERR_CDP_FILE_CHOOSER_TIMEOUT",
		slotLabel: "Start",
	};
	settleCdpFileChooserProofRun(7, payload);
	await new Promise((resolve) => setTimeout(resolve, 0));

	assert(
		cdpFileChooserProofRuns.has(7) === false,
		"cleanup must remove the active run entry",
	);
	assert(
		cdpFileChooserProofResults.get(7)?.error === "ERR_CDP_FILE_CHOOSER_TIMEOUT",
		"settled payload must be cached until wait consumes it",
	);
	assert(
		resolvedPayload?.error === "ERR_CDP_FILE_CHOOSER_TIMEOUT",
		"run promise must resolve with the settled timeout payload",
	);

	const waited = await waitForCdpFileChooserProof(7);
	assert(
		waited?.error === "ERR_CDP_FILE_CHOOSER_TIMEOUT",
		"wait must return the preserved settled payload after cleanup",
	);
	assert(
		cdpFileChooserProofResults.has(7) === false,
		"wait must drain the cached settled payload",
	);
}

async function main() {
	const {
		source,
		__sandbox,
		resolveF2VUploadAssetSource,
		resolveF2VDomFallbackAssetSource,
		shouldUseF2VCdpUpload,
		isF2VPackageUploadOnly,
		validateF2VPackageUploadOnlyJob,
		normalizeFlowProjectUrl,
		selectBestFlowTab,
		buildFlowTabSelectionBinding,
		isActualFlowEditorProbe,
		buildUniqueFlowProbeCandidates,
		evaluateActiveFlowTabPreflight,
		resolveExistingProjectEditorAuthority,
		recoverStrictActiveFlowTabTarget,
		bootstrapFlowProjectEditorForB2A0,
	} = loadHelpers();
	testAssetSourceResolution(resolveF2VUploadAssetSource);
	testDomFallbackAssetResolution(resolveF2VDomFallbackAssetSource);
	testCdpDispatchGate(shouldUseF2VCdpUpload);
	testPackageUploadOnlyLaneDetection(isF2VPackageUploadOnly);
	testPackageUploadOnlyValidation(validateF2VPackageUploadOnlyJob);
	testF2VEditorProbeGate(isActualFlowEditorProbe);
	testUniqueFlowProbeCandidates(buildUniqueFlowProbeCandidates);
	testSelectBestFlowTabPrefersActiveDuplicate(
		selectBestFlowTab,
		normalizeFlowProjectUrl,
	);
	testStaleSelectedTabRebind(buildFlowTabSelectionBinding);
	testNoActiveEditorTabFailsClosed(
		buildFlowTabSelectionBinding,
		evaluateActiveFlowTabPreflight,
	);
	testActiveTabContentScriptNotReadyFailsClosed(
		buildFlowTabSelectionBinding,
		evaluateActiveFlowTabPreflight,
	);
	testActiveTabMissingLauncherFailsClosed(
		buildFlowTabSelectionBinding,
		evaluateActiveFlowTabPreflight,
	);
	testBrokenEditorPageRejectedAsAuthority(
		buildFlowTabSelectionBinding,
		evaluateActiveFlowTabPreflight,
	);
	await testResolveExistingProjectEditorAuthorityAcceptsLiveEditor(
		resolveExistingProjectEditorAuthority,
		__sandbox,
	);
	await testResolveExistingProjectEditorAuthorityRejectsBrokenEditor(
		resolveExistingProjectEditorAuthority,
		__sandbox,
	);
	await testStrictRecoveryFocusesUsableInactiveEditor(
		recoverStrictActiveFlowTabTarget,
	);
	await testStrictRecoveryFocusesAliveInactiveEditorBeforeBootstrap(
		recoverStrictActiveFlowTabTarget,
	);
	await testStrictRecoveryFailsClosedWhenNoUsableEditor(
		recoverStrictActiveFlowTabTarget,
	);
	await testStrictRecoveryReadOnlyDoesNotBootstrapFromRootPage(
		recoverStrictActiveFlowTabTarget,
	);
	await testStrictRecoveryBootstrapsEditorFromRootPage(
		recoverStrictActiveFlowTabTarget,
	);
	await testStrictRecoverySuppressesReopenWhenEditorIsAlive(
		recoverStrictActiveFlowTabTarget,
	);
	await testBootstrapOpensFlowRootAndCreatesProject(
		bootstrapFlowProjectEditorForB2A0,
	);
	await testBootstrapCreatesProjectFromRootFlowPage(
		bootstrapFlowProjectEditorForB2A0,
	);
	await testBootstrapBindsExistingProjectEditor(
		bootstrapFlowProjectEditorForB2A0,
	);
	await testBootstrapFocusesMostRecentUsableInactiveEditor(
		bootstrapFlowProjectEditorForB2A0,
	);
	await testBootstrapDuplicateTabsPreferFocusedActiveEditor(
		bootstrapFlowProjectEditorForB2A0,
	);
	await testBootstrapFailsWhenLoginRequired(
		bootstrapFlowProjectEditorForB2A0,
	);
	await testBootstrapFailsOnProjectUrlTimeout(
		bootstrapFlowProjectEditorForB2A0,
	);
	await testBootstrapFailsWhenContentScriptIsMissing(
		bootstrapFlowProjectEditorForB2A0,
	);
	await testBootstrapFailsWhenEditorSurfaceIsMissing(
		bootstrapFlowProjectEditorForB2A0,
	);
	testStaticDispatchWiring(source);
	await testSettledCdpResultSurvivesCleanup();
	console.log("PASS test-f2v-background-upload-dispatch");
}

main().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
