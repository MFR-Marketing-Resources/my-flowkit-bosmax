import { describe, expect, it } from "vitest";
import type { ImgAssetLane } from "../api/imgFactory";
import type { Product } from "../types";
import {
	buildImgGenerationRequest,
	resolveGenerationInputs,
	resolveProductReferenceAsset,
} from "./imgCockpitLogic";

function product(overrides: Partial<Product>): Product {
	return {
		id: "prod-1",
		product_display_name: "Minyak Warisan Tok Cap Burung 25ml",
		raw_product_title: "Minyak Warisan Tok Cap Burung 25ml",
		media_id: null,
		...overrides,
	} as unknown as Product;
}

function lane(overrides: Partial<ImgAssetLane> = {}): ImgAssetLane {
	return {
		lane_id: "PRODUCT_LANE",
		requires_product_id: true,
		requires_character_reference: false,
		requires_scene_reference: false,
		requires_style_reference: false,
		...overrides,
	} as unknown as ImgAssetLane;
}

const noRefs = { character: null, scene: null, style: null };

function req(res: ReturnType<typeof resolveGenerationInputs>) {
	return buildImgGenerationRequest({
		prompt: "compiled prompt with scale lock",
		resolution: res,
		aspect: "9:16",
		count: 1,
		imageModel: "nano",
	});
}

// SCALE-07 regression: IMG Cockpit previously sent only `image_media_ids`
// (media-id-only). A catalog product (media_id=null, image_url present) passed the
// resolvable gate but contributed NOTHING to the outbound payload — the generator
// received the compiled text prompt with NO product image, so the bottle/scale was
// hallucinated. These tests pin that the REAL product visual reference now reaches
// the outbound /api/flow/generate body via refs.subjectAsset.
describe("SCALE-07: IMG Cockpit delivers the product visual reference", () => {
	// A. media_id present -> not blocked; media id reaches the ref contract.
	it("A: product with a bare media_id is delivered via refs.subjectAsset", () => {
		const res = resolveGenerationInputs(lane(), {
			product: product({ media_id: "media-123" }),
			...noRefs,
		});
		expect(res.blocked).toBe(false);
		expect(res.productAsset?.mediaId).toBe("media-123");
		const body = req(res);
		expect((body.refs as Record<string, { mediaId?: string }>).subjectAsset.mediaId).toBe(
			"media-123",
		);
	});

	// B. media_id null + image_url present -> not blocked; image_url reaches request.
	it("B: catalog product (media_id null, image_url) sends image_url as a real ref", () => {
		const res = resolveGenerationInputs(lane(), {
			product: product({ media_id: null, image_url: "https://cdn/minyak.jpg" }),
			...noRefs,
		});
		expect(res.blocked).toBe(false);
		// The media-id-only list is empty (the exact old-bug condition)...
		expect(res.mediaIds).toEqual([]);
		// ...but the product IMAGE is now carried and reaches the outbound body.
		expect(res.productAsset?.downloadUrl).toBe("https://cdn/minyak.jpg");
		const body = req(res);
		expect(body.image_media_ids).toEqual([]);
		expect(
			(body.refs as Record<string, { downloadUrl?: string }>).subjectAsset.downloadUrl,
		).toBe("https://cdn/minyak.jpg");
	});

	// C. media_id null + local_image_path only -> not blocked; local path reaches request.
	it("C: product with only a local_image_path sends localFilePath as a real ref", () => {
		const res = resolveGenerationInputs(lane(), {
			product: product({ media_id: null, local_image_path: "/cache/minyak.png" }),
			...noRefs,
		});
		expect(res.blocked).toBe(false);
		expect(res.productAsset?.localFilePath).toBe("/cache/minyak.png");
		const body = req(res);
		expect(
			(body.refs as Record<string, { localFilePath?: string }>).subjectAsset.localFilePath,
		).toBe("/cache/minyak.png");
	});

	// D. all visual sources absent -> fail closed (blocked, no ref emitted).
	it("D: product with no usable image source fails closed", () => {
		const res = resolveGenerationInputs(lane(), {
			product: product({ media_id: null }),
			...noRefs,
		});
		expect(res.productAsset).toBeNull();
		expect(res.blocked).toBe(true);
		expect(res.blockReason).toContain("image reference");
		// No product image => no subjectAsset ref in the outbound body.
		expect(req(res).refs).toBeUndefined();
	});

	it("resolveProductReferenceAsset reuses the shared productSubjectAsset resolver", () => {
		const asset = resolveProductReferenceAsset(
			product({
				image_url: "https://cdn/a.jpg",
				local_image_path: "/cache/a.png",
				media_id: "m1",
			}),
		);
		expect(asset?.downloadUrl).toBe("https://cdn/a.jpg");
		expect(asset?.mediaId).toBe("m1");
		expect(asset?.localFilePath).toBe("/cache/a.png");
		expect(resolveProductReferenceAsset(null)).toBeNull();
		expect(resolveProductReferenceAsset(product({}))).toBeNull();
	});
});
