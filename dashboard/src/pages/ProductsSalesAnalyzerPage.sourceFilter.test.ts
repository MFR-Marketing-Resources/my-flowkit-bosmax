import { describe, expect, it } from "vitest";

import { resolveInitialSourceFilter } from "./ProductsSalesAnalyzerPage";

const params = (q: string) => new URLSearchParams(q);

describe("resolveInitialSourceFilter — demo-safe /products bridge landing", () => {
	it("defaults to ALL when arriving from the Smart Registration bridge (?tab=INTELLIGENCE)", () => {
		// So both manual and imported products are discoverable on landing.
		expect(resolveInitialSourceFilter(params("tab=INTELLIGENCE"))).toBe("ALL");
	});

	it("defaults to ALL when a product is named via ?product=<id>", () => {
		// The named product may be MANUAL — it must not be hidden by a source filter.
		expect(resolveInitialSourceFilter(params("product=abc-123"))).toBe("ALL");
	});

	it("keeps the normal FASTMOSS default for a plain /products visit", () => {
		expect(resolveInitialSourceFilter(params(""))).toBe("FASTMOSS");
		expect(resolveInitialSourceFilter(params("tab=DETAILS"))).toBe("FASTMOSS");
	});

	it("respects an explicit ?source= even in the bridge context", () => {
		expect(resolveInitialSourceFilter(params("source=MANUAL"))).toBe("MANUAL");
		expect(
			resolveInitialSourceFilter(params("source=MANUAL&tab=INTELLIGENCE")),
		).toBe("MANUAL");
		expect(resolveInitialSourceFilter(params("source=FASTMOSS"))).toBe("FASTMOSS");
	});
});
