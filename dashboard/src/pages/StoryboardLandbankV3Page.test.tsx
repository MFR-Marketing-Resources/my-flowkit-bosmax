import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StoryboardLandbankV3Page from "./StoryboardLandbankV3Page";

vi.mock("../hooks/useProductCatalog", () => ({
	useProductCatalog: () => ({
		products: [{ id: "p1", raw_product_title: "Test Product", product_display_name: "Test Product" }],
		isLoadingProducts: false,
		productsError: null,
	}),
}));

vi.mock("../components/workspace/SearchableProductSelect", () => ({
	default: () => <div data-testid="v3-product-picker">Product picker</div>,
}));

vi.mock("../api/storyboardLandbankV3Round2", () => ({
	fetchV3CopyRegisterProviderStatus: vi.fn(),
	planV3Assistant: vi.fn(),
	fetchV3AssistantPromptPreview: vi.fn(),
	executeV3Assistant: vi.fn(),
	fetchV3CopyRegisterLandbank: vi.fn(),
	fetchV3ProductTruth: vi.fn(),
	approveV3Master: vi.fn(),
	approveV3MasterBatch: vi.fn(),
	setupV3Campaign: vi.fn(),
	reviewV3Entity: vi.fn(),
}));

import {
	approveV3Master,
	executeV3Assistant,
	fetchV3AssistantPromptPreview,
	fetchV3CopyRegisterLandbank,
	fetchV3CopyRegisterProviderStatus,
	fetchV3ProductTruth,
	planV3Assistant,
	reviewV3Entity,
	setupV3Campaign,
} from "../api/storyboardLandbankV3Round2";

const mockedStatus = vi.mocked(fetchV3CopyRegisterProviderStatus);
const mockedPlan = vi.mocked(planV3Assistant);
const mockedPreview = vi.mocked(fetchV3AssistantPromptPreview);
const mockedExecute = vi.mocked(executeV3Assistant);
const mockedLandbank = vi.mocked(fetchV3CopyRegisterLandbank);
const mockedTruth = vi.mocked(fetchV3ProductTruth);
const mockedApprove = vi.mocked(approveV3Master);
const mockedSetup = vi.mocked(setupV3Campaign);
const mockedReview = vi.mocked(reviewV3Entity);

const item = {
	master: {
		master_id: "master-v3",
		revision: 1,
		product_id: "p1",
		formula: { formula_id: "PAS", formula_version: "pas.v1" },
		angle: { entity_id: "angle-v3", revision: 1 },
		storyline_family: { entity_id: "family-v3", revision: 1 },
		stages: [
			{ stage_key: "problem", formula_stage_key: "problem", semantic_class: "HOOK", authored_text: "Want a lighter routine?" },
			{ stage_key: "agitate", formula_stage_key: "agitate", semantic_class: "BODY_CORE", authored_text: "Choose this lightweight formula today." },
			{ stage_key: "solution", formula_stage_key: "solution", semantic_class: "BODY_CORE", authored_text: "Keep each step simple and steady." },
			{ stage_key: "cta", formula_stage_key: "cta", semantic_class: "CTA", authored_text: "Start your routine today." },
		],
		status: "VALIDATED",
		source: "ROUND2",
		exact_content_digest: "a".repeat(64),
		word_count: 19,
	},
	projections: [8, 16, 24].map((duration) => ({
		projection_id: `projection-${duration}`,
		revision: 1,
		target_duration_seconds: duration,
		exact_resolved_dialogue: "Want a lighter routine? Choose this lightweight formula today.",
		derivation_source: "DETERMINISTIC",
		status: "VALIDATED",
		per_block_word_budgets: [19],
	})),
	quality: {
		hard_pass: true,
		formula_valid: true,
		evidence_valid: true,
		bridge_valid: true,
		claim_safety_valid: true,
		truth_current: true,
		wps_valid: true,
		issue_codes: [],
		novelty_signal: "NOVEL",
		novelty_score: 1,
		quality_score: 1,
	},
	current_truth: true,
	approval_receipt: null,
	v2_materialization: "NOT_IN_ROUND2",
	p6_status: "NOT_IN_ROUND2",
} as const;

