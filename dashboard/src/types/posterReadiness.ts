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
	angle: string;
	hook: string;
	subhook: string;
	usp_1: string;
	usp_2: string;
	usp_3: string;
	cta: string;
	operator_notes: string;
}

export const EMPTY_POSTER_DRAFT: PosterBuilderDraft = {
	poster_objective: "",
	poster_type: "",
	visual_route: "",
	human_presence_mode: "",
	frame_ratio: "9:16",
	language: "ms",
	text_density: "medium",
	angle: "",
	hook: "",
	subhook: "",
	usp_1: "",
	usp_2: "",
	usp_3: "",
	cta: "",
	operator_notes: "",
};