// Enums
export type RequestType =
	| "GENERATE_IMAGE"
	| "REGENERATE_IMAGE"
	| "EDIT_IMAGE"
	| "GENERATE_VIDEO"
	| "REGENERATE_VIDEO"
	| "GENERATE_VIDEO_REFS"
	| "TRUE_F2V"
	| "UPSCALE_VIDEO"
	| "GENERATE_CHARACTER_IMAGE"
	| "REGENERATE_CHARACTER_IMAGE"
	| "EDIT_CHARACTER_IMAGE";
export type StatusType = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";
export type Orientation = "VERTICAL" | "HORIZONTAL";
export type ChainType = "ROOT" | "CONTINUATION" | "INSERT";
export type EntityType =
	| "character"
	| "location"
	| "creature"
	| "visual_asset"
	| "generic_troop"
	| "faction";
export type ProjectStatus = "ACTIVE" | "ARCHIVED" | "DELETED";

// Models — match the Python models exactly
export interface Project {
	id: string;
	name: string;
	description: string | null;
	story: string | null;
	thumbnail_url: string | null;
	language: string;
	status: ProjectStatus;
	user_paygate_tier: string | null;
	material: string;
	narrator_voice: string | null;
	narrator_ref_audio: string | null;
	created_at: string;
	updated_at: string;
}

export interface Character {
	id: string;
	name: string;
	entity_type: EntityType;
	description: string | null;
	image_prompt: string | null;
	voice_description: string | null;
	reference_image_url: string | null;
	media_id: string | null;
	created_at: string;
	updated_at: string;
}

export interface Video {
	id: string;
	project_id: string;
	title: string;
	description: string | null;
	display_order: number;
	status: string;
	vertical_url: string | null;
	horizontal_url: string | null;
	thumbnail_url: string | null;
	duration: number | null;
	resolution: string | null;
	created_at: string;
	updated_at: string;
}

export interface Scene {
	id: string;
	video_id: string;
	display_order: number;
	prompt: string | null;
	image_prompt: string | null;
	video_prompt: string | null;
	character_names: string | null; // JSON string array
	parent_scene_id: string | null;
	chain_type: ChainType;
	source: string | null;
	vertical_image_url: string | null;
	vertical_image_media_id: string | null;
	vertical_image_status: StatusType;
	vertical_video_url: string | null;
	vertical_video_media_id: string | null;
	vertical_video_status: StatusType;
	vertical_upscale_url: string | null;
	vertical_upscale_media_id: string | null;
	vertical_upscale_status: StatusType;
	horizontal_image_url: string | null;
	horizontal_image_media_id: string | null;
	horizontal_image_status: StatusType;
	horizontal_video_url: string | null;
	horizontal_video_media_id: string | null;
	horizontal_video_status: StatusType;
	horizontal_upscale_url: string | null;
	horizontal_upscale_media_id: string | null;
	horizontal_upscale_status: StatusType;
	narrator_text: string | null;
	trim_start: number | null;
	trim_end: number | null;
	duration: number | null;
	created_at: string;
	updated_at: string;
}

export interface Request {
	id: string;
	project_id: string | null;
	video_id: string | null;
	scene_id: string | null;
	character_id: string | null;
	type: RequestType;
	orientation: Orientation | null;
	status: StatusType;
	request_id: string | null;
	media_id: string | null;
	output_url: string | null;
	error_message: string | null;
	automation_report: string | null;
	retry_count: number;
	worker_stage: string | null;
	last_heartbeat_at: string | null;
	queued_at: string | null;
	started_at: string | null;
	completed_at: string | null;
	created_at: string;
	updated_at: string;
}

// WebSocket event
export interface WSHealthData {
	status: string;
	extension_connected: boolean;
}

export interface WSSnapshotData {
	health: WSHealthData;
	requests: Request[];
	worker: {
		active: number;
		slots: number;
	};
}

export interface WSEvent {
	type:
		| "health"
		| "snapshot"
		| "request_created"
		| "request_updated"
		| "ping"
		| string;
	data: WSHealthData | WSSnapshotData | Request | Record<string, unknown>;
	timestamp: string;
}

export interface OperatorProduct {
	product_id?: string | null;
	product_name: string;
	raw_product_title?: string | null;
	product_short_name: string | null;
	product_display_name: string | null;
	category: string;
	sub_category: string;
	type_angle: string;
	product_type?: string | null;
	silo_id?: string | null;
	trigger_id?: string | null;
	submode_formula?: string | null;
	mode_recommendations?: string[];
	copywriting_angle?: string | null;
	claim_risk_level?: string | null;
	mapping_source?: string | null;
	mapping_confidence?: string | null;
	missing_fields?: string[];
	raw_category: string | null;
	avg_price_rm: number | null;
	status: string | null;
	copy_angle: string | null;
	hook: string | null;
	usp_1: string | null;
	usp_2: string | null;
	usp_3: string | null;
	body: string | null;
	cta: string | null;
	shop_name: string | null;
}

export interface WorkbookSummary {
	workbook: string;
	sheets: string[];
}

export interface ContentPackSummary {
	pack_dir: string;
	available: boolean;
	files: string[];
	engines: string[];
	durations_by_engine: Record<string, string[]>;
	avatars: string[];
	headwear_styles: string[];
	camera_styles: string[];
	product_types: string[];
	triggers: string[];
	silos: string[];
	formulas: string[];
	materials: string[];
	language_defaults: string[];
	products: OperatorProduct[];
	workbooks: WorkbookSummary[];
	notes: string[];
}

export interface BlueprintScene {
	display_order: number;
	prompt: string;
	image_prompt: string;
	video_prompt: string;
	character_names: string[];
	chain_type: ChainType;
}

export interface BlueprintResponse {
	project: Record<string, unknown>;
	video: Record<string, unknown>;
	scenes: BlueprintScene[];
	notes: string[];
}

export interface BatchStatus {
	total: number;
	pending: number;
	processing: number;
	completed: number;
	failed: number;
	done: boolean;
	all_succeeded: boolean;
	orientation: Orientation | null;
}

export interface CreatedState {
	project: Project;
	video: Video;
}

export type ManualEntityType = "character" | "visual_asset";

export interface UploadedAsset {
	label?: string;
	mediaId: string | null;
	characterId?: string;
	entityType?: ManualEntityType;
	fileName: string;
	previewUrl?: string;
	downloadUrl?: string;
	localFilePath?: string;
	assetId?: string;
	assetFingerprint?: string;
	assetSource?: string;
	isDefaultPackageAsset?: boolean;
	previewRenderableStatus?: string;
	previewErrorDetail?: string | null;
	localImagePathPresent?: boolean;
	remoteImageUrlPresent?: boolean;
}

// HYBRID is a first-class OPERATOR surface (product-image anchor + AI presenter).
// At the API/job boundary it maps to job mode "F2V" with source_mode="HYBRID"
// (ADR-007 naming contract: job modes stay IMG/T2V/I2V/F2V at the API edge).
export type WorkspaceMode = "T2V" | "HYBRID" | "F2V" | "I2V" | "IMG";
export type CreativeAssetSemanticRole =
	| "PRODUCT_REFERENCE"
	| "CHARACTER_REFERENCE"
	| "SCENE_CONTEXT_REFERENCE"
	| "STYLE_REFERENCE"
	| "COMPOSITE_FRAME_REFERENCE";
export type CreativeAssetStatus = "ACTIVE" | "ARCHIVED";
export type CreativeAssetSourceType =
	| "UPLOAD"
	| "GENERATED_IMAGE"
	| "PRODUCT_CACHE"
	| "REMOTE_URL"
	| "SYSTEM_SEED";
export type CreativeAssetStorageKind =
	| "LOCAL_FILE"
	| "REMOTE_URL"
	| "MEDIA_ID"
	| "PRODUCT_IMAGE_CACHE";
export type CreativeAssetEngineSlot =
	| "subject"
	| "scene"
	| "style"
	| "start_frame"
	| "end_frame";
export type I2VRecipeId =
	| "PRODUCT_HELD_BY_CHARACTER_IN_SCENE"
	| "CHARACTER_FIRST_PRODUCT_DEMO"
	| "STYLE_MOOD_DOMINANT_PRODUCT_SPOT";
export type PromptGenerationMode = "SINGLE" | "EXTEND";
export type PromptCameraStyle = "UGC_IPHONE_RAW" | "CINEMATIC_PRO";
export type PromptCharacterPresence = "VISIBLE_CREATOR" | "FACELESS";
export type PromptTargetLanguage = "BM_MS" | "EN_US";
type DisplayFieldValue =
	| string
	| number
	| boolean
	| null
	| undefined
	| string[]
	| number[]
	| boolean[];

