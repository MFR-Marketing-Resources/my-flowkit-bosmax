import { describe, expect, it } from "vitest";
import {
	avatarRegistryLabel,
	avatarRegistryPreviewUrl,
	buildAvatarRegistryReferenceAssets,
	filterRecipesToAvatarRegistry,
	resolveAvatarRegistryCode,
	type AvatarRegistryPoolRow,
} from "./avatarRegistry";
import type { CreativeAsset } from "../types";

const REGISTRY: AvatarRegistryPoolRow[] = [
	{
		avatar_code: "BOS_F_FARAH_01",
		character_name: "Farah",
		generated_asset_id: "ca_registry_farah",
	},
];

function makeAsset(overrides: Partial<CreativeAsset>): CreativeAsset {
	return {
		asset_id: "asset-default",
		semantic_role: "CHARACTER_REFERENCE",
		display_name: "Default asset",
		description: null,
		source_type: "UPLOAD",
		storage_kind: "LOCAL_FILE",
		preview_url: null,
		download_url: null,
		media_id: null,
		local_file_path: null,
		remote_source_url: null,
		product_id: null,
		category: null,
		silo: null,
		product_type: null,
		allowed_modes: [],
		engine_slot_eligibility: [],
		visual_dna_summary: null,
		character_dna: null,
		scene_context_dna: null,
		style_mood_dna: null,
		source_prompt_fingerprint: null,
		source_workspace_execution_package_id: null,
		source_prompt_package_snapshot_id: null,
		review_status: "APPROVED",
		status: "ACTIVE",
		created_at: "2026-08-07T00:00:00Z",
		updated_at: "2026-08-07T00:00:00Z",
		...overrides,
	};
}

describe("Avatar Registry authority", () => {
	it("allows F2V presenter recipes only when their code is in the registry", () => {
		const recipes = [
			{ avatar_code: "BOS_F_FARAH_01", scene_template_id: "SCN-1" },
			{ avatar_code: "ca_img_fastlane_generated", scene_template_id: "SCN-2" },
		];

		expect(filterRecipesToAvatarRegistry(recipes, REGISTRY)).toEqual([recipes[0]]);
		expect(resolveAvatarRegistryCode("bos_f_farAH_01", REGISTRY)).toBe(
			"BOS_F_FARAH_01",
		);
		expect(resolveAvatarRegistryCode("ca_img_fastlane_generated", REGISTRY)).toBe("");
	});

	it("maps only approved registry assets into visual reference options", () => {
		const assets: CreativeAsset[] = [
			makeAsset({
				asset_id: "ca_registry_farah",
				display_name: "Farah source",
			}),
			makeAsset({
				asset_id: "ca_img_fastlane_generated",
				display_name: "IMG Fastlane composite",
			}),
		];

		expect(buildAvatarRegistryReferenceAssets(REGISTRY, assets)).toEqual([
			{
				...assets[0],
				display_name: "Farah — BOS_F_FARAH_01",
			},
		]);
	});

	it("renders canonical names and lower-case variants without code duplication", () => {
		expect(
			avatarRegistryLabel({
				avatar_code: "BOS_F_ALYA_01",
				character_name: "Alya",
				variant: "Modest creator",
			}),
		).toBe("Alya · Modest creator");
		expect(
			avatarRegistryLabel({
				avatar_code: "BOS_F_ALYA_01",
				character_name: "BOS_F_ALYA_01",
			}),
		).toBe("BOS_F_ALYA_01");
	});

	it("falls back to the generated registry asset preview endpoint", () => {
		const row = {
			avatar_code: "BOS_F_ALYA_01",
			generated_asset_id: "ca alya/01",
		};
		expect(avatarRegistryPreviewUrl(row, {})).toBe(
			"/api/creative-assets/ca%20alya%2F01/preview",
		);
		expect(
			avatarRegistryPreviewUrl(row, {
				"ca alya/01": "/approved-preview.jpg",
			}),
		).toBe("/approved-preview.jpg");
		expect(avatarRegistryPreviewUrl({}, {})).toBeNull();
	});
});
