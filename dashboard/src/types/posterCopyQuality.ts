// Frontend mirror of the poster copy quality guard
// (agent/models/poster_copy_quality.py). Expert e-commerce poster review.

export interface PosterCopyFinding {
	code: string;
	severity: "BLOCK" | "WARN";
	field: string; // headline | support | chips | cta | product_detail | overall
	message: string;
}

export interface PosterCopyQualityReport {
	ok: boolean;
	findings: PosterCopyFinding[];
	block_count: number;
	warn_count: number;
}

export interface PosterCopyQualityRequest {
	archetype: string;
	language: string;
	child_sensitive?: boolean;
	poster_headline: string;
	poster_support_line: string;
	poster_chips: string[];
	poster_cta: string;
	product_detail_line?: string;
	max_chips: number;
}
