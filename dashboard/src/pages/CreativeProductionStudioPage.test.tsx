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
const fetchTreatmentAvailability = vi.fn();
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
	fetchTreatmentAvailability: (...args: unknown[]) =>
		fetchTreatmentAvailability(...args),
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

vi.mock("../components/CreativeSupplyFactoryPanel", () => ({
	default: () => <div data-testid="p7-supply-preserved">Creative supply</div>,
}));

import CreativeProductionStudioPage from "./CreativeProductionStudioPage";

const COHORT_SHA =
	"15b7e2aff4ede06b1a28805b111f9993b2208040e40bcee76693abc2a6ddbe7f";
const PRODUCTS = [
	{
		product_id: "product-a",
		product_name: "P6 Product A",
		product_type_group: "lip_color",
		scene_strategy_id: "LIP_COLOR",
		image_url: "https://example.com/a.jpg",
		image_readiness_status: "IMAGE_CACHE_READY",
		readiness_status: "PRODUCTION_READY",
	},
	{
		product_id: "product-b",
		product_name: "P6 Product B",
		product_type_group: "herbal_oil",
		scene_strategy_id: "HERBAL_OIL",
		image_url: "https://example.com/b.jpg",
		image_readiness_status: "IMAGE_CACHE_READY",
		readiness_status: "PRODUCTION_READY",
	},
];

type AvailabilityFixtureRequest = {
	product_video_allocations: Array<{
		product_id: string;
		video_count: number;
	}>;
	logical_mode: string;
	model_key: string;
	duration_seconds: number;
	creative_format: string;
	treatment_ids?: string[];
};

function makeTreatmentAvailability(
	body: AvailabilityFixtureRequest,
	ready = true,
) {
	const productResults = body.product_video_allocations.map((allocation) => {
		const selectedIds = ready
			? Array.from(
					{ length: allocation.video_count },
					(_, index) => `${allocation.product_id}-treatment-${index + 1}`,
				)
			: [];
		return {
			product_id: allocation.product_id,
			requested: allocation.video_count,
			eligible_capacity: ready ? allocation.video_count : 0,
			selected_count: selectedIds.length,
			selected_treatment_ids: selectedIds,
			ready,
			shortage: ready ? 0 : allocation.video_count,
			excluded_authority: [],
		};
	});
	const selectedTreatmentIds = productResults.flatMap(
		(product) => product.selected_treatment_ids,
	);
	return {
		ready,
		selection_mode: body.treatment_ids?.length ? "EXPLICIT" : "AUTO",
		requested: {
			logical_mode: body.logical_mode,
			model_key: body.model_key,
			duration_seconds: body.duration_seconds,
			creative_format: body.creative_format,
			video_count: body.product_video_allocations.reduce(
				(total, allocation) => total + allocation.video_count,
				0,
			),
		},
		selected_treatment_ids: selectedTreatmentIds,
		selected_treatments: [],
		product_results: productResults,
		supported_formats: ["UGC", "PGC", "CINEMATIC"],
		supported_configurations: [
			{
				format: "UGC",
				logical_mode: body.logical_mode,
				generation_mode: body.duration_seconds > 8 ? "EXTEND" : "SINGLE",
				duration_seconds: body.duration_seconds,
				model_keys: [body.model_key],
			},
		],
		blockers: ready
			? []
			: [
					{
						code: "TREATMENT_CAPACITY_INSUFFICIENT",
						product_id: body.product_video_allocations[0]?.product_id,
					},
				],
		availability_sha256: ready ? "a".repeat(64) : "b".repeat(64),
	};
}

const singleConfiguration = {
	model_key: "veo_3_1_lite",
	model_label: "Veo 3.1 - Lite",
	requested_total_duration_seconds: 8,
	engine_block_duration_seconds: 8,
	generation_mode: "SINGLE",
	segment_count: 1,
	execution_route: "SINGLE_SHOT_QUEUE",
};
const extendConfiguration = {
	model_key: "veo_3_1_lite",
	model_label: "Veo 3.1 - Lite",
	requested_total_duration_seconds: 16,
	engine_block_duration_seconds: 8,
	generation_mode: "EXTEND",
	segment_count: 2,
	execution_route: "VIDEO_JOBS_ORCHESTRATOR",
};

