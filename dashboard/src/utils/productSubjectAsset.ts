import type { Product, UploadedAsset } from "../types";

/** Blocker code surfaced when a product has no usable reference image, so a
 * product poster cannot be anchored and generation must fail closed. */
export const PRODUCT_REFERENCE_IMAGE_REQUIRED = "PRODUCT_REFERENCE_IMAGE_REQUIRED";

/**
 * Convert a BOSMAX product into a Flow SUBJECT reference asset for image
 * generation. Returns `null` when the product has NO usable reference image
 * (`image_url` → `rendered_img_src` → `image_analysis.image_url`).
 *
 * A `null` return is the FAIL-CLOSED signal: a product poster must anchor on the
 * real product image, so callers must block generation on null and NEVER fall
 * back to prompt-only generation (which hallucinates the product bottle/label).
 *
 * Extracted from IMGModule so IMGModule and Poster Builder share ONE resolver —
 * no duplicated product-image extraction logic.
 */
export function productSubjectAsset(
	product: Product | null | undefined,
): UploadedAsset | null {
	if (!product) return null;
	const previewUrl =
		product.image_url ||
		product.rendered_img_src ||
		product.image_analysis?.image_url ||
		null;
	if (!previewUrl) return null;
	return {
		mediaId: product.media_id ?? null,
		fileName: product.product_display_name || product.raw_product_title,
		label: "Product remote image URL",
		previewUrl,
		downloadUrl: previewUrl,
		localFilePath: product.local_image_path ?? undefined,
		assetId: undefined,
		assetFingerprint: `product:${product.id}:${previewUrl}`,
		assetSource: "PRODUCT_IMAGE_URL",
		isDefaultPackageAsset: true,
		previewRenderableStatus: "READY",
		previewErrorDetail: null,
		localImagePathPresent: Boolean(product.local_image_path),
		remoteImageUrlPresent: true,
	};
}