export interface WorkspaceExecutePayload {
	prompt: string;
	orientation?: Orientation;
	aspectRatio?: string;
	model?: string;
	count?: number;
	stop_after_stage?: string;
	startAsset?: UploadedAsset | null;
	endAsset?: UploadedAsset | null;
	refs?: {
		subjectAsset?: UploadedAsset | null;
		sceneAsset?: UploadedAsset | null;
		styleAsset?: UploadedAsset | null;
	};
	product_id?: string | null;
	prompt_package_snapshot_id?: string | null;
	workspace_execution_package_id?: string | null;
	prompt_fingerprint?: string | null;
	asset_fingerprints?: string[];
	request_lineage_payload?: {
		product_id?: string;
		mode?: WorkspaceMode;
		prompt_package_snapshot_id?: string;
		workspace_execution_package_id?: string;
		prompt_fingerprint?: string;
		asset_fingerprints?: string[];
		recipe_id?: string;
		semantic_roles?: Record<string, string | null>;
		engine_slot_mapping?: Record<string, string>;
		creative_asset_ids?: Record<string, string | null>;
		resolved_assets?: Array<Record<string, unknown>>;
		compiler_context_summary?: string;
		resolver_warnings?: string[];
		resolver_blockers?: string[];
		semantic_slot_resolver?:
			| I2VSemanticSlotResolverResponse
			| Record<string, unknown>;
		manual_slot_overrides?: Record<string, string | null>;
	};
	mode: WorkspaceMode;
	// Strict extension execution lane. When set, the extension uploads the
	// package Start asset into the current editor and stops before Generate
	// (no new project, no settings, no Agent, no Generate).
	lane?: string;
	upload_only?: boolean;
	gfv2?: boolean;
}

export interface CreativeAsset {
	asset_id: string;
	semantic_role: CreativeAssetSemanticRole;
	display_name: string;
	description: string | null;
	source_type: CreativeAssetSourceType;
	storage_kind: CreativeAssetStorageKind;
	preview_url: string | null;
	download_url: string | null;
	media_id: string | null;
	local_file_path: string | null;
	remote_source_url: string | null;
	product_id: string | null;
	category: string | null;
	silo: string | null;
	product_type: string | null;
	allowed_modes: WorkspaceMode[];
	engine_slot_eligibility: CreativeAssetEngineSlot[];
	mode_a_metadata_handoff?: Record<string, unknown> | string | null;
	visual_dna_summary: string | null;
	character_dna: string | null;
	scene_context_dna: string | null;
	style_mood_dna: string | null;
	source_prompt_fingerprint: string | null;
	source_workspace_execution_package_id: string | null;
	source_prompt_package_snapshot_id: string | null;
	review_status: string;
	status: CreativeAssetStatus;
	created_at: string;
	updated_at: string;
}

export interface CreativeAssetListResponse {
	items: CreativeAsset[];
	total: number;
}

export interface I2VSemanticResolvedAsset {
	slot_key: "subject" | "scene" | "style";
	semantic_role: string;
	asset_id: string;
	display_name?: string | null;
	asset_source?: string | null;
	asset_fingerprint?: string | null;
	preview_url?: string | null;
	download_url?: string | null;
	media_id?: string | null;
	local_file_path?: string | null;
	local_image_path_present?: boolean | null;
	remote_image_url_present?: boolean | null;
}

export interface I2VSemanticSlotResolverResponse {
	mode: "I2V";
	recipe_id: I2VRecipeId;
	semantic_roles: Record<string, string | null>;
	engine_slot_mapping: Record<string, string>;
	creative_asset_ids: Record<string, string | null>;
	resolved_assets: I2VSemanticResolvedAsset[];
	compiler_context_summary: string;
	warnings: string[];
	blockers: string[];
}

export interface ApprovedPackageResolvedAsset {
	asset_id: string;
	asset_fingerprint: string;
	slot_key: string;
	asset_source: string;
	label: string;
	file_name: string;
	preview_url: string;
	download_url: string;
	media_id: string | null;
	local_file_path?: string | null;
	preview_renderable_status?: string;
	preview_error_detail?: string | null;
	local_image_path_present?: boolean;
	remote_image_url_present?: boolean;
}

export interface ApprovedPackageAssetSlot {
	slot_key: string;
	required: boolean;
	default_source: string;
	allowed_sources: string[];
	resolved_asset: ApprovedPackageResolvedAsset | null;
}

export interface ApprovedProductPackage {
	prompt_package_snapshot_id: string;
	product_id: string;
	product_name: string;
	mode: WorkspaceMode;
	approval_status: string;
	production_generation_allowed: boolean;
	prompt_text: string;
	prompt_fingerprint: string;
	claim_safe_rewrite: string;
	image_reference_status: string;
	asset_requirements: string[];
	asset_slots: ApprovedPackageAssetSlot[];
	manual_fallback: {
		allowed: boolean;
		copy_prompt_available: boolean;
		image_preview_url: string | null;
		image_download_url: string | null;
		asset_slots: string[];
		execution_checklist: string[];
		operator_warning: string;
	};
	provenance: string[];
	warnings: string[];
	blockers: string[];
	source_of_truth_notes: string[];
}

// Copy Selection & Compiler Binding V1 — safe audit lineage for the selected
// (or fallback) Copy Set. Never carries prompt-leaking internal metadata.
export type CopyBindingStatus = "BOUND" | "NOT_SELECTED" | "REJECTED";
export interface CopyBindingLineage {
	copy_source: "selected_copy_set" | "landbank_fallback" | "claim_safe_fallback";
	copy_binding_status: CopyBindingStatus;
	copy_set_id: string | null;
	copy_set_status: string | null;
	copy_set_fingerprint: string | null;
	copy_set_angle: string | null;
	copy_set_hook_preview: string | null;
	warning: string | null;
	// Explicit-Fallback-Confirmation V1 — present only when final generation ran
	// with operator-confirmed fallback (no approved Copy Set selected).
	copy_fallback_confirmed?: boolean;
	copy_fallback_confirmation_required?: boolean;
	copy_fallback_confirmation_source?: string;
	copy_fallback_policy?: string;
}

export interface WorkspaceExecutionPackage {
	workspace_execution_package_id: string;
	product_id: string;
	product_name: string;
	mode: WorkspaceMode;
	source_mode?: "T2V" | "HYBRID" | "FRAMES" | "INGREDIENTS" | "IMAGES";
	duration_seconds: number;
	total_duration_seconds?: number;
	aspect_ratio: string;
	model: string;
	manual_override: boolean;
	prompt_text: string;
	prompt_fingerprint: string;
	prompt_package_snapshot_id: string;
	asset_slots: ApprovedPackageAssetSlot[];
	resolved_assets: ApprovedPackageResolvedAsset[];
	readiness: string;
	execution_allowed: boolean;
	production_generation_allowed: boolean;
	manual_fallback: ApprovedProductPackage["manual_fallback"];
	blockers: string[];
	copy_binding?: CopyBindingLineage | null;
	request_lineage_payload: {
		product_id: string;
		mode: WorkspaceMode;
		prompt_package_snapshot_id: string;
		workspace_execution_package_id: string;
		prompt_fingerprint: string;
		asset_fingerprints: string[];
		recipe_id?: string;
		semantic_roles?: Record<string, string | null>;
		engine_slot_mapping?: Record<string, string>;
		creative_asset_ids?: Record<string, string | null>;
		resolved_assets?: Array<Record<string, unknown>>;
		compiler_context_summary?: string;
		resolver_warnings?: string[];
		resolver_blockers?: string[];
		semantic_slot_resolver?: I2VSemanticSlotResolverResponse;
		compiler?: Record<string, unknown>;
	};
	source_of_truth_notes: string[];
	prompt_preview?: string;
	semantic_slot_resolver?: I2VSemanticSlotResolverResponse | null;
	compiler_version?: string;
	generation_mode?: PromptGenerationMode;
	camera_style?: PromptCameraStyle;
	character_presence?: PromptCharacterPresence;
	creator_persona?: string;
	target_language?: PromptTargetLanguage;
	shot_plan?: Array<{
		block_index: number;
		shot_count: number;
		shots: string[];
	}>;
	dialogue_word_budget_per_block?: number[];
	prompt_blocks?: Array<{
		block_id?: string;
		block_index: number;
		block_role: "ANCHOR" | "CONTINUATION";
		duration_seconds: number;
		shot_count: number;
		dialogue_word_budget: number;
		continuation_from_block_id?: string | null;
		compiled_prompt_text: string;
		engine_prompt_text: string;
		shot_plan?: string[];
	}>;
	warnings?: string[];
	compiler_blockers?: string[];
	continuation_lineage?: Array<{
		block_index: number;
		continuation_from_block_id: string;
		continuation_strategy: string;
	}>;
	runtime_config_snapshot?: PromptCompilerRuntimeConfig;
}

export interface WorkspacePromptPreviewResult {
	product_id: string;
	mode: string;
	compiler_version: string;
	generation_mode: PromptGenerationMode;
	total_duration_seconds: number;
	camera_style: PromptCameraStyle;
	character_presence: PromptCharacterPresence;
	creator_persona: string;
	target_language: PromptTargetLanguage;
	dialogue_word_budget_per_block: number[];
	prompt_blocks: WorkspaceExecutionPackage["prompt_blocks"];
	shot_plan: WorkspaceExecutionPackage["shot_plan"];
	final_compiled_prompt_text: string;
	prompt_fingerprint: string;
	continuation_lineage: WorkspaceExecutionPackage["continuation_lineage"];
	warnings: string[];
	blockers: string[];
	source_of_truth_notes: string[];
	copy_binding?: CopyBindingLineage | null;
	// WPS chaining enforcement metadata (present when engine_duration_target is
	// supplied; optional so legacy responses remain valid).
	wps_chaining_enforced?: boolean;
	engine_duration_target?: string | null;
	requested_total_duration_seconds?: number | null;
	resolved_block_chain?: number[];
	resolved_block_chain_source?: string;
	actual_dialogue_word_count_per_block?: number[];
	wps_status_per_block?: string[];
}

