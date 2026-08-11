// Pure, dependency-free logic for the IMG cockpit — extracted so the governance
// behavior (generation-ref resolution, approval gate, reuse safety) is verifiable
// independently of React. There is no JS test runner in this repo; the REAL gates
// are enforced + behavior-tested in the backend (validate_selectable_asset
// require_approved, save APPROVAL_REQUIRES_ALL_TRUTH_PASS, the F2V resolver). These
// helpers are the frontend mirror.

import { productSubjectAsset } from "../utils/productSubjectAsset";
import type { ImgAssetLane, StartImgGenerationInput } from "../api/imgFactory";
import type { CreativeAsset, Product, UploadedAsset } from "../types";

export type TruthStatus = "UNVERIFIED" | "PASS" | "FAIL";

export interface GenerationRef {
	label: string;
	role: string;
	mediaId: string | null;
}

export interface ResolvedGeneration {
	/** Resolvable Flow media ids to actually send to generation. */
	mediaIds: string[];
	/**
	 * The product's REAL visual reference (media_id OR image_url OR local cached
	 * file), delivered to the generator via refs.subjectAsset. `null` when there is
	 * no product or no usable image source (the FAIL-CLOSED signal).
	 *
	 * SCALE-07: `mediaIds` alone dropped catalog products (media_id=null, image_url
	 * present) — they passed the resolvable gate but contributed nothing to the
	 * outbound payload, so the generator got the text prompt with NO product image.
	 */
	productAsset: UploadedAsset | null;
	/** Every selected reference (resolved or not). */
	refs: GenerationRef[];
	/** Selected references that have no resolvable media id. */
	unresolved: GenerationRef[];
	/** True when the lane needs visual truth that cannot be resolved. */
	blocked: boolean;
	blockReason: string | null;
}

/** A downstream-reusable asset must be ACTIVE and operator-APPROVED. */
export function isReusableAsset(asset: {
	status?: string;
	review_status?: string;
}): boolean {
	return asset.status === "ACTIVE" && asset.review_status === "APPROVED";
}

/** APPROVED requires EVERY truth/safety gate to explicitly PASS. */
export function canApprove(statuses: {
	identity: TruthStatus;
	scale: TruthStatus;
	claim: TruthStatus;
}): boolean {
	return (
		statuses.identity === "PASS" &&
		statuses.scale === "PASS" &&
		statuses.claim === "PASS"
	);
}

/**
 * Resolve a product's REAL visual reference for the generator, in the backend's
 * supported ref contract (media_id OR downloadUrl OR localFilePath — see
 * agent/api/flow.py ordered_ref_slots / _resolve_asset_to_media_id).
 *
 * Reuses the shared `productSubjectAsset` resolver (image_url → rendered_img_src →
 * image_analysis.image_url), then covers the two real sources it does NOT (a
 * locally-cached file, a bare media_id) so a catalog product (media_id=null) still
 * delivers a REAL reference and never generates prompt-only. Returns `null` only
 * when NO visual source exists — the FAIL-CLOSED signal. No competing format: the
 * fallback is the same `UploadedAsset` shape productSubjectAsset emits.
 */
export function resolveProductReferenceAsset(
	product: Product | null | undefined,
): UploadedAsset | null {
	if (!product) return null;
	const shared = productSubjectAsset(product);
	if (shared) return shared;
	// productSubjectAsset requires an image URL. A locally-cached file or a bare
	// media id are still valid references the backend can resolve.
	if (product.local_image_path || product.media_id) {
		return {
			mediaId: product.media_id ?? null,
			fileName: product.product_display_name || product.raw_product_title,
			label: "Product cached image",
			localFilePath: product.local_image_path ?? undefined,
			assetSource: "PRODUCT_IMAGE_URL",
			isDefaultPackageAsset: true,
			previewRenderableStatus: "READY",
			localImagePathPresent: Boolean(product.local_image_path),
			remoteImageUrlPresent: false,
		};
	}
	return null;
}

/**
 * Build the generation payload from the SELECTED references (product / avatar /
 * scene / style). Only references that resolve to a Flow media id are sent. If a
 * lane requires product visual truth but the product has no resolvable media id,
 * generation is blocked with a clear reason.
 */
