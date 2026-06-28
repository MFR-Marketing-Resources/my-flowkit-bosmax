// biome-ignore-all format: preserve the line-stable service-worker runtime for narrow gate patches
/**
 * Flow Kit — Chrome Extension Background Service Worker
 *
 * Connects to local Python agent via WebSocket (agent runs WS server).
 * Captures bearer token, solves reCAPTCHA, proxies API calls through browser.
 */

// Runtime proof: this unpacked folder must loudly prove whether the
// lightweight F2V SOP runner is present at service-worker startup.
const BOSMAX_BUILD_PROOF = Object.freeze({
	branch: "fix/mv3-message-port-lifecycle",
	commit: "47ce04229877bb7e579fb195f42c257c9dcc0f66",
});

try {
	// eslint-disable-next-line no-undef
	importScripts("f2v-flow-queue-runner.js");
} catch (_err) {
	console.error(
		"[BOSMAX_F2V_FLOW_QUEUE_RUNNER] ERR_F2V_SOP_RUNNER_IMPORT_FAILED",
		_err,
	);
}

try {
	// eslint-disable-next-line no-undef
	importScripts("gfv2-readiness.js"); // exposes self.__GFV2_READINESS__
} catch (_err) {
	console.error("[GFV2] ERR_GFV2_READINESS_IMPORT_FAILED", _err);
}

const _bosmaxRunnerImported = Boolean(
	typeof self !== "undefined" && self.__BOSMAX_F2V_FLOW_QUEUE_RUNNER__,
);
console.log(
	`[BOSMAX_BUILD_PROOF] branch=${BOSMAX_BUILD_PROOF.branch} commit=${BOSMAX_BUILD_PROOF.commit} runner=${_bosmaxRunnerImported}`,
);
if (_bosmaxRunnerImported) {
	console.log(
		"[BOSMAX_F2V_FLOW_QUEUE_RUNNER] background_import_ok api_keys=" +
			Object.keys(self.__BOSMAX_F2V_FLOW_QUEUE_RUNNER__).length,
	);
} else {
	console.error(
		"[BOSMAX_F2V_FLOW_QUEUE_RUNNER] ERR_F2V_SOP_RUNNER_IMPORT_FAILED" +
			" — runner global missing after importScripts",
	);
}

const AGENT_WS_URL = "ws://127.0.0.1:8101";
// NOTE: This is a browser-restricted public API key — safe to ship in extension bundles.
const _API_KEY = "AIzaSyBtrm0o5ab1c-Ec8ZuLcGt3oJAA5VWt3pY";
const EXTENSION_PROTOCOL_VERSION = "FLOWKIT_EXTENSION_V1";
const FLOW_DOM_PROTOCOL_VERSION = "FLOWKIT_DOM_V1";
const FLOW_PROJECT_URL_STORAGE_KEY = "flow_project_url";

let ws = null;
let flowKey = null;
let _callbackSecret = null; // Auth secret for HTTP callback, received from server on WS connect
let state = "off"; // off | idle | running
let manualDisconnect = false;
const metrics = {
	tokenCapturedAt: null,
	requestCount: 0, // captcha-consuming requests only (gen image/video/upscale)
	successCount: 0,
	failedCount: 0,
	lastError: null,
};
const runtimeDiagnostics = {
	worker_alive: true,
	service_worker_started_at: new Date().toISOString(),
	ws_connected: false,
	runtime_reason: "EXTENSION_BOOTING",
	runtime_detail: "Flow Kit background service worker started.",
	auth_state: "UNKNOWN",
	flow_path_state: "NO_FLOW_TAB",
	target_project_state: "UNKNOWN",
	target_project_url: null,
	flow_tab_url: null,
	fallback_editor_url: null,
	stored_flow_project_url: null,
	last_bad_redirect_url: null,
	diagnostic_code: null,
	diagnostic_detail: null,
	selected_tab_id: null,
	active_editor_tab_id: null,
	selected_tab_active: false,
	selected_tab_url: null,
	active_editor_tab_url: null,
	rebound_to_active_editor_tab: false,
	same_project_url: false,
	content_script_alive_on_active_tab: false,
	safe_to_click_active_tab: false,
	last_updated_at: new Date().toISOString(),
};

function updateRuntimeDiagnostics(partial = {}) {
	const next = {
		...runtimeDiagnostics,
		...(partial && typeof partial === "object" ? partial : {}),
	};
	next.worker_alive = true;
	next.ws_connected =
		typeof next.ws_connected === "boolean"
			? next.ws_connected
			: ws?.readyState === WebSocket.OPEN;
	next.last_updated_at = new Date().toISOString();
	Object.assign(runtimeDiagnostics, next);
	return { ...runtimeDiagnostics };
}

function isAbnormalRedirectUrl(url) {
	const value = String(url || "").trim();
	return /^http:\/\/0\.0\.0\.\d+(?:[:/]|$)/i.test(value);
}

function respondOnce(reply, payload) {
	if (typeof reply !== "function") return;
	try {
		reply(payload);
	} catch (_) {}
}

// Default timeout for async message handlers. Chosen to be longer than the
// 4000ms used by sendTabMessageSafe so a downstream tab roundtrip still has
// room to surface its own normalized error before respondAsync gives up.
const DEFAULT_RESPOND_ASYNC_TIMEOUT_MS = 4500;

function normalizeChromeMessageError(rawError) {
	const message = String(rawError?.message || rawError || "").trim();
	if (!message) {
		return {
			error: "ERR_RUNTIME_LASTERROR",
			detail: "Unknown Chrome runtime messaging failure.",
		};
	}
	if (/Receiving end does not exist/i.test(message)) {
		return { error: "ERR_NO_RECEIVER", detail: message };
	}
	if (/Could not establish connection/i.test(message)) {
		return { error: "ERR_CONTENT_SCRIPT_STALE", detail: message };
	}
	if (
		/No tab with id|tab was closed|frame .* removed|The tab was closed/i.test(
			message,
		)
	) {
		return { error: "ERR_TAB_RELOADED", detail: message };
	}
	if (/message port closed before a response was received/i.test(message)) {
		return { error: "ERR_MESSAGE_RESPONSE_TIMEOUT", detail: message };
	}
	return {
		error: "ERR_RUNTIME_LASTERROR",
		detail: message,
	};
}

function shouldSilenceChromeMessageError(rawError) {
	const normalized = normalizeChromeMessageError(rawError);
	return [
		"ERR_NO_RECEIVER",
		"ERR_CONTENT_SCRIPT_STALE",
		"ERR_MESSAGE_RESPONSE_TIMEOUT",
		"ERR_TAB_RELOADED",
	].includes(normalized.error);
}

function respondAsync(
	reply,
	task,
	timeoutMs = DEFAULT_RESPOND_ASYNC_TIMEOUT_MS,
) {
	let settled = false;
	let timer = null;

	const done = (payload) => {
		if (settled) return;
		settled = true;
		if (timer) {
			clearTimeout(timer);
			timer = null;
		}
		respondOnce(reply, payload || { ok: true });
	};

	timer = setTimeout(() => {
		done({
			ok: false,
			error: "ERR_BACKGROUND_ASYNC_RESPONSE_TIMEOUT",
			detail: `respondAsync exceeded ${timeoutMs}ms`,
		});
	}, timeoutMs);

	Promise.resolve()
		.then(task)
		.then((payload) => done(payload || { ok: true }))
		.catch((error) =>
			done({
				ok: false,
				error: error?.message || String(error),
			}),
		);
	return true;
}

async function sendTabMessageSafe(tabId, payload, timeoutMs = 4000) {
	const tab = await getTabSafe(tabId);
	if (!tab?.id) {
		return {
			ok: false,
			error: "ERR_TAB_RELOADED",
			detail: `Tab ${tabId} no longer exists.`,
		};
	}

	return new Promise((resolve) => {
		let settled = false;
		const timer = setTimeout(() => {
			if (settled) return;
			settled = true;
			resolve({
				ok: false,
				error: "ERR_MESSAGE_RESPONSE_TIMEOUT",
				detail: `Timed out after ${timeoutMs}ms waiting for tab ${tabId}.`,
			});
		}, timeoutMs);

		chrome.tabs.sendMessage(tabId, payload, (response) => {
			const lastError = chrome.runtime.lastError;
			if (settled) return;
			settled = true;
			clearTimeout(timer);

			if (lastError) {
				const normalized = normalizeChromeMessageError(lastError);
				resolve({ ok: false, ...normalized });
				return;
			}
			resolve(response ?? { ok: false, error: "ERR_NO_RECEIVER" });
		});
	});
}

function _sendRuntimeMessageSafe(payload) {
	return new Promise((resolve) => {
		chrome.runtime.sendMessage(payload, (response) => {
			const lastError = chrome.runtime.lastError;
			if (lastError) {
				const normalized = normalizeChromeMessageError(lastError);
				if (!shouldSilenceChromeMessageError(lastError)) {
					console.warn("[FlowAgent] Runtime message error:", normalized.detail);
				}
				resolve({ ok: false, ...normalized });
				return;
			}
			resolve(response ?? { ok: true });
		});
	});
}

function sendRuntimeMessageNoThrow(payload) {
	try {
		chrome.runtime.sendMessage(payload, () => {
			const lastError = chrome.runtime.lastError;
			if (lastError && !shouldSilenceChromeMessageError(lastError)) {
				const normalized = normalizeChromeMessageError(lastError);
				console.warn("[FlowAgent] runtime message ignored:", normalized.detail);
			}
		});
	} catch (error) {
		console.warn("[FlowAgent] runtime message exception:", error);
	}
}

const flowContentScriptHealth = new Map();
const CDP_DEBUGGER_PROTOCOL_VERSION = "1.3";
const CDP_FILE_CHOOSER_TIMEOUT_MS = 15000;
const cdpFileChooserProofRuns = new Map();
const cdpFileChooserProofResults = new Map();
const cdpFileChooserProofAliases = new Map();

function getCdpDebuggee(tabId) {
	return { tabId };
}

async function detachDebuggerSafe(debuggee) {
	try {
		await chrome.debugger.detach(debuggee);
	} catch (_) {}
}

async function cdpClickCoordinate(tabId, x, y) {
	const debuggee = getCdpDebuggee(tabId);
	let attached = false;
	try {
		await chrome.debugger.attach(debuggee, CDP_DEBUGGER_PROTOCOL_VERSION);
		attached = true;
	} catch (_e) {
		// ignore if already attached
	}
	try {
		await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
			type: "mousePressed",
			x: x,
			y: y,
			button: "left",
			clickCount: 1,
		});
		await new Promise((r) => setTimeout(r, 100));
		await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
			type: "mouseReleased",
			x: x,
			y: y,
			button: "left",
			clickCount: 1,
		});
	} finally {
		if (attached) {
			try {
				await chrome.debugger.detach(debuggee);
			} catch (_) {}
		}
	}
	return { ok: true };
}

async function cleanupCdpFileChooserProofRun(tabId, run) {
	if (!run || run.cleanedUp) return;
	run.cleanedUp = true;

	clearTimeout(run.timeoutId);

	// Safe listener removal
	try {
		chrome.debugger.onEvent.removeListener(run.handleEvent);
	} catch (_) {}
	try {
		chrome.debugger.onDetach.removeListener(run.handleDetach);
	} catch (_) {}

	try {
		await chrome.debugger.sendCommand(
			run.debuggee,
			"Page.setInterceptFileChooserDialog",
			{
				enabled: false,
			},
		);
	} catch (_) {}

	await detachDebuggerSafe(run.debuggee);

	// Ensure Map is cleaned
	cdpFileChooserProofRuns.delete(tabId);
	for (const [aliasTabId, targetTabId] of Array.from(
		cdpFileChooserProofAliases.entries(),
	)) {
		if (aliasTabId === tabId || targetTabId === tabId) {
			cdpFileChooserProofAliases.delete(aliasTabId);
		}
	}
}

function settleCdpFileChooserProofRun(tabId, payload) {
	const run = cdpFileChooserProofRuns.get(tabId);
	if (!run || run.settled) return;
	run.settled = true;
	run.result = payload;
	cdpFileChooserProofResults.set(tabId, payload);
	void cleanupCdpFileChooserProofRun(tabId, run).finally(() => {
		run.resolve(payload);
	});
}

function rememberCdpFileChooserProofAlias(aliasTabId, targetTabId) {
	const alias = Number(aliasTabId || 0);
	const target = Number(targetTabId || 0);
	if (!alias || !target) return;
	cdpFileChooserProofAliases.set(alias, target);
}

function resolveCdpFileChooserProofTabId(...candidateTabIds) {
	const numericCandidates = candidateTabIds
		.map((value) => Number(value || 0))
		.filter((value) => Number.isFinite(value) && value > 0);
	for (const candidate of numericCandidates) {
		if (
			cdpFileChooserProofRuns.has(candidate) ||
			cdpFileChooserProofResults.has(candidate)
		) {
			return candidate;
		}
		const aliasTarget = cdpFileChooserProofAliases.get(candidate);
		if (
			aliasTarget &&
			(cdpFileChooserProofRuns.has(aliasTarget) ||
				cdpFileChooserProofResults.has(aliasTarget))
		) {
			return aliasTarget;
		}
	}
	if (cdpFileChooserProofRuns.size === 1) {
		return Array.from(cdpFileChooserProofRuns.keys())[0] || null;
	}
	if (cdpFileChooserProofResults.size === 1) {
		return Array.from(cdpFileChooserProofResults.keys())[0] || null;
	}
	return numericCandidates[0] || null;
}

async function beginCdpFileChooserProof(
	tabId,
	filePath,
	expectedFileName,
	slotLabel,
) {
	if (!tabId) {
		return { ok: false, error: "ERR_CDP_DEBUGGER_TAB_ID_MISSING" };
	}
	if (!filePath || typeof filePath !== "string") {
		return { ok: false, error: "ERR_CDP_FILE_PATH_REQUIRED" };
	}

	const existingRun = cdpFileChooserProofRuns.get(tabId);
	if (existingRun && !existingRun.settled) {
		return { ok: false, error: "ERR_CDP_FILE_CHOOSER_ALREADY_ARMED" };
	}
	cdpFileChooserProofResults.delete(tabId);

	const debuggee = getCdpDebuggee(tabId);
	await chrome.debugger.attach(debuggee, CDP_DEBUGGER_PROTOCOL_VERSION);

	try {
		await chrome.debugger.sendCommand(debuggee, "Page.enable");
		await chrome.debugger.sendCommand(debuggee, "DOM.enable");
		await chrome.debugger.sendCommand(
			debuggee,
			"Page.setInterceptFileChooserDialog",
			{ enabled: true },
		);
	} catch (error) {
		await detachDebuggerSafe(debuggee);
		throw error;
	}

	let resolveRun;
	const completionPromise = new Promise((resolve) => {
		resolveRun = resolve;
	});
	const run = {
		debuggee,
		expectedFileName: expectedFileName || null,
		filePath,
		slotLabel: slotLabel || "Start",
		resolve: resolveRun,
		result: null,
		settled: false,
		cleanedUp: false,
		timeoutId: null,
		handleEvent: null,
		handleDetach: null,
		completionPromise,
	};

	run.handleEvent = async (source, method, params) => {
		if (source?.tabId !== tabId || method !== "Page.fileChooserOpened") {
			return;
		}

		try {
			if (!params?.backendNodeId) {
				throw new Error("ERR_CDP_FILE_CHOOSER_BACKEND_NODE_MISSING");
			}

			await chrome.debugger.sendCommand(debuggee, "DOM.setFileInputFiles", {
				files: [filePath],
				backendNodeId: params.backendNodeId,
			});

			settleCdpFileChooserProofRun(tabId, {
				ok: true,
				method,
				mode: params.mode || null,
				backendNodeId: params.backendNodeId,
				filePath,
				expectedFileName: expectedFileName || null,
				slotLabel: slotLabel || "Start",
			});
		} catch (error) {
			settleCdpFileChooserProofRun(tabId, {
				ok: false,
				error: String(error?.message || error),
				method,
				backendNodeId: params?.backendNodeId || null,
				filePath,
				expectedFileName: expectedFileName || null,
				slotLabel: slotLabel || "Start",
			});
		}
	};

	run.handleDetach = (source, reason) => {
		if (source?.tabId !== tabId) return;
		settleCdpFileChooserProofRun(tabId, {
			ok: false,
			error: `ERR_CDP_DEBUGGER_DETACHED:${reason || "unknown"}`,
			detach_reason: reason || "unknown",
			filePath,
			expectedFileName: expectedFileName || null,
			slotLabel: slotLabel || "Start",
		});
	};

	run.timeoutId = setTimeout(async () => {
		// The native chooser never opened — recover by feeding any hidden file input.
		const direct = await tryDirectFileInputFeed(debuggee, filePath);
		if (direct.ok) {
			settleCdpFileChooserProofRun(tabId, {
				ok: true,
				method: "DOM.setFileInputFiles_direct",
				recovered_via: "direct_input",
				nodeId: direct.nodeId,
				input_count: direct.inputCount,
				filePath,
				expectedFileName: expectedFileName || null,
				slotLabel: slotLabel || "Start",
			});
			return;
		}
		settleCdpFileChooserProofRun(tabId, {
			ok: false,
			error: "ERR_CDP_FILE_CHOOSER_TIMEOUT",
			direct_input_error: direct.error || null,
			direct_input_detail: direct.detail || null,
			filePath,
			expectedFileName: expectedFileName || null,
			slotLabel: slotLabel || "Start",
		});
	}, CDP_FILE_CHOOSER_TIMEOUT_MS);

	chrome.debugger.onEvent.addListener(run.handleEvent);
	chrome.debugger.onDetach.addListener(run.handleDetach);
	cdpFileChooserProofRuns.set(tabId, run);

	return {
		ok: true,
		armed: true,
		slotLabel: run.slotLabel,
		expectedFileName: run.expectedFileName,
		timeout_ms: CDP_FILE_CHOOSER_TIMEOUT_MS,
	};
}

// Robust recovery for upload widgets that attach a hidden <input type=file> but
// never fire Page.fileChooserOpened (Google Flow V2's "Add Media" -> "Upload media"
// path — confirmed by live req gfv2_live_3..7 hitting ERR_CDP_FILE_CHOOSER_TIMEOUT).
// Queries the DOM directly for file inputs and feeds the materialized path via
// DOM.setFileInputFiles. Only invoked AFTER the interception times out, so the
// proven fileChooserOpened path (F2V) is unaffected.
async function tryDirectFileInputFeed(debuggee, filePath) {
	try {
		const doc = await chrome.debugger.sendCommand(debuggee, "DOM.getDocument", {
			depth: 0,
		});
		const rootNodeId = doc?.root?.nodeId;
		if (!rootNodeId) return { ok: false, error: "ERR_CDP_NO_DOCUMENT" };
		const found = await chrome.debugger.sendCommand(
			debuggee,
			"DOM.querySelectorAll",
			{ nodeId: rootNodeId, selector: "input[type=file], input[type='file']" },
		);
		const nodeIds = Array.isArray(found?.nodeIds) ? found.nodeIds : [];
		if (nodeIds.length === 0) return { ok: false, error: "ERR_CDP_NO_FILE_INPUT" };
		// Most-recently-attached input is usually the live upload target — try last first.
		let lastErr = null;
		for (let i = nodeIds.length - 1; i >= 0; i -= 1) {
			try {
				await chrome.debugger.sendCommand(debuggee, "DOM.setFileInputFiles", {
					files: [filePath],
					nodeId: nodeIds[i],
				});
				return { ok: true, nodeId: nodeIds[i], inputCount: nodeIds.length };
			} catch (error) {
				lastErr = String(error?.message || error);
			}
		}
		return { ok: false, error: "ERR_CDP_SET_FILE_INPUT_FAILED", detail: lastErr };
	} catch (error) {
		return {
			ok: false,
			error: "ERR_CDP_DIRECT_INPUT_FEED_FAILED",
			detail: String(error?.message || error),
		};
	}
}

async function waitForCdpFileChooserProof(tabId) {
	const resolvedTabId = resolveCdpFileChooserProofTabId(tabId);
	const run = cdpFileChooserProofRuns.get(resolvedTabId);
	if (!run) {
		const settledResult = cdpFileChooserProofResults.get(resolvedTabId);
		if (settledResult) {
			cdpFileChooserProofResults.delete(resolvedTabId);
			return settledResult;
		}
		return {
			ok: false,
			error: "ERR_CDP_FILE_CHOOSER_NOT_ARMED",
			detail: `requested_tab_id=${tabId || "null"} resolved_tab_id=${resolvedTabId || "null"}`,
		};
	}

	const result = run.result || (await run.completionPromise);
	cdpFileChooserProofRuns.delete(resolvedTabId);
	cdpFileChooserProofResults.delete(resolvedTabId);
	return result;
}

async function fetchAssetBase64ForCdp(assetRef) {
	const ref = String(assetRef == null ? "" : assetRef);
	if (/^data:/i.test(ref)) {
		const match = ref.match(/^data:([^;,]+)?(?:;base64)?,(.*)$/i);
		if (!match) {
			return {
				ok: false,
				error: "ERR_BACKGROUND_ASSET_FETCH_FAILED",
				detail: "INVALID_DATA_URL",
			};
		}
		const mimeType = match[1] || "image/png";
		const payload = match[2] || "";
		return {
			ok: true,
			base64: /;base64,/i.test(ref)
				? payload
				: btoa(decodeURIComponent(payload)),
			mimeType,
		};
	}
	const url = /^https?:\/\//i.test(ref)
		? ref
		: `http://127.0.0.1:8100/api/products/${ref}/image`;
	const controller = new AbortController();
	const timeoutId = setTimeout(() => controller.abort(), 10000);
	try {
		const resp = await fetch(url, { signal: controller.signal });
		clearTimeout(timeoutId);
		if (!resp.ok) {
			return {
				ok: false,
				error: "ERR_BACKGROUND_ASSET_FETCH_FAILED",
				detail: `HTTP_${resp.status}`,
			};
		}
		const blob = await resp.blob();
		const bytes = new Uint8Array(await blob.arrayBuffer());
		let binary = "";
		for (let i = 0; i < bytes.byteLength; i++)
			binary += String.fromCharCode(bytes[i]);
		return {
			ok: true,
			base64: btoa(binary),
			mimeType: blob.type || "image/jpeg",
		};
	} catch (e) {
		clearTimeout(timeoutId);
		return {
			ok: false,
			error: "ERR_BACKGROUND_ASSET_FETCH_FAILED",
			detail: String(e?.message || e),
		};
	}
}

// Materialize an asset to a real disk path via the local agent (the MV3 service worker
// cannot write files, and CDP DOM.setFileInputFiles requires an absolute path).
async function materializeAssetToDiskPath(assetRef, slotLabel) {
	const ref = String(assetRef == null ? "" : assetRef);
	const slot = String(slotLabel || "start").toLowerCase();
	// Workspace-materialized asset already on local disk — feed it directly with
	// no refetch (CDP DOM.setFileInputFiles needs an absolute path, which this is).
	if (/^(?:[a-zA-Z]:[\\/]|\/)/.test(ref) && !/^https?:\/\//i.test(ref)) {
		const baseName = ref.split(/[\\/]/).pop() || `${slot}.png`;
		return { ok: true, filePath: ref, fileName: baseName, mimeType: "image/*" };
	}
	// Remote package assets should be fetched and staged by the local agent.
	// The extension service worker must not depend on remote host permissions.
	if (/^https?:\/\//i.test(ref)) {
		let remoteFileName = `${slot}.png`;
		try {
			const remoteUrl = new URL(ref);
			remoteFileName =
				remoteUrl.pathname.split("/").pop() || remoteFileName;
		} catch (_) {}
		try {
			const resp = await fetch(
				"http://127.0.0.1:8100/api/flow/materialize-remote-file",
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({
						source_url: ref,
						file_name: remoteFileName,
					}),
				},
			);
			if (!resp.ok) {
				return {
					ok: false,
					error: "ERR_MATERIALIZE_ASSET_FAILED",
					detail: `HTTP_${resp.status}`,
				};
			}
			const data = await resp.json();
			if (!data?.local_file_path) {
				return {
					ok: false,
					error: "ERR_MATERIALIZE_ASSET_NO_PATH",
					detail: "no local_file_path in remote materialize response",
				};
			}
			return {
				ok: true,
				filePath: data.local_file_path,
				fileName: data.file_name || remoteFileName,
				mimeType: data.mime_type || "image/*",
			};
		} catch (e) {
			return {
				ok: false,
				error: "ERR_MATERIALIZE_ASSET_FAILED",
				detail: String(e?.message || e),
			};
		}
	}
	const fetched = await fetchAssetBase64ForCdp(ref);
	if (!fetched.ok) return fetched;
	const ext = (fetched.mimeType.split("/")[1] || "png").replace("jpeg", "jpg");
	const safeToken =
		ref
			.replace(/^https?:\/\//i, "")
			.replace(/[^a-zA-Z0-9._-]+/g, "_")
			.slice(-40) || "asset";
	const fileName = `${slot}-${safeToken}.${ext}`;
	try {
		const resp = await fetch(
			"http://127.0.0.1:8100/api/flow/materialize-local-file",
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					image_base64: fetched.base64,
					file_name: fileName,
					mime_type: fetched.mimeType,
				}),
			},
		);
		if (!resp.ok) {
			return {
				ok: false,
				error: "ERR_MATERIALIZE_ASSET_FAILED",
				detail: `HTTP_${resp.status}`,
			};
		}
		const data = await resp.json();
		if (!data?.local_file_path) {
			return {
				ok: false,
				error: "ERR_MATERIALIZE_ASSET_NO_PATH",
				detail: "no local_file_path in response",
			};
		}
		return {
			ok: true,
			filePath: data.local_file_path,
			fileName: data.file_name || fileName,
			mimeType: data.mime_type || fetched.mimeType,
		};
	} catch (e) {
		return {
			ok: false,
			error: "ERR_MATERIALIZE_ASSET_FAILED",
			detail: String(e?.message || e),
		};
	}
}

// Phase 2 CDP upload dependency handed to the F2V runner. phase=arm resolves the asset to
// a disk path and arms CDP file-chooser interception; phase=wait awaits the fed result.
async function cdpFileChooserUploadForJob(tabId, req) {
	const preferredUrl = await getStoredFlowProjectUrl();
	const liveEditorTab =
		(await resolveLiveFlowEditorTab(preferredUrl, "F2V")) ||
		(await getTabSafe(req?.tabId || tabId)) ||
		(await getFlowTab());
	const requestedTabId = req?.tabId || tabId || null;
	const effectiveTabId = liveEditorTab?.id || requestedTabId;
	const slot = req?.slotLabel || "Start";
	if (req?.phase === "arm") {
		if (!req.assetSource) {
			return {
				ok: false,
				error: "ERR_CDP_UPLOAD_NO_ASSET",
				detail: `slot=${slot}`,
			};
		}
		const mat = await materializeAssetToDiskPath(req.assetSource, slot);
		if (!mat.ok) return mat;
		rememberCdpFileChooserProofAlias(requestedTabId, effectiveTabId);
		rememberCdpFileChooserProofAlias(effectiveTabId, effectiveTabId);
		const armed = await beginCdpFileChooserProof(
			effectiveTabId,
			mat.filePath,
			mat.fileName,
			slot,
		);
		if (!armed?.ok) return armed;
		return {
			...armed,
			materialized: true,
			materializedName:
				(mat.filePath && mat.filePath.split(/[\\/]/).pop()) ||
				mat.fileName ||
				null,
			materializedDirLabel: /flowkit-upload-staging/i.test(
				String(mat.filePath || ""),
			)
				? "flowkit-upload-staging"
				: "staged_local_file",
			sourceType: req?.sourceType || null,
		};
	}
	if (req?.phase === "wait") {
		const boundTabId = resolveCdpFileChooserProofTabId(
			requestedTabId,
			effectiveTabId,
		);
		return await waitForCdpFileChooserProof(boundTabId);
	}
	return {
		ok: false,
		error: "ERR_CDP_UPLOAD_BAD_PHASE",
		detail: `phase=${req?.phase}`,
	};
}

async function domFileUploadFallbackForJob(tabId, req) {
	const slot = req?.slotLabel || "Start";
	const preferredUrl = await getStoredFlowProjectUrl();
	const liveEditorTab =
		(await resolveLiveFlowEditorTab(preferredUrl, "F2V")) ||
		(await getTabSafe(req?.tabId || tabId)) ||
		(await getFlowTab());
	const effectiveTabId = liveEditorTab?.id || req?.tabId || tabId || null;
	if (!effectiveTabId) {
		return {
			ok: false,
			error: "ERR_DOM_UPLOAD_TAB_ID_MISSING",
			detail: `slot=${slot}`,
		};
	}
	if (!req?.assetSource) {
		return {
			ok: false,
			error: "ERR_DOM_UPLOAD_NO_ASSET",
			detail: `slot=${slot}`,
		};
	}
	await ensureFlowDomScript(effectiveTabId);
	return await sendTabMessageSafe(
		effectiveTabId,
		{
			type: "FLOWKIT_SIMULATE_FILE_UPLOAD",
			slotLabel: slot,
			assetSource: req.assetSource,
			options: {
				reuseOpenModal: true,
				stopAfterDispatch: true,
			},
		},
		30000,
	);
}

// Resolve an operator/workspace F2V job into a single CDP-feedable Start-frame
// asset reference. Preference order keeps the SELECTED media authoritative (not
// the generic product image), and tolerates the real job shape — the dashboard
// sends `startAsset` (object) + snake_case `product_id`, never camelCase:
//   1. startAsset.localFilePath            — already materialized on disk
//   2. startAsset.downloadUrl/previewUrl   — fetchable signed URL
//   3. startAsset.mediaId/assetId          — id forms
//   4. product_id / productId / startImageMediaId
// Returns null when the job carries no upload asset (DOM path stays untouched).
function resolveF2VUploadAssetSource(job) {
	if (!job) return null;
	const a = job.startAsset;
	if (a && typeof a === "object") {
		const fromAsset =
			a.localFilePath ||
			a.downloadUrl ||
			a.previewUrl ||
			a.mediaId ||
			a.assetId;
		if (fromAsset) return fromAsset;
	} else if (typeof a === "string" && a) {
		return a;
	}
	return job.product_id || job.productId || job.startImageMediaId || null;
}

