const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class FakeClassList {
	constructor() {
		this.values = new Set();
	}

	toggle(name, force) {
		if (force) {
			this.values.add(name);
			return true;
		}
		this.values.delete(name);
		return false;
	}

	contains(name) {
		return this.values.has(name);
	}
}

class FakeElement {
	constructor(id = null) {
		this.id = id;
		this.textContent = "";
		this.classList = new FakeClassList();
		this.listeners = {};
		this.attributes = {};
		this.hidden = false;
	}

	addEventListener(event, handler) {
		this.listeners[event] = handler;
	}

	dispatch(event) {
		const handler = this.listeners[event];
		if (handler) {
			handler();
		}
	}

	getAttribute(name) {
		return this.attributes[name];
	}

	setAttribute(name, value) {
		this.attributes[name] = value;
	}
}

class FakeButton extends FakeElement {
	constructor(id = null, routeKey = null) {
		super(id);
		if (routeKey) {
			this.attributes["data-dashboard-route"] = routeKey;
		}
	}

	click() {
		this.dispatch("click");
	}
}

class FakeFrame extends FakeElement {
	constructor() {
		super("dashboard-frame");
		this._src = "";
		this.onload = null;
		this.onerror = null;
	}

	set src(value) {
		this._src = value;
	}

	get src() {
		return this._src;
	}

	removeAttribute(name) {
		if (name === "src") {
			this._src = "";
		}
		delete this.attributes[name];
	}
}

function assert(condition, message) {
	if (!condition) {
		throw new Error(message);
	}
}

function makeJsonResponse(payload) {
	return {
		ok: true,
		json: async () => payload,
		text: async () => JSON.stringify(payload),
	};
}

function createHarness(fetchQueue) {
	const frame = new FakeFrame();
	const portalUrl = new FakeElement("portal-url");
	const portalTitle = new FakeElement("portal-title");
	const routeLabel = new FakeElement("route-label");
	const portalStatus = new FakeElement("portal-status");
	const portalError = new FakeElement("portal-error");
	const launcherBuildLabel = new FakeElement("launcher-build-label");
	const runtimeStatusLabel = new FakeElement("runtime-status-label");
	const runtimeAgentHealth = new FakeElement("runtime-agent-health");
	const runtimeExtensionState = new FakeElement("runtime-extension-state");
	const runtimeServingMode = new FakeElement("runtime-serving-mode");
	const runtimeOfflineReason = new FakeElement("runtime-offline-reason");
	const runtimeApiBase = new FakeElement("runtime-api-base");
	const runtimeRepairCommand = new FakeElement("runtime-repair-command");
	const currentRouteKey = new FakeElement("current-route-key");
	const lastClickAt = new FakeElement("last-click-at");
	const lastActionCopy = new FakeElement("last-action-copy");
	const iframeSrcCopy = new FakeElement("iframe-src-copy");
	const selectedRouteUrl = new FakeElement("selected-route-url");
	const diagnosticBanner = new FakeElement("diagnostic-banner");
	const diagnosticBannerTitle = new FakeElement("diagnostic-banner-title");
	const diagnosticBannerCopy = new FakeElement("diagnostic-banner-copy");
	const readyMarker = new FakeElement("flowkit-side-panel-ready-marker");
	const errorMarker = new FakeElement("flowkit-side-panel-error-marker");
	const root = new FakeElement("flowkit-side-panel-root");
	const openSelectedRouteButton = new FakeButton("btn-open-selected-route");
	const retryButton = new FakeButton("btn-retry-runtime");
	const buttons = [
		new FakeButton(null, "operator"),
		new FakeButton(null, "product"),
		new FakeButton(null, "prompt"),
		new FakeButton(null, "registry"),
		new FakeButton(null, "creative"),
		new FakeButton(null, "bank"),
	];

	const domContentLoaded = {};
	const document = {
		body: new FakeElement("body"),
		getElementById(id) {
			return (
				{
					"dashboard-frame": frame,
					"portal-url": portalUrl,
					"portal-title": portalTitle,
					"route-label": routeLabel,
					"portal-status": portalStatus,
					"portal-error": portalError,
					"launcher-build-label": launcherBuildLabel,
					"runtime-status-label": runtimeStatusLabel,
					"runtime-agent-health": runtimeAgentHealth,
					"runtime-extension-state": runtimeExtensionState,
					"runtime-serving-mode": runtimeServingMode,
					"runtime-offline-reason": runtimeOfflineReason,
					"runtime-api-base": runtimeApiBase,
					"runtime-repair-command": runtimeRepairCommand,
					"current-route-key": currentRouteKey,
					"last-click-at": lastClickAt,
					"last-action-copy": lastActionCopy,
					"iframe-src-copy": iframeSrcCopy,
					"selected-route-url": selectedRouteUrl,
					"diagnostic-banner": diagnosticBanner,
					"diagnostic-banner-title": diagnosticBannerTitle,
					"diagnostic-banner-copy": diagnosticBannerCopy,
					"flowkit-side-panel-ready-marker": readyMarker,
					"flowkit-side-panel-error-marker": errorMarker,
					"flowkit-side-panel-root": root,
					"btn-open-selected-route": openSelectedRouteButton,
					"btn-retry-runtime": retryButton,
				}[id] || null
			);
		},
		querySelectorAll(selector) {
			if (selector === "[data-dashboard-route]") {
				return buttons;
			}
			return [];
		},
		addEventListener(event, handler) {
			domContentLoaded[event] = handler;
		},
	};

	let nextTimerId = 1;
	const timers = new Map();
	const tabCreates = [];
	const windowOpenCalls = [];
	const windowObj = {
		setTimeout(handler, delay) {
			const id = nextTimerId++;
			timers.set(id, { handler, delay });
			return id;
		},
		clearTimeout(id) {
			timers.delete(id);
		},
		open(url, target) {
			windowOpenCalls.push({ url, target });
		},
	};

	const context = vm.createContext({
		console,
		document,
		window: windowObj,
		AbortController,
		fetch: async () => {
			if (!fetchQueue.length) {
				throw new Error("Fetch queue exhausted");
			}
			const next = fetchQueue.shift();
			if (next instanceof Error) {
				throw next;
			}
			if (typeof next === "function") {
				return next();
			}
			return next;
		},
		chrome: {
			runtime: {
				lastError: null,
			},
			tabs: {
				create({ url }, callback) {
					tabCreates.push(url);
					if (callback) {
						callback();
					}
				},
			},
		},
	});

	const scriptPath = path.join(process.cwd(), "extension", "side_panel.js");
	const code = fs.readFileSync(scriptPath, "utf8");
	vm.runInContext(code, context, { filename: scriptPath });

	function flushTimers(delay) {
		const ready = [...timers.entries()].filter(
			([, timer]) => timer.delay === delay,
		);
		for (const [id, timer] of ready) {
			timers.delete(id);
			timer.handler();
		}
	}

	async function flushAsync() {
		for (let index = 0; index < 8; index += 1) {
			await Promise.resolve();
		}
	}

	return {
		buttons,
		context,
		currentRouteKey,
		diagnosticBanner,
		diagnosticBannerCopy,
		diagnosticBannerTitle,
		document,
		domContentLoaded,
		errorMarker,
		fetchQueue,
		flushAsync,
		flushTimers,
		frame,
		iframeSrcCopy,
		lastActionCopy,
		openSelectedRouteButton,
		portalStatus,
		readyMarker,
		retryButton,
		root,
		runtimeAgentHealth,
		runtimeExtensionState,
		runtimeOfflineReason,
		runtimeServingMode,
		runtimeStatusLabel,
		selectedRouteUrl,
		tabCreates,
		windowOpenCalls,
	};
}