function makeSnapshot({
	planId,
	name,
	status,
	allocations,
	configuration,
	completeness = "COMPLETE",
	missingFields = [],
}: {
	planId: string;
	name: string;
	status: string;
	allocations: Array<{
		product_id: string;
		product_name: string;
		video_count: number;
	}>;
	configuration: typeof singleConfiguration;
	completeness?: "COMPLETE" | "LEGACY_INCOMPLETE";
	missingFields?: string[];
}) {
	const targetVideoCount = allocations.reduce(
		(total, allocation) => total + allocation.video_count,
		0,
	);
	return {
		schema_version: 1,
		completeness,
		missing_fields: missingFields,
		source:
			completeness === "COMPLETE" ? "CREATE_REQUEST" : "LEGACY_RECONCILIATION",
		evidence: {},
		plan_id: planId,
		plan_name: name,
		purpose: "P6.3-R2 fixture",
		status,
		operator_id: "p6-production-operator",
		request_id: `request-${planId}`,
		product_allocations: allocations,
		target_video_count: targetVideoCount,
		target_image_count: 0,
		target_poster_count: 0,
		logical_mode: "T2V",
		video_configurations: [configuration],
		aspect_ratio: "16:9",
		operating_window_hours: 12,
		allocation_strategy: "ROUND_ROBIN",
		variation_strategy: "SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS",
		approved_pool_snapshot: {},
		pool_snapshot: {
			treatment_ids: Array.from(
				{ length: targetVideoCount },
				(_, index) => `${planId}-treatment-${index + 1}`,
			),
			creative_format: "UGC",
			copy_set_ids: [],
			poster_copy_set_ids: [],
			avatar_codes: [],
			product_reference_asset_ids: [],
			finished_frame_asset_ids: [],
			character_asset_ids: [],
			scene_asset_ids: [],
			style_asset_ids: [],
			layout_ids: [],
			controlled_reuse_reason: null,
			controlled_reuse_max_per_dna: 1,
		},
		cohort_snapshot: {
			cohort_sha256: COHORT_SHA,
			cohort_count: 438,
			product_ids: allocations.map((allocation) => allocation.product_id),
		},
		matrix_count: targetVideoCount,
		attempts_count: 0,
		qa_count: 0,
		created_at: "2026-07-29T00:00:00Z",
		updated_at: "2026-07-30T00:00:00Z",
	};
}

function makePlan(snapshot: ReturnType<typeof makeSnapshot>) {
	return {
		plan_id: snapshot.plan_id,
		request_id: snapshot.request_id,
		created_by: snapshot.operator_id,
		name: snapshot.plan_name,
		campaign_key: snapshot.purpose ?? "",
		product_scope: snapshot.cohort_snapshot.product_ids,
		plan_snapshot: snapshot,
		snapshot_summary: {
			completeness: snapshot.completeness,
			missing_fields: snapshot.missing_fields,
			product_allocations: snapshot.product_allocations,
			video_configurations: snapshot.video_configurations,
			aspect_ratio: snapshot.aspect_ratio,
		},
		p58_cohort_sha256: COHORT_SHA,
		p58_cohort_count: 438,
		target_video_count: snapshot.target_video_count,
		target_image_count: 0,
		target_poster_count: 0,
		operating_window_hours: 12,
		allocation_strategy: "ROUND_ROBIN",
		variation_strategy: "SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS",
		logical_mode: "T2V",
		model_keys: ["veo_3_1_lite"],
		duration_seconds: [
			snapshot.video_configurations[0]?.requested_total_duration_seconds ?? 8,
		],
		pool_snapshot: snapshot.pool_snapshot,
		execution_policy: { aspect: snapshot.aspect_ratio },
		capacity_snapshot: {},
		compile_snapshot: {},
		blockers: [],
		status: snapshot.status,
		control_action: "NONE",
		control_version: 0,
		approved_by: "p6-approver",
		approved_at: "2026-07-29T01:00:00Z",
		created_at: snapshot.created_at,
		updated_at: snapshot.updated_at,
	};
}

