#!/usr/bin/env node

/**
 * Read-only provider-readiness receipt for either supported provider authority.
 *
 * This deliberately uses CDP's HTTP inspection surface rather than a browser
 * automation client.  A healthy generic CDP endpoint is not provider-ready:
 * the receipt requires the unpacked Flow Kit service worker, a real Flow
 * project editor, the extension's content-script proof, authenticated numeric
 * credits, and a backend status that correlates to the same extension/session.
 */

import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const DEFAULT_CDP_URL = "http://127.0.0.1:9222";
const DEFAULT_BOSMAX_URL = "http://127.0.0.1:8100";
const DEFAULT_PROFILE =
	"C:\\Users\\USER\\Desktop\\_bosmax_runtime\\browser_uat\\chrome-profile";
const DEFAULT_EXTENSION_PATH =
	"C:\\Users\\USER\\Desktop\\_ref_flowkit\\extension";
const PROJECT_URL_RE =
	/^https:\/\/labs\.google\/fx\/tools\/flow\/project\/[^/?#]+/i;
const FLOW_URL_RE = /^https:\/\/labs\.google\/fx\/.*\/tools\/flow/i;
const SERVICE_WORKER_URL_RE = /^chrome-extension:\/\/([^/]+)\//i;
const ACTIVE_VIDEO_STATUSES = new Set([
	"INITIAL_SUBMITTING",
	"INITIAL_POLLING",
	"INITIAL_RECOVERY_REQUIRED",
	"EXTEND_SUBMITTING",
	"EXTEND_POLLING",
	"CONCAT_SUBMITTING",
	"CONCAT_POLLING",
	"FINAL_SAVING",
	"RUNNING",
	"GENERATING",
	"IN_PROGRESS",
	"POLLING",
]);
const CREDIT_KEYS = new Set([
	"credits",
	"creditbalance",
	"availablecredits",
	"remainingcredits",
	"balance",
	"creditbalancecount",
]);

function asString(value) {
	return typeof value === "string" ? value.trim() : "";
}

function isObject(value) {
	return value !== null && typeof value === "object" && !Array.isArray(value);
}

function readJsonFile(filePath) {
	try {
		return JSON.parse(fs.readFileSync(filePath, "utf8"));
	} catch (_err) {
		return null;
	}
}

function extensionManifest(extensionPath) {
	const manifest = readJsonFile(path.join(extensionPath, "manifest.json"));
	return isObject(manifest) ? manifest : null;
}

function expectedBuildId(extensionPath) {
	try {
		const source = fs.readFileSync(path.join(extensionPath, "background.js"), "utf8");
		return source.match(/const\s+BUILD_ID\s*=\s*["']([^"']+)["']/)?.[1] || null;
	} catch (_err) {
		return null;
	}
}

function psQuote(value) {
	return `'${String(value).replaceAll("'", "''")}'`;
}

function runPowerShellJson(script) {
	try {
		const stdout = execFileSync(
			"powershell.exe",
			["-NoProfile", "-NonInteractive", "-Command", script],
			{ encoding: "utf8", timeout: 30000, windowsHide: true },
		);
		return JSON.parse(stdout.trim());
	} catch (error) {
		return { __error: String(error?.message || error).slice(0, 240) };
	}
}

function inspectUatProcess(profilePath, cdpPort) {
	const script = `
$profile = ${psQuote(profilePath)}
$portArg = ${psQuote(`--remote-debugging-port=${cdpPort}`)}
$rows = @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue | ForEach-Object {
  $cmd = [string]$_.CommandLine
  if ($cmd -and $cmd.Contains($portArg)) {
    [pscustomobject]@{
      pid = [int]$_.ProcessId
      profile_match = $cmd.Contains($profile)
      cdp_match = $true
    }
  }
})
$listeners = @(Get-NetTCPConnection -LocalPort ${cdpPort} -State Listen -ErrorAction SilentlyContinue)
$loopbackOnly = $listeners.Count -gt 0 -and @($listeners | Where-Object {
  $_.LocalAddress -ne '127.0.0.1' -and $_.LocalAddress -ne '::1'
}).Count -eq 0
[pscustomobject]@{
  ok = (@($rows | Where-Object { $_.profile_match }).Count -gt 0 -and $loopbackOnly)
  chrome_pids = @($rows | Select-Object -ExpandProperty pid)
  profile_match = (@($rows | Where-Object { $_.profile_match }).Count -gt 0)
	loopback_only = $loopbackOnly
} | ConvertTo-Json -Depth 6
`;
	const result = runPowerShellJson(script);
	if (!isObject(result)) {
		return {
			ok: false,
			chrome_pids: [],
			profile_match: false,
			loopback_only: false,
		};
	}
	return {
		ok: result.ok === true,
		chrome_pids: Array.isArray(result.chrome_pids)
			? result.chrome_pids
			: result.chrome_pids == null
				? []
				: [result.chrome_pids],
		profile_match: result.profile_match === true,
		loopback_only: result.loopback_only === true,
		process_error: asString(result.__error) || null,
	};
}

async function requestJson(url, options = {}) {
	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), options.timeoutMs || 8000);
	try {
		const response = await fetch(url, {
			...options,
			signal: controller.signal,
		});
		const raw = await response.text();
		let data = null;
		try {
			data = raw ? JSON.parse(raw) : null;
		} catch (_err) {
			data = null;
		}
		return { ok: response.ok, status: response.status, data, raw };
	} catch (error) {
		return {
			ok: false,
			status: 0,
			data: null,
			raw: "",
			error: error?.name || error?.message || "REQUEST_FAILED",
		};
	} finally {
		clearTimeout(timeout);
	}
}

