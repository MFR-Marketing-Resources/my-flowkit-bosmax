import { createServer } from "node:http";
import { chromium } from "playwright";

const BASE_URL =
	process.env.PRODUCT_DATA_NETWORK_BASE_URL || "http://127.0.0.1:8100";
const LIVE_TIMEOUT_MS = Number(
	process.env.PRODUCT_DATA_NETWORK_TIMEOUT_MS || 60_000,
);
const MAX_PRODUCT_RESPONSE_BYTES = 3_000_000;

const FIXTURE_HTML = String.raw`<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>Product data loading contract fixture</title></head>
  <body>
    <main>
      <h1>Product data loading contract fixture</h1>
      <button data-testid="selector-page">Load selector</button>
      <button data-testid="selector-page-again">Load selector again</button>
      <button data-testid="selector-search">Search selector</button>
      <button data-testid="smart-page">Load Smart Registration</button>
      <button data-testid="smart-next">Load Smart Registration page 2</button>
      <button data-testid="smart-search">Search Smart Registration</button>
      <button data-testid="smart-review">Open review drafts</button>
      <button data-testid="pi-page">Load Product Intelligence</button>
      <button data-testid="detail-page">Load exact detail</button>
      <button data-testid="p6-page">Load P6 cohort</button>
      <button data-testid="p6-search">Search P6 cohort</button>
      <button data-testid="p6-next">Load P6 cohort page 2</button>
      <button data-testid="mutate">Commit fixture mutation</button>
      <output data-testid="fixture-state"></output>
    </main>
    <script>
      const selectorCache = new Map();
      const registryCache = new Map();
      const cohortCache = new Map();

      async function read(path, options) {
        const response = await fetch(path, options);
        if (!response.ok) throw new Error("fixture request failed: " + response.status);
        return response.json();
      }

      async function selector() {
        const key = "GENERATION:50";
        if (!selectorCache.has(key)) {
          selectorCache.set(key, read("/api/products?limit=50&offset=0&purpose=GENERATION"));
        }
        return selectorCache.get(key);
      }

      async function selectorSearch() {
        return read("/api/products/search?q=outside&limit=25&offset=0&purpose=GENERATION");
      }

      async function registry(query = "", offset = 0, limit = 50) {
        const key = query + ":" + offset + ":" + limit;
        if (!registryCache.has(key)) {
          const q = query ? "&q=" + encodeURIComponent(query) : "";
          registryCache.set(
            key,
            read("/api/products?view=REGISTRY&limit=" + limit + "&offset=" + offset + q),
          );
        }
        return registryCache.get(key);
      }

      async function cohort(query = "", offset = 0) {
        const key = query + ":" + offset;
        if (!cohortCache.has(key)) {
          const q = query ? "&q=" + encodeURIComponent(query) : "";
          cohortCache.set(
            key,
            read("/api/creative-production/cohort-authority?limit=50&offset=" + offset + q),
          );
        }
        return cohortCache.get(key);
      }

      async function run(action, operation) {
        await operation();
        document.body.dataset.lastAction = action;
        document.querySelector('[data-testid="fixture-state"]').textContent = action;
      }

      document.querySelector('[data-testid="selector-page"]').onclick = () => void run("selector", selector);
      document.querySelector('[data-testid="selector-page-again"]').onclick = () => void run("selector-again", selector);
      document.querySelector('[data-testid="selector-search"]').onclick = () => void run("selector-search", selectorSearch);
      document.querySelector('[data-testid="smart-page"]').onclick = () => void run("smart-page", () => registry());
      document.querySelector('[data-testid="smart-next"]').onclick = () => void run("smart-next", () => registry("", 50));
      document.querySelector('[data-testid="smart-search"]').onclick = () => void run("smart-search", () => registry("outside"));
      document.querySelector('[data-testid="smart-review"]').onclick = () => void run("smart-review", () => read("/api/product-registration/review-drafts?limit=10&offset=0"));
      document.querySelector('[data-testid="pi-page"]').onclick = () => void run("pi-page", () => registry("", 0, 20));
      document.querySelector('[data-testid="detail-page"]').onclick = () => void run("detail", () => read("/api/products/product-1"));
      document.querySelector('[data-testid="p6-page"]').onclick = () => void run("p6-page", () => cohort());
      document.querySelector('[data-testid="p6-search"]').onclick = () => void run("p6-search", () => cohort("outside"));
      document.querySelector('[data-testid="p6-next"]').onclick = () => void run("p6-next", () => cohort("", 50));
      document.querySelector('[data-testid="mutate"]').onclick = () => void run("mutated", async () => {
        await read("/api/products/mutation-fixture", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ id: "product-1", operation: "fixture-mutation" }),
        });
        selectorCache.clear();
        registryCache.clear();
        cohortCache.clear();
      });
    </script>
  </body>
</html>`;