const SNAPSHOT_A = makeSnapshot({
	planId: "plan-a",
	name: "Plan A",
	status: "PREFLIGHT_BLOCKED",
	allocations: [
		{ product_id: "product-a", product_name: "P6 Product A", video_count: 1 },
	],
	configuration: singleConfiguration,
});
const SNAPSHOT_B = makeSnapshot({
	planId: "plan-b",
	name: "Plan B",
	status: "SCHEDULED",
	allocations: [
		{ product_id: "product-a", product_name: "P6 Product A", video_count: 3 },
		{ product_id: "product-b", product_name: "P6 Product B", video_count: 2 },
	],
	configuration: extendConfiguration,
});
const SNAPSHOT_LEGACY = makeSnapshot({
	planId: "plan-legacy",
	name: "Legacy Plan",
	status: "SCHEDULED",
	allocations: [],
	configuration: singleConfiguration,
	completeness: "LEGACY_INCOMPLETE",
	missingFields: ["product_allocations"],
});
const SNAPSHOT_COMPLETED = makeSnapshot({
	planId: "plan-completed",
	name: "Completed Plan",
	status: "COMPLETED",
	allocations: [
		{ product_id: "product-a", product_name: "P6 Product A", video_count: 1 },
	],
	configuration: singleConfiguration,
});
const SNAPSHOT_CANCELLED = makeSnapshot({
	planId: "plan-cancelled",
	name: "Cancelled Plan",
	status: "CANCELLED",
	allocations: [
		{ product_id: "product-a", product_name: "P6 Product A", video_count: 1 },
	],
	configuration: singleConfiguration,
});

const PLANS = [
	makePlan(SNAPSHOT_A),
	makePlan(SNAPSHOT_B),
	makePlan(SNAPSHOT_LEGACY),
	makePlan(SNAPSHOT_COMPLETED),
	makePlan(SNAPSHOT_CANCELLED),
];

function item(planId: string, ordinal: number, productId: string) {
	return {
		item_id: `${planId}-item-${ordinal}`,
		plan_id: planId,
		item_ordinal: ordinal,
		product_id: productId,
		media_type: "VIDEO",
		logical_mode: "T2V",
		creative_dimensions: {
			generation_mode: planId === "plan-b" ? "EXTEND" : "SINGLE",
			duration_seconds: planId === "plan-b" ? "16" : "8",
		},
		creative_dna_sha256: `${ordinal}`.repeat(64),
		controlled_reuse_reason: null,
		prompt_fingerprint: null,
		workspace_generation_package_id: null,
		prompt_package: {},
		status: "PLANNED",
		output_media_id: null,
		replacement_for_item_id: null,
		replaced_by_item_id: null,
	};
}

function makeDetail(
	snapshot: ReturnType<typeof makeSnapshot>,
	items: ReturnType<typeof item>[],
) {
	return {
		plan: makePlan(snapshot),
		snapshot,
		waves: [],
		batches: [],
		items,
		attempts:
			snapshot.plan_id === "plan-b"
				? [
						{
							attempt_id: "plan-b-dry-attempt",
							item_id: "plan-b-item-0",
							attempt_number: 1,
							idempotency_key: "dry-plan-b",
							lane_id: null,
							attempt_state: "NOT_SUBMITTED",
							payload_sha256: "b".repeat(64),
							credit_spend_intended: false,
							provider_job_id: null,
							artifact_media_id: null,
							failure_stage: null,
							failure_code: null,
							recovery_class: null,
						},
					]
				: [],
		qa: [],
		audit_events: [],
		progress: {
			total: items.length,
			terminal: 0,
			percent: 0,
			by_status: { PLANNED: items.length },
		},
	};
}

const DETAILS: Record<string, ReturnType<typeof makeDetail>> = {
	"plan-a": makeDetail(SNAPSHOT_A, [item("plan-a", 0, "product-a")]),
	"plan-b": makeDetail(SNAPSHOT_B, [
		item("plan-b", 0, "product-a"),
		item("plan-b", 1, "product-a"),
		item("plan-b", 2, "product-a"),
		item("plan-b", 3, "product-b"),
		item("plan-b", 4, "product-b"),
	]),
	"plan-legacy": makeDetail(SNAPSHOT_LEGACY, []),
	"plan-completed": makeDetail(SNAPSHOT_COMPLETED, [
		item("plan-completed", 0, "product-a"),
	]),
	"plan-cancelled": makeDetail(SNAPSHOT_CANCELLED, [
		item("plan-cancelled", 0, "product-a"),
	]),
};