// ── Copy Set (Copy Strategy Studio) — approvable copywriting bundle that binds
// into the deterministic final prompt compiler as copy_intelligence.
export type CopySetStatus =
	| "DRAFT_COPY"
	| "COPY_REVIEW_REQUIRED"
	| "COPY_APPROVED"
	| "COPY_REJECTED";

export interface CopySet {
	copy_set_id: string;
	product_id: string;
	angle: string;
	hook: string;
	subhook: string;
	usp_set: string[];
	cta: string;
	platform: string;
	language: string;
	route_type: string;
	formula_family: string;
	status: CopySetStatus;
	dedupe_key: string;
	source: string;
	provenance: Record<string, unknown>;
	claim_review: {
		completeness?: { complete: boolean; missing_fields: string[] };
		safety?: { safe: boolean; violations: string[]; detail?: Record<string, string> };
		route_type?: string;
		approved?: boolean;
	};
	reviewer_note: string | null;
	approved_at: string | null;
	approved_by: string | null;
	created_at: string | null;
	updated_at: string | null;
}

export interface CopySetListResponse {
	product_id: string;
	items: CopySet[];
}

export interface CopySetGenerateResponse {
	copy_set: CopySet;
	created: boolean;
	dedupe_match: boolean;
}

// AI Copy Assist V1 — candidate generator (never auto-approved).
export interface AICopyCandidate {
	copy_set: CopySet;
	created: boolean;
	dedupe_match: boolean;
	safety: { safe: boolean; violations: string[]; detail?: Record<string, string> };
	warnings: string[];
}

export interface AICopyAssistResponse {
	provider: { lane: string; configured: boolean; provider_id: string | null };
	candidates: AICopyCandidate[];
}

export const COPY_SET_APPROVAL_PHRASE = "APPROVE_COPY_SET";

export interface PromptCompilerRuntimeConfig {
	generation_modes: PromptGenerationMode[];
	allowed_block_durations_seconds: number[];
	default_block_duration_seconds: number;
	camera_styles: Array<{
		id: PromptCameraStyle;
		label: string;
		notes: string[];
	}>;
	character_presence_options: Array<{
		id: PromptCharacterPresence;
		label: string;
		is_default: boolean;
		warning: string | null;
	}>;
	persona_registry: Array<{
		id: string;
		label: string;
		presentation: string;
		tone: string;
		continuity_notes: string;
	}>;
	language_wps_policy: Record<
		PromptTargetLanguage,
		{
			hook_wps: number;
			body_wps: number;
			cta_wps: number;
			absolute_ceiling_wps: number;
		}
	>;
	shot_count_policy: Record<string, { recommended: number; max: number }>;
	continuation_policy: Record<string, boolean>;
	engine_mode_capability_policy: Record<string, Record<string, unknown>>;
	defaults: {
		generation_mode: PromptGenerationMode;
		block_duration_seconds: number;
		camera_style: PromptCameraStyle;
		character_presence: PromptCharacterPresence;
		target_language: PromptTargetLanguage;
		creator_persona: string;
		overlay_enabled: boolean;
		dialogue_enabled: boolean;
		block_2_duration_seconds: number;
	};
}

export interface WorkspacePackageReadinessChecklistEntry {
	key: string;
	label: string;
	ready: boolean;
	detail: string;
}

export interface WorkspacePackageReadinessItem {
	product_id: string;
	product_name?: string | null;
	mode: WorkspaceMode;
	readiness_status:
		| "READY"
		| "REFERENCE_ONLY_PRODUCT"
		| "CLAIM_SAFE_PACKAGE_NOT_READY"
		| "PRODUCTION_APPROVAL_REQUIRED"
		| "START_FRAME_REQUIRED"
		| "SUBJECT_REQUIRED"
		| "PRODUCT_ARCHIVED"
		| "UNSUPPORTED_MODE"
		| "PRODUCT_NOT_FOUND";
	blocker?: string | null;
	detail: string;
	image_reference_status?: string | null;
	claim_safe_copy_status?: string | null;
	production_prompt_approved_modes?: string[];
	checklist: WorkspacePackageReadinessChecklistEntry[];
	quick_actions: {
		smart_registration_path: string;
		approved_packages_path: string;
		products_path: string;
	};
}

export interface WorkspacePackageReadinessResponse {
	mode: WorkspaceMode;
	items: WorkspacePackageReadinessItem[];
}

export interface Product {
	id: string;
	product_id?: string;
	source: "FASTMOSS" | "TIKTOKSHOP" | "MANUAL" | "IMPORTED";
	source_lane?: string | null;
	source_label?: string | null;
	reference_only?: boolean;
	catalog_visibility_reason?: string | null;
	catalog_blockers?: string[];
	lifecycle_status?: "ACTIVE" | "ARCHIVED" | "DELETED_TEST_ONLY" | null;
	archived_at?: string | null;
	archived_reason?: string | null;
	archived_by?: string | null;
	unarchived_at?: string | null;
	unarchived_reason?: string | null;
	lifecycle_provenance?: Array<Record<string, unknown>>;
	source_url?: string | null;
	brand?: string | null;
	raw_product_title: string;
	product_display_name: string;
	product_short_name: string;
	group?: string | null;
	sub_group?: string | null;
	type_of_product?: string | null;
	bosmax_product_family?: string | null;
	package_form?: string | null;
	physical_state?: string | null;
	product_scale_class?: string | null;
	handling_profile?: string | null;
	scene_profile?: string | null;
	camera_profile?: string | null;
	copy_route?: string | null;
	claim_gate?: string | null;
	claim_tokens?: string[];
	copy_formula?: string | null;
	sold_count?: number | null;
	product_sold_count?: number | null;
	shop_total_sold_count?: number | null;
	shop_count?: number | null;
	shop_names?: string[];
	sold_count_metric_scope?: "PRODUCT" | "SHOP" | "UNKNOWN" | null;
	sold_count_truth_status?:
		| "VERIFIED_PRODUCT_LEVEL"
		| "SHOP_LEVEL_AGGREGATE"
		| "NOT_VERIFIED"
		| null;
	sales_metric_warnings?: string[];
	sales_metric_provenance?: string[];
	sales_metrics_source?:
		| "LATEST_FASTMOSS_IMPORT_BATCH"
		| "LEGACY_COMBINED_WORKBOOK"
		| "NOT_FOUND"
		| null;
	sales_metrics_batch_id?: string | null;
	matched_file_type?: string | null;
	matched_by?: string | null;
	raw_metric_column?: string | null;
	image_analysis_status?: string | null;
	intelligence_confidence?: "HIGH" | "MEDIUM" | "LOW" | null;
	intelligence_status?: string | null;
	intelligence_warnings?: string[];
	intelligence_provenance?: string[];
	taxonomy_conflict?: boolean;
	taxonomy_conflict_reason?: string | null;
	sales_metrics?: {
		sold_count: number | null;
		product_sold_count?: number | null;
		shop_total_sold_count?: number | null;
		shop_count: number | null;
		shop_names: string[];
		source_status: string;
		sold_count_metric_scope?: "PRODUCT" | "SHOP" | "UNKNOWN";
		sold_count_truth_status?:
			| "VERIFIED_PRODUCT_LEVEL"
			| "SHOP_LEVEL_AGGREGATE"
			| "NOT_VERIFIED";
		sales_metric_warnings?: string[];
		sales_metric_provenance?: string[];
		sales_metrics_source?:
			| "LATEST_FASTMOSS_IMPORT_BATCH"
			| "LEGACY_COMBINED_WORKBOOK"
			| "NOT_FOUND";
		sales_metrics_batch_id?: string | null;
		matched_file_type?: string | null;
		matched_by?: string | null;
		raw_metric_column?: string | null;
	};
	image_analysis?: {
		status: string;
		image_url: string | null;
		local_image_path: string | null;
		detected_package: string | null;
		detected_text: string[];
		detected_brand?: string | null;
		detected_size_text?: string | null;
		detected_form_factor?: string | null;
		visual_confidence: string;
		evidence?: string[];
		warnings?: string[];
		provider: string;
		metadata?: Record<string, unknown>;
	};
	destination_readiness?: Record<string, string>;
	category: string | null;
	subcategory: string | null;
	type: string | null;
	price?: number | null;
	currency?: string | null;
	commission_amount?: number | null;
	commission_rate?: string | null;
	product_type_id?: string | null;
	product_type?: string | null;
	silo?: string | null;
	trigger_id?: string | null;
	formula?: string | null;
	mode_recommendations?: string[];
	copywriting_angle?: string | null;
	claim_risk_level?: string | null;
	mapping_source?:
		| "explicit"
		| "manual"
		| "rule"
		| "heuristic"
		| "fallback"
		| null;
	mapping_confidence?: "HIGH" | "MEDIUM" | "LOW" | "NEEDS_REVIEW" | null;
	mapping_review_status?: string | null;
	mapping_status?: "READY" | "NEEDS_REVIEW" | "BLOCKED" | null;
	mapping_missing_fields?: string[];
	prompt_readiness_status?: "READY" | "NEEDS_REVIEW" | "MISSING_FIELDS" | null;
	prompt_missing_fields?: string[];
	physics_dna_status?: "READY" | "MISSING_FIELDS" | null;
	physics_class?: string | null;
	product_scale?: string | null;
	hand_object_interaction?: string | null;
	recommended_grip?: string | null;
	air_gap_rule?: string | null;
	material_behavior?: string | null;
	surface_behavior?: string | null;
	fragility_level?: string | null;
	handling_notes?: string | null;
	camera_handling_notes?: string | null;
	scene_context?: string | null;
	camera_style?: string | null;
	camera_behavior?: string | null;
	camera_shot?: string | null;
	unsafe_handling_rules?: string[];
	section_4_hint?: string | null;
	section_5_physics_hint?: string | null;
	section_6_copy_hint?: string | null;
	section_9_overlay_hint?: string | null;
	section_4_visual_action_prompt?: string | null;
	section_5_product_physics_prompt?: string | null;
	section_6_dialogue_prompt?: string | null;
	section_9_overlay_prompt?: string | null;
	missing_fields?: string[];
	notes?: string[];
	shop_name: string | null;
	price_min: number | null;
	price_max: number | null;
	commission: string | null;
	image_url: string | null;
	tiktok_product_url: string | null;
	fastmoss_source_file: string | null;
	image_asset_status?: string | null;
	image_failure_detail?: string | null;
	image_readiness_status?:
		| "IMAGE_READY"
		| "IMAGE_NOT_AVAILABLE"
		| "IMAGE_DOWNLOAD_FAILED"
		| "IMAGE_URL_MISSING"
		| "IMAGE_URL_MISSING_FROM_SOURCE"
		| "IMAGE_CACHE_READY"
		| "LOCAL_CACHE_MISSING"
		| null;
	image_readiness_detail?: string | null;
	rendered_img_src?: string | null;
	image_http_status?: number | null;
	is_test_product?: boolean;
	catalog_label?: string | null;
	mode_readiness?: Record<
		string,
		{
			status: string;
			detail: string;
			missing_fields: string[];
			asset_strategy?: string;
		}
	>;
	asset_status: "UNRESOLVED" | "DOWNLOADED" | "UPLOADED_TO_FLOW";
	media_id: string | null;
	local_image_path: string | null;
	created_at: string;
	updated_at: string;
}

