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

const compactCanvaPending: ProductVisualReadiness = {
	...pending,
	can_upload_manual_cutout: true,
	can_start_canva_cutout: true,
	canva_cutout_workflow: {
		current_stage: "CANVA_PRO_REQUIRED",
		attempt_count: 0,
		alpha_verified: false,
		human_review_status: "NOT_STARTED",
		preflight: {},
	},
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

	it("keeps the compact Canva workflow bounded and readable", () => {
		render(
			<ProductVisualReadinessPanel
				productId="product-1"
				readiness={compactCanvaPending}
				compact
			/>,
		);

		const panel = screen.getByTestId("product-visual-readiness");
		const workflow = screen.getByTestId("canva-cutout-workflow");
		const workflowGrids = workflow.querySelectorAll("div.grid");

		expect(panel).toHaveClass("min-w-0", "max-w-full", "overflow-hidden");
		expect(workflowGrids).toHaveLength(2);
		expect(workflowGrids[0]).toHaveClass("grid-cols-1", "sm:grid-cols-2");
		expect(workflowGrids[1]).toHaveClass("grid-cols-1", "sm:grid-cols-2");
	});
});