// Classify the GFV2 upload asset STRICTLY from the system job payload — never a
// Desktop/manual OS pick. Returns { ok, source_type, safe_name, materialized } or a
// fail-closed { ok:false, error:'GFV2_ASSET_SOURCE_NOT_FOUND' }. safe_name is a
// basename/hash only (never a full private path).
function gfv2ClassifyAssetSource(job) {
	const safeName = (v) => {
		if (!v || typeof v !== "string") return null;
		const base = v.split("?")[0].split(/[\\/]/).pop() || null;
		return base ? base.slice(0, 80) : null;
	};
	if (!job) return { ok: false, error: "GFV2_ASSET_SOURCE_NOT_FOUND", reason: "no_job" };

	// ref_flowkit / image_ref are not wired into the actual CDP upload resolver yet.
	// Reject them explicitly so the lane cannot report a deterministic source it will
	// never hand to DOM.setFileInputFiles.
	const refFlowkit = job.ref_flowkit || job.refFlowkit || job.image_ref || job.imageRef || null;
	if (refFlowkit) {
		const v = typeof refFlowkit === "string" ? refFlowkit : refFlowkit.fileName || refFlowkit.downloadUrl || refFlowkit.mediaId;
		return {
			ok: false,
			error: "GFV2_ASSET_SOURCE_UNWIRED",
			reason: "ref_flowkit_or_image_ref_unwired",
			safe_name: safeName(v) || "ref_flowkit",
		};
	}

	const a = job.startAsset;
	if (a && typeof a === "object") {
		const localPath = a.localFilePath || a.local_file_path || null;
		// 2. Backend-materialized controlled temp file (the canonical GFV2 path).
		if (localPath && /flowkit-upload-staging/i.test(String(localPath))) {
			return { ok: true, source_type: "materialized_temp_file", safe_name: safeName(localPath), materialized: true };
		}
		// 3. Existing Google Flow media (id present) — prefer selecting the card.
		const mediaId = a.mediaId || a.media_id || a.assetId || a.asset_id || null;
		if (mediaId) {
			return { ok: true, source_type: "existing_flow_media", safe_name: safeName(a.fileName || a.file_name) || String(mediaId).slice(0, 80), materialized: false };
		}
		// 4. Workspace package Start asset (remote URL the backend materializes).
		const url = a.downloadUrl || a.download_url || a.previewUrl || a.preview_url || null;
		if (url) {
			const isWorkspace = Boolean(job.workspace_execution_package_id || job.prompt_package_snapshot_id);
			return { ok: true, source_type: isWorkspace ? "workspace_package_start" : "start_asset", safe_name: safeName(a.fileName || a.file_name || url), materialized: false };
		}
		if (localPath) {
			// An absolute local path that is NOT under the controlled staging dir is not
			// trusted as a system asset (could be a Desktop pick) — fail closed.
			return { ok: false, error: "GFV2_ASSET_SOURCE_NOT_FOUND", reason: "untrusted_local_path_not_in_staging" };
		}
	} else if (typeof a === "string" && a) {
		if (/^https?:/i.test(a)) return { ok: true, source_type: "start_asset", safe_name: safeName(a), materialized: false };
		if (/flowkit-upload-staging/i.test(a)) return { ok: true, source_type: "materialized_temp_file", safe_name: safeName(a), materialized: true };
		return { ok: false, error: "GFV2_ASSET_SOURCE_NOT_FOUND", reason: "untrusted_local_string" };
	}

	// 5. Product / existing-media id fallback.
	const pid = job.product_id || job.productId || job.startImageMediaId || null;
	if (pid) return { ok: true, source_type: "existing_flow_media", safe_name: String(pid).slice(0, 80), materialized: false };

	return { ok: false, error: "GFV2_ASSET_SOURCE_NOT_FOUND", reason: "no_system_asset_in_job" };
}

function resolveF2VDomFallbackAssetSource(job) {
	if (!job) return null;
	const a = job.startAsset;
	if (a && typeof a === "object") {
		const previewUrl =
			a.previewUrl || a.preview_url || a.downloadUrl || a.download_url || null;
		if (previewUrl) {
			return {
				previewUrl,
				fileName: a.fileName || a.file_name || a.label || "Start.png",
			};
		}
	}

	const uploadAssetSource = resolveF2VUploadAssetSource(job);
	if (!uploadAssetSource || typeof uploadAssetSource !== "string") return null;
	if (
		/^(?:[a-zA-Z]:[\\/]|\/)/.test(uploadAssetSource) &&
		!/^https?:\/\//i.test(uploadAssetSource)
	) {
		return null;
	}
	if (/^https?:\/\//i.test(uploadAssetSource)) {
		return {
			previewUrl: uploadAssetSource,
			fileName: "Start.png",
		};
	}
	return uploadAssetSource;
}

// F2V_PACKAGE_UPLOAD_ONLY lane — strict package-to-current-editor Start upload.
// This lane intentionally does NOT open/create projects, touch settings/model/
// aspect/count, click Agent, or generate. It binds the CURRENT healthy editor
// only and uploads the package Start asset via the existing CDP file chooser.
function isF2VPackageUploadOnly(job) {
	if (!job) return false;
	return (
		job.lane === "F2V_PACKAGE_UPLOAD_ONLY" || job.upload_only === true
	);
}

// Validate the BOSMAX workspace execution package is the source of truth before
// this lane touches the editor. Returns { ok, error, detail } — fail closed.
function validateF2VPackageUploadOnlyJob(job) {
	if (!job) {
		return { ok: false, error: "ERR_PACKAGE_REQUIRED", detail: "job missing" };
	}
	if (!job.request_id) {
		return { ok: false, error: "ERR_PACKAGE_REQUIRED", detail: "request_id missing" };
	}
	if (!job.workspace_execution_package_id) {
		return {
			ok: false,
			error: "ERR_PACKAGE_REQUIRED",
			detail: "workspace_execution_package_id missing",
		};
	}
	if (String(job.mode || "").trim().toUpperCase() !== "F2V") {
		return { ok: false, error: "ERR_PACKAGE_REQUIRED", detail: "mode must be F2V" };
	}
	if (!job.prompt || String(job.prompt).trim().length === 0) {
		return { ok: false, error: "ERR_PACKAGE_REQUIRED", detail: "prompt missing" };
	}
	const startAsset = job.startAsset;
	if (!startAsset) {
		return { ok: false, error: "ERR_PACKAGE_REQUIRED", detail: "start asset missing" };
	}
	const localFilePath =
		(startAsset && typeof startAsset === "object" &&
			(startAsset.localFilePath || startAsset.local_file_path)) ||
		job.local_file_path ||
		job.localFilePath ||
		null;
	if (!localFilePath || typeof localFilePath !== "string" || !localFilePath.trim()) {
		return {
			ok: false,
			error: "ERR_PACKAGE_START_LOCAL_FILE_REQUIRED",
			detail: "start asset has no usable local_file_path/localFilePath",
		};
	}
	return { ok: true, localFilePath };
}

// CDP upload is the only background-owned lane that can deterministically feed
// a real file into the native chooser for F2V Frames jobs. Default it on when
// the job carries a resolvable asset, unless the caller explicitly opts out.
function shouldUseF2VCdpUpload(
	job,
	assetSource = resolveF2VUploadAssetSource(job),
) {
	if (!job || job.skipUpload === true) return false;
	if (job.use_cdp_upload === false) return false;
	return job.use_cdp_upload === true || assetSource != null;
}

const WS_METHOD_TIMEOUT_MS = {
	get_status: 5000,
	GET_RUNTIME_SELF_TEST: 60000,
	BOOTSTRAP_FLOW_PROJECT_EDITOR: 90000,
	CHECK_FLOW_COMPOSER_READY: 12000,
	FLOW_PAGE_STATE_DIAGNOSTIC: 12000,
	RELOAD_FLOW_TAB: 12000,
	OPEN_TARGET_FLOW_PROJECT: 45000,
	OPEN_FLOW_NEW_PROJECT: 75000,
	EXECUTE_FLOW_JOB: 125000,
	DEBUG_FLOW_DOM_EXECUTION: 65000,
};

function buildFlowTabSnapshot(flowTab) {
	return {
		flow_tab_found: Boolean(flowTab),
		flow_tab_id: flowTab?.id ?? null,
		flow_url: flowTab?.url ?? null,
	};
}

async function getFlowTabSafe() {
	try {
		return await getFlowTab();
	} catch (_) {
		return null;
	}
}

function getMethodStageField(method, phase) {
	const stageFields = {
		CHECK_FLOW_COMPOSER_READY: {
			received: "BACKGROUND_RECEIVED_CHECK_FLOW_COMPOSER_READY",
			sent: "BACKGROUND_SENT_CHECK_FLOW_COMPOSER_READY_RESPONSE",
		},
		RELOAD_FLOW_TAB: {
			received: "BACKGROUND_RECEIVED_RELOAD_FLOW_TAB",
			sent: "BACKGROUND_SENT_RELOAD_FLOW_TAB_RESPONSE",
		},
		OPEN_TARGET_FLOW_PROJECT: {
			received: "BACKGROUND_RECEIVED_OPEN_TARGET_FLOW_PROJECT",
			sent: "BACKGROUND_SENT_OPEN_TARGET_FLOW_PROJECT_RESPONSE",
		},
		OPEN_FLOW_NEW_PROJECT: {
			received: "BACKGROUND_RECEIVED_OPEN_FLOW_NEW_PROJECT",
			sent: "BACKGROUND_SENT_OPEN_FLOW_NEW_PROJECT_RESPONSE",
		},
		BOOTSTRAP_FLOW_PROJECT_EDITOR: {
			received: "BACKGROUND_RECEIVED_BOOTSTRAP_FLOW_PROJECT_EDITOR",
			sent: "BACKGROUND_SENT_BOOTSTRAP_FLOW_PROJECT_EDITOR_RESPONSE",
		},
	};
	return stageFields[method]?.[phase] || null;
}

function logWsMethodStage(method, phase, flowTab, extra = {}) {
	const fieldName = getMethodStageField(method, phase);
	const payload = {
		method,
		phase,
		timestamp: new Date().toISOString(),
		...buildFlowTabSnapshot(flowTab),
		...extra,
	};
	if (fieldName) {
		payload[fieldName] = true;
	}
	console.info(`[FlowAgent] ${method} ${phase}`, payload);
	return payload;
}

function normalizeMethodError(error) {
	const rawError = String(error || "ERR_UNKNOWN_METHOD_FAILURE");
	if (rawError === "FLOW_TAB_NOT_FOUND") {
		return "ERR_NO_FLOW_TAB";
	}
	if (
		rawError === "ERR_NO_RECEIVER" ||
		rawError === "ERR_CONTENT_SCRIPT_STALE"
	) {
		return "CONTENT_SCRIPT_STALE_OR_NOT_INJECTED";
	}
	return rawError;
}

function normalizeMethodPayload(result) {
	const payload =
		result && typeof result === "object"
			? { ...result }
			: { ok: true, data: result };

	if (payload.error) {
		const rawError = String(payload.raw_error || payload.error);
		payload.error = normalizeMethodError(payload.error);
		if (!payload.raw_error && payload.error !== rawError) {
			payload.raw_error = rawError;
		}
	}

	if (typeof payload.ok !== "boolean") {
		payload.ok = !payload.error;
	}

	return payload;
}

function finalizeMethodPayload(method, result, flowTab) {
	const payload = normalizeMethodPayload(result);
	const reply = {
		method,
		timestamp: new Date().toISOString(),
		...buildFlowTabSnapshot(flowTab),
		...payload,
	};

	const receivedField = getMethodStageField(method, "received");
	if (receivedField) {
		reply[receivedField] = true;
	}

	const sentField = getMethodStageField(method, "sent");
	if (sentField) {
		reply[sentField] = true;
	}

	return reply;
}

function promiseWithTimeout(
	task,
	timeoutMs,
	timeoutError = "ERR_MESSAGE_RESPONSE_TIMEOUT",
) {
	return new Promise((resolve, reject) => {
		const timer = setTimeout(() => reject(new Error(timeoutError)), timeoutMs);
		Promise.resolve(task)
			.then((value) => {
				clearTimeout(timer);
				resolve(value);
			})
			.catch((error) => {
				clearTimeout(timer);
				reject(error);
			});
	});
}

async function executeWsMethodAndReply(msg, handler) {
	const method = msg?.method || "UNKNOWN_METHOD";
	const flowTab = await getFlowTabSafe();
	logWsMethodStage(method, "received", flowTab);

	try {
		const timeoutMs = WS_METHOD_TIMEOUT_MS[method] || 10000;
		const result = await promiseWithTimeout(
			Promise.resolve().then(handler),
			timeoutMs,
		);
		const reply = finalizeMethodPayload(method, result, flowTab);
		logWsMethodStage(method, "sent", flowTab, {
			ok: reply.ok,
			error: reply.error || null,
		});
		return reply;
	} catch (error) {
		const reply = finalizeMethodPayload(
			method,
			{
				ok: false,
				error: String(error?.message || error || "ERR_UNKNOWN_METHOD_FAILURE"),
			},
			flowTab,
		);
		logWsMethodStage(method, "sent", flowTab, {
			ok: false,
			error: reply.error || null,
		});
		return reply;
	}
}

async function getFlowTab() {
	const preferredUrl = await getStoredFlowProjectUrl();
	const tabs = await getFlowTabs();
	if (!tabs.length) {
		return null;
	}

	const focusedActiveTab = await getFocusedActiveBrowserTab();
	return buildFlowTabSelectionBinding(tabs, preferredUrl, focusedActiveTab)
		?.selectedTab;
}

async function getFlowTabs() {
	return await chrome.tabs.query({
		url: [
			"https://labs.google/fx/tools/flow*",
			"https://labs.google/fx/*/tools/flow*",
		],
	});
}

async function resolveLiveFlowEditorTab(preferredUrl = null, mode = null) {
	const tabs = await getFlowTabs();
	if (!tabs.length) {
		return null;
	}
	const focusedActiveTab = await getFocusedActiveBrowserTab();
	const binding = buildFlowTabSelectionBinding(
		tabs,
		preferredUrl,
		focusedActiveTab,
	);
	const selected = binding?.selectedTab || null;
	const editorTabs = tabs.filter(
		(tab) => isProjectEditorUrl(tab?.url) && !isRootFlowUrl(tab?.url),
	);
	const ranked = buildUniqueFlowProbeCandidates(
		editorTabs.length ? editorTabs : tabs,
		selected && isProjectEditorUrl(selected?.url) && !isRootFlowUrl(selected?.url)
			? selected
			: null,
	);
	for (const candidate of ranked) {
		const probe = await probeFlowEditorCandidate(candidate, mode);
		if (probe.ok) {
			return (await getTabSafe(candidate.id)) || candidate;
		}
	}
	return selected || null;
}

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

function isSameFlowProjectUrl(leftUrl, rightUrl) {
	const left = normalizeFlowProjectUrl(leftUrl);
	const right = normalizeFlowProjectUrl(rightUrl);
	return Boolean(left && right && left === right);
}

function flowTabLooksBroken(tab) {
	const title = String(tab?.title || "").toLowerCase();
	return (
		title.includes("something went wrong") ||
		title.includes("application error")
	);
}

function findFocusedActiveFlowEditorTab(tabs, focusedActiveTab = null) {
	const focusedTabId = Number(focusedActiveTab?.id || 0);
	if (focusedTabId > 0) {
		const focusedMatch =
			tabs.find((tab) => Number(tab?.id || 0) === focusedTabId) || focusedActiveTab;
		if (
			focusedMatch?.id &&
			focusedMatch?.active &&
			isProjectEditorUrl(focusedMatch?.url) &&
			!isRootFlowUrl(focusedMatch?.url)
		) {
			return focusedMatch;
		}
	}
	return (
		tabs.find(
			(tab) =>
				tab?.active &&
				isProjectEditorUrl(tab?.url) &&
				!isRootFlowUrl(tab?.url),
		) || null
	);
}

function buildFlowTabSelectionBinding(
	tabs,
	preferredUrl = null,
	focusedActiveTab = null,
	selectedTabOverride = null,
) {
	const list = Array.isArray(tabs) ? tabs.filter(Boolean) : [];
	const initialSelectedTab =
		selectedTabOverride || selectBestFlowTab(list, preferredUrl);
	const activeEditorTab = findFocusedActiveFlowEditorTab(list, focusedActiveTab);
	const normalizedPreferredUrl = normalizeFlowProjectUrl(preferredUrl);
	const activeEditorMatchesPreferred = normalizedPreferredUrl
		? isSameFlowProjectUrl(activeEditorTab?.url, normalizedPreferredUrl)
		: Boolean(activeEditorTab?.id);
	const sameProjectUrl = Boolean(
		activeEditorMatchesPreferred ||
			(!normalizedPreferredUrl &&
				isSameFlowProjectUrl(initialSelectedTab?.url, activeEditorTab?.url)),
	);
	let selectedTab = initialSelectedTab || activeEditorTab || null;
	let reboundToActiveEditorTab = false;
	let error = null;

	if (!activeEditorTab?.id) {
		error = "FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND";
	} else if (selectedTab?.id && Number(selectedTab.id) !== Number(activeEditorTab.id)) {
		if (sameProjectUrl) {
			selectedTab = activeEditorTab;
			reboundToActiveEditorTab = true;
		} else {
			error = "FLOW_TARGET_TAB_MISMATCH";
		}
	} else if (!selectedTab?.id && activeEditorMatchesPreferred) {
		selectedTab = activeEditorTab;
	}

	return {
		initialSelectedTab,
		selectedTab: selectedTab || null,
		activeEditorTab: activeEditorTab || null,
		selectedTabActive: Boolean(selectedTab?.active),
		selectedTabUrl: String(selectedTab?.url || "").trim() || null,
		activeEditorTabUrl: String(activeEditorTab?.url || "").trim() || null,
		sameProjectUrl,
		reboundToActiveEditorTab,
		error,
	};
}

function classifyFlowPathState(url) {
	const value = String(url || "").trim();
	if (!value) {
		return "NO_FLOW_TAB";
	}
	if (isAbnormalRedirectUrl(value)) {
		return "ABNORMAL_REDIRECT";
	}
	if (/^https:\/\/accounts\.google\.com\//i.test(value)) {
		return "FLOW_AUTH_ROUTE";
	}
	if (isProjectEditorUrl(value) && !isRootFlowUrl(value)) {
		return "FLOW_PROJECT_EDITOR";
	}
	if (isRootFlowUrl(value) && !isProjectEditorUrl(value)) {
		return "FLOW_ROOT";
	}
	if (/^https:\/\/labs\.google\/fx\//i.test(value)) {
		return "FLOW_OTHER";
	}
	return "NON_FLOW_URL";
}

function classifyAuthStateFromDiagnostic(flowUrl, pageDiagnostic = null) {
	const value = String(flowUrl || "").trim();
	const loginMarkers = Array.isArray(pageDiagnostic?.visible_login_markers)
		? pageDiagnostic.visible_login_markers
		: [];
	if (/^https:\/\/accounts\.google\.com\//i.test(value) || loginMarkers.length) {
		return "AUTH_REQUIRED";
	}
	if (/^https:\/\/labs\.google\/fx\//i.test(value)) {
		return "LIKELY_AUTHENTICATED";
	}
	return "UNKNOWN";
}

function buildRuntimeDiagnosticPayload({
	flowUrl = null,
	preferredUrl = null,
	selectedTab = null,
	pageDiagnostic = null,
	openFlowResult = null,
} = {}) {
	const normalizedFlowUrl = String(
		flowUrl || selectedTab?.url || pageDiagnostic?.flow_url || "",
	).trim();
	const normalizedPreferredUrl = String(preferredUrl || "").trim();
	const title = String(
		pageDiagnostic?.document_title || selectedTab?.title || "",
	).toLowerCase();
	const visibleErrorMarkers = Array.isArray(pageDiagnostic?.visible_error_markers)
		? pageDiagnostic.visible_error_markers
		: [];
	const flowPathState = classifyFlowPathState(normalizedFlowUrl);
	const authState = classifyAuthStateFromDiagnostic(
		normalizedFlowUrl,
		pageDiagnostic,
	);
	const agentConnected = ws?.readyState === WebSocket.OPEN;
	const abnormalUrl =
		isAbnormalRedirectUrl(normalizedFlowUrl) ||
		isAbnormalRedirectUrl(openFlowResult?.flow_url_after)
			? String(normalizedFlowUrl || openFlowResult?.flow_url_after || "").trim()
			: null;
	let runtimeReason = agentConnected
		? "FLOW_RUNTIME_CONNECTED"
		: "EXTENSION_DISCONNECTED";
	let runtimeDetail = agentConnected
		? "Flow Kit background is connected to the local agent."
		: "Flow Kit extension WebSocket bridge is offline.";
	let targetProjectState = "UNKNOWN";
	let diagnosticCode = null;
	let diagnosticDetail = null;

	if (abnormalUrl) {
		runtimeReason = "ABNORMAL_REDIRECT";
		runtimeDetail = `Flow navigation landed on unexpected URL: ${abnormalUrl}`;
		targetProjectState = "ABNORMAL_REDIRECT";
		diagnosticCode = "ABNORMAL_REDIRECT";
		diagnosticDetail = runtimeDetail;
	} else if (!normalizedFlowUrl) {
		runtimeReason = agentConnected ? "NO_FLOW_TAB" : "EXTENSION_DISCONNECTED";
		runtimeDetail = "No Google Flow tab is currently open.";
		targetProjectState = "NO_FLOW_TAB";
		diagnosticCode = "NO_FLOW_TAB";
		diagnosticDetail = runtimeDetail;
	} else if (authState === "AUTH_REQUIRED") {
		runtimeReason = "FLOW_AUTH_REQUIRED";
		runtimeDetail = "Google authentication is required before Flow editor can open.";
		targetProjectState = "AUTH_REQUIRED";
		diagnosticCode = "FLOW_AUTH_REQUIRED";
		diagnosticDetail = runtimeDetail;
	} else if (
		normalizedPreferredUrl &&
		normalizedFlowUrl === normalizedPreferredUrl &&
		(visibleErrorMarkers.length ||
			title.includes("something went wrong") ||
			title.includes("application error"))
	) {
		runtimeReason = "TARGET_PROJECT_BROKEN";
		runtimeDetail =
			"Stored Flow project opened with visible error markers instead of a usable editor.";
		targetProjectState = "TARGET_PROJECT_BROKEN";
		diagnosticCode = "TARGET_PROJECT_BROKEN";
		diagnosticDetail = runtimeDetail;
	} else if (flowPathState === "FLOW_ROOT") {
		runtimeReason = agentConnected
			? "FLOW_ROOT_OPEN_INSTEAD_OF_EDITOR"
			: "AUTH_OK_BUT_EXTENSION_OFF";
		runtimeDetail = agentConnected
			? "Flow dashboard/root is open instead of a project editor."
			: "Flow dashboard/root is open, but the WebSocket bridge is offline.";
		targetProjectState = "FLOW_ROOT";
		diagnosticCode = "FLOW_ROOT_OPEN_INSTEAD_OF_EDITOR";
		diagnosticDetail = runtimeDetail;
	} else if (flowPathState === "FLOW_PROJECT_EDITOR") {
		runtimeReason = agentConnected
			? "FLOW_EDITOR_READY"
			: "AUTH_OK_BUT_EXTENSION_OFF";
		runtimeDetail = agentConnected
			? "Flow project editor URL is active."
			: "Flow project editor URL is active, but the WebSocket bridge is offline.";
		targetProjectState = "EDITOR_URL_ACTIVE";
		diagnosticCode = agentConnected ? "FLOW_EDITOR_READY" : "AUTH_OK_BUT_EXTENSION_OFF";
		diagnosticDetail = runtimeDetail;
	} else if (/FLOW_PROJECT_EDITOR_NOT_OPEN/i.test(String(openFlowResult?.error || ""))) {
		runtimeReason = "FLOW_PROJECT_EDITOR_NOT_OPEN";
		runtimeDetail =
			"Preferred Flow project did not settle on an editor URL after navigation.";
		targetProjectState = "PREFERRED_PROJECT_NOT_OPEN";
		diagnosticCode = "FLOW_PROJECT_EDITOR_NOT_OPEN";
		diagnosticDetail = runtimeDetail;
	}

	return {
		ws_connected: agentConnected,
		runtime_reason: runtimeReason,
		runtime_detail: runtimeDetail,
		auth_state: authState,
		flow_path_state: flowPathState,
		target_project_state: targetProjectState,
		target_project_url: normalizedPreferredUrl || null,
		flow_tab_url: normalizedFlowUrl || null,
		fallback_editor_url: String(openFlowResult?.flow_url || "").trim() || null,
		stored_flow_project_url: normalizedPreferredUrl || null,
		last_bad_redirect_url: abnormalUrl,
		diagnostic_code: diagnosticCode,
		diagnostic_detail: diagnosticDetail,
	};
}

function shouldAdoptSelectedFlowProjectUrl(
	selectedTab,
	flowTabs = [],
	preferredUrl = null,
) {
	const normalizedSelectedUrl = String(selectedTab?.url || "").trim();
	if (
		!normalizedSelectedUrl ||
		!isProjectEditorUrl(normalizedSelectedUrl) ||
		isRootFlowUrl(normalizedSelectedUrl)
	) {
		return false;
	}

	const normalizedPreferredUrl = String(preferredUrl || "").trim();
	if (!normalizedPreferredUrl) {
		return true;
	}
	if (normalizedPreferredUrl === normalizedSelectedUrl) {
		return false;
	}

	const exactPreferredTabOpen = Array.isArray(flowTabs)
		? flowTabs.some(
				(tab) => String(tab?.url || "").trim() === normalizedPreferredUrl,
			)
		: false;

	return Boolean(selectedTab?.active) || flowTabs.length === 1 || !exactPreferredTabOpen;
}

async function adoptSelectedFlowProjectUrlIfNeeded(
	selectedTab,
	flowTabs = [],
	preferredUrl = null,
) {
	const normalizedPreferredUrl = String(preferredUrl || "").trim() || null;
	if (
		!shouldAdoptSelectedFlowProjectUrl(
			selectedTab,
			Array.isArray(flowTabs) ? flowTabs : [],
			normalizedPreferredUrl,
		)
	) {
		return {
			preferred_flow_project_url: normalizedPreferredUrl,
			sync_result: null,
		};
	}

	const syncResult = await syncStoredFlowProjectUrlToActiveEditor(selectedTab?.url, {
		currentStoredUrl: normalizedPreferredUrl,
		openedViaRecovery: true,
		allowWhenMissing: true,
		force: true,
	});

	return {
		preferred_flow_project_url:
			syncResult?.stored_flow_project_url ||
			String(selectedTab?.url || "").trim() ||
			normalizedPreferredUrl,
		sync_result: syncResult,
	};
}

function selectBestFlowTab(tabs, preferredUrl = null) {
	if (!tabs.length) {
		console.log("[FlowAgent] No tabs found in query");
		return null;
	}

	console.log(
		"[FlowAgent] Found Flow tabs:",
		tabs.map((t) => ({ id: t.id, url: t.url, status: t.status })),
	);

	const normalizedPreferredUrl = normalizeFlowProjectUrl(preferredUrl);
	const activeEditorTab = findFocusedActiveFlowEditorTab(tabs);
	if (
		activeEditorTab?.id &&
		(!normalizedPreferredUrl ||
			isSameFlowProjectUrl(activeEditorTab?.url, normalizedPreferredUrl))
	) {
		console.log("[FlowAgent] Using focused active editor tab:", {
			id: activeEditorTab.id,
			url: activeEditorTab.url,
			title: activeEditorTab.title,
		});
		return activeEditorTab;
	}
	if (normalizedPreferredUrl) {
		const exactMatches = tabs.filter((tab) =>
			isSameFlowProjectUrl(tab?.url, normalizedPreferredUrl),
		);
		const exactMatch =
			exactMatches.find(
				(tab) =>
					tab?.active &&
					isProjectEditorUrl(tab?.url) &&
					!isRootFlowUrl(tab?.url),
			) ||
			exactMatches.find((tab) => !flowTabLooksBroken(tab)) ||
			exactMatches[0] ||
			null;
		if (exactMatch) {
			const exactLooksBroken = flowTabLooksBroken(exactMatch);
			const activeEditorDiffers =
				activeEditorTab &&
				!isSameFlowProjectUrl(activeEditorTab?.url, normalizedPreferredUrl);
			if (!activeEditorDiffers && !exactLooksBroken) {
				console.log("[FlowAgent] Using exact preferred match:", exactMatch.url);
				return exactMatch;
			}
			console.warn(
				"[FlowAgent] Bypassing stored preferred Flow tab in favor of active/current editor",
				{
					preferred_url: normalizedPreferredUrl,
					active_editor_url: activeEditorTab?.url || null,
					exact_looks_broken: exactLooksBroken,
				},
			);
		}
	}

	const scored = tabs
		.map((tab) => {
			const title = String(tab.title || "").toLowerCase();
			let score = 0;
			if (isProjectEditorUrl(tab.url)) score += 50;
			if (!isRootFlowUrl(tab.url)) score += 10;
			if (tab.active) score += 25;
			if (tab.status === "complete") score += 10;
			if (title.includes("something went wrong")) score -= 100;
			if (title.includes("application error")) score -= 100;
			if (/google flow - [a-z]{3}\s+\d{1,2},/i.test(String(tab.title || "")))
				score += 20;
			return { tab, score };
		})
		.sort((a, b) => b.score - a.score);

	if (scored.length && scored[0].score > -50) {
		console.log("[FlowAgent] Using scored Flow tab:", {
			id: scored[0].tab.id,
			url: scored[0].tab.url,
			title: scored[0].tab.title,
			score: scored[0].score,
		});
		return scored[0].tab;
	}

	const nonRootTab = tabs.find((tab) => !isRootFlowUrl(tab.url));
	if (nonRootTab) {
		console.log("[FlowAgent] Using non-root tab:", nonRootTab.url);
		return nonRootTab;
	}

	console.log("[FlowAgent] Falling back to first tab:", tabs[0].url);
	return tabs[0];
}

function buildUniqueFlowProbeCandidates(tabs, preferredTab = null) {
	const orderedTabs = [
		preferredTab,
		...tabs.filter((tab) => tab?.id !== preferredTab?.id),
	].filter(Boolean);
	const seen = new Map();
	const unique = [];
	for (const tab of orderedTabs) {
		const url = String(tab?.url || "").trim();
		const normalizedProjectUrl = normalizeFlowProjectUrl(tab?.url);
		const key =
			normalizedProjectUrl &&
			isProjectEditorUrl(tab?.url) &&
			!isRootFlowUrl(tab?.url)
				? `editor:${normalizedProjectUrl}`
				: `tab:${tab.id ?? url}`;
		if (!seen.has(key)) {
			seen.set(key, unique.length);
			unique.push(tab);
			continue;
		}
		const existingIndex = seen.get(key);
		const existingTab = unique[existingIndex];
		const shouldReplace =
			(Boolean(tab?.active) && !existingTab?.active) ||
			(Boolean(tab?.status === "complete") && existingTab?.status !== "complete");
		if (shouldReplace) {
			unique[existingIndex] = tab;
		}
	}
	return unique;
}

function summarizeFlowTab(tab) {
	if (!tab) {
		return null;
	}
	return {
		tab_id: tab.id ?? null,
		window_id: tab.windowId ?? null,
		active: Boolean(tab.active),
		status: tab.status || null,
		title: tab.title || null,
		url: tab.url || null,
		is_root_flow_url: isRootFlowUrl(tab.url),
		looks_like_editor_url: isProjectEditorUrl(tab.url),
	};
}

function buildDuplicateFlowEditorInventory(tabs = []) {
	const grouped = new Map();
	for (const tab of Array.isArray(tabs) ? tabs : []) {
		if (!isProjectEditorUrl(tab?.url) || isRootFlowUrl(tab?.url)) {
			continue;
		}
		const normalizedProjectUrl = normalizeFlowProjectUrl(tab?.url);
		if (!normalizedProjectUrl) {
			continue;
		}
		if (!grouped.has(normalizedProjectUrl)) {
			grouped.set(normalizedProjectUrl, []);
		}
		grouped.get(normalizedProjectUrl).push({
			tab_id: tab?.id ?? null,
			window_id: tab?.windowId ?? null,
			active: Boolean(tab?.active),
			status: tab?.status || null,
			url: tab?.url || null,
			title: tab?.title || null,
		});
	}
	return Array.from(grouped.entries())
		.filter(([, duplicates]) => duplicates.length > 1)
		.map(([normalized_project_url, duplicates]) => ({
			normalized_project_url,
			duplicate_count: duplicates.length,
			tabs: duplicates,
		}));
}

