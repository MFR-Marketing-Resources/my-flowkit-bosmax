/**
 * Exact-policy contract: scene-only Flow + composeExactFromPlate final only.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/imgFactory", () => ({
	startImgGeneration: vi.fn(),
	pollImgGenerationJob: vi.fn(),
}));

vi.mock("../api/exactProductOutput", () => ({
	fetchExactProductPolicy: vi.fn(),
	buildExactSceneOnlyPrompt: vi.fn(),
	composeExactFromPlate: vi.fn(),
	validateExactProduct: vi.fn(),
}));

import { pollImgGenerationJob, startImgGeneration } from "../api/imgFactory";
import {
	buildExactSceneOnlyPrompt,
	composeExactFromPlate,
	fetchExactProductPolicy,
} from "../api/exactProductOutput";

describe("PosterBuilder exact final output", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		vi.mocked(fetchExactProductPolicy).mockResolvedValue({
			product_id: "6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
			exact_product_composite_required: true,
			canonical_valid: true,
			send_product_reference_to_flow: false,
			scene_only_prompt_block: "EXACT",
		});
		vi.mocked(buildExactSceneOnlyPrompt).mockResolvedValue({
			product_id: "6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
			exact_product_composite_required: true,
			prompt: "scene only EXACT_PRODUCT_COMPOSITE_REQUIRED",
			send_product_reference_to_flow: false,
		});
		vi.mocked(startImgGeneration).mockResolvedValue({ job_id: "job-1" });
		vi.mocked(pollImgGenerationJob).mockResolvedValue({
			status: "DONE",
			media_id: "plate-raw-1",
			url: "/api/flow/retrieved/plate-raw-1",
		});
		vi.mocked(composeExactFromPlate).mockResolvedValue({
			ok: true,
			product_id: "6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
			media_id: "exact-final-abc",
			url: "/api/flow/retrieved/exact-final-abc",
			output_sha256: "a".repeat(64),
			size_mb: 0.5,
			status: "DONE",
			truth_status: "PRODUCT_TRUTH_PRESERVED_EXACT_COMPOSITE",
			preview_sha_equals_saved_sha: true,
			lineage: {
				raw_plate_media_id: "plate-raw-1",
				raw_plate_approvable: false,
				final_media_id: "exact-final-abc",
			},
		});
	});

	it("exact path: no product refs, compose-from-plate final only", async () => {
		const productId = "6483d624-a03d-4933-9bba-6ca2e5f7b6fd";
		const policy = await fetchExactProductPolicy(productId);
		expect(policy.exact_product_composite_required).toBe(true);
		expect(policy.send_product_reference_to_flow).toBe(false);

		const scene = await buildExactSceneOnlyPrompt(productId, "poster prompt");
		const { job_id } = await startImgGeneration({
			prompt: scene.prompt,
			aspect: "9:16",
			count: 1,
		});
		expect(startImgGeneration).toHaveBeenCalledWith(
			expect.not.objectContaining({
				refs: expect.anything(),
			}),
		);
		const job = await pollImgGenerationJob(job_id);
		const finalOut = await composeExactFromPlate({
			product_id: productId,
			background_media_id: job.media_id!,
			lane: "poster",
			job_id,
		});
		expect(finalOut.media_id).toBe("exact-final-abc");
		expect(finalOut.lineage.raw_plate_approvable).toBe(false);
		expect(finalOut.url).toContain("exact-final");
		expect(composeExactFromPlate).toHaveBeenCalledWith({
			product_id: productId,
			background_media_id: "plate-raw-1",
			lane: "poster",
			job_id: "job-1",
		});
	});
});
