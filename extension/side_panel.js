const DASHBOARD_ROUTES = {
	operator: {
		label: "Operator Dashboard",
		url: "http://127.0.0.1:8100/operator?portal=side",
	},
	product: {
		label: "Product Asset Generator",
		url: "http://127.0.0.1:8100/product-asset-generator",
	},
	prompt: {
		label: "Prompt Preview",
		url: "http://127.0.0.1:8100/prompt-preview",
	},
	registry: {
		label: "Asset Registry",
		url: "http://127.0.0.1:8100/asset-registry",
	},
};

const LAUNCHER_BUILD_LABEL = "PR25+route-hotfix";
let navigationToken = 0;
let selectedRouteKey = "operator";

function setPortalState(state, detail = "") {
	document.body.classList.toggle("ready", state === "ready");
	document.body.classList.toggle("error", state === "error");

	const statusEl = document.getElementById("portal-status");
	const errorEl = document.getElementById("portal-error");
	if (statusEl) {
		statusEl.textContent =
			detail ||
			(state === "ready"
				? "Dashboard online."
				: state === "error"
					? "Dashboard offline."
					: "Connecting to localhost dashboard...");
	}
	if (errorEl && state !== "error") {
		errorEl.textContent =
			"Dashboard iframe did not finish loading. Confirm the local agent is serving the selected BOSMAX dashboard route on http://127.0.0.1:8100.";
	}

	const runtimeStatusEl = document.getElementById("runtime-status-label");
	if (runtimeStatusEl) {
		runtimeStatusEl.textContent =
			state === "ready"
				? "Dashboard status: online"
				: state === "error"
					? "Dashboard status: offline"
					: "Dashboard status: loading";
	}
}

function setRuntimeCopy(id, value) {
	const element = document.getElementById(id);
	if (element) {
		element.textContent = value;
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
	setRuntimeCopy("last-click-at", `${stamp}`);
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

function navigateToRoute(routeKey) {
	const frame = document.getElementById("dashboard-frame");
	const urlEl = document.getElementById("portal-url");
	const titleEl = document.getElementById("portal-title");
	const routeLabelEl = document.getElementById("route-label");
	if (!frame) {
		setPortalState("error", "Dashboard iframe element is missing.");
		setLastAction("Error: dashboard iframe element is missing.");
		return;
	}

	const route = DASHBOARD_ROUTES[routeKey] || DASHBOARD_ROUTES.operator;
	const token = ++navigationToken;
	let settled = false;
	let timeoutId = null;

	setActiveButton(routeKey);
	setCurrentRoute(routeKey, route.url);
	recordClick(route.label, route.url);

	if (urlEl) {
		urlEl.textContent = route.url;
	}
	setIframeSrcCopy(route.url);
	if (titleEl) {
		titleEl.textContent = `Loading ${route.label.toLowerCase()}`;
	}
	if (routeLabelEl) {
		routeLabelEl.textContent = route.label;
	}

	const markReady = () => {
		if (token !== navigationToken || settled) return;
		settled = true;
		if (timeoutId !== null) {
			window.clearTimeout(timeoutId);
		}
		setLastAction(`Iframe loaded: ${route.label}`);
		setPortalState("ready", `${route.label} online.`);
	};

	const markError = (message) => {
		if (token !== navigationToken || settled) return;
		settled = true;
		if (timeoutId !== null) {
			window.clearTimeout(timeoutId);
		}
		const errorEl = document.getElementById("portal-error");
		if (errorEl && message) {
			errorEl.textContent = message;
		}
		setLastAction(`Iframe error: ${message || `${route.label} offline.`}`);
		setPortalState("error", message || `${route.label} offline.`);
	};

	frame.onload = () => {
		window.setTimeout(markReady, 250);
	};

	frame.onerror = () => {
		markError(
			`Dashboard iframe failed to load. Confirm the local agent and ${route.label} route are reachable.`,
		);
	};

	timeoutId = window.setTimeout(() => {
		if (token === navigationToken) {
			markError(
				`Dashboard load timed out. Confirm ${route.url} is live and allowed inside the extension side panel.`,
			);
		}
	}, 12000);

	frame.src = route.url;
	setIframeSrcCopy(frame.src);
	setLastAction(`Iframe src updated: ${route.url}`);
	setPortalState("loading", `Connecting to ${route.label}...`);
}

function bootSidePortal() {
	setRuntimeCopy(
		"launcher-build-label",
		`Launcher build: ${LAUNCHER_BUILD_LABEL}`,
	);

	const buttons = document.querySelectorAll("[data-dashboard-route]");
	const frame = document.getElementById("dashboard-frame");
	const openSelectedRouteButton = document.getElementById(
		"btn-open-selected-route",
	);

	if (!frame) {
		setPortalState("error", "Dashboard iframe element is missing.");
		setLastAction("Error: dashboard iframe element is missing.");
		return;
	}

	if (!buttons.length) {
		setPortalState("error", "No launcher buttons were found in the side panel.");
		setLastAction("Error: no launcher buttons were found.");
		return;
	}

	if (!openSelectedRouteButton) {
		setPortalState("error", "Open-route fallback control is missing.");
		setLastAction("Error: open-route fallback control is missing.");
		return;
	}

	openSelectedRouteButton.addEventListener("click", () => {
		openRouteInBrowserTab(
			DASHBOARD_ROUTES[selectedRouteKey] || DASHBOARD_ROUTES.operator,
		);
	});

	setLastAction(`Launcher bindings attached: ${buttons.length} buttons ready.`);

	buttons.forEach((button) => {
		button.addEventListener("click", () => {
			const routeKey =
				button.getAttribute("data-dashboard-route") || "operator";
			navigateToRoute(routeKey);
		});
	});

	navigateToRoute("operator");
}

document.addEventListener("DOMContentLoaded", bootSidePortal);
