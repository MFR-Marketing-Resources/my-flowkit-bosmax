import { fetchAPI, postAPI } from "./client";

export interface ProductReleaseRow {
	id: string;
	raw_product_title?: string | null;
	product_display_name?: string | null;
	product_short_name?: string | null;
	brand?: string | null;
	lifecycle_status?: string | null;
	staff_release_status: "HIDDEN" | "RELEASED";
	minimum_eligibility_status: "ELIGIBLE" | "BLOCKED";
	current_minimum_eligibility: boolean;
	operationally_visible: boolean;
	visibility_reason: string;
	blocker_codes: string[];
	product_truth_status?: string | null;
	product_truth_update_pending?: boolean;
	mapping_status?: string | null;
	prompt_readiness_status?: string | null;
	claim_gate?: string | null;
	visual_readiness?: {
		canonical_media_status?: string;
		visual_grounding_status?: string;
		exact_commerce_status?: string;
		cutout_status?: string;
		blockers?: string[];
	};
	release_history?: {
		released_at?: string | null;
		hidden_at?: string | null;
		release_note?: string | null;
		release_updated_at?: string | null;
	};
}

export interface ProductReleaseResponse {
	total_count: number;
	returned_count: number;
	items: ProductReleaseRow[];
	limit: number;
	offset: number;
	has_pagination: boolean;
	summary: {
		hidden: number;
		released: number;
		visible_to_staff: number;
		released_but_blocked: number;
		eligible_to_release: number;
	};
}

export interface ProductReleaseMutationResponse {
	ok: boolean;
	action: string;
	result?: string;
	error?: string;
	message?: string;
	details?: Record<string, unknown>;
}

export function fetchProductReleaseControl(params: {
	q?: string;
	releaseStatus?: string;
	visibility?: string;
	eligibility?: string;
	blocker?: string;
} = {}): Promise<ProductReleaseResponse> {
	const query = new URLSearchParams();
	if (params.q) query.set("q", params.q);
	if (params.releaseStatus) query.set("release_status", params.releaseStatus);
	if (params.visibility) query.set("visibility", params.visibility);
	if (params.eligibility) query.set("eligibility", params.eligibility);
	if (params.blocker) query.set("blocker", params.blocker);
	query.set("limit", "1000");
	return fetchAPI<ProductReleaseResponse>(`/api/product-release?${query.toString()}`);
}

export function releaseProduct(productId: string, note?: string): Promise<ProductReleaseMutationResponse> {
	return postAPI<ProductReleaseMutationResponse>(`/api/product-release/${encodeURIComponent(productId)}/release`, { note: note || null });
}

export function hideProduct(productId: string, note?: string): Promise<ProductReleaseMutationResponse> {
	return postAPI<ProductReleaseMutationResponse>(`/api/product-release/${encodeURIComponent(productId)}/hide`, { note: note || null });
}

export function bulkUpdateProductRelease(productIds: string[], action: "RELEASE" | "HIDE", note?: string): Promise<ProductReleaseMutationResponse> {
	return postAPI<ProductReleaseMutationResponse>("/api/product-release/bulk", {
		product_ids: productIds,
		action,
		note: note || null,
	});
}
