/**
 * Faceless helpers — product-first Hybrid parity (no avatar).
 */
import { describe, expect, it } from "vitest";
import {
	buildFacelessGenerateBody,
	FACELESS_CHARACTER_PRESENCE,
	FACELESS_SOURCE_MODE,
	FACELESS_TRANSPORT_MODE,
	FACELESS_VISUAL_LAW,
	facelessPrepareBlockers,
	packageSlotResolvedAsset,
	resolvedAssetToGenerateAsset,
} from "./facelessLane";
import type { WorkspaceExecutionPackage } from "../types";

describe("facelessLane product-first", () => {
	it("defaults internal source mode to HYBRID product-anchor", () => {
		expect(FACELESS_SOURCE_MODE).toBe("HYBRID");
		expect(FACELESS_TRANSPORT_MODE).toBe("F2V");
		expect(FACELESS_CHARACTER_PRESENCE).toBe("FACELESS");
	});

	it("visual law forbids face / AI presenter", () => {
		expect(FACELESS_VISUAL_LAW).toMatch(/no visible human face/i);
		expect(FACELESS_VISUAL_LAW).toMatch(/hands/i);
		expect(FACELESS_VISUAL_LAW).not.toMatch(/F2V|FRAMES/i);
	});

	it("product-only prepare needs product + model + duration (no start frame)", () => {
		expect(
			facelessPrepareBlockers({
				productId: "p1",
				model: "Veo 3.1 - Lite",
				sceneMode: "SINGLE",
				durationSeconds: 8,
			}),
		).toEqual([]);
		expect(
			facelessPrepareBlockers({
				productId: "",
				model: "Veo 3.1 - Lite",
				sceneMode: "SINGLE",
				durationSeconds: 8,
			}).some((x) => /product/i.test(x)),
		).toBe(true);
		expect(
			facelessPrepareBlockers({
				productId: "p1",
				model: "",
				sceneMode: "SINGLE",
				durationSeconds: 8,
			}).some((x) => /model/i.test(x)),
		).toBe(true);
	});

	it("EXTEND requires authorized total duration", () => {
		expect(
			facelessPrepareBlockers({
				productId: "p1",
				model: "Veo 3.1 - Lite",
				sceneMode: "EXTEND",
			}).some((x) => /extend|total/i.test(x)),
		).toBe(true);
		expect(
			facelessPrepareBlockers({
				productId: "p1",
				model: "Veo 3.1 - Lite",
				sceneMode: "EXTEND",
				extendTotalSeconds: 24,
			}),
		).toEqual([]);
	});

	it("advanced override requires start frame only when enabled", () => {
		expect(
			facelessPrepareBlockers({
				productId: "p1",
				model: "Veo 3.1 - Lite",
				sceneMode: "SINGLE",
				durationSeconds: 8,
				referenceOverride: true,
				startFrameAssetId: null,
			}).some((x) => /Advanced|start-frame/i.test(x)),
		).toBe(true);
	});

	it("buildFacelessGenerateBody carries model + duration and package startAsset", () => {
		const pkg = {
			workspace_execution_package_id: "wep_1",
			prompt_fingerprint: "fp_1",
			prompt_text: "hands hold product",
			product_id: "p1",
			aspect_ratio: "9:16",
			asset_slots: [
				{
					slot_key: "start_frame",
					resolved_asset: {
						asset_id: "a_start",
						media_id: "m_start",
						file_name: "product.png",
						label: "product",
						download_url: "https://x/product.png",
						local_file_path: null,
					},
				},
			],
		} as unknown as WorkspaceExecutionPackage;

		const body = buildFacelessGenerateBody({
			prompt: pkg.prompt_text!,
			productId: "p1",
			workspacePackage: pkg,
			model: "Omni Flash",
			durationSeconds: 6,
			sceneMode: "SINGLE",
		});

		expect(body.mode).toBe("F2V");
		expect(body.model).toBe("Omni Flash");
		expect(body.duration_s).toBe(6);
		expect(body.generation_mode).toBe("SINGLE");
		expect((body.startAsset as { assetId: string }).assetId).toBe("a_start");
		expect(body.image_media_ids).toEqual(["m_start"]);
		expect(body.workspace_execution_package_id).toBe("wep_1");
	});

	it("EXTEND cannot fall back to a base one-door submission", () => {
		const pkg = {
			prompt_text: "hands",
			asset_slots: [
				{
					slot_key: "start_frame",
					resolved_asset: {
						asset_id: "a1",
						media_id: "m1",
						file_name: "p.png",
					},
				},
			],
		} as unknown as WorkspaceExecutionPackage;
		expect(() =>
			buildFacelessGenerateBody({
				prompt: "hands",
				workspacePackage: pkg,
				model: "Veo 3.1 - Lite",
				durationSeconds: 8,
				sceneMode: "EXTEND",
				extendTotalSeconds: 24,
			}),
		).toThrow(/durable video-job/i);
	});

	it("packageSlotResolvedAsset prefers asset_slots", () => {
		const pkg = {
			asset_slots: [
				{
					slot_key: "start_frame",
					resolved_asset: { asset_id: "from_slot" },
				},
			],
			resolved_assets: [{ slot_key: "start_frame", asset_id: "from_resolved" }],
		} as unknown as WorkspaceExecutionPackage;
		expect(packageSlotResolvedAsset(pkg, "start_frame")?.asset_id).toBe(
			"from_slot",
		);
		expect(
			resolvedAssetToGenerateAsset(packageSlotResolvedAsset(pkg, "start_frame"))
				?.assetId,
		).toBe("from_slot");
	});
});
