const LOCAL_AGENT_BASE_URL = "http://127.0.0.1:8100";
const LOCAL_AGENT_HEALTH_URL = `${LOCAL_AGENT_BASE_URL}/health`;
const LOCAL_AGENT_STATUS_URL = `${LOCAL_AGENT_BASE_URL}/api/local-agent/status`;
const DASHBOARD_STATIC_READY = "BACKEND_SERVED_STATIC";
const HEALTH_REQUEST_TIMEOUT_MS = 4500;
const IFRAME_LOAD_TIMEOUT_MS = 12000;

const DASHBOARD_ROUTES = {
	operator: {
		label: "Operator Dashboard",
		url: `${LOCAL_AGENT_BASE_URL}/operator?portal=side`,
	},
	product: {
		label: "Product Asset Generator",
		url: `${LOCAL_AGENT_BASE_URL}/product-asset-generator`,
	},
	prompt: {
		label: "Prompt Preview",
		url: `${LOCAL_AGENT_BASE_URL}/prompt-preview`,
	},
	registry: {
		label: "Asset Registry",
		url: `${LOCAL_AGENT_BASE_URL}/asset-registry`,
	},
};

const LAUNCHER_BUILD_LABEL = "issue81-side-panel-runtime-guard";

let navigationToken = 0;
let selectedRouteKey = "operator";

function getElement(id) {
	return document.getElementById(id);
}

function setRuntimeCopy(id, value) {
	const element = getElement(id);
	if (element) {
		element.textContent = value;
	}
}

function setMarkerVisibility(id, visible) {
	const marker = getElement(id);
	if (marker) {
		marker.hidden = !visible;
	}
}

function setPanelState(state) {
	document.body.classList.toggle("ready", state === "ready");
	document.body.classList.toggle("error", state === "error");
	document.body.classList.toggle("loading", state === "loading");

	const root = getElement("flowkit-side-panel-root");
	if (root) {
		root.setAttribute("data-runtime-state", state);
	}

	setMarkerVisibility("flowkit-side-panel-ready-marker", state === "ready");
	setMarkerVisibility("flowkit-side-panel-error-marker", state === "error");
}

function setBanner(state, title, copy) {
	const banner = getElement("diagnostic-banner");
	if (banner) {
		banner.setAttribute("data-banner-state", state);
	}
	setRuntimeCopy("diagnostic-banner-title", title);
	setRuntimeCopy("diagnostic-banner-copy", copy);
}

function setPortalState(state, detail = "", titleText = "") {
	setPanelState(state);

	const route = DASHBOARD_ROUTES[selectedRouteKey] || DASHBOARD_ROUTES.operator;
	const statusEl = getElement("portal-status");
	const errorEl = getElement("portal-error");
	const titleEl = getElement("portal-title");
	const runtimeStatusEl = getElement("runtime-status-label");

	if (titleEl) {
		titleEl.textContent =
			titleText ||
			(state === "ready"
				? `${route.label} ready`
				: state === "error"
					? "Flow Kit side panel blocked"
					: `Loading ${route.label.toLowerCase()}`);
	}

	if (statusEl) {
		statusEl.textContent =
			detail ||
			(state === "ready"
				? `${route.label} online.`
				: state === "error"
					? "Local agent unavailable."
					: "Connecting to localhost dashboard...");
	}

	if (errorEl && state === "error") {
		errorEl.textContent =
			detail ||
			`Embedded dashboard failed to load. Confirm ${route.url} is live and allowed inside the Flow Kit side panel.`;
	}

	if (runtimeStatusEl) {
		runtimeStatusEl.textContent =
			state === "ready"
				? "Dashboard status: online"
				: state === "error"
					? "Dashboard status: blocked"
					: "Dashboard status: loading";
	}
}

function setLastAction(message) {
	setRuntimeCopy("last-action-copy", message);
}

function setCurrentRoute(routeKey, routeUrl) {
	selectedRouteKey = routeKey;
	setRuntimeCopy("current-route-key", routeKey);
	setRuntimeCopy("selected-route-url", routeUrl);
}

function setIframeSrcCopy(value) {
	setRuntimeCopy("iframe-src-copy", value || "not-set");
}

