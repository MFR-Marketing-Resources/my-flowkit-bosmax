import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
	approveSelectedProductVisuals,
	fetchProductVisualReviewQueue,
	type ProductVisualReviewQueueItem,
	type ProductVisualReviewQueueResponse,
} from "../../api/productVisualOnboarding";
import ProductVisualReviewQueue from "./ProductVisualReviewQueue";

vi.mock("../../api/productVisualOnboarding", async (importOriginal) => {
	const actual = await importOriginal<typeof import("../../api/productVisualOnboarding")>();
	return {
		...actual,
		fetchProductVisualReviewQueue: vi.fn(),
		approveSelectedProductVisuals: vi.fn(),
	};
});

const pendingRow: ProductVisualReviewQueueItem = {
	product_id: "pending-1",
	product_name: "Recovered Product One",
	raw_product_title: "Recovered Product One",
	lifecycle_status: "ACTIVE",
	cohort: "PENDING_VISUAL_REVIEW",
	review_status: "PENDING_REVIEW",
	source_status: "AVAILABLE",
	cutout_status: "PENDING_REVIEW",
	candidate_status: "PENDING_REVIEW",
	candidate_source_kind: "AUTO_GENERATED",
	candidate_sha256: "a".repeat(64),
	candidate_media_id: "cutout-media-1",
	expected_lock_updated_at: "v1",
	expected_source_sha256: "b".repeat(64),
	expected_cutout_sha256: "a".repeat(64),
	candidate_preview_url: "/cutout-1.png",
	original_source_url: "/source-1.png",
	original_source_trust_status: "TRUSTED",
	original_source_provenance: { canonical_source_type: "PRODUCT_SOURCE_MEDIA" },
	historical_evidence_count: 0,
	missing_canonical_bytes: [],
	current_system_visual: { card: "ORIGINAL_SOURCE", label: "Original Source", status: "ORIGINAL_FALLBACK" },
	current_system_visual_url: "/source-1.png",
	blocker_state: ["OWNER_VISUAL_APPROVAL_REQUIRED"],
	release_status: "HIDDEN",
	readiness_impact: {
		current_exact_commerce_status: "CUTOUT_REQUIRED",
		current_visual_source_status: "AVAILABLE",
		after_visual_approval_exact_commerce_status: "EXACT_COMMERCE_CUTOUT_READY",
		release_decision: "OWNER_RELEASE_REVIEW_REQUIRED",
		auto_release: false,
	},
	actions: { can_approve_selected: true, can_reupload_source: false, can_recover_broken_visual: false },
	provider_operations: 0,
};

const baseQueue: ProductVisualReviewQueueResponse = {
	cohort: "PENDING_VISUAL_REVIEW",
	items: [pendingRow],
	total_count: 1,
	returned_count: 1,
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
};

describe("ProductVisualReviewQueue", () => {
	beforeEach(() => {
		vi.mocked(fetchProductVisualReviewQueue).mockResolvedValue(baseQueue);
		vi.mocked(approveSelectedProductVisuals).mockResolvedValue({
			batch_id: "batch-1",
			status: "COMPLETED",
			all_succeeded: true,
			total_selected: 1,
			approved_count: 1,
			already_approved_count: 0,
			failed_count: 0,
			results: [{ product_id: "pending-1", status: "APPROVED" }],
			provider_operations: 0,
			created_without_credit: true,
			auto_release: false,
		});
	});

	afterEach(() => {
		cleanup();
		vi.resetAllMocks();
	});

	it("renders side-by-side evidence with no default selection and exact cohorts", async () => {
		render(<ProductVisualReviewQueue />);

		expect(await screen.findByTestId("product-visual-review-queue")).toBeInTheDocument();
		expect(screen.getByText("Recovered Product One")).toBeInTheDocument();
		expect(screen.getByAltText("Recovered Product One original source")).toHaveAttribute("src", "/source-1.png");
		expect(screen.getByAltText("Recovered Product One prepared cutout")).toHaveAttribute("src", "/cutout-1.png");
		expect(screen.getByTestId("visual-review-cohort-PENDING_VISUAL_REVIEW")).toHaveTextContent("280");
		expect(screen.getByTestId("visual-review-cohort-SOURCE_REUPLOAD_REQUIRED")).toHaveTextContent("11");
		expect(screen.getByTestId("visual-review-cohort-BROKEN_APPROVED_VISUAL")).toHaveTextContent("16");
		expect(screen.getByRole("checkbox", { name: "Select Recovered Product One" })).not.toBeChecked();
	});

	it("keeps technical evidence collapsed while preserving safe responsive wrapping", async () => {
		render(<ProductVisualReviewQueue />);

		const details = await screen.findByTestId("visual-review-technical-pending-1");
		expect(details).not.toHaveAttribute("open");
		expect(details).toHaveClass("min-w-0", "max-w-full");
		expect(screen.getByTestId("visual-review-previews-pending-1")).toHaveClass("min-w-0", "grid-cols-1", "xl:grid-cols-2");
		expect(details).toHaveTextContent("a".repeat(64));

		fireEvent.click(screen.getByText("Technical evidence"));
		expect(details).toHaveAttribute("open");
		expect(details).toHaveTextContent("cutout-media-1");
	});

	it("approves only explicitly selected rows after exact confirmation", async () => {
		render(<ProductVisualReviewQueue />);
		const checkbox = await screen.findByRole("checkbox", { name: "Select Recovered Product One" });
		fireEvent.click(checkbox);
		fireEvent.click(screen.getByTestId("approve-selected-visuals"));

		expect(await screen.findByTestId("visual-review-confirmation")).toHaveTextContent("pending-1");
		expect(screen.getByTestId("visual-review-confirmation")).toHaveTextContent("Recovered Product One");
		for (const label of [
			"Exact product identity",
			"Label / logo",
			"Geometry / scale",
			"Product only / no unrelated objects",
		]) {
			fireEvent.click(screen.getByLabelText(label));
		}
		fireEvent.click(screen.getByRole("button", { name: "Confirm approve selected" }));

		await waitFor(() => expect(approveSelectedProductVisuals).toHaveBeenCalledTimes(1));
		expect(vi.mocked(approveSelectedProductVisuals).mock.calls[0][0]).toMatchObject({
			items: [{
				product_id: "pending-1",
				candidate_sha256: "a".repeat(64),
				candidate_media_id: "cutout-media-1",
				expected_lock_updated_at: "v1",
			}],
			review_note: "Owner visual recovery review",
		});
	});

	it("keeps source recovery as a separate cohort and routes to the existing visual authority", async () => {
		vi.mocked(fetchProductVisualReviewQueue).mockImplementation(async (cohort) => ({
			...baseQueue,
			cohort,
			items: [],
		}));
		const onOpenProduct = vi.fn();
		render(<ProductVisualReviewQueue onOpenProduct={onOpenProduct} />);
		fireEvent.click(await screen.findByTestId("visual-review-cohort-SOURCE_REUPLOAD_REQUIRED"));
		await waitFor(() => expect(fetchProductVisualReviewQueue).toHaveBeenLastCalledWith("SOURCE_REUPLOAD_REQUIRED", 25, 0, expect.any(AbortSignal)));
		expect(screen.queryByTestId("approve-selected-visuals")).not.toBeInTheDocument();
	});
});
