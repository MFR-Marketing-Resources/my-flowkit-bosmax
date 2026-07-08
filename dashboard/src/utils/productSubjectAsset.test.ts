import { describe, expect, it } from "vitest";
import type { Product } from "../types";
import {
	PRODUCT_REFERENCE_IMAGE_REQUIRED,
	productSubjectAsset,
} from "./productSubjectAsset";

function product(overrides: Partial<Product>): Product {
	return {
		id: "prod-1",
		product_display_name: "Minyak Warisan Tok Cap Burung 25ml",
		raw_product_title: "Minyak Warisan Tok Cap Burung 25ml",
		media_id: null,
		...overrides,
	} as unknown as Product;
}

describe("productSubjectAsset", () => {
	it("builds a subject reference asset from product.image_url", () => {
		const asset = productSubjectAsset(
			product({
				image_url: "https://cdn/minyak.jpg",
				local_image_path: "/local/minyak.png",
				media_id: "media-123",
			}),
		);
		expect(asset).not.toBeNull();
		expect(asset?.mediaId).toBe("media-123");
		expect(asset?.downloadUrl).toBe("https://cdn/minyak.jpg");
		expect(asset?.previewUrl).toBe("https://cdn/minyak.jpg");
		expect(asset?.localFilePath).toBe("/local/minyak.png");
		expect(asset?.assetFingerprint).toBe("product:prod-1:https://cdn/minyak.jpg");
		expect(asset?.assetSource).toBe("PRODUCT_IMAGE_URL");
		expect(asset?.previewRenderableStatus).toBe("READY");
		expect(asset?.localImagePathPresent).toBe(true);
		expect(asset?.remoteImageUrlPresent).toBe(true);
	});

	it("falls through image_url → rendered_img_src → image_analysis.image_url", () => {
		expect(
			productSubjectAsset(product({ rendered_img_src: "https://cdn/rendered.jpg" }))
				?.downloadUrl,
		).toBe("https://cdn/rendered.jpg");
		expect(
			productSubjectAsset(
				product({ image_analysis: { image_url: "https://cdn/analysis.jpg" } as never }),
			)?.downloadUrl,
		).toBe("https://cdn/analysis.jpg");
		// image_url wins when multiple are present.
		expect(
			productSubjectAsset(
				product({
					image_url: "https://cdn/primary.jpg",
					rendered_img_src: "https://cdn/rendered.jpg",
				}),
			)?.downloadUrl,
		).toBe("https://cdn/primary.jpg");
	});

	it("returns null (fail-closed) when the product has no usable image", () => {
		expect(productSubjectAsset(product({}))).toBeNull();
		expect(productSubjectAsset(null)).toBeNull();
		expect(productSubjectAsset(undefined)).toBeNull();
	});

	it("exports the fail-closed blocker code", () => {
		expect(PRODUCT_REFERENCE_IMAGE_REQUIRED).toBe("PRODUCT_REFERENCE_IMAGE_REQUIRED");
	});
});
