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
}

class FakeButton extends FakeElement {
	constructor(routeKey) {
		super();
		this.attributes["data-dashboard-route"] = routeKey;
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
}

const frame = new FakeFrame();
const portalUrl = new FakeElement("portal-url");
const portalTitle = new FakeElement("portal-title");
const routeLabel = new FakeElement("route-label");
const portalStatus = new FakeElement("portal-status");
const portalError = new FakeElement("portal-error");
const launcherBuildLabel = new FakeElement("launcher-build-label");
const runtimeStatusLabel = new FakeElement("runtime-status-label");
const currentRouteKey = new FakeElement("current-route-key");
const lastClickAt = new FakeElement("last-click-at");
const lastActionCopy = new FakeElement("last-action-copy");
const iframeSrcCopy = new FakeElement("iframe-src-copy");
const selectedRouteUrl = new FakeElement("selected-route-url");
const openSelectedRouteButton = new FakeButton("open-selected-route");
const buttons = [
	new FakeButton("operator"),
	new FakeButton("product"),
	new FakeButton("prompt"),
	new FakeButton("registry"),
];

const domContentLoaded = {};
const document = {
	body: new FakeElement("body"),
	getElementById(id) {
		return {
			"dashboard-frame": frame,
			"portal-url": portalUrl,
			"portal-title": portalTitle,
			"route-label": routeLabel,
			"portal-status": portalStatus,
			"portal-error": portalError,
			"launcher-build-label": launcherBuildLabel,
			"runtime-status-label": runtimeStatusLabel,
			"current-route-key": currentRouteKey,
			"last-click-at": lastClickAt,
			"last-action-copy": lastActionCopy,
			"iframe-src-copy": iframeSrcCopy,
			"selected-route-url": selectedRouteUrl,
			"btn-open-selected-route": openSelectedRouteButton,
		}[id] || null;
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
	chrome: {
		runtime: {
			lastError: null,
		},
		tabs: {
			create({ url }, callback) {
				tabCreates.push(url);
				if (callback) callback();
			},
		},
	},
});

const scriptPath = path.join(
	process.cwd(),
	"extension",
	"side_panel.js",
);
const code = fs.readFileSync(scriptPath, "utf8");
vm.runInContext(code, context, { filename: scriptPath });

if (!domContentLoaded.DOMContentLoaded) {
	throw new Error("DOMContentLoaded handler was not registered");
}

function flushTimers(delay) {
	const ready = [...timers.entries()].filter(([, timer]) => timer.delay === delay);
	for (const [id, timer] of ready) {
		timers.delete(id);
		timer.handler();
	}
}

function assert(condition, message) {
	if (!condition) {
		throw new Error(message);
	}
}

domContentLoaded.DOMContentLoaded();
assert(
	frame.src === "http://127.0.0.1:8100/operator?portal=side",
	"boot route should target operator dashboard",
);
assert(
	launcherBuildLabel.textContent === "Launcher build: PR25+route-hotfix",
	"build label should be visible after boot",
);
assert(
	currentRouteKey.textContent === "operator",
	"current route key should initialize to operator",
);
assert(
	iframeSrcCopy.textContent === "http://127.0.0.1:8100/operator?portal=side",
	"iframe src copy should initialize to operator URL",
);

frame.onload();
flushTimers(250);
assert(
	document.body.classList.contains("ready"),
	"ready class should be set after iframe load",
);
assert(
	portalStatus.textContent === "Operator Dashboard online.",
	"operator status should report online after iframe load",
);
assert(
	runtimeStatusLabel.textContent === "Dashboard status: online",
	"runtime status should report online after iframe load",
);

flushTimers(12000);
assert(
	document.body.classList.contains("ready"),
	"timeout must not override ready state after successful load",
);
assert(
	!document.body.classList.contains("error"),
	"timeout must not force error state after successful load",
);

const expectedRoutes = {
	operator: "http://127.0.0.1:8100/operator?portal=side",
	product: "http://127.0.0.1:8100/product-asset-generator",
	prompt: "http://127.0.0.1:8100/prompt-preview",
	registry: "http://127.0.0.1:8100/asset-registry",
};

for (const button of buttons) {
	button.click();
	assert(
		currentRouteKey.textContent === button.getAttribute("data-dashboard-route"),
		`current route key did not update for ${button.getAttribute("data-dashboard-route")}`,
	);
	assert(
		frame.src === expectedRoutes[button.getAttribute("data-dashboard-route")],
		`route click failed for ${button.getAttribute("data-dashboard-route")}`,
	);
	assert(
		iframeSrcCopy.textContent === expectedRoutes[button.getAttribute("data-dashboard-route")],
		`iframe src copy failed for ${button.getAttribute("data-dashboard-route")}`,
	);
	assert(
		lastActionCopy.textContent === `Iframe src updated: ${expectedRoutes[button.getAttribute("data-dashboard-route")]}`,
		`last action copy failed for ${button.getAttribute("data-dashboard-route")}`,
	);
	assert(lastClickAt.textContent !== "No click recorded", "last click timestamp was not updated");
}

openSelectedRouteButton.click();
assert(
	tabCreates.at(-1) === expectedRoutes.registry,
	"open selected route fallback should use the currently selected route",
);
assert(
	windowOpenCalls.length === 0,
	"window.open fallback should not be used when chrome.tabs.create exists",
);

console.log("PASS side_panel route wiring harness");
