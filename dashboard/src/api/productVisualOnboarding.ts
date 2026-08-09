import { fetchAPI, postAPI, postMultipartAPI } from "./client";
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
	execution_policy?: string;
	bounded_batch?: {
		default_size: number;
		max_size: number;
		estimated_throughput: string;
	};
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
	eligible_total?: number;
	max_products?: number;
	estimated_throughput?: string | null;
}

export interface ProductVisualCutoutHistoryItem {
	history_id: string | null;
	source_kind: string;
	review_status: string;
	active: boolean;
	preview_url: string;
	provenance: Record<string, unknown>;
}

export interface ProductVisualCutoutHistory {
	product_id: string;
	current: ProductVisualCutoutHistoryItem[];
	history: ProductVisualCutoutHistoryItem[];
	count: number;
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

export function uploadManualProductCutout(
	productId: string,
	file: File,
	uploadedBy: string,
): Promise<ProductVisualReadiness> {
	const body = new FormData();
	body.append("cutout", file, file.name);
	body.append("uploaded_by", uploadedBy);
	return postMultipartAPI<ProductVisualReadiness>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}/cutout/manual`,
		body,
	);
}

export function rejectProductCutout(
	productId: string,
	operator: string,
	reason: string,
): Promise<ProductVisualReadiness> {
	return postAPI<ProductVisualReadiness>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}/cutout/reject`,
		{ operator, reason },
	);
}

export function useOriginalProductFallback(
	productId: string,
	operator: string,
	reason: string,
): Promise<ProductVisualReadiness> {
	return postAPI<ProductVisualReadiness>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}/cutout/fallback`,
		{ operator, reason },
	);
}

export function fetchProductCutoutHistory(
	productId: string,
): Promise<ProductVisualCutoutHistory> {
	return fetchAPI<ProductVisualCutoutHistory>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}/cutout/history`,
	);
}

export function productVisualCutoutPreviewUrl(
	productId: string,
	variant: "original" | "auto" | "manual" | "active" | "history",
	historyId?: string | null,
): string {
	const query = historyId ? `?history_id=${encodeURIComponent(historyId)}` : "";
	return `/api/product-visual-onboarding/${encodeURIComponent(productId)}/cutout/preview/${variant}${query}`;
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
	max_products?: number;
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
