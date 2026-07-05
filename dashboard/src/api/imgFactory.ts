import type { CreativeAsset } from "../types";
import { fetchAPI, postAPI } from "./client";

export interface ImgAssetLane {
	lane_id: string;
	label: string;
	family: string;
	purpose: string;
	required_inputs: string[];
	optional_inputs: string[];
	requires_product_id: boolean;
	requires_character_reference: boolean;
	requires_scene_reference: boolean;
	requires_style_reference: boolean;
	default_semantic_role: string;
	default_asset_subtype: string;
	default_allowed_modes: string[];
	default_engine_slot_eligibility: string[];
	allows_rendered_text: boolean;
	default_contains_rendered_text: boolean;
	default_approved_for_video_support: boolean;
	default_approved_for_poster: boolean;
}

export interface ImgAssetLaneListResponse {
	items: ImgAssetLane[];
	total: number;
}

export interface ImgProviderStatus {
	provider_state: "RUNTIME_PROVEN" | "NOT_CONFIGURED";
	detail: string;
	generation_endpoint?: string | null;
}

export interface SaveImgOutputInput {
	lane_id: string;
	display_name: string;
	description?: string | null;
	generated_artifact_media_id?: string | null;
	image_base64?: string | null;
	file_name?: string | null;
	product_id?: string | null;
	source_character_asset_id?: string | null;
	source_scene_asset_id?: string | null;
	source_style_asset_id?: string | null;
	source_prompt_fingerprint?: string | null;
	source_workspace_execution_package_id?: string | null;
	source_prompt_package_snapshot_id?: string | null;
	category?: string | null;
	silo?: string | null;
	product_type?: string | null;
	identity_lock_status?: string | null;
	scale_truth_status?: string | null;
	claim_safety_status?: string | null;
	review_status?: "DRAFT" | "PENDING_REVIEW" | "APPROVED" | "REJECTED";
}

export async function fetchImgAssetLanes(): Promise<ImgAssetLaneListResponse> {
	return fetchAPI<ImgAssetLaneListResponse>("/api/img-factory/lanes");
}

export async function fetchImgProviderStatus(): Promise<ImgProviderStatus> {
	return fetchAPI<ImgProviderStatus>("/api/img-factory/provider-status");
}

export async function saveImgOutputToLibrary(
	input: SaveImgOutputInput,
): Promise<CreativeAsset> {
	return postAPI<CreativeAsset>("/api/img-factory/save", input);
}
