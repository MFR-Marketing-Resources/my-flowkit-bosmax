import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
	closeImportSoftReconciliation,
	fetchImportSoftReconciliationPreview,
	fetchProductRegistry,
	fetchProductStrategyTypeRegistry,
} from "../../api/products";
import { fetchProductVisualReviewQueue } from "../../api/productVisualOnboarding";
import AllProductsTab from "./AllProductsTab";

vi.mock("../../api/products", async (importOriginal) => {
	const actual = await importOriginal<typeof import("../../api/products")>();
	return {
		...actual,
		fetchProductRegistry: vi.fn(),
		fetchProductStrategyTypeRegistry: vi.fn(),
		fetchImportSoftReconciliationPreview: vi.fn(),
		closeImportSoftReconciliation: vi.fn(),
	};
});

vi.mock("../../api/productVisualOnboarding", async (importOriginal) => {
	const actual = await importOriginal<typeof import("../../api/productVisualOnboarding")>();
	return {
		...actual,
		fetchProductVisualReviewQueue: vi.fn(),
		approveSelectedProductVisuals: vi.fn(),
	};
});

const emptyVisualReviewQueue = {
	cohort: "PENDING_VISUAL_REVIEW",
	items: [],
	total_count: 0,
	returned_count: 0,
	limit: 25,
	offset: 0,
	has_pagination: false,
	cohort_counts: {
		PENDING_VISUAL_REVIEW: 280,
		SOURCE_REUPLOAD_REQUIRED: 11,
		BROKEN_APPROVED_VISUAL: 16,
	},
	selection_policy: "EXPLICIT_VISIBLE_PAGE_ONLY",
	metadata_read_policy: "BATCHED_VISUAL_READ_MODEL",
	provider_operations: 0,
	created_without_credit: true,
} as never;

