import { getAPI, patchAPI, postAPI } from "./client";

export interface RecommendedAvatar {
	avatar_code: string;
	character_name?: string;
	variant?: string;
	environment?: string;
	fit_score: number;
	fit_source: string;
	suitability_notes?: string | null;
}

export interface AvatarLibraryItem {
	avatar_code: string;
	character_name?: string;
	gender?: string;
	age_band?: string;
	recommended?: boolean;
}

export interface AvatarRecommendation {
	product_id?: string;
	product_name?: string | null;
	category?: string | null;
	// null when the product category is review-required (fail-closed, no plan).
	cluster: string | null;
	cluster_source: string;
	review_required?: boolean;
	avatar_count: number;
	avatars: RecommendedAvatar[];
}

export function getAvatarRecommendationForProduct(productId: string) {
	return getAPI<AvatarRecommendation>(
		`/api/creative-intelligence/avatar-recommendation?product_id=${encodeURIComponent(productId)}`,
	);
}

export function getAvatarRecommendationForCategory(category: string) {
	return getAPI<AvatarRecommendation>(
		`/api/creative-intelligence/avatar-recommendation?category=${encodeURIComponent(category)}`,
	);
}

export interface ProductClusterAudit {
	product_total: number;
	canonical_clusters: string[];
	cluster_counts: Record<string, number>;
	unknown_review_required: number;
	unknown_samples: Array<{ product_id: string; product_name: string }>;
	raw_category_counts: Record<string, number>;
	note: string;
}

export function getProductClusterAudit() {
	return getAPI<ProductClusterAudit>("/api/creative-intelligence/product-cluster-audit");
}

// --- Registry coverage lens (read-only; powers Avatar/Scene Registry cards) ---

export interface RegistryClusterCoverage {
	pool_total: number;
	bridge_active: boolean;
	clusters_covered: string[];
	clusters_missing: string[];
}

export interface RegistryCoverage {
	canonical_clusters: string[];
	cluster_total: number;
	product_total: number;
	avatar: RegistryClusterCoverage & {
		fit_total: number;
		distinct_avatars_in_fit: number;
	};
	scene: RegistryClusterCoverage & { prompt_total: number };
	camera: { preset_total: number; block_groups: string[] };
	used_by: { avatar: string[]; scene: string[] };
}

export function getRegistryCoverage() {
	return getAPI<RegistryCoverage>("/api/creative-intelligence/registry-coverage");
}

// --- Registry reconciliation lens (read-only; mapped / referenced / review) ---

export interface RegistryReconciliation {
	avatar: {
		pool_total: number;
		mapped_to_fit: number;
		referenced_by_selection: number;
		unmapped: number;
		review_candidate_count: number;
		review_candidate_sample: string[];
		mapping_basis: string;
	};
	scene: {
		pool_total: number;
		prompt_template_total: number;
		referenced_by_selection: number;
		pool_to_prompt_mapping: string;
		review_candidate_count: number;
		review_candidate_sample: string[];
		mapping_basis: string;
	};
	selection: {
		total: number;
		distinct_avatar_codes: string[];
		distinct_scene_template_ids: string[];
	};
	disclaimer: string;
}

export function getRegistryReconciliation() {
	return getAPI<RegistryReconciliation>(
		"/api/creative-intelligence/registry-reconciliation",
	);
}

// --- Archive/Delete planning (read-only dry-run; classifies pool entries) ---

export interface CleanupCandidate {
	id: string;
	name?: string;
	classification: string;
	reason: string;
	required_evidence: string;
	product_fit_refs?: number;
	selection_refs?: number;
	asset_refs?: number;
	scene_prompt_refs?: number | null;
}

export interface RegistryCleanupPlanSide {
	total: number;
	classification_counts: Record<string, number>;
	candidates_sample: CleanupCandidate[];
}

export interface RegistryCleanupPlan {
	dry_run: boolean;
	mutations: number;
	future_archive_eligible_total: number;
	owner_approval_required: boolean;
	notice: string;
	classification_legend: Record<string, string>;
	avatar: RegistryCleanupPlanSide;
	scene: RegistryCleanupPlanSide;
}

export function getRegistryCleanupPlan() {
	return getAPI<RegistryCleanupPlan>(
		"/api/creative-intelligence/registry-cleanup-plan",
	);
}

// --- Round 3: Product-first scene context promotion owner review ---

export type ScenePromotionDecision =
	| "PENDING"
	| "APPROVED_FOR_FUTURE_PROMOTION"
	| "REJECTED"
	| "STALE_REVIEW_REQUIRED";

export interface ScenePromotionCandidate {
	source_template_id: string;
	source_category: string | null;
	setting: string | null;
	candidate_fingerprint: string;
	proposed_scene_code: string;
	proposed_scene_name: string;
	background_prompt: string;
	prompt_v1: string;
	safety_block: string;
	usage_tags: string;
	decision: ScenePromotionDecision;
	reviewer_note: string | null;
	reviewed_at: string | null;
	stale_review_required: boolean;
	activation_status: "NOT_ACTIVATED";
}

