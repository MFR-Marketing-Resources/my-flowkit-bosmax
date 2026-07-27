import { getAPI } from "./apiClient";

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

export async function fetchProductVisualGrounding(
	productId: string
): Promise<ProductVisualGroundingBundle> {
	return await getAPI<ProductVisualGroundingBundle>(
		`/api/flow/product/${encodeURIComponent(productId)}/visual-grounding`
	);
}
