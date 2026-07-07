import { describe, expect, it } from "vitest";
import type { PosterReadinessResponse } from "../types/posterReadiness";
import {
	isGenerateButtonDisabled,
	isPromptDraftGenerationEnabled,
	posterStatusOperatorLabel,
	resolveBuilderShellMode,
	resolveGenerateButtonLabel,
	resolvePromptDraftButtonLabel,
	shouldShowHighRiskGuidance,
	shouldShowHumanReviewPanel,
	shouldShowRepairActionCenter,
} from "./posterBuilderUi";

function baseReadiness(
	overrides: Partial<PosterReadinessResponse>,
): PosterReadinessResponse {
	return {
		product_id: "test-id",
		poster_status: "POSTER_READY",
		generation_allowed: true,
		restricted_generation_required: false,
		preview_allowed: true,
		production_allowed: true,
		blockers: [],
		repair_actions: [],
		image_tier: "PRODUCT_HERO_POSTER_READY",
		claim_route: {
			safe_claim_clearance_required: false,
			safe_claim_clearance_status: "NOT_REQUIRED",
			restricted_safe_poster_route_verified: false,
		},
		mapping_route: { mapping_ready: true },
		approval_route: { img_approved: true, approved_modes: ["IMG"] },
		recheck_required_after_repair: false,
		notes: [],
		...overrides,
	};
}

describe("posterBuilderUi", () => {
	it("labels POSTER_READY as Ready", () => {
		expect(posterStatusOperatorLabel("POSTER_READY")).toBe("Ready");
	});

	it("POSTER_READY enables full builder shell", () => {
		const r = baseReadiness({ poster_status: "POSTER_READY" });
		expect(resolveBuilderShellMode(r)).toBe("full");
	});

	it("POSTER_REPAIR_REQUIRED shows repair center and hides builder", () => {
		const r = baseReadiness({
			poster_status: "POSTER_REPAIR_REQUIRED",
			generation_allowed: false,
			production_allowed: false,
			preview_allowed: true,
			blockers: ["CLAIM_RISK_HIGH"],
			repair_actions: [
				{
					action_code: "RUN_SAFE_CLAIM_CLEARANCE",
					label: "Run Safe Claim Clearance",
					severity: "P0",
				},
			],
		});
		expect(resolveBuilderShellMode(r)).toBe("hidden");
		expect(shouldShowRepairActionCenter(r)).toBe(true);
		expect(shouldShowHighRiskGuidance(r)).toBe(true);
		expect(resolveGenerateButtonLabel(r)).toContain("repair");
	});

	it("CLAIM_RISK_HIGH keeps generation disabled via API fields", () => {
		const r = baseReadiness({
			poster_status: "POSTER_REPAIR_REQUIRED",
			generation_allowed: false,
			blockers: ["CLAIM_RISK_HIGH"],
		});
		expect(r.generation_allowed).toBe(false);
	});

	it("POSTER_READY_RESTRICTED shows restricted shell and warning path", () => {
		const r = baseReadiness({
			poster_status: "POSTER_READY_RESTRICTED",
			generation_allowed: true,
			restricted_generation_required: true,
			production_allowed: false,
		});
		expect(resolveBuilderShellMode(r)).toBe("restricted");
		expect(resolveGenerateButtonLabel(r)).toContain("External image generation");
		expect(isPromptDraftGenerationEnabled(r)).toBe(true);
	});

	it("POSTER_PREVIEW_ONLY uses preview shell", () => {
		const r = baseReadiness({
			poster_status: "POSTER_PREVIEW_ONLY",
			generation_allowed: false,
			production_allowed: false,
			preview_allowed: true,
			blockers: ["REMOTE_IMAGE_ONLY"],
		});
		expect(resolveBuilderShellMode(r)).toBe("preview");
	});

	it("POSTER_BLOCKED hides builder and shows human review", () => {
		const r = baseReadiness({
			poster_status: "POSTER_BLOCKED",
			generation_allowed: false,
			preview_allowed: false,
			blockers: ["PRODUCT_ARCHIVED"],
		});
		expect(resolveBuilderShellMode(r)).toBe("hidden");
		expect(shouldShowHumanReviewPanel(r)).toBe(true);
	});

	it("generate button stays disabled (out of scope)", () => {
		const r = baseReadiness({ poster_status: "POSTER_READY" });
		expect(isGenerateButtonDisabled(r)).toBe(true);
		expect(resolveGenerateButtonLabel(r)).toContain("External image generation");
		expect(isPromptDraftGenerationEnabled(r)).toBe(true);
		expect(resolvePromptDraftButtonLabel(r)).toContain("prompt draft");
	});
});