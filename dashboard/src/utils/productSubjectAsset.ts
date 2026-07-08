import type { Product, UploadedAsset } from "../types";

export const PRODUCT_REFERENCE_IMAGE_REQUIRED = "PRODUCT_REFERENCE_IMAGE_REQUIRED";

/**
 * Convert a catalog product into the reference-image payload shape accepted by
 * the Flow image lane. Returns null when the product has no usable image source;
 * callers that generate product posters must fail closed instead of falling back
 * to prompt-only generation.
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
