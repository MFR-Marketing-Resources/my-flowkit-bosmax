import { postAPI } from "./client";
import type { PosterDeliverableRow } from "../types/posterCopySet";

export interface PosterV2ComposeRequest {
	product_id: string;
	staff_id: string;
	recipe_id: string;
	background_media_id?: string;
	background_local_path?: string;
	creative_mode?: string;
	image_model?: string;
	settings?: Record<string, unknown>;
	copy_v2_context?: Record<string, unknown>;
}

export type PosterV2DeliverableRow = Omit<PosterDeliverableRow, "poster_copy_set_id"> & {
	copy_blueprint_id_v2: string;
	copy_blueprint_revision_v2: number;
	copy_execution_binding_id_v2: string;
	copy_approval_snapshot_id_v2: string;
};

export interface PosterV2ComposeResponse {
	deliverable: PosterV2DeliverableRow;
	render_report: Record<string, unknown>;
	qa_report: Record<string, unknown>;
	composition_plan?: Record<string, unknown>;
	copy_architecture_v2?: Record<string, unknown>;
	copy_execution_binding?: Record<string, unknown>;
}

/**
 * Deterministic, provider-free poster composition. Copy is always resolved by
 * the backend from the product's active Copy Blueprint V2 binding; this client
 * intentionally has no poster_copy_set_id field.
 */
export async function composePosterV2(
	payload: PosterV2ComposeRequest,
): Promise<PosterV2ComposeResponse> {
	return postAPI<PosterV2ComposeResponse>("/api/poster/compose", payload);
}

export function posterV2OutputUrl(posterDeliverableId: string): string {
	return `/api/poster/deliverables/${encodeURIComponent(posterDeliverableId)}/output`;
}
