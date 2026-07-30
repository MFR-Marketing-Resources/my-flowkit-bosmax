import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const listSupplyRuns = vi.fn();
const fetchSupplyRun = vi.fn();
const executeSupplyStep = vi.fn();
const controlSupplyRun = vi.fn();
const retrySupplyTask = vi.fn();
const reviewSupplyComponent = vi.fn();

vi.mock("../api/creativeSupply", () => ({
	listSupplyRuns: (...args: unknown[]) => listSupplyRuns(...args),
	fetchSupplyRun: (...args: unknown[]) => fetchSupplyRun(...args),
	executeSupplyStep: (...args: unknown[]) => executeSupplyStep(...args),
	controlSupplyRun: (...args: unknown[]) => controlSupplyRun(...args),
	retrySupplyTask: (...args: unknown[]) => retrySupplyTask(...args),
	reviewSupplyComponent: (...args: unknown[]) =>
		reviewSupplyComponent(...args),
}));

import CreativeSupplyFactoryPanel from "./CreativeSupplyFactoryPanel";

const RUN = {
	run_id: "csr-ui",
	mission_id: "BOSMAX-P7-TEST",
	roster_sha256: "a".repeat(64),
	cohort_sha256: "b".repeat(64),
	roster: [],
	angle_plan: [],
	target_policy: {},
	state: "RUNNING",
	provider_budget_max: 120,
	provider_calls_used: 1,
	reviewer_id: "codex-p7-reviewer",
	pause_reason: null,
	last_error: null,
	created_at: "2026-07-30T00:00:00Z",
	updated_at: "2026-07-30T00:00:00Z",
};

const CANDIDATE = {
	component_id: "component-ui",
	product_id: "product-ui",
	angle_key: "angle-ui",
	angle_label: "Masalah rutin",
	component_type: "HOOK",
	content: "Rutin harian terasa makin susah?",
	status: "COMPONENT_REVIEW_REQUIRED",
	content_sha256: "c".repeat(64),
	provider_provenance: { lane: "text_assist" },
};

const STATUS = {
	run: RUN,
	products: [
		{
			product_id: "product-ui",
			product_name: "Product UI",
			rank: 1,
			role: "HERO",
			product_truth_readiness: "READY_FOR_APPROVAL",
			approved_snapshot_status: "APPROVED",
			claim_gate: "CLAIM_SAFE",
			angle_count: 4,
			component_total: 16,
			review_required_count: 1,
			approved_count: 15,
			rejected_count: 0,
			deficits: [{ angle_key: "angle-ui", component_type: "HOOK", missing: 1 }],
			composable_capacity: 432,
			capacity_target: 500,
			approved_copy_set_count: 8,
			avatar_readiness: "APPROVED",
			scene_readiness: "APPROVED",
			video_asset_readiness: {
				product_reference: true,
				composite_frame_reference: true,
			},
			poster_image_readiness: "BLOCKED",
			p6_preflight_status: "REQUIRES_EXACT_ZERO_CREDIT_PREFLIGHT",
			blockers: ["COMPOSABLE_CAPACITY_SHORTFALL:432/500"],
			next_best_supply_action: "AUTHOR:angle-ui:HOOK:missing=1",
		},
	],
	tasks: [],
	task_counts: { REVIEW_REQUIRED: 1 },
	review_events: [],
	review_queue: [
		{
			task_id: "task-ui",
			run_id: RUN.run_id,
			product_id: "product-ui",
			angle_key: "angle-ui",
			angle_label: "Masalah rutin",
			component_type: "HOOK",
			task_kind: "AUTHOR_DEFICIT",
			deficit_round: 1,
			target_approved_count: 6,
			requested_count: 2,
			attempt_count: 1,
			provider_call_count: 1,
			state: "REVIEW_REQUIRED",
			transient_failure_proven: 0,
			last_error: null,
			result: { component_ids: [CANDIDATE.component_id] },
			candidates: [CANDIDATE],
		},
	],
	provider_budget: {
		maximum: 120,
		used: 1,
		remaining: 119,
		pending_or_retry_calls: 1,
		within_ceiling: true,
	},
	exact_blockers: ["COMPOSABLE_CAPACITY_SHORTFALL:432/500"],
};

