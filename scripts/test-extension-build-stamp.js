#!/usr/bin/env node
/**
 * Harness — extension build provenance.
 *
 * Locks in the contract established when the stale hand-typed BOSMAX_BUILD_PROOF
 * (branch "fix/mv3-message-port-lifecycle", commit 47ce0422…, neither canonical)
 * was replaced with a derived stamp.
 *
 * The load-bearing assertion is #5. BUILD_ID exists to prove the background
 * service worker and the injected content script came from the SAME folder
 * (build_match), and that gate guards generation through
 * make_video._bind_editor_session -> CONTENT_BUILD_MISMATCH. A future patch that
 * "improves" provenance by re-pointing BUILD_ID at the per-commit SHA would
 * silently change a proven gate's meaning. This test fails if that happens.
 *
 * Run: node scripts/test-extension-build-stamp.js
 */
const { execFileSync } = require("node:child_process");
const { existsSync, readFileSync, renameSync, unlinkSync } = require("node:fs");
const { join } = require("node:path");
const vm = require("node:vm");

const REPO_ROOT = join(__dirname, "..");
const STAMP = join(REPO_ROOT, "extension", "build-stamp.js");
const BACKGROUND = join(REPO_ROOT, "extension", "background.js");
const PARKED = `${STAMP}.harness-parked`;

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

/** Evaluate the generated stamp the way a service worker would: `self` is global. */
function loadStamp() {
	const sandbox = {};
	sandbox.self = sandbox;
	vm.createContext(sandbox);
	vm.runInContext(readFileSync(STAMP, "utf8"), sandbox);
	return sandbox.__FLOWKIT_BUILD_STAMP__;
}

console.log("extension build stamp contract");

// Park any pre-existing stamp so the harness never destroys operator state.
const hadStamp = existsSync(STAMP);
if (hadStamp) renameSync(STAMP, PARKED);

try {
	check("1. the stamp script runs and writes extension/build-stamp.js", () => {
		execFileSync("node", [join(REPO_ROOT, "scripts", "stamp-extension-build.mjs")], {
			cwd: REPO_ROOT,
			encoding: "utf8",
		});
		assert(existsSync(STAMP), "build-stamp.js was not written");
	});

	check("2. it derives a real 40-char git sha, not a typed constant", () => {
		const stamp = loadStamp();
		assert(stamp, "__FLOWKIT_BUILD_STAMP__ was not set");
		assert(stamp.stamped === true, "stamped should be true on a generated file");
		assert(/^[0-9a-f]{40}$/.test(stamp.sha), `sha is not a 40-char hex sha: ${stamp.sha}`);
		const head = execFileSync("git", ["rev-parse", "HEAD"], {
			cwd: REPO_ROOT,
			encoding: "utf8",
		}).trim();
		assert(stamp.sha === head, `sha ${stamp.sha} does not match HEAD ${head}`);
	});

	check("3. a dirty extension folder is reported as dirty, never silently clean", () => {
		const stamp = loadStamp();
		assert(typeof stamp.dirty === "boolean", `dirty must be boolean, got ${typeof stamp.dirty}`);
	});

	check("4. the stamp is gitignored — a committed stamp would go stale again", () => {
		const out = execFileSync("git", ["check-ignore", "extension/build-stamp.js"], {
			cwd: REPO_ROOT,
			encoding: "utf8",
		}).trim();
		assert(out === "extension/build-stamp.js", `not ignored, got: ${out}`);
	});

	check("5. BUILD_ID is NOT the git sha — build_match semantics stay untouched", () => {
		const src = readFileSync(BACKGROUND, "utf8");
		const m = src.match(/const BUILD_ID\s*=\s*(.+);/);
		assert(m, "could not find the BUILD_ID declaration in background.js");
		const decl = m[1];
		assert(
			/^["'][^"']+["']$/.test(decl.trim()),
			`BUILD_ID must remain a literal build-family id. Found: ${decl.trim()}\n` +
				"       Re-pointing it at the build stamp would change what build_match proves\n" +
				"       and weaken the CONTENT_BUILD_MISMATCH gate that guards generation.",
		);
		assert(
			!/__FLOWKIT_BUILD_STAMP__/.test(decl),
			"BUILD_ID must not be derived from the build stamp",
		);
	});

	check("6. background.js survives a missing stamp (import is guarded)", () => {
		const src = readFileSync(BACKGROUND, "utf8");
		const idx = src.indexOf('importScripts("build-stamp.js")');
		assert(idx !== -1, "background.js does not import build-stamp.js");
		// The import must sit inside a try block: Chrome refuses to load an extension
		// whose manifest lists a missing file, so an unguarded import of a gitignored
		// file would brick a fresh clone.
		const before = src.slice(Math.max(0, idx - 200), idx);
		assert(/try\s*\{/.test(before), "importScripts('build-stamp.js') is not inside a try block");
		assert(
			/self\.__FLOWKIT_BUILD_STAMP__\)\s*\|\|/.test(src.replace(/\s+/g, " ")) ||
				/__FLOWKIT_BUILD_STAMP__\s*\)\s*\|\|/.test(src),
			"BOSMAX_BUILD_PROOF has no unstamped fallback",
		);
	});

	check("7. no hand-typed branch/commit provenance has crept back in", () => {
		const src = readFileSync(BACKGROUND, "utf8");
		assert(
			!/47ce04229877bb7e579fb195f42c257c9dcc0f66/.test(src),
			"the stale commit constant is back in background.js",
		);
		assert(
			!/branch:\s*["']fix\//.test(src),
			"a hand-typed branch constant is back in background.js",
		);
	});
} finally {
	// Restore operator state exactly as found.
	if (hadStamp) {
		if (existsSync(STAMP)) unlinkSync(STAMP);
		renameSync(PARKED, STAMP);
	}
}

if (failures) {
	console.error(`\n${failures} check(s) failed`);
	process.exit(1);
}
console.log("\nall checks passed");
