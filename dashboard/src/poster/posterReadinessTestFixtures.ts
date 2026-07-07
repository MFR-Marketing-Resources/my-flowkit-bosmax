import type { PosterReadinessResponse } from "../types/posterReadiness";

/** Test-only fixture IDs from PR #231 audit — not used in production UI. */
export const POSTER_AUDIT_TARGET_PRODUCT_IDS = {
	bosmaxOil: "b460ffbd-7d9d-4f6b-a570-0e9b1056439a",
	bosmaxHerbs: "90349f8c-9e14-4efe-988e-76ec60ea31f4",
	minyakWarisan: "6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
} as const;

const base = (
	overrides: Partial<PosterReadinessResponse>,
): PosterReadinessResponse => ({
	product_id: "p1",
	product_display_name: "Test Product",
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
});

export const posterReadinessFixtures = {
	ready: () => base({ poster_status: "POSTER_READY" }),
	repairRequired: () =>
		base({
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
		}),
	blocked: () =>
		base({
			poster_status: "POSTER_BLOCKED",
			generation_allowed: false,
			preview_allowed: false,
			production_allowed: false,
			blockers: ["PRODUCT_ARCHIVED"],
		}),
	restricted: () =>
		base({
			poster_status: "POSTER_READY_RESTRICTED",
			generation_allowed: true,
			restricted_generation_required: true,
			production_allowed: false,
		}),
	previewOnly: () =>
		base({
			poster_status: "POSTER_PREVIEW_ONLY",
			generation_allowed: false,
			production_allowed: false,
			preview_allowed: true,
			blockers: ["REMOTE_IMAGE_ONLY"],
		}),
};