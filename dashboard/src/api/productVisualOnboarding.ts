import { fetchAPI, postAPI } from "./client";
import type { ProductVisualReadiness } from "../types";

export interface ProductVisualBulkPreview {
	eligible_product_ids: string[];
	preview_digest: string;
	counts: {
		eligible: number;
		already_approved: number;
		pending_review: number;
		blocked: number;
		skipped: number;
	};
	total_scanned: number;
	provider_operations: number;
	created_without_credit: boolean;
}

export interface ProductVisualBulkRun {
	run_id: string;
	status: string;
	total_expected: number;
	total_processed: number;
	total_pending_review: number;
	total_failed: number;
	total_blocked: number;
	total_skipped: number;
	product_ids?: string[];
	errors?: Array<Record<string, string>>;
	provider_operations: number;
	created_without_credit: boolean;
}

export function fetchProductVisualReadiness(
	productId: string,
): Promise<ProductVisualReadiness> {
	return fetchAPI<ProductVisualReadiness>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}`,
	);
}

export function prepareProductCutout(
	productId: string,
): Promise<ProductVisualReadiness> {
	return postAPI<ProductVisualReadiness>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}/cutout/prepare`,
		{},
	);
}

export function rebuildProductCutout(
	productId: string,
): Promise<ProductVisualReadiness> {
	return postAPI<ProductVisualReadiness>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}/cutout/rebuild`,
		{},
	);
}

export function fetchProductVisualBulkPreview(
	limit = 1000,
): Promise<ProductVisualBulkPreview> {
	return fetchAPI<ProductVisualBulkPreview>(
		`/api/product-visual-onboarding/bulk/preview?limit=${encodeURIComponent(String(limit))}`,
	);
}

export function queueProductVisualBulkPrepare(input: {
	preview_digest: string;
	batch_size?: number;
}): Promise<ProductVisualBulkRun> {
	return postAPI<ProductVisualBulkRun>(
		"/api/product-visual-onboarding/bulk/prepare",
		{ confirm: true, ...input },
	);
}

export function fetchProductVisualBulkRun(
	runId: string,
): Promise<ProductVisualBulkRun> {
	return fetchAPI<ProductVisualBulkRun>(
		`/api/product-visual-onboarding/bulk/runs/${encodeURIComponent(runId)}`,
	);
}
