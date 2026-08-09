import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import ProductVisualReadinessPanel from "./ProductVisualReadinessPanel";
import type { ProductVisualReadiness } from "../../types";

const pending: ProductVisualReadiness = {
	product_id: "product-1",
	canonical_media_status: "AVAILABLE",
	reference_pack_status: "PENDING_REVIEW",
	visual_grounding_status: "VISUAL_GROUNDING_READY",
	visual_grounding_source: "PRODUCT_ROW_LOCAL_PATH",
	cutout_status: "PENDING_REVIEW",
	cutout_review_status: "PENDING_REVIEW",
	exact_commerce_status: "EXACT_COMMERCE_REVIEW_REQUIRED",
	cutout_preview_available: true,
	blockers: [],
	warnings: ["EXACT_COMMERCE_REQUIRES_EXPLICIT_HUMAN_APPROVAL"],
	provider_operations: 0,
	created_without_credit: true,
	can_prepare_cutout: false,
	can_review_cutout: true,
	can_approve_cutout: true,
	can_rebuild_cutout: true,
	can_open_source: true,
	can_view: true,
};

describe("ProductVisualReadinessPanel", () => {
	afterEach(() => cleanup());

	it("shows the four visual readiness gates and keeps approval explicit", () => {
		render(
			<ProductVisualReadinessPanel
				productId="product-1"
				productSourceUrl="https://example.test/product"
				readiness={pending}
				showApprovalForm
			/>,
		);

		expect(screen.getByTestId("product-visual-readiness")).toBeInTheDocument();
		expect(screen.getByText("PRODUCT VISUAL READINESS")).toBeInTheDocument();
		expect(screen.getByText("Reference")).toBeInTheDocument();
		expect(screen.getByText("Cutout")).toBeInTheDocument();
		expect(screen.getByText("Visual Ready")).toBeInTheDocument();
		expect(screen.getByText("Exact Commerce")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Canva Cutout" })).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Approve Exact Cutout" })).toBeDisabled();
		expect(screen.getByText("Open Source")).toHaveAttribute("href", "https://example.test/product");
	});
});
