import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchProductReleaseControl } from "./productRelease";

const responseBody = {
	total_count: 125,
	returned_count: 50,
	items: [],
	limit: 50,
	offset: 0,
	has_pagination: true,
	summary: {
		hidden: 100,
		released: 25,
		visible_to_staff: 10,
		released_but_blocked: 5,
		eligible_to_release: 20,
	},
};

function response(): Response {
	return new Response(JSON.stringify(responseBody), {
		status: 200,
		headers: { "Content-Type": "application/json" },
	});
}

describe("product release control request contract", () => {
	beforeEach(() => {
		vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response()));
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it("uses the 50-row server page default and starts at offset zero", async () => {
		await fetchProductReleaseControl();

		expect(vi.mocked(fetch)).toHaveBeenCalledWith(
			"/api/product-release?limit=50&offset=0",
			expect.any(Object),
		);
	});

	it("forwards filters, page size, and offset to the existing endpoint", async () => {
		await fetchProductReleaseControl({
			q: "serum",
			releaseStatus: "HIDDEN",
			visibility: "OWNER_RELEASE_REQUIRED",
			eligibility: "BLOCKED",
			blocker: "VISUAL_CUTOUT_NOT_READY",
			limit: 25,
			offset: 50,
		});

		expect(vi.mocked(fetch)).toHaveBeenCalledWith(
			"/api/product-release?q=serum&release_status=HIDDEN&visibility=OWNER_RELEASE_REQUIRED&eligibility=BLOCKED&blocker=VISUAL_CUTOUT_NOT_READY&limit=25&offset=50",
			expect.any(Object),
		);
	});
});
