#!/usr/bin/env node
/**
 * Harness — TikTok authenticated evidence relay (extension side).
 *
 * Two pieces are exercised against DETERMINISTIC fixtures, with no browser, no network and
 * no live TikTok page:
 *
 *   1. content-tiktok-evidence.js — the reader that runs inside the operator's already
 *      authenticated tab. The load-bearing assertions are the NEGATIVE ones: that the
 *      object it emits contains no cookie, no storage, no token and no unrelated page
 *      content, whatever the page around it contains. It runs inside a session where
 *      "read the page" and "read the account" are one keystroke apart, so the closed shape
 *      of its output IS the security control.
 *
 *   2. background.js tab routing — that a request for product A can never be answered by a
 *      tab showing product B, that a reply which does not echo the correlation id is
 *      refused, and that a replayed request id is served from cache instead of re-reading.
 *
 * The CAPTCHA assertion is a contract line, not a feature test: when the wall is up the
 * script must report it and stop. There must never be a solve path.
 *
 * Run: node scripts/test-tiktok-evidence-relay.js
 */
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");

const REPO_ROOT = join(__dirname, "..");
const CONTENT_SCRIPT = join(REPO_ROOT, "extension", "content-tiktok-evidence.js");
const BACKGROUND = join(REPO_ROOT, "extension", "background.js");
const MANIFEST = join(REPO_ROOT, "extension", "manifest.json");

let failures = 0;
function check(name, fn) {
	try {
		fn();
		console.log(`  ok   ${name}`);
	} catch (err) {
		failures += 1;
		console.error(`  FAIL ${name}\n       ${err.message}`);
	}
}
function assert(cond, msg) {
	if (!cond) throw new Error(msg);
}

const PRODUCT_URL = "https://shop.tiktok.com/view/product/1729543210987654321";

const LISTING_HTML = `<!doctype html><html><head>
<title>Minyak Warisan Cap Burung 25ml | TikTok Shop</title>
<link rel="canonical" href="${PRODUCT_URL}">
<meta property="og:title" content="Minyak Warisan Cap Burung 25ml">
<meta property="og:description" content="Minyak urut tradisional.">
<meta property="og:image" content="https://p16.tiktokcdn.com/img/og.jpg">
<script type="application/ld+json">
{"@type":"Product","name":"Minyak Warisan Cap Burung 25ml",
 "description":"Minyak urut tradisional. Bahan: minyak kelapa, halia, serai. Amaran: Elak kawasan mata.",
 "brand":{"name":"Cap Burung"},
 "image":["https://p16.tiktokcdn.com/img/minyak.jpg"],
 "offers":{"@type":"Offer","price":"18.90","priceCurrency":"MYR"}}
</script></head><body>
<nav class="nav-top">Kategori Jualan Akaun Saya operator@example.com Log Keluar</nav>
<header>TikTok Shop Malaysia</header>
<main class="product-detail-page">
  <h1>Minyak Warisan Cap Burung 25ml</h1>
  <div class="sku-list"><button>25ml</button><button>50ml</button></div>
  <div class="desc">Bahan: minyak kelapa, halia, serai. Amaran: Elak kawasan mata.</div>
</main>
<aside class="recommend-rail">Sabun Herba Ajaib 100g Bahan: sodium hidroksida</aside>
<footer class="footer-links">Terma Privasi</footer>
</body></html>`;

// TikTok's real interstitial: HTTP 200, a captcha loader, zero product data.
const SECURITY_WALL_HTML = `<!doctype html><html><head><title>Security Check</title>
<script src="https://sf16.ttwstatic.com/obj/oec-ttweb-captcha/loader/captcha/index.js"></script>
</head><body><div class="middle_page_loading"></div></body></html>`;

/**
 * Run the content script inside a real DOM with a stub chrome.runtime, then deliver one
 * acquisition message and capture the reply.
 */
function collectFrom(html, { url = PRODUCT_URL, evidenceRequestId = "req-1" } = {}) {
	const dom = new JSDOM(html, { url, runScripts: "outside-only" });
	const listeners = [];
	const sandbox = dom.getInternalVMContext();
	sandbox.chrome = {
		runtime: {
			id: "bosmax-extension-id",
			onMessage: { addListener: (fn) => listeners.push(fn) },
		},
	};
	// jsdom does not lay out boxes, so every element measures 0x0. Give images a real size
	// so the "skip icons and pixels" filter is exercised rather than trivially passing.
	sandbox.eval(`
		Object.defineProperty(HTMLImageElement.prototype, "getBoundingClientRect", {
			value() { return { width: 300, height: 300 }; },
		});
	`);
	vm.runInContext(readFileSync(CONTENT_SCRIPT, "utf8"), sandbox);
	assert(listeners.length === 1, "content script registered no message listener");

	let reply = null;
	listeners[0](
		{ type: "TIKTOK_COLLECT_PRODUCT_EVIDENCE", evidence_request_id: evidenceRequestId },
		{ id: "bosmax-extension-id" },
		(value) => {
			reply = value;
		},
	);
	assert(reply !== null, "content script never called sendResponse");
	return reply;
}