function setFrameSource(value) {
	const frame = getElement("dashboard-frame");
	if (!frame) {
		return;
	}
	if (value) {
		frame.src = value;
		setIframeSrcCopy(value);
		return;
	}
	frame.removeAttribute("src");
	setIframeSrcCopy("about:blank");
}

function recordClick(routeLabel, routeUrl) {
	const stamp = new Date().toLocaleString("en-GB", {
		hour12: false,
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit",
	});
	setRuntimeCopy("last-click-at", stamp);
	setLastAction(`Clicked: ${routeLabel}`);
	setRuntimeCopy("selected-route-url", routeUrl);
}

function openRouteInBrowserTab(route) {
	if (!route) {
		setLastAction("Open selected route failed: route is missing.");
		return;
	}

	if (
		typeof chrome !== "undefined" &&
		chrome.tabs &&
		typeof chrome.tabs.create === "function"
	) {
		chrome.tabs.create({ url: route.url }, () => {
			if (chrome.runtime?.lastError) {
				setLastAction(
					`Open selected route failed: ${chrome.runtime.lastError.message}`,
				);
				return;
			}
			setLastAction(`Opened selected route in browser tab: ${route.label}`);
		});
		return;
	}

	if (typeof window.open === "function") {
		window.open(route.url, "_blank");
		setLastAction(`Opened selected route with window.open: ${route.label}`);
		return;
	}

	setLastAction("Open selected route failed: no browser tab API available.");
}

function setActiveButton(routeKey) {
	document.querySelectorAll("[data-dashboard-route]").forEach((button) => {
		button.classList.toggle(
			"active",
			button.getAttribute("data-dashboard-route") === routeKey,
		);
	});
}

function getExtensionConnected(snapshot) {
	if (!snapshot) {
		return false;
	}
	if (typeof snapshot.status?.extension_connected === "boolean") {
		return snapshot.status.extension_connected;
	}
	return Boolean(snapshot.health?.extension_connected);
}

function getExtensionState(snapshot) {
	return String(
		snapshot?.status?.extension_state ||
			snapshot?.health?.extension_state ||
			"UNKNOWN",
	).toUpperCase();
}

function getServingMode(snapshot) {
	return (
		snapshot?.status?.dashboard_serving_mode ||
		snapshot?.health?.dashboard_serving_mode ||
		"UNKNOWN"
	);
}

function canEmbedDashboard(snapshot) {
	return (
		snapshot?.health?.status === "ok" &&
		getServingMode(snapshot) === DASHBOARD_STATIC_READY
	);
}

function syncRuntimeDiagnostics(snapshot, route) {
	const capturedAt = snapshot?.capturedAt || "unavailable";
	const extensionConnected = getExtensionConnected(snapshot);
	const extensionState = getExtensionState(snapshot);
	const servingMode = getServingMode(snapshot);
	const offlineReason =
		snapshot?.status?.offline_reason || snapshot?.errorCode || "NONE";
	const repairCommand =
		snapshot?.status?.repair_command || ".\\scripts\\install-local-agent.ps1";

	setRuntimeCopy(
		"runtime-agent-health",
		snapshot?.health?.status === "ok"
			? `ONLINE (${capturedAt})`
			: `OFFLINE (${capturedAt})`,
	);
	setRuntimeCopy(
		"runtime-extension-state",
		extensionConnected
			? `CONNECTED / ${extensionState}`
			: `DISCONNECTED / ${extensionState}`,
	);
	setRuntimeCopy("runtime-serving-mode", servingMode);
	setRuntimeCopy("runtime-offline-reason", offlineReason);
	setRuntimeCopy("runtime-api-base", LOCAL_AGENT_BASE_URL);
	setRuntimeCopy("runtime-repair-command", repairCommand);
	setRuntimeCopy("selected-route-url", route.url);
}

