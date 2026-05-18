import type {
	ApprovedProductPackage,
	PromptCameraStyle,
	PromptCharacterPresence,
	PromptCompilerRuntimeConfig,
	PromptGenerationMode,
	PromptTargetLanguage,
	WorkspaceExecutionPackage,
	WorkspaceMode,
	WorkspacePackageReadinessResponse,
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
	blocks?: Array<{
		block_index: number;
		duration_seconds: number;
	}>;
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
			overlay_enabled: true,
			dialogue_enabled: true,
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
