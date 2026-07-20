import type {
	ApprovedProductPackage,
	I2VRecipeId,
	I2VSemanticSlotResolverResponse,
	PromptCameraStyle,
	PromptCharacterPresence,
	PromptCompilerRuntimeConfig,
	PromptGenerationMode,
	PromptTargetLanguage,
	WorkspaceExecutionPackage,
	WorkspaceMode,
	WorkspacePackageReadinessResponse,
	WorkspacePromptPreviewResult,
} from "../types";
import { fetchAPI, postAPI } from "./client";

function applyDurationAuthorityDefaults<
	T extends {
		generation_mode?: PromptGenerationMode;
		duration_seconds?: number;
		blocks?: unknown[];
	},
>(request: T) {
	if (request.generation_mode === "EXTEND") {
		const {
			blocks: _rawBlocks,
			duration_seconds: _singleDuration,
			...extendRequest
		} = request;
		return extendRequest;
	}
	return request;
}

export async function fetchApprovedProductPackage(
	productId: string,
	mode: WorkspaceMode,
): Promise<ApprovedProductPackage> {
	return fetchAPI<ApprovedProductPackage>(
		`/api/products/${encodeURIComponent(productId)}/approved-package?mode=${encodeURIComponent(mode)}`,
	);
}

export async function createWorkspaceExecutionPackage(input: {
	product_id: string;
	mode: WorkspaceMode;
	duration_seconds?: number;
	aspect_ratio?: string;
	model?: string;
	manual_override?: boolean;
	generation_mode?: PromptGenerationMode;
	target_language?: PromptTargetLanguage;
	camera_style?: PromptCameraStyle;
	character_presence?: PromptCharacterPresence;
	creator_persona?: string;
	overlay_enabled?: boolean;
	dialogue_enabled?: boolean;
	// Canonical source-mode language (ADR-008): T2V | HYBRID | FRAMES | INGREDIENTS | IMAGES
	source_mode?: "T2V" | "HYBRID" | "FRAMES" | "INGREDIENTS" | "IMAGES";
	engine_duration_target?: "GROK" | "GOOGLE_FLOW";
	requested_total_duration_seconds?: number;
	recipe_id?: I2VRecipeId;
	product_reference_asset_id?: string | null;
	start_frame_asset_id?: string | null;
	end_frame_asset_id?: string | null;
	character_reference_asset_id?: string | null;
	scene_context_reference_asset_id?: string | null;
	style_reference_asset_id?: string | null;
	blocks?: Array<{
		block_index: number;
		duration_seconds: number;
	}>;
	// Copy Selection & Compiler Binding V1: operator-selected approved Copy Set.
	copy_set_id?: string | null;
	// Explicit-Fallback-Confirmation V1: required-true for FINAL generation when
	// no approved Copy Set is selected (backend fails closed otherwise).
	copy_fallback_confirmed?: boolean;
}): Promise<WorkspaceExecutionPackage> {
	const request = applyDurationAuthorityDefaults({
		duration_seconds: 8,
		aspect_ratio: "9:16",
		manual_override: false,
		generation_mode: "SINGLE" as PromptGenerationMode,
		target_language: "BM_MS" as PromptTargetLanguage,
		camera_style: "UGC_IPHONE_RAW" as PromptCameraStyle,
		character_presence: "VISIBLE_CREATOR" as PromptCharacterPresence,
		creator_persona: "DEFAULT_CREATOR",
		overlay_enabled: false,
		dialogue_enabled: true,
		recipe_id: "PRODUCT_HELD_BY_CHARACTER_IN_SCENE" as I2VRecipeId,
		product_reference_asset_id: null,
		start_frame_asset_id: null,
		end_frame_asset_id: null,
		character_reference_asset_id: null,
		scene_context_reference_asset_id: null,
		style_reference_asset_id: null,
		blocks: [],
		...input,
	});
	return postAPI<WorkspaceExecutionPackage>(
		"/api/workspace/execution-package",
		request,
	);
}

// ── Stage 1 quantity PREVIEW (credit-free; no provider/Flow/live) ──
export interface QuantityPreviewItem {
	item_index: number;
	variation_salt: string | null;
	copy_variant_id: string | null;
	hook: string | null;
	dialogue_summary: string | null;
	dialogue_fingerprint: string | null;
	seam_voice: Record<string, unknown> | null;
	compile_error: string | null;
}