function renderUnavailableState(route, snapshot) {
	syncRuntimeDiagnostics(snapshot, route);
	setFrameSource("");

	if (!snapshot || snapshot.errorCode === "LOCAL_AGENT_OFFLINE") {
		setBanner(
			"error",
			"Local agent offline",
			`Local agent offline. Retry after confirming ${LOCAL_AGENT_BASE_URL} is reachable.`,
		);
		setPortalState(
			"error",
			`Local agent offline. Retry after confirming ${LOCAL_AGENT_BASE_URL} is reachable.`,
			"Local agent offline",
		);
		setLastAction("Runtime check failed: local agent offline.");
		return;
	}

	if (getServingMode(snapshot) !== DASHBOARD_STATIC_READY) {
		const buildMessage = `Dashboard build required. Run ${snapshot.status?.repair_command || ".\\scripts\\install-local-agent.ps1"} and reload Flow Kit.`;
		setBanner("error", "Dashboard build required", buildMessage);
		setPortalState("error", buildMessage, "Dashboard build required");
		setLastAction("Runtime check failed: dashboard production bundle missing.");
		return;
	}

	setBanner(
		"warning",
		"Extension background disconnected",
		"Local agent is online, but the Flow Kit background runtime is disconnected. Reload Flow Kit in chrome://extensions, then retry.",
	);
	setPortalState(
		"error",
		"Extension background disconnected. Reload Flow Kit in chrome://extensions, then retry.",
		"Extension background disconnected",
	);
	setLastAction("Runtime check failed: extension background disconnected.");
}

function renderFrameLoadingState(route, snapshot) {
	syncRuntimeDiagnostics(snapshot, route);

	if (getExtensionConnected(snapshot)) {
		setBanner(
			"info",
			"Local agent online",
			`Local agent online. Connecting ${route.label}.`,
		);
	} else {
		setBanner(
			"warning",
			"Extension background disconnected",
			"Local agent is online, but the Flow Kit background runtime is disconnected. Reload Flow Kit in chrome://extensions while the dashboard route finishes loading.",
		);
	}

	setPortalState(
		"loading",
		`Connecting to ${route.label}...`,
		`Loading ${route.label.toLowerCase()}`,
	);
}

function renderReadyState(route, snapshot) {
	syncRuntimeDiagnostics(snapshot, route);
	if (getExtensionConnected(snapshot)) {
		setBanner(
			"success",
			"Flow Kit ready",
			`${route.label} loaded with local-agent diagnostics attached.`,
		);
	} else {
		setBanner(
			"warning",
			"Extension background disconnected",
			`${route.label} loaded, but the Flow Kit background runtime is disconnected. Reload Flow Kit in chrome://extensions to restore background services.`,
		);
	}

	setPortalState("ready", `${route.label} online.`, `${route.label} ready`);
	setLastAction(`Iframe loaded: ${route.label}`);
}

function renderFrameErrorState(route, snapshot, message) {
	syncRuntimeDiagnostics(snapshot, route);
	setBanner("error", "Embedded dashboard failed to load", message);
	setPortalState("error", message, "Embedded dashboard failed");
	setLastAction(`Iframe error: ${message}`);
}

async function fetchJsonWithTimeout(url, timeoutMs) {
	const controller = new AbortController();
	const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

	try {
		const response = await fetch(url, {
			cache: "no-store",
			signal: controller.signal,
		});
		if (!response.ok) {
			const errorBody = await response.text().catch(() => "");
			throw new Error(
				`HTTP ${response.status} ${errorBody}`.trim().slice(0, 240),
			);
		}
		return await response.json();
	} finally {
		window.clearTimeout(timeoutId);
	}
}

async function fetchRuntimeSnapshot() {
	const snapshot = {
		capturedAt: new Date().toISOString(),
		status: null,
		health: null,
		errorCode: null,
	};

	const [statusResult, healthResult] = await Promise.allSettled([
		fetchJsonWithTimeout(LOCAL_AGENT_STATUS_URL, HEALTH_REQUEST_TIMEOUT_MS),
		fetchJsonWithTimeout(LOCAL_AGENT_HEALTH_URL, HEALTH_REQUEST_TIMEOUT_MS),
	]);

	if (statusResult.status === "fulfilled") {
		snapshot.status = statusResult.value;
	}
	if (healthResult.status === "fulfilled") {
		snapshot.health = healthResult.value;
	}

	if (!snapshot.status || !snapshot.health) {
		snapshot.errorCode = "LOCAL_AGENT_OFFLINE";
		return snapshot;
	}

	if (!getExtensionConnected(snapshot)) {
		snapshot.errorCode = "EXTENSION_DISCONNECTED";
	}

	return snapshot;
}

