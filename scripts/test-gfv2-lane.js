"use strict";

// Unit tests for the GFV2 lane decision logic extracted from extension/background.js:
//   - isGfv2Lane(job)
//   - gfv2ClassifySurface(tab, capture)   (stale c240ebbd / something-went-wrong / editor)
//   - GFV2_STAGE_MAP (SOP -> GFV2 stage mapping)
// Pure logic — no live Flow tab required.

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const assert = (cond, msg) => {
	if (!cond) throw new Error(`ASSERTION_FAILED: ${msg}`);
};

const SRC = fs.readFileSync(
	path.join(__dirname, "..", "extension", "background.js"),
	"utf8",
);

function extractFunctionSource(source, name) {
	const markers = [`function ${name}(`, `async function ${name}(`];
	const start = markers
		.map((m) => source.indexOf(m))
		.filter((i) => i >= 0)
		.sort((a, b) => a - b)[0];
	assert(start >= 0, `missing ${name} in background.js`);
	const firstBrace = source.indexOf("{", source.indexOf("(", start));
	let depth = 0;
	for (let i = firstBrace; i < source.length; i += 1) {
		if (source[i] === "{") depth += 1;
		else if (source[i] === "}") {
			depth -= 1;
			if (depth === 0) return source.slice(start, i + 1);
		}
	}
	throw new Error(`unbalanced braces for ${name}`);
}

function extractConstObject(source, name) {
	const start = source.indexOf(`const ${name} = Object.freeze({`);
	assert(start >= 0, `missing ${name}`);
	const firstBrace = source.indexOf("{", start);
	let depth = 0;
	for (let i = firstBrace; i < source.length; i += 1) {
		if (source[i] === "{") depth += 1;
		else if (source[i] === "}") {
			depth -= 1;
			if (depth === 0) return source.slice(start, source.indexOf(";", i) + 1);
		}
	}
	throw new Error(`unbalanced ${name}`);
}

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(
	[
		extractConstObject(SRC, "GFV2_STAGE_MAP"),
		extractFunctionSource(SRC, "isGfv2Lane"),
		extractFunctionSource(SRC, "gfv2ClassifySurface"),
		"this.__t = { GFV2_STAGE_MAP, isGfv2Lane, gfv2ClassifySurface };",
	].join("\n"),
	sandbox,
);
const { GFV2_STAGE_MAP, isGfv2Lane, gfv2ClassifySurface } = sandbox.__t;

const tests = [];
const test = (n, f) => tests.push([n, f]);

test("isGfv2Lane: lane flag and gfv2 flag activate; others do not", () => {
	assert(isGfv2Lane({ lane: "GFV2_UPLOAD_SETTINGS_PROMPT_GENERATE" }) === true, "lane flag");
	assert(isGfv2Lane({ gfv2: true }) === true, "gfv2 flag");
	assert(isGfv2Lane({ lane: "F2V_PACKAGE_UPLOAD_ONLY" }) === false, "old lane is not GFV2");
	assert(isGfv2Lane({ mode: "F2V" }) === false, "plain F2V not GFV2");
	assert(isGfv2Lane(null) === false, "null not GFV2");
});

test("gfv2ClassifySurface: stale c240ebbd is never a valid surface", () => {
	const r = gfv2ClassifySurface(
		{ url: "https://labs.google/fx/tools/flow/project/c240ebbd-x" },
		{ ok: true, evaluation: { proofs: { editor: { ok: true } } }, diagnostic: {} },
	);
	assert(r.healthy === false && r.reason === "stale_stored_project", "c240ebbd must be rejected even if editor reads ok");
});

test("gfv2ClassifySurface: 'Back to projects' + no editor = something_went_wrong", () => {
	const r = gfv2ClassifySurface(
		{ url: "https://labs.google/fx/tools/flow/project/abc" },
		{
			ok: true,
			evaluation: { proofs: { editor: { ok: false } } },
			diagnostic: { button_texts: ["arrow_backBack to projects"] },
		},
	);
	assert(r.healthy === false && r.reason === "something_went_wrong", "error page must be rejected");
});

test("gfv2ClassifySurface: login blocker rejected", () => {
	const r = gfv2ClassifySurface(
		{ url: "https://labs.google/fx/tools/flow" },
		{ ok: true, evaluation: { proofs: { editor: { ok: false } } }, diagnostic: { login_or_access_blocker: true } },
	);
	assert(r.healthy === false && r.reason === "login_or_access_blocker", "login blocker must be rejected");
});

test("gfv2ClassifySurface: healthy editor surface (no Frames/project required)", () => {
	const r = gfv2ClassifySurface(
		{ url: "https://labs.google/fx/tools/flow" }, // root, NOT /project/
		{
			ok: true,
			evaluation: { proofs: { editor: { ok: true } } },
			diagnostic: { button_texts: ["Upload media", "Settings"] },
		},
	);
	assert(r.healthy === true && r.reason === "ok", "a composer/editor surface must pass without /project/ or Frames");
});

test("gfv2ClassifySurface: editor not ready rejected", () => {
	const r = gfv2ClassifySurface(
		{ url: "https://labs.google/fx/tools/flow" },
		{ ok: true, evaluation: { proofs: { editor: { ok: false } } }, diagnostic: { button_texts: [] } },
	);
	assert(r.healthy === false && r.reason === "no_editor_surface", "no editor surface must be rejected");
});

test("GFV2_STAGE_MAP maps the SOP stages to the V2 contract stages", () => {
	assert(GFV2_STAGE_MAP.F2V_SOP_START_CLICKED === "GFV2_UPLOAD_MEDIA_OPENED", "upload media");
	assert(GFV2_STAGE_MAP.F2V_SOP_UPLOAD_WAIT_DONE === "GFV2_ADD_TO_PROMPT_CLICKED", "add to prompt");
	assert(GFV2_STAGE_MAP.F2V_SOP_PROMPT_INSERTED === "GFV2_PROMPT_INSERTED", "prompt inserted");
	assert(GFV2_STAGE_MAP.F2V_SOP_RATIO_9_16_CONFIRMED === "GFV2_RATIO_9_16_CONFIRMED", "ratio");
	assert(GFV2_STAGE_MAP.F2V_SOP_COUNT_1X_CONFIRMED === "GFV2_COUNT_1X_CONFIRMED", "count");
});

let failed = 0;
for (const [name, fn] of tests) {
	try {
		fn();
		console.log(`PASS ${name}`);
	} catch (err) {
		failed += 1;
		console.error(`FAIL ${name}\n  ${err.message}`);
	}
}
if (failed > 0) {
	console.error(`\n${failed} failing case(s)`);
	process.exit(1);
}
console.log("\nPASS test-gfv2-lane");
