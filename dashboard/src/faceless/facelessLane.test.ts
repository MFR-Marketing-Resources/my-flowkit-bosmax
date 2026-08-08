import { describe, expect, it } from "vitest";
import { CREATIVE_LANE_SETTINGS_UNAVAILABLE } from "../api/creativeLaneSettings";
import {
	FACELESS_CHARACTER_PRESENCE,
	FACELESS_SOURCE_MODE,
	FACELESS_TRANSPORT_MODE,
	buildFacelessGenerateBody,
	facelessPrepareBlockers,
	facelessProductBlocker,
	facelessStartFrameBlocker,
	optionLabel,
	packageSlotResolvedAsset,
} from "./facelessLane";
import type { WorkspaceExecutionPackage } from "../types";

function fakePkg(
	overrides: Partial<WorkspaceExecutionPackage> = {},
): WorkspaceExecutionPackage {
	return {
		source_of_truth_notes: [],
		warnings: [],
		provenance: [],
		workspace_execution_package_id: "wep_test",
		product_id: "prod-1",
		product_name: "Test",
		mode: "F2V",
		duration_seconds: 8,
		aspect_ratio: "9:16",
		model: "",
		manual_override: false,
		prompt_text: "SECTION 1 - ROLE & OBJECTIVE\nFaceless clip prompt",
		prompt_fingerprint: "fp_test",
		prompt_package_snapshot_id: "snap_1",
		asset_slots: [
			{
				slot_key: "start_frame",
				required: true,
				default_source: "CREATIVE_LIBRARY",
				allowed_sources: ["CREATIVE_LIBRARY"],
				resolved_asset: {
					asset_id: "ca_start_selected",
					asset_fingerprint: "fp_start",
					slot_key: "start_frame",
					asset_source: "CREATIVE_LIBRARY_COMPOSITE",
					label: "Start frame",
					file_name: "start.png",
					preview_url: "/api/creative-assets/ca_start_selected/preview",
					download_url: "https://cdn.example.com/start.png",
					media_id: null,
					local_file_path: null,
					remote_image_url_present: true,
				},
			},
		],
		resolved_assets: [],
		readiness: "READY",
		execution_allowed: true,
		production_generation_allowed: true,
		manual_fallback: {
			allowed: false,
			copy_prompt_available: false,
			image_preview_url: null,
			image_download_url: null,
			asset_slots: [],
			execution_checklist: [],
			operator_warning: "",
		},
		blockers: [],
		request_lineage_payload: {
			product_id: "prod-1",
			mode: "F2V",
			prompt_package_snapshot_id: "snap_1",
			workspace_execution_package_id: "wep_test",
			prompt_fingerprint: "fp_test",
			asset_fingerprints: ["fp_start"],
		},
		...overrides,
	} as WorkspaceExecutionPackage;
}

