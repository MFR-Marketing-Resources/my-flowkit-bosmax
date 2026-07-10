// Poster Copy Set + AI Poster Copy Assistant + compositor API clients
// (POSTER_BUILDER_V2). Poster-native domain — separate from /api/copy-sets.
import { getAPI, patchAPI, postAPI } from "./client";
import type {
	PosterAngleRecommendation,
	PosterComposeResponse,
	PosterCopyDirection,
	PosterCopySet,
	PosterDeliverableReconstruction,
	PosterObjectiveRecommendation,
} from "../types/posterCopySet";

export async function recommendPosterObjectives(payload: {
	product_id: string;
	refresh_ai?: boolean;
}): Promise<{
	recommendations: PosterObjectiveRecommendation[];
	warnings: string[];
}> {
	return postAPI("/poster/copy-sets/recommend-objectives", payload);
}

export async function recommendPosterAngles(payload: {
	product_id: string;
	archetype: string;
	refresh_ai?: boolean;
}): Promise<{ angles: PosterAngleRecommendation[]; warnings: string[] }> {
	return postAPI("/poster/copy-sets/recommend-angles", payload);
}

export async function generatePosterDirections(payload: {
	product_id: string;
	archetype: string;
	angle: string;
	tone?: string;
	language?: string;
	count?: number;
}): Promise<{
	directions: PosterCopyDirection[];
	ai_model: string;
	prompt_version: string;
	warnings: string[];
}> {
	return postAPI("/poster/copy-sets/directions", payload);
}

export async function regeneratePosterField(payload: {
	product_id: string;
	archetype: string;
	angle: string;
	field: string;
	language?: string;
	fields: Record<string, unknown>;
}): Promise<{ field: string; value: string | string[]; provenance: string }> {
	return postAPI("/poster/copy-sets/regenerate-field", payload);
}

export async function createPosterCopySet(
	payload: Record<string, unknown>,
): Promise<PosterCopySet> {
	return postAPI("/poster/copy-sets", payload);
}

export async function approvePosterCopySet(
	posterCopySetId: string,
	approvalPhrase: string,
): Promise<PosterCopySet> {
	return postAPI(`/poster/copy-sets/${posterCopySetId}/approve`, {
		approval_phrase: approvalPhrase,
		approved_by: "operator",
	});
}

export async function listPosterCopySets(
	productId: string,
): Promise<{ poster_copy_sets: PosterCopySet[] }> {
	return getAPI(`/poster/copy-sets?product_id=${encodeURIComponent(productId)}`);
}

// ── Deterministic compositor (credit-free) ──────────────────────────────────

export async function composePoster(payload: {
	product_id: string;
	poster_copy_set_id: string;
	recipe_id: string;
	background_media_id?: string;
	settings?: Record<string, unknown>;
}): Promise<PosterComposeResponse> {
	return postAPI("/poster/compose", payload);
}

export async function savePosterToLibrary(
	posterDeliverableId: string,
): Promise<{ creative_asset_id: string; already_saved: boolean }> {
	return postAPI(`/poster/deliverables/${posterDeliverableId}/save-to-library`, {});
}

export function posterDeliverableOutputUrl(posterDeliverableId: string): string {
	return `/api/poster/deliverables/${posterDeliverableId}/output`;
}

// Creative Library round trip: reopen a saved poster from its asset id.
export async function fetchPosterDeliverableByAsset(
	creativeAssetId: string,
): Promise<PosterDeliverableReconstruction> {
	return getAPI(
		`/poster/deliverables/by-asset/${encodeURIComponent(creativeAssetId)}`,
	);
}

// Safe edit flow for an APPROVED set: creates DRAFT v(n+1), parent SUPERSEDED.
export async function newPosterCopySetVersion(
	posterCopySetId: string,
	patch: Record<string, unknown>,
): Promise<PosterCopySet> {
	return postAPI(`/poster/copy-sets/${posterCopySetId}/new-version`, patch);
}

export async function patchPosterCopySet(
	posterCopySetId: string,
	patch: Record<string, unknown>,
): Promise<PosterCopySet> {
	return patchAPI(`/poster/copy-sets/${posterCopySetId}`, patch);
}