export interface ProductCatalogResponse {
	total_count: number;
	returned_count: number;
	has_pagination: boolean;
	limit: number;
	offset: number;
	items: Product[];
}

export type ProductIntelligenceSnapshotStatus =
	| "DRAFT"
	| "APPROVED"
	| "SUPERSEDED"
	| "REJECTED"
	| "ARCHIVED";

export type ProductIntelligenceReviewDraftStatus =
	| "DRAFT"
	| "READY_FOR_REVIEW"
	| "NEEDS_REVISION"
	| "REJECTED"
	| "APPROVED";

export type ProductIntelligenceClaimGate =
	| "CLAIM_SAFE"
	| "CLAIM_REVIEW_REQUIRED"
	| "CLAIM_BLOCKED";

export type ProductIntelligenceLatestStatus =
	| "NO_APPROVED_SNAPSHOT"
	| "APPROVED_SNAPSHOT_AVAILABLE";

export interface ProductIntelligenceSnapshot {
	snapshot_id: string;
	product_id: string;
	version: number;
	status: ProductIntelligenceSnapshotStatus;
	product_description: string | null;
	benefits_json: string[];
	usp_json: string[];
	usage_text: string | null;
	ingredients_text: string | null;
	warnings_text: string | null;
	target_customer_text: string | null;
	paste_anything_summary: string | null;
	source_urls_json: Record<string, unknown>;
	image_evidence_json: Record<string, unknown>;
	package_notes: string | null;
	size_or_volume: string | null;
	product_form_factor: string | null;
	packaging_description: string | null;
	product_truth_lock: string | null;
	claim_gate: string | null;
	claim_risk_level: string | null;
	claim_tokens_json: string[];
	allowed_claims_json: string[];
	blocked_claims_json: string[];
	buyer_persona_snapshot_json: Record<string, unknown>;
	copy_strategy_summary_json: Record<string, unknown>;
	confidence_score: number | null;
	completeness_score: number | null;
	readiness_status: string | null;
	created_from_review_draft_id: string | null;
	created_by: string | null;
	approved_by: string | null;
	approved_at: string | null;
	supersedes_snapshot_id: string | null;
	created_at: string;
	updated_at: string;
}

export interface ProductIntelligenceFieldProvenance {
	provenance_id: string;
	snapshot_id: string;
	product_id: string;
	field_name: string;
	declared_value: string | null;
	normalized_value: string | null;
	source_type: string;
	source_url: string | null;
	source_lane: string | null;
	evidence_kind: string;
	extraction_method: string;
	confidence_score: number | null;
	verification_status: string;
	claim_risk_flag: string | null;
	reviewer_decision: string | null;
	reviewer_note: string | null;
	created_at: string;
	updated_at: string;
}

export interface ProductIntelligenceProvenanceSummary {
	total_snapshots: number;
	approved_snapshot_count: number;
	latest_approved_snapshot_id: string | null;
	latest_approved_version: number | null;
}

export interface ProductIntelligenceLatestSnapshotResponse {
	product_id: string;
	latest_snapshot: ProductIntelligenceSnapshot | null;
	status: ProductIntelligenceLatestStatus;
	provenance_summary: ProductIntelligenceProvenanceSummary;
}

export interface ProductIntelligenceSnapshotListResponse {
	product_id: string;
	items: ProductIntelligenceSnapshot[];
}

export interface ProductIntelligenceFieldProvenanceListResponse {
	snapshot_id: string;
	product_id: string;
	items: ProductIntelligenceFieldProvenance[];
}

export interface ProductIntelligenceReviewFieldProvenanceInput {
	field_name: string;
	declared_value: string | null;
	normalized_value: string | null;
	source_type: string;
	source_url: string | null;
	source_lane: string | null;
	evidence_kind: string;
	extraction_method: string;
	confidence_score: number | null;
	verification_status: string;
	claim_risk_flag: string | null;
	reviewer_decision: string | null;
	reviewer_note: string | null;
}

export interface ProductIntelligenceReviewFieldProvenance
	extends ProductIntelligenceReviewFieldProvenanceInput {
	review_provenance_id: string;
	draft_id: string;
	product_id: string;
	created_at: string;
	updated_at: string;
}

export interface ProductIntelligenceReviewDraft {
	draft_id: string;
	product_id: string;
	review_status: ProductIntelligenceReviewDraftStatus;
	product_description: string | null;
	benefits_json: string[];
	usp_json: string[];
	usage_text: string | null;
	ingredients_text: string | null;
	warnings_text: string | null;
	target_customer_text: string | null;
	paste_anything_summary: string | null;
	source_urls_json: Record<string, unknown>;
	image_evidence_json: Record<string, unknown>;
	package_notes: string | null;
	size_or_volume: string | null;
	product_form_factor: string | null;
	packaging_description: string | null;
	product_truth_lock: string | null;
	claim_gate: ProductIntelligenceClaimGate;
	claim_risk_level: "LOW" | "MEDIUM" | "HIGH";
	claim_tokens_json: string[];
	allowed_claims_json: string[];
	blocked_claims_json: string[];
	buyer_persona_snapshot_json: Record<string, unknown>;
	copy_strategy_summary_json: Record<string, unknown>;
	confidence_score: number | null;
	completeness_score: number | null;
	readiness_status: string | null;
	reviewer_note: string | null;
	created_by: string | null;
	reviewed_by: string | null;
	approved_by: string | null;
	approved_at: string | null;
	rejected_by: string | null;
	rejected_at: string | null;
	created_at: string;
	updated_at: string;
	provenance_items: ProductIntelligenceReviewFieldProvenance[];
}

export interface ProductIntelligenceReviewDraftListResponse {
	product_id: string;
	items: ProductIntelligenceReviewDraft[];
}

export interface ProductIntelligenceReviewDraftValidationResponse {
	draft: ProductIntelligenceReviewDraft;
	missing_required_fields: string[];
	present_required_fields: string[];
	completeness_score: number;
	readiness_status: string;
	claim_gate: ProductIntelligenceClaimGate;
	claim_risk_level: "LOW" | "MEDIUM" | "HIGH";
	claim_tokens_json: string[];
	allowed_claims_json: string[];
	blocked_claims_json: string[];
	approval_blockers: string[];
}

export interface ProductIntelligenceReviewDraftMutationRequest {
	product_description?: string | null;
	benefits_json?: string[] | null;
	usp_json?: string[] | null;
	usage_text?: string | null;
	ingredients_text?: string | null;
	warnings_text?: string | null;
	target_customer_text?: string | null;
	paste_anything_summary?: string | null;
	source_urls_json?: Record<string, unknown> | null;
	image_evidence_json?: Record<string, unknown> | null;
	package_notes?: string | null;
	size_or_volume?: string | null;
	product_form_factor?: string | null;
	packaging_description?: string | null;
	product_truth_lock?: string | null;
	allowed_claims_json?: string[] | null;
	blocked_claims_json?: string[] | null;
	buyer_persona_snapshot_json?: Record<string, unknown> | null;
	copy_strategy_summary_json?: Record<string, unknown> | null;
	confidence_score?: number | null;
	reviewer_note?: string | null;
	created_by?: string | null;
	reviewed_by?: string | null;
	provenance_items?: ProductIntelligenceReviewFieldProvenanceInput[] | null;
}

