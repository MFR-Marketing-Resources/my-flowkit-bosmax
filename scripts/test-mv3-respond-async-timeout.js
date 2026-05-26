/**
 * test-mv3-respond-async-timeout.js
 *
 * Static + behavioural contract test for the MV3 message-port lifecycle fix.
 *
 * Verifies that the `respondAsync` helper in each of the three extension
 * scripts (background.js, content-flow-dom.js, content.js):
 *   1. Settles the sendResponse callback with the resolved payload when the
 *      task completes within the timeout.
 *   2. Settles with `{ ok: false, error: <message> }` when the task rejects.
 *   3. Settles with a structured timeout error
 *      (`ERR_BACKGROUND_ASYNC_RESPONSE_TIMEOUT` for background.js,
 *       `ERR_CONTENT_ASYNC_RESPONSE_TIMEOUT` for content scripts) when the
 *      task hangs past the timeout.
 *   4. Never invokes sendResponse twice (double-settle protected) even when a
 *      late resolution arrives after the timeout has fired.
 *
 * The test extracts each `respondAsync` body verbatim from the on-disk source
 * (no rewrites, no mocking the underlying logic) and exercises it inside a
 * fresh vm context. This proves the contract against the actual shipped code
 * and will fail loudly if a future edit drops the timeout or the double-settle
 * guard.
 *
 * Run: `node scripts/test-mv3-respond-async-timeout.js`
 *
 * Authority: AGENTS.md → CHROME_EXTENSION_MV3_DEBUG_CONTRACT.md
 */

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const EXT_DIR = path.resolve(__dirname, "..", "extension");

function assert(condition, message) {
	if (!condition) {
		throw new Error(`ASSERTION_FAILED: ${message}`);
	}
}