export interface QuantityPreviewResult {
	quantity_requested: number;
	quantity_max: number;
	planned_item_count: number;
	logical_mode: string;
	generation_mode: string;
	copy_source: string | null;
	copy_rotation_warnings: string[];
	items: QuantityPreviewItem[];
	dialogue_uniqueness_status: string;
	duplicate_dialogue_groups: number[][];
	blockers: string[];
	preview_ready: boolean;
	live_bulk_status: string;
	live_bulk_stage: string;
	credit: string;
	provider_calls: number;
	flow_calls: number;
}

/** Stage-1 credit-free preview of N unique-copy plans. NEVER fires, approves,
 *  enqueues, or spends credit — the server plans + compiles only. */
export async function previewQuantityCopyPlans(input: {
	product_id: string;
	mode: WorkspaceMode;
	source_mode?: string | null;
	generation_mode?: PromptGenerationMode;
	duration_seconds?: number;
	requested_total_duration_seconds?: number | null;
	quantity: number;
	target_language?: PromptTargetLanguage;
}): Promise<QuantityPreviewResult> {
	return postAPI<QuantityPreviewResult>("/api/workspace/quantity-preview", input);
}

// ── Approved copy-pool readiness (credit-free; read-only) ──
// A copy set stores copy INGREDIENTS, not dialogue — dialogue only exists once the
// compiler renders SECTION 6. So approved_copy_count alone never proves N unique
// items are possible; unique_dialogue_count is the number that matters.
export interface CopyPoolDuplicateGroup {
	dialogue_fingerprint: string;
	copy_set_ids: string[];
}

export type CopyPoolReadinessStatus =
	| "READY"
	| "COPY_POOL_SHORTAGE"
	| "NO_APPROVED_COPY_AVAILABLE";

export interface CopyPoolReadinessResult {
	product_id: string;
	quantity_requested: number;
	quantity_max: number;
	approved_copy_count: number;
	unique_dialogue_count: number;
	shortage_count: number;
	readiness_status: CopyPoolReadinessStatus;
	duplicate_fingerprint_groups: CopyPoolDuplicateGroup[];
	scanned_copy_set_count: number;
	pool_scan_capped: boolean;
	compile_errors: string[];
	next_action: string | null;
	credit: string;
	provider_calls: number;
	flow_calls: number;
}

/** Read-only check of whether a product can supply N UNIQUE approved dialogues.
 *  Compiles approved copy sets to count distinct dialogue. NEVER generates,
 *  approves, enqueues or spends credit. */
export async function fetchCopyPoolReadiness(input: {
	product_id: string;
	mode: WorkspaceMode;
	source_mode?: string | null;
	generation_mode?: PromptGenerationMode;
	duration_seconds?: number;
	requested_total_duration_seconds?: number | null;
	quantity: number;
	target_language?: PromptTargetLanguage;
}): Promise<CopyPoolReadinessResult> {
	return postAPI<CopyPoolReadinessResult>("/api/workspace/copy-pool-readiness", input);
}

// ── Stage 2A itemized bulk fan-out plan (credit-free; read-only) ──
// N SEPARATE intents, never one blind count:N batch — `count` is the provider's
// per-submission copy count, not an item multiplier.
export interface BulkFanoutIntent {
	item_index: number | null;
	copy_variant_id: string | null;
	variation_salt: string | null;
	dialogue_fingerprint: string | null;
	hook: string | null;
	dialogue_summary: string | null;
	seam_voice: Record<string, unknown> | null;
	logical_mode: string;
	source_mode: string | null;
	generation_mode: string;
	workspace_generation_package_id: string | null;
	production_run_id: string | null;
	production_job_id: string | null;
	item_status: string;
	compile_error: string | null;
	credit_state: string;
	credit_warning: string;
}

export interface BulkFanoutPlanResult {
	product_id: string;
	quantity_requested: number;
	quantity_max: number;
	logical_mode: string;
	generation_mode: string;
	planned_intent_count: number;
	intents: BulkFanoutIntent[];
	bulk_plan_fingerprint: string;
	copy_pool_readiness_status: string;
	dialogue_uniqueness_status: string;
	blockers: string[];
	/** All prerequisites proven. Does NOT mean the run may fire — the server
	 *  gate still stops at the Stage 3 credit boundary. */
	bulk_authorizable: boolean;
	live_bulk_status: string;
	live_bulk_stage: string;
	required_confirm_phrase: string;
	credit: string;
	provider_calls: number;
	flow_calls: number;
}

