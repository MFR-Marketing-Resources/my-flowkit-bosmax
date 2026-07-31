import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock the transport so we can assert the exact URLs the reporting fetchers build —
// the /api prefix (the SPA-catch-all 405/HTML trap) and the cross-filter + pagination
// seam params must all be present and correct.
vi.mock("./client", () => ({ getAPI: vi.fn() }));

import {
	fetchClusterAudit,
	fetchCopywritingCoverage,
	fetchExceptions,
	fetchFailedGenerations,
	fetchMappingSummary,
} from "./reporting";
import { getAPI } from "./client";

const mockedGet = vi.mocked(getAPI);
const url = () => mockedGet.mock.calls[0][0] as string;
const parse = (u: string) => new URL(u, "http://x").searchParams;

describe("reporting api URL building (/api prefix + filter seam)", () => {
	beforeEach(() => {
		mockedGet.mockReset();
		mockedGet.mockResolvedValue({} as never);
	});

	it("coverage/copywriting carries the /api prefix and the lifecycle filter", async () => {
		await fetchCopywritingCoverage({ lifecycle_status: "ALL" });
		expect(url().startsWith("/api/reporting/coverage/copywriting?")).toBe(true);
		expect(parse(url()).get("lifecycle_status")).toBe("ALL");
	});

	it("exceptions forwards kind + every seam filter + pagination", async () => {
		await fetchExceptions(
			"missing_copy",
			{
				lifecycle_status: "ACTIVE",
				cluster: "beauty_makeup",
				product_type_group: "lipstick_lip_tint",
			},
			25,
			50,
		);
		expect(url().startsWith("/api/reporting/exceptions?")).toBe(true);
		const p = parse(url());
		expect(p.get("kind")).toBe("missing_copy");
		expect(p.get("lifecycle_status")).toBe("ACTIVE");
		expect(p.get("cluster")).toBe("beauty_makeup");
		expect(p.get("product_type_group")).toBe("lipstick_lip_tint");
		expect(p.get("limit")).toBe("25");
		expect(p.get("offset")).toBe("50");
	});

	it("omits empty cluster / product_type_group (no blank params)", async () => {
		await fetchExceptions("missing_image", {
			lifecycle_status: "ACTIVE",
			cluster: null,
			product_type_group: null,
		});
		const p = parse(url());
		expect(p.has("cluster")).toBe(false);
		expect(p.has("product_type_group")).toBe(false);
	});

	it("reuses existing endpoints (not duplicated) for cluster + mapping", async () => {
		await fetchClusterAudit();
		expect(url()).toBe("/api/creative-intelligence/product-cluster-audit");
		mockedGet.mockReset();
		mockedGet.mockResolvedValue({} as never);
		await fetchMappingSummary();
		expect(url()).toBe("/api/products/mapping-summary");
	});

	it("failed-generations uses the honest report endpoint", async () => {
		await fetchFailedGenerations();
		expect(url()).toBe("/api/reporting/failed-generations");
	});
});
