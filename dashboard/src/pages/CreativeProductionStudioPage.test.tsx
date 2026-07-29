import "@testing-library/jest-dom/vitest";
import {
	act,
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchCohortAuthority = vi.fn();
const fetchGovernedPoolAuthority = vi.fn();
const listProductionPlans = vi.fn();
const fetchProductionPlan = vi.fn();
const listExecutionLanes = vi.fn();
const createProductionPlan = vi.fn();
const preflightProductionPlan = vi.fn();
const materializeContentMatrix = vi.fn();
const compileProductionPlan = vi.fn();
const approveProductionPlan = vi.fn();
const assignProductionWaves = vi.fn();
const dryRunProductionPlan = vi.fn();
const startProductionPlan = vi.fn();
const controlProductionPlan = vi.fn();
const reconcileAttempt = vi.fn();
const retryAttempt = vi.fn();
const decideItemQa = vi.fn();

vi.mock("../api/creativeProduction", () => ({
	fetchCohortAuthority: (...args: unknown[]) => fetchCohortAuthority(...args),
	fetchGovernedPoolAuthority: (...args: unknown[]) =>
		fetchGovernedPoolAuthority(...args),
	listProductionPlans: (...args: unknown[]) => listProductionPlans(...args),
	fetchProductionPlan: (...args: unknown[]) => fetchProductionPlan(...args),
	listExecutionLanes: (...args: unknown[]) => listExecutionLanes(...args),
	createProductionPlan: (...args: unknown[]) => createProductionPlan(...args),
	preflightProductionPlan: (...args: unknown[]) =>
		preflightProductionPlan(...args),
	materializeContentMatrix: (...args: unknown[]) =>
		materializeContentMatrix(...args),
	compileProductionPlan: (...args: unknown[]) => compileProductionPlan(...args),
	approveProductionPlan: (...args: unknown[]) => approveProductionPlan(...args),
	assignProductionWaves: (...args: unknown[]) => assignProductionWaves(...args),
	dryRunProductionPlan: (...args: unknown[]) => dryRunProductionPlan(...args),
	startProductionPlan: (...args: unknown[]) => startProductionPlan(...args),
	controlProductionPlan: (...args: unknown[]) => controlProductionPlan(...args),
	reconcileAttempt: (...args: unknown[]) => reconcileAttempt(...args),
	retryAttempt: (...args: unknown[]) => retryAttempt(...args),
	decideItemQa: (...args: unknown[]) => decideItemQa(...args),
	P6_LIVE_CONFIRMATION: "AUTHORIZE_P6_LIVE_CREDIT_SPEND",
}));

import CreativeProductionStudioPage from "./CreativeProductionStudioPage";

const COHORT = {
	cohort_count: 438,
	cohort_sha256:
		"15b7e2aff4ede06b1a28805b111f9993b2208040e40bcee76693abc2a6ddbe7f",
	product_ids: ["product-1"],
	products: [
		{
			product_id: "product-1",
			product_name: "P6 Product",
			product_type_group: "lip_color",
			scene_strategy_id: "LIP_COLOR",
		},
	],
	matches_frozen_authority: true,
	p6_not_started: false,
};

const PLAN = {
	plan_id: "p6plan-ui",
	request_id: "request-ui",
	created_by: "p6-production-operator",
	name: "Rendered P6 plan",
	campaign_key: "",
	product_scope: ["product-1"],
	p58_cohort_sha256: COHORT.cohort_sha256,
	p58_cohort_count: 438,
	target_video_count: 2,
	target_image_count: 0,
	target_poster_count: 0,
	operating_window_hours: 12,
	allocation_strategy: "ROUND_ROBIN",
	variation_strategy: "SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS",
	logical_mode: "T2V",
	model_keys: ["Veo 3.1 - Lite"],
	duration_seconds: [8],
	pool_snapshot: {},
	execution_policy: {},
	capacity_snapshot: {
		requested: { VIDEO: 2, IMAGE: 0, POSTER: 0 },
		safe_capacity: { VIDEO: 1, IMAGE: 0, POSTER: 0 },
	},
	compile_snapshot: {},
	blockers: [
		{
			code: "UNIQUE_CAPACITY_SHORTFALL",
			media_type: "VIDEO",
			shortfall: 1,
		},
	],
	status: "PREFLIGHT_BLOCKED",
	control_action: "NONE",
	control_version: 0,
	approved_by: null,
	approved_at: null,
	created_at: "2026-07-29T00:00:00Z",
	updated_at: "2026-07-29T00:00:00Z",
};

const DETAIL = {
	plan: PLAN,
	waves: [],
	batches: [],
	items: [
		{
			item_id: "p6item-ui",
			plan_id: PLAN.plan_id,
			item_ordinal: 0,
			product_id: "product-1",
			media_type: "VIDEO",
			logical_mode: "T2V",
			creative_dimensions: {
				angle: "proof",
				hook: "problem",
				layout_id: "",
			},
			creative_dna_sha256: "a".repeat(64),
			controlled_reuse_reason: null,
			prompt_fingerprint: null,
			workspace_generation_package_id: null,
			prompt_package: {},
			status: "PLANNED",
			output_media_id: null,
			replacement_for_item_id: null,
			replaced_by_item_id: null,
		},
	],
	attempts: [],
	qa: [],
	audit_events: [],
	progress: {
		total: 1,
		terminal: 0,
		percent: 0,
		by_status: { PLANNED: 1 },
	},
};

const LANES = {
	lanes: [
		{
			lane_id: "google-flow-video-primary",
			provider: "GOOGLE_FLOW",
			engine: "ADR_007_API_FIRST",
			eligible_media_types: ["VIDEO"],
			verified_max_inflight: 1,
			min_interval_seconds: 83,
			cooldown_seconds: 300,
			next_available_at: null,
			completed_job_count: 0,
			health_status: "UNKNOWN",
			enabled: true,
			runtime_proof_status: "VERIFIED",
			evidence_reference: "ADR-007",
			active_lease_count: 0,
		},
		{
			lane_id: "google-flow-image-primary",
			provider: "GOOGLE_FLOW",
			engine: "IMAGE_API_FIRST",
			eligible_media_types: ["IMAGE", "POSTER"],
			verified_max_inflight: 1,
			min_interval_seconds: 83,
			cooldown_seconds: 300,
			next_available_at: null,
			completed_job_count: 0,
			health_status: "UNKNOWN",
			enabled: false,
			runtime_proof_status: "UNVERIFIED",
			evidence_reference: "proof required",
			active_lease_count: 0,
		},
	],
};

function prime(detail = DETAIL) {
	fetchCohortAuthority.mockResolvedValue(COHORT);
	fetchGovernedPoolAuthority.mockResolvedValue({
		product_ids: ["product-1"],
		logical_mode: "T2V",
		products: [],
		copy_sets: [],
		poster_copy_sets: [],
		avatar_profiles: [],
		product_reference_assets: [],
		finished_frame_assets: [],
		character_assets: [],
		scene_assets: [],
		style_assets: [],
		poster_recipes: [],
		blockers: [],
		copy_reuse_cap: 15,
		near_duplicate_threshold: 0.8,
		credit_spend: 0,
	});
	listProductionPlans.mockResolvedValue({ plans: [detail.plan] });
	fetchProductionPlan.mockResolvedValue(detail);
	listExecutionLanes.mockResolvedValue(LANES);
	preflightProductionPlan.mockResolvedValue({
		plan_id: PLAN.plan_id,
		status: "PREFLIGHT_BLOCKED",
		requested: { VIDEO: 2, IMAGE: 0, POSTER: 0 },
		safe_capacity: { VIDEO: 1, IMAGE: 0, POSTER: 0 },
		pool_counts: {},
		quota_pressure: {},
		historical_exclusions: 0,
		blockers: PLAN.blockers,
		remediation: [],
		assumptions: {},
		snapshot_sha256: "snapshot",
	});
}

beforeEach(() => {
	vi.stubGlobal("crypto", {
		randomUUID: () => "00000000-0000-4000-8000-000000000001",
	});
	fetchGovernedPoolAuthority.mockResolvedValue({
		product_ids: ["product-1"],
		logical_mode: "T2V",
		products: [],
		copy_sets: [],
		poster_copy_sets: [],
		avatar_profiles: [],
		product_reference_assets: [],
		finished_frame_assets: [],
		character_assets: [],
		scene_assets: [],
		style_assets: [],
		poster_recipes: [],
		blockers: [],
		copy_reuse_cap: 15,
		near_duplicate_threshold: 0.8,
		credit_spend: 0,
	});
});

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
	vi.unstubAllGlobals();
});