function projectIdFromUrl(value) {
	try {
		const url = new URL(value);
		if (!PROJECT_URL_RE.test(url.href)) return null;
		const marker = "/project/";
		const index = url.pathname.indexOf(marker);
		return index < 0
			? null
			: decodeURIComponent(url.pathname.slice(index + marker.length).split("/")[0]);
	} catch (_err) {
		return null;
	}
}

function projectUrlMatches(left, right) {
	const leftId = projectIdFromUrl(left);
	const rightId = projectIdFromUrl(right);
	return Boolean(leftId && rightId && leftId === rightId);
}

function extractNumericCredit(value) {
	const seen = new Set();
	function walk(node) {
		if (node === null || node === undefined) return null;
		if (typeof node !== "object") return null;
		if (seen.has(node)) return null;
		seen.add(node);
		if (Array.isArray(node)) {
			for (const item of node) {
				const found = walk(item);
				if (found !== null) return found;
			}
			return null;
		}
		for (const [key, child] of Object.entries(node)) {
			const normalized = key.toLowerCase().replaceAll("_", "");
			if (CREDIT_KEYS.has(normalized)) {
				if (typeof child === "number" && Number.isFinite(child)) return child;
				if (typeof child === "string" && /^\s*-?\d+(?:\.\d+)?\s*$/.test(child)) {
					const number = Number(child);
					if (Number.isFinite(number)) return number;
				}
			}
			const nested = walk(child);
			if (nested !== null) return nested;
		}
		return null;
	}
	return walk(value);
}

function loginUrl(value) {
	const url = asString(value).toLowerCase();
	return (
		url.includes("accounts.google.com") ||
		url.includes("/signin/") ||
		url.includes("servicelogin") ||
		url.includes("/challenge/") ||
		url.includes("/chooser/")
	);
}

function isProjectTarget(target) {
	return target?.type === "page" && PROJECT_URL_RE.test(asString(target.url));
}

function serviceWorkerExtensionId(target) {
	const match = asString(target?.url).match(SERVICE_WORKER_URL_RE);
	return match?.[1] || null;
}

function activeVideoJob(rows, extensionStatus) {
	const persistent = (Array.isArray(rows) ? rows : []).filter((job) =>
		ACTIVE_VIDEO_STATUSES.has(asString(job?.status).toUpperCase()),
	);
	const extensionState = asString(
		extensionStatus?.state || extensionStatus?.extension_state,
	).toLowerCase();
	return {
		in_flight: persistent.length > 0 || extensionState === "running",
		active_jobs: persistent.map((job) => ({
			job_id: job?.job_id || null,
			status: job?.status || null,
		})),
		extension_state: extensionState || null,
	};
}

/**
 * Pure readiness classifier.  Tests use this function with mocked observations;
 * the CLI adds the live CDP/API observations below.
 */
