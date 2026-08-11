import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const {
	fetchProductVisualReadinessMock,
	prepareProductCutoutMock,
	rebuildProductCutoutMock,
	uploadManualProductCutoutMock,
	saveProductVisualSetupMock,
} = vi.hoisted(() => ({
	fetchProductVisualReadinessMock: vi.fn(),
	prepareProductCutoutMock: vi.fn(),
	rebuildProductCutoutMock: vi.fn(),
	uploadManualProductCutoutMock: vi.fn(),
	saveProductVisualSetupMock: vi.fn(),
}));

vi.mock("../../api/productVisualOnboarding", async () => {
	const actual = await vi.importActual<typeof import("../../api/productVisualOnboarding")>(
		"../../api/productVisualOnboarding",
	);
	return {
		...actual,
		fetchProductVisualReadiness: fetchProductVisualReadinessMock,
		prepareProductCutout: prepareProductCutoutMock,
		rebuildProductCutout: rebuildProductCutoutMock,
		uploadManualProductCutout: uploadManualProductCutoutMock,
		saveProductVisualSetup: saveProductVisualSetupMock,
	};
});

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

const sourceInputOnly: ProductVisualReadiness = {
	...trustedSourcePendingAuto,
	auto_cutout_status: "NOT_PREPARED",
	auto_cutout_preview_url: null,
	auto_input_preview_url: "https://example.test/original.png",
	auto_input_source: "ORIGINAL_SOURCE_INPUT",
	auto_input_trust_status: "TRUSTED",
	can_prepare_cutout: true,
	can_rebuild_cutout: true,
	can_upload_manual_cutout: true,
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
	auto_cutout_status: "PENDING_REVIEW",
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
		fetchProductVisualReadinessMock.mockReset();
		prepareProductCutoutMock.mockReset();
		rebuildProductCutoutMock.mockReset();
		uploadManualProductCutoutMock.mockReset();
		saveProductVisualSetupMock.mockReset();
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
		expect(screen.getByTestId("save-visual-changes")).toBeDisabled();
		expect(screen.queryByRole("button", { name: "Approve as Official Cutout" })).not.toBeInTheDocument();
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
		expect(screen.getByRole("button", { name: "GENERATE AUTO CUTOUT" })).toBeDisabled();
		expect(screen.getByRole("button", { name: "Canva Cutout" })).toBeDisabled();
		expect(screen.getByRole("button", { name: "UPLOAD MANUAL CUTOUT" })).toBeDisabled();
		expect(screen.getByRole("button", { name: "Use Original Fallback" })).toBeDisabled();
		expect(screen.getAllByText("Trusted same-product source must be prepared first.").length).toBeGreaterThan(0);
		expect(screen.getByText("SOURCE NOT RESOLVED")).toBeInTheDocument();
		expect(screen.queryByAltText("Original source cutout")).not.toBeInTheDocument();
		expect(screen.getAllByText("Not available")).toHaveLength(3);
	});

	it("keeps Upload Manual Cutout enabled while Auto regeneration is in flight (per-lane busy)", () => {
		rebuildProductCutoutMock.mockImplementation(() => new Promise(() => {}));
		render(<ProductVisualReadinessPanel productId="product-1" readiness={perLaneBusy} />);

		const rebuild = screen.getByRole("button", { name: "REGENERATE AUTO CUTOUT" });
		const upload = screen.getByRole("button", { name: "UPLOAD MANUAL CUTOUT" });
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
		render(<ProductVisualReadinessPanel productId="product-1" readiness={trustedSourcePendingAuto} showApprovalForm />);
		fireEvent.click(screen.getByTestId("visual-selection-auto"));

		expect(screen.getByTestId("confirm-product-isolation")).toBeInTheDocument();
		expect(screen.getByTestId("save-visual-changes")).toBeEnabled();
	});

	it("keeps the Canva label truthful and shows Continue in Canva when resuming", () => {
		render(<ProductVisualReadinessPanel productId="product-1" readiness={canvaResume} />);

		expect(screen.getByRole("button", { name: "Continue in Canva" })).toBeInTheDocument();
		const helper = screen.getByTestId("canva-helper");
		expect(helper.textContent || "").not.toMatch(/auto/i);
	});

	it("marks the approved candidate as official and offers local choices on the others", () => {
		render(<ProductVisualReadinessPanel productId="product-1" readiness={approvedAuto} />);
		// approved auto card carries the official marker and no redundant action
		expect(screen.getByTestId("official-ribbon-auto")).toBeInTheDocument();
		expect(screen.queryByTestId("set-official-auto")).not.toBeInTheDocument();
		// The non-official cards expose local choices; backend mutation waits for Save Changes.
		expect(screen.getByTestId("set-official-original")).toBeInTheDocument();
		expect(screen.getByTestId("set-official-manual")).toBeInTheDocument();
	});

	it("enables a local choice only on the live candidate card", () => {
		render(<ProductVisualReadinessPanel productId="product-1" readiness={trustedSourcePendingAuto} />);
		// original is the current reference -> ribbon, not a button
		expect(screen.getByTestId("official-ribbon-original")).toBeInTheDocument();
		// auto is the active pending candidate -> actionable locally
		expect(screen.getByTestId("set-official-auto")).toBeEnabled();
		// manual has no uploaded candidate -> its action is disabled
		expect(screen.getByTestId("set-official-manual")).toBeDisabled();
	});

	it("states the transparent-PNG requirement for manual upload", () => {
		render(<ProductVisualReadinessPanel productId="product-1" readiness={perLaneBusy} />);
		expect(screen.getByText(/transparent background/i)).toBeInTheDocument();
	});

	it("re-reads after Replace Manual Cutout, reloads the preview, and keeps the replacement pending", async () => {
		const replacementPending: ProductVisualReadiness = {
			...approvedManual,
			cutout_status: "PENDING_REVIEW",
			cutout_review_status: "PENDING_REVIEW",
			manual_cutout_status: "PENDING_REVIEW",
			active_visual_source: "SAME_PRODUCT_TRUSTED_SOURCE",
			current_system_visual: {
				card: "ORIGINAL_SOURCE",
				label: "Original Source",
				status: "ORIGINAL_FALLBACK",
			},
			cutout_media_id: "same-media-id",
			attempt_count: 1,
			can_upload_manual_cutout: true,
			can_review_cutout: true,
			can_approve_cutout: true,
		};
		uploadManualProductCutoutMock.mockResolvedValue(approvedManual);
		fetchProductVisualReadinessMock.mockResolvedValue(replacementPending);

		render(<ProductVisualReadinessPanel productId="product-1" readiness={approvedManual} showApprovalForm />);
		const before = screen.getByAltText("Manual / Canva cutout").getAttribute("src");
		const input = document.querySelector('input[type="file"]') as HTMLInputElement;

		fireEvent.change(input, {
			target: {
				files: [new File(["replacement"], "replacement.png", { type: "image/png" })],
			},
		});

		await waitFor(() => expect(screen.getByTestId("manual-upload-message")).toHaveTextContent(/replacement is now PENDING REVIEW/i));
		expect(fetchProductVisualReadinessMock).toHaveBeenCalledWith("product-1");
		expect(screen.getByTestId("set-official-manual")).toBeEnabled();
		expect(screen.queryByTestId("official-ribbon-manual")).not.toBeInTheDocument();
		expect(screen.getByTestId("current-system-visual")).toHaveTextContent("Original Source");
		expect(screen.getByAltText("Manual / Canva cutout").getAttribute("src")).not.toBe(before);
		expect(screen.getByAltText("Manual / Canva cutout").getAttribute("src")).toContain("v=1-");
	});

	it("provides a read-only Refresh preview control", async () => {
		fetchProductVisualReadinessMock.mockResolvedValue(trustedSourcePendingAuto);
		render(<ProductVisualReadinessPanel productId="product-1" readiness={trustedSourcePendingAuto} />);

		fireEvent.click(screen.getByTestId("refresh-visual-preview"));

		await waitFor(() => expect(fetchProductVisualReadinessMock).toHaveBeenCalledWith("product-1"));
		expect(screen.getByTestId("refresh-visual-preview")).toHaveTextContent("Refresh preview");
	});

	it("shows a URL-only Original Source without promoting it to trusted", () => {
		const displayOnly: ProductVisualReadiness = {
			...missingSource,
			original_display_url: "https://example.test/kaxier.jpg",
			original_display_source: "PRODUCT_ROW_IMAGE_URL",
			original_display_trust_status: "DISPLAY_ONLY",
			can_upload_manual_cutout: true,
			can_open_source: true,
		};

		render(<ProductVisualReadinessPanel productId="product-1" readiness={displayOnly} />);

		expect(screen.getByAltText("Original Source cutout")).toHaveAttribute("src", expect.stringContaining("https://example.test/kaxier.jpg"));
		expect(screen.getByTestId("original-display-only")).toHaveTextContent("not yet prepared as trusted source");
		expect(screen.getByRole("button", { name: "UPLOAD MANUAL CUTOUT" })).toBeEnabled();
		expect(screen.getByTestId("set-official-original")).toBeEnabled();
		expect(screen.getByTestId("visual-selection-original")).toBeEnabled();
		expect(screen.getByTestId("set-official-auto")).toBeDisabled();
		expect(screen.getByTestId("visual-selection-auto")).toBeDisabled();
		expect(screen.getByAltText("Auto Cutout source input")).toHaveAttribute(
			"src",
			expect.stringContaining("https://example.test/kaxier.jpg"),
		);
	});

	it("shows the Auto loader in-place and keeps the Manual lane enabled", async () => {
		let releasePrepare!: (value: ProductVisualReadiness) => void;
		prepareProductCutoutMock.mockReturnValue(new Promise<ProductVisualReadiness>((resolve) => {
			releasePrepare = resolve;
		}));
		const generated = {
			...sourceInputOnly,
			auto_cutout_status: "PENDING_REVIEW" as const,
			auto_cutout_preview_url: "https://example.test/generated.png",
			auto_input_preview_url: null,
		};
		fetchProductVisualReadinessMock.mockResolvedValue(generated);

		render(<ProductVisualReadinessPanel productId="product-1" readiness={sourceInputOnly} />);
		fireEvent.click(screen.getByTestId("generate-auto-cutout"));

		expect(screen.getByTestId("auto-cutout-loading")).toHaveTextContent("GENERATING CUTOUT");
		expect(screen.getByTestId("auto-cutout-control-loading")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "UPLOAD MANUAL CUTOUT" })).toBeEnabled();

		releasePrepare(sourceInputOnly);
		await waitFor(() => expect(screen.getByAltText("Auto Cutout cutout")).toHaveAttribute("src", expect.stringContaining("generated.png")));
		expect(fetchProductVisualReadinessMock).toHaveBeenCalledWith("product-1");
		expect(screen.getByTestId("card-badge-auto")).toHaveTextContent("PENDING REVIEW");
		expect(screen.getByTestId("generate-auto-cutout")).toHaveTextContent("REGENERATE AUTO CUTOUT");
		expect(screen.getByAltText("Auto Cutout cutout").getAttribute("src")).toContain("v=");
	});

	it("keeps the Original input and exposes a retryable card error when Auto fails", async () => {
		prepareProductCutoutMock.mockRejectedValue(new Error("cutout generation failed"));
		render(<ProductVisualReadinessPanel productId="product-1" readiness={sourceInputOnly} />);

		fireEvent.click(screen.getByTestId("generate-auto-cutout"));
		await waitFor(() => expect(screen.getByTestId("auto-cutout-message")).toHaveTextContent("Cutout generation failed"));
		expect(screen.getByAltText("Auto Cutout source input")).toHaveAttribute("src", expect.stringContaining("original.png"));
		expect(screen.getByTestId("generate-auto-cutout")).toBeEnabled();
	});

	it("surfaces a backend preparation failure inside the Auto card", async () => {
		const failed = {
			...sourceInputOnly,
			cutout_status: "PREPARATION_FAILED" as const,
			failure_code: "CUTOUT_PREPARATION_FAILED",
		};
		prepareProductCutoutMock.mockResolvedValue(failed);
		fetchProductVisualReadinessMock.mockResolvedValue(failed);
		render(<ProductVisualReadinessPanel productId="product-1" readiness={sourceInputOnly} />);

		fireEvent.click(screen.getByTestId("generate-auto-cutout"));
		await waitFor(() => expect(screen.getByTestId("auto-cutout-message")).toHaveTextContent("Cutout generation failed"));
		expect(screen.getByAltText("Auto Cutout source input")).toHaveAttribute("src", expect.stringContaining("original.png"));
		expect(screen.getByTestId("generate-auto-cutout")).toBeEnabled();
	});

	it("shows the Manual loader, re-reads the result, and keeps Auto enabled", async () => {
		let releaseUpload!: (value: ProductVisualReadiness) => void;
		uploadManualProductCutoutMock.mockReturnValue(new Promise<ProductVisualReadiness>((resolve) => {
			releaseUpload = resolve;
		}));
		const manualPending: ProductVisualReadiness = {
			...sourceInputOnly,
			manual_cutout_status: "PENDING_REVIEW",
			manual_cutout_preview_url: "https://example.test/manual-new.png",
		};
		fetchProductVisualReadinessMock.mockResolvedValue(manualPending);

		render(<ProductVisualReadinessPanel productId="product-1" readiness={sourceInputOnly} />);
		const input = document.querySelector('input[type="file"]') as HTMLInputElement;
		fireEvent.change(input, {
			target: { files: [new File(["manual"], "manual.png", { type: "image/png" })] },
		});

		expect(screen.getByTestId("manual-cutout-loading")).toHaveTextContent("UPLOADING CUTOUT");
		expect(screen.getByTestId("generate-auto-cutout")).toBeEnabled();
		releaseUpload(sourceInputOnly);

		await waitFor(() => expect(screen.getByAltText("Manual / Canva cutout")).toHaveAttribute("src", expect.stringContaining("manual-new.png")));
		expect(fetchProductVisualReadinessMock).toHaveBeenCalledWith("product-1");
		expect(screen.getByTestId("manual-upload-message")).toHaveTextContent("PENDING REVIEW");
	});

	it("keeps the existing Manual preview when a replacement fails", async () => {
		uploadManualProductCutoutMock.mockRejectedValue(new Error("Transparent PNG required."));
		render(<ProductVisualReadinessPanel productId="product-1" readiness={approvedManual} />);
		const before = screen.getByAltText("Manual / Canva cutout").getAttribute("src");
		const input = document.querySelector('input[type="file"]') as HTMLInputElement;
		fireEvent.change(input, {
			target: { files: [new File(["replacement"], "replacement.png", { type: "image/png" })] },
		});

		await waitFor(() => expect(screen.getByTestId("manual-upload-message")).toHaveTextContent(/PNG has no transparent background/i));
		expect(screen.getByAltText("Manual / Canva cutout").getAttribute("src")).toBe(before);
		expect(fetchProductVisualReadinessMock).not.toHaveBeenCalled();
	});

	it("marks a radio/card choice dirty without changing the backend current visual", () => {
		render(<ProductVisualReadinessPanel productId="product-1" readiness={trustedSourcePendingAuto} />);

		fireEvent.click(screen.getByTestId("visual-selection-auto"));
		expect(screen.getByTestId("unsaved-visual-changes")).toBeInTheDocument();
		expect(screen.getByTestId("current-system-visual")).toHaveTextContent("Original Source");
		expect(screen.getByTestId("save-visual-changes")).toBeEnabled();
	});

	it("performs a real pending Auto save and verifies the authoritative result", async () => {
		saveProductVisualSetupMock.mockResolvedValue(approvedAuto);
		fetchProductVisualReadinessMock.mockResolvedValue(approvedAuto);
		render(<ProductVisualReadinessPanel productId="product-1" readiness={trustedSourcePendingAuto} showApprovalForm />);
		fireEvent.click(screen.getByTestId("visual-selection-auto"));
		fireEvent.change(screen.getByPlaceholderText("Reviewer identity"), { target: { value: "reviewer-1" } });
		fireEvent.change(screen.getByPlaceholderText("Review note"), { target: { value: "Identity and geometry checked." } });
		for (const name of ["Identity", "Label / logo", "Geometry / scale", "Product only — no unrelated props, food, decoration, or secondary objects remain"]) {
			fireEvent.click(screen.getByRole("checkbox", { name }));
		}

		fireEvent.click(screen.getByTestId("save-visual-changes"));
		await waitFor(() => expect(saveProductVisualSetupMock).toHaveBeenCalledWith("product-1", expect.objectContaining({
			selected_visual: "AUTO",
			reviewed_by: "reviewer-1",
		})));
		expect(fetchProductVisualReadinessMock).toHaveBeenCalledWith("product-1");
		expect(await screen.findByTestId("save-visual-message")).toHaveTextContent("SAVED");
		expect(screen.getByTestId("current-system-visual")).toHaveTextContent("Auto Cutout");
		expect(screen.queryByTestId("unsaved-visual-changes")).not.toBeInTheDocument();
	});

	it("keeps a dirty local selection and current Original state when Save fails", async () => {
		saveProductVisualSetupMock.mockRejectedValue(new Error("review authority unavailable"));
		render(<ProductVisualReadinessPanel productId="product-1" readiness={trustedSourcePendingAuto} showApprovalForm />);
		fireEvent.click(screen.getByTestId("visual-selection-auto"));
		fireEvent.change(screen.getByPlaceholderText("Reviewer identity"), { target: { value: "reviewer-1" } });
		fireEvent.change(screen.getByPlaceholderText("Review note"), { target: { value: "Identity and geometry checked." } });
		for (const name of ["Identity", "Label / logo", "Geometry / scale", "Product only — no unrelated props, food, decoration, or secondary objects remain"]) {
			fireEvent.click(screen.getByRole("checkbox", { name }));
		}

		fireEvent.click(screen.getByTestId("save-visual-changes"));
		await waitFor(() => expect(screen.getByTestId("save-visual-message")).toHaveTextContent("review authority unavailable"));
		expect(screen.getByTestId("unsaved-visual-changes")).toBeInTheDocument();
		expect(screen.getByTestId("current-system-visual")).toHaveTextContent("Original Source");
		expect(screen.queryByTestId("official-ribbon-auto")).not.toBeInTheDocument();
		expect(fetchProductVisualReadinessMock).not.toHaveBeenCalled();
	});
});