async function runReadyScenario() {
	const queue = [
		makeJsonResponse({
			extension_connected: true,
			extension_state: "IDLE",
			dashboard_serving_mode: "BACKEND_SERVED_STATIC",
			repair_command: ".\\scripts\\install-local-agent.ps1",
			offline_reason: null,
		}),
		makeJsonResponse({
			status: "ok",
			extension_connected: true,
			extension_state: "idle",
		}),
	];
	const harness = createHarness(queue);
	assert(
		harness.domContentLoaded.DOMContentLoaded,
		"DOMContentLoaded handler missing",
	);

	harness.domContentLoaded.DOMContentLoaded();
	await harness.flushAsync();

	assert(
		harness.frame.src === "http://127.0.0.1:8100/operator?portal=side",
		"boot route should target operator dashboard",
	);
	assert(
		harness.root.attributes["data-runtime-state"] === "loading",
		"root should stay loading until iframe load completes",
	);
	assert(
		harness.runtimeServingMode.textContent === "BACKEND_SERVED_STATIC",
		"serving mode should surface backend static status",
	);
	assert(
		harness.runtimeExtensionState.textContent === "CONNECTED / IDLE",
		"extension runtime should report connected state",
	);

	harness.frame.onload();
	harness.flushTimers(250);

	assert(
		harness.document.body.classList.contains("ready"),
		"ready class should be set after iframe load",
	);
	assert(
		harness.readyMarker.hidden === false,
		"ready marker should be visible after successful load",
	);
	assert(
		harness.errorMarker.hidden === true,
		"error marker should stay hidden after successful load",
	);
	assert(
		harness.diagnosticBanner.attributes["data-banner-state"] === "success",
		"ready banner should report success",
	);
	assert(
		harness.portalStatus.textContent === "Operator Dashboard online.",
		"operator status should report online after iframe load",
	);
	assert(
		harness.runtimeStatusLabel.textContent === "Dashboard status: online",
		"runtime status should report online after iframe load",
	);

	harness.fetchQueue.push(
		makeJsonResponse({
			extension_connected: true,
			extension_state: "IDLE",
			dashboard_serving_mode: "BACKEND_SERVED_STATIC",
			repair_command: ".\\scripts\\install-local-agent.ps1",
			offline_reason: null,
		}),
		makeJsonResponse({
			status: "ok",
			extension_connected: true,
			extension_state: "idle",
		}),
	);

	harness.buttons
		.find(
			(button) => button.getAttribute("data-dashboard-route") === "registry",
		)
		.click();
	await harness.flushAsync();
	harness.frame.onload();
	harness.flushTimers(250);
	assert(
		harness.currentRouteKey.textContent === "registry",
		"route click should update current route key",
	);
	assert(
		harness.frame.src === "http://127.0.0.1:8100/asset-registry",
		"route click should retarget the iframe after runtime checks pass",
	);

	harness.fetchQueue.push(
		makeJsonResponse({
			extension_connected: true,
			extension_state: "IDLE",
			dashboard_serving_mode: "BACKEND_SERVED_STATIC",
			repair_command: ".\\scripts\\install-local-agent.ps1",
			offline_reason: null,
		}),
		makeJsonResponse({
			status: "ok",
			extension_connected: true,
			extension_state: "idle",
		}),
	);

	harness.buttons
		.find(
			(button) => button.getAttribute("data-dashboard-route") === "creative",
		)
		.click();
	await harness.flushAsync();
	harness.frame.onload();
	harness.flushTimers(250);
	assert(
		harness.currentRouteKey.textContent === "creative",
		"creative route click should update current route key",
	);
	assert(
		harness.frame.src ===
			"http://127.0.0.1:8100/assets/creative-library?portal=side",
		"creative route should target the creative library portal route",
	);

	harness.fetchQueue.push(
		makeJsonResponse({
			extension_connected: true,
			extension_state: "IDLE",
			dashboard_serving_mode: "BACKEND_SERVED_STATIC",
			repair_command: ".\\scripts\\install-local-agent.ps1",
			offline_reason: null,
		}),
		makeJsonResponse({
			status: "ok",
			extension_connected: true,
			extension_state: "idle",
		}),
	);

	harness.buttons
		.find((button) => button.getAttribute("data-dashboard-route") === "bank")
		.click();
	await harness.flushAsync();
	harness.frame.onload();
	harness.flushTimers(250);
	assert(
		harness.currentRouteKey.textContent === "bank",
		"bank route click should update current route key",
	);
	assert(
		harness.frame.src ===
			"http://127.0.0.1:8100/workspace/generation-packages?portal=side",
		"bank route should target the prompt handoff bank portal route",
	);

	harness.openSelectedRouteButton.click();
	assert(
		harness.tabCreates.at(-1) ===
			"http://127.0.0.1:8100/workspace/generation-packages?portal=side",
		"open selected route should use the active route",
	);
	assert(
		harness.windowOpenCalls.length === 0,
		"window.open fallback should not be used when chrome.tabs.create exists",
	);
}

