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
import type { GovernedPoolAuthority } from "../api/creativeProduction";

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
const fetchVideoModels = vi.fn();

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

vi.mock("../api/productionQueue", () => ({
	fetchVideoModels: (...args: unknown[]) => fetchVideoModels(...args),
}));

import CreativeProductionStudioPage from "./CreativeProductionStudioPage";

const COHORT = {
	cohort_count: 438,
	cohort_sha256:
		"15b7e2aff4ede06b1a28805b111f9993b2208040e40bcee76693abc2a6ddbe7f",
	product_ids: ["product-1", "product-2"],
	products: [
		{
			product_id: "product-1",
			product_name: "P6 Product",
			product_type_group: "lip_color",
			scene_strategy_id: "LIP_COLOR",
			image_url: "https://example.com/product-1.jpg",
			image_readiness_status: "IMAGE_CACHE_READY",
			readiness_status: "PRODUCTION_READY",
		},
		{
			product_id: "product-2",
			product_name: "P6 Product Two",
			product_type_group: "lip_color",
			scene_strategy_id: "LIP_COLOR",
			image_url: "https://example.com/product-2.jpg",
			image_readiness_status: "IMAGE_CACHE_READY",
			readiness_status: "PRODUCTION_READY",
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
				generation_mode: "SINGLE",
				duration_seconds: "8",
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
	live_execution_certified: false,
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
	fetchVideoModels.mockResolvedValue({
		default: "veo_3_1_lite",
		models: [
			{
				key: "veo_3_1_lite",
				ui_label: "Veo 3.1 - Lite",
				default_duration_s: 8,
				allowed_durations_s: [4, 6, 8],
				extend_block_duration_s: 8,
				extend_totals_s: [16, 24],
			},
			{
				key: "omni_flash",
				ui_label: "Omni Flash",
				default_duration_s: 10,
				allowed_durations_s: [4, 6, 8, 10],
				extend_block_duration_s: null,
				extend_totals_s: [],
			},
		],
	});
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
			"PRODUCT AUTHORITY READY",
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

	it("creates an explicit per-product allocation with a governed Extend choice", async () => {
		prime();
		createProductionPlan.mockResolvedValue(PLAN);
		render(<CreativeProductionStudioPage />);
		await screen.findByTestId("p6-plan-status");
		await waitFor(() =>
			expect(fetchGovernedPoolAuthority).toHaveBeenCalledTimes(1),
		);
		fireEvent.change(screen.getByLabelText("Video quantity for P6 Product"), {
			target: { value: "3" },
		});
		expect(fetchGovernedPoolAuthority).toHaveBeenCalledTimes(1);
		fireEvent.change(screen.getByLabelText("Governed video duration"), {
			target: { value: "16" },
		});
		expect(screen.getByTestId("p6-orchestration-summary")).toHaveTextContent(
			"Extend · 2 continuous 8-second segments",
		);
		await waitFor(() =>
			expect(screen.getByTestId("p6-create-plan")).toBeEnabled(),
		);
		await act(async () => {
			fireEvent.click(screen.getByTestId("p6-create-plan"));
		});
		await waitFor(() => expect(createProductionPlan).toHaveBeenCalledTimes(1));
		expect(createProductionPlan.mock.calls[0][0]).toMatchObject({
			product_ids: ["product-1"],
			product_video_allocations: [{ product_id: "product-1", video_count: 3 }],
			target_video_count: 3,
			model_keys: ["veo_3_1_lite"],
			duration_seconds: [16],
		});
	});

	it("ignores stale pool authority responses after the operator changes mode", async () => {
		prime();
		const readyAuthority: GovernedPoolAuthority = {
			product_ids: ["product-1"],
			logical_mode: "F2V",
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
		};
		let resolveT2v: ((authority: typeof readyAuthority) => void) | undefined;
		let resolveF2v: ((authority: typeof readyAuthority) => void) | undefined;
		fetchGovernedPoolAuthority.mockImplementation(
			(_productIds: string[], logicalMode: string) =>
				new Promise<typeof readyAuthority>((resolve) => {
					if (logicalMode === "F2V") resolveF2v = resolve;
					else resolveT2v = resolve;
				}),
		);
		render(<CreativeProductionStudioPage />);
		await screen.findByTestId("p6-plan-status");
		await waitFor(() =>
			expect(fetchGovernedPoolAuthority).toHaveBeenCalledWith(
				["product-1"],
				"T2V",
			),
		);
		fireEvent.change(screen.getByLabelText("Video logical mode"), {
			target: { value: "F2V" },
		});
		await waitFor(() =>
			expect(fetchGovernedPoolAuthority).toHaveBeenCalledWith(
				["product-1"],
				"F2V",
			),
		);
		await act(async () => {
			resolveF2v?.(readyAuthority);
		});
		await waitFor(() =>
			expect(screen.getByTestId("p6-create-plan")).toBeEnabled(),
		);
		await act(async () => {
			resolveT2v?.({
				...readyAuthority,
				logical_mode: "T2V",
				blockers: [
					{
						code: "APPROVED_PRODUCT_AVATAR_SELECTION_REQUIRED",
						product_id: "product-1",
					},
				],
			});
		});
		expect(screen.queryByTestId("p6-pool-authority-blockers")).toBeNull();
		expect(screen.getByTestId("p6-create-plan")).toBeEnabled();
	});

	it("keeps Omni 10 seconds single-shot and exposes no unproven Omni Extend total", async () => {
		prime();
		render(<CreativeProductionStudioPage />);
		await screen.findByTestId("p6-plan-status");
		fireEvent.change(screen.getByLabelText("Governed video model"), {
			target: { value: "omni_flash" },
		});
		const duration = screen.getByLabelText("Governed video duration");
		expect(duration).toHaveValue("10");
		expect(duration).toHaveTextContent("10s — Single");
		expect(duration).not.toHaveTextContent("20s");
		expect(screen.getByTestId("p6-orchestration-summary")).toHaveTextContent(
			"Single-shot",
		);
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

	it("reflects runtime certification and only enables a scheduled exact-phrase request", async () => {
		const scheduledDetail = {
			...DETAIL,
			plan: {
				...PLAN,
				status: "SCHEDULED",
				blockers: [],
			},
		};
		prime(scheduledDetail);
		listExecutionLanes.mockResolvedValue({
			...LANES,
			live_execution_certified: true,
		});
		render(<CreativeProductionStudioPage />);
		await screen.findByTestId("p6-plan-status");
		expect(screen.getByTestId("p6-live-certification-truth")).toHaveTextContent(
			"Runtime live-execution certification is present",
		);
		const liveButton = screen.getByTestId("p6-action-live-start");
		expect(liveButton).toBeDisabled();
		fireEvent.change(screen.getByTestId("p6-live-confirmation"), {
			target: { value: "AUTHORIZE_P6_LIVE_CREDIT_SPEND" },
		});
		expect(liveButton).toBeEnabled();
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

	it("renders the 6-step progressive stepper and context-sensitive primary CTA", async () => {
		prime();
		render(<CreativeProductionStudioPage />);
		await screen.findByTestId("p6-plan-status");
		expect(screen.getByText("Production Stepper & Next Action")).toBeInTheDocument();
		expect(screen.getByText("STEP 3 OF 6")).toBeInTheDocument();
		expect(screen.getByTestId("p6-primary-action")).toHaveTextContent("Run preflight inspection");
	});

	it("renders quantity increment and decrement controls in product picker", async () => {
		prime();
		render(<CreativeProductionStudioPage />);
		await screen.findByTestId("p6-plan-status");
		const selected = await screen.findByTestId("p6-selected-product");
		expect(selected).toBeInTheDocument();
		const decreaseBtn = screen.getByRole("button", {
			name: /Decrease quantity for/i,
		});
		const increaseBtn = screen.getByRole("button", {
			name: /Increase quantity for/i,
		});
		expect(decreaseBtn).toBeEnabled();
		fireEvent.click(decreaseBtn);
		expect(screen.getByLabelText(/Video quantity for/i)).toHaveValue(1);
		expect(decreaseBtn).toBeDisabled();
		fireEvent.click(increaseBtn);
		expect(screen.getByLabelText(/Video quantity for/i)).toHaveValue(2);
		expect(decreaseBtn).toBeEnabled();
	});

	it("detects draft vs active plan mismatch and surfaces warning", async () => {
		prime();
		render(<CreativeProductionStudioPage />);
		await screen.findByTestId("p6-plan-status");
		expect(screen.getByTestId("p6-plan-selector-bar")).toBeInTheDocument();
		fireEvent.click(screen.getByText(/product.*selected/i));
		fireEvent.click(screen.getAllByTestId("p6-product-option")[1]);
		expect(
			await screen.findByTestId("p6-draft-mismatch-warning"),
		).toBeInTheDocument();
		expect(screen.getByTestId("p6-primary-action")).toBeDisabled();
		expect(screen.getByTestId("p6-primary-action")).toHaveTextContent(
			"Form Mismatched",
		);
	});

	it("renders plain-language live gate disabled reasons", async () => {
		prime();
		render(<CreativeProductionStudioPage />);
		await screen.findByTestId("p6-plan-status");
		expect(screen.getByTestId("p6-live-disabled-reason")).toHaveTextContent(
			"Runtime live-execution certification is absent",
		);
	});
});

