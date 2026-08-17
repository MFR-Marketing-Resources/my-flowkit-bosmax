import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
	fetchProductCatalog,
	invalidateProductCatalogCache,
	revalidateProductCatalog,
} from "./products";

const catalogResponse = {
	items: [{ id: "product-1" }],
	total_count: 1,
};

function response(): Response {
	return new Response(JSON.stringify(catalogResponse), {
		status: 200,
		headers: { "Content-Type": "application/json" },
	});
}

describe("product catalog request cache", () => {
	beforeEach(() => {
		invalidateProductCatalogCache();
		vi.stubGlobal(
			"fetch",
			vi.fn().mockImplementation(() => Promise.resolve(response())),
		);
	});

	afterEach(() => {
		invalidateProductCatalogCache();
		vi.unstubAllGlobals();
		vi.useRealTimers();
	});

	it("deduplicates concurrent and warm requests by window and purpose", async () => {
		const first = fetchProductCatalog();
		const second = fetchProductCatalog();
		await Promise.all([first, second]);
		await fetchProductCatalog();
		await fetchProductCatalog(50, "REVIEW");
		await fetchProductCatalog(25);

		const fetchMock = vi.mocked(fetch);
		expect(fetchMock).toHaveBeenCalledTimes(3);
		expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
			"/api/products?limit=50&offset=0&purpose=GENERATION",
			"/api/products?limit=50&offset=0&purpose=REVIEW",
			"/api/products?limit=25&offset=0&purpose=GENERATION",
		]);
	});

	it("expires the warm entry and supports explicit revalidation", async () => {
		vi.useFakeTimers();
		await fetchProductCatalog();
		vi.advanceTimersByTime(30_001);
		await fetchProductCatalog();
		await revalidateProductCatalog();

		expect(vi.mocked(fetch)).toHaveBeenCalledTimes(3);
	});

	it("does not retain a failed request", async () => {
		const fetchMock = vi.mocked(fetch);
		fetchMock.mockRejectedValueOnce(new Error("catalog unavailable"));
		await expect(fetchProductCatalog()).rejects.toThrow("catalog unavailable");
		await expect(fetchProductCatalog()).resolves.toEqual(catalogResponse);
		expect(fetchMock).toHaveBeenCalledTimes(2);
	});
});