function sleep(ms) {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Pulls the `respondAsync` function definition out of a given extension source
 * file by string matching. The function is defined at the top level of each
 * file and starts with the literal `function respondAsync(`.
 */
function extractRespondAsyncSource(filePath) {
	const source = fs.readFileSync(filePath, "utf8");
	const startIdx = source.indexOf("function respondAsync(");
	assert(startIdx >= 0, `respondAsync not found in ${filePath}`);

	// We also need the DEFAULT_*_TIMEOUT_MS constants declared immediately
	// above respondAsync — they are required by the function default arg.
	// Walk backwards from startIdx to find the preceding `const DEFAULT_`
	// block (it lives on the same scope just above the function).
	const constMarker = "const DEFAULT_";
	let constStart = source.lastIndexOf(constMarker, startIdx);
	assert(
		constStart >= 0 && constStart < startIdx,
		`expected DEFAULT_*_TIMEOUT_MS constant above respondAsync in ${filePath}`,
	);

	// Find the matching closing brace of the function body using a simple
	// depth counter on `{` / `}` starting at the first `{` after startIdx.
	const firstBrace = source.indexOf("{", startIdx);
	assert(firstBrace > 0, `function body brace not found in ${filePath}`);
	let depth = 0;
	let endIdx = -1;
	for (let i = firstBrace; i < source.length; i++) {
		const ch = source[i];
		if (ch === "{") depth += 1;
		else if (ch === "}") {
			depth -= 1;
			if (depth === 0) {
				endIdx = i;
				break;
			}
		}
	}
	assert(endIdx > firstBrace, `unbalanced braces in ${filePath} respondAsync`);

	return source.slice(constStart, endIdx + 1);
}

/**
 * Load `respondAsync` into an isolated vm sandbox so it does not collide
 * with Node's globals or other test cases.
 *
 * background.js's respondAsync calls a sibling helper `respondOnce(reply,
 * payload)`. We stub that minimally in the sandbox so the extracted function
 * runs end-to-end without dragging in the rest of background.js.
 */
function loadRespondAsync(filePath) {
	const fnSource = extractRespondAsyncSource(filePath);
	const sandbox = {
		setTimeout,
		clearTimeout,
		console,
		Promise,
		// Stub matches the real respondOnce contract in background.js — only
		// invoke the reply if callable, swallow any callback errors.
		respondOnce(reply, payload) {
			if (typeof reply !== "function") return;
			try {
				reply(payload);
			} catch (_) {}
		},
	};
	vm.createContext(sandbox);
	vm.runInContext(`${fnSource}\nthis.__respondAsync = respondAsync;`, sandbox);
	return sandbox.__respondAsync;
}

/**
 * Run a single scenario against a respondAsync and assert the captured
 * sendResponse payload matches expectations.
 */
async function runScenario(name, respondAsync, taskFactory, expect, opts = {}) {
	let captured = null;
	let captureCount = 0;
	const sendResponse = (payload) => {
		captureCount += 1;
		captured = payload;
	};

	const returnValue = respondAsync(sendResponse, taskFactory, opts.timeoutMs);
	assert(returnValue === true, `${name}: respondAsync must return literal true`);

	// Wait for the maximum of: the scenario's expected settle time, or
	// the timeout + a small margin. 50ms slack covers task scheduling jitter.
	const waitMs = opts.waitMs ?? Math.max((opts.timeoutMs || 100) + 50, 100);
	await sleep(waitMs);

	assert(
		captured !== null,
		`${name}: sendResponse was never invoked within ${waitMs}ms`,
	);
	assert(
		captureCount === 1,
		`${name}: sendResponse was invoked ${captureCount} times (must be exactly 1)`,
	);

	for (const [key, expectedValue] of Object.entries(expect)) {
		assert(
			captured[key] === expectedValue,
			`${name}: captured.${key} = ${JSON.stringify(captured[key])} (expected ${JSON.stringify(expectedValue)})`,
		);
	}

	// Wait additional 100ms to confirm no second settle slips through after
	// timeout has already fired.
	await sleep(100);
	assert(
		captureCount === 1,
		`${name}: late settle leaked through — sendResponse called ${captureCount} times after grace`,
	);
}

async function testBackgroundRespondAsync() {
	const respondAsync = loadRespondAsync(path.join(EXT_DIR, "background.js"));

	// 1. Resolved task within timeout
	await runScenario(
		"background.resolved",
		respondAsync,
		async () => ({ ok: true, result: "test-payload" }),
		{ ok: true, result: "test-payload" },
		{ timeoutMs: 200 },
	);

	// 2. Rejected task within timeout
	await runScenario(
		"background.rejected",
		respondAsync,
		async () => {
			throw new Error("BOOM");
		},
		{ ok: false, error: "BOOM" },
		{ timeoutMs: 200 },
	);

	// 3. Hanging task hits timeout
	await runScenario(
		"background.timeout",
		respondAsync,
		() => new Promise(() => {}), // never resolves
		{ ok: false, error: "ERR_BACKGROUND_ASYNC_RESPONSE_TIMEOUT" },
		{ timeoutMs: 100, waitMs: 200 },
	);

	// 4. Late resolution after timeout — must not double-settle
	let lateResolve;
	const lateTask = () => new Promise((resolve) => { lateResolve = resolve; });
	let captureCount = 0;
	let captured = null;
	respondAsync(
		(payload) => {
			captureCount += 1;
			captured = payload;
		},
		lateTask,
		80,
	);
	await sleep(150);
	assert(captureCount === 1, "background.late: timeout did not fire");
	assert(
		captured?.error === "ERR_BACKGROUND_ASYNC_RESPONSE_TIMEOUT",
		"background.late: timeout did not produce expected error",
	);
	lateResolve({ ok: true, result: "late" });
	await sleep(100);
	assert(
		captureCount === 1,
		`background.late: late resolution caused double-settle (${captureCount})`,
	);

	console.log("[PASS] background.js respondAsync contract");
}

async function testContentFlowDomRespondAsync() {
	const respondAsync = loadRespondAsync(
		path.join(EXT_DIR, "content-flow-dom.js"),
	);

	await runScenario(
		"content-flow-dom.resolved",
		respondAsync,
		async () => ({ ok: true, data: "flow-ok" }),
		{ ok: true, data: "flow-ok" },
		{ timeoutMs: 200 },
	);

	await runScenario(
		"content-flow-dom.timeout",
		respondAsync,
		() => new Promise(() => {}),
		{ ok: false, error: "ERR_CONTENT_ASYNC_RESPONSE_TIMEOUT" },
		{ timeoutMs: 100, waitMs: 200 },
	);

	console.log("[PASS] content-flow-dom.js respondAsync contract");
}

async function testContentRespondAsync() {
	const respondAsync = loadRespondAsync(path.join(EXT_DIR, "content.js"));

	await runScenario(
		"content.resolved",
		respondAsync,
		async () => ({ token: "abc123" }),
		{ token: "abc123" },
		{ timeoutMs: 200 },
	);

	await runScenario(
		"content.timeout",
		respondAsync,
		() => new Promise(() => {}),
		{ ok: false, error: "ERR_CONTENT_ASYNC_RESPONSE_TIMEOUT" },
		{ timeoutMs: 100, waitMs: 200 },
	);

	console.log("[PASS] content.js respondAsync contract");
}

/**
 * Static guardrail: assert each file still defines a DEFAULT_*_TIMEOUT_MS
 * constant and uses it as the respondAsync default. This protects against a
 * future "cleanup" edit that drops the timeout machinery silently.
 */
function staticGuards() {
	const checks = [
		{
			file: "background.js",
			constName: "DEFAULT_RESPOND_ASYNC_TIMEOUT_MS",
			errCode: "ERR_BACKGROUND_ASYNC_RESPONSE_TIMEOUT",
		},
		{
			file: "content-flow-dom.js",
			constName: "DEFAULT_CONTENT_RESPOND_ASYNC_TIMEOUT_MS",
			errCode: "ERR_CONTENT_ASYNC_RESPONSE_TIMEOUT",
		},
		{
			file: "content.js",
			constName: "DEFAULT_CAPTCHA_RESPOND_ASYNC_TIMEOUT_MS",
			errCode: "ERR_CONTENT_ASYNC_RESPONSE_TIMEOUT",
		},
	];

	for (const { file, constName, errCode } of checks) {
		const src = fs.readFileSync(path.join(EXT_DIR, file), "utf8");
		assert(
			src.includes(`const ${constName}`),
			`${file}: missing constant ${constName}`,
		);
		assert(
			src.includes(`timeoutMs = ${constName}`),
			`${file}: respondAsync default must reference ${constName}`,
		);
		assert(
			src.includes(errCode),
			`${file}: must emit ${errCode} on timeout`,
		);
	}
	console.log("[PASS] static guards — all three files declare timeout machinery");
}

async function main() {
	staticGuards();
	await testBackgroundRespondAsync();
	await testContentFlowDomRespondAsync();
	await testContentRespondAsync();
	console.log("\nALL TESTS PASSED");
}

main().catch((err) => {
	console.error("\nTEST FAILED:", err.message);
	process.exit(1);
});
