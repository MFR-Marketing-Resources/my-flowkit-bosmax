import { getAPI, postAPI, postMultipartAPI } from "./client";

export interface CopyIntelligenceDryRunReport {
	source_workbook: string;
	total_source_rows: number;
	usable_rows: number;
	matched_high_confidence: number;
	matched_medium_confidence: number;
	low_confidence_quarantined: number;
	unmatched: number;
	duplicates: number;
	conflicts: number;
	blank_no_copy_rows: number;
	suspicious_cross_product_copy: number;
	examples: Record<string, Array<Record<string, string | number>>>;
	records: unknown[];
}

export interface CopyIntelligenceWorkbookUploadReport {
	source_id: string;
	original_filename: string;
	fingerprint: string;
	sheet_names: string[];
	required_sheets: string[];
}

export interface CopyIntelligenceSeedLedgerRow {
	seed_id: string;
	source_row: number;
	source_product_name: string;
	target_avatar: string | null;
	pain_point: string | null;
	emotion_trigger: string | null;
	dream_outcome: string | null;
	key_ingredients_features: string | null;
	hook_script: string | null;
	cta_script: string | null;
	confidence: string;
	match_method: string;
	status: string;
	source_workbook: string;
	source_sheet: string;
	provenance: Record<string, string>;
	reviewed_by: string | null;
	reviewed_at: string | null;
	review_note: string | null;
}

export interface CopyIntelligenceSeedLedgerResponse {
	total: number;
	items: CopyIntelligenceSeedLedgerRow[];
}

export interface CopyIntelligenceSeedReviewResult {
	seed_id: string;
	previous_status: string;
	new_status: string;
	confidence: string;
	reviewed_by: string;
	reviewed_at: string;
	review_note: string;
}

export interface CopyIntelligenceSeedReviewInput {
	reviewed_by: string;
	review_note: string;
	confirmation_phrase: string;
}

export function uploadCopyIntelligenceWorkbook(workbook: File) {
	const body = new FormData();
	body.append("workbook", workbook);
	return postMultipartAPI<CopyIntelligenceWorkbookUploadReport>(
		"/api/kalodata/copy-intelligence/workbooks",
		body,
	);
}

export function runUploadedCopyIntelligenceDryRun(sourceId: string) {
	return postAPI<CopyIntelligenceDryRunReport>(
		"/api/kalodata/copy-intelligence/dry-run-upload",
		{ source_id: sourceId },
	);
}

export function listCopyIntelligenceSeedLedger(filters: {
	confidence?: string;
	status?: string;
	search?: string;
} = {}) {
	const params = new URLSearchParams();
	for (const [key, value] of Object.entries(filters)) {
		if (value) params.set(key, value);
	}
	const query = params.toString();
	return getAPI<CopyIntelligenceSeedLedgerResponse>(
		`/api/kalodata/copy-intelligence/seeds${query ? `?${query}` : ""}`,
	);
}

export function approveCopyIntelligenceSeed(
	seedId: string,
	input: CopyIntelligenceSeedReviewInput,
) {
	return postAPI<CopyIntelligenceSeedReviewResult>(
		`/api/kalodata/copy-intelligence/seeds/${encodeURIComponent(seedId)}/approve`,
		input,
	);
}

export function rejectCopyIntelligenceSeed(
	seedId: string,
	input: CopyIntelligenceSeedReviewInput,
) {
	return postAPI<CopyIntelligenceSeedReviewResult>(
		`/api/kalodata/copy-intelligence/seeds/${encodeURIComponent(seedId)}/reject`,
		input,
	);
}