export function resolveGenerationInputs(
	lane: ImgAssetLane | null,
	refs: {
		product: Product | null;
		character: CreativeAsset | null;
		scene: CreativeAsset | null;
		style: CreativeAsset | null;
	},
): ResolvedGeneration {
	const all: GenerationRef[] = [];
	if (refs.character) {
		all.push({
			label: refs.character.display_name,
			role: "CHARACTER_REFERENCE",
			mediaId: refs.character.media_id ?? null,
		});
	}
	if (refs.scene) {
		all.push({
			label: refs.scene.display_name,
			role: "SCENE_CONTEXT_REFERENCE",
			mediaId: refs.scene.media_id ?? null,
		});
	}
	if (refs.style) {
		all.push({
			label: refs.style.display_name,
			role: "STYLE_REFERENCE",
			mediaId: refs.style.media_id ?? null,
		});
	}

	const mediaIds = all
		.map((r) => r.mediaId)
		.filter((m): m is string => Boolean(m));
	const unresolved = all.filter((r) => !r.mediaId);

	// SCALE-07 fix: resolve the product's REAL visual reference (not just a media
	// id). Products from /api/products have media_id=null and expose the image via
	// image_url; the media-id-only `mediaIds` list dropped them from the outbound
	// payload even though they passed the gate. `productAsset` carries the real
	// image (media_id OR image_url OR local file) and is delivered via
	// refs.subjectAsset in buildImgGenerationRequest. Resolvable ⟺ productAsset≠null.
	const productAsset = resolveProductReferenceAsset(refs.product);
	const productResolvable = Boolean(productAsset);

	let blocked = false;
	let blockReason: string | null = null;
	if (lane?.requires_product_id && !productResolvable) {
		blocked = true;
		blockReason =
			"This lane requires a product with an image reference. Select a product " +
			"that has a resolved image (image URL or local file).";
	} else if (lane?.requires_character_reference && !refs.character) {
		blocked = true;
		blockReason =
			"This lane requires an APPROVED avatar (character reference). Select one " +
			"in Section 3 — approve it there if it is still pending.";
	} else if (lane?.requires_scene_reference && !refs.scene) {
		blocked = true;
		blockReason =
			"This lane requires an APPROVED scene reference. Select one in Section 4 " +
			"— approve it there if it is still pending.";
	} else if (lane?.requires_style_reference && !refs.style) {
		blocked = true;
		blockReason =
			"This lane requires an APPROVED style reference. Select one in Section 4 " +
			"— approve it there if it is still pending.";
	}

	return { mediaIds, productAsset, refs: all, unresolved, blocked, blockReason };
}

/**
 * Assemble the EXACT request body ImgCockpitPage sends to POST /api/flow/generate
 * (via startImgGeneration). SCALE-07: the product's real visual reference is
 * delivered through `refs.subjectAsset` (the backend-proven product-reference slot
 * — see tests/api/test_flow_generate_product_ref.py), so a catalog product's image
 * reaches the generator instead of only the compiled text prompt. Pure + testable:
 * this is the outbound-payload proof seam.
 */
export function buildImgGenerationRequest(input: {
	prompt: string;
	resolution: ResolvedGeneration;
	aspect: string;
	count: number;
	imageModel?: string;
	productId?: string;
	visualLaneId?: string;
}): StartImgGenerationInput {
	const { prompt, resolution, aspect, count, imageModel, productId, visualLaneId } = input;
	const refs: Record<string, unknown> = {};
	if (resolution.productAsset) {
		refs.productAsset = resolution.productAsset;
	}
	return {
		prompt,
		product_id: productId,
		visual_lane_id: visualLaneId,
		image_media_ids: resolution.mediaIds,
		aspect,
		count,
		image_model: imageModel,
		refs: Object.keys(refs).length > 0 ? refs : undefined,
	};
}

/**
 * Assemble the EXACT request body ImgFastlanePage sends to POST /api/flow/generate.
 * Enforces single product reference authority via refs.productAsset; product media ID is excluded
 * from image_media_ids.
 */
export function buildFastlaneGenerationRequest(input: {
	prompt: string;
	resolvedRefsPayload: Record<string, { mediaId?: string | null; downloadUrl?: string | null; localFilePath?: string | null }>;
	groundedProdAsset?: { mediaId?: string | null; downloadUrl?: string | null; localFilePath?: string | null } | null;
	aspect: string;
	quantity: number;
	imageModel?: string;
	productId?: string;
	visualLaneId?: string;
}): StartImgGenerationInput {
	const {
		prompt,
		resolvedRefsPayload,
		groundedProdAsset,
		aspect,
		quantity,
		imageModel,
		productId,
		visualLaneId,
	} = input;
	const refs: Record<string, unknown> = { ...resolvedRefsPayload };
	if (groundedProdAsset) {
		refs.productAsset = groundedProdAsset;
	}
	const mediaIds = Object.entries(resolvedRefsPayload)
		.filter(([key]) => key !== "productAsset")
		.map(([, asset]) => asset.mediaId)
		.filter((id): id is string => Boolean(id));

	return {
		prompt,
		product_id: productId,
		visual_lane_id: visualLaneId,
		image_media_ids: mediaIds,
		aspect,
		count: quantity,
		image_model: imageModel,
		refs: Object.keys(refs).length > 0 ? refs : undefined,
	};
}
