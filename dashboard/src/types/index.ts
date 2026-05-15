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
	mediaId: string;
	characterId?: string;
	entityType?: ManualEntityType;
	fileName: string;
	previewUrl?: string;
}

export interface Product {
	id: string;
	product_id?: string;
	source: "FASTMOSS" | "TIKTOKSHOP" | "MANUAL" | "IMPORTED";
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
	shop_count?: number | null;
	shop_names?: string[];
	image_analysis_status?: string | null;
	intelligence_confidence?: "HIGH" | "MEDIUM" | "LOW" | null;
	intelligence_status?: string | null;
	intelligence_warnings?: string[];
	intelligence_provenance?: string[];
	taxonomy_conflict?: boolean;
	taxonomy_conflict_reason?: string | null;
	sales_metrics?: {
		sold_count: number | null;
		shop_count: number | null;
		shop_names: string[];
		source_status: string;
	};
	image_analysis?: {
		status: string;
		image_url: string | null;
		local_image_path: string | null;
		detected_package: string | null;
		detected_text: string | null;
		confidence: string;
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
	last_health_check: string | null;
	license_status: string;
	approval_status: string;
	registration: LocalAgentRegistration;
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