export interface ScenePromotionQuarantineItem {
	source_template_id: string;
	source_category?: string | null;
	setting?: string | null;
	reason: string;
	duplicate_scene_code?: string;
}

export interface ScenePromotionDecisionCounts {
	PENDING: number;
	APPROVED_FOR_FUTURE_PROMOTION: number;
	REJECTED: number;
	STALE_REVIEW_REQUIRED: number;
}

export interface ScenePromotionProductReview {
	dry_run: true;
	activation_allowed: false;
	registry_mutations: 0;
	product_id: string;
	product_name: string | null;
	category: string | null;
	cluster: string | null;
	cluster_source: string;
	review_required: boolean;
	product_suitability_template_count: number;
	candidate_count: number;
	quarantine_count: number;
	decision_counts: ScenePromotionDecisionCounts;
	candidates: ScenePromotionCandidate[];
	quarantine: ScenePromotionQuarantineItem[];
	message?: string;
	source?: string;
}

export interface ScenePromotionReviewItem {
	source_template_id: string;
	candidate_fingerprint: string;
	decision: Exclude<ScenePromotionDecision, "STALE_REVIEW_REQUIRED">;
	reviewer_note?: string | null;
}

export interface ScenePromotionReviewRequest extends ScenePromotionReviewItem {
	reviewed_via_product_id: string;
}

export interface ScenePromotionBulkReviewRequest {
	reviewed_via_product_id: string;
	items: ScenePromotionReviewItem[];
}

export function getScenePromotionProductReview(productId: string) {
	return getAPI<ScenePromotionProductReview>(
		`/api/creative-intelligence/scene-context-promotion/review/product/${encodeURIComponent(productId)}`,
	);
}

export function submitScenePromotionReview(payload: ScenePromotionReviewRequest) {
	return postAPI<ScenePromotionProductReview>(
		"/api/creative-intelligence/scene-context-promotion/review",
		payload,
	);
}

export function submitScenePromotionBulkReview(
	payload: ScenePromotionBulkReviewRequest,
) {
	return postAPI<ScenePromotionProductReview>(
		"/api/creative-intelligence/scene-context-promotion/review/bulk",
		payload,
	);
}

export type ActivationStatus = "NOT_APPROVED" | "STALE_REVIEW_REQUIRED" | "BLOCKED" | "ELIGIBLE_FOR_CONTROLLED_PROMOTION" | "ACTIVE_IN_REGISTRY";
export interface ActivationEligibilityCandidate { source_template_id: string; candidate_fingerprint: string; cluster: string; current_review_decision: ScenePromotionDecision; stale_review_required: boolean; activation_eligible: boolean; activation_blocker: string | null; activation_status: ActivationStatus; existing_scene_code: string | null; proposed_scene_code: string | null; generation_status: "NOT_GENERATED"; }
export interface ActivationEligibilityResponse { product_id: string; cluster: string | null; candidate_count: number; registry_mutations: 0; candidates: ActivationEligibilityCandidate[]; }
export interface ActivationResult { activation_id: string; source_template_id: string; candidate_fingerprint: string; product_id: string; cluster: string; scene_code: string; scene_name: string; activation_status: "ACTIVE_IN_REGISTRY"; generation_status: "NOT_GENERATED"; idempotent: boolean; registry_scene_count: number; registry_mutations: number; provider_calls: 0; generation_jobs: 0; credits_used: 0; }
export interface BulkActivationResult { requested_count: number; activated_count: number; idempotent_count: number; registry_scene_count: number; items: ActivationResult[]; registry_mutations: number; provider_calls: 0; generation_jobs: 0; credits_used: 0; }
export interface ActivationHistoryEvent { activation_id: string; source_template_id: string; reviewed_via_product_id: string | null; cluster: string; scene_code: string; scene_name: string; activated_by: string; activation_note: string | null; activated_at: string; }
export interface ActivationHistoryResponse { count: number; events: ActivationHistoryEvent[]; registry_mutations: 0; provider_calls: 0; generation_jobs: 0; credits_used: 0; }
export interface ActivationRequest { reviewed_via_product_id: string; source_template_id: string; candidate_fingerprint: string; confirmation: "PROMOTE_TO_ACTIVE_REGISTRY"; activated_by: string; activation_note?: string | null; }
export interface BulkActivationRequest { reviewed_via_product_id: string; items: Pick<ActivationRequest, "source_template_id" | "candidate_fingerprint">[]; confirmation: "PROMOTE_TO_ACTIVE_REGISTRY"; activated_by: string; activation_note?: string | null; }
export function getScenePromotionActivationEligibility(productId: string) { return getAPI<ActivationEligibilityResponse>(`/api/creative-intelligence/scene-context-promotion/activation/product/${encodeURIComponent(productId)}`); }
export function activateScenePromotion(payload: ActivationRequest) { return postAPI<ActivationResult>("/api/creative-intelligence/scene-context-promotion/activation", payload); }
export function activateScenePromotionBulk(payload: BulkActivationRequest) { return postAPI<BulkActivationResult>("/api/creative-intelligence/scene-context-promotion/activation/bulk", payload); }
export function getScenePromotionActivationHistory(productId?: string, sourceTemplateId?: string, limit = 100) { const query = new URLSearchParams({ limit: String(limit) }); if (productId) query.set("product_id", productId); if (sourceTemplateId) query.set("source_template_id", sourceTemplateId); return getAPI<ActivationHistoryResponse>(`/api/creative-intelligence/scene-context-promotion/activation/history?${query}`); }

