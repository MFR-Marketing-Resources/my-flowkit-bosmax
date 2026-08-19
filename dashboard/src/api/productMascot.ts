// Product Mascot Key Visual API — a per-product creative-derivative character
// anchor. Preview / Upload / Replace / Remove only (no generation).
import { deleteAPI, getAPI, postAPI } from "./client";

export interface ProductMascot {
	product_id: string;
	asset_id: string;
	creative_asset_id?: string;
	media_id: string | null;
	local_file_path: string | null;
	display_name: string | null;
	preview_url: string | null;
	download_url: string | null;
	asset_subtype: string | null;
	semantic_role: string | null;
	review_status: string | null;
	status: string | null;
	updated_at: string | null;
}

export interface ProductMascotResponse {
	product_id: string;
	available: boolean;
	mascot: ProductMascot | null;
}

export async function fetchProductMascot(
	productId: string,
): Promise<ProductMascotResponse> {
	return getAPI(
		`/api/products/${encodeURIComponent(productId)}/mascot-key-visual`,
	);
}

export async function setProductMascot(
	productId: string,
	input: { image_base64: string; file_name?: string | null; display_name?: string | null },
): Promise<ProductMascotResponse> {
	return postAPI(
		`/api/products/${encodeURIComponent(productId)}/mascot-key-visual`,
		{
			image_base64: input.image_base64,
			file_name: input.file_name ?? null,
			display_name: input.display_name ?? null,
		},
	);
}

export async function removeProductMascot(productId: string): Promise<void> {
	return deleteAPI(
		`/api/products/${encodeURIComponent(productId)}/mascot-key-visual`,
	);
}
