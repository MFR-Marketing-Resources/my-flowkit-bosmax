import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Zero-legacy-caller regression gate for the Copy Register V2 cutover.
//
// `agent/api/legacy_copy_guard.require_legacy_copy_maintenance` seals the pre-V2
// copy-storage endpoints below: every one returns HTTP 410
// LEGACY_COPY_STORAGE_DISABLED in normal operation. No shipped frontend module may
// call them — the canonical copy authority is /api/copy-register/v2. This test fails
// if a sealed endpoint literal reappears in non-test source, preventing the
// "Copy Intelligence / Bulk Angle / poster / supply produced a 410" defect from
// regressing.
const SEALED_ENDPOINTS = [
	"/api/copy-sets",
	"/api/copy-components",
	"/api/creative-supply",
	"/api/poster/copy-sets",
	"/api/copywriting/readiness",
	"/api/poster/copy-recommendations",
	"/api/poster/copy/fit",
];

const SRC_ROOT = dirname(fileURLToPath(import.meta.url));
const SELF = "legacyCopyStorageClosure.test.ts";

function shippedSourceFiles(dir: string): string[] {
	const out: string[] = [];
	for (const entry of readdirSync(dir)) {
		const full = join(dir, entry);
		if (statSync(full).isDirectory()) {
			out.push(...shippedSourceFiles(full));
			continue;
		}
		if (!/\.(ts|tsx)$/.test(entry)) continue;
		// Tests may legitimately reference archived endpoints (history / fixtures);
		// only shipped runtime source is gated.
		if (/\.test\.(ts|tsx)$/.test(entry)) continue;
		if (entry === SELF) continue;
		out.push(full);
	}
	return out;
}

// Strip comments so a documentation mention of an archived endpoint never trips the
// gate — only a real code/string reference to a sealed endpoint is an offence.
function stripComments(text: string): string {
	return text
		.replace(/\/\*[\s\S]*?\*\//g, "")
		.replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

describe("legacy copy storage V2 cutover — zero normal callers", () => {
	it("no shipped frontend module references a sealed legacy copy-storage endpoint", () => {
		const offenders: string[] = [];
		for (const file of shippedSourceFiles(SRC_ROOT)) {
			const code = stripComments(readFileSync(file, "utf8"));
			for (const endpoint of SEALED_ENDPOINTS) {
				if (code.includes(endpoint)) {
					offenders.push(`${file.replace(/\\/g, "/")} → ${endpoint}`);
				}
			}
		}
		expect(
			offenders,
			`Sealed legacy copy endpoints must be replaced by /api/copy-register/v2:\n${offenders.join("\n")}`,
		).toEqual([]);
	});
});