export interface FastMossSalesMetricScopeEntry {
	file_type_id: string;
	metric_name: string;
	source_column: string;
	metric_scope: "PRODUCT" | "SHOP" | "AD" | "CREATOR" | "UNKNOWN";
	truth_status:
		| "VERIFIED_PRODUCT_LEVEL"
		| "SHOP_LEVEL_AGGREGATE"
		| "NOT_VERIFIED";
	warning?: string | null;
}

export interface FastMossImportFileReport {
	upload_field_key: string;
	file_type_id?: string | null;
	label?: string | null;
	original_filename: string;
	detected_by: string;
	storage_path: string;
	extension: string;
	sheet_names: string[];
	selected_sheet?: string | null;
	headers: string[];
	row_count: number;
	required_columns_present: string[];
	optional_columns_present: string[];
	missing_required_columns: string[];
	unknown_columns: string[];
	parse_status: string;
	parse_warnings: string[];
	parse_errors: string[];
	sales_metric_scope_report: FastMossSalesMetricScopeEntry[];
	sample_records: Record<string, unknown>[];
}

export interface FastMossImportBatchReport {
	batch_id: string;
	import_status: string;
	write_back_status: string;
	latest_reference_only: boolean;
	growth_analytics_enabled: boolean;
	uploaded_files: number;
	recognized_file_types: string[];
	missing_expected_file_types: string[];
	duplicate_file_types: string[];
	row_counts_by_file_type: Record<string, number>;
	column_validation_by_file_type: Record<
		string,
		{
			required_columns_present: string[];
			missing_required_columns: string[];
			optional_columns_present: string[];
			unknown_columns: string[];
			parse_status: string;
		}
	>;
	sales_metric_scope_report: FastMossSalesMetricScopeEntry[];
	product_reference_sample: Record<string, unknown>[];
	parse_warnings: string[];
	parse_errors: string[];
	ready_for_processing: boolean;
	raw_file_storage_path: string;
	provenance: string[];
	files: FastMossImportFileReport[];
}

export interface ProductMapping {
	product_id: string;
	raw_product_title: string;
	product_short_name: string;
	category: string;
	subcategory: string;
	type: string;
	product_type: string;
	product_type_id?: string;
	silo: string;
	trigger_id: string;
	formula: string;
	mode_recommendations: string[];
	copywriting_angle: string;
	claim_risk_level: string;
	mapping_source: "explicit" | "manual" | "rule" | "heuristic" | "fallback";
	mapping_confidence: "HIGH" | "MEDIUM" | "LOW" | "NEEDS_REVIEW";
	mapping_review_status?: string;
	mapping_status?: "READY" | "NEEDS_REVIEW" | "BLOCKED";
	mapping_missing_fields?: string[];
	prompt_readiness_status?: "READY" | "NEEDS_REVIEW" | "MISSING_FIELDS";
	prompt_missing_fields?: string[];
	physics_class?: string;
	product_scale?: string;
	hand_object_interaction?: string;
	recommended_grip?: string;
	handling_notes?: string;
	air_gap_rule?: string;
	material_behavior?: string;
	surface_behavior?: string;
	fragility_level?: string;
	camera_handling_notes?: string;
	scene_context?: string;
	camera_style?: string;
	camera_behavior?: string;
	camera_shot?: string;
	unsafe_handling_rules?: string[];
	section_4_hint?: string;
	section_5_physics_hint?: string;
	section_6_copy_hint?: string;
	section_9_overlay_hint?: string;
	section_4_visual_action_prompt?: string;
	section_5_product_physics_prompt?: string;
	section_6_dialogue_prompt?: string;
	section_9_overlay_prompt?: string;
	missing_fields: string[];
	notes: string[];
}

export interface OperatorBatchContext {
	batch_id: string;
	batch_mode: string;
	variant_id: string;
	queue_status: string;
}

export interface ProductPreflight {
	product_id: string | null;
	lifecycle_status?: "ACTIVE" | "ARCHIVED" | "DELETED_TEST_ONLY" | null;
	mapping_status: "READY" | "NEEDS_REVIEW" | "BLOCKED";
	missing_fields: string[];
	physics_dna_status: string;
	creative_brief_status: string;
	creative_missing_fields: string[];
	prompt_readiness_status: string;
	prompt_missing_fields: string[];
	flow_readiness_status: string;
	blocking_reason: string | null;
	repair_action: string;
	backfill_action: string;
	flow_readiness_action: string;
	build_allowed: boolean;
	safe_to_generate_prompt?: boolean;
}

export interface OperatorPreflightResponse {
	product_id: string;
	product: Product;
	preflight: ProductPreflight;
	batch_context: OperatorBatchContext | null;
}

export interface FlowReadinessSmokeResult {
	status: "READY" | "BLOCKED";
	checked_mode: string;
	extension_runtime: "PASS" | "FAIL";
	flow_tab_found: boolean;
	flow_tab_id: number | null;
	flow_url: string | null;
	extension_protocol_version: string | null;
	content_script_protocol_version: string | null;
	content_script_loaded: boolean;
	content_script_alive: boolean;
	last_content_script_seen_at: string | null;
	signed_in_likely: boolean;
	composer_found: boolean;
	composer_editable: boolean;
	generate_button_found: boolean;
	current_mode_visible: string;
	blocking_modal_detected: boolean;
	flow_composer_ready: boolean;
	execute_flow_job_smoke: string;
	primary_blocker: string | null;
	last_checked_at: string | null;
	raw_error: string | null;
	batch_context: OperatorBatchContext | null;
}

export interface ReloadFlowTabResult {
	ok: boolean;
	error: string | null;
	action_taken: string;
	flow_tab_id: number | null;
	flow_url: string | null;
	extension_protocol_version: string | null;
	content_script_protocol_version: string | null;
	content_script_loaded: boolean;
	content_script_alive: boolean;
	last_content_script_seen_at: string | null;
	primary_blocker: string | null;
	last_checked_at: string | null;
}

export interface OpenTargetFlowProjectResult {
	ok: boolean;
	error: string | null;
	flow_project_url: string | null;
	flow_tab_id: number | null;
	flow_url_before: string | null;
	flow_url_after: string | null;
	flow_url: string | null;
	extension_protocol_version: string | null;
	content_script_protocol_version?: string | null;
	content_script_loaded?: boolean;
	content_script_alive?: boolean;
	last_content_script_seen_at?: string | null;
	primary_blocker: string | null;
	last_checked_at: string | null;
}

export interface LocalAgentRegistration {
	operator_id: string | null;
	device_id: string;
	approval_status: string;
	license_status: string;
	registered_at: string | null;
	updated_at: string;
}

export interface LocalAgentStatus {
	task_name: string;
	health_url: string;
	dashboard_url: string;
	content_pack_url: string;
	dashboard_serving_mode: string;
	repair_command: string;
	extension_connected: boolean;
	extension_state: string;
	offline_reason: string | null;
	auto_start_enabled: boolean;
	auto_start_mode: string;
	auto_start_warning: string | null;
	last_health_check: string | null;
	license_status: string;
	approval_status: string;
	registration: LocalAgentRegistration;
}

export type AIProviderId =
	| "qwen"
	| "anthropic"
	| "openai"
	| "gemini"
	| "deepseek";

export type AIProviderLaneId = "text_assist" | "vision";

export type AIProviderLaneStatus =
	| "NOT_CONFIGURED"
	| "MODEL_MISSING"
	| "MODEL_DISABLED"
	| "KEY_MISSING"
	| "EXECUTION_DISABLED"
	| "READY";

export interface AIProviderModelOption {
	model_id: string;
	label: string;
	lanes: string[];
	enabled: boolean;
	source: string;
}

export interface AIProviderCatalogEntry {
	label: string;
	transport: string;
	enabled: boolean;
	supported_lanes: string[];
	models: AIProviderModelOption[];
}

export interface AIProviderSummary {
	provider_id: AIProviderId;
	label: string;
	env_var: string;
	has_key: boolean;
	masked_key: string | null;
	status: string;
	is_active: boolean;
	updated_at: string | null;
	activated_at: string | null;
	activation_scope: string;
	current_capabilities: string[];
	default_model: string | null;
	supported_lanes: string[];
}

export interface AIProviderLaneSetting {
	lane: AIProviderLaneId;
	label: string;
	provider_id: AIProviderId | null;
	model_id: string | null;
	execution_enabled: boolean;
	configured_by_user: boolean;
	key_present: boolean;
	model_valid: boolean;
	status: AIProviderLaneStatus;
	configured: boolean;
}

export interface AIProviderRegistry {
	active_provider: AIProviderId | null;
	providers: AIProviderSummary[];
	model_catalog: Record<string, AIProviderCatalogEntry>;
	lanes: AIProviderLaneSetting[];
}

export interface TelemetrySummary {
	total_today: number;
	queued: number;
	processing: number;
	waiting_flow: number;
	flow_running: number;
	completed: number;
	failed: number;
	last_job_status: string;
	last_stage: string;
	last_error: string;
	idle_seconds: number;
}