function jsonResponse(response, body, status = 200) {
	const payload = JSON.stringify(body);
	response.writeHead(status, {
		"content-type": "application/json; charset=utf-8",
		"cache-control": "no-store",
		"content-length": Buffer.byteLength(payload),
	});
	response.end(payload);
}

function fixtureProduct(id = "product-1") {
	return {
		id,
		raw_product_title: "Outside Product",
		product_display_name: "Outside Product",
		product_short_name: "Outside Product",
		source: "MANUAL",
		lifecycle_status: "ACTIVE",
		image_url: "",
		image_readiness_status: "IMAGE_URL_MISSING",
	};
}

async function readRequestBody(request) {
	const chunks = [];
	for await (const chunk of request) chunks.push(chunk);
	return Buffer.concat(chunks).toString("utf8");
}

function startFixtureServer() {
	const server = createServer(async (request, response) => {
		const requestUrl = new URL(request.url || "/", "http://127.0.0.1");
		if (requestUrl.pathname === "/fixture.html") {
			response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
			response.end(FIXTURE_HTML);
			return;
		}
		if (!requestUrl.pathname.startsWith("/api/")) {
			response.writeHead(404);
			response.end("not found");
			return;
		}

		if (requestUrl.pathname === "/api/products/mutation-fixture") {
			await readRequestBody(request);
			jsonResponse(response, { status: "ok" });
			return;
		}
		if (requestUrl.pathname === "/api/products/search") {
			jsonResponse(response, {
				items: [fixtureProduct("product-search")],
				total_count: 1,
				returned_count: 1,
				has_pagination: false,
				limit: Number(requestUrl.searchParams.get("limit") || 25),
				offset: Number(requestUrl.searchParams.get("offset") || 0),
			});
			return;
		}
		if (requestUrl.pathname === "/api/products/product-1") {
			jsonResponse(response, fixtureProduct());
			return;
		}
		if (requestUrl.pathname === "/api/products") {
			const limit = Number(requestUrl.searchParams.get("limit") || 50);
			const offset = Number(requestUrl.searchParams.get("offset") || 0);
			jsonResponse(response, {
				items: [fixtureProduct(offset ? "product-page-2" : "product-1")],
				total_count: 101,
				returned_count: 1,
				has_pagination: true,
				limit,
				offset,
				facets: {},
			});
			return;
		}
		if (requestUrl.pathname === "/api/creative-production/cohort-authority") {
			const limit = Number(requestUrl.searchParams.get("limit") || 50);
			const offset = Number(requestUrl.searchParams.get("offset") || 0);
			jsonResponse(response, {
				cohort_count: 581,
				cohort_sha256: "a".repeat(64),
				product_ids: ["product-1", "product-page-2"],
				products: [fixtureProduct(offset ? "product-page-2" : "product-1")],
				matches_frozen_authority: true,
				total_count: 101,
				returned_count: 1,
				has_pagination: true,
				limit,
				offset,
			});
			return;
		}
		if (requestUrl.pathname === "/api/product-registration/review-drafts") {
			jsonResponse(response, []);
			return;
		}
		jsonResponse(response, {});
	});

	return new Promise((resolve) => {
		server.listen(0, "127.0.0.1", () => {
			const address = server.address();
			if (!address || typeof address === "string") {
				throw new Error("fixture server did not expose a TCP port");
			}
			resolve({ server, url: `http://127.0.0.1:${address.port}` });
		});
	});
}

function isApiUrl(rawUrl) {
	try {
		return new URL(rawUrl).pathname.startsWith("/api/");
	} catch {
		return false;
	}
}

