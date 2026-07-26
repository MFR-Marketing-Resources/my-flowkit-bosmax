/**
 * Fail-closed exact-policy gate + lane contracts.
 * Policy endpoint failure ⇒ zero startImgGeneration calls.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const startImgGeneration = vi.fn();
const pollImgGenerationJob = vi.fn();
const fetchExactProductPolicy = vi.fn();
const buildExactSceneOnlyPrompt = vi.fn();
const composeExactFromPlate = vi.fn();

vi.mock("../api/imgFactory", () => ({
	startImgGeneration: (...args: unknown[]) => startImgGeneration(...args),
	pollImgGenerationJob: (...args: unknown[]) => pollImgGenerationJob(...args),
}));

vi.mock("../api/exactProductOutput", async () => {
	const actual = await vi.importActual<
		typeof import("../api/exactProductOutput")
	>("../api/exactProductOutput");
	return {
		...actual,
		fetchExactProductPolicy: (...args: unknown[]) =>
			fetchExactProductPolicy(...args),
		buildExactSceneOnlyPrompt: (...args: unknown[]) =>
			buildExactSceneOnlyPrompt(...args),
		composeExactFromPlate: (...args: unknown[]) =>
			composeExactFromPlate(...args),
	};
});

import {
	EXACT_PRODUCT_POLICY_UNAVAILABLE,
	resolveExactGenerationGate,
} from "../api/exactProductOutput";

const MWCB = "6483d624-a03d-4933-9bba-6ca2e5f7b6fd";

/** Mirrors Poster / Fastlane / Cockpit generate gate before startImgGeneration. */
async function laneGenerateWithGate(opts: {
	productId: string | null;
	prompt: string;
}): Promise<{ started: boolean; error?: string; exact?: boolean }> {
	const gate = await resolveExactGenerationGate(
		opts.productId,
		fetchExactProductPolicy as never,
	);
	if (gate.mode === "blocked") {
		return { started: false, error: gate.message };
	}
	const exact = gate.mode === "exact";
	let prompt = opts.prompt;
	if (exact && opts.productId) {
		const scene = await buildExactSceneOnlyPrompt(opts.productId, prompt);
		prompt = scene.prompt;
	}
	await startImgGeneration({
		prompt,
		refs: exact ? undefined : { subjectAsset: { mediaId: "prod" } },
	});
	if (exact && opts.productId) {
		const job = await pollImgGenerationJob("job-1");
		await composeExactFromPlate({
			product_id: opts.productId,
			background_media_id: job.media_id,
			lane: "studio",
		});
	}
	return { started: true, exact };
}

describe("resolveExactGenerationGate fail-closed", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		startImgGeneration.mockResolvedValue({ job_id: "job-1" });
		pollImgGenerationJob.mockResolvedValue({
			status: "DONE",
			media_id: "plate-1",
		});
		buildExactSceneOnlyPrompt.mockResolvedValue({
			product_id: MWCB,
			exact_product_composite_required: true,
			prompt: "scene EXACT",
			send_product_reference_to_flow: false,
		});
		composeExactFromPlate.mockResolvedValue({
			ok: true,
			media_id: "final-uuid",
			url: "/api/flow/retrieved/final-uuid",
		});
	});

	it("blocks on policy fetch failure and never starts IMG", async () => {
		fetchExactProductPolicy.mockRejectedValue(new Error("network down"));
		const r = await laneGenerateWithGate({
			productId: MWCB,
			prompt: "studio",
		});
		expect(r.started).toBe(false);
		expect(r.error).toContain(EXACT_PRODUCT_POLICY_UNAVAILABLE);
		expect(startImgGeneration).not.toHaveBeenCalled();
	});

	it("Poster Builder contract: policy failure → 0 startImgGeneration", async () => {
		fetchExactProductPolicy.mockRejectedValue(new Error("500"));
		const r = await laneGenerateWithGate({
			productId: MWCB,
			prompt: "poster",
		});
		expect(r.started).toBe(false);
		expect(startImgGeneration).toHaveBeenCalledTimes(0);
	});

	it("IMG Fastlane contract: policy failure → 0 startImgGeneration", async () => {
		fetchExactProductPolicy.mockRejectedValue(new Error("timeout"));
		const r = await laneGenerateWithGate({
			productId: MWCB,
			prompt: "fastlane",
		});
		expect(r.started).toBe(false);
		expect(startImgGeneration).toHaveBeenCalledTimes(0);
	});

	it("IMG Cockpit contract: policy failure → 0 startImgGeneration", async () => {
		fetchExactProductPolicy.mockRejectedValue(new Error("ECONNREFUSED"));
		const r = await laneGenerateWithGate({
			productId: MWCB,
			prompt: "cockpit",
		});
		expect(r.started).toBe(false);
		expect(startImgGeneration).toHaveBeenCalledTimes(0);
	});

	it("explicit non-exact may use standard path with refs", async () => {
		fetchExactProductPolicy.mockResolvedValue({
			product_id: "other",
			exact_product_composite_required: false,
			canonical_valid: true,
		});
		const r = await laneGenerateWithGate({
			productId: "other",
			prompt: "serum",
		});
		expect(r.started).toBe(true);
		expect(r.exact).toBe(false);
		expect(startImgGeneration).toHaveBeenCalledTimes(1);
		expect(startImgGeneration.mock.calls[0][0].refs).toBeTruthy();
	});

	it("exact path: scene-only + no product refs + compose", async () => {
		fetchExactProductPolicy.mockResolvedValue({
			product_id: MWCB,
			exact_product_composite_required: true,
			canonical_valid: true,
		});
		const r = await laneGenerateWithGate({
			productId: MWCB,
			prompt: "studio hero",
		});
		expect(r.started).toBe(true);
		expect(r.exact).toBe(true);
		expect(startImgGeneration).toHaveBeenCalledWith(
			expect.objectContaining({
				prompt: "scene EXACT",
				refs: undefined,
			}),
		);
		expect(composeExactFromPlate).toHaveBeenCalled();
	});

	it("canonical invalid blocks before IMG", async () => {
		fetchExactProductPolicy.mockResolvedValue({
			product_id: MWCB,
			exact_product_composite_required: true,
			canonical_valid: false,
			error: { code: "CANONICAL_PRODUCT_SOURCE_INVALID", message: "hash" },
		});
		const r = await laneGenerateWithGate({
			productId: MWCB,
			prompt: "x",
		});
		expect(r.started).toBe(false);
		expect(startImgGeneration).not.toHaveBeenCalled();
	});

	it("direct gate unit: fetch throw → blocked code", async () => {
		const gate = await resolveExactGenerationGate(MWCB, async () => {
			throw new Error("boom");
		});
		expect(gate.mode).toBe("blocked");
		if (gate.mode === "blocked") {
			expect(gate.code).toBe(EXACT_PRODUCT_POLICY_UNAVAILABLE);
		}
	});
});
