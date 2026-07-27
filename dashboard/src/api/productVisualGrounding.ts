import { getAPI, postAPI } from "./client";

export interface ProductReferenceInfo {
	source_type: string;
	media_id: string | null;
	local_path: string | null;
	image_url: string | null;
	mime_type: string;
	sha256: string;
	width: number;
	height: number;
	provenance: string;
	validation_status: string;
}

export interface ProductVisualGroundingBundle {
	product_id: string;
	product_display_name: string;
	product_reference: ProductReferenceInfo;
	identity_lock: string;
	geometry_lock: string;
	scale_lock: string;
	label_lock: string;
	handling_lock: string;
	negative_rules: string;
	product_category: string;
	product_type: string;
	size_or_volume: string;
	grounding_source: string;
	grounding_confidence: string;
	field_provenance: Record<string, unknown>;
}

export interface GroundedPayloadResponse {
	product_id: string;
	product_display_name: string;
	selected_strategy: string;
	product_reference: ProductReferenceInfo;
	grounding_locks: {
		identity_lock: string;
		geometry_lock: string;
		scale_lock: string;
		label_lock: string;
		handling_lock: string;
		negative_rules: string;
	};
	full_prompt: string;
	field_provenance: Record<string, unknown>;
}

export const STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION = "REFERENCE_CONDITIONED_HUMAN_INTERACTION";
export const STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE = "PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE";
export const STRATEGY_FIXED_HERO_POSTER = "FIXED_HERO_POSTER";

export function resolveGenerationStrategy(params: {
	laneId?: string;
	hasAvatar?: boolean;
	isProductOnly?: boolean;
	isPoster?: boolean;
}): string {
	if (params.isPoster) {
		return STRATEGY_FIXED_HERO_POSTER;
	}
	if (
		params.hasAvatar ||
		(params.laneId &&
			(params.laneId.includes("AVATAR") ||
				params.laneId.includes("UGC") ||
				params.laneId.includes("MODEL") ||
				params.laneId.includes("HYBRID")))
	) {
		return STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION;
	}
	if (params.isProductOnly || (params.laneId && params.laneId.includes("PRODUCT_ONLY"))) {
		return STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE;
	}
	return STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION;
}

export async function fetchProductVisualGrounding(
	productId: string
): Promise<ProductVisualGroundingBundle> {
	return await getAPI<ProductVisualGroundingBundle>(
		`/api/flow/product/${encodeURIComponent(productId)}/visual-grounding`
	);
}

export async function fetchGroundedPayload(
	productId: string,
	options: {
		prompt?: string;
		lane_id?: string;
		has_avatar?: boolean;
		is_product_only?: boolean;
		is_poster?: boolean;
	} = {}
): Promise<GroundedPayloadResponse> {
	return await postAPI<GroundedPayloadResponse>(
		`/api/flow/product/${encodeURIComponent(productId)}/grounded-payload`,
		{
			prompt: options.prompt || "",
			lane_id: options.lane_id,
			has_avatar: options.has_avatar || false,
			is_product_only: options.is_product_only || false,
			is_poster: options.is_poster || false,
		}
	);
}

export interface CanonicalRefAsset {
	mediaId?: string;
	localFilePath?: string;
	downloadUrl?: string;
	fileName?: string;
	semanticRole?: string;
}

export function buildProviderProductReferenceAsset(grounded: GroundedPayloadResponse): CanonicalRefAsset | null {
	const ref = grounded.product_reference;
	if (!ref) return null;
	const mediaId = ref.media_id || undefined;
	const localFilePath = ref.local_path || undefined;
	const downloadUrl = ref.image_url || undefined;

	if (!mediaId && !localFilePath && !downloadUrl) {
		return null;
	}

	return {
		mediaId,
		localFilePath,
		downloadUrl,
		fileName: `${grounded.product_id}_reference.jpeg`,
		semanticRole: "PRODUCT_REFERENCE",
	};
}