function extractFlowProjectId(url) {
	const value = String(url || "").trim();
	const match = value.match(/\/project\/([^/?#]+)/i);
	return match?.[1] || null;
}

function determineFlowBootstrapStartState(flowTabs = [], focusedActiveTab = null) {
	const tabs = Array.isArray(flowTabs) ? flowTabs.filter(Boolean) : [];
	const editorTabs = tabs.filter(
		(tab) => isProjectEditorUrl(tab?.url) && !isRootFlowUrl(tab?.url),
	);
	const rootTabs = tabs.filter((tab) => isRootFlowUrl(tab?.url));
	const activeEditorTab = findFocusedActiveFlowEditorTab(editorTabs, focusedActiveTab);
	if (editorTabs.length) {
		return {
			startedFrom: "EXISTING_PROJECT_EDITOR",
			entryTab:
				activeEditorTab ||
				editorTabs
					.slice()
					.sort((left, right) => Number(right?.id || 0) - Number(left?.id || 0))[0] ||
				null,
			editorTabs,
			rootTabs,
			activeEditorTab: activeEditorTab || null,
		};
	}
	if (rootTabs.length) {
		const focusedRootTab =
			(focusedActiveTab?.id &&
				rootTabs.find(
					(tab) => Number(tab?.id || 0) === Number(focusedActiveTab?.id || 0),
				)) ||
			rootTabs.find((tab) => tab?.active) ||
			rootTabs[0] ||
			null;
		return {
			startedFrom: "ROOT_FLOW_PAGE",
			entryTab: focusedRootTab,
			editorTabs,
			rootTabs,
			activeEditorTab: null,
		};
	}
	return {
		startedFrom: "NO_FLOW_TAB",
		entryTab: null,
		editorTabs,
		rootTabs,
		activeEditorTab: null,
	};
}

function rankFlowBootstrapEditorCandidates(editorTabs = [], focusedActiveTab = null) {
	const activeEditorTab = findFocusedActiveFlowEditorTab(editorTabs, focusedActiveTab);
	return [...(Array.isArray(editorTabs) ? editorTabs : [])].sort((left, right) => {
		if (Number(left?.id || 0) === Number(activeEditorTab?.id || 0)) return -1;
		if (Number(right?.id || 0) === Number(activeEditorTab?.id || 0)) return 1;
		if (Boolean(left?.active) !== Boolean(right?.active)) {
			return left?.active ? -1 : 1;
		}
		if (String(left?.status || "") !== String(right?.status || "")) {
			if (left?.status === "complete") return -1;
			if (right?.status === "complete") return 1;
		}
		return Number(right?.id || 0) - Number(left?.id || 0);
	});
}

function mapFlowBootstrapBindingFailureCode(preflightError) {
	switch (String(preflightError || "")) {
		case "FLOW_ACTIVE_TAB_CONTENT_SCRIPT_NOT_READY":
			return "FLOW_PROJECT_CONTENT_SCRIPT_NOT_READY";
		case "FLOW_ACTIVE_TAB_ADD_MEDIA_LAUNCHER_NOT_FOUND":
			return "FLOW_PROJECT_EDITOR_SURFACE_NOT_READY";
		default:
			return "FLOW_PROJECT_EDITOR_TAB_BIND_FAILED";
	}
}

function mapOpenFlowNewProjectFailureCode(result) {
	const authState = classifyAuthStateFromDiagnostic(
		result?.flow_url || result?.location_href || "",
		result,
	);
	if (
		authState === "AUTH_REQUIRED" ||
		(Array.isArray(result?.visible_login_markers) &&
			result.visible_login_markers.length > 0)
	) {
		return "FLOW_LOGIN_REQUIRED";
	}
	switch (String(result?.error || "")) {
		case "FLOW_PROJECT_LIST_OR_LANDING_NOT_DETECTED":
			return "FLOW_ROOT_PAGE_NOT_READY";
		case "FLOW_PROJECT_CREATION_PATH_MISSING":
			return result?.new_project_clicked === true
				? "FLOW_CREATE_PROJECT_CLICK_FAILED"
				: "FLOW_CREATE_PROJECT_CONTROL_NOT_FOUND";
		case "FLOW_PROJECT_EDITOR_NOT_READY":
			return isProjectEditorUrl(result?.flow_url)
				? "FLOW_PROJECT_EDITOR_SURFACE_NOT_READY"
				: "FLOW_PROJECT_EDITOR_URL_TIMEOUT";
		default:
			if (String(result?.error || "").includes("ERR_MESSAGE")) {
				return "FLOW_ROOT_PAGE_NOT_READY";
			}
			return "FLOW_CREATE_PROJECT_CLICK_FAILED";
	}
}

async function getFocusedActiveBrowserTab() {
	try {
		const tabs = await chrome.tabs.query({
			active: true,
			lastFocusedWindow: true,
		});
		return tabs?.[0] || null;
	} catch (_) {
		return null;
	}
}

function isFlowContentScriptReadyForActiveTab(diagnostic) {
	if (!diagnostic || typeof diagnostic !== "object") {
		return false;
	}
	if (diagnostic.error || diagnostic.raw_error) {
		return false;
	}
	const contentScriptAlive =
		typeof diagnostic.content_script_alive === "boolean"
			? diagnostic.content_script_alive
			: Boolean(diagnostic.content_script_loaded);
	const buildMatch =
		typeof diagnostic.build_match === "boolean"
			? diagnostic.build_match
			: diagnostic.content_build_id
				? diagnostic.content_build_id === BUILD_ID
				: true;
	return Boolean(
		diagnostic.content_script_loaded &&
			contentScriptAlive &&
			diagnostic.runtime_ready &&
			buildMatch,
	);
}

function isActiveTabAddMediaLauncherReady(mode, diagnostic) {
	if (!diagnostic || typeof diagnostic !== "object") {
		return false;
	}
	const observedSlots = Array.isArray(diagnostic?.observed?.visibleUploadSlots)
		? diagnostic.observed.visibleUploadSlots.map((value) => String(value))
		: [];
	const editorCapabilityReady = Boolean(
		diagnostic?.editor_capability_ready === true ||
			diagnostic?.ui_contract_v2?.editor_capability_ready === true,
	);
	if (diagnostic?.blocking_modal_detected) {
		return false;
	}
	if (String(mode || "").trim().toUpperCase() !== "F2V") {
		return editorCapabilityReady;
	}
	// F2V: accept editorCapabilityReady OR strict_composer_ok (strong signals),
	// OR a live composer with visible upload slots (surface-signal fallback that handles
	// the case where configLauncher detection fails due to targetLooksLikePageShell
	// false-positive when the pill's closest button ancestor wraps "add media" text).
	const composerLive = Boolean(
		diagnostic?.composer_found && diagnostic?.composer_editable,
	);
	const uploadSlotsVisible =
		observedSlots.includes("Start") || observedSlots.includes("End");
	return Boolean(
		editorCapabilityReady ||
			diagnostic?.strict_composer_ok === true ||
			(composerLive && uploadSlotsVisible),
	);
}

function evaluateActiveFlowTabPreflight(
	binding,
	contentDiagnostic = null,
	pageDiagnostic = null,
	composerDiagnostic = null,
	mode = null,
) {
	const selectedTab = binding?.selectedTab || null;
	const activeEditorTab = binding?.activeEditorTab || null;
	const mergedContentDiagnostic =
		contentDiagnostic && typeof contentDiagnostic === "object"
			? contentDiagnostic
			: {};
	const mergedComposerDiagnostic =
		composerDiagnostic && typeof composerDiagnostic === "object"
			? {
					...mergedContentDiagnostic,
					...composerDiagnostic,
				}
			: mergedContentDiagnostic;
	const contentScriptAliveOnActiveTab =
		isFlowContentScriptReadyForActiveTab(mergedContentDiagnostic);
	// Reject a broken editor page as runtime authority. Real page-level evidence
	// (visible "Something went wrong"/error markers) means the bound project is a
	// dead Flow error surface even though its URL/title look like a valid editor.
	// Such a target must not keep winning just because it is the active/stored tab.
	const brokenErrorMarkers = Array.isArray(pageDiagnostic?.visible_error_markers)
		? pageDiagnostic.visible_error_markers.map((value) => String(value))
		: [];
	const activeEditorBroken = Boolean(
		activeEditorTab?.id &&
			(brokenErrorMarkers.length > 0 || flowTabLooksBroken(activeEditorTab)),
	);
	const safeToClickActiveTab =
		!activeEditorBroken &&
		contentScriptAliveOnActiveTab &&
		isActiveTabAddMediaLauncherReady(
			mode,
			mergedComposerDiagnostic || pageDiagnostic || mergedContentDiagnostic,
		);
	const preflight = {
		selected_tab_id: Number(selectedTab?.id || 0),
		active_editor_tab_id: Number(activeEditorTab?.id || 0),
		selected_tab_active: Boolean(selectedTab?.active),
		same_project_url: Boolean(binding?.sameProjectUrl),
		content_script_alive_on_active_tab: contentScriptAliveOnActiveTab,
		safe_to_click_active_tab: safeToClickActiveTab,
		broken_target_rejected: activeEditorBroken,
	};
	let error = null;
	if (!activeEditorTab?.id) {
		error = "FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND";
	} else if (activeEditorBroken) {
		// Broken editor surface — treat as no usable active editor so strict
		// recovery looks for a healthy editor (or opens a fresh one) instead of
		// binding the dead project.
		error = "FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND";
	} else if (binding?.error === "FLOW_TARGET_TAB_MISMATCH") {
		error = "FLOW_TARGET_TAB_MISMATCH";
	} else if (!selectedTab?.id || Number(selectedTab.id) !== Number(activeEditorTab.id)) {
		error = "FLOW_REBOUND_TO_ACTIVE_TAB_FAILED";
	} else if (!contentScriptAliveOnActiveTab) {
		error = "FLOW_ACTIVE_TAB_CONTENT_SCRIPT_NOT_READY";
	} else if (!safeToClickActiveTab) {
		error = "FLOW_ACTIVE_TAB_ADD_MEDIA_LAUNCHER_NOT_FOUND";
	}
	return {
		ok: !error,
		error,
		preflight,
		selectedTab,
		activeEditorTab,
		reboundToActiveEditorTab: Boolean(binding?.reboundToActiveEditorTab),
		selectedTabActive: Boolean(selectedTab?.active),
		selectedTabUrl: String(selectedTab?.url || "").trim() || null,
		activeEditorTabUrl: String(activeEditorTab?.url || "").trim() || null,
		sameProjectUrl: Boolean(binding?.sameProjectUrl),
		contentScriptAliveOnActiveTab,
		safeToClickActiveTab,
		brokenTargetRejected: activeEditorBroken,
		brokenTargetUrl: activeEditorBroken
			? String(activeEditorTab?.url || "").trim() || null
			: null,
		brokenTargetMarkers: activeEditorBroken ? brokenErrorMarkers : [],
	};
}

async function getTabSafe(tabId) {
	if (!tabId) {
		return null;
	}
	try {
		return await chrome.tabs.get(tabId);
	} catch (_) {
		return null;
	}
}

async function buildActiveFlowTabPreflight(mode = "F2V", options = {}) {
	const preferredUrl =
		options?.preferredUrl !== undefined
			? options.preferredUrl
			: await getStoredFlowProjectUrl();
	const tabs = Array.isArray(options?.tabs)
		? options.tabs.filter(Boolean)
		: await getFlowTabs();
	const focusedActiveTab =
		options?.focusedActiveTab !== undefined
			? options.focusedActiveTab
			: await getFocusedActiveBrowserTab();
	const binding = buildFlowTabSelectionBinding(
		tabs,
		preferredUrl,
		focusedActiveTab,
		options?.selectedTabOverride || null,
	);
	const duplicateTabInventory = buildDuplicateFlowEditorInventory(tabs);
	const targetTab =
		(await getTabSafe(binding?.selectedTab?.id || binding?.activeEditorTab?.id)) ||
		binding?.selectedTab ||
		binding?.activeEditorTab ||
		null;
	let contentDiagnostic = null;
	let pageDiagnostic = null;
	let composerDiagnostic = null;

	if (targetTab?.id) {
		await ensureFlowDomScript(targetTab.id);
		contentDiagnostic = await pingFlowDomScript(targetTab);
		if (isFlowContentScriptReadyForActiveTab(contentDiagnostic)) {
			pageDiagnostic = await sendTabMessageSafe(
				targetTab.id,
				{
					type: "FLOW_PAGE_STATE_DIAGNOSTIC",
					mode,
				},
				12000,
			);
			if (canUsePageDiagnosticForComposerReadiness(pageDiagnostic)) {
				composerDiagnostic = buildComposerReadinessFromPageDiagnostic(pageDiagnostic);
			} else {
				composerDiagnostic = await sendTabMessageSafe(
					targetTab.id,
					{
						type: "CHECK_FLOW_COMPOSER_READY",
						mode,
					},
					12000,
				);
			}
		}
	}

	const evaluated = evaluateActiveFlowTabPreflight(
		{
			...binding,
			selectedTab: targetTab || binding?.selectedTab || null,
		},
		contentDiagnostic,
		pageDiagnostic,
		composerDiagnostic,
		mode,
	);
	return {
		...evaluated,
		duplicate_tab_inventory: duplicateTabInventory,
		content_diagnostic: contentDiagnostic,
		page_diagnostic: pageDiagnostic,
		composer_diagnostic:
			composerDiagnostic || (canUsePageDiagnosticForComposerReadiness(pageDiagnostic)
				? buildComposerReadinessFromPageDiagnostic(pageDiagnostic)
				: null),
	};
}

async function recoverStrictActiveFlowTabTarget(
	mode = "F2V",
	options = {},
	deps = {},
) {
	const api = {
		getFlowTabs: deps.getFlowTabs || getFlowTabs,
		getTabSafe: deps.getTabSafe || getTabSafe,
		focusTab: deps.focusTab || focusTab,
		waitForTabComplete: deps.waitForTabComplete || waitForTabComplete,
		buildActiveFlowTabPreflight:
			deps.buildActiveFlowTabPreflight || buildActiveFlowTabPreflight,
		probeFlowEditorCandidate:
			deps.probeFlowEditorCandidate || probeFlowEditorCandidate,
		openFlowProjectFn:
			deps.openFlowProjectFn || openPreferredFlowProjectOrNewProject,
		settleFlowProjectAfterOpen:
			deps.settleFlowProjectAfterOpen || settleFlowProjectAfterOpen,
	};
	const preferredUrl =
		options?.preferredUrl !== undefined ? options.preferredUrl : null;
	const allowBootstrapRecovery = options?.allowBootstrapRecovery !== false;
	const initialTabs = Array.isArray(options?.tabs)
		? options.tabs.filter(Boolean)
		: await api.getFlowTabs();
	const initialPreflight =
		options?.activeTabPreflight ||
		(await api.buildActiveFlowTabPreflight(mode, {
			preferredUrl,
			tabs: initialTabs,
		}));

	if (initialPreflight?.ok) {
		return {
			ok: true,
			activeTabPreflight: initialPreflight,
			focus_recovery_attempted: false,
			focus_recovery_succeeded: false,
			focused_editor_tab_id: 0,
			bootstrap_recovery_attempted: false,
			bootstrap_recovery_succeeded: false,
			bootstrapped_editor_tab_id: 0,
		};
	}

	if (String(initialPreflight?.error || "") !== "FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND") {
		return {
			ok: false,
			activeTabPreflight: initialPreflight,
			focus_recovery_attempted: false,
			focus_recovery_succeeded: false,
			focused_editor_tab_id: 0,
			bootstrap_recovery_attempted: false,
			bootstrap_recovery_succeeded: false,
			bootstrapped_editor_tab_id: 0,
		};
	}

	const selectedTab = selectBestFlowTab(initialTabs, preferredUrl);
	const editorTabs = initialTabs.filter(
		(tab) => isProjectEditorUrl(tab?.url) && !isRootFlowUrl(tab?.url),
	);
	const preferredProbeTab =
		selectedTab &&
		isProjectEditorUrl(selectedTab?.url) &&
		!isRootFlowUrl(selectedTab?.url)
			? selectedTab
			: null;
	const rankedEditorTabs = rankFlowBootstrapEditorCandidates(editorTabs);
	const candidates = buildUniqueFlowProbeCandidates(
		rankedEditorTabs,
		preferredProbeTab,
	);

	let anyEditorProbeOk = false;
	let anyEditorProbeAlive = false;
	let lastRecoveredPreflight = null;
	let lastFocusedEditorTabId = 0;
	for (const candidateTab of candidates) {
		const probe = await api.probeFlowEditorCandidate(candidateTab, mode);
		const probeShowsLiveEditor = Boolean(
			isFlowContentScriptReadyForActiveTab(probe?.diagnostic) &&
				isProjectEditorUrl(probe?.tab?.url || candidateTab?.url),
		);
		if (!probe?.ok && !probeShowsLiveEditor) {
			continue;
		}
		if (probeShowsLiveEditor) {
			anyEditorProbeAlive = true;
		}
		if (probe?.ok) {
			anyEditorProbeOk = true;
		}
		let focusedTab = (await api.getTabSafe(candidateTab?.id)) || candidateTab;
		try {
			focusedTab = (await api.focusTab(focusedTab)) || focusedTab;
		} catch (_) {}
		try {
			focusedTab = (await api.waitForTabComplete(focusedTab.id, 20000)) || focusedTab;
		} catch (_) {
			focusedTab = (await api.getTabSafe(focusedTab.id)) || focusedTab;
		}
		lastFocusedEditorTabId = Number(focusedTab?.id || 0);
		const refreshedTabs = await api.getFlowTabs();
		const recoveredPreflight = await api.buildActiveFlowTabPreflight(mode, {
			preferredUrl: focusedTab?.url || preferredUrl,
			tabs:
				refreshedTabs.length > 0
					? refreshedTabs
					: [
							focusedTab,
							...initialTabs.filter(
								(tab) => Number(tab?.id || 0) !== Number(focusedTab?.id || 0),
							),
						],
			focusedActiveTab: focusedTab,
			selectedTabOverride: focusedTab,
		});
		lastRecoveredPreflight = recoveredPreflight || lastRecoveredPreflight;
		if (recoveredPreflight?.ok) {
			return {
				ok: true,
				activeTabPreflight: recoveredPreflight,
				focus_recovery_attempted: true,
				focus_recovery_succeeded: true,
				focused_editor_tab_id: Number(focusedTab?.id || 0),
				bootstrap_recovery_attempted: false,
				bootstrap_recovery_succeeded: false,
				bootstrapped_editor_tab_id: 0,
			};
		}
	}

	// REOPEN GUARD — a live Flow project editor is already open (a candidate tab
	// probed OK and was focused) but its active-tab preflight gate did not pass
	// (e.g. launcher-readiness race right after focus). Opening/creating a SECOND
	// project here would duplicate the editor and invalidate B.2A. Fail closed and
	// surface the real preflight blocker instead of silently bootstrapping a new
	// project. The caller reads activeTabPreflight.error, so the precise existing
	// blocker (e.g. FLOW_ACTIVE_TAB_ADD_MEDIA_LAUNCHER_NOT_FOUND) is what surfaces;
	// FLOW_PROJECT_REOPEN_LOOP is recorded on the recovery envelope as the reason
	// the bootstrap was suppressed.
	if (anyEditorProbeAlive || anyEditorProbeOk) {
		return {
			ok: false,
			error: "FLOW_PROJECT_REOPEN_LOOP",
			reopen_suppressed: true,
			activeTabPreflight: lastRecoveredPreflight || initialPreflight,
			focus_recovery_attempted: true,
			focus_recovery_succeeded: false,
			focused_editor_tab_id: lastFocusedEditorTabId,
			bootstrap_recovery_attempted: false,
			bootstrap_recovery_succeeded: false,
			bootstrapped_editor_tab_id: 0,
		};
	}

	if (!allowBootstrapRecovery) {
		return {
			ok: false,
			activeTabPreflight: lastRecoveredPreflight || initialPreflight,
			focus_recovery_attempted: candidates.length > 0,
			focus_recovery_succeeded: false,
			focused_editor_tab_id: lastFocusedEditorTabId,
			bootstrap_recovery_attempted: false,
			bootstrap_recovery_succeeded: false,
			bootstrapped_editor_tab_id: 0,
			bootstrap_recovery_blocked: true,
		};
	}

	// When the rejected target was a broken Flow editor page, the remembered
	// (preferred) project URL is the dead one. Do NOT pass it to the open fallback
	// or it would re-navigate to the same broken project — open a fresh project
	// instead by dropping the broken preferred URL.
	const brokenPreferredUrl = Boolean(
		initialPreflight?.brokenTargetRejected || lastRecoveredPreflight?.brokenTargetRejected,
	);
	const bootstrapPreferredUrl = brokenPreferredUrl ? null : preferredUrl;
	let openFlowResult = null;
	let settledTab = null;
	try {
		openFlowResult = await api.openFlowProjectFn(mode, bootstrapPreferredUrl);
		settledTab = await api.settleFlowProjectAfterOpen(openFlowResult);
	} catch (_) {}
	if (settledTab?.id) {
		const refreshedTabs = await api.getFlowTabs();
		const bootstrappedPreflight = await api.buildActiveFlowTabPreflight(mode, {
			preferredUrl: settledTab?.url || preferredUrl,
			tabs:
				refreshedTabs.length > 0
					? refreshedTabs
					: [
							settledTab,
							...initialTabs.filter(
								(tab) => Number(tab?.id || 0) !== Number(settledTab?.id || 0),
							),
						],
			focusedActiveTab: settledTab,
			selectedTabOverride: settledTab,
		});
		if (bootstrappedPreflight?.ok) {
			return {
				ok: true,
				activeTabPreflight: bootstrappedPreflight,
				focus_recovery_attempted: candidates.length > 0,
				focus_recovery_succeeded: false,
				focused_editor_tab_id: 0,
				bootstrap_recovery_attempted: true,
				bootstrap_recovery_succeeded: true,
				bootstrapped_editor_tab_id: Number(settledTab?.id || 0),
			};
		}
	}

	return {
		ok: false,
		activeTabPreflight: initialPreflight,
		focus_recovery_attempted: candidates.length > 0,
		focus_recovery_succeeded: false,
		focused_editor_tab_id: 0,
		bootstrap_recovery_attempted: true,
		bootstrap_recovery_succeeded: false,
		bootstrapped_editor_tab_id: 0,
	};
}

async function bootstrapFlowProjectEditorForB2A0(mode = "F2V", deps = {}) {
	const api = {
		getStoredFlowProjectUrl: deps.getStoredFlowProjectUrl || getStoredFlowProjectUrl,
		getFlowTabs: deps.getFlowTabs || getFlowTabs,
		getFocusedActiveBrowserTab:
			deps.getFocusedActiveBrowserTab || getFocusedActiveBrowserTab,
		getFlowTab: deps.getFlowTab || getFlowTab,
		getTabSafe: deps.getTabSafe || getTabSafe,
		focusTab: deps.focusTab || focusTab,
		openTabInNormalWindow: deps.openTabInNormalWindow || openTabInNormalWindow,
		waitForTabComplete: deps.waitForTabComplete || waitForTabComplete,
		ensureFlowDomScript: deps.ensureFlowDomScript || ensureFlowDomScript,
		pingFlowDomScript: deps.pingFlowDomScript || pingFlowDomScript,
		sendTabMessageSafe: deps.sendTabMessageSafe || sendTabMessageSafe,
		buildActiveFlowTabPreflight:
			deps.buildActiveFlowTabPreflight || buildActiveFlowTabPreflight,
		probeFlowEditorCandidate:
			deps.probeFlowEditorCandidate || probeFlowEditorCandidate,
		handleOpenFlowNewProject: deps.handleOpenFlowNewProject || handleOpenFlowNewProject,
		settleFlowProjectAfterOpen:
			deps.settleFlowProjectAfterOpen || settleFlowProjectAfterOpen,
		classifyAuthStateFromDiagnostic:
			deps.classifyAuthStateFromDiagnostic || classifyAuthStateFromDiagnostic,
	};
	const rootUrl = "https://labs.google/fx/tools/flow";
	const stageEvents = [];
	const proof = {
		flow_entry_url: rootUrl,
		started_from: "NO_FLOW_TAB",
		created_new_project: false,
		selected_tab_id_before: 0,
		selected_tab_id_after: 0,
		selected_tab_url_after: null,
		project_id: null,
		content_script_ready: false,
		editor_surface_ready: false,
		safe_to_run_b2a: false,
		stopped_before_add_media: true,
	};
	const recordStage = (stage, status, message = null) => {
		stageEvents.push({ stage, status, message });
	};
	const buildFailure = (error, stage = null, message = null) => {
		if (stage) {
			recordStage(stage, "FAIL", message || error);
		}
		return {
			ok: false,
			error,
			detail: message || error,
			stages: stageEvents.map((item) => item.stage),
			stage_events: stageEvents,
			...proof,
		};
	};
	const finalizeBoundEditor = async (projectTab, startedFrom, extra = {}) => {
		let focusedTab = (await api.getTabSafe(projectTab?.id)) || projectTab || null;
		if (!focusedTab?.id) {
			return buildFailure(
				"FLOW_PROJECT_EDITOR_TAB_BIND_FAILED",
				"F2V_V2A0_PROJECT_EDITOR_TAB_BOUND",
				"FLOW_PROJECT_EDITOR_TAB_BIND_FAILED",
			);
		}
		try {
			focusedTab = (await api.focusTab(focusedTab)) || focusedTab;
		} catch (_) {}
		try {
			focusedTab = (await api.waitForTabComplete(focusedTab.id, 20000)) || focusedTab;
		} catch (_) {
			focusedTab = (await api.getTabSafe(focusedTab.id)) || focusedTab;
		}
		const preflight = await api.buildActiveFlowTabPreflight(mode, {
			preferredUrl: focusedTab?.url || null,
			selectedTabOverride: focusedTab,
		});
		if (!preflight?.ok) {
			const mappedError = mapFlowBootstrapBindingFailureCode(preflight?.error);
			const failStage =
				mappedError === "FLOW_PROJECT_CONTENT_SCRIPT_NOT_READY"
					? "F2V_V2A0_CONTENT_SCRIPT_READY"
					: mappedError === "FLOW_PROJECT_EDITOR_SURFACE_NOT_READY"
						? "F2V_V2A0_EDITOR_SURFACE_READY"
						: "F2V_V2A0_PROJECT_EDITOR_TAB_BOUND";
			return buildFailure(mappedError, failStage, preflight?.error || mappedError);
		}
		proof.started_from = startedFrom;
		proof.selected_tab_id_after = Number(
			preflight?.preflight?.selected_tab_id || focusedTab?.id || 0,
		);
		proof.selected_tab_url_after =
			preflight?.selectedTabUrl || focusedTab?.url || null;
		proof.project_id = extractFlowProjectId(proof.selected_tab_url_after);
		proof.content_script_ready = Boolean(
			preflight?.preflight?.content_script_alive_on_active_tab,
		);
		proof.editor_surface_ready = Boolean(
			preflight?.preflight?.safe_to_click_active_tab,
		);
		proof.safe_to_run_b2a = Boolean(preflight?.ok);
		recordStage(
			"F2V_V2A0_PROJECT_EDITOR_TAB_BOUND",
			"PASS",
			JSON.stringify({
				selected_tab_id: proof.selected_tab_id_after,
				selected_tab_url: proof.selected_tab_url_after,
				rebound_to_active_editor_tab: Boolean(
					preflight?.reboundToActiveEditorTab,
				),
			}),
		);
		recordStage(
			"F2V_V2A0_CONTENT_SCRIPT_READY",
			"PASS",
			JSON.stringify({
				content_script_alive_on_active_tab: true,
			}),
		);
		recordStage(
			"F2V_V2A0_EDITOR_SURFACE_READY",
			"PASS",
			JSON.stringify({
				safe_to_click_active_tab: true,
			}),
		);
		recordStage(
			"F2V_V2A0_STOPPED_BEFORE_ADD_MEDIA",
			"PASS",
			JSON.stringify({
				add_media_clicked: false,
				upload_picker_opened: false,
				file_upload_attempted: false,
				add_to_prompt_attempted: false,
				settings_attempted: false,
				prompt_injection_attempted: false,
				generate_attempted: false,
			}),
		);
		return {
			ok: true,
			stages: stageEvents.map((item) => item.stage),
			stage_events: stageEvents,
			...proof,
			...extra,
		};
	};

	const preferredUrl = await api.getStoredFlowProjectUrl();
	const flowTabs = await api.getFlowTabs();
	const focusedActiveTab = await api.getFocusedActiveBrowserTab();
	const selectedBeforeTab = await api.getFlowTab();
	proof.selected_tab_id_before = Number(selectedBeforeTab?.id || 0);
	const startState = determineFlowBootstrapStartState(flowTabs, focusedActiveTab);
	proof.started_from = startState.startedFrom;
	proof.flow_entry_url = String(startState.entryTab?.url || rootUrl);

	if (startState.startedFrom === "EXISTING_PROJECT_EDITOR") {
		recordStage(
			"F2V_V2A0_EXISTING_PROJECT_EDITOR_FOUND",
			"PASS",
			JSON.stringify({
				editor_tab_ids: startState.editorTabs.map((tab) => Number(tab?.id || 0)),
				active_editor_tab_id: Number(startState.activeEditorTab?.id || 0),
			}),
		);
		for (const candidate of rankFlowBootstrapEditorCandidates(
			startState.editorTabs,
			focusedActiveTab,
		)) {
			const probe = await api.probeFlowEditorCandidate(candidate, mode);
			if (!probe?.ok) {
				continue;
			}
			let usableTab = (await api.getTabSafe(candidate.id)) || candidate;
			if (!usableTab?.active) {
				try {
					usableTab = (await api.focusTab(usableTab)) || usableTab;
				} catch (_) {}
			}
			return await finalizeBoundEditor(usableTab, "EXISTING_PROJECT_EDITOR", {
				created_new_project: false,
			});
		}
	}

	let flowEntryTab = startState.entryTab;
	if (startState.startedFrom === "NO_FLOW_TAB") {
		try {
			flowEntryTab = await api.openTabInNormalWindow(rootUrl);
			flowEntryTab = await api.waitForTabComplete(flowEntryTab.id, 30000);
		} catch (error) {
			return buildFailure(
				"FLOW_TAB_OPEN_FAILED",
				"F2V_V2A0_FLOW_ENTRY_OPENED_OR_FOUND",
				String(error?.message || error || "FLOW_TAB_OPEN_FAILED"),
			);
		}
	} else if (flowEntryTab?.id) {
		try {
			flowEntryTab = (await api.focusTab(flowEntryTab)) || flowEntryTab;
		} catch (_) {}
	}

	proof.flow_entry_url = String(flowEntryTab?.url || rootUrl);
	recordStage(
		"F2V_V2A0_FLOW_ENTRY_OPENED_OR_FOUND",
		"PASS",
		JSON.stringify({
			started_from: proof.started_from,
			flow_entry_url: proof.flow_entry_url,
			tab_id: Number(flowEntryTab?.id || 0),
		}),
	);
	if (!flowEntryTab?.id) {
		return buildFailure(
			"FLOW_TAB_OPEN_FAILED",
			"F2V_V2A0_FLOW_ENTRY_OPENED_OR_FOUND",
			"FLOW_TAB_OPEN_FAILED",
		);
	}

	await api.ensureFlowDomScript(flowEntryTab.id);
	const entryDiagnostic = await api.pingFlowDomScript(flowEntryTab);
	if (entryDiagnostic?.raw_error) {
		return buildFailure(
			"FLOW_ROOT_PAGE_NOT_READY",
			"F2V_V2A0_ROOT_PAGE_DETECTED_OR_SKIPPED",
			entryDiagnostic.raw_error,
		);
	}
	const entryPageDiagnostic = await api.sendTabMessageSafe(
		flowEntryTab.id,
		{
			type: "FLOW_PAGE_STATE_DIAGNOSTIC",
			mode,
		},
		12000,
	);
	const authState = api.classifyAuthStateFromDiagnostic(
		entryPageDiagnostic?.flow_url || flowEntryTab?.url || "",
		entryPageDiagnostic,
	);
	if (
		authState === "AUTH_REQUIRED" ||
		(Array.isArray(entryPageDiagnostic?.visible_login_markers) &&
			entryPageDiagnostic.visible_login_markers.length > 0)
	) {
		return buildFailure(
			"FLOW_LOGIN_REQUIRED",
			"F2V_V2A0_FLOW_AUTHENTICATED",
			"FLOW_LOGIN_REQUIRED",
		);
	}
	recordStage(
		"F2V_V2A0_FLOW_AUTHENTICATED",
		"PASS",
		JSON.stringify({
			auth_state: authState,
		}),
	);
	recordStage(
		"F2V_V2A0_ROOT_PAGE_DETECTED_OR_SKIPPED",
		"PASS",
		JSON.stringify({
			root_page_detected: Boolean(
				isRootFlowUrl(entryPageDiagnostic?.flow_url || flowEntryTab?.url || ""),
			),
		}),
	);

	const openFlowResult = await api.handleOpenFlowNewProject(mode);
	if (!openFlowResult?.ok) {
		const mappedError = mapOpenFlowNewProjectFailureCode(openFlowResult);
		if (mappedError === "FLOW_ROOT_PAGE_NOT_READY") {
			return buildFailure(
				mappedError,
				"F2V_V2A0_ROOT_PAGE_DETECTED_OR_SKIPPED",
				openFlowResult?.error || mappedError,
			);
		}
		if (mappedError === "FLOW_CREATE_PROJECT_CONTROL_NOT_FOUND") {
			return buildFailure(
				mappedError,
				"F2V_V2A0_CREATE_PROJECT_CONTROL_FOUND",
				openFlowResult?.error || mappedError,
			);
		}
		return buildFailure(
			mappedError,
			"F2V_V2A0_CREATE_PROJECT_CLICKED",
			openFlowResult?.error || mappedError,
		);
	}
	recordStage(
		"F2V_V2A0_CREATE_PROJECT_CONTROL_FOUND",
		"PASS",
		JSON.stringify({
			project_list_or_landing_detected: Boolean(
				openFlowResult?.project_list_or_landing_detected,
			),
		}),
	);
	proof.created_new_project = openFlowResult?.new_project_clicked === true;
	recordStage(
		"F2V_V2A0_CREATE_PROJECT_CLICKED",
		"PASS",
		JSON.stringify({
			new_project_clicked: openFlowResult?.new_project_clicked === true,
		}),
	);
	const settledTab = await api.settleFlowProjectAfterOpen(openFlowResult);
	if (!settledTab?.id || !isProjectEditorUrl(settledTab?.url)) {
		return buildFailure(
			"FLOW_PROJECT_EDITOR_URL_TIMEOUT",
			"F2V_V2A0_PROJECT_EDITOR_URL_CONFIRMED",
			openFlowResult?.error || "FLOW_PROJECT_EDITOR_URL_TIMEOUT",
		);
	}
	recordStage(
		"F2V_V2A0_PROJECT_EDITOR_URL_CONFIRMED",
		"PASS",
		JSON.stringify({
			selected_tab_id_after: Number(settledTab?.id || 0),
			selected_tab_url_after: settledTab?.url || null,
			project_id: extractFlowProjectId(settledTab?.url),
		}),
	);
	return await finalizeBoundEditor(settledTab, proof.started_from, {
		created_new_project: proof.created_new_project,
	});
}

function isActualFlowEditorProbe(result, mode = null) {
	if (!result || result.error) {
		return false;
	}
	const modeVisible = String(result.current_mode_visible || "");
	const visibleUploadSlots = Array.isArray(result?.observed?.visibleUploadSlots)
		? result.observed.visibleUploadSlots.map((value) => String(value))
		: [];
	const normalizedMode = String(mode || "").trim().toUpperCase();
	if (normalizedMode === "F2V") {
		const looksLikeFramesEditor =
			modeVisible.includes("Video/Frames") ||
			visibleUploadSlots.includes("Start") ||
			visibleUploadSlots.includes("End");
		return Boolean(
			result.flow_tab_found &&
				result.signed_in_likely &&
				result.ok &&
				looksLikeFramesEditor,
		);
	}
	return Boolean(
		result.flow_tab_found &&
			result.signed_in_likely &&
			(result.ok ||
				result.composer_found ||
				result.generate_button_found ||
				modeVisible !== "UNKNOWN"),
	);
}

async function probeFlowEditorCandidate(tab, mode) {
	const safeTab = await getTabSafe(tab?.id);
	if (!safeTab?.id) {
		return {
			ok: false,
			error: "ERR_TAB_RELOADED",
			tab: summarizeFlowTab(tab),
		};
	}
	await ensureFlowDomScript(safeTab.id);
	const diagnostic = await pingFlowDomScript(safeTab);
	if (diagnostic.raw_error) {
		return {
			ok: false,
			error: diagnostic.raw_error,
			detail: diagnostic.raw_error,
			tab: summarizeFlowTab(safeTab),
			diagnostic,
		};
	}
	const readiness = await sendTabMessageSafe(
		safeTab.id,
		{
			type: "CHECK_FLOW_COMPOSER_READY",
			mode,
		},
		12000,
	);
	return {
		ok: isActualFlowEditorProbe(readiness, mode),
		tab: summarizeFlowTab(safeTab),
		readiness,
		diagnostic,
	};
}

async function resolveExistingProjectEditorAuthority(tab, mode) {
	const safeTab = await getTabSafe(tab?.id);
	if (
		!safeTab?.id ||
		!isProjectEditorUrl(safeTab?.url) ||
		isRootFlowUrl(safeTab?.url)
	) {
		return {
			ok: false,
			error: "FLOW_EDITOR_AUTHORITY_NOT_ELIGIBLE",
			tab: summarizeFlowTab(tab),
		};
	}
	if (flowTabLooksBroken(safeTab)) {
		return {
			ok: false,
			error: "FLOW_EDITOR_AUTHORITY_BROKEN",
			tab: summarizeFlowTab(safeTab),
		};
	}
	await ensureFlowDomScript(safeTab.id);
	const diagnostic = await pingFlowDomScript(safeTab);
	if (!isFlowContentScriptReadyForActiveTab(diagnostic)) {
		return {
			ok: false,
			error:
				diagnostic?.raw_error || "FLOW_ACTIVE_TAB_CONTENT_SCRIPT_NOT_READY",
			tab: summarizeFlowTab(safeTab),
			diagnostic,
		};
	}
	let pageDiagnostic = null;
	try {
		pageDiagnostic = await sendTabMessageSafe(
			safeTab.id,
			{
				type: "FLOW_PAGE_STATE_DIAGNOSTIC",
				mode,
			},
			12000,
		);
	} catch (_) {}
	const brokenErrorMarkers = Array.isArray(pageDiagnostic?.visible_error_markers)
		? pageDiagnostic.visible_error_markers.map((value) => String(value))
		: [];
	if (brokenErrorMarkers.length) {
		return {
			ok: false,
			error: "FLOW_EDITOR_AUTHORITY_BROKEN",
			tab: summarizeFlowTab(safeTab),
			diagnostic,
			page_diagnostic: pageDiagnostic,
		};
	}
	return {
		ok: true,
		tab: summarizeFlowTab(safeTab),
		diagnostic,
		page_diagnostic: pageDiagnostic,
	};
}

function classifyFlowTabKind(tab) {
	if (!tab?.url) {
		return "UNKNOWN";
	}
	if (isProjectEditorUrl(tab.url)) {
		return "EDITOR";
	}
	if (isRootFlowUrl(tab.url)) {
		return "ROOT";
	}
	return "OTHER_FLOW";
}

function summarizeOpenFlowResult(result) {
	if (!result || typeof result !== "object") {
		return null;
	}
	return {
		ok: Boolean(result.ok),
		error: result.error || null,
		detail: result.detail || null,
		editor_ready: Boolean(result.editor_ready),
		new_project_clicked: Boolean(result.new_project_clicked),
		project_list_or_landing_detected: Boolean(
			result.project_list_or_landing_detected,
		),
		flow_tab_id: result.flow_tab_id ?? null,
		flow_url_before: result.flow_url_before || null,
		flow_url_after: result.flow_url_after || null,
		flow_url: result.flow_url || null,
	};
}

async function getLocalRuntimeDiagnosticSnapshot() {
	const preferredUrl = await getStoredFlowProjectUrl();
	const flowTabs = await getFlowTabs();
	const activeTabPreflight = await buildActiveFlowTabPreflight("F2V", {
		preferredUrl,
		tabs: flowTabs,
	});
	const selectedTab = activeTabPreflight?.selectedTab || null;
	const adoptedTarget = await adoptSelectedFlowProjectUrlIfNeeded(
		selectedTab,
		flowTabs,
		preferredUrl,
	);
	const effectivePreferredUrl =
		adoptedTarget?.preferred_flow_project_url || preferredUrl;
	const badRedirectTabs = await chrome.tabs.query({ url: ["http://0.0.0.43/*"] });
	const badRedirectTab = badRedirectTabs.length ? badRedirectTabs[0] : null;
	const diagnostics = buildRuntimeDiagnosticPayload({
		flowUrl: selectedTab?.url || badRedirectTab?.url || null,
		preferredUrl: effectivePreferredUrl,
		selectedTab: selectedTab || badRedirectTab,
	});
	diagnostics.selected_tab_id = activeTabPreflight?.preflight?.selected_tab_id || null;
	diagnostics.active_editor_tab_id =
		activeTabPreflight?.preflight?.active_editor_tab_id || null;
	diagnostics.selected_tab_active = Boolean(
		activeTabPreflight?.preflight?.selected_tab_active,
	);
	diagnostics.selected_tab_url = activeTabPreflight?.selectedTabUrl || null;
	diagnostics.active_editor_tab_url =
		activeTabPreflight?.activeEditorTabUrl || null;
	diagnostics.rebound_to_active_editor_tab = Boolean(
		activeTabPreflight?.reboundToActiveEditorTab,
	);
	diagnostics.same_project_url = Boolean(
		activeTabPreflight?.preflight?.same_project_url,
	);
	diagnostics.content_script_alive_on_active_tab = Boolean(
		activeTabPreflight?.preflight?.content_script_alive_on_active_tab,
	);
	diagnostics.safe_to_click_active_tab = Boolean(
		activeTabPreflight?.preflight?.safe_to_click_active_tab,
	);
	updateRuntimeDiagnostics(diagnostics);
	return {
		ok: true,
		...buildBackgroundStatusResponse(),
		flow_tabs: flowTabs.map((tab) => ({
			...summarizeFlowTab(tab),
			tab_kind: classifyFlowTabKind(tab),
		})),
		target_tab: selectedTab
			? {
					...summarizeFlowTab(selectedTab),
					tab_kind: classifyFlowTabKind(selectedTab),
				}
			: null,
		last_bad_redirect_tab: badRedirectTab ? summarizeFlowTab(badRedirectTab) : null,
		preferred_flow_project_url: effectivePreferredUrl,
		target_auto_sync: adoptedTarget?.sync_result || null,
		active_tab_preflight: activeTabPreflight?.preflight || null,
		target_binding_error: activeTabPreflight?.error || null,
		target_binding_telemetry: activeTabPreflight
			? {
					selected_tab_id: activeTabPreflight.preflight?.selected_tab_id || 0,
					active_editor_tab_id:
						activeTabPreflight.preflight?.active_editor_tab_id || 0,
					selected_tab_active:
						Boolean(activeTabPreflight.preflight?.selected_tab_active),
					selected_tab_url: activeTabPreflight.selectedTabUrl || null,
					active_editor_tab_url: activeTabPreflight.activeEditorTabUrl || null,
					rebound_to_active_editor_tab:
						Boolean(activeTabPreflight.reboundToActiveEditorTab),
				}
			: null,
		duplicate_editor_tabs: activeTabPreflight?.duplicate_tab_inventory || [],
	};
}

async function resolveFlowExecutionTarget(job = null) {
	const preferredUrl = await getStoredFlowProjectUrl();
	let tabs = await getFlowTabs();
	const initialCandidateTabs = tabs.map(summarizeFlowTab).filter(Boolean);
	if (!tabs.length) {
		return {
			ok: false,
			error: "ERR_NO_FLOW_TAB",
			detail: {
				reason: "no_google_flow_tabs_found",
				candidate_tabs: [],
			},
		};
	}

	const strictActiveBinding =
		String(job?.mode || "").trim().toUpperCase() === "F2V";
	let activeTabPreflight = null;
	if (strictActiveBinding) {
		const strictRecovery = await recoverStrictActiveFlowTabTarget(
			job?.mode || "F2V",
			{
				preferredUrl,
				tabs,
			},
		);
		activeTabPreflight = strictRecovery?.activeTabPreflight || null;
		if (strictRecovery?.ok) {
			tabs = await getFlowTabs();
		}
		if (!activeTabPreflight?.ok) {
			return {
				ok: false,
				error: activeTabPreflight?.error || "FLOW_REBOUND_TO_ACTIVE_TAB_FAILED",
				candidate_tabs: initialCandidateTabs,
				detail: {
					reason: "active_flow_tab_preflight_failed",
					selected_tab_id: activeTabPreflight?.preflight?.selected_tab_id || 0,
					active_editor_tab_id:
						activeTabPreflight?.preflight?.active_editor_tab_id || 0,
					selected_tab_active:
						Boolean(activeTabPreflight?.preflight?.selected_tab_active),
					same_project_url:
						Boolean(activeTabPreflight?.preflight?.same_project_url),
					content_script_alive_on_active_tab: Boolean(
						activeTabPreflight?.preflight?.content_script_alive_on_active_tab,
					),
					safe_to_click_active_tab: Boolean(
						activeTabPreflight?.preflight?.safe_to_click_active_tab,
					),
					selected_tab_url: activeTabPreflight?.selectedTabUrl || null,
					active_editor_tab_url: activeTabPreflight?.activeEditorTabUrl || null,
					rebound_to_active_editor_tab: Boolean(
						activeTabPreflight?.reboundToActiveEditorTab,
					),
					focus_recovery_attempted: Boolean(
						strictRecovery?.focus_recovery_attempted,
					),
					focus_recovery_succeeded: Boolean(
						strictRecovery?.focus_recovery_succeeded,
					),
					focused_editor_tab_id:
						Number(strictRecovery?.focused_editor_tab_id || 0),
					bootstrap_recovery_attempted: Boolean(
						strictRecovery?.bootstrap_recovery_attempted,
					),
					bootstrap_recovery_succeeded: Boolean(
						strictRecovery?.bootstrap_recovery_succeeded,
					),
					bootstrapped_editor_tab_id:
						Number(strictRecovery?.bootstrapped_editor_tab_id || 0),
					reopen_suppressed: Boolean(strictRecovery?.reopen_suppressed),
					reopen_suppressed_reason: strictRecovery?.reopen_suppressed
						? strictRecovery?.error || "FLOW_PROJECT_REOPEN_LOOP"
						: null,
					duplicate_editor_tabs:
						activeTabPreflight?.duplicate_tab_inventory || [],
				},
			};
		}
		const preflightTarget =
			(await getTabSafe(activeTabPreflight?.selectedTab?.id)) ||
			activeTabPreflight?.selectedTab ||
			null;
		return {
			ok: true,
			targetTab: preflightTarget,
			candidate_tabs: initialCandidateTabs,
			target_probe:
				activeTabPreflight?.composer_diagnostic ||
				activeTabPreflight?.page_diagnostic ||
				activeTabPreflight?.content_diagnostic ||
				null,
			active_tab_preflight: activeTabPreflight?.preflight || null,
			focus_recovery_attempted: Boolean(
				strictRecovery?.focus_recovery_attempted,
			),
			focus_recovery_succeeded: Boolean(
				strictRecovery?.focus_recovery_succeeded,
			),
			focused_editor_tab_id: Number(strictRecovery?.focused_editor_tab_id || 0),
			bootstrap_recovery_attempted: Boolean(
				strictRecovery?.bootstrap_recovery_attempted,
			),
			bootstrap_recovery_succeeded: Boolean(
				strictRecovery?.bootstrap_recovery_succeeded,
			),
			bootstrapped_editor_tab_id: Number(
				strictRecovery?.bootstrapped_editor_tab_id || 0,
			),
		};
	}

	let selectedTab = selectBestFlowTab(tabs, preferredUrl);
	const selectedTitle = String(selectedTab?.title || "").toLowerCase();
	const canFastTrackSelectedEditor =
		Boolean(selectedTab?.id) &&
		isProjectEditorUrl(selectedTab?.url) &&
		!isRootFlowUrl(selectedTab?.url) &&
		!selectedTitle.includes("something went wrong") &&
		!selectedTitle.includes("application error");
	if (canFastTrackSelectedEditor) {
		await ensureFlowDomScript(selectedTab.id);
		const fastDiagnostic = await pingFlowDomScript(selectedTab);
		if (!fastDiagnostic?.raw_error) {
			const probedTab = await getTabSafe(selectedTab.id);
			return {
				ok: true,
				targetTab: probedTab || selectedTab,
				candidate_tabs: initialCandidateTabs,
				target_probe: fastDiagnostic,
			};
		}
	}
	const nonRootEditors = tabs.filter(
		(tab) => isProjectEditorUrl(tab?.url) && !isRootFlowUrl(tab?.url),
	);
	const preferredProbeTab =
		selectedTab &&
		isProjectEditorUrl(selectedTab?.url) &&
		!isRootFlowUrl(selectedTab?.url)
			? selectedTab
			: null;
	const rankedTabs = buildUniqueFlowProbeCandidates(
		nonRootEditors.length ? nonRootEditors : tabs,
		preferredProbeTab,
	);
	for (const candidateTab of rankedTabs) {
		const probe = await probeFlowEditorCandidate(candidateTab, job?.mode);
		if (probe.ok) {
			const probedTab = await getTabSafe(candidateTab.id);
			return {
				ok: true,
				targetTab: probedTab || candidateTab,
				candidate_tabs: initialCandidateTabs,
				target_probe: probe.readiness || null,
			};
		}
	}

	await new Promise((resolve) => setTimeout(resolve, 1500));
	const retryTabs = await getFlowTabs();
	const retryNonRootEditors = retryTabs.filter(
		(tab) => isProjectEditorUrl(tab?.url) && !isRootFlowUrl(tab?.url),
	);
	const retrySelectedTab = selectBestFlowTab(retryTabs, preferredUrl);
	const retryPreferredProbeTab =
		retrySelectedTab &&
		isProjectEditorUrl(retrySelectedTab?.url) &&
		!isRootFlowUrl(retrySelectedTab?.url)
			? retrySelectedTab
			: null;
	const retryRankedTabs = buildUniqueFlowProbeCandidates(
		retryNonRootEditors.length ? retryNonRootEditors : retryTabs,
		retryPreferredProbeTab,
	);
	for (const candidateTab of retryRankedTabs) {
		const probe = await probeFlowEditorCandidate(candidateTab, job?.mode);
		if (probe.ok) {
			const probedTab = await getTabSafe(candidateTab.id);
			return {
				ok: true,
				targetTab: probedTab || candidateTab,
				candidate_tabs: initialCandidateTabs,
				target_probe: probe.readiness || null,
			};
		}
	}

	if (
		selectedTab &&
		(isRootFlowUrl(selectedTab.url) || isProjectEditorUrl(selectedTab.url))
	) {
		const openResult = await openPreferredFlowProjectOrNewProject(
			job?.mode,
			preferredUrl,
		);
		const settledTab = await settleFlowProjectAfterOpen(openResult);
		tabs = await getFlowTabs();
		const candidateTabs = tabs.map(summarizeFlowTab).filter(Boolean);
		selectedTab =
			settledTab ||
			tabs.find((tab) => tab.id === openResult?.flow_tab_id) ||
			selectBestFlowTab(tabs, openResult?.flow_url || preferredUrl);
		if (selectedTab) {
			const probe = await probeFlowEditorCandidate(selectedTab, job?.mode);
			if (probe.ok) {
				const probedTab = await getTabSafe(selectedTab.id);
				return {
					ok: true,
					targetTab: probedTab || selectedTab,
					candidate_tabs: candidateTabs,
					open_flow_result: summarizeOpenFlowResult(openResult),
					target_probe: probe.readiness || null,
				};
			}
		}
		return {
			ok: false,
			error: "ERR_FLOW_TAB_NOT_TARGETED",
			candidate_tabs: candidateTabs,
			detail: {
				reason: isRootFlowUrl(selectedTab?.url)
					? "flow_root_without_project_editor"
					: "flow_project_editor_unhealthy",
				target_tab_url: selectedTab?.url || openResult?.flow_url || null,
				candidate_tabs: candidateTabs,
				open_flow_result: summarizeOpenFlowResult(openResult),
			},
		};
	}

	return {
		ok: false,
		error: "ERR_FLOW_TAB_NOT_TARGETED",
		candidate_tabs: initialCandidateTabs,
		detail: {
			reason: "flow_tab_not_project_editor",
			target_tab_url: selectedTab?.url || null,
			candidate_tabs: initialCandidateTabs,
		},
	};
}

async function getStoredFlowProjectUrl() {
	try {
		const stored = await chrome.storage.local.get(FLOW_PROJECT_URL_STORAGE_KEY);
		return String(stored?.[FLOW_PROJECT_URL_STORAGE_KEY] || "").trim() || null;
	} catch (_) {
		return null;
	}
}

async function setStoredFlowProjectUrl(flowProjectUrl) {
	const normalized = String(flowProjectUrl || "").trim();
	if (!normalized) {
		await chrome.storage.local.remove(FLOW_PROJECT_URL_STORAGE_KEY);
		updateRuntimeDiagnostics({ stored_flow_project_url: null });
		return null;
	}
	await chrome.storage.local.set({
		[FLOW_PROJECT_URL_STORAGE_KEY]: normalized,
	});
	updateRuntimeDiagnostics({ stored_flow_project_url: normalized });
	return normalized;
}

async function syncStoredFlowProjectUrlToActiveEditor(
	activeEditorUrl,
	options = {},
) {
	const normalizedActiveUrl = String(activeEditorUrl || "").trim();
	if (!isProjectEditorUrl(normalizedActiveUrl) || isRootFlowUrl(normalizedActiveUrl)) {
		return {
			ok: false,
			synced: false,
			reason: "ACTIVE_URL_NOT_EDITOR",
			stored_flow_project_url: await getStoredFlowProjectUrl(),
			active_flow_project_url: normalizedActiveUrl || null,
		};
	}
	const currentStoredUrl = String(
		options.currentStoredUrl || (await getStoredFlowProjectUrl()) || "",
	).trim();
	const openedViaRecovery = Boolean(options.openedViaRecovery);
	const allowWhenMissing = options.allowWhenMissing !== false;
	const force = options.force === true;
	const shouldSync =
		force ||
		(openedViaRecovery && normalizedActiveUrl !== currentStoredUrl) ||
		(allowWhenMissing && !currentStoredUrl);
	if (!shouldSync) {
		return {
			ok: true,
			synced: false,
			reason: "SYNC_NOT_REQUIRED",
			stored_flow_project_url: currentStoredUrl || null,
			active_flow_project_url: normalizedActiveUrl,
		};
	}
	const stored = await setStoredFlowProjectUrl(normalizedActiveUrl);
	return {
		ok: true,
		synced: Boolean(stored),
		reason: openedViaRecovery ? "RECOVERY_EDITOR_SYNCED" : "EDITOR_SYNCED",
		stored_flow_project_url: stored,
		active_flow_project_url: normalizedActiveUrl,
	};
}

async function ensureFlowDomScript(tabId) {
	try {
		await chrome.scripting.executeScript({
			target: { tabId },
			files: ["content-flow-dom.js"],
		});
	} catch (e) {
		console.warn("[FlowAgent] Script injection failed (already injected?):", e);
	}
}

function getKnownContentScriptHealth(tabId) {
	const last = flowContentScriptHealth.get(tabId);
	return {
		content_build_id: last?.content_build_id || null,
		content_script_protocol_version:
			last?.content_script_protocol_version || null,
		content_script_loaded: Boolean(last?.content_script_loaded),
		content_script_alive: Boolean(last?.content_script_alive),
		runtime_ready: Boolean(last?.runtime_ready),
		build_match:
			last?.content_build_id != null
				? last.content_build_id === BUILD_ID
				: false,
		last_content_script_seen_at: last?.last_content_script_seen_at || null,
	};
}

function rememberContentScriptHealth(tabId, payload) {
	const timestamp = payload?.timestamp || new Date().toISOString();
	flowContentScriptHealth.set(tabId, {
		content_build_id: payload?.content_build_id || null,
		content_script_protocol_version:
			payload?.content_script_protocol_version || null,
		content_script_loaded: Boolean(payload?.content_script_loaded),
		content_script_alive: Boolean(
			payload?.ok && payload?.content_script_loaded,
		),
		runtime_ready: Boolean(payload?.runtime_ready),
		last_content_script_seen_at: timestamp,
	});
	return getKnownContentScriptHealth(tabId);
}

function buildFlowReadinessBase(flowTab) {
	return {
		ok: false,
		flow_tab_found: Boolean(flowTab),
		flow_tab_id: flowTab?.id ?? null,
		flow_url: flowTab?.url ?? null,
		background_build_id: BUILD_ID,
		content_build_id: null,
		extension_protocol_version: EXTENSION_PROTOCOL_VERSION,
		content_script_protocol_version: null,
		content_script_loaded: false,
		content_script_alive: false,
		runtime_ready: false,
		build_match: false,
		last_content_script_seen_at: null,
		signed_in_likely: false,
		composer_found: false,
		composer_editable: false,
		generate_button_found: false,
		current_mode_visible: "UNKNOWN",
		blocking_modal_detected: false,
		primary_blocker: null,
		last_checked_at: new Date().toISOString(),
		raw_error: null,
	};
}

function classifyFlowPrimaryBlocker(result) {
	const rawError = String(
		result?.raw_error || result?.detail || result?.error || "",
	);
	if (
		[
			"ERR_UNKNOWN_MESSAGE_TYPE",
			"ERR_CONTENT_SCRIPT_STALE",
			"ERR_NO_RECEIVER",
			"ERR_MESSAGE_RESPONSE_TIMEOUT",
		].includes(rawError)
	) {
		return "CONTENT_SCRIPT_STALE_OR_NOT_INJECTED";
	}
	if (!result?.flow_tab_found) {
		return "FLOW_PROJECT_LIST_NOT_EDITOR";
	}
	if (!result?.content_script_loaded || !result?.content_script_alive) {
		return "CONTENT_SCRIPT_STALE_OR_NOT_INJECTED";
	}
	if (
		result?.content_script_protocol_version &&
		result.content_script_protocol_version !== FLOW_DOM_PROTOCOL_VERSION
	) {
		return "CONTENT_SCRIPT_STALE_OR_NOT_INJECTED";
	}
	if (!result?.runtime_ready || !result?.build_match) {
		return "CONTENT_SCRIPT_STALE_OR_NOT_INJECTED";
	}
	if (
		rawError.includes("FLOW_MODE_MISMATCH") ||
		rawError.includes("ABORT_FLOW_MODE_MISMATCH")
	) {
		return "FLOW_MODE_MISMATCH";
	}
	if (!result?.signed_in_likely) {
		return "FLOW_EDITOR_NOT_AUTHENTICATED";
	}
	if (result?.flow_url && !isProjectEditorUrl(result.flow_url)) {
		return "FLOW_PROJECT_LIST_NOT_EDITOR";
	}
	if (result?.composer_found && !result?.composer_editable) {
		return "COMPOSER_NOT_EDITABLE";
	}
	if (result?.composer_found && !result?.generate_button_found) {
		return "GENERATE_BUTTON_NOT_FOUND";
	}
	if (!result?.composer_found) {
		return "FLOW_PROJECT_LIST_NOT_EDITOR";
	}
	return null;
}

function finalizeFlowReadiness(result) {
	const finalized = {
		...result,
		last_checked_at: new Date().toISOString(),
	};
	if (!finalized.content_build_id && finalized.flow_tab_id != null) {
		const health = getKnownContentScriptHealth(finalized.flow_tab_id);
		finalized.content_build_id = health.content_build_id;
		finalized.runtime_ready = finalized.runtime_ready || health.runtime_ready;
	}
	if (finalized.content_build_id) {
		finalized.build_match =
			finalized.content_build_id === finalized.background_build_id;
	}
	finalized.primary_blocker = classifyFlowPrimaryBlocker(finalized);
	return finalized;
}

function isRecoverableComposerRouteError(error) {
	const rawError = String(error || "").trim();
	return [
		"ERR_MESSAGE_RESPONSE_TIMEOUT",
		"ERR_NO_RECEIVER",
		"ERR_CONTENT_SCRIPT_STALE",
		"ERR_TAB_RELOADED",
	].includes(rawError);
}

function canUsePageDiagnosticForComposerReadiness(pageDiagnostic) {
	return Boolean(
		pageDiagnostic &&
			typeof pageDiagnostic === "object" &&
			!pageDiagnostic.error &&
			pageDiagnostic.flow_url &&
			pageDiagnostic.ui_contract_v2 &&
			pageDiagnostic.content_script_loaded &&
			pageDiagnostic.content_script_protocol_version ===
				FLOW_DOM_PROTOCOL_VERSION &&
			pageDiagnostic.runtime_ready &&
			pageDiagnostic.content_build_id === BUILD_ID,
	);
}

function buildComposerReadinessFromPageDiagnostic(pageDiagnostic) {
	const strictComposerOk =
		typeof pageDiagnostic?.strict_composer_ok === "boolean"
			? pageDiagnostic.strict_composer_ok
			: Boolean(
					pageDiagnostic?.signed_in_likely &&
						pageDiagnostic?.editor_capability_ready &&
						!pageDiagnostic?.blocking_modal_detected,
				);
	return {
		ok: strictComposerOk,
		flow_tab_found: Boolean(pageDiagnostic?.flow_url),
		flow_url: pageDiagnostic?.flow_url || null,
		location_href: pageDiagnostic?.location_href || pageDiagnostic?.flow_url || null,
		document_title: pageDiagnostic?.document_title || null,
		document_ready_state: pageDiagnostic?.document_ready_state || null,
		signed_in_likely: Boolean(pageDiagnostic?.signed_in_likely),
		composer_found: Boolean(pageDiagnostic?.composer_found),
		composer_editable: Boolean(pageDiagnostic?.composer_editable),
		prompt_field_found: Boolean(pageDiagnostic?.prompt_field_found),
		generate_button_found: Boolean(pageDiagnostic?.generate_button_found),
		current_mode_visible: pageDiagnostic?.current_mode_visible || "UNKNOWN",
		blocking_modal_detected: Boolean(pageDiagnostic?.blocking_modal_detected),
		observed: pageDiagnostic?.observed || null,
		runtime_ready: Boolean(pageDiagnostic?.runtime_ready),
		content_build_id: pageDiagnostic?.content_build_id || null,
		content_script_loaded: Boolean(pageDiagnostic?.content_script_loaded),
		content_script_alive: Boolean(pageDiagnostic?.content_script_loaded),
		content_script_protocol_version:
			pageDiagnostic?.content_script_protocol_version || null,
		ui_contract_version: pageDiagnostic?.ui_contract_version || null,
		ui_contract_v2: pageDiagnostic?.ui_contract_v2 || null,
		editor_capability_ready: Boolean(pageDiagnostic?.editor_capability_ready),
		pre_generate_ready: Boolean(pageDiagnostic?.pre_generate_ready),
		strict_composer_ok: Boolean(pageDiagnostic?.strict_composer_ok),
		strict_composer_error: pageDiagnostic?.strict_composer_error || null,
		page_preselection_ready: Boolean(pageDiagnostic?.ok),
		mode_mismatch_non_fatal: Boolean(pageDiagnostic?.mode_mismatch_non_fatal),
		recovered_via_flow_page_state_diagnostic: true,
		raw_error: null,
	};
}

async function pingFlowDomScript(flowTab) {
	const response = await sendTabMessageSafe(flowTab.id, {
		type: "FLOWKIT_DIAGNOSTIC_PING",
	});
	if (response?.ok && response?.content_script_loaded) {
		const health = rememberContentScriptHealth(flowTab.id, response);
		return {
			...health,
			raw_error: null,
		};
	}

	const health = getKnownContentScriptHealth(flowTab.id);
	return {
		...health,
		raw_error: response?.error || "ERR_NO_RECEIVER",
	};
}

async function waitForTabReload(tabId, timeoutMs = 10000) {
	const tab = await chrome.tabs.get(tabId);
	if (tab.status === "complete") {
		return tab;
	}

	return await new Promise((resolve, reject) => {
		let settled = false;
		const timer = setTimeout(() => {
			if (settled) return;
			settled = true;
			chrome.tabs.onUpdated.removeListener(listener);
			reject(new Error("ERR_MESSAGE_RESPONSE_TIMEOUT"));
		}, timeoutMs);

		const listener = (updatedTabId, changeInfo, updatedTab) => {
			if (updatedTabId !== tabId || changeInfo.status !== "complete") {
				return;
			}
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			chrome.tabs.onUpdated.removeListener(listener);
			resolve(updatedTab);
		};

		chrome.tabs.onUpdated.addListener(listener);
	});
}

async function waitForTabComplete(tabId, timeoutMs = 15000) {
	const tab = await chrome.tabs.get(tabId);
	if (tab.status === "complete") {
		return tab;
	}

	return await new Promise((resolve, reject) => {
		let settled = false;
		const timer = setTimeout(() => {
			if (settled) return;
			settled = true;
			chrome.tabs.onUpdated.removeListener(listener);
			reject(new Error("ERR_MESSAGE_RESPONSE_TIMEOUT"));
		}, timeoutMs);

		const listener = (updatedTabId, changeInfo, updatedTab) => {
			if (updatedTabId !== tabId || changeInfo.status !== "complete") {
				return;
			}
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			chrome.tabs.onUpdated.removeListener(listener);
			resolve(updatedTab);
		};

		chrome.tabs.onUpdated.addListener(listener);
	});
}

async function focusTab(tab) {
	if (!tab?.id) {
		return tab;
	}
	if (tab.windowId != null) {
		await chrome.windows.update(tab.windowId, { focused: true });
	}
	return await chrome.tabs.update(tab.id, { active: true });
}

async function openTabInNormalWindow(url) {
	const windows = await chrome.windows.getAll({
		windowTypes: ["normal"],
		populate: true,
	});
	const normalWindow = windows.find((item) => item?.id != null);

	if (normalWindow?.id != null) {
		try {
			await chrome.windows.update(normalWindow.id, { focused: true });
		} catch (_) {}
		return await chrome.tabs.create({
			windowId: normalWindow.id,
			url,
			active: true,
		});
	}

	const createdWindow = await chrome.windows.create({
		url,
		focused: true,
		type: "normal",
	});
	const createdTab =
		createdWindow?.tabs?.find((item) => item?.url === url) ||
		createdWindow?.tabs?.[0] ||
		null;
	if (!createdTab?.id) {
		throw new Error("ERR_NO_NORMAL_BROWSER_WINDOW");
	}
	return createdTab;
}

async function handleOpenTargetFlowProject(flowProjectUrl, mode = null) {
	const normalizedUrl = String(flowProjectUrl || "").trim();
	if (!normalizedUrl) {
		return {
			ok: false,
			error: "ERR_FLOW_PROJECT_URL_REQUIRED",
			flow_project_url: null,
			flow_tab_id: null,
			flow_url_before: null,
			flow_url_after: null,
			flow_url: null,
			extension_protocol_version: EXTENSION_PROTOCOL_VERSION,
		};
	}

	await setStoredFlowProjectUrl(normalizedUrl);

	const flowTabBefore = await getFlowTab();
	const flowUrlBefore = flowTabBefore?.url || null;

	const exactTabs = await chrome.tabs.query({ url: normalizedUrl });
	let targetTab = exactTabs.length ? exactTabs[0] : null;

	if (targetTab) {
		targetTab = await focusTab(targetTab);
	} else {
		targetTab = await openTabInNormalWindow(normalizedUrl);
	}

	try {
		targetTab = await waitForTabComplete(targetTab.id);
	} catch (_) {
		targetTab = await chrome.tabs.get(targetTab.id);
	}

	await ensureFlowDomScript(targetTab.id);
	const diagnostic = await pingFlowDomScript(targetTab);
	const flowUrlAfter = targetTab?.url || normalizedUrl;
	const flowTabId = targetTab?.id ?? null;
	const pathState = classifyFlowPathState(flowUrlAfter);
	const nonEditorDiagnosticCode = isAbnormalRedirectUrl(flowUrlAfter)
		? "ABNORMAL_REDIRECT"
		: pathState === "FLOW_ROOT"
			? "FLOW_ROOT_OPEN_INSTEAD_OF_EDITOR"
			: "FLOW_PROJECT_EDITOR_NOT_OPEN";
	const nonEditorDiagnosticDetail = isAbnormalRedirectUrl(flowUrlAfter)
		? `Flow navigation landed on unexpected URL: ${flowUrlAfter}`
		: pathState === "FLOW_ROOT"
			? "Flow dashboard/root stayed open instead of a project editor."
			: "Preferred Flow project did not settle on an editor URL.";

	if (!isProjectEditorUrl(flowUrlAfter)) {
		updateRuntimeDiagnostics(
			buildRuntimeDiagnosticPayload({
				flowUrl: flowUrlAfter,
				preferredUrl: normalizedUrl,
				selectedTab: targetTab,
				openFlowResult: {
					error: "FLOW_PROJECT_EDITOR_NOT_OPEN",
					flow_url_after: flowUrlAfter,
					flow_url: flowUrlAfter,
				},
			}),
		);
		return {
			ok: false,
			error: "FLOW_PROJECT_EDITOR_NOT_OPEN",
			diagnostic_code: nonEditorDiagnosticCode,
			diagnostic_detail: nonEditorDiagnosticDetail,
			flow_project_url: normalizedUrl,
			flow_tab_id: flowTabId,
			flow_url_before: flowUrlBefore,
			flow_url_after: flowUrlAfter,
			flow_url: flowUrlAfter,
			extension_protocol_version: EXTENSION_PROTOCOL_VERSION,
			...diagnostic,
		};
	}

	const probe = await probeFlowEditorCandidate(targetTab, mode);
	if (!probe.ok) {
		updateRuntimeDiagnostics({
			...buildRuntimeDiagnosticPayload({
				flowUrl: flowUrlAfter,
				preferredUrl: normalizedUrl,
				selectedTab: targetTab,
			}),
			runtime_reason: "FLOW_PROJECT_EDITOR_NOT_READY",
			runtime_detail:
				probe.readiness?.error ||
				probe.detail ||
				"Flow project editor URL is open, but the editor did not become ready.",
			diagnostic_code: "FLOW_PROJECT_EDITOR_NOT_READY",
			diagnostic_detail:
				probe.readiness?.error ||
				probe.detail ||
				"Flow project editor URL is open, but the editor did not become ready.",
		});
		return {
			ok: false,
			error: probe.error || "FLOW_PROJECT_EDITOR_NOT_READY",
			detail: probe.readiness?.error || probe.detail || null,
			flow_project_url: normalizedUrl,
			flow_tab_id: flowTabId,
			flow_url_before: flowUrlBefore,
			flow_url_after: flowUrlAfter,
			flow_url: flowUrlAfter,
			extension_protocol_version: EXTENSION_PROTOCOL_VERSION,
			target_probe: probe.readiness || null,
			target_probe_diagnostic: probe.diagnostic || null,
			...diagnostic,
		};
	}

	updateRuntimeDiagnostics(
		buildRuntimeDiagnosticPayload({
			flowUrl: flowUrlAfter,
			preferredUrl: normalizedUrl,
			selectedTab: targetTab,
		}),
	);
	return {
		ok: true,
		error: diagnostic.raw_error || null,
		flow_project_url: normalizedUrl,
		flow_tab_id: flowTabId,
		flow_url_before: flowUrlBefore,
		flow_url_after: flowUrlAfter,
		flow_url: flowUrlAfter,
		extension_protocol_version: EXTENSION_PROTOCOL_VERSION,
		...diagnostic,
	};
}

async function openPreferredFlowProjectOrNewProject(mode, preferredUrl = null) {
	const normalizedPreferredUrl = String(preferredUrl || "").trim();
	if (normalizedPreferredUrl) {
		const preferredResult = await handleOpenTargetFlowProject(
			normalizedPreferredUrl,
			mode,
		);
		if (preferredResult?.ok) {
			return {
				...preferredResult,
				open_strategy: "preferred_project_url",
			};
		}
	}

	const newProjectResult = await handleOpenFlowNewProject(mode);
	return {
		...newProjectResult,
		open_strategy: "new_project",
	};
}

async function settleFlowProjectAfterOpen(openFlowResult, settleMs = 2500) {
	const targetTabId = openFlowResult?.flow_tab_id ?? null;
	if (targetTabId) {
		try {
			await waitForTabComplete(targetTabId, 20000);
		} catch (_) {}
	}
	if (settleMs > 0) {
		await new Promise((resolve) => setTimeout(resolve, settleMs));
	}
	const preferredUrl =
		String(
			openFlowResult?.flow_url_after ||
				openFlowResult?.flow_url ||
				(await getStoredFlowProjectUrl()) ||
				"",
		).trim() || null;
	return (
		(await resolveLiveFlowEditorTab(preferredUrl, "F2V")) ||
		(await getTabSafe(targetTabId)) ||
		(await getFlowTab())
	);
}

async function handleOpenFlowNewProject(mode) {
	const rootUrl = "https://labs.google/fx/tools/flow";
	const exactTabs = await chrome.tabs.query({ url: rootUrl });
	let targetTab = exactTabs.length ? exactTabs[0] : null;

	if (targetTab) {
		targetTab = await focusTab(targetTab);
	} else {
		targetTab = await openTabInNormalWindow(rootUrl);
	}

	try {
		targetTab = await waitForTabComplete(targetTab.id, 30000);
	} catch (_) {
		targetTab = await chrome.tabs.get(targetTab.id);
	}

	await ensureFlowDomScript(targetTab.id);
	let result = await sendTabMessageSafe(
		targetTab.id,
		{
			type: "OPEN_FLOW_NEW_PROJECT",
			mode,
		},
		70000,
	);

	if (
		[
			"ERR_MESSAGE_RESPONSE_TIMEOUT",
			"ERR_NO_RECEIVER",
			"ERR_CONTENT_SCRIPT_STALE",
			"ERR_TAB_RELOADED",
		].includes(result?.error)
	) {
		await ensureFlowDomScript(targetTab.id);
		result = await sendTabMessageSafe(
			targetTab.id,
			{
				type: "OPEN_FLOW_NEW_PROJECT",
				mode,
			},
			70000,
		);
	}

	const refreshedTab = await chrome.tabs
		.get(targetTab.id)
		.catch(() => targetTab);
	const resolvedFlowUrl = String(
		result?.flow_url || refreshedTab?.url || targetTab?.url || rootUrl,
	).trim();
	const settledEditorTab =
		(await resolveLiveFlowEditorTab(
			isProjectEditorUrl(resolvedFlowUrl) ? resolvedFlowUrl : null,
			mode,
		)) || null;
	const effectiveFlowTab = settledEditorTab || refreshedTab || targetTab;
	const effectiveFlowUrl = String(
		settledEditorTab?.url || resolvedFlowUrl || rootUrl,
	).trim();
	if (isProjectEditorUrl(effectiveFlowUrl)) {
		await setStoredFlowProjectUrl(effectiveFlowUrl);
	}

	return {
		ok: Boolean(result?.ok),
		open_flow_root: Boolean(result?.open_flow_root),
		project_list_or_landing_detected: Boolean(
			result?.project_list_or_landing_detected,
		),
		new_project_clicked: result?.new_project_clicked || false,
		editor_ready: Boolean(result?.editor_ready),
		error: result?.error || null,
		detail: result?.detail || null,
		flow_tab_id: effectiveFlowTab?.id ?? refreshedTab?.id ?? targetTab?.id ?? null,
		flow_url_before: rootUrl,
		flow_url_after: effectiveFlowUrl,
		flow_url: effectiveFlowUrl,
		extension_protocol_version: EXTENSION_PROTOCOL_VERSION,
		...result,
	};
}

async function handleBootstrapFlowProjectEditor(mode = "F2V") {
	return await bootstrapFlowProjectEditorForB2A0(mode);
}

async function handleReloadExtension() {
	setTimeout(() => {
		try {
			chrome.runtime.reload();
		} catch (_) {}
	}, 100);
	return { ok: true, action: "RELOAD_EXTENSION" };
}

async function handleReloadFlowTab() {
	const flowTab = await getFlowTab();
	if (!flowTab) {
		return {
			ok: false,
			error: "ERR_NO_FLOW_TAB",
			action_taken: "NONE",
			flow_tab_id: null,
			flow_url: null,
			extension_protocol_version: EXTENSION_PROTOCOL_VERSION,
		};
	}

	try {
		await chrome.tabs.reload(flowTab.id);
		const reloadedTab = await waitForTabReload(flowTab.id);
		await ensureFlowDomScript(flowTab.id);
		const diagnostic = await pingFlowDomScript(reloadedTab);
		return {
			ok: !diagnostic.raw_error,
			error: diagnostic.raw_error,
			action_taken: "RELOAD_AND_REINJECT",
			flow_tab_id: flowTab.id,
			flow_url: reloadedTab?.url || flowTab.url,
			extension_protocol_version: EXTENSION_PROTOCOL_VERSION,
			...diagnostic,
		};
	} catch (error) {
		return {
			ok: false,
			error: String(error?.message || error),
			action_taken: "RELOAD_AND_REINJECT",
			flow_tab_id: flowTab.id,
			flow_url: flowTab.url,
			extension_protocol_version: EXTENSION_PROTOCOL_VERSION,
			...getKnownContentScriptHealth(flowTab.id),
		};
	}
}

// ─── URL → Log Type Classifier ─────────────────────────────

// Visible log types — only these appear in the request log
const _VISIBLE_TYPES = new Set([
	"GEN_IMG",
	"GEN_VID",
	"GEN_VID_REF",
	"UPSCALE",
	"TRACKING",
	"URL_REFRESH",
]);

function _classifyApiUrl(url) {
	if (url.includes("uploadImage")) return "UPLOAD";
	if (url.includes("batchGenerateImages")) return "GEN_IMG";
	if (url.includes("UpsampleVideo")) return "UPSCALE";
	if (url.includes("ReferenceImages")) return "GEN_VID_REF";
	if (url.includes("batchAsyncGenerateVideo")) return "GEN_VID";
	if (url.includes("batchCheckAsync")) return "POLL";
	if (url.includes("upsampleImage")) return "UPS_IMG";
	if (url.includes("/media/")) return "MEDIA";
	if (url.includes("/credits")) return "CREDITS";
	return "API";
}

// ─── Request Log ────────────────────────────────────────────

const requestLog = [];

function addRequestLog(entry) {
	requestLog.unshift(entry);
	if (requestLog.length > 100) requestLog.pop();
	broadcastRequestLog();
}

function updateRequestLog(id, updates) {
	const entry = requestLog.find((e) => e.id === id);
	if (entry) Object.assign(entry, updates);
	broadcastRequestLog();
}

function broadcastRequestLog() {
	sendRuntimeMessageNoThrow({ type: "REQUEST_LOG_UPDATE", log: requestLog });
}

// ─── Startup ────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(init);
chrome.runtime.onStartup.addListener(init);
chrome.alarms.onAlarm.addListener(async (alarm) => {
	if (alarm.name === "reconnect") connectToAgent();
	if (alarm.name === "keepAlive") keepAlive();
	if (alarm.name === "token-refresh") {
		await captureTokenFromFlowTab();
	}
});

async function init() {
	const data = await chrome.storage.local.get([
		"flowKey",
		"metrics",
		"callbackSecret",
	]);
	if (data.flowKey) flowKey = data.flowKey;
	if (data.metrics) Object.assign(metrics, data.metrics);
	if (data.callbackSecret) _callbackSecret = data.callbackSecret;
	try {
		await chrome.sidePanel.setOptions({
			path: "side_panel.html",
			enabled: true,
		});
		await chrome.sidePanel.setPanelBehavior({
			openPanelOnActionClick: true,
		});
	} catch (error) {
		console.error(
			"[FlowAgent] Failed to configure side panel behavior:",
			error,
		);
	}
	connectToAgent();
	chrome.alarms.create("keepAlive", { periodInMinutes: 0.4 });
}

// ─── Token Capture ──────────────────────────────────────────

chrome.webRequest.onBeforeSendHeaders.addListener(
	(details) => {
		if (!details?.requestHeaders?.length) return;
		const authHeader = details.requestHeaders.find(
			(h) => h.name?.toLowerCase() === "authorization",
		);
		const value = authHeader?.value || "";
		if (!value.startsWith("Bearer ya29.")) return;

		const token = value.replace(/^Bearer\s+/i, "").trim();
		if (!token) return;

		// Always update — even if same token string, refresh the timestamp
		flowKey = token;
		metrics.tokenCapturedAt = Date.now();
		chrome.storage.local.set({ flowKey, metrics });
		console.log("[FlowAgent] Bearer token captured");

		// Notify agent
		if (ws?.readyState === WebSocket.OPEN) {
			ws.send(JSON.stringify({ type: "token_captured", flowKey }));
		}
	},
	{ urls: ["https://aisandbox-pa.googleapis.com/*", "https://labs.google/*"] },
	["requestHeaders", "extraHeaders"],
);

let _openingFlowTab = false;

async function captureTokenFromFlowTab() {
	const tabs = await chrome.tabs.query({
		url: [
			"https://labs.google/fx/tools/flow*",
			"https://labs.google/fx/*/tools/flow*",
		],
	});
	if (!tabs.length) {
		if (_openingFlowTab) {
			console.log("[FlowAgent] Flow tab already opening, skipping");
			return;
		}
		_openingFlowTab = true;
		try {
			console.log("[FlowAgent] No Flow tab found — opening one in background");
			await chrome.tabs.create({
				url: "https://labs.google/fx/tools/flow",
				active: false,
			});
			await sleep(3000);
			const retryTabs = await chrome.tabs.query({
				url: [
					"https://labs.google/fx/tools/flow*",
					"https://labs.google/fx/*/tools/flow*",
				],
			});
			if (!retryTabs.length) {
				console.log("[FlowAgent] Flow tab not ready yet after open");
				return;
			}
			await chrome.scripting.executeScript({
				target: { tabId: retryTabs[0].id },
				files: ["content.js"],
			});
			console.log(
				"[FlowAgent] Token refresh triggered on newly opened Flow tab",
			);
		} catch (e) {
			console.error("[FlowAgent] Token refresh failed after opening tab:", e);
		} finally {
			_openingFlowTab = false;
		}
		return;
	}
	try {
		await chrome.scripting.executeScript({
			target: { tabId: tabs[0].id },
			files: ["content.js"],
		});
		console.log("[FlowAgent] Token refresh triggered on Flow tab");
	} catch (e) {
		console.error("[FlowAgent] Token refresh failed:", e);
	}
}

// ─── WebSocket to Agent ─────────────────────────────────────

function connectToAgent() {
	if (manualDisconnect) return;
	if (ws?.readyState === WebSocket.CONNECTING) return;
	if (ws?.readyState === WebSocket.OPEN) return;

	try {
		ws = new WebSocket(AGENT_WS_URL);
	} catch (e) {
		console.error("[FlowAgent] WS connect error:", e);
		scheduleReconnect();
		return;
	}

	const replyToAgent = (msg, result) => {
		if (!msg?.id) return;
		sendToAgent({ id: msg.id, result: result || { ok: true } });
	};

	const replyAgentError = (msg, error) => {
		if (!msg?.id) return;
		replyToAgent(msg, {
			ok: false,
			error: String(error?.message || error),
		});
	};

	ws.onopen = () => {
		console.log("[FlowAgent] Connected to agent");
		chrome.alarms.clear("reconnect");
		setState("idle");
		clearHealthyBridgeWsError();
		updateRuntimeDiagnostics({
			ws_connected: true,
			runtime_reason: "AGENT_WS_CONNECTED",
			runtime_detail: "Flow Kit background is connected to the local agent.",
			diagnostic_code: null,
			diagnostic_detail: null,
		});

		// Token refresh alarm — 45 min gives buffer before ~60 min expiry
		chrome.alarms.create("token-refresh", { periodInMinutes: 45 });

		// Send current state + resend token if we have one
		ws.send(
			JSON.stringify({
				type: "extension_ready",
				flowKeyPresent: !!flowKey,
				tokenAge:
					flowKey && metrics.tokenCapturedAt
						? Date.now() - metrics.tokenCapturedAt
						: null,
			}),
		);
		if (flowKey) {
			ws.send(JSON.stringify({ type: "token_captured", flowKey }));
		}
	};

	ws.onmessage = async ({ data }) => {
		let msg = null;
		try {
			msg = JSON.parse(data);

			if (msg.method === "api_request") {
				await handleApiRequest(msg);
			} else if (msg.method === "trpc_request") {
				await handleTrpcRequest(msg);
			} else if (msg.method === "solve_captcha") {
				await handleSolveCaptcha(msg);
			} else if (msg.method === "get_status") {
				const result = await executeWsMethodAndReply(
					msg,
					async () => getLocalRuntimeDiagnosticSnapshot(),
				);
				replyToAgent(msg, result);
			} else if (msg.method === "GET_RUNTIME_SELF_TEST") {
				const result = await executeWsMethodAndReply(msg, () =>
					handleRuntimeSelfTest(
						msg.params?.mode,
						msg.params?.attempt_open_project === true,
					),
				);
				replyToAgent(msg, result);
			} else if (msg.method === "BOOTSTRAP_FLOW_PROJECT_EDITOR") {
				const result = await executeWsMethodAndReply(msg, () =>
					handleBootstrapFlowProjectEditor(msg.params?.mode),
				);
				replyToAgent(msg, result);
			} else if (msg.type === "callback_secret") {
				_callbackSecret = msg.secret;
				chrome.storage.local.set({ callbackSecret: msg.secret });
				console.log("[FlowAgent] Received callback secret");
			} else if (msg.method === "CHECK_FLOW_COMPOSER_READY") {
				const result = await executeWsMethodAndReply(msg, () =>
					handleCheckFlowComposerReady(msg.params?.mode),
				);
				replyToAgent(msg, result);
			} else if (msg.method === "FLOW_PAGE_STATE_DIAGNOSTIC") {
				const result = await executeWsMethodAndReply(msg, () =>
					handleFlowPageStateDiagnostic(msg.params?.mode),
				);
				replyToAgent(msg, result);
			} else if (msg.method === "RELOAD_EXTENSION") {
				const result = await executeWsMethodAndReply(msg, () =>
					handleReloadExtension(),
				);
				replyToAgent(msg, result);
			} else if (msg.method === "RELOAD_FLOW_TAB") {
				const result = await executeWsMethodAndReply(msg, () =>
					handleReloadFlowTab(),
				);
				replyToAgent(msg, result);
			} else if (msg.method === "OPEN_TARGET_FLOW_PROJECT") {
				const result = await executeWsMethodAndReply(msg, () =>
					handleOpenTargetFlowProject(msg.params?.flow_project_url),
				);
				replyToAgent(msg, result);
			} else if (msg.method === "OPEN_FLOW_NEW_PROJECT") {
				const result = await executeWsMethodAndReply(msg, () =>
					handleOpenFlowNewProject(msg.params?.mode),
				);
				replyToAgent(msg, result);
			} else if (msg.method === "EXECUTE_FLOW_JOB") {
				// ACK immediately to prevent agent timeout on long jobs
				replyToAgent(msg, { accepted: true });

				// Run job asynchronously — post terminal telemetry when done so
				// the dashboard poll loop can exit (WAITING_FLOW otherwise stays forever).
				handleExecuteFlowJob(msg.params?.job).then((result) => {
					const requestId = msg.params?.job?.request_id;
					if (requestId) {
						postStageTelemetry({
							request_id: requestId,
							stage: result?.ok ? "COMPLETED" : "FAILED",
							status: result?.ok ? "PASS" : "FAIL",
							message: result?.error || result?.detail || (result?.ok ? "Job completed" : "Job failed"),
							source: "extension",
						}, null);
					}
				}).catch((err) => {
					console.error("[EXECUTE_FLOW_JOB] Async execution error:", err);
				});
			} else if (msg.method === "DEBUG_FLOW_DOM_EXECUTION") {
				const result = await executeWsMethodAndReply(msg, () =>
					handleDebugFlowDomExecution(msg.params?.mode, msg.params?.job),
				);
				replyToAgent(msg, result);
			} else if (msg.type === "pong") {
				// keepalive response
			} else if (msg?.id) {
				replyToAgent(
					msg,
					finalizeMethodPayload(
						msg.method || "UNKNOWN_METHOD",
						{
							ok: false,
							error: msg.method
								? "ERR_UNKNOWN_METHOD"
								: "ERR_UNKNOWN_MESSAGE_TYPE",
						},
						await getFlowTabSafe(),
					),
				);
			}
		} catch (e) {
			console.error("[FlowAgent] Message error:", e);
			if (msg?.id) {
				replyToAgent(
					msg,
					finalizeMethodPayload(
						msg.method || "UNKNOWN_METHOD",
						{
							ok: false,
							error: String(e?.message || e || "ERR_UNKNOWN_METHOD_FAILURE"),
						},
						await getFlowTabSafe(),
					),
				);
			} else {
				replyAgentError(msg, e);
			}
		}
	};

	ws.onclose = () => {
		setState("off");
		chrome.alarms.clear("token-refresh");
		updateRuntimeDiagnostics({
			ws_connected: false,
			runtime_reason: "EXTENSION_DISCONNECTED",
			runtime_detail: "Flow Kit extension WebSocket bridge closed.",
			diagnostic_code: "EXTENSION_DISCONNECTED",
			diagnostic_detail: "WebSocket connection to local agent is closed.",
		});
		if (!manualDisconnect) scheduleReconnect();
	};

	ws.onerror = (e) => {
		console.error("[FlowAgent] WS error:", e);
		metrics.lastError = "WS_ERROR";
		updateRuntimeDiagnostics({
			ws_connected: false,
			runtime_reason: "WS_ERROR",
			runtime_detail: "WebSocket connection to local agent failed.",
			diagnostic_code: "WS_ERROR",
			diagnostic_detail: String(e?.message || "WebSocket error"),
		});
		chrome.storage.local.set({ metrics });
	};
}

function scheduleReconnect() {
	chrome.alarms.create("reconnect", { delayInMinutes: 0.083 }); // ~5s
}

function clearHealthyBridgeWsError() {
	if (!ws || ws.readyState !== WebSocket.OPEN) return;
	if (metrics.lastError !== "WS_ERROR") return;
	metrics.lastError = null;
	chrome.storage.local.set({ metrics });
}

function keepAlive() {
	if (ws?.readyState === WebSocket.OPEN) {
		ws.send(JSON.stringify({ type: "ping" }));
	} else {
		connectToAgent();
	}
}

function sendToAgent(msg) {
	// API responses (with msg.id) go via HTTP — immune to WS disconnect
	if (msg.id) {
		fetch("http://127.0.0.1:8100/api/ext/callback", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(msg),
		}).catch(() => {
			// HTTP failed — fallback to WS
			if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
		});
		return;
	}
	// Non-response messages (ping, status) or no secret yet — use WS
	if (ws?.readyState === WebSocket.OPEN) {
		ws.send(JSON.stringify(msg));
	}
}

// ─── reCAPTCHA Solving ──────────────────────────────────────

async function requestCaptchaFromTab(tabId, requestId, pageAction) {
	try {
		await chrome.scripting.executeScript({
			target: { tabId },
			files: ["content.js"],
		});
	} catch (_) {}

	const initialResponse = await sendTabMessageSafe(
		tabId,
		{
			type: "GET_CAPTCHA",
			requestId,
			pageAction,
		},
		16000,
	);

	if (!initialResponse?.error) {
		return initialResponse;
	}

	const msg = initialResponse.error || "";
	const shouldInject =
		msg.includes("Receiving end does not exist") ||
		msg.includes("Could not establish connection") ||
		msg.includes("ERR_UNKNOWN_MESSAGE_TYPE") ||
		msg.includes("ERR_NO_RECEIVER");
	if (!shouldInject) {
		return initialResponse;
	}

	await chrome.scripting.executeScript({
		target: { tabId },
		files: ["content.js"],
	});
	await sleep(200);
	return await sendTabMessageSafe(
		tabId,
		{
			type: "GET_CAPTCHA",
			requestId,
			pageAction,
		},
		16000,
	);
}

async function solveCaptcha(requestId, captchaAction) {
	const tabs = await chrome.tabs.query({
		url: [
			"https://labs.google/fx/tools/flow*",
			"https://labs.google/fx/*/tools/flow*",
		],
	});

	if (!tabs.length) {
		// Auto-open Flow tab and wait briefly before returning error
		try {
			await chrome.tabs.create({
				url: "https://labs.google/fx/tools/flow",
				active: false,
			});
			await sleep(3000);
			// Retry tab query after opening
			const retryTabs = await chrome.tabs.query({
				url: [
					"https://labs.google/fx/tools/flow*",
					"https://labs.google/fx/*/tools/flow*",
				],
			});
			if (!retryTabs.length) return { error: "NO_FLOW_TAB" };
			const resp = await Promise.race([
				requestCaptchaFromTab(retryTabs[0].id, requestId, captchaAction),
				new Promise((_, rej) =>
					setTimeout(() => rej(new Error("CAPTCHA_TIMEOUT")), 30000),
				),
			]);
			return resp;
		} catch (e) {
			return { error: e.message || "NO_FLOW_TAB" };
		}
	}

	try {
		const resp = await Promise.race([
			requestCaptchaFromTab(tabs[0].id, requestId, captchaAction),
			new Promise((_, rej) =>
				setTimeout(() => rej(new Error("CAPTCHA_TIMEOUT")), 30000),
			),
		]);
		return resp;
	} catch (e) {
		return { error: e.message };
	}
}

async function handleSolveCaptcha(msg) {
	const { id, params } = msg;
	const result = await solveCaptcha(
		id,
		params?.captchaAction || "VIDEO_GENERATION",
	);

	// Standalone captcha solve counts as captcha-consuming
	metrics.requestCount++;
	if (result?.token) {
		metrics.successCount++;
	} else {
		metrics.failedCount++;
		metrics.lastError = result?.error || "NO_TOKEN";
	}
	chrome.storage.local.set({ metrics });

	sendToAgent({ id, result });
}

// ─── API Request Proxy ──────────────────────────────────────

async function handleTrpcRequest(msg) {
	const { id, params } = msg;
	const { url, method = "POST", headers = {}, body } = params;

	if (!url?.startsWith("https://labs.google/")) {
		sendToAgent({ id, error: "INVALID_TRPC_URL" });
		return;
	}

	setState("running");
	// TRPC calls don't consume captcha — don't count in metrics

	const logId = id;
	const _logType = url.includes("createProject") ? "CREATE_PROJECT" : "TRPC";
	// TRPC calls are silent — don't show in request log

	const fetchHeaders = { "Content-Type": "application/json", ...headers };
	if (flowKey) {
		fetchHeaders.authorization = `Bearer ${flowKey}`;
	}

	try {
		const resp = await fetch(url, {
			method,
			headers: fetchHeaders,
			body: body ? JSON.stringify(body) : undefined,
			credentials: "include",
		});
		const data = await resp.json();
		chrome.storage.local.set({ metrics });
		updateRequestLog(logId, { status: "success" });
		sendToAgent({ id, status: resp.status, data });
	} catch (e) {
		console.error("[FlowAgent] tRPC request failed:", e);
		chrome.storage.local.set({ metrics });
		updateRequestLog(logId, {
			status: "failed",
			error: e.message || "TRPC_FETCH_FAILED",
		});
		sendToAgent({ id, error: e.message || "TRPC_FETCH_FAILED" });
	} finally {
		setState("idle");
	}
}

async function handleApiRequest(msg) {
	const { id, params } = msg;
	const { url, method, headers, body, captchaAction } = params;

	if (!url) {
		sendToAgent({ id, error: "MISSING_URL" });
		return;
	}

	if (!url.startsWith("https://aisandbox-pa.googleapis.com/")) {
		sendToAgent({ id, error: "INVALID_URL" });
		return;
	}

	setState("running");
	const hasCaptcha = !!captchaAction;
	if (hasCaptcha) metrics.requestCount++;

	const logId = id;
	const logType = _classifyApiUrl(url);
	if (_VISIBLE_TYPES.has(logType)) {
		const payloadSummary = body ? JSON.stringify(body).slice(0, 200) : null;
		addRequestLog({
			id: logId,
			type: logType,
			time: new Date().toISOString(),
			status: "processing",
			error: null,
			outputUrl: null,
			url,
			payloadSummary,
		});
	}

	try {
		// Step 1: Solve captcha if needed
		let captchaToken = null;
		if (captchaAction) {
			const captchaResult = await solveCaptcha(id, captchaAction);
			captchaToken = captchaResult?.token || null;
			if (!captchaToken) {
				// Cannot proceed without captcha — API will 403
				const err = captchaResult?.error || "CAPTCHA_FAILED";
				console.error(
					`[FlowAgent] Captcha failed for ${captchaAction}: ${err}`,
				);
				sendToAgent({ id, status: 403, error: `CAPTCHA_FAILED: ${err}` });
				if (hasCaptcha) {
					metrics.failedCount++;
					metrics.lastError = `CAPTCHA_FAILED: ${err}`;
				}
				chrome.storage.local.set({ metrics });
				updateRequestLog(logId, {
					status: "failed",
					error: `CAPTCHA_FAILED: ${err}`,
				});
				setState("idle");
				return;
			}
		}

		// Step 2: Inject captcha token into body
		let finalBody = body;
		if (captchaToken && finalBody) {
			finalBody = JSON.parse(JSON.stringify(finalBody)); // deep clone
			if (finalBody.clientContext?.recaptchaContext) {
				finalBody.clientContext.recaptchaContext.token = captchaToken;
			}
			if (finalBody.requests && Array.isArray(finalBody.requests)) {
				for (const req of finalBody.requests) {
					if (req.clientContext?.recaptchaContext) {
						req.clientContext.recaptchaContext.token = captchaToken;
					}
				}
			}
		}

		// Step 3: Use flowKey for auth
		const activeFlowKey = flowKey;
		if (!activeFlowKey) {
			sendToAgent({ id, status: 503, error: "NO_FLOW_KEY" });
			if (hasCaptcha) {
				metrics.failedCount++;
				metrics.lastError = "NO_FLOW_KEY";
			}
			chrome.storage.local.set({ metrics });
			updateRequestLog(logId, { status: "failed", error: "NO_FLOW_KEY" });
			setState("idle");
			return;
		}

		const fetchHeaders = { ...(headers || {}) };
		fetchHeaders.authorization = `Bearer ${activeFlowKey}`;

		// Step 4: Make the API call from browser context
		const response = await fetch(url, {
			method: method || "POST",
			headers: fetchHeaders,
			credentials: "include",
			body: method === "GET" ? undefined : JSON.stringify(finalBody),
		});

		let responseData;
		const responseText = await response.text();
		try {
			responseData = JSON.parse(responseText);
		} catch {
			responseData = responseText;
		}

		sendToAgent({
			id,
			status: response.status,
			data: responseData,
		});

		const responseSummary = responseText ? responseText.slice(0, 300) : null;
		if (response.ok) {
			if (hasCaptcha) {
				metrics.successCount++;
				metrics.lastError = null;
			}
			updateRequestLog(logId, {
				status: "success",
				httpStatus: response.status,
				responseSummary,
			});
		} else {
			if (hasCaptcha) {
				metrics.failedCount++;
				metrics.lastError = `API_${response.status}`;
			}
			updateRequestLog(logId, {
				status: "failed",
				error: `API_${response.status}`,
				httpStatus: response.status,
				responseSummary,
			});
		}
	} catch (e) {
		sendToAgent({
			id,
			status: 500,
			error: e.message || "API_REQUEST_FAILED",
		});
		if (hasCaptcha) {
			metrics.failedCount++;
			metrics.lastError = e.message;
		}
		updateRequestLog(logId, {
			status: "failed",
			error: e.message || "API_REQUEST_FAILED",
		});
	}

	chrome.storage.local.set({ metrics });
	setState("idle");
}

// ─── State & Popup ──────────────────────────────────────────

function setState(newState) {
	state = newState;
	const badges = { idle: "●", running: "▶", off: "○" };
	const colors = { idle: "#22c55e", running: "#f59e0b", off: "#6b7280" };
	chrome.action.setBadgeText({ text: badges[state] || "" });
	chrome.action.setBadgeBackgroundColor({ color: colors[state] || "#000" });
	broadcastStatus();
}

function broadcastStatus() {
	sendRuntimeMessageNoThrow({ type: "STATUS_PUSH" });
}

const BUILD_ID = "flowkit-gfv2-post-submit-proof-2026-06-28a";

function buildBackgroundStatusResponse() {
	const buildId = BUILD_ID;
	const runtimeReady = true;
	return {
		connected: ws?.readyState === WebSocket.OPEN,
		agentConnected: ws?.readyState === WebSocket.OPEN,
		flowKeyPresent: !!flowKey,
		manualDisconnect,
		tokenAge: metrics.tokenCapturedAt
			? Date.now() - metrics.tokenCapturedAt
			: null,
		metrics: {
			requestCount: metrics.requestCount,
			successCount: metrics.successCount,
			failedCount: metrics.failedCount,
			lastError: metrics.lastError,
		},
		state,
		buildId,
		build_id: buildId,
		background_build_id: buildId,
		gitSha: buildId,
		git_sha: buildId,
		runtimeReady,
		runtime_ready: runtimeReady,
		// Background-only identity is not build alignment proof.
		build_match: false,
		build_match_scope: "background_only_unverified",
		worker_alive: true,
		service_worker_started_at: runtimeDiagnostics.service_worker_started_at,
		ws_connected: ws?.readyState === WebSocket.OPEN,
		runtime_reason: runtimeDiagnostics.runtime_reason,
		runtime_detail: runtimeDiagnostics.runtime_detail,
		auth_state: runtimeDiagnostics.auth_state,
		flow_path_state: runtimeDiagnostics.flow_path_state,
		target_project_state: runtimeDiagnostics.target_project_state,
		target_project_url: runtimeDiagnostics.target_project_url,
		flow_tab_url: runtimeDiagnostics.flow_tab_url,
		fallback_editor_url: runtimeDiagnostics.fallback_editor_url,
		stored_flow_project_url: runtimeDiagnostics.stored_flow_project_url,
		last_bad_redirect_url: runtimeDiagnostics.last_bad_redirect_url,
		diagnostic_code: runtimeDiagnostics.diagnostic_code,
		diagnostic_detail: runtimeDiagnostics.diagnostic_detail,
		selected_tab_id: runtimeDiagnostics.selected_tab_id,
		active_editor_tab_id: runtimeDiagnostics.active_editor_tab_id,
		selected_tab_active: runtimeDiagnostics.selected_tab_active,
		selected_tab_url: runtimeDiagnostics.selected_tab_url,
		active_editor_tab_url: runtimeDiagnostics.active_editor_tab_url,
		rebound_to_active_editor_tab:
			runtimeDiagnostics.rebound_to_active_editor_tab,
		same_project_url: runtimeDiagnostics.same_project_url,
		content_script_alive_on_active_tab:
			runtimeDiagnostics.content_script_alive_on_active_tab,
		safe_to_click_active_tab: runtimeDiagnostics.safe_to_click_active_tab,
		last_updated_at: runtimeDiagnostics.last_updated_at,
	};
}

function buildStageTelemetryPayload(message = {}, contentHealth = null) {
	const contentBuildId =
		message.content_build_id ||
		contentHealth?.content_build_id ||
		"CONTENT_BUILD_UNAVAILABLE";
	const runtimeReady =
		typeof message.runtime_ready === "boolean"
			? message.runtime_ready
			: Boolean(contentHealth?.runtime_ready);
	const calculatedBuildMatch = Boolean(
		runtimeReady &&
			contentBuildId !== "CONTENT_BUILD_UNAVAILABLE" &&
			contentBuildId === BUILD_ID,
	);
	return {
		request_id: message.request_id,
		timestamp: message.timestamp || new Date().toISOString(),
		git_sha: message.git_sha || BUILD_ID,
		background_build_id: BUILD_ID,
		content_build_id: contentBuildId,
		stage: message.stage,
		checkpoint: message.checkpoint || message.stage,
		status: message.status,
		message: message.message || null,
		source: message.source || "extension",
		runtime_ready: runtimeReady,
		build_match:
			calculatedBuildMatch &&
			(typeof message.build_match !== "boolean" || message.build_match),
		selector_used: message.selector_used || null,
		evidence_pointer: message.evidence_pointer || null,
		fail_code: message.fail_code || null,
		first_fail_stage: message.first_fail_stage || null,
	};
}

function postStageTelemetry(message = {}, contentHealth = null) {
	if (!message?.request_id || !message?.stage || !message?.status) {
		return;
	}
	fetch("http://127.0.0.1:8100/api/telemetry/stage", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(buildStageTelemetryPayload(message, contentHealth)),
	}).catch(() => {});
}

async function handleMessage(msg, sender) {
	if (
		msg?.type !== "DISCONNECT" &&
		msg?.type !== "RECONNECT" &&
		(!ws ||
			ws.readyState === WebSocket.CLOSED ||
			ws.readyState === WebSocket.CLOSING)
	) {
		connectToAgent();
	}

	if (msg.type === "STATUS") {
		return buildBackgroundStatusResponse();
	}

	if (msg.type === "LOCAL_RUNTIME_DIAGNOSTIC") {
		return getLocalRuntimeDiagnosticSnapshot();
	}

	if (msg.type === "BOOTSTRAP_FLOW_PROJECT_EDITOR") {
		return await handleBootstrapFlowProjectEditor(msg.mode);
	}

	if (msg.type === "DISCONNECT") {
		manualDisconnect = true;
		if (ws) ws.close();
		return { ok: true };
	}

	if (msg.type === "RECONNECT") {
		manualDisconnect = false;
		init(); // Use init to ensure storage is loaded too
		return { ok: true };
	}

	if (msg.type === "REQUEST_LOG") {
		// If we have history on local agent, try to merge or prefer it
		try {
			const resp = await fetch(
				"http://127.0.0.1:8100/api/requests/snapshot?project_id=any&limit=20",
			);
			if (resp.ok) {
				const history = await resp.json();
				if (history && history.length > 0) {
					// Map backend Requests to extension log format if needed
					const merged = history.map((r) => ({
						id: r.id,
						type: r.type,
						time: r.created_at,
						status: r.status,
						error: r.error_message || "",
						isBackend: true,
					}));
					return { log: merged };
				}
			}
		} catch (e) {
			console.warn("Failed to sync history from agent:", e);
		}
		return { log: requestLog };
	}

	if (msg.type === "OPEN_FLOW_TAB") {
		const tabs = await chrome.tabs.query({
			url: [
				"https://labs.google/fx/tools/flow*",
				"https://labs.google/fx/*/tools/flow*",
			],
		});
		if (tabs.length) {
			await chrome.tabs.update(tabs[0].id, { active: true });
			return { ok: true, tabId: tabs[0].id };
		}
		const tab = await chrome.tabs.create({
			url: "https://labs.google/fx/tools/flow",
		});
		return { ok: true, tabId: tab.id };
	}

	if (msg.type === "REFRESH_TOKEN") {
		await captureTokenFromFlowTab();
		return { ok: true };
	}

	if (msg.type === "TEST_CAPTCHA") {
		const result = await solveCaptcha(
			`test-${Date.now()}`,
			msg.pageAction || "IMAGE_GENERATION",
		);
		return result?.error
			? { ok: false, error: result.error }
			: { ok: true, data: result };
	}

	if (msg.type === "TRPC_MEDIA_URLS") {
		handleTrpcMediaUrls(msg.trpcUrl, msg.body);
		return { ok: true };
	}

	if (msg.type === "CHECK_FLOW_COMPOSER_READY") {
		return await handleCheckFlowComposerReady(msg.mode);
	}

	if (msg.type === "OPEN_FLOW_NEW_PROJECT") {
		return await handleOpenFlowNewProject(msg.mode);
	}

	if (msg.type === "RELOAD_FLOW_TAB") {
		return await handleReloadFlowTab();
	}

	if (msg.type === "EXECUTE_FLOW_JOB") {
		return await handleExecuteFlowJob(msg.job);
	}

	if (msg.type === "CONFIGURE_F2V_SETTINGS") {
		return await handleConfigureF2VSettings(msg.job, sender?.tab?.id);
	}

	if (msg.type === "FLOW_JOB_COMPLETED" || msg.type === "FLOW_JOB_FAILED") {
		return { ok: true };
	}

	if (msg.type === "FLOW_STAGE_EVENT") {
		const contentHealth = sender?.tab?.id
			? getKnownContentScriptHealth(sender.tab.id)
			: null;
		postStageTelemetry(
			{ ...msg, source: msg.source || "extension" },
			contentHealth,
		);
		return { ok: true };
	}

	if (msg.type === "FLOWKIT_CDP_BEGIN_FILE_CHOOSER_POC") {
		let filePath = msg.filePath;
		let expectedFileName = msg.expectedFileName;
		if (
			(!filePath || typeof filePath !== "string") &&
			msg.assetSource != null
		) {
			const materialized = await materializeAssetToDiskPath(
				msg.assetSource,
				msg.slotLabel,
			);
			if (!materialized?.ok) {
				return materialized;
			}
			filePath = materialized.filePath;
			expectedFileName =
				expectedFileName || materialized.fileName || msg.expectedFileName;
		}
		return await beginCdpFileChooserProof(
			sender?.tab?.id || null,
			filePath,
			expectedFileName,
			msg.slotLabel,
		);
	}

	if (msg.type === "FLOWKIT_CDP_WAIT_FILE_CHOOSER_POC") {
		return await waitForCdpFileChooserProof(sender?.tab?.id || null);
	}

	if (msg.type === "RESOLVE_LOCAL_ASSET") {
		const { assetId, filename, request_id } = msg;
		const url = `http://127.0.0.1:8100/api/products/${assetId}/image`;
		console.log(
			`[FlowAgent] Background proxy resolving asset: ${assetId} from ${url}`,
		);

		if (request_id) {
			postStageTelemetry({
				request_id,
				stage: "BACKGROUND_ASSET_PROXY_RECEIVED",
				checkpoint: "BACKGROUND_ASSET_PROXY_RECEIVED",
				status: "PASS",
				message: `assetId=${assetId}`,
				source: "extension",
			});
		}

		const controller = new AbortController();
		const timeoutId = setTimeout(() => controller.abort(), 10000);

		try {
			const resp = await fetch(url, { signal: controller.signal });
			clearTimeout(timeoutId);
			console.log(`[FlowAgent] Background fetch status: ${resp.status}`);
			if (!resp.ok) {
				return {
					ok: false,
					error: "ERR_BACKGROUND_ASSET_FETCH_FAILED",
					detail: `HTTP_${resp.status}`,
				};
			}
			const blob = await resp.blob();
			console.log(
				`[FlowAgent] Background fetch blob: ${blob.size} bytes, type: ${blob.type}`,
			);
			const buffer = await blob.arrayBuffer();
			const bytes = new Uint8Array(buffer);
			let binary = "";
			for (let i = 0; i < bytes.byteLength; i++) {
				binary += String.fromCharCode(bytes[i]);
			}
			const dataUrl = `data:${blob.type || "image/jpeg"};base64,${btoa(binary)}`;
			console.log(
				`[FlowAgent] Background proxy success: ${dataUrl.length} chars`,
			);
			return { ok: true, dataUrl, mimeType: blob.type, filename };
		} catch (e) {
			clearTimeout(timeoutId);
			console.error(`[FlowAgent] Background proxy error: ${e.message}`);
			return {
				ok: false,
				error: "ERR_BACKGROUND_ASSET_FETCH_FAILED",
				detail: e.message,
			};
		}
	}

	return {
		ok: false,
		error: "ERR_UNKNOWN_MESSAGE_TYPE",
		detail: `type=${msg.type}`,
	};
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
	if (message.type === "STATUS") {
		sendResponse(buildBackgroundStatusResponse());
		return false;
	}

	if (message.type === "GET_RUNTIME_SELF_TEST") {
		return respondAsync(sendResponse, async () =>
			handleRuntimeSelfTest(
				message.mode,
				message.attempt_open_project === true,
			),
		);
	}

	// LONG-RUNNING JOBS: Use immediate ACK pattern
	if (message.type === "EXECUTE_FLOW_JOB") {
		sendResponse({
			ok: true,
			accepted: true,
			request_id: message.job?.request_id,
		});

		// Execute asynchronously after returning
		setTimeout(async () => {
			try {
				const result = await handleExecuteFlowJob(message.job);
				// Send final status via FLOW_JOB_COMPLETED
				sendRuntimeMessageNoThrow({
					type: "FLOW_JOB_COMPLETED",
					request_id: message.job?.request_id,
					result: result,
					success: result.ok === true,
				});
			} catch (err) {
				// Send error via FLOW_JOB_FAILED
				sendRuntimeMessageNoThrow({
					type: "FLOW_JOB_FAILED",
					request_id: message.job?.request_id,
					error: String(err?.message || err),
				});
			}
		}, 0);

		return false; // Already called sendResponse synchronously
	}

	if (message.type === "CHECK_FLOW_COMPOSER_READY") {
		return respondAsync(sendResponse, async () => {
			const result = await handleCheckFlowComposerReady(message.mode);
			return result && typeof result === "object" && "ok" in result
				? result
				: { ok: true, data: result };
		});
	}

	if (message.type === "OPEN_FLOW_NEW_PROJECT") {
		return respondAsync(sendResponse, async () => {
			const result = await handleOpenFlowNewProject(message.mode);
			return result && typeof result === "object" && "ok" in result
				? result
				: { ok: true, data: result };
		});
	}

	if (message.type === "RELOAD_FLOW_TAB") {
		return respondAsync(sendResponse, async () => {
			const result = await handleReloadFlowTab();
			return result && typeof result === "object" && "ok" in result
				? result
				: { ok: true, data: result };
		});
	}

	// CONFIGURE_F2V_SETTINGS runs the full settings SOP (Video → Frames → 9:16 → 1x → Model).
	// Each of the 6 steps has ~300ms settle + executeScript round-trips — total can reach 10-30s.
	// Must NOT fall through to the 4500ms default catch-all or it times out every time.
	if (message.type === "CONFIGURE_F2V_SETTINGS") {
		return respondAsync(
			sendResponse,
			async () => {
				const data = await handleMessage(message, sender);
				return data && typeof data === "object" && "ok" in data
					? data
					: { ok: true, data };
			},
			60000,
		);
	}

	return respondAsync(sendResponse, async () => {
		const data = await handleMessage(message, sender);
		return data && typeof data === "object" && "ok" in data
			? data
			: { ok: true, data };
	});
});