async function navigateToRoute(routeKey, options = {}) {
	const frame = getElement("dashboard-frame");
	const route = DASHBOARD_ROUTES[routeKey] || DASHBOARD_ROUTES.operator;
	const token = ++navigationToken;
	let settled = false;
	let timeoutId = null;

	if (!frame) {
		setPortalState("error", "Dashboard iframe element is missing.");
		setLastAction("Error: dashboard iframe element is missing.");
		return;
	}

	setActiveButton(routeKey);
	setCurrentRoute(routeKey, route.url);
	recordClick(route.label, route.url);
	setRuntimeCopy("route-label", route.label);
	setRuntimeCopy("portal-url", route.url);
	setLastAction(`Checking local agent before launching: ${route.label}`);

	let snapshot = null;
	try {
		snapshot = await fetchRuntimeSnapshot();
	} catch (error) {
		snapshot = {
			capturedAt: new Date().toISOString(),
			status: null,
			health: null,
			errorCode: "LOCAL_AGENT_OFFLINE",
			errorMessage: error instanceof Error ? error.message : String(error),
		};
	}

	if (token !== navigationToken) {
		return;
	}

	if (!canEmbedDashboard(snapshot)) {
		renderUnavailableState(route, snapshot);
		return;
	}

	renderFrameLoadingState(route, snapshot);

	const markReady = () => {
		if (token !== navigationToken || settled) {
			return;
		}
		settled = true;
		if (timeoutId !== null) {
			window.clearTimeout(timeoutId);
		}
		renderReadyState(route, snapshot);
	};

	const markError = (message) => {
		if (token !== navigationToken || settled) {
			return;
		}
		settled = true;
		if (timeoutId !== null) {
			window.clearTimeout(timeoutId);
		}
		renderFrameErrorState(route, snapshot, message);
	};

	frame.onload = () => {
		window.setTimeout(markReady, 250);
	};

	frame.onerror = () => {
		markError(
			`Embedded dashboard failed to load. Confirm ${route.url} is reachable from the Flow Kit side panel.`,
		);
	};

	timeoutId = window.setTimeout(() => {
		markError(
			`Embedded dashboard timed out while loading ${route.url}. Use retry or open the route in a browser tab for direct inspection.`,
		);
	}, IFRAME_LOAD_TIMEOUT_MS);

	if (options.forceReload || frame.src !== route.url) {
		frame.src = route.url;
	}
	setIframeSrcCopy(route.url);
	setLastAction(`Iframe src updated: ${route.url}`);
}

function bootSidePortal() {
	setRuntimeCopy(
		"launcher-build-label",
		`Launcher build: ${LAUNCHER_BUILD_LABEL}`,
	);
	setRuntimeCopy("runtime-api-base", LOCAL_AGENT_BASE_URL);

	const buttons = document.querySelectorAll("[data-dashboard-route]");
	const frame = getElement("dashboard-frame");
	const openSelectedRouteButton = getElement("btn-open-selected-route");
	const retryButton = getElement("btn-retry-runtime");

	if (!frame) {
		setPortalState("error", "Dashboard iframe element is missing.");
		setLastAction("Error: dashboard iframe element is missing.");
		return;
	}

	if (!buttons.length) {
		setPortalState(
			"error",
			"No launcher buttons were found in the side panel.",
		);
		setLastAction("Error: no launcher buttons were found.");
		return;
	}

	if (!openSelectedRouteButton || !retryButton) {
		setPortalState("error", "Runtime controls are incomplete.");
		setLastAction("Error: runtime controls are incomplete.");
		return;
	}

	openSelectedRouteButton.addEventListener("click", () => {
		openRouteInBrowserTab(
			DASHBOARD_ROUTES[selectedRouteKey] || DASHBOARD_ROUTES.operator,
		);
	});

	retryButton.addEventListener("click", () => {
		setLastAction("Retry requested from side panel shell.");
		navigateToRoute(selectedRouteKey, { forceReload: true });
	});

	buttons.forEach((button) => {
		button.addEventListener("click", () => {
			const routeKey =
				button.getAttribute("data-dashboard-route") || "operator";
			navigateToRoute(routeKey, { forceReload: true });
		});
	});

	setLastAction(`Launcher bindings attached: ${buttons.length} buttons ready.`);
	setPanelState("loading");
	navigateToRoute("operator", { forceReload: true });
}

document.addEventListener("DOMContentLoaded", bootSidePortal);
