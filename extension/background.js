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
			if (settled) return;
			settled = true;
			clearTimeout(timer);

			const lastError = chrome.runtime.lastError;
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
}

function settleCdpFileChooserProofRun(tabId, payload) {
	const run = cdpFileChooserProofRuns.get(tabId);
	if (!run || run.settled) return;
	run.settled = true;
	run.result = payload;
	void cleanupCdpFileChooserProofRun(tabId, run).finally(() => {
		run.resolve(payload);
	});
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

	run.timeoutId = setTimeout(() => {
		settleCdpFileChooserProofRun(tabId, {
			ok: false,
			error: "ERR_CDP_FILE_CHOOSER_TIMEOUT",
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

async function waitForCdpFileChooserProof(tabId) {
	const run = cdpFileChooserProofRuns.get(tabId);
	if (!run) {
		return { ok: false, error: "ERR_CDP_FILE_CHOOSER_NOT_ARMED" };
	}

	const result = run.result || (await run.completionPromise);
	cdpFileChooserProofRuns.delete(tabId);
	return result;
}

async function fetchAssetBase64ForCdp(assetId) {
	const url = `http://127.0.0.1:8100/api/products/${assetId}/image`;
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
async function materializeAssetToDiskPath(assetId, slotLabel) {
	const fetched = await fetchAssetBase64ForCdp(assetId);
	if (!fetched.ok) return fetched;
	const ext = (fetched.mimeType.split("/")[1] || "png").replace("jpeg", "jpg");
	const fileName = `${String(slotLabel || "start").toLowerCase()}-${assetId}.${ext}`;
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
		return await beginCdpFileChooserProof(
			tabId,
			mat.filePath,
			mat.fileName,
			slot,
		);
	}
	if (req?.phase === "wait") {
		return await waitForCdpFileChooserProof(tabId);
	}
	return {
		ok: false,
		error: "ERR_CDP_UPLOAD_BAD_PHASE",
		detail: `phase=${req?.phase}`,
	};
}

const WS_METHOD_TIMEOUT_MS = {
	get_status: 5000,
	GET_RUNTIME_SELF_TEST: 60000,
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

	return selectBestFlowTab(tabs, preferredUrl);
}

async function getFlowTabs() {
	return await chrome.tabs.query({
		url: [
			"https://labs.google/fx/tools/flow*",
			"https://labs.google/fx/*/tools/flow*",
		],
	});
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

function selectBestFlowTab(tabs, preferredUrl = null) {
	if (!tabs.length) {
		console.log("[FlowAgent] No tabs found in query");
		return null;
	}

	console.log(
		"[FlowAgent] Found Flow tabs:",
		tabs.map((t) => ({ id: t.id, url: t.url, status: t.status })),
	);

	const normalizedPreferredUrl = String(preferredUrl || "").trim();
	if (normalizedPreferredUrl) {
		const exactMatch = tabs.find((tab) => tab.url === normalizedPreferredUrl);
		if (exactMatch) {
			console.log("[FlowAgent] Using exact preferred match:", exactMatch.url);
			return exactMatch;
		}
	}

	const editorTab = tabs.find((tab) => isProjectEditorUrl(tab.url));
	if (editorTab) {
		console.log("[FlowAgent] Using project editor tab:", editorTab.url);
		return editorTab;
	}

	const nonRootTab = tabs.find((tab) => !isRootFlowUrl(tab.url));
	if (nonRootTab) {
		console.log("[FlowAgent] Using non-root tab:", nonRootTab.url);
		return nonRootTab;
	}

	console.log("[FlowAgent] Falling back to first tab:", tabs[0].url);
	return tabs[0];
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

function isActualFlowEditorProbe(result) {
	if (!result || result.error) {
		return false;
	}
	const modeVisible = String(result.current_mode_visible || "");
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
		ok: isActualFlowEditorProbe(readiness),
		tab: summarizeFlowTab(safeTab),
		readiness,
		diagnostic,
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

	let selectedTab = selectBestFlowTab(tabs, preferredUrl);
	if (selectedTab && isProjectEditorUrl(selectedTab.url)) {
		return {
			ok: true,
			targetTab: selectedTab,
			candidate_tabs: initialCandidateTabs,
		};
	}

	const rankedTabs = [
		selectedTab,
		...tabs.filter((tab) => tab?.id !== selectedTab?.id),
	].filter(Boolean);
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

	if (selectedTab && isRootFlowUrl(selectedTab.url)) {
		const openResult = await handleOpenFlowNewProject(job?.mode);
		tabs = await getFlowTabs();
		const candidateTabs = tabs.map(summarizeFlowTab).filter(Boolean);
		selectedTab =
			tabs.find((tab) => tab.id === openResult?.flow_tab_id) ||
			selectBestFlowTab(tabs, openResult?.flow_url || preferredUrl);
		if (selectedTab && isProjectEditorUrl(selectedTab.url)) {
			return {
				ok: true,
				targetTab: selectedTab,
				candidate_tabs: candidateTabs,
				open_flow_result: summarizeOpenFlowResult(openResult),
			};
		}
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
				reason: "flow_root_without_project_editor",
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
		return null;
	}
	await chrome.storage.local.set({
		[FLOW_PROJECT_URL_STORAGE_KEY]: normalized,
	});
	return normalized;
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
	if (
		result?.flow_url &&
		!result.flow_url.includes("/project/") &&
		!result.flow_url.includes("/edit/")
	) {
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

async function handleOpenTargetFlowProject(flowProjectUrl) {
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

	if (!isProjectEditorUrl(flowUrlAfter)) {
		return {
			ok: false,
			error: "FLOW_PROJECT_EDITOR_NOT_OPEN",
			flow_project_url: normalizedUrl,
			flow_tab_id: flowTabId,
			flow_url_before: flowUrlBefore,
			flow_url_after: flowUrlAfter,
			flow_url: flowUrlAfter,
			extension_protocol_version: EXTENSION_PROTOCOL_VERSION,
			...diagnostic,
		};
	}

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
	if (isProjectEditorUrl(resolvedFlowUrl)) {
		await setStoredFlowProjectUrl(resolvedFlowUrl);
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
		flow_tab_id: refreshedTab?.id ?? targetTab?.id ?? null,
		flow_url_before: rootUrl,
		flow_url_after: resolvedFlowUrl,
		flow_url: resolvedFlowUrl,
		extension_protocol_version: EXTENSION_PROTOCOL_VERSION,
		...result,
	};
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
				const result = await executeWsMethodAndReply(msg, async () =>
					buildBackgroundStatusResponse(),
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
				const result = await executeWsMethodAndReply(msg, () =>
					handleExecuteFlowJob(msg.params?.job),
				);
				replyToAgent(msg, result);
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
		if (!manualDisconnect) scheduleReconnect();
	};

	ws.onerror = (e) => {
		console.error("[FlowAgent] WS error:", e);
		metrics.lastError = "WS_ERROR";
		chrome.storage.local.set({ metrics });
	};
}

function scheduleReconnect() {
	chrome.alarms.create("reconnect", { delayInMinutes: 0.083 }); // ~5s
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
	const initialResponse = await sendTabMessageSafe(tabId, {
		type: "GET_CAPTCHA",
		requestId,
		pageAction,
	});

	if (!initialResponse?.error) {
		return initialResponse;
	}

	const msg = initialResponse.error || "";
	const shouldInject =
		msg.includes("Receiving end does not exist") ||
		msg.includes("Could not establish connection");
	if (!shouldInject) {
		return initialResponse;
	}

	await chrome.scripting.executeScript({
		target: { tabId },
		files: ["content.js"],
	});
	await sleep(200);
	return await sendTabMessageSafe(tabId, {
		type: "GET_CAPTCHA",
		requestId,
		pageAction,
	});
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

const BUILD_ID = "flowkit-f2v-runner-audit-2026-05-28b";

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
		build_match: true,
	};
}

function buildStageTelemetryPayload(message = {}, contentHealth = null) {
	return {
		request_id: message.request_id,
		timestamp: message.timestamp || new Date().toISOString(),
		git_sha: message.git_sha || BUILD_ID,
		background_build_id: BUILD_ID,
		content_build_id:
			message.content_build_id || contentHealth?.content_build_id || BUILD_ID,
		stage: message.stage,
		checkpoint: message.checkpoint || message.stage,
		status: message.status,
		message: message.message || null,
		source: message.source || "extension",
		runtime_ready:
			typeof message.runtime_ready === "boolean"
				? message.runtime_ready
				: Boolean(contentHealth?.runtime_ready),
		build_match:
			typeof message.build_match === "boolean"
				? message.build_match
				: (message.content_build_id ||
						contentHealth?.content_build_id ||
						BUILD_ID) === BUILD_ID,
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
	if (msg.type === "STATUS") {
		return buildBackgroundStatusResponse();
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
		return await beginCdpFileChooserProof(
			sender?.tab?.id || null,
			msg.filePath,
			msg.expectedFileName,
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

	return respondAsync(sendResponse, async () => {
		const data = await handleMessage(message, sender);
		return data && typeof data === "object" && "ok" in data
			? data
			: { ok: true, data };
	});
});

async function handleExecuteFlowJob(job) {
	const targetResolution = await resolveFlowExecutionTarget(job);
	if (!targetResolution.ok) {
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
				const runnerResult = await runnerApi.executeF2VVisibleSopRunner(
					deps,
					flowTab.id,
					job,
					{
						settleMs: 300,
						uploadWaitMs: 10000,
						cdpCoordinateClick: async (params) => {
							console.log(
								"[FlowAgent] Performing CDP coordinate click:",
								params,
							);
							return await cdpClickCoordinate(params.tabId, params.x, params.y);
						},
						// Phase 2 opt-in: only jobs that explicitly set use_cdp_upload get the CDP
						// file-chooser upload path; everything else keeps the proven DOM path.
						...(job.use_cdp_upload === true
							? {
									cdpFileChooserUpload: (req) =>
										cdpFileChooserUploadForJob(flowTab.id, req),
								}
							: {}),
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

async function handleCheckFlowComposerReady(mode) {
	const flowTab = await getFlowTab();
	const base = buildFlowReadinessBase(flowTab);
	if (!flowTab) {
		return finalizeFlowReadiness({
			...base,
			error: "ERR_NO_FLOW_TAB",
			raw_error: "ERR_NO_FLOW_TAB",
			detail: "No Google Flow tab matched the editor URL patterns.",
		});
	}

	await ensureFlowDomScript(flowTab.id);

	const diagnostic = await pingFlowDomScript(flowTab);
	if (diagnostic.raw_error) {
		return finalizeFlowReadiness({
			...base,
			...diagnostic,
			error: diagnostic.raw_error,
		});
	}

	const response = await sendTabMessageSafe(flowTab.id, {
		type: "CHECK_FLOW_COMPOSER_READY",
		mode,
	});
	if (response?.error === "ERR_MESSAGE_RESPONSE_TIMEOUT") {
		return finalizeFlowReadiness({
			...base,
			...diagnostic,
			error: "ERR_MESSAGE_RESPONSE_TIMEOUT",
			raw_error: "ERR_MESSAGE_RESPONSE_TIMEOUT",
			detail: "Timed out waiting for content script readiness response.",
		});
	}
	if (response?.error) {
		return finalizeFlowReadiness({
			...base,
			...diagnostic,
			error: response.error,
			raw_error: response.error,
			detail: response.error,
		});
	}
	if (!response?.ok && !response?.error) {
		return finalizeFlowReadiness({
			...base,
			...diagnostic,
			error: "ABORT_FLOW_COMPOSER_NOT_READY",
			raw_error: "ERR_EMPTY_COMPOSER_RESPONSE",
		});
	}
	return finalizeFlowReadiness({
		...base,
		...diagnostic,
		...response,
		flow_url: response?.flow_url || flowTab.url,
	});
}

async function handleFlowPageStateDiagnostic(mode) {
	const flowTab = await getFlowTab();
	const base = buildFlowReadinessBase(flowTab);
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
		};
	}

	await ensureFlowDomScript(flowTab.id);

	const diagnostic = await pingFlowDomScript(flowTab);
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
		};
	}

	const response = await sendTabMessageSafe(flowTab.id, {
		type: "FLOW_PAGE_STATE_DIAGNOSTIC",
		mode,
	});

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
		};
	}

	return {
		...base,
		...diagnostic,
		...response,
		flow_url: response?.flow_url || flowTab.url,
	};
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

async function handleRuntimeSelfTest(mode = "F2V", attemptOpenProject = false) {
	const preferredUrl = await getStoredFlowProjectUrl();
	let flowTabs = await getFlowTabs();
	let selectedTab = selectBestFlowTab(flowTabs, preferredUrl);
	let openFlowResult = null;

	if (
		attemptOpenProject &&
		selectedTab &&
		isRootFlowUrl(selectedTab.url) &&
		!isProjectEditorUrl(selectedTab.url)
	) {
		openFlowResult = await handleOpenFlowNewProject(mode);
		flowTabs = await getFlowTabs();
		selectedTab = selectBestFlowTab(
			flowTabs,
			openFlowResult?.flow_url || preferredUrl,
		);
	}

	const pageDiagnostic = await handleFlowPageStateDiagnostic(mode);
	const composerDiagnostic = await handleCheckFlowComposerReady(mode);
	const runnerApi =
		typeof self !== "undefined" ? self.__BOSMAX_F2V_FLOW_QUEUE_RUNNER__ : null;
	const contentBuildId = String(
		pageDiagnostic?.content_build_id ||
			composerDiagnostic?.content_build_id ||
			"",
	).trim();
	const buildMismatchError =
		contentBuildId && contentBuildId !== BUILD_ID
			? "ERR_EXTENSION_BUILD_MISMATCH"
			: null;
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
		contentReceiverError ||
		(composerModeMismatchNonFatal
			? null
			: composerDiagnostic?.error ||
				pageDiagnostic?.error ||
				openFlowResult?.error ||
				null);
	const selfTestOk = Boolean(selectedTab) && !lastError;

	return {
		ok: selfTestOk,
		...buildBackgroundStatusResponse(),
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
		preferred_flow_project_url: preferredUrl,
		open_flow_result: summarizeOpenFlowResult(openFlowResult),
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
