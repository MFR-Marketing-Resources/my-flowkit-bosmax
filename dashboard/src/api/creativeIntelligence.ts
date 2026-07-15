import { getAPI, postAPI } from "./client";

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

// --- Round 3: Camera / Video Presets (read-only) ---

export interface CameraPreset {
	preset_code: string;
	preset_name?: string;
	shot_type?: string;
	distance_angle?: string;
	movement?: string;
	block_group?: string;
	source_row?: number;
}

export interface CameraBlockRecommendation {
	block_purpose?: string;
	content_type?: string;
	recommended_preset?: CameraPreset | null;
	alt_presets: CameraPreset[];
	source_row?: number;
}

export interface CameraVocabularyEntry {
	code?: string;
	name?: string;
	shot_type?: string;
	description?: string;
	effect?: string;
	use_case?: string;
}

export interface CameraPresetRecommendation {
	product_id?: string;
	product_name?: string | null;
	category?: string | null;
	cluster: string;
	cluster_source: string;
	block_groups: string[];
	block_recommendation_count: number;
	block_recommendations: CameraBlockRecommendation[];
	library: {
		shot_distances: CameraVocabularyEntry[];
		camera_angles: CameraVocabularyEntry[];
		camera_movements: CameraVocabularyEntry[];
		ecomm_shot_types: CameraVocabularyEntry[];
		named_presets: CameraPreset[];
	};
	filtered_by: { block: string | null; content_type: string | null };
	has_recommendations: boolean;
}

export function getCameraPresetRecommendationForProduct(productId: string) {
	return getAPI<CameraPresetRecommendation>(
		`/api/creative-intelligence/camera-preset-recommendation?product_id=${encodeURIComponent(productId)}`,
	);
}

// --- Round 4: unified creative setup + saved selection (review-gated) ---

export interface SavedCreativeSelection {
	product_id: string;
	selection_id: string;
	cluster?: string | null;
	cluster_source?: string | null;
	selected_avatar_code?: string | null;
	selected_scene_template_id?: string | null;
	selected_camera_preset_code?: string | null;
	selected_block_purpose?: string | null;
	selected_content_type?: string | null;
	notes?: string | null;
	status: "DRAFT" | "APPROVED" | "REJECTED";
	reviewer_note?: string | null;
	created_at?: string;
	updated_at?: string;
	reviewed_at?: string | null;
	preview?: {
		cluster?: string | null;
		cluster_source?: string | null;
		avatar?: Record<string, unknown> | null;
		scene_template?: ScenePromptTemplate | null;
		camera_preset?: CameraPreset | null;
		not_for_generation?: boolean;
		note?: string;
	} | null;
}

export interface CreativeSetup {
	product_id: string;
	product_name?: string | null;
	category?: string | null;
	cluster: string;
	cluster_source: string;
	recommended_avatars: RecommendedAvatar[];
	recommended_scene_templates: ScenePromptTemplate[];
	camera_block_recommendations: CameraBlockRecommendation[];
	camera_library: CameraPresetRecommendation["library"];
	saved_selection: SavedCreativeSelection | null;
}

export interface SaveCreativeSelectionPayload {
	product_id: string;
	selected_avatar_code?: string | null;
	selected_scene_template_id?: string | null;
	selected_camera_preset_code?: string | null;
	selected_block_purpose?: string | null;
	selected_content_type?: string | null;
	notes?: string | null;
}

export function getCreativeSetupForProduct(productId: string) {
	return getAPI<CreativeSetup>(
		`/api/creative-intelligence/creative-setup?product_id=${encodeURIComponent(productId)}`,
	);
}

export function saveCreativeSelection(payload: SaveCreativeSelectionPayload) {
	return postAPI<SavedCreativeSelection>("/api/creative-intelligence/creative-selection", payload);
}

export function reviewCreativeSelection(productId: string, action: "APPROVE" | "REJECT", reviewerNote?: string) {
	return postAPI<SavedCreativeSelection>("/api/creative-intelligence/creative-selection/review", {
		product_id: productId,
		action,
		reviewer_note: reviewerNote ?? null,
	});
}

// --- Round 5: gated generation handoff preview (APPROVED-only, read-only) ---

export interface CreativeHandoff {
	product_id: string;
	product_name: string;
	selection_id?: string | null;
	selection_status: string;
	cluster?: string | null;
	cluster_source?: string | null;
	avatar: { avatar_code?: string | null; character_name?: string | null; resolved_descriptor?: string | null };
	scene_template: {
		template_id?: string | null;
		variant?: string | null;
		main_action?: string | null;
		setting?: string | null;
		raw_prompt_template?: string | null;
	};
	camera_preset: {
		preset_code?: string | null;
		preset_name?: string | null;
		shot_type?: string | null;
		distance_angle?: string | null;
		movement?: string | null;
	};
	resolved_prompt_preview?: string | null;
	placeholders_resolved: Record<string, boolean>;
	provenance: Record<string, unknown>;
	auto_generated: boolean;
	requires_confirmation: boolean;
	handoff_status: string;
	note: string;
}

export function getCreativeHandoffForProduct(productId: string) {
	return getAPI<CreativeHandoff>(
		`/api/creative-intelligence/creative-handoff?product_id=${encodeURIComponent(productId)}`,
	);
}
