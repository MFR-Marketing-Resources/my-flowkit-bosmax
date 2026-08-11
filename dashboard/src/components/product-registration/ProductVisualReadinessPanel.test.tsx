import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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

const missingSource: ProductVisualReadiness = {
	...pending,
	canonical_media_status: "MISSING",
	visual_grounding_status: "VISUAL_GROUNDING_BLOCKED",
	visual_grounding_source: "SOURCE_NOT_RESOLVED",
	cutout_status: "NOT_PREPARED",
	auto_cutout_status: "NOT_PREPARED",
	manual_cutout_status: "NOT_UPLOADED",
	active_visual_source: "BLOCKED",
	original_preview_url: null,
	auto_cutout_preview_url: null,
	manual_cutout_preview_url: null,
	blockers: ["TRUSTED_SAME_PRODUCT_SOURCE_REQUIRED"],
	can_prepare_cutout: false,
	can_review_cutout: false,
	can_approve_cutout: false,
	can_rebuild_cutout: false,
	can_upload_manual_cutout: false,
	can_start_canva_cutout: false,
	can_use_original_fallback: false,
};

// ── Product-aware cutout completion fixtures (prop-driven, no API mock) ──────
const approvedAuto: ProductVisualReadiness = {
	...pending,
	active_visual_source: "APPROVED_AUTO_CANONICAL_CUTOUT",
	auto_cutout_status: "APPROVED",
	manual_cutout_status: "NOT_UPLOADED",
	original_preview_url: "https://example.test/original.png",
	auto_cutout_preview_url: "https://example.test/auto.png",
	manual_cutout_preview_url: null,
	current_system_visual: { card: "AUTO_CUTOUT", label: "Auto Cutout", status: "OFFICIAL" },
};

const approvedManual: ProductVisualReadiness = {
	...pending,
	active_visual_source: "APPROVED_MANUAL_CANONICAL_CUTOUT",
	auto_cutout_status: "NOT_PREPARED",
	manual_cutout_status: "APPROVED",
	original_preview_url: "https://example.test/original.png",
	manual_cutout_preview_url: "https://example.test/manual.png",
	current_system_visual: { card: "MANUAL_CUTOUT", label: "Manual / Canva Cutout", status: "OFFICIAL" },
};

const trustedSourcePendingAuto: ProductVisualReadiness = {
	...pending,
	active_visual_source: "SAME_PRODUCT_TRUSTED_SOURCE",
	auto_cutout_status: "PENDING_REVIEW",
	manual_cutout_status: "NOT_UPLOADED",
	original_preview_url: "https://example.test/original.png",
	auto_cutout_preview_url: "https://example.test/auto.png",
	current_system_visual: { card: "ORIGINAL_SOURCE", label: "Original Source", status: "ORIGINAL_FALLBACK" },
};

const targetRequired: ProductVisualReadiness = {
	...pending,
	original_preview_url: "https://example.test/original.png",
	product_isolation_status: "TARGET_SELECTION_REQUIRED",
	target_selection_required: true,
	target_selection_available: false,
};

const targetNotRequired: ProductVisualReadiness = {
	...pending,
	original_preview_url: "https://example.test/original.png",
	target_selection_required: false,
	target_selection_available: false,
};

const perLaneBusy: ProductVisualReadiness = {
	...pending,
	cutout_status: "PENDING_REVIEW",
	manual_cutout_status: "NOT_UPLOADED",
	can_prepare_cutout: false,
	can_rebuild_cutout: true,
	can_upload_manual_cutout: true,
	can_start_canva_cutout: true,
};

const canvaResume: ProductVisualReadiness = {
	...pending,
	can_upload_manual_cutout: true,
	can_start_canva_cutout: true,
	canva_cutout_workflow: {
		current_stage: "MAGIC_GRAB",
		attempt_count: 0,
		alpha_verified: false,
		human_review_status: "PENDING_REVIEW",
		preflight: {},
	},
};

