import { getAPI, patchAPI, postAPI } from "./client";

// ─── Copy Set client (Copy Strategy Studio Phase 2) ─────────
// Wraps the Phase 1 backend at /api/copy-sets. Pre-generation copywriting only:
// this client never touches the Google Flow execution lane or the prompt compiler.

export const COPY_SET_APPROVAL_PHRASE = "APPROVE_COPY_SET";

export type CopySetStatus =
	| "DRAFT_COPY"
	| "COPY_REVIEW_REQUIRED"
	| "COPY_APPROVED"
	| "COPY_REJECTED";

export interface CopySetCompleteness {
	complete: boolean;
	missing_fields: string[];
}

export interface CopySetSafety {
	safe: boolean;
	violations: string[];
	detail: Record<string, string>;
}

export interface CopySetClaimReview {
	completeness?: CopySetCompleteness;
	safety?: CopySetSafety;
	route_type?: string;
	approved?: boolean;
}

export interface CopySet {
	copy_set_id: string;
	product_id: string;
	angle: string;
	hook: string;
	subhook: string;
	usp_set: string[];
	cta: string;
	platform: string;
	language: string;
	route_type: string;
	formula_family: string;
	status: CopySetStatus;
	dedupe_key: string;
	source: string;
	provenance: Record<string, unknown>;
	claim_review: CopySetClaimReview;
	reviewer_note: string | null;
	approved_at: string | null;
	approved_by: string | null;
	created_at: string | null;
	updated_at: string | null;
}

export interface CopySetGeneratePayload {
	product_id: string;
	angle?: string;
	hook?: string;
	subhook?: string;
	usp_set?: string[];
	cta?: string;
	platform?: string;
	language?: string;
	route_type?: string;
	formula_family?: string;
	content_style_mode?: string;
}

export interface CopySetGenerateResult {
	copy_set: CopySet;
	created: boolean;
	dedupe_match: boolean;
}

export interface CopySetPatchPayload {
	angle?: string;
	hook?: string;
	subhook?: string;
	usp_set?: string[];
	cta?: string;
	platform?: string;
	language?: string;
	route_type?: string;
	formula_family?: string;
	reviewer_note?: string;
}

export interface CopySetApprovePayload {
	approval_phrase: string;
	reviewer_note?: string;
	approved_by?: string;
}

export interface CopySetRejectPayload {
	reviewer_note: string;
}

export interface CopySetRegeneratePayload {
	angle?: string;
	platform?: string;
	language?: string;
	route_type?: string;
	formula_family?: string;
	content_style_mode?: string;
}

export interface CopySetListResponse {
	product_id: string;
	items: CopySet[];
}

export async function generateCopySet(
	payload: CopySetGeneratePayload,
): Promise<CopySetGenerateResult> {
	return postAPI<CopySetGenerateResult>("/api/copy-sets/generate", payload);
}

export async function listCopySetsForProduct(
	productId: string,
): Promise<CopySetListResponse> {
	return getAPI<CopySetListResponse>(
		`/api/copy-sets/product/${encodeURIComponent(productId)}`,
	);
}

export async function getCopySet(copySetId: string): Promise<CopySet> {
	return getAPI<CopySet>(`/api/copy-sets/${encodeURIComponent(copySetId)}`);
}

export async function patchCopySet(
	copySetId: string,
	payload: CopySetPatchPayload,
): Promise<CopySet> {
	return patchAPI<CopySet>(
		`/api/copy-sets/${encodeURIComponent(copySetId)}`,
		payload,
	);
}

export async function approveCopySet(
	copySetId: string,
	payload: CopySetApprovePayload,
): Promise<CopySet> {
	return postAPI<CopySet>(
		`/api/copy-sets/${encodeURIComponent(copySetId)}/approve`,
		payload,
	);
}

export async function rejectCopySet(
	copySetId: string,
	payload: CopySetRejectPayload,
): Promise<CopySet> {
	return postAPI<CopySet>(
		`/api/copy-sets/${encodeURIComponent(copySetId)}/reject`,
		payload,
	);
}

export async function regenerateCopySet(
	copySetId: string,
	payload?: CopySetRegeneratePayload,
): Promise<CopySet> {
	return postAPI<CopySet>(
		`/api/copy-sets/${encodeURIComponent(copySetId)}/regenerate`,
		payload ?? {},
	);
}