export function classifyFlowProviderReadiness(observation = {}) {
	const authorityMode =
		asString(observation.provider_browser_authority_mode) || "DEDICATED_CDP_UAT";
	const runtimeCurrentMain = observation.runtime_current_main === true;
	const videoJobInFlight = observation.video_job_in_flight === true;
	const uiComposerRequired = observation.ui_composer_required === true;
	const composerReady =
		observation.composer_found === true &&
		(observation.composer_runtime_ready !== false);
	let primaryBlocker = null;

	if (authorityMode === "OWNER_PROFILE_EXTENSION_BRIDGE") {
		const transportConnected = observation.flow_transport_connected === true;
		const sessionPresent =
			observation.extension_session_present !== false &&
			Boolean(asString(observation.extension_session_id));
		const sameSession = observation.same_extension_session === true;
		const sameTab = observation.same_flow_tab === true;
		const challengeVerified =
			observation.session_challenge_verified === true;
		const projectFound = observation.flow_project_tab_found === true;
		const contentAlive = observation.content_script_alive === true;
		const buildMatch = observation.extension_build_match !== false;
		const authenticated = observation.flow_auth_status === "AUTHENTICATED";

		if (!runtimeCurrentMain) primaryBlocker = "RUNTIME_NOT_CURRENT_MAIN";
		else if (!transportConnected) primaryBlocker = "EXTENSION_BRIDGE_NOT_CONNECTED";
		else if (!sessionPresent || !sameSession) {
			primaryBlocker = "EXTENSION_SESSION_MISMATCH";
		} else if (!challengeVerified || observation.challenge_nonce_match === false) {
			primaryBlocker = "FLOW_SESSION_CHALLENGE_FAILED";
		} else if (!sameTab || !projectFound) {
			primaryBlocker = "FLOW_PROJECT_NOT_FOUND";
		} else if (!contentAlive) {
			primaryBlocker = "FLOW_CONTENT_SCRIPT_NOT_ALIVE";
		} else if (!buildMatch) {
			primaryBlocker = "EXTENSION_BUILD_MISMATCH";
		} else if (!authenticated) {
			primaryBlocker = "FLOW_AUTH_UNAUTHENTICATED";
		} else if (videoJobInFlight) {
			primaryBlocker = "PROVIDER_JOB_IN_FLIGHT";
		} else if (uiComposerRequired && !composerReady) {
			primaryBlocker = "FLOW_COMPOSER_NOT_READY";
		}
	} else if (authorityMode === "DEDICATED_CDP_UAT") {
		const browserReady = observation.browser_uat_ready === true;
		const extensionLoaded =
			observation.extension_loaded === true &&
			observation.extension_service_worker_alive !== false;
		const projectFound = observation.flow_project_tab_found === true;
		const authenticated = observation.flow_auth_status === "AUTHENTICATED";
		const transportConnected = observation.flow_transport_connected === true;
		const transportBound =
			observation.flow_transport_bound_to_uat_browser === true;

		if (!browserReady) primaryBlocker = "UAT_BROWSER_NOT_READY";
		else if (!runtimeCurrentMain) primaryBlocker = "UAT_RUNTIME_NOT_CURRENT_MAIN";
		else if (!extensionLoaded) {
			primaryBlocker = observation.owner_extension_install_required
				? "OWNER_UAT_EXTENSION_INSTALL_REQUIRED"
				: "UAT_EXTENSION_NOT_LOADED";
		} else if (!projectFound) {
			primaryBlocker = observation.login_required
				? "OWNER_GOOGLE_FLOW_LOGIN_REQUIRED"
				: "UAT_FLOW_PROJECT_NOT_OPEN";
		} else if (!authenticated) primaryBlocker = "UAT_FLOW_UNAUTHENTICATED";
		else if (!transportConnected || !transportBound) {
			primaryBlocker = "UAT_FLOW_TRANSPORT_NOT_BOUND";
		} else if (videoJobInFlight) primaryBlocker = "UAT_PROVIDER_JOB_IN_FLIGHT";
	} else {
		primaryBlocker = "INVALID_PROVIDER_BROWSER_AUTHORITY_MODE";
	}

	const ready = primaryBlocker === null;
	return {
		browser_uat_ready:
			authorityMode === "OWNER_PROFILE_EXTENSION_BRIDGE"
				? observation.flow_transport_connected === true
				: observation.browser_uat_ready === true,
		provider_browser_authority_mode: authorityMode,
		runtime_current_main: runtimeCurrentMain,
		flow_provider_uat_ready: ready,
		FLOW_PROVIDER_UAT_READY: ready,
		primary_blocker: ready ? "FLOW_PROVIDER_UAT_READY" : primaryBlocker,
	};
}