async function runOfflineRetryScenario() {
	const queue = [
		new Error("connect ECONNREFUSED"),
		new Error("connect ECONNREFUSED"),
	];
	const harness = createHarness(queue);
	assert(
		harness.domContentLoaded.DOMContentLoaded,
		"DOMContentLoaded handler missing",
	);

	harness.domContentLoaded.DOMContentLoaded();
	await harness.flushAsync();

	assert(
		harness.document.body.classList.contains("error"),
		"offline boot should fail closed into error state",
	);
	assert(
		harness.errorMarker.hidden === false,
		"error marker should be visible when runtime is offline",
	);
	assert(
		harness.portalStatus.textContent.includes("Local agent offline"),
		"offline message should mention local agent availability",
	);
	assert(
		harness.diagnosticBanner.attributes["data-banner-state"] === "error",
		"offline banner should report error",
	);
	assert(
		harness.runtimeOfflineReason.textContent === "LOCAL_AGENT_OFFLINE",
		"offline reason should be explicit",
	);

	harness.fetchQueue.push(
		makeJsonResponse({
			extension_connected: false,
			extension_state: "OFF",
			dashboard_serving_mode: "BACKEND_SERVED_STATIC",
			repair_command: ".\\scripts\\install-local-agent.ps1",
			offline_reason: "EXTENSION_DISCONNECTED",
		}),
		makeJsonResponse({
			status: "ok",
			extension_connected: false,
			extension_state: "off",
		}),
	);

	harness.retryButton.click();
	await harness.flushAsync();
	harness.frame.onload();
	harness.flushTimers(250);

	assert(
		harness.document.body.classList.contains("ready"),
		"retry should recover to ready state once backend comes back",
	);
	assert(
		harness.diagnosticBanner.attributes["data-banner-state"] === "warning",
		"background disconnect should remain explicit as a warning",
	);
	assert(
		harness.diagnosticBannerCopy.textContent.includes(
			"background runtime is disconnected",
		),
		"warning banner should explain the disconnected extension background",
	);
}

async function main() {
	await runReadyScenario();
	await runOfflineRetryScenario();
	console.log("PASS side_panel route wiring harness");
}

main().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