export interface TelemetryRequest {
	request_id: string;
	project_id: string | null;
	video_id: string | null;
	scene_id: string | null;
	product_id: string | null;
	request_type: RequestType | string | null;
	mode: string | null;
	status: string;
	google_flow_stage: string | null;
	extension_stage: string | null;
	worker_stage: string | null;
	queued_at: string | null;
	started_at: string | null;
	last_heartbeat_at: string | null;
	completed_at: string | null;
	failed_at: string | null;
	duration_seconds: number | null;
	idle_seconds: number | null;
	processing_seconds: number | null;
	error_code: string | null;
	error_message: string | null;
	created_at: string;
}

export interface TelemetryStageEvent {
	id: string;
	request_id: string;
	timestamp: string;
	stage: string;
	status: string;
	message: string | null;
	source: string;
}

export interface TelemetryRequestDetail {
	telemetry: TelemetryRequest;
	stages: TelemetryStageEvent[];
}
export interface ProductCreativeBrief {
	brief_id: string;
	product_id: string;
	product_intelligence: {
		product_short_name: string;
		raw_product_title: string;
		category: string;
		subcategory: string;
		type: string;
		price: number | null;
		commission_rate: string | null;
		image_readiness_status: string;
		source_url: string;
		tiktok_product_url: string;
	};
	commercial_signals: {
		price: number | null;
		commission_rate: string | null;
		shop_name: string | null;
	};
	physics_dna: {
		physics_class: string;
		product_scale: string;
		recommended_grip: string;
		hand_object_interaction: string;
		material_behavior: string;
		surface_behavior: string;
		unsafe_handling_rules: string[];
		section_5_product_physics_prompt: string;
	};
	copywriting_route: {
		product_type: string;
		silo: string;
		trigger_id: string;
		formula: string;
		copywriting_angle: string;
		claim_risk_level: string;
	};
	creative_mapping: {
		character_recommendations: string[];
		scene_context_recommendations: string[];
		camera_recommendations: string[];
		mode_recommendations: string[];
	};
	readiness: {
		Images: string;
		Ingredients: string;
		Frames: string;
		"Text to Video": string;
	};
	claim_boundaries: {
		risk_level: string;
		restricted_keywords: string[];
	};
	missing_fields: string[];
}

export interface VariationPlan {
	variant_id: string;
	product_id: string;
	brief_id: string;
	variation_index: number;
	hook_angle: string;
	scene_context: string;
	camera_route: string;
	copywriting_formula: string;
	overlay_strategy: string;
	cta_style: string;
	google_flow_mode: string;
	asset_strategy: string;
	diversity_fingerprint: string;
	readiness: string;
	blocked_reason: string[];
}

export type AssetSourceStatus =
	| "REPO_VERIFIED"
	| "INPUT_SLOT_ONLY"
	| "EXTERNAL_OPERATOR_PACK_NOT_VERIFIED"
	| "EMPTY_NOT_VERIFIED"
	| "DERIVED_FROM_PRODUCT_DATA";

export interface AssetCatalogEntry {
	asset_type: string;
	display_name: string;
	description: string;
	item_count: number;
	source_status: AssetSourceStatus | string;
	warnings: string[];
	provenance: Record<string, unknown>;
	empty_reason: string | null;
}

export interface AssetCatalogResponse {
	catalog: AssetCatalogEntry[];
	warnings: string[];
	provenance: Record<string, unknown>;
}

export interface AssetOption {
	asset_id: string;
	asset_type: string;
	label: string;
	description: string;
	metadata: Record<string, unknown>;
	compatibility_tags: string[];
	source_status: AssetSourceStatus | string;
	source_file: string | null;
	source_path: string | null;
	warnings: string[];
	provenance: Record<string, unknown>;
	is_selectable: boolean;
	is_canonical: boolean;
	verified_level: string;
}

export interface AssetOptionsResponse {
	asset_type: string;
	options: AssetOption[];
	warnings: string[];
	provenance: Record<string, unknown>;
	source_status: AssetSourceStatus | string;
	empty_reason: string | null;
}

export interface AssetDetailResponse {
	asset: AssetOption;
	warnings: string[];
	provenance: Record<string, unknown>;
}

export interface AssetSelectionRequest {
	selected_assets: Record<string, string | string[] | null>;
}

export interface AssetSelectionResponse {
	selection_status: "PASS" | "WARN" | "FAIL" | string;
	resolved_assets: AssetOption[];
	warnings: string[];
	errors: string[];
	provenance: Record<string, unknown>;
}

export interface AssetCompatibilityRequest {
	selected_assets: Record<string, string | string[] | null>;
}

export interface AssetCompatibilityResponse {
	compatibility_status: "PASS" | "WARN" | "FAIL" | "NOT_VERIFIED" | string;
	warnings: string[];
	errors: string[];
	provenance: Record<string, unknown>;
}

export type BosmaxSourceStatus =
	| "REPO_VERIFIED"
	| "PRODUCT_DERIVED"
	| "OPERATOR_PACK"
	| "INPUT_SLOT_ONLY"
	| "NOT_FOUND"
	| string;

export interface BosmaxAuthorityOption {
	value: string;
	label: string;
	source_status: BosmaxSourceStatus;
	source_file?: string | null;
	source_endpoint?: string | null;
	source_origin?: string | null;
	warnings: string[];
	metadata: Record<string, unknown>;
}

export interface BosmaxAuthorityFallback {
	label: string;
	reason: string;
	source_status: BosmaxSourceStatus;
	source_file?: string | null;
	source_endpoint?: string | null;
	source_origin?: string | null;
	warnings: string[];
}

export interface BosmaxFieldProvenance {
	field: string;
	source_status: BosmaxSourceStatus;
	source_file?: string | null;
	source_endpoint?: string | null;
	source_origin?: string | null;
	warnings: string[];
}

export interface BosmaxSourceMatrixEntry {
	key: string;
	label: string;
	source_status: BosmaxSourceStatus;
	source_file?: string | null;
	source_endpoint?: string | null;
	source_origin?: string | null;
	warnings: string[];
	details: Record<string, unknown>;
}

export interface BosmaxProductContextRecord {
	product_id?: string | null;
	product_display_name?: string | null;
	category?: string | null;
	subcategory?: string | null;
	type?: string | null;
	product_type?: string | null;
	source?: string | null;
	claim_risk_level?: string | null;
	raw_product_title?: string | null;
}

export interface BosmaxCreativeContextRecord {
	trigger_id?: string | null;
	silo?: string | null;
	formula?: string | null;
	hook?: string | null;
	usp_1?: string | null;
	usp_2?: string | null;
	usp_3?: string | null;
	cta?: string | null;
	copywriting_angle?: string | null;
	creative_mapping?: Record<string, unknown> | null;
}

export interface BosmaxVisualContextRecord {
	scene_context?: string | null;
	camera_style?: string | null;
	camera_behavior?: string | null;
	style_reference?: string | null;
	overlay_hint?: string | null;
	product_handling?: string | null;
	product_physics?: string | null;
}

export interface BosmaxProductContext {
	product_id: string;
	product: BosmaxProductContextRecord;
	creative: BosmaxCreativeContextRecord;
	visual: BosmaxVisualContextRecord;
	warnings: string[];
	provenance: BosmaxFieldProvenance[];
}

export interface BosmaxProductGroup {
	options: BosmaxAuthorityOption[];
	contexts: BosmaxProductContext[];
}

export interface BosmaxCreativeGroup {
	trigger_options: BosmaxAuthorityOption[];
	silo_options: BosmaxAuthorityOption[];
	formula_options: BosmaxAuthorityOption[];
	products_with_copy_signals: BosmaxAuthorityOption[];
}

export interface BosmaxVisualGroup {
	scene_context_options: BosmaxAuthorityOption[];
	camera_style_options: BosmaxAuthorityOption[];
	camera_behavior_options: BosmaxAuthorityOption[];
	style_reference_options: BosmaxAuthorityOption[];
	overlay_hint_options: BosmaxAuthorityOption[];
	product_handling_options: BosmaxAuthorityOption[];
	product_physics_options: BosmaxAuthorityOption[];
}

export interface BosmaxCharacterGroup {
	character_options: BosmaxAuthorityOption[];
	avatar_options: BosmaxAuthorityOption[];
	headwear_suggestions: BosmaxAuthorityOption[];
	wardrobe_fallback: BosmaxAuthorityFallback;
}

export interface BosmaxExecutionGroup {
	language_options: BosmaxAuthorityOption[];
	platform_options: BosmaxAuthorityOption[];
	engine_options: BosmaxAuthorityOption[];
	duration_options: BosmaxAuthorityOption[];
	source_route_options: BosmaxAuthorityOption[];
	destination_mode_options: BosmaxAuthorityOption[];
	output_type_options: BosmaxAuthorityOption[];
}

export interface BosmaxProvenanceGroup {
	source_matrix: BosmaxSourceMatrixEntry[];
	missing_sources: BosmaxAuthorityFallback[];
	warnings: string[];
	sales_analyzer_wired_to_prompt_tools: boolean;
}

export interface BosmaxPromptToolContextResponse {
	product: BosmaxProductGroup;
	creative: BosmaxCreativeGroup;
	visual: BosmaxVisualGroup;
	character: BosmaxCharacterGroup;
	execution: BosmaxExecutionGroup;
	provenance: BosmaxProvenanceGroup;
}