/** Load ONLY the relay helpers out of background.js — the file is a service worker. */
function loadBackgroundRelay() {
	const source = readFileSync(BACKGROUND, "utf8");
	const start = source.indexOf("const TIKTOK_EVIDENCE_TAB_QUERY");
	const end = source.indexOf("async function handleReloadExtension");
	assert(start > 0 && end > start, "TikTok relay block not found in background.js");
	// URL and Date are service-worker globals. Without them tiktokProductIdentity() throws
	// and returns null for EVERY url, which would make the routing checks below pass
	// vacuously — they would "prove" that no tab ever matches anything.
	const sandbox = { console, Date, URL };
	vm.createContext(sandbox);
	// `chrome` is declared up front so a test can swap in a stub; leaving it undefined
	// keeps the guard checks honest (reaching chrome at all would throw).
	vm.runInContext(`let chrome;\n${source.slice(start, end)}\nthis.__relay = {
		tiktokProductIdentity, tiktokIdentityMatches, readTikTokEvidenceReplay,
		rememberTikTokEvidenceReply, handleTikTokAcquireProductEvidence,
		__setChrome: (stub) => { chrome = stub; },
	};`, sandbox);
	return sandbox.__relay;
}

console.log("tiktok authenticated evidence relay");

// ── manifest reach ──────────────────────────────────────────────────────────
check("1. host access is exactly the two authorized TikTok Shop hosts", () => {
	const manifest = JSON.parse(readFileSync(MANIFEST, "utf8"));
	const tiktokHosts = manifest.host_permissions.filter((h) => h.includes("tiktok"));
	assert(
		JSON.stringify(tiktokHosts.sort()) ===
			JSON.stringify(["https://shop-my.tiktok.com/*", "https://shop.tiktok.com/*"]),
		`extension reach widened beyond the two authorized hosts: ${tiktokHosts}`,
	);
	const entry = manifest.content_scripts.find((cs) =>
		(cs.js || []).includes("content-tiktok-evidence.js"),
	);
	assert(entry, "content-tiktok-evidence.js is not declared in the manifest");
	assert(
		JSON.stringify(entry.matches.slice().sort()) ===
			JSON.stringify(["https://shop-my.tiktok.com/*", "https://shop.tiktok.com/*"]),
		`the evidence content script matches more than the two authorized hosts: ${entry.matches}`,
	);
	assert(entry.all_frames === false, "the evidence reader must be top-frame only");
});

// ── the security model ──────────────────────────────────────────────────────
check("2. the emitted object carries no credential or session material", () => {
	const reply = collectFrom(LISTING_HTML);
	assert(reply.ok === true, `expected a successful read, got ${reply.error}`);
	const allowed = new Set([
		"canonical_url", "title", "description", "brand", "price_text", "currency",
		"variant_labels", "images", "page_text", "evidence_methods",
	]);
	const extra = Object.keys(reply.evidence).filter((k) => !allowed.has(k));
	assert(extra.length === 0, `evidence carried unexpected keys: ${extra}`);
	const serialized = JSON.stringify(reply.evidence).toLowerCase();
	for (const banned of ["cookie", "sessionid", "localstorage", "sessionstorage",
		"authorization", "bearer", "mstoken"]) {
		assert(!serialized.includes(banned), `evidence leaked ${banned}`);
	}
});