// Strict lane: bind the CURRENT healthy Flow editor only. NEVER opens/creates a
// project, NEVER runs broad recovery. Fails closed if no healthy editor exists.
async function handleF2VPackageUploadOnlyJob(job) {
	const requestId = job?.request_id || null;
	const emit = (stage, status, message) => {
		if (!requestId) return;
		postStageTelemetry(
			{ request_id: requestId, stage, status, message, source: "extension" },
			null,
		);
	};

	// Preflight: package is the only source of truth.
	const validation = validateF2VPackageUploadOnlyJob(job);
	if (!validation.ok) {
		emit("FAILED", "FAIL", validation.error);
		return { ok: false, error: validation.error, detail: validation.detail };
	}
	emit("F2V_PACKAGE_UPLOAD_ONLY_ACCEPTED", "PASS", `request_id=${requestId}`);
	emit(
		"PACKAGE_SOURCE_VALIDATED",
		"PASS",
		`workspace_execution_package_id=${job.workspace_execution_package_id}`,
	);

	// Bind the CURRENT editor only — read-only preflight, no recovery, no open.
	const preferredUrl = await getStoredFlowProjectUrl();
	const tabs = await getFlowTabs();
	const activeTabPreflight = await buildActiveFlowTabPreflight("F2V", {
		preferredUrl,
		tabs,
	});
	const selectedTab = activeTabPreflight?.selectedTab || null;
	const selectedUrl = String(selectedTab?.url || "").trim();
	const editorHealthy = Boolean(
		activeTabPreflight?.ok &&
			selectedTab?.id &&
			isProjectEditorUrl(selectedUrl) &&
			!isRootFlowUrl(selectedUrl) &&
			!activeTabPreflight?.brokenTargetRejected,
	);
	if (!editorHealthy) {
		const failCode = activeTabPreflight?.brokenTargetRejected
			? "ERR_FLOW_EDITOR_BROKEN"
			: "ERR_FLOW_EDITOR_REQUIRED";
		emit("FAILED", "FAIL", failCode);
		return {
			ok: false,
			error: failCode,
			detail: {
				reason: "no_healthy_current_editor_for_upload_only_lane",
				runtime_binding_error: activeTabPreflight?.error || null,
				selected_tab_url: selectedUrl || null,
				broken_target_rejected: Boolean(activeTabPreflight?.brokenTargetRejected),
			},
		};
	}
	emit("FLOW_EDITOR_READY", "PASS", `tab=${selectedTab.id} url=${selectedUrl}`);

	// Route to the content-script strict path — never the broad SOP runner.
	await ensureFlowDomScript(selectedTab.id);
	const laneJob = { ...job, lane: "F2V_PACKAGE_UPLOAD_ONLY", upload_only: true };
	const result = await sendTabMessageSafe(
		selectedTab.id,
		{ type: "EXECUTE_FLOW_JOB", job: laneJob },
		120000,
	);
	if (result?.raw_error) {
		emit("FAILED", "FAIL", result.raw_error);
		return { ok: false, error: result.raw_error, detail: result.detail || null };
	}
	return result;
}

