import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StoryboardLandbankV3Page from "./StoryboardLandbankV3Page";

const mockNavigate = vi.fn();

vi.mock("react-router-dom", async (importOriginal) => {
	const actual = await importOriginal<typeof import("react-router-dom")>();
	return { ...actual, useNavigate: () => mockNavigate };
});

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

vi.mock("../api/products", async (importOriginal) => {
	const actual = await importOriginal<typeof import("../api/products")>();
	return { ...actual, fetchProductDetail: vi.fn() };
});

vi.mock("../api/storyboardLandbankV3Round2", () => ({
	fetchV3CopyRegisterProviderStatus: vi.fn(),
	planV3Assistant: vi.fn(),
	fetchV3AssistantPromptPreview: vi.fn(),
	executeV3Assistant: vi.fn(),
	fetchV3CopyRegisterLandbank: vi.fn(),
	fetchV3ProductTruth: vi.fn(),
	fetchV3ProductionCapacity: vi.fn(),
	approveV3Master: vi.fn(),
	approveV3MasterBatch: vi.fn(),
	setupV3Campaign: vi.fn(),
	reviewV3Entity: vi.fn(),
	deleteV3Draft: vi.fn(),
	regenerateV3Component: vi.fn(),
	materializeV3Projection: vi.fn(),
	materializeV3ProjectionsBulk: vi.fn(),
}));

import {
	approveV3Master,
	executeV3Assistant,
	fetchV3CopyRegisterLandbank,
	fetchV3CopyRegisterProviderStatus,
	fetchV3ProductionCapacity,
	fetchV3ProductTruth,
	materializeV3Projection,
	materializeV3ProjectionsBulk,
	planV3Assistant,
	regenerateV3Component,
	setupV3Campaign,
	type V3LandbankItem,
	type V3ProductionCapacity,
} from "../api/storyboardLandbankV3Round2";
import { fetchProductDetail } from "../api/products";
import type { Product } from "../types";

const mockedProductDetail = vi.mocked(fetchProductDetail);
const mockedStatus = vi.mocked(fetchV3CopyRegisterProviderStatus);
const mockedPlan = vi.mocked(planV3Assistant);
const mockedExecute = vi.mocked(executeV3Assistant);
const mockedLandbank = vi.mocked(fetchV3CopyRegisterLandbank);
const mockedTruth = vi.mocked(fetchV3ProductTruth);
const mockedCapacity = vi.mocked(fetchV3ProductionCapacity);
const mockedApprove = vi.mocked(approveV3Master);
const mockedSetup = vi.mocked(setupV3Campaign);
const mockedRegenerate = vi.mocked(regenerateV3Component);
const mockedMaterialize = vi.mocked(materializeV3Projection);
const mockedMaterializeBulk = vi.mocked(materializeV3ProjectionsBulk);

