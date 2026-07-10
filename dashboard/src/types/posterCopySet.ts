// Poster Copy Set — poster-NATIVE copy domain (POSTER_BUILDER_V2).
// Fully separate from the video Copy Set types; statuses are namespaced
// POSTER_COPY_* so poster copy can never masquerade as video copy.

export interface PosterObjectiveRecommendation {
	archetype: string;
	recipe_id: string;
	objective: string;
	reason: string;
	source: "DETERMINISTIC" | "AI" | string;
}

export interface PosterAngleRecommendation {
	angle: string;
	rationale: string;
	source: "RECIPE" | "AI" | string;
}

export interface PosterCopyDirection {
	primary_message: string;
	support_message: string;
	proof_points: string[];
	cta: string;
	disclaimer: string;
	tone: string;
	language: string;
	field_provenance: Record<string, string>;
}

export interface PosterCopySet {
	poster_copy_set_id: string;
	product_id: string;
	campaign_id: string;
	objective: string;
	archetype: string;
	angle: string;
	primary_message: string;
	support_message: string;
	proof_points: string[];
	offer: Record<string, unknown> | null;
	cta: string;
	disclaimer: string;
	tone: string;
	language: string;
	variants: unknown[];
	field_provenance: Record<string, string>;
	ai_model: string;
	prompt_version: string;
	status: string;
	version: number;
	parent_poster_copy_set_id: string;
	approved_at: string | null;
	approved_by: string;
	warnings?: string[];
}

export const POSTER_COPY_APPROVAL_PHRASE = "APPROVE_POSTER_COPY_SET";

export interface PosterQAFinding {
	code: string;
	severity: "BLOCK" | "WARN";
	message: string;
	zone_id: string;
}

export interface PosterQAReport {
	ok: boolean;
	findings: PosterQAFinding[];
	block_count: number;
	warn_count: number;
}

export interface PosterDeliverableRow {
	poster_deliverable_id: string;
	product_id: string;
	poster_copy_set_id: string;
	recipe_id: string;
	template_version: string;
	composition_strategy: string;
	background_media_id: string;
	output_path: string;
	output_sha256: string;
	creative_asset_id: string;
	status: "POSTER_DRAFT" | "POSTER_COMPOSED" | "POSTER_SAVED" | string;
}

export interface PosterComposeResponse {
	deliverable: PosterDeliverableRow;
	render_report: Record<string, unknown>;
	qa_report: PosterQAReport;
}

// Creative Library round trip: full reconstruction of a saved poster.
export interface PosterDeliverableReconstruction {
	deliverable: PosterDeliverableRow;
	render_manifest: Record<string, unknown>;
	poster_copy_set: PosterCopySet | null;
	// The saved poster's copy set may since have been SUPERSEDED. Reopen still
	// restores the EXACT historical copy read-only and flags it for the UI.
	poster_copy_set_status?: string;
	poster_copy_set_historical?: boolean;
	qa_report: PosterQAReport | Record<string, unknown>;
	output_available: boolean;
	// Which durable source served the original bytes (DELIVERABLE_FILE |
	// CREATIVE_LIBRARY), and whether it was sha-verified.
	output_source?: string | null;
	output_sha256_verified?: boolean;
}