// ---- Google Flow V2 runtime lane: GFV2_UPLOAD_SETTINGS_PROMPT_GENERATE ----
// V2 contract: Upload media -> Add to Prompt -> Settings -> Prompt -> Generate.
// Does NOT require Frames/Ingredients buttons, /project/ URL, or Start-slot proof.
// Reuses the proven SOP runner (skipGenerate) and stops BEFORE Generate.

const GFV2_FLOW_ROOT_URL = "https://labs.google/fx/tools/flow";

function isGfv2Lane(job) {
	return Boolean(
		job &&
			(
				job.lane === "GFV2_UPLOAD_SETTINGS_PROMPT_GENERATE" ||
				job.lane === "GFV2_POST_SUBMIT_DOWNLOAD" ||
				job.gfv2 === true ||
				job.postSubmitDownload === true
			),
	);
}

function isGfv2PostSubmitDownload(job) {
	return Boolean(
		job &&
			(job.lane === "GFV2_POST_SUBMIT_DOWNLOAD" || job.postSubmitDownload === true),
	);
}

// Maps the proven SOP runner stages to the V2 telemetry contract.
// NB: settings stages are NOT mapped here — the gfv2SettingsVerify hook owns the
// granular GFV2 settings telemetry (panel opened / 9:16 / 1x / model / persisted)
// so the proof is DOM-confirmed and never duplicated.
const GFV2_STAGE_MAP = Object.freeze({
	F2V_SOP_START_CLICKED: "GFV2_UPLOAD_MEDIA_OPENED",
	F2V_SOP_UPLOAD_CLICKED: "GFV2_ASSET_SELECTED",
	F2V_SOP_UPLOAD_WAIT_DONE: "GFV2_ADD_TO_PROMPT_CLICKED",
	F2V_SOP_PROMPT_INSERTED: "GFV2_PROMPT_INSERTED",
});

