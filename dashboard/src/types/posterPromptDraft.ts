export type PromptPackageStatus =
	| "DRAFT_READY"
	| "PREVIEW_ONLY"
	| "BLOCKED"
	| "REPAIR_REQUIRED";

export interface PosterCopyLayout {
	hook: string;
	subhook: string;
	usp: string[];
	cta: string;
}

export interface PosterPromptDraftRequest {
	product_id: string;
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

export interface PosterPromptDraftResponse {
	product_id: string;
	product_display_name?: string | null;
	poster_status: string;
	prompt_package_status: PromptPackageStatus;
	generation_allowed: boolean;
	production_allowed: boolean;
	restricted_mode: boolean;
	poster_prompt: string;
	negative_prompt: string;
	copy_layout: PosterCopyLayout;
	visual_instruction: string;
	text_overlay_instruction: string;
	product_truth_lock: string;
	safety_guardrails: string[];
	blocked_reasons: string[];
	repair_actions: Record<string, unknown>[];
	readiness_meta: Record<string, unknown>;
	operator_notes: string;
	validation_warnings?: string[];
}