function renderPage() {
	return render(
		<MemoryRouter initialEntries={["/creative/storyboard-landbank-v3?product_id=p1"]}>
			<StoryboardLandbankV3Page />
		</MemoryRouter>,
	);
}

describe("StoryboardLandbankV3Page Round 2 contract", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockedStatus.mockResolvedValue({ lane: "text_assist", status: "NOT_CONFIGURED", configured: false, provider_id: null, model_id: null, execution_enabled: false, provider_calls: 0, credit_spend: 0, fake_provider_allowed: true });
		mockedTruth.mockResolvedValue({ product_id: "p1", lineage: {}, facts: [{ fact_id: "fact-1", fact_kind: "BENEFIT", text: "A lightweight daily routine.", text_digest: "d".repeat(64), approved: true }], fact_count: 1, provider_calls: 0, mutations: 0 });
		mockedLandbank.mockResolvedValue({ source: "V3_COPY_REGISTER", product_id: "p1", items: [item], total: 1, limit: 50, offset: 0, has_more: false, provider_calls: 0, v2_mixed: false, full_storyboard_first: true });
		mockedPlan.mockResolvedValue({ plan: { plan_id: "plan-v3", run_id: "run-v3", product_id: "p1", recipe: { entity_id: "recipe-v3", revision: 1 }, mode: "CREATE", target_counts: { HOOK: 1, BODY_CORE: 1, CTA: 1 }, gaps: [{ semantic_class: "HOOK", current_count: 0, target_count: 1, gap_count: 1, reason: "target" }, { semantic_class: "BODY_CORE", current_count: 0, target_count: 1, gap_count: 1, reason: "target" }, { semantic_class: "CTA", current_count: 0, target_count: 1, gap_count: 1, reason: "target" }], target_durations_seconds: [8, 16, 24], wps_mode: "SAFE", provider: { lane: "text_assist", status: "NOT_CONFIGURED", configured: false, provider_id: null, model_id: null, execution_enabled: false, provider_calls: 0, credit_spend: 0, fake_provider_allowed: true }, prompt_version: "v1", prompt_digest: "b".repeat(64), estimated_provider_calls: 1, estimated_output_tokens: 540, estimated_credit_spend: 0, max_proposals: 3, explicit_execute_required: true, created_at: "2026-08-17T00:00:00Z", created_by: "operator" }, provider_calls: 0, credit_spend: 0 });
		mockedPreview.mockResolvedValue({ preview: { prompt_digest: "c".repeat(64), system_instructions: "strict", untrusted_truth_json: "{}", requested_output_contract: {} }, provider_calls: 0, credit_spend: 0 });
		mockedExecute.mockResolvedValue({ run_id: "run-v3", plan_id: "plan-v3", status: "EXECUTED", provider: { mode: "FAKE_TEST", provider_id: "fake", model_id: "fixture" }, master: { entity_id: "master-v3", revision: 1 }, projections: [], quality: item.quality, provider_calls: 0, credit_spend: 0, projection_derivation: "DETERMINISTIC_WPS_FROM_AI_AUTHORED_MASTER" });
		mockedApprove.mockResolvedValue({ receipt: { receipt_id: "receipt-v3" }, master: { ...item.master, status: "APPROVED" }, projections: item.projections, automatic_approval: false });
		mockedSetup.mockResolvedValue({ recipe_id: "recipe-preset", recipe_revision: 1, preset: "FAST54", reused: false, recipe: {} });
		mockedReview.mockResolvedValue({});
	});

	afterEach(() => cleanup());

	it("builds a campaign recipe from a preset without a raw recipe id", async () => {
		renderPage();
		expect(await screen.findByTestId("storyboard-landbank-v3-page")).toBeInTheDocument();
		fireEvent.change(screen.getByTestId("v3-preset"), { target: { value: "FAST54" } });
		fireEvent.change(screen.getByTestId("v3-formula"), { target: { value: "PAS" } });
		fireEvent.click(screen.getByTestId("v3-build-campaign"));
		await waitFor(() => expect(mockedSetup).toHaveBeenCalledWith(expect.objectContaining({ product_id: "p1", preset: "FAST54", formula_id: "PAS", wps_mode: "SWEET" })));
		expect(await screen.findByTestId("v3-active-recipe")).toBeInTheDocument();
		// The raw recipe id lives in the Technical Details drawer, not the main path.
		expect(screen.getByTestId("v3-technical-details")).toBeInTheDocument();
	});

	it("surfaces draft review actions and separates clean candidates from exceptions", async () => {
		renderPage();
		await screen.findByTestId("storyboard-landbank-v3-page");
		// Review-verb actions are available on the reviewable master card.
		fireEvent.click(await screen.findByTestId("v3-action-validate"));
		await waitFor(() => expect(mockedReview).toHaveBeenCalledWith("validate", "MASTER_STORYBOARD", "master-v3", 1));
		// Batch approval dialog shows the exact machine-clean scope.
		fireEvent.click(screen.getByTestId("v3-open-bulk-approval"));
		expect(await screen.findByTestId("v3-batch-scope")).toBeInTheDocument();
		expect(screen.getByTestId("v3-batch-clean-item")).toHaveTextContent("master-v3");
	});

	it("keeps V3 jobs separated and walks explicit plan → fake execute → full review → approval", async () => {
		renderPage();
		expect(await screen.findByTestId("storyboard-landbank-v3-page")).toBeInTheDocument();
		expect(screen.getByText("V2 production authority stays separate")).toBeInTheDocument();
		expect(screen.getByTestId("v3-provider-status")).toHaveTextContent("FAKE TEST ENABLED");

		fireEvent.change(screen.getByTestId("v3-recipe-id"), { target: { value: "recipe-v3" } });
		fireEvent.click(screen.getByTestId("v3-plan-assistant"));
		await waitFor(() => expect(mockedPlan).toHaveBeenCalledWith(expect.objectContaining({ product_id: "p1", recipe_id: "recipe-v3", mode: "CREATE" })));
		expect(await screen.findByTestId("v3-assistant-plan")).toHaveTextContent("Plan plan-v3");
		fireEvent.click(screen.getByTestId("v3-prompt-preview"));
		await waitFor(() => expect(mockedPreview).toHaveBeenCalledWith("plan-v3"));
		fireEvent.click(screen.getByTestId("v3-execute-fake"));
		await waitFor(() => expect(mockedExecute).toHaveBeenCalledWith("plan-v3", "FAKE_TEST"));
		expect(await screen.findByTestId("v3-full-storyboard")).toHaveTextContent("Want a lighter routine?");
		expect(screen.getByTestId("v3-projection-grid")).toHaveTextContent("8s projection");

		fireEvent.click(screen.getByTestId("v3-open-approval"));
		expect(await screen.findByTestId("v3-approval-dialog")).toBeInTheDocument();
		for (const key of ["semantic_reviewed", "product_truth_reviewed", "formula_reviewed", "evidence_reviewed", "bridge_reviewed", "safety_reviewed", "duration_reviewed"]) {
			fireEvent.click(screen.getByTestId(`v3-check-${key}`));
		}
		fireEvent.click(screen.getByTestId("v3-approve-master"));
		await waitFor(() => expect(mockedApprove).toHaveBeenCalledWith(expect.objectContaining({ master_id: "master-v3", checklist: expect.objectContaining({ duration_reviewed: true }) })));
	});

	it("disables live Generate with AI when text_assist is not configured", async () => {
		// Default beforeEach mock is NOT_CONFIGURED (fake test enabled).
		renderPage();
		fireEvent.change(await screen.findByTestId("v3-recipe-id"), { target: { value: "recipe-v3" } });
		fireEvent.click(screen.getByTestId("v3-plan-assistant"));
		expect(await screen.findByTestId("v3-generate-live")).toBeDisabled();
		expect(screen.getByTestId("v3-execute-fake")).toBeEnabled();
	});

	it("enables live Generate with AI when text_assist is configured", async () => {
		mockedStatus.mockResolvedValue({ lane: "text_assist", status: "READY", configured: true, provider_id: "qwen", model_id: "qwen-plus", execution_enabled: true, provider_calls: 0, credit_spend: 0, fake_provider_allowed: false });
		renderPage();
		fireEvent.change(await screen.findByTestId("v3-recipe-id"), { target: { value: "recipe-v3" } });
		fireEvent.click(screen.getByTestId("v3-plan-assistant"));
		expect(await screen.findByTestId("v3-generate-live")).toBeEnabled();
	});
});