function attachCapture(page) {
	const requests = [];
	const responses = [];
	const responseTasks = [];
	const startedAt = new Map();

	page.on("request", (request) => {
		if (!isApiUrl(request.url())) return;
		startedAt.set(request, Date.now());
		requests.push({
			method: request.method(),
			url: request.url(),
			postData: request.postData() || null,
			startedAt: Date.now(),
		});
	});
	page.on("response", (response) => {
		if (!isApiUrl(response.url())) return;
		responseTasks.push(
			(async () => {
				let bytes = 0;
				try {
					bytes = (await response.body()).byteLength;
				} catch {
					// A response can disappear during a navigation; status/URL remain useful.
				}
				responses.push({
					method: response.request().method(),
					url: response.url(),
					status: response.status(),
					bytes,
					durationMs: Date.now() - (startedAt.get(response.request()) || Date.now()),
				});
			})(),
		);
	});

	return {
		requests,
		responses,
		async settle() {
			await Promise.all(responseTasks);
		},
	};
}

function assert(condition, message) {
	if (!condition) throw new Error(`PRODUCT_DATA_NETWORK_CONTRACT_FAILED: ${message}`);
}

function parseRequest(record) {
	return new URL(record.url);
}

function isGenerationOrProviderExecutionPath(pathname) {
	return (
		/^\/api\/(?:generate|provider)(?:\/|$)/i.test(pathname) ||
		/^\/api\/flow\/(?:generate|execute-flow-job|video-jobs|native-extend)(?:\/|$)/i.test(pathname) ||
		/^\/api\/bulk-generation(?:\/|$)/i.test(pathname)
	);
}

function assertRequestContracts(capture) {
	for (const request of capture.requests) {
		const parsed = parseRequest(request);
		const { pathname, searchParams } = parsed;
		if (request.method === "GET" && pathname === "/api/products") {
			assert(searchParams.has("limit"), `${request.url} is missing limit`);
			assert(searchParams.has("offset"), `${request.url} is missing offset`);
			assert(Number(searchParams.get("limit")) <= 100, `${request.url} exceeds page bound`);
		}
		if (request.method === "GET" && pathname === "/api/products/search") {
			assert(searchParams.has("q"), `${request.url} is missing search query`);
			assert(searchParams.get("offset") === "0", `${request.url} must start at offset 0`);
			assert(Number(searchParams.get("limit")) <= 100, `${request.url} exceeds search bound`);
		}
		if (request.method === "GET" && pathname === "/api/creative-production/cohort-authority") {
			assert(searchParams.has("limit"), `${request.url} is missing cohort limit`);
			assert(searchParams.has("offset"), `${request.url} is missing cohort offset`);
			assert(Number(searchParams.get("limit")) <= 100, `${request.url} exceeds cohort bound`);
		}
		if (request.method === "GET" && pathname === "/api/product-registration/review-drafts") {
			assert(Number(searchParams.get("limit") || 0) <= 100, `${request.url} exceeds draft bound`);
		}
		assert(!isGenerationOrProviderExecutionPath(pathname), `provider/generation call observed: ${request.url}`);
	}
	for (const response of capture.responses) {
		assert(response.status >= 200 && response.status < 300, `${response.status} for ${response.url}`);
		assert(response.bytes <= MAX_PRODUCT_RESPONSE_BYTES, `${response.url} response is ${response.bytes} bytes`);
	}
}

async function clickAction(page, testId, action) {
	const startedAt = Date.now();
	await page.getByTestId(testId).click();
	await page.waitForFunction(
		(expected) => document.body.dataset.lastAction === expected,
		action,
		{ timeout: 10_000 },
	);
	return Date.now() - startedAt;
}

async function runAndAwaitLiveResponse(page, action, matches, description) {
	const responsePromise = page.waitForResponse(
		(response) => {
			if (!matches(response)) return false;
			return response.status() >= 200 && response.status() < 300;
		},
		{ timeout: LIVE_TIMEOUT_MS },
	);
	await action();
	const response = await responsePromise;
	assert(response.ok(), `${description} returned ${response.status()}`);
}

function responseObservations(capture) {
	const byPath = new Map();
	for (const response of capture.responses) {
		const path = new URL(response.url).pathname;
		const current = byPath.get(path) || {
			requestCount: 0,
			maxPayloadBytes: 0,
			maxDurationMs: 0,
		};
		current.requestCount += 1;
		current.maxPayloadBytes = Math.max(current.maxPayloadBytes, response.bytes);
		current.maxDurationMs = Math.max(current.maxDurationMs, response.durationMs);
		byPath.set(path, current);
	}
	return Object.fromEntries(byPath);
}