// PURE three-party build decision. A matching background ID alone is never
// sufficient: GFV2 requires a live page response from content-flow-dom plus
// the runner's exported build ID before any visible SOP action may execute.
function gfv2DecideBuildProof(input) {
	const backgroundBuildId = String(input?.background_build_id || "").trim();
	const runnerBuildId = String(input?.runner_build_id || "").trim();
	const pageDiagnostic = input?.page_diagnostic || null;
	const contentBuildId = String(
		pageDiagnostic?.content_build_id || "",
	).trim();
	const contentProofLive = Boolean(
		pageDiagnostic &&
			contentBuildId &&
			pageDiagnostic.content_script_loaded === true &&
			pageDiagnostic.content_script_alive === true &&
			pageDiagnostic.runtime_ready === true,
	);
	const detail = {
		background_build_id: backgroundBuildId || null,
		runner_build_id: runnerBuildId || null,
		content_build_id: contentBuildId || null,
		content_script_loaded: Boolean(pageDiagnostic?.content_script_loaded),
		content_script_alive: Boolean(pageDiagnostic?.content_script_alive),
		runtime_ready: Boolean(pageDiagnostic?.runtime_ready),
		page_build_match: pageDiagnostic?.build_match === true,
	};

	if (!contentProofLive) {
		return {
			...detail,
			proceed: false,
			build_match: false,
			error: "GFV2_CONTENT_BUILD_UNAVAILABLE",
			detail,
		};
	}
	if (!backgroundBuildId || !runnerBuildId) {
		return {
			...detail,
			proceed: false,
			build_match: false,
			error: "GFV2_BUILD_PROOF_UNAVAILABLE",
			detail,
		};
	}

	const buildMatch = Boolean(
		pageDiagnostic.build_match === true &&
			backgroundBuildId === runnerBuildId &&
			backgroundBuildId === contentBuildId,
	);
	if (!buildMatch) {
		return {
			...detail,
			proceed: false,
			build_match: false,
			error: "GFV2_BUILD_MISMATCH",
			detail,
		};
	}
	return {
		...detail,
		proceed: true,
		build_match: true,
		error: null,
		detail,
	};
}

// PURE granular-settings decision: given the V2 readiness settings proof, returns the
// ordered telemetry emissions + a proceed/blocker verdict. Enforces, in order:
//   1. settings surface DOM-confirmed (panel open OR composer pill readable)
//   2. visible wrong (image) model -> HARD FAIL (never soft-passed)
//   3. 9:16 required   4. 1x required
//   5. visible Veo Lite confirmed OR hidden soft-pass (only with 9:16+1x and no wrong model)
//   6. persistence (V2 has no Save button -> live composer reflection is the proof)
function gfv2DecideSettingsProof(proof, observedModel, opts) {
	const requireVisibleVeo = Boolean(opts && opts.requireVisibleVeo);
	const p = proof || {};
	const panelOpened = Boolean(p.settings_panel_opened);
	const ratioOk = Boolean(p.ratio_9_16_confirmed);
	const countOk = Boolean(p.count_1x_confirmed);
	const wrongModel = Boolean(p.model_visible_wrong);
	const veoOk = Boolean(p.model_veo_lite_confirmed);
	const modelState = p.model_state || "unknown";
	const detail = {
		panel_opened: panelOpened,
		ratio_9_16_confirmed: ratioOk,
		count_1x_confirmed: countOk,
		model_state: modelState,
		model_visible_wrong: wrongModel,
		model_veo_lite_confirmed: veoOk,
		model_canonical: p.model_canonical || observedModel || null,
	};
	const emissions = [];
	const push = (stage, status, message) => emissions.push({ stage, status, message });

	if (panelOpened || (ratioOk && countOk)) {
		push("GFV2_SETTINGS_OPENED", "PASS", `source=${panelOpened ? "settings_panel_dom" : "composer_pill_confirmed"}`);
	} else {
		push("GFV2_SETTINGS_PANEL_NOT_FOUND", "FAIL", JSON.stringify(detail));
		return { emissions, proceed: false, error: "GFV2_SETTINGS_PANEL_NOT_FOUND", detail };
	}
	if (wrongModel) {
		push("GFV2_VISIBLE_WRONG_MODEL", "FAIL", `model=${detail.model_canonical || "?"}`);
		return { emissions, proceed: false, error: "GFV2_VISIBLE_WRONG_MODEL", detail };
	}
	if (ratioOk) {
		push("GFV2_RATIO_9_16_CONFIRMED", "PASS", "source=composer");
	} else {
		push("GFV2_RATIO_9_16_NOT_CONFIRMED", "FAIL", JSON.stringify(detail));
		return { emissions, proceed: false, error: "GFV2_RATIO_9_16_NOT_CONFIRMED", detail };
	}
	if (countOk) {
		push("GFV2_COUNT_1X_CONFIRMED", "PASS", "source=composer");
	} else {
		push("GFV2_COUNT_1X_NOT_CONFIRMED", "FAIL", JSON.stringify(detail));
		return { emissions, proceed: false, error: "GFV2_COUNT_1X_NOT_CONFIRMED", detail };
	}
	if (veoOk) {
		push("GFV2_MODEL_VEO_LITE_CONFIRMED", "PASS", `model=${detail.model_canonical || "veo lite"}`);
	} else if (requireVisibleVeo) {
		// Video lane: the target Veo 3.1 - Lite must be confirmed (no soft-pass when a
		// concrete video model dropdown exists but Veo Lite could not be selected).
		push("GFV2_MODEL_VEO_LITE_NOT_FOUND", "FAIL", `model_state=${modelState} model=${detail.model_canonical || "?"}`);
		return { emissions, proceed: false, error: "GFV2_MODEL_VEO_LITE_NOT_FOUND", detail };
	} else {
		push("GFV2_MODEL_HIDDEN_SOFT_PASS", "PASS", `model_state=${modelState} ratio_count_confirmed=true no_visible_wrong_model=true`);
	}
	// Persistence: an explicit false from the interactive primitive is a hard fail;
	// undefined (pure-logic tests / observe path) is treated as composer-reflected.
	if (p.settings_persisted === false) {
		push("GFV2_SETTINGS_NOT_PERSISTED", "FAIL", `ratio=${ratioOk} count=${countOk} veo=${veoOk}`);
		return { emissions, proceed: false, error: "GFV2_SETTINGS_NOT_PERSISTED", detail };
	}
	push("GFV2_SETTINGS_SAVED_OR_PERSISTED", "PASS", `persistence=${p.settings_persisted === undefined ? "composer_reflected" : "video_section_verified"} save_button_found=${Boolean(p.save_button_found)}`);
	return { emissions, proceed: true, detail };
}

