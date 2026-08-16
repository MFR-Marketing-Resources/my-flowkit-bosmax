import { fetchAPI, postAPI, postMultipartAPI } from "./client";
import type { CanvaCutoutWorkflow, ProductVisualReadiness } from "../types";

export type CanvaCapabilityStatus = "READY" | "UNAVAILABLE" | "UNKNOWN" | "PRO_REQUIRED" | "USER_ACTION_REQUIRED";
export type CanvaMethod = "MAGIC_GRAB" | "BACKGROUND_REMOVER" | "MAGIC_LAYERS";

export interface CanvaPreflightInput {
	canva_method?: CanvaMethod;
	design_id?: string;
	design_url?: string;
	login_status: CanvaCapabilityStatus;
	magic_grab_status: CanvaCapabilityStatus;
	background_remover_status: CanvaCapabilityStatus;
	magic_layers_status: CanvaCapabilityStatus;
	transparent_export_status: CanvaCapabilityStatus;
}

export interface CanvaWorkflowEnvelope {
	workflow: CanvaCutoutWorkflow;
	readiness: ProductVisualReadiness;
}

export interface CanvaCutoutBulkPreview {
	eligible_product_ids: string[];
	preview_digest: string;
	counts: {
		eligible: number;
		already_approved: number;
		pending_review: number;
		canva_pro_required: number;
		missing_source: number;
		blocked: number;
		skipped: number;
	};
	remaining: number;
	total_scanned: number;
	execution_policy: string;
	automation_boundary: string;
	bounded_batch?: {
		default_size: number;
		max_size: number;
		estimated_throughput: string;
	};
	provider_operations: number;
	created_without_credit: boolean;
}

export interface CanvaCutoutBulkItem {
	item_id: string;
	product_id: string;
	ordinal: number;
	priority: number;
	workflow_id?: string | null;
	current_stage: string;
	last_error?: string | null;
}

export interface CanvaCutoutBulkRun {
	run_id: string;
	status: string;
	preview_digest: string;
	total_expected: number;
	total_processed: number;
	total_ready: number;
	total_pending_review: number;
	total_failed: number;
	total_blocked: number;
	total_bypassed: number;
	next_index: number;
	product_ids: string[];
	priority_product_ids: string[];
	preflight: Record<string, string>;
	last_error_code?: string | null;
	last_error?: string | null;
	items: CanvaCutoutBulkItem[];
	provider_operations: number;
	created_without_credit: boolean;
	automation_boundary: string;
}

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

export interface ProductOriginalSourceCandidate {
	product_id: string;
	media_id: string;
	sha256: string;
	filename: string;
	mime: string;
	bytes: number;
	width: number;
	height: number;
	status: string;
	uploaded_by?: string;
	created_without_credit: boolean;
}

export function fetchProductVisualReadiness(
	productId: string,
): Promise<ProductVisualReadiness> {
	return fetchAPI<ProductVisualReadiness>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}`,
	);
}

export function fetchCanvaCutoutWorkflow(productId: string): Promise<CanvaCutoutWorkflow> {
	return fetchAPI<CanvaCutoutWorkflow>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}/canva`,
	);
}

export function startCanvaCutout(productId: string): Promise<CanvaWorkflowEnvelope> {
	return postAPI<CanvaWorkflowEnvelope>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}/canva/start`,
		{},
	);
}

export function recordCanvaPreflight(
	productId: string,
	input: CanvaPreflightInput,
): Promise<CanvaWorkflowEnvelope> {
	return postAPI<CanvaWorkflowEnvelope>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}/canva/preflight`,
		input,
	);
}

export function advanceCanvaStage(
	productId: string,
	input: { stage: string; canva_method: CanvaMethod; design_id?: string; design_url?: string },
): Promise<CanvaWorkflowEnvelope> {
	return postAPI<CanvaWorkflowEnvelope>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}/canva/stage`,
		input,
	);
}

export function completeCanvaCutout(
	productId: string,
	file: File,
	input: { canva_method: CanvaMethod; uploaded_by: string; design_id?: string; design_url?: string },
): Promise<CanvaWorkflowEnvelope> {
	const body = new FormData();
	body.append("cutout", file, file.name);
	body.append("canva_method", input.canva_method);
	body.append("uploaded_by", input.uploaded_by);
	if (input.design_id) body.append("design_id", input.design_id);
	if (input.design_url) body.append("design_url", input.design_url);
	return postMultipartAPI<CanvaWorkflowEnvelope>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}/canva/complete`,
		body,
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