check("3. the source file never references a credential or storage API", () => {
	// Stronger than inspecting one page's output: these APIs are simply absent, so no
	// future page shape can make them fire.
	const source = readFileSync(CONTENT_SCRIPT, "utf8");
	// Strip comments — the file DISCUSSES these APIs to explain why it avoids them.
	const code = source
		.replace(/\/\*[\s\S]*?\*\//g, "")
		.replace(/^\s*\/\/.*$/gm, "");
	for (const api of ["document.cookie", "localStorage", "sessionStorage",
		"indexedDB", "chrome.cookies"]) {
		assert(!code.includes(api), `content script references ${api}`);
	}
});

check("4. account chrome and neighbouring products are not transmitted", () => {
	const reply = collectFrom(LISTING_HTML);
	const text = reply.evidence.page_text;
	assert(!text.includes("operator@example.com"), "account identity was transmitted");
	assert(!text.includes("Log Keluar"), "navigation chrome was transmitted");
	// The recommendation rail carries ANOTHER product's ingredient list. Shipping it would
	// let the server's labelled-section parser attribute it to this product.
	assert(!text.includes("sodium hidroksida"),
		"a neighbouring product's ingredients were transmitted");
	assert(text.includes("minyak kelapa"), "this product's own evidence was lost");
});

check("5. only TikTok CDN images are collected", () => {
	const withAd = LISTING_HTML.replace(
		"<h1>",
		'<img src="https://ads.example.com/banner.jpg"><h1>',
	);
	const reply = collectFrom(withAd);
	assert(reply.evidence.images.length > 0, "no product image was collected");
	for (const url of reply.evidence.images) {
		assert(/tiktokcdn|byteimg|ibyteimg/.test(url), `third-party image collected: ${url}`);
	}
});

// ── the CAPTCHA contract ────────────────────────────────────────────────────
check("6. a live Security Check is reported and never solved", () => {
	const reply = collectFrom(SECURITY_WALL_HTML);
	assert(reply.ok === false, "the bot wall was parsed as a successful product read");
	assert(reply.error === "TIKTOK_SECURITY_CHECK_PRESENT",
		`expected TIKTOK_SECURITY_CHECK_PRESENT, got ${reply.error}`);
	assert(reply.evidence === undefined, "a walled page still emitted evidence");

	const code = readFileSync(CONTENT_SCRIPT, "utf8")
		.replace(/\/\*[\s\S]*?\*\//g, "")
		.replace(/^\s*\/\/.*$/gm, "");
	// No clicking, typing, dragging or form submission anywhere in the reader.
	for (const forbidden of [".click(", "dispatchEvent", "requestSubmit", "HTMLFormElement",
		"mousedown", "pointerdown"]) {
		assert(!code.includes(forbidden),
			`the reader contains interaction code (${forbidden}) — it must only read`);
	}
});

check("6b. a readable product page is NOT called walled just because the captcha SDK loaded", () => {
	// The first live pilot round failed here: TikTok ships the captcha loader on ordinary
	// product pages, so matching on <script src> reported SECURITY_CHECK_PRESENT for three
	// listings the operator had already cleared by hand and left open on screen.
	const withSdk = LISTING_HTML.replace(
		"</head>",
		'<script src="https://sf16.ttwstatic.com/obj/oec-ttweb-captcha/loader/captcha/index.js"></script>' +
			'<div id="captcha-verify-container" style="display:none"></div></head>',
	);
	const reply = collectFrom(withSdk);
	assert(reply.ok === true,
		`a readable listing was refused as walled: ${reply.error}`);
	assert(reply.evidence.title.includes("Minyak"), "evidence was lost");
});

check("6c. the wall still wins when the page states no product", () => {
	// The protection that must survive the fix above: a challenge shell carries no title
	// and no description, so it can never be reported as a successful empty product.
	const reply = collectFrom(SECURITY_WALL_HTML);
	assert(reply.ok === false && reply.error === "TIKTOK_SECURITY_CHECK_PRESENT",
		`expected the wall to be reported, got ${reply.error}`);
});

check("7. a page with no product facts reports empty rather than inventing", () => {
	const reply = collectFrom(
		'<!doctype html><html><head><title>TikTok Shop</title></head><body><main></main></body></html>',
	);
	assert(reply.ok === false, "an empty page reported a successful read");
	assert(reply.error === "TIKTOK_EVIDENCE_EMPTY", `unexpected error ${reply.error}`);
});

check("8. the correlation id is echoed verbatim", () => {
	const reply = collectFrom(LISTING_HTML, { evidenceRequestId: "abc-123-xyz" });
	assert(reply.evidence_request_id === "abc-123-xyz",
		"the reply cannot be tied back to the request that asked for it");
});

// ── background tab routing ──────────────────────────────────────────────────
check("9. a request for one product can never be answered by another product's tab", () => {
	const relay = loadBackgroundRelay();
	const wanted = relay.tiktokProductIdentity(PRODUCT_URL);
	assert(
		relay.tiktokIdentityMatches(
			wanted,
			relay.tiktokProductIdentity(`${PRODUCT_URL}?enter_from=mall&trace=x1`),
		),
		"a tracking query string broke the operator's own tab match",
	);
	assert(
		!relay.tiktokIdentityMatches(
			wanted,
			relay.tiktokProductIdentity("https://shop.tiktok.com/view/product/9999999999"),
		),
		"a DIFFERENT product's tab was accepted",
	);
	// TikTok's OWN redirect moves a product between the two authorized Shop hosts, so the
	// SAME product id must match across them — requiring one host rejected the operator's
	// own correct tab on the first live pilot round.
	assert(
		relay.tiktokIdentityMatches(
			relay.tiktokProductIdentity(
				"https://shop-my.tiktok.com/pdp/1733784168157316566?source=product_detail",
			),
			relay.tiktokProductIdentity(
				"https://shop.tiktok.com/view/product/1733784168157316566?region=MY",
			),
		),
		"the same product did not match across the two authorized hosts",
	);
	// ...but a DIFFERENT product still never matches, on either host.
	assert(
		!relay.tiktokIdentityMatches(
			relay.tiktokProductIdentity("https://shop-my.tiktok.com/pdp/1733784168157316566"),
			relay.tiktokProductIdentity("https://shop.tiktok.com/view/product/1729547196228863761"),
		),
		"a different product matched across hosts",
	);
	assert(relay.tiktokProductIdentity("https://www.tiktok.com/@someone") === null,
		"a non-Shop TikTok URL was treated as a product");
	assert(relay.tiktokProductIdentity("http://shop.tiktok.com/view/product/1") === null,
		"an insecure URL was accepted");
});

check("10. a replayed request id is served from cache, not re-read", () => {
	const relay = loadBackgroundRelay();
	relay.rememberTikTokEvidenceReply("dup-1", { ok: true, evidence: { title: "X" } });
	const cached = relay.readTikTokEvidenceReplay("dup-1");
	assert(cached && cached.ok === true, "a replayed request id was not cached");
	assert(relay.readTikTokEvidenceReplay("never-sent") === null,
		"an unknown request id returned a cached answer");
});

check("11. a missing correlation id is refused before any tab is touched", async () => {
	const relay = loadBackgroundRelay();
	// No chrome stub is installed: reaching chrome.tabs would throw, which is itself the
	// proof that the guard runs first.
	const result = relay.handleTikTokAcquireProductEvidence({ product_url: PRODUCT_URL });
	return result.then((reply) => {
		assert(reply.ok === false && reply.error === "TIKTOK_EVIDENCE_REQUEST_ID_MISSING",
			`expected TIKTOK_EVIDENCE_REQUEST_ID_MISSING, got ${JSON.stringify(reply)}`);
	});
});

check("12b. a permission-blind extension says so instead of 'no tab open'", async () => {
	const relay = loadBackgroundRelay();
	// Chrome reports the two TikTok origins as NOT granted. Every tab.url would come back
	// undefined, so the url-filtered query would match nothing and look exactly like an
	// empty browser — the conflation that cost a live pilot round.
	relay.__setChrome({
		permissions: { contains: async () => false },
		tabs: {
			query: async () => {
				throw new Error("tabs.query must not run when the host is not granted");
			},
		},
	});
	const reply = await relay.handleTikTokAcquireProductEvidence({
		evidence_request_id: "req-perm",
		product_url: PRODUCT_URL,
	});
	assert(reply.error === "TIKTOK_HOST_PERMISSION_MISSING",
		`expected TIKTOK_HOST_PERMISSION_MISSING, got ${JSON.stringify(reply)}`);
});

check("12c. a genuinely empty browser reports counts, never a tab inventory", async () => {
	const relay = loadBackgroundRelay();
	relay.__setChrome({
		permissions: { contains: async () => true },
		tabs: {
			query: async (q) =>
				q && q.url
					? []
					: [
							{ id: 1, url: "https://labs.google/fx/tools/flow" },
							{ id: 2, url: "https://mail.google.com/inbox" },
							{ id: 3 },
						],
		},
	});
	const reply = await relay.handleTikTokAcquireProductEvidence({
		evidence_request_id: "req-empty",
		product_url: PRODUCT_URL,
	});
	assert(reply.error === "TIKTOK_NO_MATCHING_TAB", `unexpected ${reply.error}`);
	assert(reply.total_tabs === 3, `total_tabs should be 3, got ${reply.total_tabs}`);
	assert(reply.tabs_with_readable_url === 2,
		`tabs_with_readable_url should be 2, got ${reply.tabs_with_readable_url}`);
	// The operator's other tabs must never travel to the backend.
	const serialized = JSON.stringify(reply);
	assert(!serialized.includes("mail.google.com") && !serialized.includes("labs.google"),
		"the reply leaked the operator's other tab URLs");
});

check("12. an unsupported host is refused before any tab is touched", async () => {
	const relay = loadBackgroundRelay();
	const result = relay.handleTikTokAcquireProductEvidence({
		evidence_request_id: "req-host",
		product_url: "https://www.tiktok.com/@someone/video/1",
	});
	return result.then((reply) => {
		assert(reply.ok === false && reply.error === "TIKTOK_PRODUCT_URL_INVALID",
			`expected TIKTOK_PRODUCT_URL_INVALID, got ${JSON.stringify(reply)}`);
	});
});

// Async checks resolve after the synchronous run; give them a tick before reporting.
setTimeout(() => {
	if (failures) {
		console.error(`\n${failures} check(s) FAILED`);
		process.exit(1);
	}
	console.log("\nall checks passed");
}, 50);
