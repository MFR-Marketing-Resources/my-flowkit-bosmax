import { describe, expect, it } from "vitest";
import type { Product } from "../types";
import { productSubjectAsset } from "./productSubjectAsset";

function baseProduct(overrides: Partial<Product> = {}): Product {
	return {
		id: "p1",
		source: "MANUAL",
		raw_product_title: "Raw Product",
		product_display_name: "Display Product",
		category: "Oil",
		subcategory: "Herbal",
		type: "Roll-on",
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
		created_at: "2026-01-01T00:00:00Z",
		updated_at: "2026-01-01T00:00:00Z",
		...overrides,
	};
}

describe("productSubjectAsset", () => {
	it("returns a Flow subject reference from the canonical product image URL", () => {
		const asset = productSubjectAsset(
			baseProduct({
				image_url: "https://cdn.example/product.png",
				media_id: "media-1",
				local_image_path: "/tmp/product.png",
			}),
		);

		expect(asset).toEqual(
			expect.objectContaining({
				mediaId: "media-1",
				fileName: "Display Product",
				previewUrl: "https://cdn.example/product.png",
				downloadUrl: "https://cdn.example/product.png",
				localFilePath: "/tmp/product.png",
				assetFingerprint: "product:p1:https://cdn.example/product.png",
				assetSource: "PRODUCT_IMAGE_URL",
				localImagePathPresent: true,
				remoteImageUrlPresent: true,
			}),
		);
	});

	it("falls back to rendered_img_src before image_analysis image URL", () => {
		expect(
			productSubjectAsset(
				baseProduct({
					rendered_img_src: "https://rendered.example/product.png",
					image_analysis: {
						status: "READY",
						image_url: "https://analysis.example/product.png",
						local_image_path: null,
						detected_package: null,
						detected_text: [],
						visual_confidence: "HIGH",
						provider: "test",
					},
				}),
			)?.downloadUrl,
		).toBe("https://rendered.example/product.png");
	});

	it("falls back to image_analysis image URL when no primary image fields exist", () => {
		expect(
			productSubjectAsset(
				baseProduct({
					image_analysis: {
						status: "READY",
						image_url: "https://analysis.example/product.png",
						local_image_path: null,
						detected_package: null,
						detected_text: [],
						visual_confidence: "HIGH",
						provider: "test",
					},
				}),
			)?.downloadUrl,
		).toBe("https://analysis.example/product.png");
	});

	it("returns null when no usable product reference image exists", () => {
		expect(productSubjectAsset(baseProduct())).toBeNull();
		expect(productSubjectAsset(null)).toBeNull();
	});
});