describe("P6 Production Studio rendered contract", () => {
	it("renders frozen cohort, zero-credit boundary, truthful states and lanes", async () => {
		prime();
		render(<CreativeProductionStudioPage />);
		expect(await screen.findByTestId("p6-cohort-authority")).toHaveTextContent(
			"COHORT_AUTHORITY_VERIFIED",
		);
		expect(screen.getByTestId("p6-zero-credit-boundary")).toHaveTextContent(
			"0 media credits",
		);
		expect(await screen.findByTestId("p6-plan-status")).toHaveTextContent(
			"PREFLIGHT_BLOCKED",
		);
		expect(screen.getByTestId("p6-content-matrix")).toHaveTextContent(
			"PLANNED",
		);
		expect(
			screen.getByTestId("p6-lane-google-flow-video-primary"),
		).toHaveTextContent("Max inflight");
		expect(
			screen.getByTestId("p6-lane-google-flow-image-primary"),
		).toHaveTextContent("UNVERIFIED");
	});

	it("renders exact capacity shortfall rather than fabricating output", async () => {
		prime();
		render(<CreativeProductionStudioPage />);
		const report = await screen.findByTestId("p6-capacity-report");
		expect(report).toHaveTextContent("Safe unique");
		expect(report).toHaveTextContent("UNIQUE_CAPACITY_SHORTFALL");
		expect(report).toHaveTextContent('"shortfall":1');
	});

	it("wires the credit-free preflight action to the P6 API", async () => {
		prime();
		render(<CreativeProductionStudioPage />);
		await screen.findByTestId("p6-plan-status");
		await act(async () => {
			fireEvent.click(screen.getByTestId("p6-action-preflight"));
		});
		await waitFor(() =>
			expect(preflightProductionPlan).toHaveBeenCalledWith(
				"p6plan-ui",
				"p6-production-operator",
			),
		);
		expect(startProductionPlan).not.toHaveBeenCalled();
	});

	it("keeps live dispatch disabled until scheduled and exact phrase are both present", async () => {
		prime();
		render(<CreativeProductionStudioPage />);
		await screen.findByTestId("p6-plan-status");
		const liveButton = screen.getByTestId("p6-action-live-start");
		expect(liveButton).toBeDisabled();
		fireEvent.change(screen.getByTestId("p6-live-confirmation"), {
			target: { value: "AUTHORIZE_P6_LIVE_CREDIT_SPEND" },
		});
		expect(liveButton).toBeDisabled();
		expect(startProductionPlan).not.toHaveBeenCalled();
	});

	it("renders a coherent empty plan state", async () => {
		fetchCohortAuthority.mockResolvedValue(COHORT);
		listProductionPlans.mockResolvedValue({ plans: [] });
		listExecutionLanes.mockResolvedValue(LANES);
		render(<CreativeProductionStudioPage />);
		expect(await screen.findByTestId("p6-empty-plans")).toBeInTheDocument();
		expect(
			screen.getByText(/Create or select a durable P6/),
		).toBeInTheDocument();
	});
});
