import { getAPI } from "./client";

export interface RecommendedAvatar {
	avatar_code: string;
	character_name?: string;
	variant?: string;
	environment?: string;
	fit_score: number;
	fit_source: string;
	suitability_notes?: string | null;
}

export interface AvatarRecommendation {
	product_id?: string;
	product_name?: string | null;
	category?: string | null;
	cluster: string;
	cluster_source: string;
	avatar_count: number;
	avatars: RecommendedAvatar[];
}

export function getAvatarRecommendationForProduct(productId: string) {
	return getAPI<AvatarRecommendation>(
		`/api/creative-intelligence/avatar-recommendation?product_id=${encodeURIComponent(productId)}`,
	);
}

// --- Round 2: Scene / Image Prompt templates (read-only) ---

export interface ScenePromptTemplate {
	template_id: string;
	source_category?: string;
	cluster: string;
	cluster_source?: string;
	main_action?: string;
	setting?: string;
	full_prompt_template?: string;
	base_prompt?: string;
	combined_prompt_suggestion?: string;
	negative_prompt?: string;
	variant?: string;
	notes?: string;
	status?: string;
}

export interface SceneGlobalConfig {
	style_suffix?: string;
	negative_prompt?: string;
	common_actions?: Record<string, string>;
}

export interface ScenePromptRecommendation {
	product_id?: string;
	product_name?: string | null;
	category?: string | null;
	cluster: string;
	cluster_source: string;
	template_count: number;
	templates: ScenePromptTemplate[];
	global_config: SceneGlobalConfig;
	cluster_has_templates: boolean;
}

export function getScenePromptRecommendationForProduct(productId: string) {
	return getAPI<ScenePromptRecommendation>(
		`/api/creative-intelligence/scene-prompt-recommendation?product_id=${encodeURIComponent(productId)}`,
	);
}
