import { postAPI, postMultipartAPI } from "./client";

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
