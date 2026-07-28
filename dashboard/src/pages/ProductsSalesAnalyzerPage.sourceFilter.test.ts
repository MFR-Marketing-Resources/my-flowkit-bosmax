import { describe, expect, it } from "vitest";

import type { Product } from "../types";
import {
	resolveInitialSourceFilter,
	resolveProductsPageImageSource,
} from "./ProductsSalesAnalyzerPage";

const params = (q: string) => new URLSearchParams(q);

function product(overrides: Partial<Product> = {}): Product {
	const base: Product = {
		id: "product-1",
		source: "FASTMOSS",
		raw_product_title: "Product one",
		product_display_name: "Product one",
		product_short_name: "Product one",
		category: null,
		subcategory: null,
		type: null,
		shop_name: null,
		price_min: null,
		price_max: null,
		commission: null,
		image_url: null,
		tiktok_product_url: null,
		fastmoss_source_file: null,
		asset_status: "UNRESOLVED",
		media_id: null,
		local_image_path: null,
		created_at: "2026-07-28T00:00:00Z",
		updated_at: "2026-07-28T00:00:00Z",
	};
	return { ...base, ...overrides };
}

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

describe("resolveProductsPageImageSource", () => {
	it("uses the cache route only when the local image cache is ready", () => {
		expect(
			resolveProductsPageImageSource(
				product({
					id: "cache ready/product",
					image_readiness_status: "IMAGE_CACHE_READY",
					image_url: "https://cdn.example.com/remote.jpg",
				}),
			),
		).toBe("/api/products/cache%20ready%2Fproduct/image");
	});

	it("uses a browser-safe remote image when the local cache is missing", () => {
		expect(
			resolveProductsPageImageSource(
				product({
					image_readiness_status: "LOCAL_CACHE_MISSING",
					local_image_path: "C:\\stale\\product.jpg",
					image_url: "https://cdn.example.com/product.jpg",
					rendered_img_src: "/api/products/product-1/image",
				}),
			),
		).toBe("https://cdn.example.com/product.jpg");
	});

	it("uses image analysis as the next browser-safe remote source", () => {
		expect(
			resolveProductsPageImageSource(
				product({
					image_readiness_status: "LOCAL_CACHE_MISSING",
					image_url: "javascript:alert(1)",
					image_analysis: {
						status: "READY",
						image_url: "https://cdn.example.com/analysis.jpg",
						local_image_path: null,
						detected_package: null,
						detected_text: [],
						visual_confidence: "HIGH",
						provider: "fixture",
					},
				}),
			),
		).toBe("https://cdn.example.com/analysis.jpg");
	});

	it("falls back when no browser-safe local or remote source exists", () => {
		expect(
			resolveProductsPageImageSource(
				product({
					image_readiness_status: "LOCAL_CACHE_MISSING",
					image_url: "data:image/png;base64,unsafe",
					rendered_img_src: "/api/products/product-1/image",
				}),
			),
		).toBeNull();
	});

	it("renders a Kalodata-provenance MANUAL product from its remote image", () => {
		expect(
			resolveProductsPageImageSource(
				product({
					source: "MANUAL",
					source_url: "https://www.kalodata.com/product/example",
					image_readiness_status: "LOCAL_CACHE_MISSING",
					image_url: "https://cdn.example.com/kalodata-product.jpg",
				}),
			),
		).toBe("https://cdn.example.com/kalodata-product.jpg");
	});

	it("renders a FastMoss product from its remote image when cache is missing", () => {
		expect(
			resolveProductsPageImageSource(
				product({
					source: "FASTMOSS",
					fastmoss_source_file: "FASTMOSS_COMBINED.xlsx",
					image_readiness_status: "LOCAL_CACHE_MISSING",
					image_url: "https://cdn.example.com/fastmoss-product.jpg",
				}),
			),
		).toBe("https://cdn.example.com/fastmoss-product.jpg");
	});
});
