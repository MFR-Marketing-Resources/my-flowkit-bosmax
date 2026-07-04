import type {
	AICopyAssistResponse,
	CopySet,
	CopySetGenerateResponse,
	CopySetListResponse,
} from "../types";
import { COPY_SET_APPROVAL_PHRASE } from "../types";
import { fetchAPI, patchAPI, postAPI } from "./client";

// Copy Set API client (Copy Strategy Studio) — read/review/approve/select the
// approvable copywriting bundle that binds into the deterministic final prompt
// compiler. No AI provider execution: generation reuses landbank / copy signals.

export async function listCopySetsForProduct(
	productId: string,
): Promise<CopySetListResponse> {
	return fetchAPI<CopySetListResponse>(
		`/api/copy-sets/product/${encodeURIComponent(productId)}`,
	);
}

export async function generateCopySet(input: {
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
}): Promise<CopySetGenerateResponse> {
	return postAPI<CopySetGenerateResponse>("/api/copy-sets/generate", input);
}

// AI Copy Assist — generate reviewable candidate Copy Set(s). Candidates come
// back as COPY_REVIEW_REQUIRED and must be approved before they can be selected.
export async function generateAICopyCandidate(input: {
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
	operator_notes?: string;
	candidate_count?: number;
}): Promise<AICopyAssistResponse> {
	return postAPI<AICopyAssistResponse>("/api/copy-sets/ai-assist", input);
}

export async function regenerateCopySet(
	copySetId: string,
	overrides?: Record<string, unknown>,
): Promise<CopySet> {
	return postAPI<CopySet>(
		`/api/copy-sets/${encodeURIComponent(copySetId)}/regenerate`,
		overrides ?? {},
	);
}

export async function patchCopySet(
	copySetId: string,
	patch: Partial<
		Pick<
			CopySet,
			| "angle"
			| "hook"
			| "subhook"
			| "usp_set"
			| "cta"
			| "platform"
			| "language"
			| "route_type"
			| "formula_family"
		>
	> & { reviewer_note?: string },
): Promise<CopySet> {
	return patchAPI<CopySet>(
		`/api/copy-sets/${encodeURIComponent(copySetId)}`,
		patch,
	);
}

export async function approveCopySet(
	copySetId: string,
	input?: { reviewer_note?: string; approved_by?: string },
): Promise<CopySet> {
	return postAPI<CopySet>(
		`/api/copy-sets/${encodeURIComponent(copySetId)}/approve`,
		{ approval_phrase: COPY_SET_APPROVAL_PHRASE, ...(input ?? {}) },
	);
}

export async function rejectCopySet(
	copySetId: string,
	reviewerNote: string,
): Promise<CopySet> {
	return postAPI<CopySet>(
		`/api/copy-sets/${encodeURIComponent(copySetId)}/reject`,
		{ reviewer_note: reviewerNote },
	);
}
