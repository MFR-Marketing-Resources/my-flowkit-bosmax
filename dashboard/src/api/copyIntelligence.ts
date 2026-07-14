import { postAPI } from "./client";

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

export function runCopyIntelligenceDryRun(sourcePath: string) {
	return postAPI<CopyIntelligenceDryRunReport>(
		"/api/kalodata/copy-intelligence/dry-run",
		{ source_path: sourcePath },
	);
}