describe("ProductVisualReadinessPanel", () => {
	afterEach(() => {
		cleanup();
		vi.unstubAllGlobals();
	});

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
		expect(screen.getByRole("button", { name: "Approve as Official Cutout" })).toBeDisabled();
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

	it("keeps all operator lanes visible and explains blocked source actions", () => {
		render(
			<ProductVisualReadinessPanel
				productId="missing-source"
				productSourceUrl="https://example.test/product"
				readiness={missingSource}
			/>,
		);

		expect(screen.getByRole("region", { name: "Original source controls" })).toBeInTheDocument();
		expect(screen.getByRole("region", { name: "Auto cutout controls" })).toBeInTheDocument();
		expect(screen.getByRole("region", { name: "Manual and Canva cutout controls" })).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Prepare Auto Cutout" })).toBeDisabled();
		expect(screen.getByRole("button", { name: "Canva Cutout" })).toBeDisabled();
		expect(screen.getByRole("button", { name: "Upload My Cutout" })).toBeDisabled();
		expect(screen.getByRole("button", { name: "Use Original Fallback" })).toBeDisabled();
		expect(screen.getAllByText("Trusted same-product source must be prepared first.").length).toBeGreaterThan(0);
		expect(screen.getByText("SOURCE NOT RESOLVED")).toBeInTheDocument();
		expect(screen.queryByAltText("Original source cutout")).not.toBeInTheDocument();
		expect(screen.getAllByText("Not available")).toHaveLength(3);
	});

	it("keeps Upload My Cutout enabled while an Auto rebuild is in flight (per-lane busy)", () => {
		vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
		render(<ProductVisualReadinessPanel productId="product-1" readiness={perLaneBusy} />);

		const rebuild = screen.getByRole("button", { name: "Rebuild Auto Cutout" });
		const upload = screen.getByRole("button", { name: "Upload My Cutout" });
		expect(rebuild).toBeEnabled();
		expect(upload).toBeEnabled();

		fireEvent.click(rebuild);

		// The Auto lane is now busy — it disables ONLY itself.
		expect(rebuild).toBeDisabled();
		expect(upload).toBeEnabled();
	});

	it("renders a visible reason under every disabled primary action", () => {
		render(<ProductVisualReadinessPanel productId="missing-source" readiness={missingSource} />);

		for (const testid of ["reason-auto", "reason-manual", "reason-canva", "reason-fallback"]) {
			expect(screen.getByTestId(testid)).toHaveTextContent("Trusted same-product source must be prepared first.");
		}
	});

	it("marks the Original card as the current system reference under trusted-source fallback", () => {
		render(<ProductVisualReadinessPanel productId="product-1" readiness={trustedSourcePendingAuto} />);

		const original = screen.getByTestId("card-badge-original");
		expect(within(original).getByText("CURRENT SYSTEM REFERENCE")).toBeInTheDocument();
		expect(within(original).getByText("ORIGINAL FALLBACK")).toBeInTheDocument();
	});

	it("shows a pending auto candidate as PENDING REVIEW, never OFFICIAL", () => {
		render(<ProductVisualReadinessPanel productId="product-1" readiness={trustedSourcePendingAuto} />);

		const auto = screen.getByTestId("card-badge-auto");
		expect(within(auto).getByText("PENDING REVIEW")).toBeInTheDocument();
		expect(within(auto).queryByText("OFFICIAL CUTOUT")).not.toBeInTheDocument();
		expect(within(auto).queryByText("CURRENT SYSTEM REFERENCE")).not.toBeInTheDocument();
	});

	it("marks the Auto card OFFICIAL + CURRENT when auto cutout is approved", () => {
		render(<ProductVisualReadinessPanel productId="product-1" readiness={approvedAuto} />);

		const auto = screen.getByTestId("card-badge-auto");
		expect(within(auto).getByText("OFFICIAL CUTOUT")).toBeInTheDocument();
		expect(within(auto).getByText("CURRENT SYSTEM REFERENCE")).toBeInTheDocument();
		expect(within(screen.getByTestId("card-badge-original")).getByText("NOT SELECTED")).toBeInTheDocument();
		expect(within(screen.getByTestId("card-badge-manual")).getByText("NOT SELECTED")).toBeInTheDocument();
		expect(screen.getByTestId("current-system-visual")).toHaveTextContent("Official cutout.");
	});

	it("marks the Manual card OFFICIAL + CURRENT when manual cutout is approved", () => {
		render(<ProductVisualReadinessPanel productId="product-1" readiness={approvedManual} />);

		const manual = screen.getByTestId("card-badge-manual");
		expect(within(manual).getByText("OFFICIAL CUTOUT")).toBeInTheDocument();
		expect(within(manual).getByText("CURRENT SYSTEM REFERENCE")).toBeInTheDocument();
	});

	it("keeps exactly one card marked as the current system reference", () => {
		render(<ProductVisualReadinessPanel productId="product-1" readiness={approvedAuto} />);

		expect(screen.getAllByText("CURRENT SYSTEM REFERENCE")).toHaveLength(1);
	});

	it("renders the current system visual summary from backend authority", () => {
		render(<ProductVisualReadinessPanel productId="product-1" readiness={trustedSourcePendingAuto} />);

		const summary = screen.getByTestId("current-system-visual");
		expect(summary).toHaveTextContent("Original Source");
		expect(summary).toHaveTextContent("Auto cutout is waiting for review.");
	});

	it("shows Select Product Area only when target selection is required", () => {
		const view = render(<ProductVisualReadinessPanel productId="product-1" readiness={targetRequired} />);
		expect(screen.getByTestId("select-product-area")).toBeInTheDocument();
		view.unmount();

		render(<ProductVisualReadinessPanel productId="product-1" readiness={targetNotRequired} />);
		expect(screen.queryByTestId("select-product-area")).not.toBeInTheDocument();
	});

	it("adds the product-isolation confirmation to the approval form", () => {
		render(<ProductVisualReadinessPanel productId="product-1" readiness={pending} showApprovalForm />);

		expect(screen.getByTestId("confirm-product-isolation")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Approve as Official Cutout" })).toBeDisabled();
	});

	it("keeps the Canva label truthful and shows Continue in Canva when resuming", () => {
		render(<ProductVisualReadinessPanel productId="product-1" readiness={canvaResume} />);

		expect(screen.getByRole("button", { name: "Continue in Canva" })).toBeInTheDocument();
		const helper = screen.getByTestId("canva-helper");
		expect(helper.textContent || "").not.toMatch(/auto/i);
	});
});
