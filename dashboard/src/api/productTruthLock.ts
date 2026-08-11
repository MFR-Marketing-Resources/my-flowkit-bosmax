import { getAPI, postAPI } from "./client";

export interface ProductTruthLockStatus {
	product_id: string;
	lock_present: boolean;
	lock_valid: boolean;
	exact_allowed: boolean;
	review_status?: string | null;
	product_truth_status: string;
	failure_state?: string;
	error?: string;
	canonical_cutout_media_id?: string;
	canonical_cutout_sha256?: string;
	source_width?: number;
	source_height?: number;
}

export interface ProductTruthLockApproval {
	reviewed_by: string;
	review_note: string;
	confirm_identity: boolean;
	confirm_label_logo: boolean;
	confirm_geometry_scale: boolean;
	confirm_product_isolation: boolean;
}

export function fetchProductTruthLock(
	productId: string,
): Promise<ProductTruthLockStatus> {
	return getAPI<ProductTruthLockStatus>(
		`/api/product-truth/${encodeURIComponent(productId)}/visual-lock`,
	);
}

export function productTruthCutoutPreviewUrl(productId: string): string {
	return `/api/product-truth/${encodeURIComponent(productId)}/visual-lock/cutout-preview`;
}

export function approveProductTruthLock(
	productId: string,
	input: ProductTruthLockApproval,
): Promise<ProductTruthLockStatus> {
	return postAPI<ProductTruthLockStatus>(
		`/api/product-truth/${encodeURIComponent(productId)}/visual-lock/approve`,
		input,
	);
}
