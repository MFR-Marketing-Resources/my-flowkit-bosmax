// WRNA Round 3 — typed view of the BACKEND-resolved canonical composition
// plan. The frontend never derives or defaults any of these values: every
// field is displayed exactly as the resolver returned it (absent → "—").

export interface CompositionPlanSuppression {
	property: string;
	mode_value: string;
	resolved_value: string;
	reason: string;
	authority: string;
}

export interface CompositionPlanProvenance {
	constraint_schema?: string;
	active_locks?: string[];
	suppressions?: CompositionPlanSuppression[];
}

export interface CompositionPlan {
	schema_version?: string;
	profile_id?: string;
	creative_mode?: string;
	recipe_id?: string;
	authority_versions?: {
		creative_direction?: string;
		representation_policy?: string;
	};
	provenance?: CompositionPlanProvenance;
	canvas?: {
		frame_ratio?: string;
		safe_margin?: string;
		edge_exclusion?: string;
	};
	reading_order?: string[];
	product?: {
		anchor?: string;
		dominance?: string;
		label_visibility?: string;
		label_style?: string;
		real_world_scale?: string;
		identity_lock?: boolean;
	};
	copy?: {
		copy_side?: string;
		hook_zone?: string;
		subhook_zone?: string;
		usp_zone?: string;
		cta_zone?: string;
		strategy?: string;
	};
	typography?: {
		hook?: string;
		subhook?: string;
		usp?: string;
		cta?: string;
		intensity?: string;
	};
	scene?: {
		lighting?: string;
		human_presence?: string;
		identity_policy?: string;
		face_safe_rule?: string;
		background_complexity?: string;
		prop_density?: string;
		negative_space?: string;
	};
	quality_negative_rules?: string[];
	warnings?: string[];
	blockers?: string[];
	signature?: string;
}