async function runFixture() {
	const fixture = await startFixtureServer();
	const browser = await chromium.launch({ headless: true });
	try {
		const page = await browser.newPage();
		const capture = attachCapture(page);
		await page.goto(`${fixture.url}/fixture.html`, { waitUntil: "domcontentloaded" });

		await clickAction(page, "selector-page", "selector");
		await clickAction(page, "selector-search", "selector-search");
		await clickAction(page, "smart-page", "smart-page");
		await clickAction(page, "smart-next", "smart-next");
		await clickAction(page, "smart-page", "smart-page");
		await clickAction(page, "smart-search", "smart-search");
		await clickAction(page, "pi-page", "pi-page");
		await clickAction(page, "detail-page", "detail");
		await clickAction(page, "p6-page", "p6-page");
		await clickAction(page, "p6-search", "p6-search");
		await clickAction(page, "p6-next", "p6-next");
		await clickAction(page, "p6-page", "p6-page");
		await clickAction(page, "selector-page-again", "selector-again");

		const reviewBeforeOpen = capture.requests.filter(
			(request) => new URL(request.url).pathname === "/api/product-registration/review-drafts",
		).length;
		assert(reviewBeforeOpen === 0, "review drafts loaded before explicit workflow open");
		await clickAction(page, "smart-review", "smart-review");

		await clickAction(page, "mutate", "mutated");
		await clickAction(page, "selector-page", "selector");
		await capture.settle();

		const byPath = (path) => capture.requests.filter((request) => new URL(request.url).pathname === path);
		const selectorRequests = capture.requests.filter((request) => {
			const parsed = new URL(request.url);
			return parsed.pathname === "/api/products" && parsed.searchParams.get("purpose") === "GENERATION";
		});
		const registryRequests = capture.requests.filter((request) => {
			const parsed = new URL(request.url);
			return parsed.pathname === "/api/products" && parsed.searchParams.get("view") === "REGISTRY";
		});
		const cohortRequests = byPath("/api/creative-production/cohort-authority");
		assert(selectorRequests.length === 2, `selector cache/mutation sequence expected 2 requests, got ${selectorRequests.length}`);
		assert(byPath("/api/products/search").length === 1, "selector search expected exactly one request");
		assert(registryRequests.length === 4, `registry page/search/PI sequence expected 4 requests, got ${registryRequests.length}`);
		assert(
			registryRequests.filter((request) => {
				const parsed = new URL(request.url);
				return parsed.searchParams.get("limit") === "50" && parsed.searchParams.get("offset") === "0" && !parsed.searchParams.has("q");
			}).length === 1,
			"Smart Registration page 1 should be reused after page 2",
		);
		assert(
			registryRequests.filter((request) => {
				const parsed = new URL(request.url);
				return parsed.searchParams.get("limit") === "50" && parsed.searchParams.get("offset") === "50";
			}).length === 1,
			"Smart Registration page 2 should be requested once",
		);
		assert(cohortRequests.length === 3, `P6 page/search/pagination expected 3 requests, got ${cohortRequests.length}`);
		assert(
			cohortRequests.filter((request) => {
				const parsed = new URL(request.url);
				return parsed.searchParams.get("offset") === "0" && !parsed.searchParams.has("q");
			}).length === 1,
			"P6 page 1 should be reused after pagination",
		);
		assert(byPath("/api/products/product-1").length === 1, "exact detail expected exactly one request");
		assert(byPath("/api/product-registration/review-drafts").length === 1, "review drafts expected one explicit-open request");
		assert(capture.requests.filter((request) => new URL(request.url).pathname.endsWith("/image")).length === 0, "fixture selector flows must not fan out image requests");
		assert(capture.requests.filter((request) => request.method === "POST" && new URL(request.url).pathname === "/api/products/mutation-fixture").length === 1, "mutation expected exactly one POST");
		const mutation = capture.requests.find((request) => new URL(request.url).pathname === "/api/products/mutation-fixture");
		assert(mutation?.postData?.includes('"operation":"fixture-mutation"'), "mutation payload is not deterministic");

		assertRequestContracts(capture);
		return {
			mode: "fixture",
			requestCount: capture.requests.length,
			responseCount: capture.responses.length,
			maxResponseBytes: Math.max(...capture.responses.map((response) => response.bytes), 0),
			maxObservedDurationMs: Math.max(...capture.responses.map((response) => response.durationMs), 0),
			observations: responseObservations(capture),
		};
	} finally {
		await browser.close();
		await new Promise((resolve, reject) => fixture.server.close((error) => (error ? reject(error) : resolve())));
	}
}

