import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
	fetchProductCatalog,
	fetchProductRegistry,
	invalidateProductCatalogCache,
	invalidateProductRegistryCache,
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

describe("product registry request cache", () => {
	const registryResponse = {
		items: [{ id: "product-1" }],
		total_count: 1,
		returned_count: 1,
		has_pagination: false,
		limit: 20,
		offset: 0,
	};

	function registryResponseBody(): Response {
		return new Response(JSON.stringify(registryResponse), {
			status: 200,
			headers: { "Content-Type": "application/json" },
		});
	}

	beforeEach(() => {
		invalidateProductRegistryCache();
		vi.stubGlobal(
			"fetch",
			vi.fn().mockImplementation(() =>
				Promise.resolve(registryResponseBody()),
			),
		);
	});

	afterEach(() => {
		invalidateProductRegistryCache();
		vi.unstubAllGlobals();
		vi.useRealTimers();
	});

	it("deduplicates concurrent and warm requests without colliding pages or filters", async () => {
		const params = {
			q: "serum",
			source: "MANUAL" as const,
			group: "beauty",
			limit: 20,
			offset: 0,
		};
		await Promise.all([fetchProductRegistry(params), fetchProductRegistry(params)]);
		await fetchProductRegistry(params);
		await fetchProductRegistry({ ...params, offset: 20 });
		await fetchProductRegistry({ ...params, group: "food" });

		const fetchMock = vi.mocked(fetch);
		expect(fetchMock).toHaveBeenCalledTimes(3);
		expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
			"/api/products?source=MANUAL&q=serum&group=beauty&view=REGISTRY&limit=20&offset=0",
			"/api/products?source=MANUAL&q=serum&group=beauty&view=REGISTRY&limit=20&offset=20",
			"/api/products?source=MANUAL&q=serum&group=food&view=REGISTRY&limit=20&offset=0",
		]);
	});

	it("expires warm pages and evicts failures", async () => {
		vi.useFakeTimers();
		await fetchProductRegistry({ limit: 20, offset: 0 });
		vi.advanceTimersByTime(30_001);
		await fetchProductRegistry({ limit: 20, offset: 0 });

		const fetchMock = vi.mocked(fetch);
		fetchMock.mockRejectedValueOnce(new Error("registry unavailable"));
		await expect(
			fetchProductRegistry({ q: "will-fail", limit: 20, offset: 0 }),
		).rejects.toThrow("registry unavailable");
		await expect(
			fetchProductRegistry({ q: "will-fail", limit: 20, offset: 0 }),
		).resolves.toEqual(registryResponse);
		expect(fetchMock).toHaveBeenCalledTimes(4);
	});

	it("clears registry pages when a catalog mutation invalidates shared reads", async () => {
		await fetchProductRegistry({ limit: 20, offset: 0 });
		invalidateProductCatalogCache();
		await fetchProductRegistry({ limit: 20, offset: 0 });
		expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2);
	});

	it("serializes the server-authoritative visual review facet", async () => {
		await fetchProductRegistry({
			visualReview: "PENDING_VISUAL_REVIEW",
			limit: 20,
			offset: 0,
		});

		expect(vi.mocked(fetch)).toHaveBeenCalledWith(
			"/api/products?visual_review=PENDING_VISUAL_REVIEW&view=REGISTRY&limit=20&offset=0",
			expect.anything(),
		);
	});
});
