export type PosterReadinessStatus =
	| "POSTER_READY"
	| "POSTER_READY_RESTRICTED"
	| "POSTER_REPAIR_REQUIRED"
	| "POSTER_PREVIEW_ONLY"
	| "POSTER_BLOCKED";

export type PosterImageTier =
	| "PRODUCT_HERO_POSTER_READY"
	| "PRODUCT_IMAGE_PROMPT_READY"
	| "TEXT_ONLY_POSTER_READY"
	| "IMAGE_MISSING";

export interface PosterRepairAction {
	action_code: string;
	label: string;
	severity: string;
	allowed_now?: boolean;
	auto_executable?: boolean;
	requires_human_approval?: boolean;
	recommended_endpoint?: string | null;
	recommended_future_endpoint?: string | null;
	manual_review_required?: boolean;
	next_check?: string;
	expected_status_after_success?: string | null;
	expected_status_if_no_other_blockers?: string | null;
	notes?: string | null;
}

export interface PosterClaimRoute {
	claim_risk_level?: string | null;
	claim_gate?: string | null;
	claim_safe_copy_status?: string | null;
	safe_claim_clearance_required: boolean;
	safe_claim_clearance_status: string;
	restricted_safe_poster_route_verified: boolean;
}

export interface PosterMappingRoute {
	mapping_status?: string | null;
	mapping_ready: boolean;
	mapping_review_status?: string | null;
}

export interface PosterApprovalRoute {
	img_approved: boolean;
	approved_modes: string[];
	production_prompt_approval_status?: string | null;
}

export interface PosterReadinessResponse {
	product_id: string;
	product_display_name?: string | null;
	poster_status: PosterReadinessStatus;
	generation_allowed: boolean;
	restricted_generation_required: boolean;
	preview_allowed: boolean;
	production_allowed: boolean;
	blockers: string[];
	repair_actions: PosterRepairAction[];
	image_tier: PosterImageTier;
	claim_route: PosterClaimRoute;
	mapping_route: PosterMappingRoute;
	approval_route: PosterApprovalRoute;
	next_best_action?: string | null;
	recheck_required_after_repair: boolean;
	notes: string[];
	diagnostics?: Record<string, unknown>;
}

export interface PosterBuilderDraft {
	poster_objective: string;
	poster_type: string;
	visual_route: string;
	human_presence_mode: string;
	frame_ratio: string;
	language: string;
	text_density: string;
	// Poster copy (short — see POSTER_COPY_LIMITS). Angle is a STRATEGY concept, not a
	// poster text field, so it is intentionally NOT part of the poster copy draft.
	hook: string;
	subhook: string;
	usp_1: string;
	usp_2: string;
	usp_3: string;
	cta: string;
	operator_notes: string;
	// Copy provenance (Phase D). copy_source is the kit source the copy came from
	// ("APPROVED_COPY_SET" / "DRAFT_COPY_SET" / "AI_CANDIDATE" / "FALLBACK_TEMPLATE" /
	// "manual"). Non-approved copy is review-only unless copy_fallback_confirmed.
	copy_source: string;
	copy_set_id: string;
	copy_fallback_confirmed: boolean;
	// Approved poster-native copy set (POSTER_BUILDER_V2). When set, the backend
	// projects its fields into the zone copy and treats the package as
	// production-eligible. Any manual copy edit clears it.
	poster_copy_set_id: string;
	// Poster recipe (V2). Selected recipe/archetype id; drives the recipe-first
	// composer path. Empty = legacy no-recipe path.
	poster_recipe_id: string;
}

export const EMPTY_POSTER_DRAFT: PosterBuilderDraft = {
	poster_objective: "",
	poster_type: "",
	visual_route: "",
	human_presence_mode: "",
	frame_ratio: "9:16",
	language: "ms",
	text_density: "medium",
	hook: "",
	subhook: "",
	usp_1: "",
	usp_2: "",
	usp_3: "",
	cta: "",
	operator_notes: "",
	copy_source: "manual",
	copy_set_id: "",
	copy_fallback_confirmed: false,
	poster_copy_set_id: "",
	poster_recipe_id: "",
};