export interface PromptPreviewRequest {
	source_route?: string | null;
	destination_mode?: string | null;
	output_type?: string | null;
	product_id?: string | null;
	product_payload?: Record<string, unknown> | null;
	avatar_id?: string | null;
	avatar_selection?: string | null;
	wardrobe_id?: string | null;
	wardrobe_selection?: string | null;
	headwear_style?: string | null;
	scene_context?: string | null;
	camera_style?: string | null;
	camera_behavior?: string | null;
	trigger_id?: string | null;
	silo?: string | null;
	formula?: string | null;
	language?: string | null;
	platform?: string | null;
	engine?: string | null;
	requested_scene?: string | null;
	requested_character?: string | null;
	requested_language?: string | null;
	requested_platform?: string | null;
	requested_engine?: string | null;
	asset_bindings: Record<string, unknown>[];
	target_duration_seconds: number;
	block_duration_seconds: number;
	extension_strategy?: string | null;
	include_temporal_plan: boolean;
	strict_validation: boolean;
	dry_run_only: boolean;
}

export interface PromptPreviewResponse {
	preview_status: "PASS" | "WARN" | "FAIL" | string;
	source_route?: string | null;
	destination_mode?: string | null;
	output_type?: string | null;
	planner_output: Record<string, unknown>;
	adapter_output: Record<string, unknown>;
	composer_output: Record<string, unknown>;
	temporal_output: Record<string, unknown>;
	warnings: string[];
	errors: string[];
	provenance: Record<string, unknown>;
	execution_allowed: boolean;
	flow_execution_allowed: boolean;
	batch_execution_allowed: boolean;
	dry_run_only: boolean;
}

export type ProductAssetIntent =
	| "CHARACTER_CONCEPT"
	| "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT"
	| "PRODUCT_LIFESTYLE_IMAGE_PROMPT"
	| "SCENE_REFERENCE_PROMPT"
	| "STYLE_REFERENCE_PROMPT"
	| "INGREDIENTS_ASSET_BUNDLE";

export interface ProductAssetGeneratorRequest {
	product_id?: string | null;
	product_payload?: Record<string, unknown> | null;
	target_asset_intent: ProductAssetIntent | string;
	gender?: string | null;
	ethnicity?: string | null;
	age_range?: string | null;
	scene_context?: string | null;
	platform?: string | null;
	language?: string | null;
	camera_style?: string | null;
	camera_behavior?: string | null;
	wardrobe?: string | null;
	headwear?: string | null;
	include_product_in_hand?: boolean;
	target_destination_mode?: string | null;
	strict_validation?: boolean;
	dry_run_only: boolean;
	// Image reference slots — Creative Library assets
	character_reference_asset_id?: string | null;
	scene_context_reference_asset_id?: string | null;
	style_reference_asset_id?: string | null;
	// Character consistency mode: when true + scene_context_reference provided,
	// the character image anchors identity and scene becomes the new environment.
	character_anchor_mode?: boolean;
}

export interface ProductAssetGeneratorResponse {
	preview_status: "PASS" | "WARN" | "FAIL" | string;
	target_asset_intent?: string | null;
	product_context: Record<string, unknown>;
	derived_asset_suggestions: Record<string, unknown>[];
	prompt_suggestions: Record<string, unknown>[];
	required_assets: Record<string, unknown>[];
	missing_assets: Record<string, unknown>[];
	handling_notes: string[];
	physics_notes: string[];
	scene_notes: string[];
	camera_notes: string[];
	warning_summary: string[];
	warnings: string[];
	truth_warnings: string[];
	preview_warnings: string[];
	errors: string[];
	provenance: Record<string, unknown>;
	truth_status: Record<string, unknown>;
	dry_run_only: boolean;
	execution_allowed: boolean;
	image_generation_allowed: boolean;
	flow_execution_allowed: boolean;
	batch_execution_allowed: boolean;
}

export interface ModeReadiness {
	status: string;
	detail: string;
	missing_evidence: string[];
}

export interface ProductKnowledgeCompleteRequest {
	product_name?: string;
	product_knowledge_text?: string;
	benefits_text?: string;
	usage_text?: string;
	target_customer_text?: string;
	ingredients_text?: string;
	warnings_text?: string;
	price?: number;
	currency?: string;
	commission_amount?: number;
	commission_rate?: string;
	size_or_volume?: string;
	package_notes?: string;
	image_notes?: string;
	product_form_factor?: string;
	packaging_description?: string;
	source_lane?: string;
	image_url?: string;
	product_url?: string;
	source_url?: string;
	tiktok_product_url?: string;
	tiktok_shop_url?: string;
	local_image_path?: string;
	image_base64?: string;
	image_filename?: string;
	paste_anything_about_product?: string;
}

export interface ProductKnowledgeCompleteResponse {
	completion_status: string;
	input_quality_status: string;
	declared_evidence_summary: string;
	declared_input_fields: Record<string, DisplayFieldValue>;
	extracted_product_facts: Record<string, DisplayFieldValue>;
	suggested_normalized_name?: string;
	suggested_size_or_volume?: string;
	suggested_package_notes?: string;
	suggested_source_lane?: string;
	suggested_category?: string;
	suggested_subcategory?: string;
	suggested_type?: string;
	suggested_bosmax_product_family?: string;
	suggested_package_form?: string;
	suggested_physical_state?: string;
	suggested_product_scale_class?: string;
	suggested_physics_class?: string;
	suggested_handling_profile?: string;
	suggested_recommended_grip?: string;
	suggested_section_5_product_physics_prompt?: string;
	suggested_copy_route?: string;
	suggested_copy_formula?: string;
	suggested_silo?: string;
	suggested_trigger_id?: string;
	suggested_target_customer?: string;
	suggested_usage_summary?: string;
	suggested_usp_list: string[];
	suggested_hook_angles: string[];
	suggested_cta_angles: string[];
	claim_tokens: string[];
	claim_gate: string;
	claim_risk_level: string;
	copy_safety_notes?: string;
	image_analysis_status: string;
	image_analysis_provider: string;
	image_analysis_visual_confidence: string;
	image_analysis_warnings: string[];
	image_analysis_detected_package?: string;
	image_analysis_detected_text: string[];
	image_analysis_local_image_path?: string;
	image_analysis_image_url?: string;
	extraction_status?: string | null;
	missing_required_evidence: string[];
	human_review_fields: string[];
	blocked_fields: string[];
	readiness_by_mode: Record<string, ModeReadiness>;
	provenance: string[];
	warnings: string[];
	errors: string[];
}

export interface AIFormImportResponse {
	import_id: string;
	parse_status: "PARSED" | "PARSE_ERROR" | "VALIDATION_ERROR";
	parse_error_code?: string | null;
	parse_error_detail?: string | null;
	parsed_request: ProductKnowledgeCompleteRequest | null;
	parse_warnings: string[];
	parse_errors: string[];
	accepted_formats: string[];
	detected_extension?: string | null;
	detected_content_type?: string | null;
	parser_strategy_used?: string | null;
	completion_response: ProductKnowledgeCompleteResponse | null;
	write_back_status: string;
	user_review_required: boolean;
	provenance: string[];
}

export interface RegistrationReviewDraft {
	review_draft_id: string;
	review_status:
		| "REVIEW_READY"
		| "NEEDS_HUMAN_REVIEW"
		| "BLOCKED"
		| "COMMITTED";
	source_lane: string;
	declared_evidence_fields: Record<string, DisplayFieldValue>;
	system_inferred_fields: Record<string, DisplayFieldValue>;
	canonical_candidate_fields: Record<string, DisplayFieldValue>;
	human_review_fields: string[];
	blocked_fields: string[];
	missing_required_evidence: string[];
	claim_gate: string;
	claim_tokens: string[];
	claim_risk_level: string;
	copy_safety_notes: string | null;
	taxonomy_status: string;
	taxonomy_conflict: boolean;
	taxonomy_conflict_reason: string | null;
	product_family_status: string;
	physics_status: string;
	scale_truth_status: string;
	registration_gate_status: string;
	write_back_allowed: boolean;
	write_back_performed: boolean;
	write_back_status: string;
	user_actions: string[];
	approval_checklist: Record<string, boolean>;
	rejection_checklist: Record<string, boolean>;
	readiness_by_mode: Record<string, ModeReadiness>;
	provenance: string[];
	warnings: string[];
	errors: string[];
	draft_freshness_status: string;
	last_evidence_edit_at?: string;
	last_recomputed_at?: string;
	image_asset_status: string;
	image_asset_detail?: string | null;
	created_at?: string;
	updated_at?: string;
	fastmoss_reference_id?: string | null;
}

export interface RegistrationReviewDraftFieldDecisions {
	approved_fields: string[];
	rejected_fields: string[];
	edited_declared_evidence: Record<string, DisplayFieldValue>;
	requested_more_evidence_fields: string[];
}

export interface RegistrationReviewDraftEvidencePatchRequest {
	product_name?: string;
	product_knowledge_text?: string;
	benefits_text?: string;
	usage_text?: string;
	target_customer_text?: string;
	ingredients_text?: string;
	warnings_text?: string;
	paste_anything_about_product?: string;
	price?: number;
	currency?: string;
	commission_amount?: number;
	commission_rate?: string;
	size_or_volume?: string;
	package_notes?: string;
	product_url?: string;
	source_url?: string;
	tiktok_product_url?: string;
	tiktok_shop_url?: string;
	image_url?: string;
	local_image_path?: string;
	image_base64?: string;
	image_filename?: string;
	hook_angles?: string[];
	cta_angles?: string[];
	recompute?: boolean;
}