describe("CreativeSupplyFactoryPanel", () => {
	beforeEach(() => {
		listSupplyRuns.mockResolvedValue({ runs: [RUN] });
		fetchSupplyRun.mockResolvedValue(STATUS);
		executeSupplyStep.mockResolvedValue(STATUS);
		controlSupplyRun.mockResolvedValue(STATUS);
		reviewSupplyComponent.mockResolvedValue({ run: STATUS });
	});

	afterEach(() => {
		cleanup();
		vi.clearAllMocks();
	});

	it("renders frozen supply status, budget, blockers, and review queue", async () => {
		render(<CreativeSupplyFactoryPanel />);
		expect(
			await screen.findByTestId("p7-creative-supply-factory"),
		).toBeInTheDocument();
		expect(await screen.findByText("1/120")).toBeInTheDocument();
		expect(screen.getByTestId("p7-product-product-ui")).toHaveTextContent(
			"COMPOSABLE_CAPACITY_SHORTFALL",
		);
		expect(screen.getByTestId("p7-review-queue")).toHaveTextContent(
			CANDIDATE.content,
		);
		expect(screen.queryByText(/approve all/i)).not.toBeInTheDocument();
	});

	it("keeps loading distinct from a truthful no-run state while detail settles", async () => {
		let resolveStatus: (value: typeof STATUS) => void = () => undefined;
		fetchSupplyRun.mockImplementationOnce(
			() =>
				new Promise<typeof STATUS>((resolve) => {
					resolveStatus = resolve;
				}),
		);

		render(<CreativeSupplyFactoryPanel />);
		expect(await screen.findByTestId("p7-loading-run")).toHaveTextContent(
			"Loading the selected canonical P7 run",
		);
		expect(screen.queryByTestId("p7-empty-run")).not.toBeInTheDocument();

		resolveStatus(STATUS);
		expect(await screen.findByText("1/120")).toBeInTheDocument();
		expect(screen.queryByTestId("p7-loading-run")).not.toBeInTheDocument();
		expect(screen.queryByTestId("p7-empty-run")).not.toBeInTheDocument();
	});

	it("renders a retryable load failure instead of a false no-run state", async () => {
		fetchSupplyRun.mockRejectedValueOnce(new Error("detail unavailable"));

		render(<CreativeSupplyFactoryPanel />);
		expect(await screen.findByRole("alert")).toHaveTextContent(
			"detail unavailable",
		);
		expect(screen.getByTestId("p7-load-failed")).toHaveTextContent(
			"Use Refresh creative supply",
		);
		expect(screen.queryByTestId("p7-empty-run")).not.toBeInTheDocument();
	});

	it("refuses blind review and binds an explicit decision to the content sha", async () => {
		render(<CreativeSupplyFactoryPanel />);
		await screen.findByTestId("p7-review-component-ui");
		fireEvent.click(screen.getByRole("button", { name: "Approve reviewed" }));
		expect(await screen.findByRole("alert")).toHaveTextContent(
			"Review reason required",
		);
		expect(reviewSupplyComponent).not.toHaveBeenCalled();

		fireEvent.change(screen.getByLabelText("Review reason component-ui"), {
			target: {
				value:
					"Product-specific, correct angle and HOOK type, claim-safe BM, distinct and provenance verified.",
			},
		});
		fireEvent.click(screen.getByRole("button", { name: "Approve reviewed" }));
		await waitFor(() =>
			expect(reviewSupplyComponent).toHaveBeenCalledWith(RUN.run_id, {
				task_id: "task-ui",
				component_id: CANDIDATE.component_id,
				decision: "APPROVED",
				reviewed_content_sha256: CANDIDATE.content_sha256,
				reasons: [
					"Product-specific, correct angle and HOOK type, claim-safe BM, distinct and provenance verified.",
				],
				reviewer_id: RUN.reviewer_id,
			}),
		);
	});

	it("exposes durable pause and one-slot author controls", async () => {
		render(<CreativeSupplyFactoryPanel />);
		await screen.findByTestId("p7-author-next-slot");
		fireEvent.click(screen.getByTestId("p7-pause-run"));
		await waitFor(() =>
			expect(controlSupplyRun).toHaveBeenCalledWith(
				RUN.run_id,
				"PAUSE",
				"Operator paused at a durable task boundary.",
			),
		);
		fireEvent.click(screen.getByTestId("p7-author-next-slot"));
		await waitFor(() => expect(executeSupplyStep).toHaveBeenCalledWith(RUN.run_id));
	});
});