describe("AllProductsTab visual surface", () => {
	beforeEach(() => {
		vi.mocked(fetchProductVisualReviewQueue).mockResolvedValue(emptyVisualReviewQueue);
		vi.mocked(fetchProductRegistry).mockResolvedValue({
			items: [],
			total_count: 0,
		} as never);
		vi.mocked(fetchProductStrategyTypeRegistry).mockResolvedValue({
			items: [],
			clusters: [],
		} as never);
		vi.mocked(fetchImportSoftReconciliationPreview).mockResolvedValue({
			safe_candidate_count: 0,
			review_required_count: 0,
			hub_claim_conflict_open_count: 0,
			ineligible_count: 0,
			expected_safe_count: 549,
			matches_expected_safe_count: false,
			reason_code: "SAFE_IMPORT_SOFT_FIELD_RECONCILIATION",
			policy: {},
		} as never);
		vi.mocked(closeImportSoftReconciliation).mockResolvedValue({
			status: "COMPLETED",
			success_count: 0,
			failure_count: 0,
			candidate_count: 0,
		} as never);
	});
	afterEach(() => {
		cleanup();
	});

	it("keeps the catalog default and opens the owner review workspace without exposing bulk cutout controls", async () => {
		render(<AllProductsTab />);

		expect(screen.getByTestId("workspace-product-catalog")).toHaveAttribute("aria-selected", "true");
		expect(screen.queryByTestId("product-visual-review-queue")).not.toBeInTheDocument();
		fireEvent.click(screen.getByTestId("workspace-visual-review"));
		expect(await screen.findByTestId("product-visual-review-queue")).toBeInTheDocument();
		expect(screen.getByTestId("workspace-visual-review")).toHaveTextContent("280");
		expect(screen.getByText("Owner Visual Review Queue")).toBeInTheDocument();
		expect(screen.queryByText("All Products")).not.toBeInTheDocument();
		const bodyText = document.body.textContent ?? "";
		expect(bodyText).not.toMatch(/bulk cutout|cutout queue|run all|queue all|pause all|resume all|cancel all/i);
	});

	it("shows the standard canvas note on each product visual row", async () => {
		vi.mocked(fetchProductRegistry).mockResolvedValueOnce({
			items: [
				{
					id: "product-1",
					source: "MANUAL",
					raw_product_title: "Canvas note product",
					product_display_name: "Canvas note product",
					product_short_name: "Canvas note",
					category: null,
					subcategory: null,
					type: null,
					shop_name: null,
					price: null,
					currency: null,
					commission_amount: null,
					commission_rate: null,
					image_url: null,
					lifecycle_status: "ACTIVE",
					visual_canvas_width: 1000,
					visual_canvas_height: 1000,
					visual_readiness: {
						visual_canvas_label: "1000×1000 px",
						visual_canvas_requirement: "Manual / Canva cutouts must be transparent PNG files on an exact 1000x1000 px canvas.",
						canonical_media_status: "AVAILABLE",
						cutout_status: "NOT_PREPARED",
						cutout_review_status: "NOT_STARTED",
						visual_grounding_status: "VISUAL_GROUNDING_READY_FALLBACK",
						can_start_canva_cutout: true,
					},
				} as never,
			],
			total_count: 1,
		} as never);

		render(<AllProductsTab />);

		expect(await screen.findByTestId("table-visual-canvas-requirement")).toHaveTextContent(
			"Canvas 1000×1000 px",
		);
	});

	it("shows the approved cutout in Visual while keeping the source thumbnail in Image", async () => {
		vi.mocked(fetchProductRegistry).mockResolvedValueOnce({
			items: [
				{
					id: "approved-manual-product",
					source: "MANUAL",
					raw_product_title: "Approved manual product",
					product_display_name: "Approved manual product",
					product_short_name: "Approved manual",
					image_url: "/images/original-source.png",
					lifecycle_status: "ACTIVE",
					visual_readiness: {
						visual_canvas_label: "1000×1000 px",
						canonical_media_status: "AVAILABLE",
						cutout_status: "APPROVED",
						cutout_review_status: "APPROVED",
						visual_grounding_status: "VISUAL_GROUNDING_READY",
						active_visual_source: "APPROVED_MANUAL_CANONICAL_CUTOUT",
						original_preview_url: "/api/product-visual-onboarding/approved-manual-product/cutout/preview/original",
						original_display_url: "/images/original-source.png",
						active_cutout_preview_url: "/api/product-visual-onboarding/approved-manual-product/cutout/preview/active",
						manual_cutout_preview_url: "/api/product-visual-onboarding/approved-manual-product/cutout/preview/manual",
						current_system_visual: {
							card: "MANUAL_CUTOUT",
							label: "Manual / Canva Cutout",
							status: "OFFICIAL",
						},
					},
				} as never,
			],
			total_count: 1,
		} as never);

		render(<AllProductsTab />);

		const visualSummary = await screen.findByTestId("table-visual-summary");
		expect(visualSummary.querySelector("img")).toHaveAttribute(
			"src",
			"/api/product-visual-onboarding/approved-manual-product/cutout/preview/active",
		);
		expect(document.querySelectorAll("img")[0]).toHaveAttribute(
			"src",
			"/images/original-source.png",
		);
	});

	it("keeps the original source visible until a cutout candidate is officially approved", async () => {
		vi.mocked(fetchProductRegistry).mockResolvedValueOnce({
			items: [
				{
					id: "pending-manual-product",
					source: "MANUAL",
					raw_product_title: "Pending manual product",
					product_display_name: "Pending manual product",
					product_short_name: "Pending manual",
					image_url: "/images/original-source.png",
					lifecycle_status: "ACTIVE",
					visual_readiness: {
						visual_canvas_label: "1000×1000 px",
						canonical_media_status: "AVAILABLE",
						cutout_status: "PENDING_REVIEW",
						cutout_review_status: "PENDING_REVIEW",
						visual_grounding_status: "VISUAL_GROUNDING_READY_FALLBACK",
						active_visual_source: "SAME_PRODUCT_TRUSTED_SOURCE",
						original_preview_url: "/api/product-visual-onboarding/pending-manual-product/cutout/preview/original",
						original_display_url: "/images/original-source.png",
						active_cutout_preview_url: "/api/product-visual-onboarding/pending-manual-product/cutout/preview/active",
						manual_cutout_preview_url: "/api/product-visual-onboarding/pending-manual-product/cutout/preview/manual",
						current_system_visual: {
							card: "ORIGINAL_SOURCE",
							label: "Original Source",
							status: "ORIGINAL_FALLBACK",
						},
					},
				} as never,
			],
			total_count: 1,
		} as never);

		render(<AllProductsTab />);

		const visualSummary = await screen.findByTestId("table-visual-summary");
		expect(visualSummary.querySelector("img")).toHaveAttribute(
			"src",
			"/api/product-visual-onboarding/pending-manual-product/cutout/preview/original",
		);
	});
});