export interface RegistrationCommitRequest {
	draft_id: string;
	write_back_confirmed: boolean;
	user_confirmation_phrase: string;
	commit_reason?: string;
}

export interface RegistrationCommitResponse {
	commit_status: "COMMITTED" | "BLOCKED" | "FAILED";
	write_back_performed: boolean;
	committed_product_id?: string;
	committed_fields?: string[];
	excluded_fields?: string[];
	blocked_reasons?: string[];
	errors?: string[];
	provenance?: string[];
}

// ─── Workspace Generation Package (Prompt Handoff Bank) ─────

export type WorkspaceGenerationPackageStatus =
	| "DRAFT"
	| "READY_MANUAL"
	| "READY_DOM_STAGED"
	| "BLOCKED"
	| "ARCHIVED";

export interface WorkspaceGenerationPackageAsset {
	slot_key: string;
	label: string;
	asset_id: string | null;
	preview_url: string | null;
	download_url: string | null;
	source?: string;
}

export interface WorkspaceGenerationPackageManualHandoff {
	copy_prompt_available: boolean;
	final_prompt_text: string;
	upload_order: string[];
	actions: Array<{
		action: string;
		label: string;
		slot_key?: string;
		preview_url?: string | null;
		download_url?: string | null;
		available: boolean;
	}>;
	blockers: string[];
	warnings: string[];
	manual_fallback_ready: boolean;
	dom_handoff_note: string;
}

export interface WorkspaceGenerationPackageDomScaffold {
	mode: string;
	lineage: {
		product_id: string;
		prompt_package_snapshot_id: string;
		workspace_execution_package_id: string | null;
		workspace_generation_package_id: string;
		prompt_fingerprint: string;
		asset_fingerprints: string[];
	};
	prompt: {
		final_text: string;
		blocks: unknown[];
		generation_mode: string;
	};
	assets: Record<string, WorkspaceGenerationPackageAsset | null>;
	settings: Record<string, unknown>;
	semantic_resolution: Record<string, unknown>;
	manual_handoff: { upload_order: string[] };
	readiness: {
		manual_handoff_ready: boolean;
		dom_handoff_ready: false; // always false in this wave
		blockers: string[];
		warnings: string[];
	};
}

export interface WorkspaceGenerationPackage {
	workspace_generation_package_id: string;
	mode: string;
	product_id: string;
	product_name_snapshot: string;
	source_lane: string;
	prompt_package_snapshot_id: string;
	workspace_execution_package_id: string | null;
	generation_mode: string;
	final_prompt_text: string;
	prompt_blocks_json: unknown[];
	selected_assets_json: Record<string, unknown>;
	resolved_engine_slots_json: Record<string, string | null>;
	resolver_output_json: Record<string, unknown>;
	image_assets_json: Record<string, WorkspaceGenerationPackageAsset | null>;
	manual_handoff_json: WorkspaceGenerationPackageManualHandoff;
	dom_handoff_payload_json: WorkspaceGenerationPackageDomScaffold;
	blockers_json: string[];
	warnings_json: string[];
	status: WorkspaceGenerationPackageStatus;
	operator_notes: string | null;
	batch_run_id: string | null;
	// Prompt Queue / Production Queue separation (additive backend fields)
	logical_mode?: string | null;
	variation_strategy?: string | null;
	prompt_fingerprint?: string | null;
	variation_fingerprints_json?: unknown;
	anti_redundancy_json?:
		| { hard_blocks?: string[]; warnings?: string[] }
		| string
		| null;
	production_status?: string | null;
	production_run_id?: string | null;
	production_error?: string | null;
	artifact_media_ids_json?: string[] | string | null;
	approved_at?: string | null;
	sent_to_production_at?: string | null;
	created_at: string;
	updated_at: string;
}

export interface WorkspaceGenerationPackageListResponse {
	packages: WorkspaceGenerationPackage[];
	count: number;
}

export interface F2VGenerationPackageRequest {
	product_id: string;
	workspace_execution_package_id?: string | null;
	generation_mode?: string;
	duration_seconds?: number;
	target_language?: string;
	camera_style?: string;
	character_presence?: string;
	creator_persona?: string;
	overlay_enabled?: boolean;
	dialogue_enabled?: boolean;
	source_mode?: "HYBRID" | "FRAMES";
	blocks?: Array<{ block_index: number; duration_seconds: number }>;
	start_frame_asset_id?: string | null;
	start_frame_preview_url?: string | null;
	start_frame_download_url?: string | null;
	end_frame_asset_id?: string | null;
	end_frame_preview_url?: string | null;
	end_frame_download_url?: string | null;
	operator_notes?: string | null;
}

export interface I2VGenerationPackageRequest {
	product_id: string;
	workspace_execution_package_id?: string | null;
	recipe_id?: string;
	generation_mode?: string;
	target_language?: string;
	camera_style?: string;
	character_presence?: string;
	creator_persona?: string;
	overlay_enabled?: boolean;
	dialogue_enabled?: boolean;
	product_reference_asset_id?: string | null;
	character_reference_asset_id?: string | null;
	scene_context_reference_asset_id?: string | null;
	style_reference_asset_id?: string | null;
	operator_notes?: string | null;
}

export type BulkPromotionStatus =
	| "PENDING_DRAFT"
	| "DRAFT_GENERATED"
	| "READY_FOR_APPROVAL"
	| "NEEDS_REVIEW"
	| "MISSING_REQUIRED_FIELD"
	| "CLAIM_RISK"
	| "IMAGE_MISSING"
	| "DUPLICATE_SUSPECTED"
	| "DUPLICATE_LINKED"
	| "APPROVED"
	| "REJECTED";

export type BulkClaimRisk = "LOW" | "MEDIUM" | "HIGH" | "UNKNOWN";
export type BulkImageReadiness = "IMAGE_PRESENT" | "IMAGE_MISSING";

export interface FastmossBulkQueueRow {
	reference_id: string;
	raw_product_title: string;
	source_url?: string | null;
	tiktok_product_url?: string | null;
	image_url?: string | null;
	category?: string | null;
	claim_risk_level: BulkClaimRisk;
	mapping_confidence?: number | null;
	image_readiness: BulkImageReadiness;
	copy_route?: string | null;
	sold_count?: number | null;
	commission_rate?: string | null;
	promotion_status: BulkPromotionStatus;
	draft_id?: string | null;
	committed_product_id?: string | null;
	suspected_existing_product_id?: string | null;
	suspected_existing_product_title?: string | null;
	suspected_existing_product_source?: string | null;
	suspected_existing_product_mapping_source?: string | null;
	duplicate_match_reason?: string | null;
	linked_product_id?: string | null;
	linked_product_title?: string | null;
	duplicate_resolution?: string | null;
	duplicate_resolved_at?: string | null;
	duplicate_resolution_note?: string | null;
	duplicate_ignore_product_id?: string | null;
	error_message?: string | null;
	batch_provenance?: string | null;
	duplicate_candidate?: {
		product_id: string;
		title?: string | null;
		source?: string | null;
		mapping_source?: string | null;
		match_reason?: string | null;
	} | null;
	content_generation_allowed?: boolean;
	resolved_product_id?: string | null;
	content_generation_reason?: string | null;
	created_at: string;
	updated_at: string;
}

export interface BulkQueuePage {
	items: FastmossBulkQueueRow[];
	total: number;
	page: number;
	page_size: number;
}

export interface BulkQueueStats {
	total: number;
	by_status: Record<string, number>;
	by_risk: Record<string, number>;
}

export interface BulkCreateDraftsResult {
	success: number;
	failed: number;
	results: Array<{
		reference_id: string;
		status: "OK" | "ERROR";
		draft_id?: string | null;
		promotion_status?: string | null;
		error?: string | null;
	}>;
}

export interface BulkApproveResult {
	approved: number;
	skipped: number;
	failed: number;
	results: Array<{
		reference_id: string;
		outcome: "APPROVED" | "SKIPPED" | "FAILED";
		reason?: string | null;
		committed_product_id?: string | null;
		commit_status?: string | null;
	}>;
}

export interface BulkRecomputeSelectedResult {
	recomputed: number;
	ready_for_approval: number;
	missing_required_field: number;
	claim_risk: number;
	duplicate_suspected: number;
	image_missing: number;
	failed: number;
	skipped: number;
	results: Array<{
		reference_id: string;
		previous_status?: string | null;
		new_status?: string | null;
		previous_error_message?: string | null;
		new_error_message?: string | null;
		draft_id?: string | null;
		outcome: "OK" | "SKIPPED" | "ERROR";
		error?: string | null;
	}>;
}

export type DuplicateReviewAction =
	| "LINK_TO_EXISTING_PRODUCT"
	| "MARK_FALSE_DUPLICATE"
	| "KEEP_BLOCKED"
	| "REJECT_REFERENCE";

export interface BulkDuplicateResolveResult {
	reference_id: string;
	action: DuplicateReviewAction;
	previous_status: string;
	new_status: string;
	linked_product_id?: string | null;
	duplicate_resolution?: string | null;
	content_generation_allowed: boolean;
	message: string;
}
