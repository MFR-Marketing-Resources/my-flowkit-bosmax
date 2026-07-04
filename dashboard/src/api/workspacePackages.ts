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
	character_reference_asset_id?: string | null;
	scene_context_reference_asset_id?: string | null;
	style_reference_asset_id?: string | null;
	blocks?: Array<{
		block_index: number;
		duration_seconds: number;
	}>;
	// Copy Selection & Compiler Binding V1: operator-selected approved Copy Set.
	copy_set_id?: string | null;
}): Promise<WorkspaceExecutionPackage> {
	return postAPI<WorkspaceExecutionPackage>(
		"/api/workspace/execution-package",
		{
			duration_seconds: 8,
			aspect_ratio: "9:16",
			manual_override: false,
			generation_mode: "SINGLE",
			target_language: "BM_MS",
			camera_style: "UGC_IPHONE_RAW",
			character_presence: "VISIBLE_CREATOR",
			creator_persona: "DEFAULT_CREATOR",
			overlay_enabled: false, // NO_OVERLAY law (ADR-008): default off
			dialogue_enabled: true,
			recipe_id: "PRODUCT_HELD_BY_CHARACTER_IN_SCENE",
			product_reference_asset_id: null,
			character_reference_asset_id: null,
			scene_context_reference_asset_id: null,
			style_reference_asset_id: null,
			blocks: [],
			...input,
		},
	);
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
	return postAPI<WorkspacePromptPreviewResult>(
		"/api/workspace/ugc-video-prompt-compile",
		{
			duration_seconds: 8,
			generation_mode: "SINGLE",
			target_language: "BM_MS",
			camera_style: "UGC_IPHONE_RAW",
			character_presence: "VISIBLE_CREATOR",
			creator_persona: "DEFAULT_CREATOR",
			overlay_enabled: false, // NO_OVERLAY law (ADR-008): default off
			dialogue_enabled: true,
			blocks: [],
			...input,
		},
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