// Read-only granular GFV2 settings verification: capture the live V2 readiness proof,
// run the pure decision, emit each stage in order, return { proceed, error, detail }.
// Interactive granular settings verification: drive the content-script V2 settings
// primitive (open panel, confirm/select 9:16 + 1x, read model, persist), then run the
// pure decision over the REAL applied result. These are live hard gates.
async function gfv2DriveSettingsVerify(flowTab, emit, options = {}) {
	await ensureFlowDomScript(flowTab.id);
	const applyOptions = {
		requireSaveTransition: options.requireSaveTransition === true,
		expectedPrompt: String(options.expectedPrompt || ""),
	};
	let res = await sendTabMessageSafe(
		flowTab.id,
		{ type: "GFV2_APPLY_SETTINGS", options: applyOptions },
		35000,
	);
	if (
		[
			"ERR_MESSAGE_RESPONSE_TIMEOUT",
			"ERR_NO_RECEIVER",
			"ERR_CONTENT_SCRIPT_STALE",
			"ERR_TAB_RELOADED",
		].includes(res?.error)
	) {
		await ensureFlowDomScript(flowTab.id);
		res = await sendTabMessageSafe(
			flowTab.id,
			{ type: "GFV2_APPLY_SETTINGS", options: applyOptions },
			35000,
		);
	}
	res = res || {};
	// Surface the real V2 controls + launcher candidates for forensics.
	if (Array.isArray(res.launcher_candidates)) {
		emit("GFV2_SETTINGS_LAUNCHERS", "WAITING_FLOW", JSON.stringify(res.launcher_candidates).slice(0, 1000));
	}
	if (Array.isArray(res.controls_seen) && res.controls_seen.length) {
		const json = JSON.stringify(res.controls_seen);
		for (let i = 0; i < json.length && i < 9000; i += 1800) {
			emit("GFV2_SETTINGS_DISCOVERY", "WAITING_FLOW", `part${Math.floor(i / 1800)} ${json.slice(i, i + 1800)}`);
		}
	}
	emit("GFV2_SETTINGS_VIDEO_BAND", "WAITING_FLOW", JSON.stringify({ band: res.video_band || null, model_before: res.model_before || null, model_after: res.model_after || null, model_dropdown_options: res.model_dropdown_options || null, veo_lite_option_text: res.veo_lite_option_text || null, actions: res.actions || [] }).slice(0, 800));
	// The primitive could not even locate the Video generation default section.
	if (res.error === "GFV2_SETTINGS_PANEL_NOT_FOUND" && !res.settings_panel_opened) {
		emit("GFV2_SETTINGS_PANEL_NOT_FOUND", "FAIL", res.detail || "video_section_not_found");
		return { proceed: false, error: "GFV2_SETTINGS_PANEL_NOT_FOUND", detail: res };
	}
	if (applyOptions.requireSaveTransition) {
		if (res.save_button_found) {
			emit(
				"GFV2_SETTINGS_SAVE_CLICKED",
				"WAITING_FLOW",
				`settings_state_before=${res?.agent_settings_state_before_save?.identity || "unknown"}`,
			);
		}
		if (res.settings_transition_verified !== true) {
			const transitionError =
				res.error || "GFV2_COMPOSER_NOT_READY_AFTER_SETTINGS";
			emit(
				"GFV2_SETTINGS_SAVE_VERIFICATION_FAILED",
				"FAIL",
				JSON.stringify({
					error: transitionError,
					settings_active: Boolean(res.agent_settings_active_after_save),
					composer_editable: Boolean(res.composer_editable_after_save),
					prompt_reflected: Boolean(res.prompt_reflected_after_save),
				}),
			);
			return { proceed: false, error: transitionError, detail: res };
		}
	}
	const proof = {
		settings_panel_opened: Boolean(res.settings_panel_opened),
		ratio_9_16_confirmed: Boolean(res.ratio_9_16_confirmed),
		count_1x_confirmed: Boolean(res.count_1x_confirmed),
		model_visible_wrong: Boolean(res.model_visible_wrong),
		model_veo_lite_confirmed: Boolean(res.model_veo_lite_confirmed),
		model_state: res.model_visible_wrong ? "wrong" : res.model_veo_lite_confirmed ? "correct" : "unknown",
		model_canonical: res.model_canonical || null,
		save_button_found: Boolean(res.save_button_found),
		settings_persisted: Boolean(res.settings_saved_or_persisted),
	};
	// Video lane: require Veo 3.1 - Lite to be confirmed inside the Video section (no
	// hidden soft-pass when a real video model dropdown exists).
	const decision = gfv2DecideSettingsProof(proof, proof.model_canonical, { requireVisibleVeo: true });
	for (const e of decision.emissions) emit(e.stage, e.status, e.message);
	// Post-upload, the V2 generation settings DO render — these are real live gates.
	if (!decision.proceed) {
		// surface the primitive's more specific Veo-not-found cause if applicable
		const err =
			res.error === "GFV2_MODEL_VEO_LITE_NOT_FOUND" && decision.error === "GFV2_MODEL_VEO_LITE_NOT_FOUND"
				? res.error
				: decision.error;
		return { proceed: false, error: err, detail: { decision: decision.detail, applied: res } };
	}
	if (applyOptions.requireSaveTransition) {
		emit(
			"GFV2_SETTINGS_SAVE_VERIFIED",
			"PASS",
			JSON.stringify({
				settings_active: false,
				composer_editable: true,
				prompt_reflected: true,
				composer_identity: res.composer_identity_after_save || null,
			}),
		);
	}
	return { proceed: true, detail: decision.detail, proof, applied: res };
}

// Post-upload settings probe: once media is in the composer, re-drive the V2 settings
// primitive to discover whether the generation settings (9:16/1x/model) are now
// reachable. Emits a probe stage with the result + a discovery dump. Read/observe;
// hard-fails nothing here (investigation), but reports the real reachability.
// Decide whether a Flow tab is a usable V2 surface from its URL + a V2 capture.
// Pure-ish: takes the tab and a captured GFV2 readiness result. Stale c240ebbd and
// "Back to projects" / "Something went wrong" pages are NOT valid surfaces.
function gfv2ClassifySurface(tab, capture) {
	const url = String(tab?.url || "");
	if (url.includes("c240ebbd")) {
		return { healthy: false, reason: "stale_stored_project" };
	}
	const diag = capture?.diagnostic || {};
	const editorOk = Boolean(capture?.ok && capture?.evaluation?.proofs?.editor?.ok);
	const routeLooksEditor = Boolean(isProjectEditorUrl(url) && !isRootFlowUrl(url));
	const composerStrong = Boolean(
		diag?.composer_found &&
			diag?.composer_editable &&
			!diag?.landing_nav_only &&
			(diag?.generate_button_found ||
				diag?.bottom_composer_config_pill_visible ||
				diag?.current_mode_visible !== "UNKNOWN"),
	);
	const buttons = (Array.isArray(diag.button_texts) ? diag.button_texts : [])
		.join(" ")
		.toLowerCase();
	const wentWrong =
		/something went wrong/.test(buttons) ||
		(/back to projects/.test(buttons) && !editorOk);
	if (wentWrong) {
		return { healthy: false, reason: "something_went_wrong" };
	}
	if (diag.login_or_access_blocker) {
		return { healthy: false, reason: "login_or_access_blocker" };
	}
	if (diag.landing_nav_only) {
		return { healthy: false, reason: "landing_nav_only" };
	}
	if (editorOk && (routeLooksEditor || composerStrong)) {
		return { healthy: true, reason: "ok" };
	}
	if (diag.root_flow_url && !routeLooksEditor && !composerStrong) {
		return { healthy: false, reason: "landing_nav_only" };
	}
	return { healthy: false, reason: "no_editor_surface" };
}

// GFV2_ENSURE_SURFACE: acquire a healthy Google Flow V2 surface automatically.
// Ignores stale/broken tabs, opens/focuses Flow root, reaches a session if needed.
// Never navigates to stored stale project URLs; never resumes Option B auto-nav.
async function gfv2EnsureSurface(mode, emit) {
	emit("GFV2_ENSURE_SURFACE_STARTED", "WAITING_FLOW", null);
	const tabs = await getFlowTabs();

	// 1. Prefer an already-open HEALTHY surface.
	for (const tab of tabs) {
		const cap = await captureGoogleFlowV2Readiness(tab);
		const cls = gfv2ClassifySurface(tab, cap);
		if (!cls.healthy) {
			if (cls.reason === "stale_stored_project" || cls.reason === "something_went_wrong") {
				emit("GFV2_STALE_FLOW_TAB_IGNORED", "WAITING_FLOW", `url=${tab.url} reason=${cls.reason}`);
			}
			continue;
		}
		try {
			await focusTab(tab);
		} catch (_) {}
		emit("GFV2_SURFACE_READY", "PASS", `tab=${tab.id} url=${String(tab.url).slice(0, 80)} strategy=existing_healthy`);
		return { ok: true, tab: (await getTabSafe(tab.id)) || tab };
	}

	// 2. No healthy surface — open a BRAND-NEW tab directly to Flow root.
	//    Deliberately do NOT call openPreferredFlowProjectOrNewProject (it settled
	//    back onto the stale c240ebbd project), do NOT reuse any existing tab, and
	//    do NOT touch the stored project URL. New tab only.
	let rootTab;
	try {
		rootTab = await openTabInNormalWindow(GFV2_FLOW_ROOT_URL);
	} catch (err) {
		emit("GFV2_ENSURE_SURFACE_FAILED", "FAIL", `open_error=${String(err?.message || err)}`);
		return { ok: false, error: "GFV2_ROOT_LOAD_TIMEOUT", detail: { open_error: String(err?.message || err) } };
	}
	try {
		rootTab = await waitForTabComplete(rootTab.id, 30000);
	} catch (_) {
		try {
			rootTab = await chrome.tabs.get(rootTab.id);
		} catch (_) {}
	}
	if (!rootTab?.id) {
		emit("GFV2_ENSURE_SURFACE_FAILED", "FAIL", "root_tab_load_timeout");
		return { ok: false, error: "GFV2_ROOT_LOAD_TIMEOUT", detail: { reason: "no_root_tab" } };
	}
	emit("GFV2_FLOW_ROOT_OPENED", "WAITING_FLOW", `tab=${rootTab.id} url=${String(rootTab.url || "").slice(0, 80)} strategy=new_root_tab`);

	// 3. Classify the fresh root tab.
	await ensureFlowDomScript(rootTab.id);
	let cap = await captureGoogleFlowV2Readiness(rootTab);
	let cls = gfv2ClassifySurface(rootTab, cap);
	if (cap?.diagnostic?.login_or_access_blocker) {
		emit("GFV2_ENSURE_SURFACE_FAILED", "FAIL", "login_or_access_blocker");
		return { ok: false, error: "GFV2_LOGIN_REQUIRED", detail: { url: rootTab.url || null } };
	}
	if (cls.healthy) {
		emit("GFV2_SURFACE_READY", "PASS", `tab=${rootTab.id} strategy=root_composer`);
		return { ok: true, tab: rootTab };
	}

	// 4. Root/dashboard shows no composer — automate the New/Create action to reach
	//    a session. Reuses the proven OPEN_FLOW_NEW_PROJECT content-script click.
	let createResult = await sendTabMessageSafe(
		rootTab.id,
		{ type: "OPEN_FLOW_NEW_PROJECT", mode },
		70000,
	);
	if (
		[
			"ERR_MESSAGE_RESPONSE_TIMEOUT",
			"ERR_NO_RECEIVER",
			"ERR_CONTENT_SCRIPT_STALE",
			"ERR_TAB_RELOADED",
		].includes(createResult?.error)
	) {
		await ensureFlowDomScript(rootTab.id);
		createResult = await sendTabMessageSafe(
			rootTab.id,
			{ type: "OPEN_FLOW_NEW_PROJECT", mode },
			70000,
		);
	}
	const createDidAct = Boolean(
		createResult &&
			(createResult.ok ||
				createResult.new_project_clicked ||
				createResult.editor_ready),
	);
	if (!createDidAct) {
		emit("GFV2_ENSURE_SURFACE_FAILED", "FAIL", `create_error=${createResult?.error || "no_create_action"}`);
		return {
			ok: false,
			error: "GFV2_EDITOR_ENTRY_FAILED",
			detail: {
				create_error: createResult?.error || "no_create_action",
				create_result: createResult || null,
				url: rootTab?.url || null,
			},
		};
	}

	// 5. Wait for the editor to settle on the SAME tab, then re-classify.
	try {
		rootTab = await waitForTabComplete(rootTab.id, 20000);
	} catch (_) {
		try {
			rootTab = await chrome.tabs.get(rootTab.id);
		} catch (_) {}
	}
	await ensureFlowDomScript(rootTab.id);
	cap = await captureGoogleFlowV2Readiness(rootTab);
	cls = gfv2ClassifySurface(rootTab, cap);
	if (cls.healthy) {
		emit("GFV2_SURFACE_READY", "PASS", `tab=${rootTab.id} strategy=created_session`);
		return { ok: true, tab: rootTab };
	}
	emit("GFV2_ENSURE_SURFACE_FAILED", "FAIL", `reason=${cls.reason} url=${rootTab?.url || "?"}`);
	return {
		ok: false,
		error:
			cls.reason === "landing_nav_only"
				? "GFV2_EDITOR_NOT_READY_LANDING_NAV_ONLY"
				: "GFV2_EDITOR_ENTRY_FAILED",
		detail: {
			reason: cls.reason,
			url: rootTab?.url || null,
			create_result: createResult || null,
		},
	};
}

async function gfv2VerifyRuntimeBuildAlignment(flowTab, runnerApi) {
	const capture = await captureGoogleFlowV2Readiness(flowTab);
	const decision = gfv2DecideBuildProof({
		background_build_id: BUILD_ID,
		runner_build_id: runnerApi?.F2V_FLOW_QUEUE_RUNNER_BUILD_ID,
		page_diagnostic: capture?.ok ? capture.diagnostic : null,
	});
	return {
		...decision,
		capture_error: capture?.ok ? null : capture?.error || "GFV2_OBSERVE_FAILED",
		capture_detail: capture?.ok ? null : capture?.detail || null,
	};
}

async function handleGfv2Job(job) {
	const requestId = job?.request_id || null;
	const postSubmitDownload = isGfv2PostSubmitDownload(job);
	const emit = (stage, status, message, buildProof = null) => {
		if (!requestId) return;
		const buildFields = buildProof
			? {
					content_build_id: buildProof.content_build_id || undefined,
					runtime_ready: Boolean(buildProof.runtime_ready),
					build_match: buildProof.build_match === true,
					fail_code:
						String(status).toUpperCase() === "FAIL"
							? buildProof.error || null
							: null,
				}
			: {};
		postStageTelemetry(
			{
				request_id: requestId,
				stage,
				status,
				message,
				source: "extension",
				...buildFields,
			},
			null,
		);
	};
	emit("GFV2_LANE_ACCEPTED", "WAITING_FLOW", `request_id=${requestId}`);

	// Asset source MUST be the same system-controlled source the CDP upload lane will
	// actually resolve and feed. Fail closed if the classifier or the resolver disagree.
	const f2vUploadAssetSource = resolveF2VUploadAssetSource(job);
	const assetSrc = gfv2ClassifyAssetSource(job);
	const f2vWantsCdpUpload = shouldUseF2VCdpUpload(job, f2vUploadAssetSource);
	if (!assetSrc.ok || !f2vUploadAssetSource || !f2vWantsCdpUpload) {
		const sourceError =
			assetSrc.error ||
			(!f2vUploadAssetSource
				? "GFV2_ASSET_SOURCE_NOT_FOUND"
				: "GFV2_ASSET_SOURCE_UNWIRED");
		emit(sourceError, "FAIL", `reason=${assetSrc.reason || "resolver_disagreed"}`);
		emit("FAILED", "FAIL", sourceError);
		return {
			ok: false,
			error: sourceError,
			detail: {
				reason:
					assetSrc.reason ||
					(!f2vUploadAssetSource
						? "resolver_disagreed"
						: "cdp_upload_disabled"),
			},
		};
	}
	emit("GFV2_ASSET_SOURCE_RESOLVED", "PASS", `source_type=${assetSrc.source_type} name=${assetSrc.safe_name || "?"}`);

	const surface = await gfv2EnsureSurface(job?.mode || "F2V", emit);
	if (!surface.ok) {
		emit("FAILED", "FAIL", surface.error);
		return { ok: false, error: surface.error, detail: surface.detail || null };
	}
	const flowTab = surface.tab;
	emit("GFV2_EDITOR_READY", "PASS", `tab=${flowTab.id} url=${String(flowTab.url || "").slice(0, 80)}`);

	const runnerApi =
		typeof self !== "undefined" ? self.__BOSMAX_F2V_FLOW_QUEUE_RUNNER__ : null;
	if (!runnerApi || typeof runnerApi.executeF2VVisibleSopRunner !== "function") {
		emit("FAILED", "FAIL", "GFV2_RUNNER_NOT_LOADED");
		return { ok: false, error: "GFV2_RUNNER_NOT_LOADED" };
	}

	const buildProof = await gfv2VerifyRuntimeBuildAlignment(flowTab, runnerApi);
	const buildProofMessage = [
		`background=${buildProof.background_build_id || "unavailable"}`,
		`runner=${buildProof.runner_build_id || "unavailable"}`,
		`content=${buildProof.content_build_id || "unavailable"}`,
		`build_match=${buildProof.build_match ? 1 : 0}`,
	].join(" ");
	if (!buildProof.proceed) {
		emit(buildProof.error, "FAIL", buildProofMessage, buildProof);
		emit("FAILED", "FAIL", buildProof.error, buildProof);
		return {
			ok: false,
			error: buildProof.error,
			detail: buildProof.detail,
		};
	}
	emit(
		"GFV2_BUILD_ALIGNMENT_VERIFIED",
		"PASS",
		buildProofMessage,
		buildProof,
	);

	const gfv2Emit = (payload) => {
		// Emit the runner's native stage AND the mapped GFV2 contract stage.
		postStageTelemetry(
			{
				request_id: requestId,
				stage: payload.stage,
				status: payload.status,
				message: payload.message,
				source: "extension",
				selector_used: payload.selector_used || null,
				evidence_pointer: payload.evidence_pointer || null,
			},
			getKnownContentScriptHealth(flowTab.id),
		);
		const mapped = GFV2_STAGE_MAP[payload.stage];
		if (mapped && String(payload.status).toUpperCase() === "PASS") {
			emit(mapped, "PASS", payload.message);
		}
	};

	const deps = {
		scripting: runnerApi.createChromeScriptingAdapter(chrome),
		downloads:
			typeof runnerApi.createChromeDownloadsAdapter === "function" &&
			chrome?.downloads
				? runnerApi.createChromeDownloadsAdapter(chrome)
				: null,
		// Surface is already acquired — do not open/recover anything inside the runner.
		newProjectFn: async () => ({
			ok: true,
			flow_tab_id: flowTab.id,
			flow_url: flowTab.url,
			open_strategy: "gfv2_surface_acquired",
		}),
		telemetry: gfv2Emit,
	};

	const cdpOpt = f2vWantsCdpUpload
		? {
				cdpFileChooserUpload: (req) =>
					cdpFileChooserUploadForJob(flowTab.id, {
						...req,
						assetSource: f2vUploadAssetSource || req?.assetSource,
						sourceType: assetSrc.source_type,
					}),
				// NB: the DOM upload fallback (FLOWKIT_SIMULATE_FILE_UPLOAD) is NOT wired
				// here on purpose — it is unimplemented in the content script and a
				// content script cannot set <input type=file>.files (browser security).
				// The robust recovery for the V2 widget is a CDP direct
				// input[type=file] + DOM.setFileInputFiles path (see cdpFileChooserUploadForJob).
			}
		: {};

	let runnerResult;
	try {
		runnerResult = await runnerApi.executeF2VVisibleSopRunner(deps, flowTab.id, job, {
			settleMs: 300,
			uploadWaitMs: 10000,
			skipUpload: false,
			skipGenerate: true, // GFV2 UAT stops BEFORE Generate.
			// NB: gfv2ForceDomSettings / gfv2SkipModeSteps are deliberately NOT passed.
			// The legacy DOM settings path is incompatible with the V2 surface (it
			// clicks non-existent Video/Frames mode options and cannot open the V2
			// settings panel — ERR_F2V_OPTION_VIDEO_NOT_FOUND / no_settings_launcher).
			// Until a V2 settings read/interaction layer exists, the lane keeps the
			// authority shortcut and emits the granular proof it CAN observe.
			// NB: settings are NOT verified pre-upload. Live discovery proved the V2
			// generation settings (tune panel: 9:16/1x/model) only render in the composer
			// AFTER media is added — matching the original V2 SOP
			// (Upload -> Add to Prompt -> Settings). Settings proof runs post-upload below.
			// GFV2 upload-menu contract telemetry: launcher click is NOT a file chooser;
			// the in-menu "Upload media"/"Upload from computer" item is clicked first.
			gfv2Stage: (stage, status, message) => emit(stage, status, message),
			cdpCoordinateClick: async (params) =>
				await cdpClickCoordinate(params.tabId, params.x, params.y),
			...cdpOpt,
		});
	} catch (err) {
		emit("FAILED", "FAIL", "GFV2_RUNNER_THREW");
		return { ok: false, error: "GFV2_RUNNER_THREW", detail: String(err?.message || err) };
	}

	if (!runnerResult?.ok) {
		const code = runnerResult?.error || "GFV2_RUNNER_FAILED";
		emit("FAILED", "FAIL", code);
		return { ok: false, error: code, detail: runnerResult || null };
	}

	// Runner completed upload + add-to-prompt + prompt with skipGenerate.
	emit("GFV2_ASSET_UPLOADED_OR_SELECTED", "PASS", `via=${runnerResult?.stage_results?.upload_proof?.via || "cdp_file_chooser"} source=system_job_asset`);
	emit("GFV2_ASSET_BOUND_TO_PROMPT", "PASS", `media_attached=${Boolean(runnerResult?.stage_results?.media_attached)}`);

	// GRANULAR SETTINGS PROOF (post-upload, V2 SOP order). Opens the tune-settings
	// panel, confirms/selects 9:16 + 1x, classifies the model (Veo / hidden-soft-pass
	// / visible-wrong hard-fail), verifies persistence. Real live gate before STOP.
	const settings = await gfv2DriveSettingsVerify(flowTab, emit, {
		requireSaveTransition: postSubmitDownload,
		expectedPrompt: job?.prompt,
	});
	if (!settings.proceed) {
		emit("FAILED", "FAIL", settings.error || "GFV2_SETTINGS_NOT_VERIFIED");
		return { ok: false, error: settings.error || "GFV2_SETTINGS_NOT_VERIFIED", detail: settings.detail || null };
	}

	emit("GFV2_PROMPT_ACCEPTED", "PASS", `prompt_inserted=${Boolean(runnerResult?.stage_results?.prompt_inserted)}`);
	if (postSubmitDownload) {
		if (typeof runnerApi.executeGfv2PostSubmitDownloadContinuation !== "function") {
			emit("FAILED", "FAIL", "GFV2_POST_SUBMIT_CONTINUATION_NOT_LOADED");
			return { ok: false, error: "GFV2_POST_SUBMIT_CONTINUATION_NOT_LOADED" };
		}
		const continuation = await runnerApi.executeGfv2PostSubmitDownloadContinuation(
			deps,
			flowTab.id,
			job,
			{
				settleMs: 300,
				promptProof: runnerResult?.stage_results?.prompt_proof || null,
				flowUrl: flowTab.url || null,
				surfaceIdentity: `flow_tab:${flowTab.id}`,
				settingsState: "closed_verified",
				settingsComposerIdentity:
					settings?.applied?.composer_identity_after_save || null,
			},
		);
		if (!continuation?.ok) {
			const code = continuation?.error || "GFV2_POST_SUBMIT_CONTINUATION_FAILED";
			emit("FAILED", "FAIL", code);
			return { ok: false, error: code, detail: continuation || null };
		}
		return {
			ok: true,
			gfv2_post_submit_download: true,
			flow_tab_id: flowTab.id,
			runner: runnerResult,
			continuation,
		};
	}
	emit("GFV2_GENERATE_ENABLED", "PASS", "verified_enabled_not_clicked");
	emit("GFV2_STOP_BEFORE_GENERATE", "PASS", "gfv2_ready_stopped_before_generate");
	return {
		ok: true,
		gfv2_stopped_before_generate: true,
		flow_tab_id: flowTab.id,
		runner: runnerResult,
	};
}

async function handleExecuteFlowJob(job) {
	// Google Flow V2 lane — surface acquisition + upload/settings/prompt, stop before generate.
	if (isGfv2Lane(job)) {
		return await handleGfv2Job(job);
	}
	// Strict package-upload-only lane bypasses target recovery / project open.
	if (isF2VPackageUploadOnly(job)) {
		return await handleF2VPackageUploadOnlyJob(job);
	}
	const targetResolution = await resolveFlowExecutionTarget(job);
	if (!targetResolution.ok) {
		// Post FAILED stage so the backend telemetry status exits WAITING_FLOW.
		// Without this the dashboard poll loop never terminates.
		const requestId = job?.request_id;
		if (requestId) {
			postStageTelemetry({
				request_id: requestId,
				stage: "FAILED",
				status: "FAIL",
				message: targetResolution.error || "FLOW_EXECUTION_TARGET_FAILED",
				source: "extension",
			}, null);
		}
		return {
			ok: false,
			error: targetResolution.error,
			detail: targetResolution.detail || null,
			candidate_tabs: targetResolution.candidate_tabs || [],
		};
	}
	const flowTab = targetResolution.targetTab;

	if (job && job.mode === "F2V") {
		const runnerApi =
			typeof self !== "undefined"
				? self.__BOSMAX_F2V_FLOW_QUEUE_RUNNER__
				: null;
		if (runnerApi) {
			console.log(
				"[FlowAgent] Routing F2V job directly to f2v-flow-queue-runner",
			);
			const deps = {
				scripting: runnerApi.createChromeScriptingAdapter(chrome),
				newProjectFn: async (tabId, runnerJob) => {
					const currentTab = await getTabSafe(tabId);
					if (currentTab?.id && isProjectEditorUrl(currentTab.url)) {
						const existingAuthority =
							await resolveExistingProjectEditorAuthority(
							currentTab,
							runnerJob?.mode || job?.mode,
						);
						if (existingAuthority.ok) {
							return {
								ok: true,
								flow_tab_id: currentTab.id,
								flow_url: currentTab.url,
								open_strategy: "already_on_editor_authority",
								target_probe:
									existingAuthority.page_diagnostic ||
									existingAuthority.diagnostic ||
									null,
							};
						}
					}

					const preferredUrl = await getStoredFlowProjectUrl();
					const openFlowResult = await openPreferredFlowProjectOrNewProject(
						runnerJob?.mode || job?.mode,
						preferredUrl,
					);
					const settledTab = await settleFlowProjectAfterOpen(openFlowResult);
					const settledProbe =
						settledTab?.id && isProjectEditorUrl(settledTab?.url)
							? await probeFlowEditorCandidate(
									settledTab,
									runnerJob?.mode || job?.mode,
								)
							: null;
					return {
						...openFlowResult,
						ok: Boolean(openFlowResult?.ok && settledProbe?.ok),
						error:
							openFlowResult?.ok && !settledProbe?.ok
								? settledProbe?.error || "FLOW_PROJECT_EDITOR_NOT_READY"
								: openFlowResult?.error || null,
						flow_tab_id: settledTab?.id ?? openFlowResult?.flow_tab_id ?? null,
						flow_url: settledTab?.url || openFlowResult?.flow_url || null,
						target_probe: settledProbe?.readiness || null,
					};
				},
				telemetry: (payload) => {
					const contentHealth = getKnownContentScriptHealth(flowTab.id);
					postStageTelemetry(
						{
							request_id: job.request_id || `flow_${Date.now()}`,
							stage: payload.stage,
							status: payload.status,
							message: payload.message,
							source: "extension",
						},
						contentHealth,
					);
				},
			};
			try {
				// F2V Frames jobs require a Start-frame media upload. The DOM upload
				// branch cannot deliver a local file (no in-DOM upload control), so any
				// F2V job carrying a resolvable upload asset takes the CDP file-chooser
				// path BY DEFAULT. Explicit opt-out: use_cdp_upload:false or skipUpload:true.
				// (Previously CDP was opt-in via use_cdp_upload:true, which operator/
				// workspace jobs never set — leaving Frames jobs on the empty DOM path and
				// failing at F2V_SOP_UPLOAD_WAIT_DONE / ERR_F2V_ADD_TO_PROMPT_NOT_FOUND.)
				const f2vUploadAssetSource = resolveF2VUploadAssetSource(job);
				const f2vDomFallbackAssetSource = resolveF2VDomFallbackAssetSource(job);
				const f2vWantsCdpUpload = shouldUseF2VCdpUpload(
					job,
					f2vUploadAssetSource,
				);
				const f2vCdpUploadOpt = f2vWantsCdpUpload
					? {
							cdpFileChooserUpload: (req) =>
								cdpFileChooserUploadForJob(flowTab.id, {
									...req,
									// Authoritative selected-media reference resolved from the
									// real job shape; overrides the runner's raw object guess.
									assetSource: f2vUploadAssetSource || req?.assetSource,
								}),
							domUploadFallback:
								f2vDomFallbackAssetSource != null
									? (req) =>
											domFileUploadFallbackForJob(flowTab.id, {
												...req,
												assetSource:
													f2vDomFallbackAssetSource || req?.assetSource,
											})
									: null,
						}
					: {};
				console.log(
					"[FlowAgent] F2V upload lane:",
					`cdp=${f2vWantsCdpUpload}`,
					`assetSource=${
						typeof f2vUploadAssetSource === "string"
							? f2vUploadAssetSource.slice(0, 80)
							: f2vUploadAssetSource
					}`,
				);
				const runnerResult = await runnerApi.executeF2VVisibleSopRunner(
					deps,
					flowTab.id,
					job,
					{
						settleMs: 300,
						uploadWaitMs: 10000,
						skipUpload: job?.skipUpload === true,
						skipGenerate: job?.skipGenerate === true,
						cdpCoordinateClick: async (params) => {
							console.log(
								"[FlowAgent] Performing CDP coordinate click:",
								params,
							);
							return await cdpClickCoordinate(params.tabId, params.x, params.y);
						},
						...f2vCdpUploadOpt,
					},
				);
				return runnerResult;
			} catch (err) {
				return {
					ok: false,
					error: "ERR_F2V_SOP_RUNNER_THREW",
					detail: String(err?.message || err || ""),
				};
			}
		} else {
			console.warn(
				"[FlowAgent] F2V runner not loaded, falling back to content-flow-dom",
			);
		}
	}

	await ensureFlowDomScript(flowTab.id);

	const initialHealth = await pingFlowDomScript(flowTab);
	if (initialHealth?.raw_error) {
		console.warn(
			"[FlowAgent] Flow DOM ping failed before execute, retrying injection:",
			initialHealth.raw_error,
		);
		await ensureFlowDomScript(flowTab.id);
	}

	let result = await sendTabMessageSafe(flowTab.id, {
		type: "EXECUTE_FLOW_JOB",
		job,
	});

	if (
		[
			"ERR_MESSAGE_RESPONSE_TIMEOUT",
			"ERR_NO_RECEIVER",
			"ERR_CONTENT_SCRIPT_STALE",
			"ERR_TAB_RELOADED",
		].includes(result?.error)
	) {
		console.warn(
			"[FlowAgent] EXECUTE_FLOW_JOB bridge failed, reinjecting and retrying once:",
			result.error,
		);
		await ensureFlowDomScript(flowTab.id);
		result = await sendTabMessageSafe(flowTab.id, {
			type: "EXECUTE_FLOW_JOB",
			job,
		});
	}

	return result;
}

async function handleConfigureF2VSettings(job, tabId) {
	const activeTabId = tabId || (await getFlowTab())?.id;
	if (!activeTabId) {
		return {
			ok: false,
			error: "ERR_NO_FLOW_TAB",
			detail: "No active Google Flow tab was targeted.",
		};
	}
	const runnerApi =
		typeof self !== "undefined" ? self.__BOSMAX_F2V_FLOW_QUEUE_RUNNER__ : null;
	if (!runnerApi) {
		return {
			ok: false,
			error: "ERR_F2V_RUNNER_NOT_LOADED",
			detail: "Runner API not loaded in background.",
		};
	}
	console.log(
		"[FlowAgent] Background delegated settings configuration triggered for tab:",
		activeTabId,
	);
	const deps = {
		scripting: runnerApi.createChromeScriptingAdapter(chrome),
		newProjectFn: async (tabId, runnerJob) => {
			const currentTab = await getTabSafe(tabId);
			if (currentTab?.id && isProjectEditorUrl(currentTab.url)) {
				const existingAuthority = await resolveExistingProjectEditorAuthority(
					currentTab,
					runnerJob?.mode || job?.mode,
				);
				if (existingAuthority.ok) {
					return {
						ok: true,
						flow_tab_id: currentTab.id,
						flow_url: currentTab.url,
						open_strategy: "already_on_editor_authority",
						target_probe:
							existingAuthority.page_diagnostic ||
							existingAuthority.diagnostic ||
							null,
					};
				}
			}

			const preferredUrl = await getStoredFlowProjectUrl();
			const openFlowResult = await openPreferredFlowProjectOrNewProject(
				runnerJob?.mode || job?.mode,
				preferredUrl,
			);
			const settledTab = await settleFlowProjectAfterOpen(openFlowResult);
			const settledProbe =
				settledTab?.id && isProjectEditorUrl(settledTab?.url)
					? await probeFlowEditorCandidate(settledTab, runnerJob?.mode || job?.mode)
					: null;
			return {
				...openFlowResult,
				ok: Boolean(openFlowResult?.ok && settledProbe?.ok),
				error:
					openFlowResult?.ok && !settledProbe?.ok
						? settledProbe?.error || "FLOW_PROJECT_EDITOR_NOT_READY"
						: openFlowResult?.error || null,
				flow_tab_id: settledTab?.id ?? openFlowResult?.flow_tab_id ?? null,
				flow_url: settledTab?.url || openFlowResult?.flow_url || null,
				target_probe: settledProbe?.readiness || null,
			};
		},
		telemetry: (payload) => {
			const contentHealth = getKnownContentScriptHealth(activeTabId);
			postStageTelemetry(
				{
					request_id: job?.request_id || `flow_${Date.now()}`,
					stage: payload.stage,
					status: payload.status,
					message: payload.message,
					source: "extension",
				},
				contentHealth,
			);
		},
	};
	try {
		const runnerResult = await runnerApi.executeF2VVisibleSopRunner(
			deps,
			activeTabId,
			job,
			{
				settleMs: 300,
				skipUpload: true,
				skipGenerate: true,
				cdpCoordinateClick: async (params) => {
					console.log("[FlowAgent] Performing CDP coordinate click:", params);
					return await cdpClickCoordinate(params.tabId, params.x, params.y);
				},
			},
		);
		return runnerResult;
	} catch (err) {
		return {
			ok: false,
			error: "ERR_F2V_SOP_RUNNER_THREW",
			detail: String(err?.message || err || ""),
		};
	}
}

