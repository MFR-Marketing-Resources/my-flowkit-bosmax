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
	machine_qa?: CampaignMachineQA | null;
	campaign_qa?: CampaignPostCompositionQA | null;
	world_class_review?: WorldClassPosterReview | null;
}

export type CampaignQAStatus = "PASS" | "WARN" | "UNVERIFIED" | "BLOCK";

export interface CampaignQADimension {
	status: CampaignQAStatus;
	evidence: string[];
}

export interface CampaignMachineQA {
	media_id: string;
	machine_qa_status: "PASS" | "WARN" | "FAIL" | "UNVERIFIED";
	product_identity: CampaignQADimension;
	label: CampaignQADimension;
	logo: CampaignQADimension;
	geometry: CampaignQADimension;
	scale: CampaignQADimension;
	perspective: CampaignQADimension;
	contact_shadow: CampaignQADimension;
	lighting_coherence: CampaignQADimension;
	product_background_integration: CampaignQADimension;
	unexpected_marketing_text: CampaignQADimension;
	duplicated_products: CampaignQADimension;
	human_defects: CampaignQADimension;
	findings: string[];
	human_review_required: boolean;
	review_state: string;
}

export interface CampaignPostCompositionQA {
	ok: boolean;
	checks: Record<string, CampaignQADimension>;
	findings: string[];
	block_count: number;
	warn_count: number;
	human_review_required: boolean;
	campaign_review_status:
		| "PENDING_HUMAN_REVIEW"
		| "REVISION_REQUIRED"
		| "APPROVED"
		| "REJECTED";
	clean_key_visual_lineage: boolean;
	copy_provenance_verified: boolean;
	output_sha256: string;
}

export interface WorldClassPosterReview {
	product_identity: number;
	product_integration_physics: number;
	typography_copy_hierarchy: number;
	malaysian_context_authenticity: number;
	conversion_strength: number;
	total: number;
	critical_findings: string[];
	reviewer: string;
	reviewed_at: string;
	review_notes: string;
	rejection_reasons: string[];
	decision: "REJECTED" | "REVISION_REQUIRED" | "APPROVED";
}

export interface CampaignVariant {
	variant_id: string;
	variant_index: number;
	design_route: string;
	layout_variant: string;
	manifest_sha256: string;
	output_url: string;
	key_visual_media_id: string;
	provider_operation_count: number;
	max_retry_operations: number;
	kv_reused: boolean;
}

export interface CampaignVariantsResponse {
	product_id: string;
	poster_deliverable_id: string;
	selected_copy_route: string;
	selected_design_route: string;
	variants: [CampaignVariant, CampaignVariant, CampaignVariant];
	key_visual_reused: boolean;
	provider_operation_count: number;
	max_retry_operations: number;
	warnings: string[];
}

export interface CampaignReviewRequest {
	decision: "REJECTED" | "REVISION_REQUIRED" | "APPROVED";
	reviewer: string;
	product_identity: number;
	product_integration_physics: number;
	typography_copy_hierarchy: number;
	malaysian_context_authenticity: number;
	conversion_strength: number;
	critical_findings?: string[];
	review_notes?: string;
	rejection_reasons?: string[];
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
	// The EXACT canonical composition plan the manifest preserved (empty/absent
	// on the legacy no-mode path) — lets the UI prove compile == displayed plan.
	composition_plan?: import("./posterCompositionPlan").CompositionPlan;
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