describe("All Products Product Truth operator surface", () => {
	afterEach(() => {
		cleanup();
		vi.resetAllMocks();
	});

	beforeEach(() => {
		vi.mocked(fetchProductVisualReviewQueue).mockResolvedValue(emptyVisualReviewQueue);
		vi.mocked(fetchImportSoftReconciliationPreview).mockResolvedValue({
			safe_candidate_count: 549,
			review_required_count: 6,
			hub_claim_conflict_open_count: 20,
			ineligible_count: 0,
			expected_safe_count: 549,
			matches_expected_safe_count: true,
			reason_code: "SAFE_IMPORT_SOFT_FIELD_RECONCILIATION",
			policy: { approves_import_into_product_truth: false, deletes_history: false },
		} as never);
		vi.mocked(closeImportSoftReconciliation).mockResolvedValue({
			status: "COMPLETED",
			success_count: 549,
			failure_count: 0,
			candidate_count: 549,
		} as never);

		vi.mocked(fetchProductStrategyTypeRegistry).mockResolvedValue({
			items: [],
			clusters: [],
		} as never);
	});

	const baseItem = {
		id: "sambal",
		source: "MANUAL",
		raw_product_title: "Sambal Nyet Berapi by Khairulaming",
		product_display_name: "Sambal Nyet Berapi by Khairulaming",
		product_short_name: "Sambal Nyet",
		lifecycle_status: "ACTIVE",
		product_truth_status: "APPROVED",
		product_truth_update_pending: false,
		product_truth_action_label: "View Product Truth",
		product_truth_approved_snapshot_version: 3,
		open_review_draft: null,
		visual_readiness: {
			visual_canvas_label: "1000×1000 px",
			canonical_media_status: "AVAILABLE",
			cutout_status: "NOT_PREPARED",
			cutout_review_status: "NOT_STARTED",
			visual_grounding_status: "VISUAL_GROUNDING_READY_FALLBACK",
			can_start_canva_cutout: true,
		},
	};

	it("renders Product Truth badges, summary, filter, and keeps Review Draft separate", async () => {
		vi.mocked(fetchProductRegistry).mockResolvedValue({
			items: [
				baseItem as never,
				{
					...baseItem,
					id: "pending",
					raw_product_title: "Pending update product",
					product_display_name: "Pending update product",
					product_truth_update_pending: true,
					product_truth_action_label: "Review Update",
				} as never,
				{
					...baseItem,
					id: "review",
					raw_product_title: "Needs review product",
					product_display_name: "Needs review product",
					product_truth_status: "NEEDS_REVIEW",
					product_truth_action_label: "Review Product Truth",
					open_review_draft: {
						draft_id: "d1",
						review_status: "READY_FOR_REVIEW",
					},
				} as never,
			],
			total_count: 3,
			product_truth_summary: {
				APPROVED: 2,
				NEEDS_REVIEW: 1,
				ACTION_REQUIRED: 0,
				NOT_STARTED: 0,
				UPDATE_PENDING: 1,
			},
		} as never);

		render(<AllProductsTab />);

		expect(await screen.findByTestId("product-truth-summary")).toBeInTheDocument();
		expect(screen.getByTestId("product-truth-summary-approved")).toHaveTextContent("2");
		expect(screen.getByTestId("product-truth-summary-update-pending")).toHaveTextContent(
			"Update Pending: 1",
		);
		expect(screen.getByTestId("product-truth-filter")).toBeInTheDocument();
		expect(screen.getByRole("columnheader", { name: "Product Truth" })).toBeInTheDocument();
		expect(screen.getByRole("columnheader", { name: "Review Draft" })).toBeInTheDocument();
		expect(screen.queryByRole("columnheader", { name: /^Draft$/i })).not.toBeInTheDocument();

		const statuses = await screen.findAllByTestId("product-truth-status");
		expect(statuses.some((el) => el.textContent?.includes("APPROVED"))).toBe(true);
		expect(statuses.some((el) => el.textContent?.includes("NEEDS REVIEW"))).toBe(true);
		expect(screen.getByTestId("product-truth-update-pending")).toHaveTextContent(
			"Update pending",
		);
	});

	it("Review Draft cell surfaces the NEEDS_REVISION blocker reason (claim tokens)", async () => {
		vi.mocked(fetchProductRegistry).mockResolvedValue({
			items: [
				{
					...baseItem,
					id: "blocked",
					raw_product_title: "Claim blocked product",
					product_display_name: "Claim blocked product",
					open_review_draft: {
						draft_id: "d-blocked",
						review_status: "NEEDS_REVISION",
						claim_gate: "CLAIM_BLOCKED",
						claim_tokens: ["rawat", "penyakit"],
						readiness_status: "CLAIM_BLOCKED",
					},
				} as never,
			],
			total_count: 1,
			product_truth_summary: {
				APPROVED: 1,
				NEEDS_REVIEW: 0,
				ACTION_REQUIRED: 0,
				NOT_STARTED: 0,
				UPDATE_PENDING: 0,
			},
		} as never);

		render(<AllProductsTab />);

		const reason = await screen.findByTestId("review-draft-blocker-reason");
		expect(reason).toHaveTextContent("Claim: rawat, penyakit");
	});

	it("maps Product Truth row action labels and opens Intelligence via callback", async () => {
		const onOpen = vi.fn();
		vi.mocked(fetchProductRegistry).mockResolvedValue({
			items: [
				{
					...baseItem,
					id: "sambal",
					product_truth_action_label: "View Product Truth",
				} as never,
			],
			total_count: 1,
			product_truth_summary: {
				APPROVED: 1,
				NEEDS_REVIEW: 0,
				ACTION_REQUIRED: 0,
				NOT_STARTED: 0,
				UPDATE_PENDING: 0,
			},
		} as never);

		render(<AllProductsTab onOpenProduct={onOpen} />);

		const action = await screen.findByTestId("table-product-truth-action");
		expect(action).toHaveTextContent("View Product Truth");
		fireEvent.click(action);
		expect(onOpen).toHaveBeenCalledWith("sambal", { tab: "INTELLIGENCE" });

		fireEvent.click(screen.getByTestId("table-open-product"));
		expect(onOpen).toHaveBeenCalledWith("sambal");
	});

	it("applies Product Truth filter when a summary card is clicked", async () => {
		vi.mocked(fetchProductRegistry).mockResolvedValue({
			items: [baseItem as never],
			total_count: 1,
			product_truth_summary: {
				APPROVED: 1,
				NEEDS_REVIEW: 0,
				ACTION_REQUIRED: 0,
				NOT_STARTED: 0,
				UPDATE_PENDING: 0,
			},
		} as never);

		render(<AllProductsTab />);
		await screen.findByTestId("product-truth-summary");
		vi.mocked(fetchProductRegistry).mockClear();
		fireEvent.click(screen.getByTestId("product-truth-summary-approved"));
		await vi.waitFor(() => {
			expect(fetchProductRegistry).toHaveBeenCalled();
		});
		const lastCall = vi.mocked(fetchProductRegistry).mock.calls.at(-1)?.[0] as {
			productTruth?: string;
		};
		expect(lastCall?.productTruth).toBe("APPROVED");
	});

	it("Review Draft cell shows em dash when open_review_draft is null (terminal history hidden)", async () => {
		vi.mocked(fetchProductRegistry).mockResolvedValue({
			items: [
				{
					...baseItem,
					id: "d2f8fd58-437b-4447-8730-694b782eef17",
					raw_product_title: "Sambal Nyet Berapi by Khairulaming",
					product_display_name: "Sambal Nyet Berapi by Khairulaming",
					product_truth_status: "APPROVED",
					product_truth_update_pending: false,
					product_truth_action_label: "View Product Truth",
					open_review_draft: null,
				} as never,
			],
			total_count: 1,
			product_truth_summary: {
				APPROVED: 1,
				NEEDS_REVIEW: 0,
				ACTION_REQUIRED: 0,
				NOT_STARTED: 0,
				UPDATE_PENDING: 0,
			},
		} as never);

		render(<AllProductsTab />);
		expect(await screen.findByText("Sambal Nyet Berapi by Khairulaming")).toBeInTheDocument();
		expect(screen.getByRole("columnheader", { name: "Review Draft" })).toBeInTheDocument();
		expect(screen.queryByText("READY FOR REVIEW")).not.toBeInTheDocument();
	});


	it("shows import soft reconciliation panel with safe/review/claim counts", async () => {
		render(<AllProductsTab />);
		expect(await screen.findByTestId("import-soft-reconciliation-panel")).toBeInTheDocument();
		expect(screen.getByTestId("import-soft-safe-count")).toHaveTextContent("549");
		expect(screen.getByTestId("import-soft-review-count")).toHaveTextContent("6");
		expect(screen.getByTestId("import-soft-claim-count")).toHaveTextContent("20");
		expect(screen.getByTestId("import-soft-close-button")).toBeEnabled();
	});

});
