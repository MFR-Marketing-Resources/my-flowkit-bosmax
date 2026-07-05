// Pure, dependency-free logic for the IMG cockpit — extracted so the governance
// behavior (generation-ref resolution, approval gate, reuse safety) is verifiable
// independently of React. There is no JS test runner in this repo; the REAL gates
// are enforced + behavior-tested in the backend (validate_selectable_asset
// require_approved, save APPROVAL_REQUIRES_ALL_TRUTH_PASS, the F2V resolver). These
// helpers are the frontend mirror.

import type { ImgAssetLane } from "../api/imgFactory";
import type { CreativeAsset, Product } from "../types";

export type TruthStatus = "UNVERIFIED" | "PASS" | "FAIL";

export interface GenerationRef {
	label: string;
	role: string;
	mediaId: string | null;
}

export interface ResolvedGeneration {
	/** Resolvable Flow media ids to actually send to generation. */
	mediaIds: string[];
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
	if (refs.product) {
		all.push({
			label: refs.product.product_display_name || refs.product.id,
			role: "PRODUCT",
			mediaId: refs.product.media_id ?? null,
		});
	}
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

	let blocked = false;
	let blockReason: string | null = null;
	if (lane?.requires_product_id) {
		const productRef = all.find((r) => r.role === "PRODUCT");
		if (!productRef || !productRef.mediaId) {
			blocked = true;
			blockReason =
				"This lane requires product visual truth, but the selected product has " +
				"no resolvable image reference (media id). Generation is blocked until a " +
				"resolvable product image exists.";
		}
	}

	return { mediaIds, refs: all, unresolved, blocked, blockReason };
}