/** Plan N itemized live-production intents. Plans only — creates no package,
 *  approves nothing, enqueues nothing, fires nothing, spends no credit. */
export async function fetchBulkFanoutPlan(input: {
	product_id: string;
	mode: WorkspaceMode;
	source_mode?: string | null;
	generation_mode?: PromptGenerationMode;
	duration_seconds?: number;
	requested_total_duration_seconds?: number | null;
	quantity: number;
	target_language?: PromptTargetLanguage;
}): Promise<BulkFanoutPlanResult> {
	return postAPI<BulkFanoutPlanResult>("/api/workspace/bulk-fanout-plan", input);
}

export async function fetchWorkspaceExecutionPackageHistory(
	productId?: string,
	mode?: WorkspaceMode,
	limit = 20,
): Promise<WorkspaceExecutionPackage[]> {
	const params = new URLSearchParams();
	if (productId) params.set("product_id", productId);
	if (mode) params.set("mode", mode);
	params.set("limit", String(limit));
	return fetchAPI<WorkspaceExecutionPackage[]>(
		`/api/workspace/execution-packages?${params.toString()}`,
	);
}

export async function fetchWorkspacePackageReadiness(input: {
	mode: WorkspaceMode;
	source_mode?: "T2V" | "HYBRID" | "FRAMES" | "INGREDIENTS" | "IMAGES";
	product_ids: string[];
}): Promise<WorkspacePackageReadinessResponse> {
	return postAPI<WorkspacePackageReadinessResponse>(
		"/api/workspace/package-readiness",
		input,
	);
}

export async function fetchPromptCompilerRuntimeConfig(): Promise<PromptCompilerRuntimeConfig> {
	return fetchAPI<PromptCompilerRuntimeConfig>(
		"/api/workspace/prompt-compiler-config",
	);
}

export async function compileWorkspacePromptPreview(input: {
	product_id: string;
	mode: WorkspaceMode;
	duration_seconds?: number;
	generation_mode?: PromptGenerationMode;
	target_language?: PromptTargetLanguage;
	camera_style?: PromptCameraStyle;
	character_presence?: PromptCharacterPresence;
	creator_persona?: string;
	overlay_enabled?: boolean;
	dialogue_enabled?: boolean;
	// Canonical source-mode passthrough (ADR-008)
	source_mode?: "T2V" | "HYBRID" | "FRAMES" | "INGREDIENTS" | "IMAGES";
	engine_duration_target?: "GROK" | "GOOGLE_FLOW";
	requested_total_duration_seconds?: number;
	blocks?: Array<{
		block_index: number;
		duration_seconds: number;
	}>;
	// Copy Selection & Compiler Binding V1: operator-selected approved Copy Set.
	copy_set_id?: string | null;
}): Promise<WorkspacePromptPreviewResult> {
	const request = applyDurationAuthorityDefaults({
		duration_seconds: 8,
		generation_mode: "SINGLE" as PromptGenerationMode,
		target_language: "BM_MS" as PromptTargetLanguage,
		camera_style: "UGC_IPHONE_RAW" as PromptCameraStyle,
		character_presence: "VISIBLE_CREATOR" as PromptCharacterPresence,
		creator_persona: "DEFAULT_CREATOR",
		overlay_enabled: false,
		dialogue_enabled: true,
		blocks: [],
		...input,
	});
	return postAPI<WorkspacePromptPreviewResult>(
		"/api/workspace/ugc-video-prompt-compile",
		request,
	);
}

export async function resolveI2VSemanticSlots(input: {
	product_id: string;
	recipe_id: I2VRecipeId;
	product_reference_asset_id?: string | null;
	character_reference_asset_id?: string | null;
	scene_context_reference_asset_id?: string | null;
	style_reference_asset_id?: string | null;
}): Promise<I2VSemanticSlotResolverResponse> {
	return postAPI<I2VSemanticSlotResolverResponse>(
		"/api/workspace/i2v/resolve-slots",
		{
			mode: "I2V",
			product_reference_asset_id: null,
			character_reference_asset_id: null,
			scene_context_reference_asset_id: null,
			style_reference_asset_id: null,
			...input,
		},
	);
}
