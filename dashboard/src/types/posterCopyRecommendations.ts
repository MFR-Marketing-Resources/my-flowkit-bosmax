export type PosterKitSource =
	| "APPROVED_COPY_SET"
	| "DRAFT_COPY_SET"
	| "AI_CANDIDATE"
	| "FALLBACK_TEMPLATE";

export type PosterKitStatus = "approved" | "draft" | "candidate";

export interface PosterCopyKit {
	kit_id: string;
	status: PosterKitStatus;
	source: PosterKitSource;
	angle: string;
	hook: string;
	subhook: string;
	usp_1: string;
	usp_2: string;
	usp_3: string;
	cta: string;
	poster_type: string;
	visual_route: string;
	human_presence_mode: string;
	frame_ratio: string;
	language: string;
	text_density: string;
	background_environment?: string;
	brand_tone?: string;
	safety_notes: string[];
	blocked_reasons: string[];
	copy_set_id?: string | null;
	// True only for an approved Copy Set whose formula-validation verdict passed.
	formula_validated?: boolean;
}

export interface PosterCopyRecommendationsRequest {
	product_id: string;
	poster_objective?: string;
	poster_type?: string;
	frame_ratio?: string;
	language?: string;
	visual_route?: string;
	human_presence_mode?: string;
	text_density?: string;
	refresh_ai?: boolean;
}

export interface PosterCopyRecommendationsResponse {
	product_id: string;
	product_display_name?: string | null;
	poster_status: string;
	generation_allowed: boolean;
	recommendation_source: string;
	recommendations: PosterCopyKit[];
	blocked_reasons: string[];
	repair_actions: Record<string, unknown>[];
	ai_provider_status: Record<string, unknown>;
	warnings: string[];
}

export type PosterWorkingMode = "auto" | "guided" | "manual";