function makeItem(overrides: { status?: string; hardPass?: boolean; masterId?: string } = {}): V3LandbankItem {
	return {
		master: {
			master_id: overrides.masterId ?? "master-v3",
			revision: 1,
			product_id: "p1",
			formula: { formula_id: "PAS", formula_version: "pas.v1" },
			angle: { entity_id: "angle-v3", revision: 1 },
			storyline_family: { entity_id: "family-v3", revision: 1 },
			stages: [
				{ stage_key: "problem", formula_stage_key: "problem", semantic_class: "HOOK", authored_text: "Want a lighter routine?" },
				{ stage_key: "cta", formula_stage_key: "cta", semantic_class: "CTA", authored_text: "Start your routine today." },
			],
			status: overrides.status ?? "VALIDATED",
			source: "ROUND2",
			exact_content_digest: "a".repeat(64),
			word_count: 12,
			resolved_component_refs: [{ entity_id: "component-v3", revision: 1 }],
		},
		projections: [8, 16, 24].map((duration) => ({
			projection_id: `projection-${duration}`,
			revision: 1,
			target_duration_seconds: duration,
			exact_resolved_dialogue: "Want a lighter routine? Start today.",
			derivation_source: "DETERMINISTIC",
			status: "VALIDATED",
			per_block_word_budgets: [12],
		})),
		quality: {
			hard_pass: overrides.hardPass ?? true,
			formula_valid: overrides.hardPass ?? true,
			evidence_valid: overrides.hardPass ?? true,
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
	};
}

const approvedItem: V3LandbankItem = {
	...makeItem({ status: "APPROVED", masterId: "master-approved" }),
	approval_receipt: { receipt_id: "receipt-approved" },
	v2_materialization: "PARTIALLY_MATERIALIZED",
	p6_status: "NOT_ALLOCATED",
	projections: [
		{ projection_id: "proj-mat", revision: 1, target_duration_seconds: 8, exact_resolved_dialogue: "Ready copy.", derivation_source: "DETERMINISTIC", status: "APPROVED", per_block_word_budgets: [12], materialization: { status: "MATERIALIZED", link_id: "link-mat", v2_blueprint_id: "bp-mat", v2_blueprint_revision: 1 } },
		{ projection_id: "proj-stale", revision: 1, target_duration_seconds: 16, exact_resolved_dialogue: "Stale copy.", derivation_source: "DETERMINISTIC", status: "APPROVED", per_block_word_budgets: [12], materialization: { status: "STALE", link_id: "link-stale", reason: "PRODUCT_TRUTH_ADVANCED" } },
		{ projection_id: "proj-fresh", revision: 1, target_duration_seconds: 24, exact_resolved_dialogue: "Fresh copy.", derivation_source: "DETERMINISTIC", status: "APPROVED", per_block_word_budgets: [12], materialization: { status: "NOT_MATERIALIZED", link_id: null } },
	],
};

function capacityFixture(overrides: Partial<V3ProductionCapacity> = {}): V3ProductionCapacity {
	return { product_id: "p1", semantic_capacity: 0, projection_capacity: 0, executable_copy_capacity: 0, production_capacity: 0, stale_copy_count: 0, production_capacity_note: "note", ...overrides };
}

function landbankResponse(items: V3LandbankItem[]) {
	return { source: "V3_COPY_REGISTER" as const, product_id: "p1", items, total: items.length, limit: 50, offset: 0, has_more: false, provider_calls: 0, v2_mixed: false as const, full_storyboard_first: true as const };
}

function planResponse() {
	return {
		plan: {
			plan_id: "plan-v3",
			run_id: "run-v3",
			product_id: "p1",
			recipe: { entity_id: "recipe-v3", revision: 1 },
			formula: { formula_id: "PAS", formula_version: "pas.v1" },
			mode: "CREATE" as const,
			target_counts: { HOOK: 1 },
			gaps: [{ semantic_class: "HOOK" as const, current_count: 0, target_count: 1, gap_count: 1, reason: "target" }],
			target_durations_seconds: [8, 16, 24],
			wps_mode: "SAFE" as const,
			provider: { lane: "text_assist" as const, status: "NOT_CONFIGURED", configured: false, provider_id: null, model_id: null, execution_enabled: false, provider_calls: 0, credit_spend: 0, fake_provider_allowed: true },
			prompt_version: "v1",
			prompt_digest: "b".repeat(64),
			estimated_provider_calls: 1,
			estimated_output_tokens: 540,
			estimated_credit_spend: 0,
			max_proposals: 1,
			evidence_fact_ids: ["fact:p1:benefit:0"],
			explicit_execute_required: true as const,
			created_at: "2026-08-17T00:00:00Z",
			created_by: "operator",
		},
		provider_calls: 0,
		credit_spend: 0,
	};
}

function renderAt(path: string) {
	return render(
		<MemoryRouter initialEntries={[path]}>
			<StoryboardLandbankV3Page />
		</MemoryRouter>,
	);
}

describe("Copywriting Landbank operator wizard", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockNavigate.mockReset();
		mockedStatus.mockResolvedValue({ lane: "text_assist", status: "NOT_CONFIGURED", configured: false, provider_id: null, model_id: null, execution_enabled: false, provider_calls: 0, credit_spend: 0, fake_provider_allowed: true });
		mockedTruth.mockResolvedValue({ product_id: "p1", lineage: { snapshot_status: "APPROVED", snapshot_id: "snap-1", snapshot_version: 5 }, facts: [{ fact_id: "fact-1", fact_kind: "BENEFIT", text: "A lightweight daily routine.", text_digest: "d".repeat(64), approved: true }], fact_count: 1, provider_calls: 0, mutations: 0 });
		mockedCapacity.mockResolvedValue(capacityFixture({ semantic_capacity: 18 }));
		mockedLandbank.mockResolvedValue(landbankResponse([makeItem()]));
		mockedPlan.mockResolvedValue(planResponse());
		mockedExecute.mockResolvedValue({ run_id: "run-v3", plan_id: "plan-v3", status: "EXECUTED", provider: { mode: "FAKE_TEST", provider_id: "fake", model_id: "fixture" }, master: { entity_id: "master-v3", revision: 1 }, projections: [], quality: makeItem().quality, provider_calls: 0, credit_spend: 0, projection_derivation: "DETERMINISTIC" });
		mockedApprove.mockResolvedValue({ receipt: { receipt_id: "receipt-v3" }, master: { ...makeItem().master, status: "APPROVED" }, projections: [...makeItem().projections], automatic_approval: false });
		mockedSetup.mockResolvedValue({ recipe_id: "recipe-resolved", recipe_revision: 1, preset: "FAST54", reused: false, recipe: {} });
		mockedRegenerate.mockResolvedValue({ new_revision: 2, source_revision: 1, component: { entity_id: "component-v3", revision: 2 }, automatic_approval: false, run_id: "run-regen" });
		mockedMaterialize.mockResolvedValue({ projection_id: "proj-fresh", status: "MATERIALIZED", blueprint_status: "PRODUCTION_VALID", blueprint_id: "bp-fresh", revision: 1, link_id: "link-fresh", v2_approval_snapshot_id: "snap-fresh", materialization_digest: "m".repeat(64), idempotent_reuse: false });
		mockedMaterializeBulk.mockResolvedValue({ requested: 1, materialized_count: 1, blocked_count: 0, materialized: [], blocked: [] });
	});

	afterEach(() => cleanup());

	// A + J: Setup exposes only business fields; technical settings live under Advanced.
	it("shows only business fields in Setup and keeps recipe id / WPS under Advanced", async () => {
		renderAt("/creative/storyboard-landbank-v3?product_id=p1&step=SETUP");
		await screen.findByTestId("storyboard-landbank-v3-page");
		expect(screen.getByTestId("v3-goal")).toBeInTheDocument();
		expect(screen.getByTestId("v3-formula")).toBeInTheDocument();
		expect(screen.getByTestId("v3-scale")).toBeInTheDocument();
		expect(screen.getByTestId("v3-target")).toBeInTheDocument();
		// Recipe id and WPS are only inside the Advanced / Technical Details drawer.
		const advanced = screen.getByTestId("v3-setup-technical");
		expect(within(advanced).getByTestId("v3-recipe-id")).toBeInTheDocument();
		expect(within(advanced).getByTestId("v3-wps-mode")).toBeInTheDocument();
	});

	// Task B §5 / Test G (reverse) — the only Copy Authority door from Landbank lives
	// under Advanced and carries the selected product id to the advanced V2 console.
	it("bridges to Copy Authority from Advanced, carrying the product id", async () => {
		renderAt("/creative/storyboard-landbank-v3?product_id=p1&step=SETUP");
		await screen.findByTestId("storyboard-landbank-v3-page");
		const advanced = screen.getByTestId("v3-setup-technical");
		const bridge = within(advanced).getByTestId("v3-open-v2-register");
		expect(bridge).toHaveTextContent(/Open Copy Authority/i);
		expect(bridge).toHaveAttribute("href", "/creative/copy-authority?product_id=p1");
	});

	// B + C: system auto-creates/reuses the recipe and calculates the gap.
	it("creates the recipe and calculates the gap automatically without a raw recipe id", async () => {
		renderAt("/creative/storyboard-landbank-v3?product_id=p1&step=SETUP");
		fireEvent.click(await screen.findByTestId("v3-create-campaign"));
		await waitFor(() => expect(mockedSetup).toHaveBeenCalledWith(expect.objectContaining({ product_id: "p1", preset: "FAST54", formula_id: "PAS", wps_mode: "SWEET" })));
		// Reaching Generate auto-runs the gap plan (no manual "Plan" button).
		await waitFor(() => expect(mockedPlan).toHaveBeenCalledWith(expect.objectContaining({ product_id: "p1", recipe_id: "recipe-resolved" })));
		expect(await screen.findByTestId("v3-generate")).toBeInTheDocument();
	});

	// D + E + F: one primary Generate CTA; no generation before it; no prominent fake control.
	it("has a single Generate CTA, does not generate on load, and hides the fake-provider control", async () => {
		renderAt("/creative/storyboard-landbank-v3?product_id=p1&step=GENERATE");
		await screen.findByTestId("v3-preflight-ready");
		expect(screen.getByTestId("v3-generate")).toBeInTheDocument();
		// No live/fake generation happened just by loading the step.
		expect(mockedExecute).not.toHaveBeenCalled();
		// The fake-provider "test" button from the old UI is not in the primary path.
		expect(screen.queryByTestId("v3-execute-fake")).not.toBeInTheDocument();
		fireEvent.click(screen.getByTestId("v3-generate"));
		// Provider is NOT configured, so the primary CTA routes through the fake lane internally.
		await waitFor(() => expect(mockedExecute).toHaveBeenCalledWith("plan-v3", "FAKE_TEST"));
	});

	it("routes the primary Generate CTA to the live provider when it is configured", async () => {
		mockedStatus.mockResolvedValue({ lane: "text_assist", status: "READY", configured: true, provider_id: "qwen", model_id: "qwen-plus", execution_enabled: true, provider_calls: 0, credit_spend: 0, fake_provider_allowed: false });
		renderAt("/creative/storyboard-landbank-v3?product_id=p1&step=GENERATE");
		fireEvent.click(await screen.findByTestId("v3-generate"));
		await waitFor(() => expect(mockedExecute).toHaveBeenCalledWith("plan-v3", "LIVE_TEXT_ASSIST"));
	});

	// Section 14: fail closed with operator language when Product Truth is missing.
	it("fails closed with an operator message when there is no approved Product Truth", async () => {
		mockedTruth.mockResolvedValue({ product_id: "p1", lineage: {}, facts: [], fact_count: 0, provider_calls: 0, mutations: 0 });
		renderAt("/creative/storyboard-landbank-v3?product_id=p1&step=GENERATE");
		const blocked = await screen.findByTestId("v3-preflight-blocked");
		expect(blocked).toHaveTextContent(/Product Truth/i);
		expect(screen.getByTestId("v3-blocker-action")).toBeInTheDocument();
		// No Generate CTA is offered while blocked.
		expect(screen.queryByTestId("v3-generate")).not.toBeInTheDocument();
		expect(mockedExecute).not.toHaveBeenCalled();
	});

	// Task A: an APPROVED snapshot with facts reads Product Truth READY — the false
	// "no approved Product Truth" (from a zero fact count) must be gone.
	it("reports Product Truth READY (no false 'no approved Product Truth') for an approved snapshot with facts", async () => {
		renderAt("/creative/storyboard-landbank-v3?product_id=p1&step=GENERATE");
		const ready = await screen.findByTestId("v3-preflight-ready");
		expect(ready).toHaveTextContent(/Product Truth/i);
		expect(ready).toHaveTextContent(/READY/i);
		expect(screen.queryByText(/no approved Product Truth/i)).not.toBeInTheDocument();
	});

	// Task A: approved truth + zero evidence facts is an EVIDENCE state, not a
	// "no approved Product Truth" state (Truth approval and evidence are distinct).
	it("shows an evidence blocker (not 'no approved Product Truth') when the approved snapshot has no facts", async () => {
		mockedTruth.mockResolvedValue({ product_id: "p1", lineage: { snapshot_status: "APPROVED", snapshot_id: "s", snapshot_version: 5 }, facts: [], fact_count: 0, provider_calls: 0, mutations: 0 });
		renderAt("/creative/storyboard-landbank-v3?product_id=p1&step=GENERATE");
		const blocked = await screen.findByTestId("v3-preflight-blocked");
		expect(blocked).not.toHaveTextContent(/no approved Product Truth/i);
		expect(blocked).toHaveTextContent(/evidence/i);
		expect(screen.queryByTestId("v3-generate")).not.toBeInTheDocument();
	});

	// Task A: Next Action is blocker-aware — it must never recommend Generate while
	// generation is blocked (e.g. the snapshot is not approved).
	it("recommends resolving the Product-Truth blocker, never Generate, when the snapshot is not approved", async () => {
		mockedTruth.mockResolvedValue({ product_id: "p1", lineage: { snapshot_status: "DRAFT" }, facts: [], fact_count: 0, provider_calls: 0, mutations: 0 });
		renderAt("/creative/storyboard-landbank-v3?product_id=p1");
		const label = await screen.findByTestId("v3-next-action-label");
		expect(label).toHaveTextContent(/Product Truth/i);
		expect(label).not.toHaveTextContent(/Generate/i);
	});

	// G: Review separates PASS vs NEEDS ATTENTION.
	it("separates passed copy from copy that needs attention in Review", async () => {
		mockedLandbank.mockResolvedValue(landbankResponse([
			makeItem({ masterId: "m-pass", hardPass: true }),
			makeItem({ masterId: "m-attn", hardPass: false }),
		]));
		renderAt("/creative/storyboard-landbank-v3?product_id=p1&step=REVIEW");
		await screen.findByTestId("v3-review-summary");
		expect(screen.getByTestId("v3-review-passed")).toHaveTextContent("1");
		expect(screen.getByTestId("v3-review-attention")).toHaveTextContent("1");
		// The needs-attention card explains itself in plain language.
		expect(screen.getAllByTestId("v3-copy-warnings").length).toBeGreaterThan(0);
	});

	// H: approval requires all governed checks; grouped, never auto-checked.
	it("requires all governed checks and groups them, never auto-approving", async () => {
		renderAt("/creative/storyboard-landbank-v3?product_id=p1&step=REVIEW");
		fireEvent.click(await screen.findByTestId("v3-open-approval"));
		const dialog = await screen.findByTestId("v3-approval-dialog");
		// Grouped into operator sections.
		expect(within(dialog).getByText("Content")).toBeInTheDocument();
		expect(within(dialog).getByText("Product safety")).toBeInTheDocument();
		expect(within(dialog).getByText("Production fit")).toBeInTheDocument();
		const approve = screen.getByTestId("v3-approve-master");
		expect(approve).toBeDisabled();
		for (const key of ["semantic_reviewed", "product_truth_reviewed", "formula_reviewed", "evidence_reviewed", "bridge_reviewed", "safety_reviewed", "duration_reviewed"]) {
			fireEvent.click(screen.getByTestId(`v3-check-${key}`));
		}
		expect(approve).toBeEnabled();
		fireEvent.click(approve);
		await waitFor(() => expect(mockedApprove).toHaveBeenCalledWith(expect.objectContaining({ master_id: "master-v3", checklist: expect.objectContaining({ duration_reviewed: true }) })));
	});

	it("regenerates a copy without auto-approval", async () => {
		mockedLandbank.mockResolvedValue(landbankResponse([makeItem()]));
		renderAt("/creative/storyboard-landbank-v3?product_id=p1&step=REVIEW");
		fireEvent.click(await screen.findByTestId("v3-action-regenerate"));
		await waitFor(() => expect(mockedRegenerate).toHaveBeenCalledWith("component-v3", 1, "FAKE_TEST"));
	});

	// I: Production Ready terminology maps to materialization states; read-only on load.
	it("maps materialization to production language and never prepares on load", async () => {
		mockedLandbank.mockResolvedValue(landbankResponse([approvedItem]));
		mockedCapacity.mockResolvedValue(capacityFixture({ semantic_capacity: 1, production_capacity: 1 }));
		renderAt("/creative/storyboard-landbank-v3?product_id=p1&step=PRODUCTION");
		await screen.findByTestId("v3-production-summary");
		expect(screen.getByTestId("v3-prepare-chip-proj-mat")).toHaveTextContent("Production Ready");
		expect(screen.getByTestId("v3-prepare-chip-proj-stale")).toHaveTextContent("Needs Revalidation");
		expect(screen.getByTestId("v3-prepare-chip-proj-fresh")).toHaveTextContent("Needs Preparation");
		// A prepared projection cannot be re-prepared; stale + clean can.
		expect(screen.getByTestId("v3-prepare-proj-mat")).toBeDisabled();
		expect(screen.getByTestId("v3-prepare-proj-stale")).toBeEnabled();
		expect(screen.getByTestId("v3-prepare-proj-fresh")).toBeEnabled();
		expect(mockedMaterialize).not.toHaveBeenCalled();
		expect(mockedMaterializeBulk).not.toHaveBeenCalled();
	});

	it("prepares an approved copy for production, receipt-bound", async () => {
		mockedLandbank.mockResolvedValue(landbankResponse([approvedItem]));
		mockedCapacity.mockResolvedValue(capacityFixture({ semantic_capacity: 1, production_capacity: 1 }));
		renderAt("/creative/storyboard-landbank-v3?product_id=p1&step=PRODUCTION");
		fireEvent.click(await screen.findByTestId("v3-prepare-proj-fresh"));
		await waitFor(() => expect(mockedMaterialize).toHaveBeenCalledWith(expect.objectContaining({ projectionId: "proj-fresh", receiptId: "receipt-approved" })));
	});

	it("hands off to Production Studio carrying the product id", async () => {
		mockedLandbank.mockResolvedValue(landbankResponse([approvedItem]));
		mockedCapacity.mockResolvedValue(capacityFixture({ semantic_capacity: 1, production_capacity: 1 }));
		renderAt("/creative/storyboard-landbank-v3?product_id=p1&step=PRODUCTION");
		fireEvent.click(await screen.findByTestId("v3-open-production-studio"));
		expect(mockNavigate).toHaveBeenCalledWith("/production-studio?product_id=p1");
	});

	// K: deep-link / refresh reconstructs the correct step from backend state.
	it("reconstructs the Production step from approved copy on a bare deep-link", async () => {
		mockedLandbank.mockResolvedValue(landbankResponse([approvedItem]));
		mockedCapacity.mockResolvedValue(capacityFixture({ semantic_capacity: 1, production_capacity: 1 }));
		renderAt("/creative/storyboard-landbank-v3?product_id=p1");
		// No explicit step in the URL — the page derives PRODUCTION from approved supply.
		expect(await screen.findByTestId("v3-production-summary")).toBeInTheDocument();
	});

	it("reconstructs the Review step from reviewable copy on a bare deep-link", async () => {
		mockedLandbank.mockResolvedValue(landbankResponse([makeItem()]));
		renderAt("/creative/storyboard-landbank-v3?product_id=p1");
		expect(await screen.findByTestId("v3-review-summary")).toBeInTheDocument();
	});

	// Regression A: a deep-linked product that sorts outside the first-page catalog
	// window (useProductCatalog(50)) is resolved deterministically by id, not skipped.
	it("deep-links a product outside the first-page catalog window via a by-id fetch", async () => {
		mockedProductDetail.mockResolvedValue({
			id: "p99",
			raw_product_title: "Deep Linked Product",
			product_display_name: "Deep Linked Product",
		} as unknown as Product);
		renderAt("/creative/storyboard-landbank-v3?product_id=p99&step=SETUP");
		await waitFor(() => expect(mockedProductDetail).toHaveBeenCalledWith("p99"));
		// The resolved product becomes the selection (header renders its name) and its
		// Product Truth is loaded — proving it was selected, not silently skipped.
		await waitFor(() =>
			expect(screen.getByTestId("v3-product-name")).toHaveTextContent("Deep Linked Product"),
		);
		await waitFor(() => expect(mockedTruth).toHaveBeenCalledWith("p99"));
	});

	// Regression B: an unresolvable deep-link id surfaces an operator error and never
	// silently selects a different product (no fallback to the in-window product).
	it("does not silently select another product when the deep-linked id is invalid", async () => {
		mockedProductDetail.mockRejectedValue(new Error("404 Not Found"));
		renderAt("/creative/storyboard-landbank-v3?product_id=ghost-id&step=SETUP");
		expect(await screen.findByTestId("v3-error")).toHaveTextContent(
			/couldn't open the copy landbank/i,
		);
		expect(mockedProductDetail).toHaveBeenCalledWith("ghost-id");
		// Nothing was selected: the header keeps the empty-state prompt and the
		// in-window product (p1) was NOT substituted, so no truth load fired.
		expect(screen.getByTestId("v3-product-name")).toHaveTextContent(
			"Select a product to begin.",
		);
		expect(mockedTruth).not.toHaveBeenCalled();
	});
});
