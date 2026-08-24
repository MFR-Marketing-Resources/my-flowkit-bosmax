import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
	approveSelectedProductVisuals,
	fetchProductVisualReadiness,
} from "../../api/productVisualOnboarding";
import type { Product, ProductVisualReadiness } from "../../types";
import ProductVisualReviewDrawer from "./ProductVisualReviewDrawer";

vi.mock("../../api/productVisualOnboarding", async (importOriginal) => {
	const actual = await importOriginal<typeof import("../../api/productVisualOnboarding")>();
	return {
		...actual,
		fetchProductVisualReadiness: vi.fn(),
		approveSelectedProductVisuals: vi.fn(),
	};
});

const product = {
	id: "pending-1",
	source: "MANUAL",
	raw_product_title: "Pending product",
	product_display_name: "Pending product",
	product_short_name: "Pending",
	image_url: "/source.png",
	lifecycle_status: "ACTIVE",
} as Product;

const readiness = {
	product_id: product.id,
	canonical_media_status: "AVAILABLE",
	reference_pack_status: "READY",
	visual_grounding_status: "READY",
	visual_grounding_source: "PRODUCT_SOURCE_MEDIA",
	cutout_status: "PENDING_REVIEW",
	cutout_review_status: "PENDING_REVIEW",
	exact_commerce_status: "CUTOUT_REQUIRED",
	official_visual_status: "NOT_APPROVED",
	candidate_source_kind: "AUTO_GENERATED",
	canonical_cutout_sha256: "a".repeat(64),
	canonical_cutout_media_id: "cutout-media-1",
	visual_lock_updated_at: "2026-08-24T00:00:00Z",
	canonical_source_sha256: "b".repeat(64),
	auto_cutout_preview_url: "/cutout.png",
	original_preview_url: "/source.png",
	blockers: ["OWNER_VISUAL_APPROVAL_REQUIRED"],
	warnings: [],
	provider_operations: 0,
	created_without_credit: true,
	can_prepare_cutout: false,
	can_review_cutout: true,
	can_approve_cutout: true,
	can_rebuild_cutout: false,
	can_open_source: true,
	can_view: true,
} as ProductVisualReadiness;

describe("ProductVisualReviewDrawer", () => {
	beforeEach(() => {
		vi.mocked(fetchProductVisualReadiness).mockResolvedValue(readiness);
		vi.mocked(approveSelectedProductVisuals).mockResolvedValue({
			batch_id: "batch-1",
			status: "COMPLETED",
			all_succeeded: true,
			total_selected: 1,
			approved_count: 1,
			already_approved_count: 0,
			failed_count: 0,
			results: [{ product_id: product.id, status: "APPROVED" }],
			provider_operations: 0,
			created_without_credit: true,
			auto_release: false,
		});
	});

	afterEach(() => {
		cleanup();
		vi.resetAllMocks();
	});

	it("loads one product, keeps technical evidence collapsed, and binds approval to the read candidate", async () => {
		render(<ProductVisualReviewDrawer product={product} onClose={vi.fn()} />);

		expect(await screen.findByTestId("product-visual-review-drawer")).toBeInTheDocument();
	expect(screen.getByAltText("Pending product original source")).toHaveAttribute("src", "/source.png");
	expect(screen.getByAltText("Pending product prepared cutout")).toHaveAttribute("src", "/cutout.png");
		expect(screen.getByTestId("visual-review-technical-evidence")).not.toHaveAttribute("open");
		fireEvent.click(screen.getByText("Technical evidence"));
		expect(screen.getByTestId("visual-review-technical-evidence")).toHaveTextContent("cutout-media-1");
	});

	it("requires all exact confirmations before the single governed approval call", async () => {
		render(<ProductVisualReviewDrawer product={product} onClose={vi.fn()} />);
		await screen.findByTestId("visual-review-approval");

		const approve = screen.getByTestId("visual-review-approve");
		expect(approve).toBeDisabled();
		for (const label of [
			"Exact product identity",
			"Label / logo",
			"Geometry / scale",
			"Product only / no unrelated objects",
		]) {
			fireEvent.click(screen.getByLabelText(label));
		}
		fireEvent.click(approve);

		await waitFor(() => expect(approveSelectedProductVisuals).toHaveBeenCalledTimes(1));
		expect(vi.mocked(approveSelectedProductVisuals).mock.calls[0][0]).toMatchObject({
			items: [
				{
					product_id: product.id,
					candidate_sha256: "a".repeat(64),
					candidate_media_id: "cutout-media-1",
					expected_lock_updated_at: "2026-08-24T00:00:00Z",
					candidate_source_kind: "AUTO_GENERATED",
				},
			],
			review_note: "Owner visual approval pilot",
		});
	});
});
