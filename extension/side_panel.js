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

let navigationToken = 0;

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
		return;
	}

	const route = DASHBOARD_ROUTES[routeKey] || DASHBOARD_ROUTES.operator;
	const token = ++navigationToken;
	let settled = false;
	let timeoutId = null;

	setActiveButton(routeKey);

	if (urlEl) {
		urlEl.textContent = route.url;
	}
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
	setPortalState("loading", `Connecting to ${route.label}...`);
}

function bootSidePortal() {
	document.querySelectorAll("[data-dashboard-route]").forEach((button) => {
		button.addEventListener("click", () => {
			const routeKey =
				button.getAttribute("data-dashboard-route") || "operator";
			navigateToRoute(routeKey);
		});
	});

	navigateToRoute("operator");
}

document.addEventListener("DOMContentLoaded", bootSidePortal);