export { inspectUatProcess };

function parseCliArgs(argv) {
	const args = {
		cdpUrl: DEFAULT_CDP_URL,
		bosmaxUrl: DEFAULT_BOSMAX_URL,
		providerBrowserAuthorityMode:
			process.env.FLOW_PROVIDER_BROWSER_AUTHORITY || "DEDICATED_CDP_UAT",
		ownerProfileLabel:
			process.env.FLOW_PROVIDER_OWNER_PROFILE_LABEL || null,
		providerExecutionRoute:
			process.env.FLOW_PROVIDER_EXECUTION_ROUTE ||
			"EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
		sceneScaffoldRoute:
			process.env.FLOW_PROVIDER_SCENE_SCAFFOLD_ROUTE || "AGENT_T2V",
	};
	for (let index = 0; index < argv.length; index += 1) {
		const arg = argv[index];
		if (arg === "--cdp-url") args.cdpUrl = argv[++index];
		else if (arg === "--bosmax-url") args.bosmaxUrl = argv[++index];
		else if (arg === "--extension-path") args.extensionPath = argv[++index];
		else if (arg === "--profile-path") args.profilePath = argv[++index];
		else if (arg === "--browser-uat-root") args.browserUatRoot = argv[++index];
		else if (arg === "--provider-authority-mode") args.providerBrowserAuthorityMode = argv[++index];
		else if (arg === "--owner-profile-label") args.ownerProfileLabel = argv[++index];
		else if (arg === "--provider-execution-route") args.providerExecutionRoute = argv[++index];
		else if (arg === "--scene-scaffold-route") args.sceneScaffoldRoute = argv[++index];
		else if (arg === "--open-target") args.openTarget = argv[++index];
	}
	return args;
}

async function openCdpTarget(cdpUrl, targetUrl) {
	const encoded = encodeURIComponent(targetUrl);
	return requestJson(`${cdpUrl.replace(/\/$/, "")}/json/new?${encoded}`, {
		method: "PUT",
		headers: { "Content-Type": "application/json" },
		timeoutMs: 8000,
	});
}