async function runLive() {
	const browser = await chromium.launch({ headless: process.env.PRODUCT_DATA_NETWORK_HEADED !== "1" });
	try {
		const page = await browser.newPage();
		const capture = attachCapture(page);

		await page.goto(`${BASE_URL}/operator/hybrid`, {
			waitUntil: "domcontentloaded",
			timeout: LIVE_TIMEOUT_MS,
		});
		await page.getByRole("button", { name: /Search and select product/i }).waitFor({ timeout: LIVE_TIMEOUT_MS });
		await page.getByRole("button", { name: /Search and select product/i }).click();
		const selectorSearch = page.locator('input[placeholder="Search all products by name..."]');
		await runAndAwaitLiveResponse(
			page,
			() => selectorSearch.fill("outside"),
			(response) => new URL(response.url()).pathname === "/api/products/search",
			"selector search",
		);

		await page.goto(`${BASE_URL}/product-registration`, {
			waitUntil: "domcontentloaded",
			timeout: LIVE_TIMEOUT_MS,
		});
		await page.getByTestId("product-registry-table").waitFor({ timeout: LIVE_TIMEOUT_MS });
		const allSearch = page.locator('input[placeholder="product title…"]');
		await runAndAwaitLiveResponse(
			page,
			() => allSearch.fill("outside"),
			(response) => {
				const url = new URL(response.url());
				return (
					url.pathname === "/api/products" &&
					url.searchParams.get("view") === "REGISTRY" &&
					url.searchParams.get("q") === "outside"
				);
			},
			"Smart Registration search",
		);
		const firstRow = page.locator('[data-testid="product-registry-table"] tbody tr').first();
		if (await firstRow.count()) {
			await firstRow.click();
			await page.waitForURL("**/product/**", { timeout: LIVE_TIMEOUT_MS });
		}

		await page.goto(`${BASE_URL}/products`, {
			waitUntil: "domcontentloaded",
			timeout: LIVE_TIMEOUT_MS,
		});
		await page.waitForTimeout(1_000);
		const lazyDrafts = page.getByTestId("product-intelligence-review-drafts-lazy");
		if (await lazyDrafts.count()) {
			await lazyDrafts.locator("summary").click();
			await page.waitForTimeout(1_000);
		}

		await page.goto(`${BASE_URL}/production-studio`, {
			waitUntil: "domcontentloaded",
			timeout: LIVE_TIMEOUT_MS,
		});
		const advanced = page.getByTestId("p6-open-advanced-workspace");
		if (await advanced.count()) await advanced.click();
		const p6Picker = page.getByTestId("p6-product-picker");
		await p6Picker.waitFor({ timeout: LIVE_TIMEOUT_MS });
		await p6Picker.locator("button").first().click();
		const p6Search = page.getByLabel("Search governed products");
		await p6Search.waitFor({ timeout: LIVE_TIMEOUT_MS });
		await runAndAwaitLiveResponse(
			page,
			() => p6Search.fill("outside"),
			(response) => {
				const url = new URL(response.url());
				return (
					url.pathname === "/api/creative-production/cohort-authority" &&
					url.searchParams.get("q") === "outside"
				);
			},
			"P6 cohort search",
		);
		const next = page.getByRole("button", { name: "Next" });
		if (await next.count() && await next.isEnabled()) await next.click();
		await page.waitForTimeout(1_000);

		await capture.settle();
		assertRequestContracts(capture);
		const paths = new Set(capture.requests.map((request) => new URL(request.url).pathname));
		assert([...paths].some((path) => path === "/api/products"), "live registry/catalog list was not observed");
		assert([...paths].some((path) => path === "/api/products/search"), "live selector search was not observed");
		assert([...paths].some((path) => path === "/api/creative-production/cohort-authority"), "live P6 authority was not observed");
		return {
			mode: "live",
			baseUrl: BASE_URL,
			requestCount: capture.requests.length,
			responseCount: capture.responses.length,
			maxResponseBytes: Math.max(...capture.responses.map((response) => response.bytes), 0),
			maxObservedDurationMs: Math.max(...capture.responses.map((response) => response.durationMs), 0),
			observations: responseObservations(capture),
		};
	} finally {
		await browser.close();
	}
}

const fixtureMode = process.argv.includes("--fixture") || process.env.PRODUCT_DATA_NETWORK_FIXTURE === "1";
try {
	const report = fixtureMode ? await runFixture() : await runLive();
	console.log(JSON.stringify({ status: "PASS", ...report }, null, 2));
} catch (error) {
	console.error(error instanceof Error ? error.stack || error.message : String(error));
	process.exitCode = 1;
}