export function setProductCutoutTarget(
	productId: string,
	roi: { x: number; y: number; width: number; height: number; selected_by?: string },
): Promise<ProductVisualReadiness> {
	return postAPI<ProductVisualReadiness>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}/cutout/target`,
		roi,
	);
}

// The shared `deleteAPI` helper in ./client returns Promise<void>; this endpoint
// returns the updated readiness, so we go through fetchAPI with method DELETE
// (same pattern getAPI/postAPI use) to keep the typed response.
export function clearProductCutoutTarget(
	productId: string,
): Promise<ProductVisualReadiness> {
	return fetchAPI<ProductVisualReadiness>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}/cutout/target`,
		{ method: "DELETE" },
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

export function uploadOriginalSourceCandidate(
	productId: string,
	file: File,
	uploadedBy = "operator",
): Promise<ProductOriginalSourceCandidate> {
	const body = new FormData();
	body.append("source", file, file.name);
	body.append("uploaded_by", uploadedBy);
	return postMultipartAPI<ProductOriginalSourceCandidate>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}/source/reauthorization`,
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

export interface VisualSetupSaveInput {
	selected_visual: "ORIGINAL" | "ORIGINAL_SOURCE_REAUTHORIZE" | "AUTO" | "MANUAL";
	reviewed_by?: string;
	review_note?: string;
	confirm_identity?: boolean;
	confirm_label_logo?: boolean;
	confirm_geometry_scale?: boolean;
	confirm_product_isolation?: boolean;
	expected_previous_canonical_sha256?: string;
	expected_replacement_sha256?: string;
	replacement_media_id?: string;
}

export function saveProductVisualSetup(
	productId: string,
	input: VisualSetupSaveInput,
): Promise<ProductVisualReadiness> {
	return postAPI<ProductVisualReadiness>(
		`/api/product-visual-onboarding/${encodeURIComponent(productId)}/save-visual-setup`,
		input,
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

export function fetchCanvaCutoutBulkPreview(limit = 1000): Promise<CanvaCutoutBulkPreview> {
	return fetchAPI<CanvaCutoutBulkPreview>(
		`/api/product-visual-onboarding/canva/bulk/preview?limit=${encodeURIComponent(String(limit))}`,
	);
}

export function queueCanvaCutoutBulk(input: {
	preview_digest: string;
	max_products?: number;
	priority_product_ids?: string[];
	preflight: CanvaPreflightInput;
}): Promise<CanvaCutoutBulkRun> {
	return postAPI<CanvaCutoutBulkRun>(
		"/api/product-visual-onboarding/canva/bulk/prepare",
		{ confirm: true, ...input },
	);
}

export function fetchCanvaCutoutBulkRun(runId: string): Promise<CanvaCutoutBulkRun> {
	return fetchAPI<CanvaCutoutBulkRun>(
		`/api/product-visual-onboarding/canva/bulk/runs/${encodeURIComponent(runId)}`,
	);
}

export function pauseCanvaCutoutBulk(runId: string): Promise<CanvaCutoutBulkRun> {
	return postAPI<CanvaCutoutBulkRun>(
		`/api/product-visual-onboarding/canva/bulk/runs/${encodeURIComponent(runId)}/pause`,
		{},
	);
}

export function resumeCanvaCutoutBulk(runId: string, preflight: CanvaPreflightInput): Promise<CanvaCutoutBulkRun> {
	return postAPI<CanvaCutoutBulkRun>(
		`/api/product-visual-onboarding/canva/bulk/runs/${encodeURIComponent(runId)}/resume`,
		{ preflight },
	);
}

export function cancelCanvaCutoutBulk(runId: string): Promise<CanvaCutoutBulkRun> {
	return postAPI<CanvaCutoutBulkRun>(
		`/api/product-visual-onboarding/canva/bulk/runs/${encodeURIComponent(runId)}/cancel`,
		{},
	);
}

export function bypassCanvaCutoutBulkItem(runId: string, productId: string, operator: string, reason: string): Promise<CanvaCutoutBulkRun> {
	return postAPI<CanvaCutoutBulkRun>(
		`/api/product-visual-onboarding/canva/bulk/runs/${encodeURIComponent(runId)}/items/${encodeURIComponent(productId)}/bypass`,
		{ operator, reason },
	);
}
