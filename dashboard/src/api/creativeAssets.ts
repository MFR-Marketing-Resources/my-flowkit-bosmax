import type {
	CreativeAsset,
	CreativeAssetEligibilityAuditResponse,
	CreativeAssetEligibilityAuditSurface,
	CreativeAssetEngineSlot,
	CreativeAssetListResponse,
	CreativeAssetSemanticRole,
	CreativeAssetSourceType,
	CreativeAssetStatus,
	CreativeAssetStorageKind,
	WorkspaceMode,
} from "../types";
import { fetchAPI, patchAPI, postAPI } from "./client";

function normalizeJsonishInput(
	value: string | null | undefined,
): Record<string, unknown> | string | null {
	const trimmed = String(value ?? "").trim();
	if (!trimmed) return null;
	try {
		return JSON.parse(trimmed) as Record<string, unknown>;
	} catch {
		return trimmed;
	}
}

async function fileToDataUrl(file: File): Promise<string> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result || ""));
		reader.onerror = reject;
		reader.readAsDataURL(file);
	});
}

export async function fetchCreativeAssets(
	input: {
		semantic_role?: CreativeAssetSemanticRole;
		status?: CreativeAssetStatus;
		allowed_mode?: WorkspaceMode;
		engine_slot?: CreativeAssetEngineSlot;
		product_id?: string;
		search?: string;
		limit?: number;
	} = {},
): Promise<CreativeAssetListResponse> {
	const params = new URLSearchParams();
	if (input.semantic_role) params.set("semantic_role", input.semantic_role);
	if (input.status) params.set("status", input.status);
	if (input.allowed_mode) params.set("allowed_mode", input.allowed_mode);
	if (input.engine_slot) params.set("engine_slot", input.engine_slot);
	if (input.product_id) params.set("product_id", input.product_id);
	if (input.search) params.set("search", input.search);
	params.set("limit", String(input.limit ?? 200));
	return fetchAPI<CreativeAssetListResponse>(
		`/api/creative-assets?${params.toString()}`,
	);
}

export async function fetchCreativeAssetEligibilityAudit(input: {
	surface: CreativeAssetEligibilityAuditSurface;
	recipe_id?: string;
	limit?: number;
}): Promise<CreativeAssetEligibilityAuditResponse> {
	const params = new URLSearchParams();
	params.set("surface", input.surface);
	if (input.recipe_id) params.set("recipe_id", input.recipe_id);
	params.set("limit", String(input.limit ?? 1000));
	// Collision-proof audit route: shares no path space with
	// /api/creative-assets/{asset_id}, so a stale backend answers 404 Not Found
	// (an honest miss) instead of the misleading CREATIVE_ASSET_NOT_FOUND.
	return fetchAPI<CreativeAssetEligibilityAuditResponse>(
		`/api/creative-asset-eligibility/audit?${params.toString()}`,
	);
}

export async function createCreativeAsset(input: {
	display_name: string;
	semantic_role: CreativeAssetSemanticRole;
	description?: string;
	source_type?: CreativeAssetSourceType;
	storage_kind?: CreativeAssetStorageKind;
	file?: File | null;
	product_id?: string;
	category?: string;
	silo?: string;
	product_type?: string;
	allowed_modes?: WorkspaceMode[];
	engine_slot_eligibility?: CreativeAssetEngineSlot[];
	visual_dna_summary?: string;
	character_dna?: string;
	scene_context_dna?: string;
	style_mood_dna?: string;
	mode_a_metadata_handoff?: string;
	remote_source_url?: string;
	preview_url?: string;
	download_url?: string;
}): Promise<CreativeAsset> {
	const image_base64 = input.file ? await fileToDataUrl(input.file) : undefined;
	return postAPI<CreativeAsset>("/api/creative-assets", {
		display_name: input.display_name,
		semantic_role: input.semantic_role,
		description: input.description ?? null,
		source_type: input.source_type ?? (input.file ? "UPLOAD" : "REMOTE_URL"),
		storage_kind:
			input.storage_kind ?? (input.file ? "LOCAL_FILE" : "REMOTE_URL"),
		product_id: input.product_id ?? null,
		category: input.category ?? null,
		silo: input.silo ?? null,
		product_type: input.product_type ?? null,
		allowed_modes: input.allowed_modes ?? [],
		engine_slot_eligibility: input.engine_slot_eligibility ?? [],
		visual_dna_summary: input.visual_dna_summary ?? null,
		character_dna: input.character_dna ?? null,
		scene_context_dna: input.scene_context_dna ?? null,
		style_mood_dna: input.style_mood_dna ?? null,
		mode_a_metadata_handoff: normalizeJsonishInput(
			input.mode_a_metadata_handoff,
		),
		remote_source_url: input.remote_source_url ?? null,
		preview_url: input.preview_url ?? null,
		download_url: input.download_url ?? null,
		image_base64,
		file_name: input.file?.name ?? null,
	});
}

export async function updateCreativeAsset(
	assetId: string,
	input: {
		display_name?: string;
		description?: string;
		product_id?: string | null;
		category?: string | null;
		silo?: string | null;
		product_type?: string | null;
		allowed_modes?: WorkspaceMode[];
		engine_slot_eligibility?: CreativeAssetEngineSlot[];
		visual_dna_summary?: string | null;
		character_dna?: string | null;
		scene_context_dna?: string | null;
		style_mood_dna?: string | null;
		mode_a_metadata_handoff?: string | null;
		// Review lifecycle + truth/safety gates (backend CreativeAssetUpdateRequest).
		review_status?: "DRAFT" | "PENDING_REVIEW" | "APPROVED" | "REJECTED";
		identity_lock_status?: string | null;
		scale_truth_status?: string | null;
		claim_safety_status?: string | null;
		approved_for_video_support?: boolean;
		approved_for_poster?: boolean;
	},
): Promise<CreativeAsset> {
	// Only touch mode_a_metadata_handoff when the caller explicitly provided the key.
	// Previously it was ALWAYS sent (normalized to null when omitted), so a review-only
	// PATCH like { review_status: "APPROVED" } cleared the asset's existing metadata.
	const body: Record<string, unknown> = { ...input };
	if ("mode_a_metadata_handoff" in input) {
		body.mode_a_metadata_handoff = normalizeJsonishInput(
			input.mode_a_metadata_handoff,
		);
	}
	return patchAPI<CreativeAsset>(`/api/creative-assets/${assetId}`, body);
}

export async function archiveCreativeAsset(
	assetId: string,
): Promise<CreativeAsset> {
	return postAPI<CreativeAsset>(`/api/creative-assets/${assetId}/archive`, {});
}

export async function unarchiveCreativeAsset(
	assetId: string,
): Promise<CreativeAsset> {
	return postAPI<CreativeAsset>(
		`/api/creative-assets/${assetId}/unarchive`,
		{},
	);
}