const HEALTHY_LANES = {
	live_execution_certified: true,
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
			health_status: "HEALTHY",
			enabled: true,
			runtime_proof_status: "VERIFIED",
			evidence_reference: "ADR-007",
			active_lease_count: 0,
		},
	],
};

function prime() {
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
		],
	});
	fetchCohortAuthority.mockResolvedValue({
		cohort_count: 438,
		cohort_sha256: COHORT_SHA,
		product_ids: PRODUCTS.map((product) => product.product_id),
		products: PRODUCTS,
		matches_frozen_authority: true,
		p6_not_started: false,
	});
	fetchGovernedPoolAuthority.mockResolvedValue({
		product_ids: [],
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
	fetchTreatmentAvailability.mockImplementation(
		(body: AvailabilityFixtureRequest) =>
			Promise.resolve(makeTreatmentAvailability(body)),
	);
	listProductionPlans.mockResolvedValue({ plans: PLANS });
	fetchProductionPlan.mockImplementation((planId: string) =>
		Promise.resolve(DETAILS[planId]),
	);
	listExecutionLanes.mockResolvedValue(HEALTHY_LANES);
	startProductionPlan.mockResolvedValue({ plan_id: "plan-b" });
}

async function selectPlan(planId: string) {
	const select = await screen.findByLabelText("Select production plan");
	fireEvent.change(select, { target: { value: planId } });
	await screen.findByTestId("p6-plan-status");
}

beforeEach(() => {
	vi.stubGlobal("crypto", {
		randomUUID: () => "00000000-0000-4000-8000-000000000001",
	});
	prime();
});

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
	vi.unstubAllGlobals();
});