describe("facelessLane", () => {
	it("uses F2V/FRAMES transport with faceless presence", () => {
		expect(FACELESS_TRANSPORT_MODE).toBe("F2V");
		expect(FACELESS_SOURCE_MODE).toBe("FRAMES");
		expect(FACELESS_CHARACTER_PRESENCE).toBe("FACELESS");
	});

	it("fails closed without product or start frame", () => {
		expect(facelessProductBlocker(null)).toMatch(/product/i);
		expect(facelessStartFrameBlocker("")).toMatch(/start frame/i);
		expect(
					facelessPrepareBlockers({ productId: null, startFrameAssetId: null }),
				).toHaveLength(3); // product + start frame + model
				expect(
					facelessPrepareBlockers({
						productId: "p1",
						startFrameAssetId: "asset-1",
						model: "Veo 3.1 - Lite",
					}),
				).toEqual([]);
			});

	it("frontend settings shell is fail-closed empty (no second SSOT vocab)", () => {
		expect(CREATIVE_LANE_SETTINGS_UNAVAILABLE.source).toBe("unavailable");
		expect(CREATIVE_LANE_SETTINGS_UNAVAILABLE.hook.options).toEqual([]);
		expect(CREATIVE_LANE_SETTINGS_UNAVAILABLE.background.options).toEqual([]);
		const labels = CREATIVE_LANE_SETTINGS_UNAVAILABLE.hook.options.map(
			(o) => o.label,
		);
		expect(labels).not.toContain("Penat Kejar Promo");
		expect(labels).not.toContain("Nangis Mak-Mak");
		expect(optionLabel([], "AUTO")).toBe("AUTO");
	});

	it("F-05: generate body carries startAsset from prepared package (not package id alone)", () => {
		const pkg = fakePkg();
		const start = packageSlotResolvedAsset(pkg, "start_frame");
		expect(start?.asset_id).toBe("ca_start_selected");

		const body = buildFacelessGenerateBody({
					prompt: pkg.prompt_text,
					productId: pkg.product_id,
					workspacePackage: pkg,
					startFrameAssetId: "ca_start_selected",
					model: "Omni Flash",
					durationSeconds: 6,
					sceneMode: "SINGLE",
				});

				// Internal transport only — not operator product mode chrome
				expect(body.mode).toBe("F2V");
				expect(body.aspect).toBe("9:16");
				expect(body.aspectRatio).toBeUndefined();
				expect(body.prompt).toContain("Faceless clip");
				expect(body.product_id).toBe("prod-1");
				expect(body.model).toBe("Omni Flash");
				expect(body.duration_s).toBe(6);
				expect(body.generation_mode).toBe("SINGLE");

				const startAsset = body.startAsset as Record<string, unknown>;
				expect(startAsset).toBeTruthy();
				expect(startAsset.assetId).toBe("ca_start_selected");
				expect(startAsset.downloadUrl).toBe("https://cdn.example.com/start.png");
				// Must not rely only on package id for frame transport
				expect(body.workspace_execution_package_id).toBe("wep_test");
				expect(startAsset.assetId).not.toBe(body.workspace_execution_package_id);
			});

			it("product surface: EXTEND carries total plan + first-block 8s duration", () => {
				const pkg = fakePkg();
				const body = buildFacelessGenerateBody({
					prompt: pkg.prompt_text,
					workspacePackage: pkg,
					model: "Veo 3.1 - Lite",
					sceneMode: "EXTEND",
					extendTotalSeconds: 16,
					durationSeconds: 8,
				});
				expect(body.generation_mode).toBe("EXTEND");
				expect(body.requested_total_duration_seconds).toBe(16);
				expect(body.duration_s).toBe(8);
				expect(body.model).toBe("Veo 3.1 - Lite");
			});

			it("requires model + extend total in prepare blockers", () => {
				expect(
					facelessPrepareBlockers({
						productId: "p1",
						startFrameAssetId: "a1",
						model: "",
						sceneMode: "SINGLE",
					}).some((b) => /model/i.test(b)),
				).toBe(true);
				expect(
					facelessPrepareBlockers({
						productId: "p1",
						startFrameAssetId: "a1",
						model: "Veo 3.1 - Lite",
						sceneMode: "EXTEND",
						extendTotalSeconds: null,
					}).some((b) => /extend/i.test(b)),
				).toBe(true);
				expect(
					facelessPrepareBlockers({
						productId: "p1",
						startFrameAssetId: "a1",
						model: "Omni Flash",
						sceneMode: "SINGLE",
					}),
				).toEqual([]);
			});

	it("F-05: live mediaId is listed in image_media_ids for start_generate path", () => {
		const uuid = "12345678-1234-1234-1234-123456789abc";
		const pkg = fakePkg({
			asset_slots: [
				{
					slot_key: "start_frame",
					required: true,
					default_source: "CREATIVE_LIBRARY",
					allowed_sources: ["CREATIVE_LIBRARY"],
					resolved_asset: {
						asset_id: "ca_live",
						asset_fingerprint: "fp",
						slot_key: "start_frame",
						asset_source: "MEDIA_ID",
						label: "Live",
						file_name: "live.png",
						preview_url: "",
						download_url: "",
						media_id: uuid,
					},
				},
			],
		});
		const body = buildFacelessGenerateBody({
			prompt: pkg.prompt_text,
			workspacePackage: pkg,
		});
		expect(body.image_media_ids).toEqual([uuid]);
		expect((body.startAsset as { mediaId: string }).mediaId).toBe(uuid);
	});

	it("F-05: fails closed when no start frame transport exists", () => {
		expect(() =>
			buildFacelessGenerateBody({
				prompt: "x",
				workspacePackage: fakePkg({ asset_slots: [], resolved_assets: [] }),
				startFrameAssetId: null,
			}),
		).toThrow(/start frame/i);
	});
});