async function handleDebugFlowDomExecution(mode, job) {
	const flowTab = await getFlowTab();
	if (!flowTab) return { ok: false, error: "ERR_NO_FLOW_TAB" };
	await ensureFlowDomScript(flowTab.id);
	// Increase timeout for debug/full execution
	return await sendTabMessageSafe(
		flowTab.id,
		{
			type: "DEBUG_FLOW_DOM_EXECUTION",
			params: { mode, job },
		},
		60000,
	);
}

async function handleCheckFlowComposerReady(mode, options = {}) {
	const preferredUrl = await getStoredFlowProjectUrl();
	const normalizedPreferredUrl = String(preferredUrl || "").trim();
	const allowProjectOpenRecovery = options?.allowProjectOpenRecovery === true;
	const allowFreshProjectRecovery = options?.allowFreshProjectRecovery === true;
	let flowTab = await getFlowTab();
	let openFlowResult = null;
	if (
		allowProjectOpenRecovery &&
		flowTab &&
		isRootFlowUrl(flowTab.url) &&
		!isProjectEditorUrl(flowTab.url)
	) {
		openFlowResult = await openPreferredFlowProjectOrNewProject(
			mode,
			preferredUrl,
		);
		flowTab = await settleFlowProjectAfterOpen(openFlowResult);
	}
	let base = buildFlowReadinessBase(flowTab);
	if (!flowTab) {
		return finalizeFlowReadiness({
			...base,
			error: "ERR_NO_FLOW_TAB",
			raw_error: "ERR_NO_FLOW_TAB",
			detail: "No Google Flow tab matched the editor URL patterns.",
		});
	}

	await ensureFlowDomScript(flowTab.id);

	let diagnostic = await pingFlowDomScript(flowTab);
	if (diagnostic.raw_error) {
		return finalizeFlowReadiness({
			...base,
			...diagnostic,
			error: diagnostic.raw_error,
			open_flow_result: summarizeOpenFlowResult(openFlowResult),
		});
	}

	let response = await sendTabMessageSafe(flowTab.id, {
		type: "CHECK_FLOW_COMPOSER_READY",
		mode,
	});
	const activeTabUrl = String(flowTab?.url || "").trim();
	const shouldRetryFreshProject =
		Boolean(normalizedPreferredUrl) &&
		activeTabUrl === normalizedPreferredUrl &&
		isProjectEditorUrl(activeTabUrl) &&
		(!response?.ok || response?.error);
	if (shouldRetryFreshProject && allowFreshProjectRecovery) {
		openFlowResult = await handleOpenFlowNewProject(mode);
		flowTab = await settleFlowProjectAfterOpen(openFlowResult);
		base = buildFlowReadinessBase(flowTab);
		if (!flowTab) {
			return finalizeFlowReadiness({
				...base,
				error: "ERR_NO_FLOW_TAB",
				raw_error: "ERR_NO_FLOW_TAB",
				detail: "Fresh project fallback did not produce a usable Flow tab.",
				open_flow_result: summarizeOpenFlowResult(openFlowResult),
			});
		}
		await ensureFlowDomScript(flowTab.id);
		diagnostic = await pingFlowDomScript(flowTab);
		if (diagnostic.raw_error) {
			return finalizeFlowReadiness({
				...base,
				...diagnostic,
				error: diagnostic.raw_error,
				open_flow_result: summarizeOpenFlowResult(openFlowResult),
			});
		}
		response = await sendTabMessageSafe(flowTab.id, {
			type: "CHECK_FLOW_COMPOSER_READY",
			mode,
		});
	}
	if (response?.error && isRecoverableComposerRouteError(response.error)) {
		const pageDiagnosticResponse = await sendTabMessageSafe(
			flowTab.id,
			{
				type: "FLOW_PAGE_STATE_DIAGNOSTIC",
				mode,
			},
			12000,
		);
		if (canUsePageDiagnosticForComposerReadiness(pageDiagnosticResponse)) {
			return finalizeFlowReadiness({
				...base,
				...diagnostic,
				...buildComposerReadinessFromPageDiagnostic(pageDiagnosticResponse),
				open_flow_result: summarizeOpenFlowResult(openFlowResult),
				flow_url: pageDiagnosticResponse?.flow_url || flowTab.url,
			});
		}
	}
	if (response?.error === "ERR_MESSAGE_RESPONSE_TIMEOUT") {
		return finalizeFlowReadiness({
			...base,
			...diagnostic,
			error: "ERR_MESSAGE_RESPONSE_TIMEOUT",
			raw_error: "ERR_MESSAGE_RESPONSE_TIMEOUT",
			detail: "Timed out waiting for content script readiness response.",
			open_flow_result: summarizeOpenFlowResult(openFlowResult),
		});
	}
	if (response?.error) {
		return finalizeFlowReadiness({
			...base,
			...diagnostic,
			error: response.error,
			raw_error: response.error,
			detail: response.error,
			open_flow_result: summarizeOpenFlowResult(openFlowResult),
		});
	}
	if (!response?.ok && !response?.error) {
		return finalizeFlowReadiness({
			...base,
			...diagnostic,
			error: "ABORT_FLOW_COMPOSER_NOT_READY",
			raw_error: "ERR_EMPTY_COMPOSER_RESPONSE",
			open_flow_result: summarizeOpenFlowResult(openFlowResult),
		});
	}
	return finalizeFlowReadiness({
		...base,
		...diagnostic,
		...response,
		open_flow_result: summarizeOpenFlowResult(openFlowResult),
		flow_url: response?.flow_url || flowTab.url,
	});
}

async function handleFlowPageStateDiagnostic(mode, options = {}) {
	const preferredUrl = await getStoredFlowProjectUrl();
	const normalizedPreferredUrl = String(preferredUrl || "").trim();
	const allowProjectOpenRecovery = options?.allowProjectOpenRecovery === true;
	const allowFreshProjectRecovery = options?.allowFreshProjectRecovery === true;
	let flowTab = await getFlowTab();
	let openFlowResult = null;
	if (
		allowProjectOpenRecovery &&
		flowTab &&
		isRootFlowUrl(flowTab.url) &&
		!isProjectEditorUrl(flowTab.url)
	) {
		openFlowResult = await openPreferredFlowProjectOrNewProject(
			mode,
			preferredUrl,
		);
		flowTab = await settleFlowProjectAfterOpen(openFlowResult);
	}
	let base = buildFlowReadinessBase(flowTab);
	if (!flowTab) {
		return {
			...base,
			error: "ERR_NO_FLOW_TAB",
			raw_error: "ERR_NO_FLOW_TAB",
			detail: "No Google Flow tab matched the editor URL patterns.",
			location_href: null,
			document_title: null,
			document_ready_state: null,
			body_text_first_2000_chars: "",
			visible_login_markers: [],
			visible_loading_markers: [],
			visible_error_markers: [],
			visible_project_editor_markers: [],
			visible_composer_placeholder_markers: [],
			button_texts: [],
			textarea_placeholders: [],
			input_placeholders: [],
			contenteditable_texts: [],
			aria_labels: [],
			open_flow_result: summarizeOpenFlowResult(openFlowResult),
		};
	}

	await ensureFlowDomScript(flowTab.id);

	let diagnostic = await pingFlowDomScript(flowTab);
	if (diagnostic.raw_error) {
		return {
			...base,
			...diagnostic,
			error: diagnostic.raw_error,
			detail: diagnostic.raw_error,
			location_href: flowTab.url,
			document_title: null,
			document_ready_state: null,
			body_text_first_2000_chars: "",
			visible_login_markers: [],
			visible_loading_markers: [],
			visible_error_markers: [],
			visible_project_editor_markers: [],
			visible_composer_placeholder_markers: [],
			button_texts: [],
			textarea_placeholders: [],
			input_placeholders: [],
			contenteditable_texts: [],
			aria_labels: [],
			open_flow_result: summarizeOpenFlowResult(openFlowResult),
		};
	}

	let response = await sendTabMessageSafe(flowTab.id, {
		type: "FLOW_PAGE_STATE_DIAGNOSTIC",
		mode,
	});
	const activeTabUrl = String(flowTab?.url || "").trim();
	const shouldRetryFreshProject =
		Boolean(normalizedPreferredUrl) &&
		activeTabUrl === normalizedPreferredUrl &&
		isProjectEditorUrl(activeTabUrl) &&
		Array.isArray(response?.visible_error_markers) &&
		response.visible_error_markers.length > 0;
	if (shouldRetryFreshProject && allowFreshProjectRecovery) {
		openFlowResult = await handleOpenFlowNewProject(mode);
		flowTab = await settleFlowProjectAfterOpen(openFlowResult);
		base = buildFlowReadinessBase(flowTab);
		if (!flowTab) {
			return {
				...base,
				error: "ERR_NO_FLOW_TAB",
				raw_error: "ERR_NO_FLOW_TAB",
				detail: "Fresh project fallback did not produce a usable Flow tab.",
				location_href: null,
				document_title: null,
				document_ready_state: null,
				body_text_first_2000_chars: "",
				visible_login_markers: [],
				visible_loading_markers: [],
				visible_error_markers: [],
				visible_project_editor_markers: [],
				visible_composer_placeholder_markers: [],
				button_texts: [],
				textarea_placeholders: [],
				input_placeholders: [],
				contenteditable_texts: [],
				aria_labels: [],
				open_flow_result: summarizeOpenFlowResult(openFlowResult),
			};
		}
		await ensureFlowDomScript(flowTab.id);
		diagnostic = await pingFlowDomScript(flowTab);
		if (diagnostic.raw_error) {
			return {
				...base,
				...diagnostic,
				error: diagnostic.raw_error,
				detail: diagnostic.raw_error,
				location_href: flowTab.url,
				document_title: null,
				document_ready_state: null,
				body_text_first_2000_chars: "",
				visible_login_markers: [],
				visible_loading_markers: [],
				visible_error_markers: [],
				visible_project_editor_markers: [],
				visible_composer_placeholder_markers: [],
				button_texts: [],
				textarea_placeholders: [],
				input_placeholders: [],
				contenteditable_texts: [],
				aria_labels: [],
				open_flow_result: summarizeOpenFlowResult(openFlowResult),
			};
		}
		response = await sendTabMessageSafe(flowTab.id, {
			type: "FLOW_PAGE_STATE_DIAGNOSTIC",
			mode,
		});
	}

	if (response?.error) {
		return {
			...base,
			...diagnostic,
			error: response.error,
			raw_error: response.error,
			detail: response.error,
			location_href: flowTab.url,
			document_title: null,
			document_ready_state: null,
			body_text_first_2000_chars: "",
			visible_login_markers: [],
			visible_loading_markers: [],
			visible_error_markers: [],
			visible_project_editor_markers: [],
			visible_composer_placeholder_markers: [],
			button_texts: [],
			textarea_placeholders: [],
			input_placeholders: [],
			contenteditable_texts: [],
			aria_labels: [],
			open_flow_result: summarizeOpenFlowResult(openFlowResult),
		};
	}

	const finalResult = {
		...base,
		...diagnostic,
		...response,
		open_flow_result: summarizeOpenFlowResult(openFlowResult),
		flow_url: response?.flow_url || flowTab.url,
	};
	const finalFlowUrl = String(finalResult.flow_url || "").trim();
	const openedViaRecovery = Boolean(
		finalResult?.open_flow_result?.ok &&
			(finalResult?.open_flow_result?.new_project_clicked ||
				finalResult?.open_flow_result?.open_strategy === "new_project" ||
				(normalizedPreferredUrl &&
					finalFlowUrl &&
					finalFlowUrl !== normalizedPreferredUrl)),
	);
	if (finalFlowUrl) {
		const syncResult = await syncStoredFlowProjectUrlToActiveEditor(finalFlowUrl, {
			currentStoredUrl: normalizedPreferredUrl,
			openedViaRecovery,
			allowWhenMissing: true,
		});
		finalResult.stored_flow_project_url =
			syncResult.stored_flow_project_url || normalizedPreferredUrl || null;
	}
	return finalResult;
}

function classifyContentReceiverError(rawError) {
	const message = String(rawError || "").trim();
	if (!message) {
		return null;
	}
	if (
		message.includes("ABORT_FLOW_MODE_MISMATCH") ||
		message.includes("FLOW_MODE_MISMATCH")
	) {
		return null;
	}
	if (
		message === "ERR_NO_RECEIVER" ||
		message === "ERR_CONTENT_SCRIPT_STALE" ||
		message === "ERR_MESSAGE_RESPONSE_TIMEOUT" ||
		message.startsWith("ERR_RUNTIME_LASTERROR")
	) {
		return "ERR_FLOW_CONTENT_RECEIVER_MISSING";
	}
	return message;
}

function isPreselectionEditorReadyDiagnostic(diagnostic) {
	if (!diagnostic || typeof diagnostic !== "object") {
		return false;
	}
	const markers = Array.isArray(diagnostic.visible_project_editor_markers)
		? diagnostic.visible_project_editor_markers.map((value) => String(value))
		: [];
	const modeVisible = String(diagnostic.current_mode_visible || "");
	const showsVideoFrames =
		modeVisible.includes("Video/Frames") ||
		(markers.includes("Video") && markers.includes("Frames"));
	return Boolean(
		diagnostic.runtime_ready &&
			diagnostic.content_script_loaded &&
			diagnostic.content_script_alive &&
			diagnostic.composer_found &&
			diagnostic.composer_editable &&
			diagnostic.generate_button_found &&
			diagnostic.prompt_field_found &&
			showsVideoFrames,
	);
}

// Read-only Google Flow V2 readiness capture. Asks the content script to observe
// the live DOM (GFV2_OBSERVE_STATE — no clicks), then evaluates it through the
// gfv2-readiness proof model. Emits diagnostic-only telemetry/logs. Returns
// { ok, diagnostic, evaluation } or a structured error — never throws.
async function captureGoogleFlowV2Readiness(selectedTab) {
	const gfv2Api =
		typeof self !== "undefined" ? self.__GFV2_READINESS__ : null;
	if (!selectedTab?.id) {
		return { ok: false, error: "GFV2_NO_FLOW_TAB", diagnostic: null, evaluation: null };
	}
	try {
		await ensureFlowDomScript(selectedTab.id);
		const resp = await sendTabMessageSafe(
			selectedTab.id,
			{
				type: "GFV2_OBSERVE_STATE",
				expected_background_build_id: BUILD_ID,
			},
			12000,
		);
		const diagnostic = resp?.diagnostic || null;
		if (!resp?.ok || !diagnostic) {
			return {
				ok: false,
				error: resp?.error || "GFV2_OBSERVE_FAILED",
				detail: resp?.detail || resp?.raw_error || null,
				diagnostic: diagnostic || null,
				evaluation: null,
			};
		}
		console.log("[GFV2] GFV2_DIAGNOSTIC_CAPTURED", {
			contract: diagnostic.google_flow_ui_contract,
			tab: selectedTab.id,
		});
		let evaluation = null;
		if (gfv2Api && typeof gfv2Api.evaluateGoogleFlowV2Readiness === "function") {
			evaluation = gfv2Api.evaluateGoogleFlowV2Readiness(diagnostic);
			console.log("[GFV2] GFV2_READINESS_EVALUATED", {
				ready: evaluation.ready,
				primary_blocker: evaluation.primary_blocker,
				upload: evaluation.proofs?.upload?.ok,
				settings: evaluation.proofs?.settings?.ok,
				prompt: evaluation.proofs?.prompt?.ok,
				generate: evaluation.proofs?.generate?.ok,
			});
		}
		return { ok: true, diagnostic, evaluation };
	} catch (err) {
		return {
			ok: false,
			error: "GFV2_CAPTURE_THREW",
			detail: String(err?.message || err),
			diagnostic: null,
			evaluation: null,
		};
	}
}

async function handleRuntimeSelfTest(mode = "F2V", attemptOpenProject = false) {
	let preferredUrl = await getStoredFlowProjectUrl();
	let flowTabs = await getFlowTabs();
	let activeTabPreflight = await buildActiveFlowTabPreflight(mode, {
		preferredUrl,
		tabs: flowTabs,
	});

	// If the editor tab exists but isn't currently active (common post-reload focus mismatch),
	// apply the same focus recovery that job execution uses in resolveFlowExecutionTarget.
	if (activeTabPreflight?.error === "FLOW_ACTIVE_EDITOR_TAB_NOT_FOUND") {
		const strictRecovery = await recoverStrictActiveFlowTabTarget(mode, {
			preferredUrl,
			tabs: flowTabs,
			activeTabPreflight,
			allowBootstrapRecovery: attemptOpenProject === true,
		});
		if (strictRecovery?.activeTabPreflight) {
			activeTabPreflight = strictRecovery.activeTabPreflight;
			if (strictRecovery.ok) {
				flowTabs = await getFlowTabs();
			}
		}
	}

	let selectedTab = activeTabPreflight?.selectedTab || null;
	const adoptedTarget = await adoptSelectedFlowProjectUrlIfNeeded(
		selectedTab,
		flowTabs,
		preferredUrl,
	);
	preferredUrl = adoptedTarget?.preferred_flow_project_url || preferredUrl;
	let openFlowResult = null;

	if (
		attemptOpenProject &&
		selectedTab &&
		isRootFlowUrl(selectedTab.url) &&
		!isProjectEditorUrl(selectedTab.url)
	) {
		openFlowResult = await openPreferredFlowProjectOrNewProject(
			mode,
			preferredUrl,
		);
		const settledTab = await settleFlowProjectAfterOpen(openFlowResult);
		flowTabs = await getFlowTabs();
		activeTabPreflight = await buildActiveFlowTabPreflight(mode, {
			preferredUrl: settledTab?.url || openFlowResult?.flow_url || preferredUrl,
			tabs: settledTab?.url
				? [settledTab, ...flowTabs.filter((tab) => tab.id !== settledTab.id)]
				: flowTabs,
		});
		selectedTab = activeTabPreflight?.selectedTab || null;
		const adoptedSettledTarget = await adoptSelectedFlowProjectUrlIfNeeded(
			selectedTab,
			flowTabs,
			settledTab?.url || openFlowResult?.flow_url || preferredUrl,
		);
		preferredUrl =
			adoptedSettledTarget?.preferred_flow_project_url || preferredUrl;
	}

	const pageDiagnostic = await handleFlowPageStateDiagnostic(mode, {
		allowProjectOpenRecovery: attemptOpenProject === true,
		allowFreshProjectRecovery: attemptOpenProject === true,
	});
	const composerDiagnostic = canUsePageDiagnosticForComposerReadiness(
		pageDiagnostic,
	)
		? buildComposerReadinessFromPageDiagnostic(pageDiagnostic)
		: await handleCheckFlowComposerReady(mode, {
				allowProjectOpenRecovery: attemptOpenProject === true,
				allowFreshProjectRecovery: attemptOpenProject === true,
			});
	const resolvedPreferredUrl = await getStoredFlowProjectUrl();
	const runnerApi =
		typeof self !== "undefined" ? self.__BOSMAX_F2V_FLOW_QUEUE_RUNNER__ : null;
	const runtimeBuildProof = gfv2DecideBuildProof({
		background_build_id: BUILD_ID,
		runner_build_id: runnerApi?.F2V_FLOW_QUEUE_RUNNER_BUILD_ID,
		page_diagnostic: pageDiagnostic,
	});
	const contentBuildId = runtimeBuildProof.content_build_id || null;
	const buildMismatchError = runtimeBuildProof.proceed
		? null
		: runtimeBuildProof.error;
	const pagePreselectionReady =
		isPreselectionEditorReadyDiagnostic(pageDiagnostic);
	const composerModeMismatchNonFatal =
		pagePreselectionReady &&
		String(composerDiagnostic?.error || "").includes(
			"ABORT_FLOW_MODE_MISMATCH",
		);
	const contentReceiverError = classifyContentReceiverError(
		pageDiagnostic?.error ||
			pageDiagnostic?.raw_error ||
			composerDiagnostic?.error ||
			composerDiagnostic?.raw_error,
	);
	const lastError =
		metrics.lastError ||
		buildMismatchError ||
		activeTabPreflight?.error ||
		contentReceiverError ||
		(composerModeMismatchNonFatal
			? null
			: composerDiagnostic?.error ||
				pageDiagnostic?.error ||
				openFlowResult?.error ||
				null);
	const selfTestOk = Boolean(selectedTab) && !lastError;
	const runtimePayload = {
		...buildRuntimeDiagnosticPayload({
			flowUrl:
				pageDiagnostic?.flow_url ||
				selectedTab?.url ||
				openFlowResult?.flow_url_after ||
				null,
			preferredUrl: resolvedPreferredUrl || preferredUrl,
			selectedTab,
			pageDiagnostic,
			openFlowResult,
		}),
		selected_tab_id: activeTabPreflight?.preflight?.selected_tab_id || null,
		active_editor_tab_id:
			activeTabPreflight?.preflight?.active_editor_tab_id || null,
		selected_tab_active: Boolean(
			activeTabPreflight?.preflight?.selected_tab_active,
		),
		selected_tab_url: activeTabPreflight?.selectedTabUrl || null,
		active_editor_tab_url: activeTabPreflight?.activeEditorTabUrl || null,
		rebound_to_active_editor_tab: Boolean(
			activeTabPreflight?.reboundToActiveEditorTab,
		),
		same_project_url: Boolean(activeTabPreflight?.preflight?.same_project_url),
		content_script_alive_on_active_tab: Boolean(
			activeTabPreflight?.preflight?.content_script_alive_on_active_tab,
		),
		safe_to_click_active_tab: Boolean(
			activeTabPreflight?.preflight?.safe_to_click_active_tab,
		),
	};
	if (buildMismatchError) {
		runtimePayload.diagnostic_code = buildMismatchError;
		runtimePayload.diagnostic_detail =
			`GFV2 runtime build proof failed: background=${runtimeBuildProof.background_build_id || "unavailable"} runner=${runtimeBuildProof.runner_build_id || "unavailable"} content=${runtimeBuildProof.content_build_id || "unavailable"}.`;
	}
	if (lastError && !runtimePayload.diagnostic_code) {
		runtimePayload.diagnostic_code = String(lastError);
		runtimePayload.diagnostic_detail = String(lastError);
	}
	updateRuntimeDiagnostics(runtimePayload);

	// Google Flow UI Contract V2 — read-only diagnostic capture + evaluation.
	// Never clicks. Surfaces the V2 readiness alongside the self-test so a live
	// snapshot can be requested without a new endpoint.
	const gfv2 = await captureGoogleFlowV2Readiness(selectedTab);

	return {
		ok: selfTestOk,
		gfv2,
		...buildBackgroundStatusResponse(),
		runner_build_id: runtimeBuildProof.runner_build_id,
		content_build_id: contentBuildId,
		build_match: runtimeBuildProof.build_match,
		build_match_scope: runtimeBuildProof.content_build_id
			? "background_runner_content_page_proof"
			: "content_page_proof_unavailable",
		build_proof: runtimeBuildProof,
		extension_id: chrome.runtime.id || null,
		expected_content_build_id: BUILD_ID,
		bosmax_build_proof: BOSMAX_BUILD_PROOF,
		runner_loaded: Boolean(runnerApi),
		runner_api_keys: runnerApi ? Object.keys(runnerApi) : [],
		cdp_engine_loaded: Boolean(
			chrome?.debugger &&
				typeof beginCdpFileChooserProof === "function" &&
				typeof waitForCdpFileChooserProof === "function",
		),
		flow_tabs: flowTabs.map((tab) => ({
			...summarizeFlowTab(tab),
			tab_kind: classifyFlowTabKind(tab),
		})),
		target_tab: selectedTab
			? {
					...summarizeFlowTab(selectedTab),
					tab_kind: classifyFlowTabKind(selectedTab),
				}
			: null,
		preferred_flow_project_url: resolvedPreferredUrl || preferredUrl,
		open_flow_result: summarizeOpenFlowResult(openFlowResult),
		active_tab_preflight: activeTabPreflight?.preflight || null,
		target_binding_error: activeTabPreflight?.error || null,
		target_binding_telemetry: activeTabPreflight
			? {
					selected_tab_id: activeTabPreflight.preflight?.selected_tab_id || 0,
					active_editor_tab_id:
						activeTabPreflight.preflight?.active_editor_tab_id || 0,
					selected_tab_active:
						Boolean(activeTabPreflight.preflight?.selected_tab_active),
					selected_tab_url: activeTabPreflight.selectedTabUrl || null,
					active_editor_tab_url: activeTabPreflight.activeEditorTabUrl || null,
					rebound_to_active_editor_tab:
						Boolean(activeTabPreflight.reboundToActiveEditorTab),
				}
			: null,
		duplicate_editor_tabs: activeTabPreflight?.duplicate_tab_inventory || [],
		page_diagnostic: pageDiagnostic,
		composer_diagnostic: composerDiagnostic,
		page_preselection_ready: pagePreselectionReady,
		composer_mode_mismatch_non_fatal: composerModeMismatchNonFatal,
		content_receiver_error: contentReceiverError,
		build_mismatch_error: buildMismatchError,
		last_error: lastError,
	};
}

// ─── TRPC Media URL Extractor ──────────────────────────────

function handleTrpcMediaUrls(_trpcUrl, bodyText) {
	try {
		// Extract all fresh GCS signed URLs
		const urlRegex =
			/https:\/\/storage\.googleapis\.com\/ai-sandbox-videofx\/(?:image|video)\/[0-9a-f-]{36}\?[^"'\s]+/g;
		const matches = bodyText.match(urlRegex) || [];
		if (!matches.length) return;

		// Deduplicate and parse
		const urlMap = {};
		for (const rawUrl of matches) {
			// Unescape JSON-escaped URLs
			const url = rawUrl.replace(/\\u0026/g, "&").replace(/\\/g, "");
			const mediaMatch = url.match(/\/(image|video)\/([0-9a-f-]{36})\?/);
			if (mediaMatch) {
				const [, mediaType, mediaId] = mediaMatch;
				// Keep last occurrence (freshest)
				urlMap[mediaId] = { mediaType, url, mediaId };
			}
		}

		const entries = Object.values(urlMap);
		if (!entries.length) return;

		console.log(
			`[FlowAgent] Captured ${entries.length} fresh media URLs from TRPC`,
		);
		// URL refresh is silent — don't show in request log

		// Forward to agent for DB update
		if (ws?.readyState === WebSocket.OPEN) {
			ws.send(
				JSON.stringify({
					type: "media_urls_refresh",
					urls: entries,
				}),
			);
		}
	} catch (e) {
		console.error("[FlowAgent] Failed to extract TRPC media URLs:", e);
	}
}

function sleep(ms) {
	return new Promise((r) => setTimeout(r, ms));
}

// ─── Human-like Telemetry ──────────────────────────────────
// Periodically send tracking events to Google's analytics endpoints
// to mimic normal browser behavior.

const _UA = navigator.userAgent;
let _telemetrySessionId = `;${Date.now()}`;

function _rand(min, max) {
	return Math.floor(Math.random() * (max - min + 1)) + min;
}

function _buildBatchLogPayload() {
	const events = [];
	const types = ["FLOW_IMAGE_LATENCY", "FLOW_VIDEO_LATENCY"];
	const count = _rand(1, 3);
	for (let i = 0; i < count; i++) {
		events.push({
			event: types[_rand(0, types.length - 1)],
			eventProperties: [
				{ key: "CURRENT_TIME_MS", doubleValue: Date.now() },
				{ key: "DURATION_MS", doubleValue: _rand(150, 800) },
				{ key: "USER_AGENT", stringValue: _UA },
				{ key: "IS_DESKTOP", booleanValue: true },
			],
			eventMetadata: { sessionId: _telemetrySessionId },
			eventTime: new Date().toISOString(),
		});
	}
	return { appEvents: events };
}

function _buildFrontendEventsPayload() {
	const eventTypes = [
		"FLOW_IMAGE_LATENCY",
		"FLOW_VIDEO_LATENCY",
		"GRID_SCROLL_DEPTH",
		"FLOW_PROJECT_OPEN",
		"FLOW_SCENE_VIEW",
	];
	const count = _rand(1, 4);
	const events = [];
	for (let i = 0; i < count; i++) {
		const et = eventTypes[_rand(0, eventTypes.length - 1)];
		const params = {
			USER_AGENT: {
				"@type": "type.googleapis.com/google.protobuf.StringValue",
				value: _UA,
			},
			IS_DESKTOP: {
				"@type": "type.googleapis.com/google.protobuf.StringValue",
				value: "true",
			},
		};
		if (et.includes("LATENCY")) {
			params.CURRENT_TIME_MS = {
				"@type": "type.googleapis.com/google.protobuf.StringValue",
				value: String(Date.now()),
			};
			params.DURATION_MS = {
				"@type": "type.googleapis.com/google.protobuf.StringValue",
				value: String(_rand(100, 600)),
			};
		}
		if (et === "GRID_SCROLL_DEPTH") {
			params.MEDIA_GENERATION_PAYGATE_TIER = {
				"@type": "type.googleapis.com/google.protobuf.StringValue",
				value: "PAYGATE_TIER_TWO",
			};
		}
		events.push({
			eventType: et,
			metadata: {
				sessionId: _telemetrySessionId,
				createTime: new Date().toISOString(),
				additionalParams: params,
			},
		});
	}
	return { events };
}

async function sendTelemetry() {
	if (!flowKey || state === "off") return;

	const headers = {
		"Content-Type": "text/plain;charset=UTF-8",
		authorization: `Bearer ${flowKey}`,
	};

	// Telemetry is silent — don't show in request log
	try {
		if (Math.random() < 0.5) {
			await fetch(`https://aisandbox-pa.googleapis.com/v1:batchLog`, {
				method: "POST",
				headers,
				credentials: "include",
				body: JSON.stringify(_buildBatchLogPayload()),
			});
		} else {
			await fetch(
				`https://aisandbox-pa.googleapis.com/v1/flow:batchLogFrontendEvents`,
				{
					method: "POST",
					headers,
					credentials: "include",
					body: JSON.stringify(_buildFrontendEventsPayload()),
				},
			);
		}
	} catch {}
}

// Send telemetry at random intervals (45-120s) to look organic
function scheduleTelemetry() {
	const delay = _rand(45, 120) * 1000;
	setTimeout(async () => {
		await sendTelemetry();
		scheduleTelemetry(); // reschedule with new random interval
	}, delay);
}

// Refresh session ID every ~30min like a real user
setInterval(
	() => {
		_telemetrySessionId = `;${Date.now()}`;
	},
	_rand(25, 35) * 60 * 1000,
);

scheduleTelemetry();

// Ensure initialization runs when worker starts
init().catch(console.error);

console.log("[FlowAgent] Extension loaded");
