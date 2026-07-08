// Frontend mirror of the backend poster recipe / spec contracts
// (agent/models/poster_recipe.py). PR B2 UI consumes GET /api/poster/recipes and
// renders poster_spec / overlay_spec from the prompt-draft response.

export interface PosterZone {
	zone_id: string;
	role: string; // HEADLINE | SUBHEADLINE | CHIP | CTA | FOOTER | ICON_ROW
	source_field: string; // hook | subhook | usp_1 | usp_2 | usp_3 | cta | ""
	x: number;
	y: number;
	w: number;
	h: number;
	align: string;
	font_role: string;
	max_chars: number;
	placeholder: string;
}

export interface PosterRecipe {
	recipe_id: string;
	archetype: string;
	label: string;
	description: string;
	layout_template: string;
	product_placement: string;
	background_scene: string;
	visual_style: string;
	typography_mood: string;
	icon_guidance: string;
	composition_rules: string[];
	safe_zones: string[];
	chip_slots: string[];
	zones: PosterZone[];
	negative_prompt_additions: string[];
	allowed_text_density: string[];
}

export interface PosterSpec {
	recipe_id: string;
	archetype: string;
	layout_template: string;
	product_placement: string;
	background_scene: string;
	visual_style: string;
	typography_mood: string;
	icon_guidance: string;
	composition_rules: string[];
	safe_zones: string[];
	chip_slots: string[];
}

export interface OverlayZone {
	zone_id: string;
	role: string;
	x: number;
	y: number;
	w: number;
	h: number;
	align: string;
	font_role: string;
	max_chars: number;
	text: string;
}

export interface OverlaySpec {
	schema_version: string;
	frame_ratio: string;
	typography_mood: string;
	safe_zones: string[];
	zones: OverlayZone[];
	renderer: string; // "NONE_PHASE_2" — foundation only, no compositor yet
	disclaimer: string;
}