describe("P6.3-R2 production plan state isolation", () => {
	it("opens in NEW_DRAFT without auto-selecting history or rendering old plan data", async () => {
		render(<CreativeProductionStudioPage />);
		await screen.findByText(
			"NEW PRODUCTION PLAN — no existing plan is selected.",
		);
		expect(fetchProductionPlan).not.toHaveBeenCalled();
		expect(screen.getByLabelText("Select production plan")).toHaveValue("");
		expect(screen.queryByTestId("p6-content-matrix")).not.toBeInTheDocument();
		expect(
			screen.queryByTestId("p6-live-confirmation"),
		).not.toBeInTheDocument();
		expect(screen.getByTestId("p6-create-plan")).toHaveTextContent(
			"Create production plan",
		);
	});

	it("loads an existing plan only by explicit selection and renders exact 3+2 EXTEND truth", async () => {
		render(<CreativeProductionStudioPage />);
		await selectPlan("plan-b");
		const snapshot = screen.getByTestId("p6-readonly-plan-snapshot");
		expect(snapshot).toHaveTextContent("P6 Product A");
		expect(snapshot).toHaveTextContent("3 videos");
		expect(snapshot).toHaveTextContent("P6 Product B");
		expect(snapshot).toHaveTextContent("2 videos");
		expect(snapshot).toHaveTextContent("16s EXTEND");
		expect(snapshot).toHaveTextContent("2 segments");
		expect(
			screen.getByTestId("p6-selected-treatment-authority"),
		).toHaveTextContent("5 immutable approvals");
		expect(snapshot).toHaveTextContent("plan-b-treatment-5");
		expect(screen.getByTestId("p6-content-matrix")).toHaveTextContent(
			"plan-b-item-4",
		);
	});

	it("ignores a late Plan A response after Plan B has been selected", async () => {
		let resolvePlanA:
			| ((detail: ReturnType<typeof makeDetail>) => void)
			| undefined;
		fetchProductionPlan.mockImplementation((planId: string) => {
			if (planId === "plan-a") {
				return new Promise((resolve) => {
					resolvePlanA = resolve;
				});
			}
			return Promise.resolve(DETAILS[planId]);
		});
		render(<CreativeProductionStudioPage />);
		const select = await screen.findByLabelText("Select production plan");
		fireEvent.change(select, { target: { value: "plan-a" } });
		fireEvent.change(select, { target: { value: "plan-b" } });
		expect(await screen.findByText("Plan B")).toBeInTheDocument();
		await act(async () => {
			resolvePlanA?.(DETAILS["plan-a"]);
		});
		expect(screen.getByTestId("p6-readonly-plan-snapshot")).toHaveTextContent(
			"16s EXTEND",
		);
		expect(screen.getByLabelText("Select production plan")).toHaveValue(
			"plan-b",
		);
	});

	it("fails closed during capacity checks and ignores a stale shortage response", async () => {
		let resolveFirst:
			| ((value: ReturnType<typeof makeTreatmentAvailability>) => void)
			| undefined;
		let firstRequest: AvailabilityFixtureRequest | undefined;
		fetchTreatmentAvailability
			.mockReset()
			.mockImplementationOnce(
				(body: AvailabilityFixtureRequest) =>
					new Promise((resolve) => {
						firstRequest = body;
						resolveFirst = resolve;
					}),
			)
			.mockImplementationOnce((body: AvailabilityFixtureRequest) =>
				Promise.resolve(makeTreatmentAvailability(body)),
			);

		render(<CreativeProductionStudioPage />);
		await screen.findByText("Select existing plan");
		fireEvent.click(screen.getByRole("button", { name: /Choose products/i }));
		fireEvent.click(
			await screen.findByRole("option", { name: /P6 Product A/i }),
		);

		await waitFor(() =>
			expect(fetchTreatmentAvailability).toHaveBeenCalledTimes(1),
		);
		expect(screen.getByTestId("p6-create-plan")).toBeDisabled();
		expect(screen.getByTestId("p6-treatment-availability")).toHaveTextContent(
			"CHECKING",
		);

		fireEvent.change(screen.getByLabelText("Video quantity for P6 Product A"), {
			target: { value: "2" },
		});
		await waitFor(() =>
			expect(screen.getByTestId("p6-treatment-availability")).toHaveTextContent(
				"2/2 unique approved treatments allocated",
			),
		);
		await waitFor(() =>
			expect(screen.getByTestId("p6-create-plan")).toBeEnabled(),
		);

		await act(async () => {
			if (!firstRequest) throw new Error("first availability request missing");
			resolveFirst?.(makeTreatmentAvailability(firstRequest, false));
		});
		expect(screen.getByTestId("p6-treatment-availability")).toHaveTextContent(
			"2/2 unique approved treatments allocated",
		);
		expect(screen.getByTestId("p6-create-plan")).toBeEnabled();
		expect(screen.queryByText(/0\/1 eligible/i)).not.toBeInTheDocument();
	});

	it("duplicates an active plan into an explicit UNSAVED draft with no old matrix or live action", async () => {
		render(<CreativeProductionStudioPage />);
		await selectPlan("plan-b");
		fireEvent.click(screen.getAllByText("Duplicate as new plan")[0]);
		expect(
			await screen.findByTestId("p6-unsaved-draft-warning"),
		).toHaveTextContent("UNSAVED NEW PLAN");
		expect(
			screen.getByLabelText("Video quantity for P6 Product A"),
		).toHaveValue(3);
		expect(
			screen.getByLabelText("Video quantity for P6 Product B"),
		).toHaveValue(2);
		expect(screen.queryByTestId("p6-content-matrix")).not.toBeInTheDocument();
		expect(
			screen.queryByTestId("p6-live-confirmation"),
		).not.toBeInTheDocument();
		expect(screen.getByTestId("p6-create-plan")).toHaveTextContent(
			"Create new production plan",
		);
		expect(
			screen.getByText(
				/joining happens only after separate live confirmation/i,
			),
		).toBeInTheDocument();
	});

	it("returns atomically to a blank new plan", async () => {
		render(<CreativeProductionStudioPage />);
		await selectPlan("plan-a");
		fireEvent.click(screen.getByText("Return to new plan"));
		expect(
			await screen.findByText(
				"NEW PRODUCTION PLAN — no existing plan is selected.",
			),
		).toBeInTheDocument();
		expect(screen.queryByTestId("p6-content-matrix")).not.toBeInTheDocument();
		expect(
			screen.queryByTestId("p6-readonly-plan-snapshot"),
		).not.toBeInTheDocument();
	});

	it("marks incomplete legacy plans and keeps production disabled without inventing allocation", async () => {
		render(<CreativeProductionStudioPage />);
		await selectPlan("plan-legacy");
		expect(screen.getByTestId("p6-primary-action")).toHaveTextContent(
			"Production unavailable",
		);
		expect(
			screen.getByText("Legacy plan — incomplete snapshot"),
		).toBeInTheDocument();
		expect(screen.getByTestId("p6-live-disabled-reason")).toHaveTextContent(
			"product_allocations",
		);
		expect(
			screen.getByTestId("p6-readonly-plan-snapshot"),
		).not.toHaveTextContent(/1 video/);
	});

	it("filters history by authoritative status and does not classify test plans by name", async () => {
		render(<CreativeProductionStudioPage />);
		await screen.findByText("Production history");
		expect(screen.queryByText("Completed Plan")).not.toBeInTheDocument();
		expect(screen.queryByText("Cancelled Plan")).not.toBeInTheDocument();
		fireEvent.change(
			screen.getByLabelText("Filter production history by status"),
			{ target: { value: "ALL" } },
		);
		expect(await screen.findByText("Completed Plan")).toBeInTheDocument();
		expect(screen.getByText("Cancelled Plan")).toBeInTheDocument();
		expect(
			screen.getByText(/no reliable provenance marker exists/i),
		).toBeInTheDocument();
	});

	it("resets confirmation on plan switch and binds start to the exact plan and aspect", async () => {
		render(<CreativeProductionStudioPage />);
		await selectPlan("plan-b");
		const confirmation = screen.getByTestId("p6-live-confirmation");
		fireEvent.change(confirmation, {
			target: { value: "AUTHORIZE_P6_LIVE_CREDIT_SPEND" },
		});
		expect(screen.getByTestId("p6-action-live-start")).toBeEnabled();
		expect(
			screen.getAllByText(/sends the next queued item now/i),
		).not.toHaveLength(0);
		expect(screen.getByText(/Plan: plan-b/)).toBeInTheDocument();
		fireEvent.change(screen.getByLabelText("Select production plan"), {
			target: { value: "plan-a" },
		});
		await waitFor(() =>
			expect(screen.getByTestId("p6-live-confirmation")).toHaveValue(""),
		);
		fireEvent.change(screen.getByLabelText("Select production plan"), {
			target: { value: "plan-b" },
		});
		await waitFor(() =>
			expect(screen.getByTestId("p6-plan-status")).toHaveTextContent(
				"SCHEDULED",
			),
		);
		fireEvent.change(screen.getByTestId("p6-live-confirmation"), {
			target: { value: "AUTHORIZE_P6_LIVE_CREDIT_SPEND" },
		});
		fireEvent.click(screen.getByTestId("p6-action-live-start"));
		await waitFor(() =>
			expect(startProductionPlan).toHaveBeenCalledWith(
				"plan-b",
				"p6-production-operator",
				"AUTHORIZE_P6_LIVE_CREDIT_SPEND",
				"16:9",
			),
		);
	});

	it("refuses to render matrix, attempts or QA when a response is not plan-bound", async () => {
		fetchProductionPlan.mockImplementation((planId: string) => {
			if (planId !== "plan-a") return Promise.resolve(DETAILS[planId]);
			return Promise.resolve({
				...DETAILS["plan-a"],
				items: [
					{
						...DETAILS["plan-a"].items[0],
						plan_id: "wrong-plan",
					},
				],
			});
		});
		render(<CreativeProductionStudioPage />);
		const select = await screen.findByLabelText("Select production plan");
		fireEvent.change(select, { target: { value: "plan-a" } });
		expect(await screen.findByRole("alert")).toHaveTextContent(
			"internally inconsistent",
		);
		expect(screen.queryByTestId("p6-content-matrix")).not.toBeInTheDocument();
		expect(screen.queryByTestId("p6-attempt-list")).not.toBeInTheDocument();
		expect(screen.queryByTestId("p6-qa-list")).not.toBeInTheDocument();
	});

	it("preserves plain operator labels and SINGLE/EXTEND semantics", async () => {
		render(<CreativeProductionStudioPage />);
		expect(await screen.findByText("Select existing plan")).toBeInTheDocument();
		expect(screen.getAllByText("New production plan")).not.toHaveLength(0);
		expect(screen.queryByText(/durable \/video-jobs/i)).not.toBeInTheDocument();
		expect(screen.queryByText(/operator authority/i)).not.toBeInTheDocument();
		await selectPlan("plan-a");
		expect(screen.getByTestId("p6-readonly-plan-snapshot")).toHaveTextContent(
			"8s SINGLE",
		);
	});
});