export async function collectFlowProviderReadiness(config = {}) {
	const cdpUrl = asString(config.cdpUrl || DEFAULT_CDP_URL).replace(/\/$/, "");
	const bosmaxUrl = asString(config.bosmaxUrl || DEFAULT_BOSMAX_URL).replace(/\/$/, "");
	const authorityMode =
		asString(
			config.providerBrowserAuthorityMode ||
				config.provider_browser_authority_mode ||
				process.env.FLOW_PROVIDER_BROWSER_AUTHORITY,
		) || "DEDICATED_CDP_UAT";
	const ownerProfileLabel =
		asString(config.ownerProfileLabel || config.owner_profile_label) || null;
	const providerExecutionRoute =
		asString(config.providerExecutionRoute || config.provider_execution_route) ||
		"EXACT_PRODUCT_DETERMINISTIC_COMPOSITE";
	const sceneScaffoldRoute =
		asString(config.sceneScaffoldRoute || config.scene_scaffold_route) || "AGENT_T2V";
	const extensionRoot = config.browserUatRoot ||
		"C:\\Users\\USER\\Desktop\\_bosmax_runtime\\browser_uat";
	const contract = readJsonFile(path.join(extensionRoot, "browser-uat.json")) || {};
	const extensionPath = path.resolve(
		config.extensionPath ||
			process.env.BOSMAX_EXTENSION_PATH ||
			contract.extension_path ||
			DEFAULT_EXTENSION_PATH,
	);
	const profilePath = path.resolve(
		config.profilePath || contract.profile_path || DEFAULT_PROFILE,
	);
	const manifest = extensionManifest(extensionPath);
	const expectedBuild = expectedBuildId(extensionPath);
	const versionResponse = await requestJson(`${cdpUrl}/json/version`);
	const targetResponse = await requestJson(`${cdpUrl}/json/list`);
	const runtimeResponse = await requestJson(
		`${bosmaxUrl}/api/local-agent/runtime-provenance`,
	);
	const runtime = isObject(runtimeResponse.data) ? runtimeResponse.data : {};
	const runtimeSha = asString(runtime.runtime_sha);
	const originMain = asString(runtime.origin_main);
	const runtimeCurrentMain = Boolean(
		runtimeSha &&
		originMain &&
		runtimeSha === originMain &&
		runtime.canonical_runtime === true &&
		runtime.source_stale === false &&
		runtime.release_dirty === false &&
		runtime.db_canonical === true &&
		runtime.bundle_matches === true,
	);
	const targets = Array.isArray(targetResponse.data) ? targetResponse.data : [];
	const process = inspectUatProcess(profilePath, Number(contract.cdp_port || 9222));
	const browserReady =
		versionResponse.ok &&
		process.ok &&
		process.profile_match &&
		process.loopback_only;

	const serviceWorkers = targets.filter((target) => serviceWorkerExtensionId(target));
	const workerIds = serviceWorkers.map(serviceWorkerExtensionId).filter(Boolean);
	const projectTargets = targets.filter(isProjectTarget);
	const projectTarget = projectTargets[0] || null;
	const flowTargets = targets.filter((target) => FLOW_URL_RE.test(asString(target.url)));
	const loginTargets = targets.filter((target) => loginUrl(target.url));

	const statusResponse = await requestJson(`${bosmaxUrl}/api/flow/status`);
	const status = isObject(statusResponse.data) ? statusResponse.data : {};
	const creditsResponse = await requestJson(`${bosmaxUrl}/api/flow/credits`);
	const creditBalance = extractNumericCredit(creditsResponse.data);
	const readinessResponse = await requestJson(`${bosmaxUrl}/api/operator/flow-provider-readiness`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			provider_browser_authority_mode: authorityMode,
			owner_profile_label: ownerProfileLabel,
			extension_source_path: extensionPath,
			provider_execution_route: providerExecutionRoute,
			scene_scaffold_route: sceneScaffoldRoute,
			mode: "T2V",
		}),
	});
	const readiness = isObject(readinessResponse.data) ? readinessResponse.data : {};
	const jobsResponse = await requestJson(`${bosmaxUrl}/api/flow/video-jobs?limit=100`);
	const jobsPayload = isObject(jobsResponse.data) ? jobsResponse.data : {};
	const jobEvidence = activeVideoJob(jobsPayload.jobs, status);

	const extensionId =
		authorityMode === "OWNER_PROFILE_EXTENSION_BRIDGE"
			? asString(readiness.extension_id) || asString(status.extension_id) || null
			: workerIds.includes(asString(status.extension_id))
				? asString(status.extension_id)
				: workerIds[0] || null;
	const extensionLoaded =
		authorityMode === "OWNER_PROFILE_EXTENSION_BRIDGE"
			? Boolean(asString(readiness.extension_session_id))
			: serviceWorkers.length > 0;
	const statusFlowUrl =
		asString(status.flow_tab_url) ||
		asString(status.active_editor_tab_url) ||
		asString(readiness.flow_project_url);
	const transportProjectId = projectIdFromUrl(statusFlowUrl);
	const projectId = projectIdFromUrl(projectTarget?.url);
	const readinessProjectUrl = asString(readiness.flow_project_url) || null;
	const readinessProjectId = asString(readiness.flow_project_id) || null;
	const flowProjectFound =
		authorityMode === "OWNER_PROFILE_EXTENSION_BRIDGE"
			? readiness.flow_tab_found === true && Boolean(readinessProjectId)
			: Boolean(projectTarget);
	const contentProof =
		authorityMode === "OWNER_PROFILE_EXTENSION_BRIDGE"
			? readiness.content_script_loaded === true &&
				readiness.content_script_alive === true &&
				readiness.session_challenge_verified === true
			: readiness.content_script_alive === true ||
				(serviceWorkers.length > 0 && projectTarget != null);
	const extensionIdentityProof =
		Boolean(extensionId) &&
		(authorityMode === "OWNER_PROFILE_EXTENSION_BRIDGE"
			? asString(readiness.extension_session_id) === asString(status.extension_session_id)
			: asString(status.extension_id) === extensionId &&
				Boolean(asString(status.extension_session_id))) &&
		(!manifest?.version ||
			asString(readiness.extension_version || status.extension_version) ===
				asString(manifest.version));
	const projectProof =
		authorityMode === "OWNER_PROFILE_EXTENSION_BRIDGE"
			? readiness.same_flow_tab === true && Boolean(readinessProjectId)
			: Boolean(projectTarget) &&
				Boolean(projectId) &&
				Boolean(transportProjectId) &&
				transportProjectId === projectId &&
				projectUrlMatches(statusFlowUrl, projectTarget?.url);
	const flowTransportConnected =
		status.connected === true && readiness.flow_transport_connected !== false;
	const observedExtensionBuild = extensionIdentityProof
		? asString(readiness.extension_build) ||
			asString(status.extension_build) ||
			asString(status.background_build_id) ||
			null
		: null;
	const flowTransportBound =
		authorityMode === "OWNER_PROFILE_EXTENSION_BRIDGE"
			? readiness.flow_transport_bound_to_provider_browser === true &&
				readiness.session_challenge_verified === true
			: browserReady &&
				extensionLoaded &&
				extensionIdentityProof &&
				flowTransportConnected &&
				projectProof &&
				contentProof;
	const flowAuthStatus =
		asString(readiness.flow_auth_status) ||
		(asString(status.auth_state).toUpperCase() === "AUTHENTICATED"
			? "AUTHENTICATED"
			: "UNKNOWN");
	const loginRequired =
		loginTargets.length > 0 ||
		(asString(readiness.primary_blocker) === "FLOW_AUTH_UNAUTHENTICATED");
	const classification = classifyFlowProviderReadiness({
		provider_browser_authority_mode: authorityMode,
		browser_uat_ready: browserReady,
		runtime_current_main: runtimeCurrentMain,
		extension_loaded: extensionLoaded,
		extension_service_worker_alive: serviceWorkers.length > 0,
		extension_session_id: asString(readiness.extension_session_id || status.extension_session_id),
		extension_session_present: Boolean(asString(readiness.extension_session_id || status.extension_session_id)),
		flow_project_tab_found: flowProjectFound,
		flow_auth_status: flowAuthStatus,
		flow_transport_connected: flowTransportConnected,
		flow_transport_bound_to_uat_browser: flowTransportBound,
		flow_transport_bound_to_provider_browser: flowTransportBound,
		session_challenge_verified: readiness.session_challenge_verified === true,
		challenge_nonce_match: readiness.challenge?.challenge_nonce_match === true,
		same_extension_session: readiness.same_extension_session === true,
		same_flow_tab: readiness.same_flow_tab === true,
		content_script_alive: readiness.content_script_alive === true,
		extension_build_match:
			authorityMode === "OWNER_PROFILE_EXTENSION_BRIDGE"
				? readiness.extension_build_match === true
				: true,
		ui_composer_required: readiness.ui_composer_required === true,
		composer_found: readiness.composer_found === true,
		composer_runtime_ready: readiness.composer_runtime_ready === true,
		video_job_in_flight: jobEvidence.in_flight,
		login_required: loginRequired,
	});

	return {
		...classification,
		provider_browser_authority_mode: authorityMode,
		owner_profile_label: ownerProfileLabel,
		extension_source_path: extensionPath,
		provider_execution_route: providerExecutionRoute,
		scene_scaffold_route: sceneScaffoldRoute,
		ui_composer_required: readiness.ui_composer_required === true,
		chrome_pid: process.chrome_pids[0] || contract.chrome_pid || null,
		profile_path: profilePath,
		cdp_url: cdpUrl,
		dedicated_cdp_browser_ready: browserReady,
		runtime_sha: runtimeSha || null,
		origin_main: originMain || null,
		runtime_current_main: runtimeCurrentMain,
		source_stale: runtime.source_stale ?? null,
		release_dirty: runtime.release_dirty ?? null,
		db_canonical: runtime.db_canonical ?? null,
		bundle_matches: runtime.bundle_matches ?? null,
		release_dir: runtime.release_dir || null,
		dashboard_bundle: runtime.dashboard_bundle || null,
		extension_loaded: extensionLoaded,
		extension_id: extensionId,
		extension_version: asString(readiness.extension_version || status.extension_version) || null,
		extension_build: observedExtensionBuild,
		extension_build_expected: expectedBuild,
		extension_build_match: readiness.extension_build_match === true,
		extension_service_worker_alive:
			authorityMode === "OWNER_PROFILE_EXTENSION_BRIDGE"
			? Boolean(asString(readiness.extension_session_id))
			: serviceWorkers.length > 0,
		extension_service_worker_target_count: serviceWorkers.length,
		extension_service_worker_url: serviceWorkers[0]?.url || null,
		extension_session_id: asString(readiness.extension_session_id || status.extension_session_id) || null,
		flow_key_present: readiness.flow_key_present === true || status.flow_key_present === true,
		flow_project_tab_found: flowProjectFound,
		flow_tab_found: readiness.flow_tab_found === true,
		flow_tab_id: readiness.flow_tab_id ?? null,
		flow_project_url:
			authorityMode === "OWNER_PROFILE_EXTENSION_BRIDGE"
				? readinessProjectUrl
				: projectTarget?.url || null,
		flow_project_id:
			authorityMode === "OWNER_PROFILE_EXTENSION_BRIDGE"
				? readinessProjectId
				: projectId,
		flow_transport_connected: flowTransportConnected,
		flow_transport_bound_to_uat_browser: flowTransportBound,
		flow_transport_bound_to_provider_browser: flowTransportBound,
		flow_auth_status: flowAuthStatus,
		numeric_credit_balance:
			readiness.numeric_credit_balance ?? creditBalance,
		video_job_in_flight: jobEvidence.in_flight,
		proof: {
			browser_version: versionResponse.data?.Browser || null,
			profile_match: process.profile_match,
			cdp_loopback_only: process.loopback_only,
			flow_page_target_count: flowTargets.length,
			project_target_count: projectTargets.length,
			service_worker_target_count: serviceWorkers.length,
			worker_extension_ids: workerIds,
			backend_status_http: statusResponse.status,
			runtime_http: runtimeResponse.status,
			runtime_sha: runtimeSha || null,
			origin_main: originMain || null,
			backend_extension_id: asString(status.extension_id) || null,
			backend_flow_tab_url: statusFlowUrl || null,
			backend_extension_session_present: Boolean(asString(status.extension_session_id)),
			extension_identity_proof: extensionIdentityProof,
			project_proof: projectProof,
			content_script_proof: contentProof,
			flow_provider_readiness_http: readinessResponse.status,
			flow_provider_readiness_blocker: readiness.primary_blocker || null,
			flow_provider_readiness_raw: readiness,
			flow_session_challenge_verified: readiness.session_challenge_verified === true,
			same_extension_session: readiness.same_extension_session === true,
			same_flow_tab: readiness.same_flow_tab === true,
			active_video_jobs: jobEvidence.active_jobs,
			extension_state: jobEvidence.extension_state,
			credits_http: creditsResponse.status,
			credits_error_status:
				creditsResponse.data?.error?.status || creditsResponse.data?.detail?.status || null,
		},
	};
}

async function main() {
	const args = parseCliArgs(process.argv.slice(2));
	if (args.openTarget) {
		const result = await openCdpTarget(args.cdpUrl || DEFAULT_CDP_URL, args.openTarget);
		process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
		process.exitCode = result.ok ? 0 : 2;
		return;
	}
	try {
		const receipt = await collectFlowProviderReadiness(args);
		process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
		process.exitCode = receipt.flow_provider_uat_ready ? 0 : 2;
	} catch (error) {
		const receipt = {
			browser_uat_ready: false,
			flow_provider_uat_ready: false,
			primary_blocker: "UAT_BROWSER_NOT_READY",
			error: error?.message || String(error),
			profile_path: args.profilePath || DEFAULT_PROFILE,
			cdp_url: args.cdpUrl || DEFAULT_CDP_URL,
		};
		process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
		process.exitCode = 2;
	}
}

const isCli = process.argv[1] &&
	path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));
if (isCli) await main();