export interface ClusterCoverageRow { cluster: string; eligible_active_scene_count: number; primary_scene_count: number; shared_compatible_scene_count: number; gap_to_target: number; eligible_scene_codes: string[]; }
export interface ClusterCoverageResponse { canonical_clusters: string[]; target_per_cluster: number; active_scene_total: number; classified_scene_total: number; review_required_scene_total: number; shared_scene_total: number; per_cluster: ClusterCoverageRow[]; milestone_complete: boolean; registry_mutations: 0; }
export interface ClusterAwareSceneProfile { scene_code: string; scene_name: string; primary_cluster: string | null; compatible_clusters: string[]; cluster_classification_status: "CLASSIFIED" | "REVIEW_REQUIRED"; }
export interface SceneClassificationResponse { active_scene_total: number; registry_mutations: 0; scenes: ClusterAwareSceneProfile[]; }
export function getSceneContextClusterCoverage() { return getAPI<ClusterCoverageResponse>("/api/workspace/scene-context-registry/cluster-coverage"); }
export function getSceneContextClassification() { return getAPI<SceneClassificationResponse>("/api/workspace/scene-context-registry/classification"); }

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
	cluster: string | null;
	cluster_source: string;
	review_required?: boolean;
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
	cluster: string | null;
	cluster_source: string;
	review_required?: boolean;
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
	// Multi-select: the full chosen set (primary = first). Server always returns
	// these, deriving a one-item list from the primary for legacy single rows.
	selected_avatar_codes?: string[];
	selected_scene_template_ids?: string[];
	selected_camera_preset_codes?: string[];
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

export interface DefaultCreativeSelection {
	selected_avatar_codes: string[];
	selected_scene_template_ids: string[];
	selected_camera_preset_codes: string[];
	source?: string;
}

export interface CreativeSetup {
	product_id: string;
	product_name?: string | null;
	category?: string | null;
	cluster: string | null;
	cluster_source: string;
	review_required?: boolean;
	recommended_avatars: RecommendedAvatar[];
	avatar_library?: AvatarLibraryItem[];
	default_selection?: DefaultCreativeSelection | null;
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
	selected_avatar_codes?: string[] | null;
	selected_scene_template_ids?: string[] | null;
	selected_camera_preset_codes?: string[] | null;
	selected_block_purpose?: string | null;
	selected_content_type?: string | null;
	notes?: string | null;
}

export interface BulkAutoSetupResult {
	targets: number;
	done: number;
	skipped: number;
	failed: number;
	reasons: Record<string, number>;
	errors: { product_id: string; error: string }[];
	approved: boolean;
	applied: boolean;
}

export function getCreativeSetupForProduct(productId: string) {
	return getAPI<CreativeSetup>(
		`/api/creative-intelligence/creative-setup?product_id=${encodeURIComponent(productId)}`,
	);
}

export function saveCreativeSelection(payload: SaveCreativeSelectionPayload) {
	return postAPI<SavedCreativeSelection>("/api/creative-intelligence/creative-selection", payload);
}

/**
 * Bulk auto-fill each eligible product's creative selection from its top-scored
 * recommendation, optionally APPROVING it. `dry_run` defaults true on the server;
 * pass `dry_run: false` to actually write.
 */
export function bulkAutoSetupCreativeSelection(payload: {
	product_ids?: string[] | null;
	approve?: boolean;
	dry_run?: boolean;
	limit?: number | null;
}) {
	return postAPI<BulkAutoSetupResult>(
		"/api/creative-intelligence/creative-selection/bulk-auto-setup",
		payload,
	);
}

/** Avatar-only partial update — preserves scene/camera/block/content/notes server-side. */
export function patchCreativeSelectionAvatar(payload: {
	product_id: string;
	selected_avatar_code: string;
	notes_append?: string | null;
}) {
	return patchAPI<SavedCreativeSelection>(
		"/api/creative-intelligence/creative-selection/avatar",
		payload,
	);
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
