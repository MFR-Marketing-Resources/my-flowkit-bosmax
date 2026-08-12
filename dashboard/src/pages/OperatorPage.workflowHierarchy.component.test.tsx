/**
 * Workflow Upgrade V1 — Operator workflow hierarchy contract.
 *
 * Proves the approved five-step operator sequence renders in DOM order:
 *   Step 1  Select Product
 *   Step 2  Creative Direction (Scene Strategy authority + Copy Set/Angle/Hook)
 *   Step 3  Generation Setup (UGC prompt compiler controls)
 *   Step 4  Compile & Review (4a Load Package, 4b Generate Final Prompt)
 *   Step 5  Generate Video
 *
 * Rendered-DOM contract only: no business logic, no generate clicks.
 */
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
	fetchAPI: vi.fn().mockResolvedValue({ models: [] }),
}));
vi.mock("../api/copywritingReadiness", () => ({
	useCopywritingReadiness: () => ({ readiness: null, loading: false }),
}));
vi.mock("../api/creativeAssets", () => ({
	fetchCreativeAssetEligibilityAudit: vi
		.fn()
		.mockResolvedValue({ eligible_assets: [] }),
}));
vi.mock("../api/creativeIntelligence", () => ({
	getCreativeSetupForProduct: vi.fn().mockResolvedValue({}),
	getProductRecipes: vi.fn().mockResolvedValue({
		recipes: [],
		recommended_pretick: [],
	}),
}));
vi.mock("../api/products", () => ({
	fetchProductCatalog: vi.fn().mockResolvedValue({ items: [] }),
}));
vi.mock("../api/workspacePackages", () => ({
	compileWorkspacePromptPreview: vi.fn(),
	createWorkspaceExecutionPackage: vi.fn(),
	fetchPromptCompilerRuntimeConfig: vi.fn(() => new Promise<never>(() => {})),
	fetchWorkspacePackageReadiness: vi.fn(),
}));
vi.mock("../api/workspaceGenerationPackages", () => ({
	createF2VGenerationPackage: vi.fn(),
	createI2VGenerationPackage: vi.fn(),
}));
vi.mock("../components/BackendVersionBanner", () => ({ default: () => null }));
vi.mock("../components/NativeExtendPanel", () => ({ default: () => null }));
vi.mock("../components/copywriting/CopywritingReadinessCard", () => ({
	default: () => <div data-testid="copywriting-readiness-mock" />,
}));
vi.mock("../components/reporting/RequestReportPanel", () => ({
	default: () => null,
}));
vi.mock("../components/SocialCopyPackagePanel", () => ({ default: () => null }));
vi.mock("../components/workspace/CopySelectionPanel", () => ({
	default: () => <div data-testid="copy-selection-panel-mock" />,
}));
vi.mock("../components/workspace/CanonicalReferenceBindingControls", () => ({
	default: ({ mode }: { mode: string }) => (
		<div data-testid="v4-reference-binding">{mode} reference controls</div>
	),
	EMPTY_BINDING: {
		productReferenceAssetId: null,
		startFrameAssetId: null,
		endFrameAssetId: null,
		characterReferenceAssetId: null,
		sceneContextReferenceAssetId: null,
		styleReferenceAssetId: null,
	},
}));
vi.mock("../components/workspace/IMGModule", () => ({
	default: () => <div data-testid="v4-img-module">IMG module</div>,
}));
vi.mock("../components/workspace/SearchableProductSelect", () => ({
	default: () => <div data-testid="product-select-mock" />,
}));
vi.mock("../components/workspace/VisualAssetPicker", () => ({
	default: () => null,
}));

import OperatorPage from "./OperatorPage";

afterEach(() => cleanup());

function renderOperator(
	mode: "HYBRID" | "T2V" | "I2V" | "F2V" | "IMG",
	search = "?classic=1",
) {
	render(
		<MemoryRouter
			initialEntries={[{ pathname: `/operator/${mode}`, search }]}
		>
			<OperatorPage mode={mode} />
		</MemoryRouter>,
	);
}

function precedes(a: HTMLElement, b: HTMLElement) {
	// DOCUMENT_POSITION_FOLLOWING = b comes after a in document order.
	return Boolean(
		a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING,
	);
}

describe("Workflow Upgrade V1 — five-step order", () => {
	it("renders Steps 1..5 in strict DOM order", () => {
		renderOperator("HYBRID");
		const steps = [1, 2, 3, 4, 5].map((n) =>
			screen.getByTestId(`workflow-step-${n}`),
		);
		for (let i = 0; i < steps.length - 1; i++) {
			expect(precedes(steps[i], steps[i + 1])).toBe(true);
		}
	});

	it("Step 1 is Select Product (contains the product picker)", () => {
		renderOperator("HYBRID");
		const step1 = screen.getByTestId("workflow-step-1");
		expect(step1).toHaveTextContent("Step 1 — Select Product");
		expect(step1).toContainElement(screen.getByTestId("product-select-mock"));
	});

	it("Step 2 is Creative Direction and contains Scene Strategy + Copy Selection", () => {
		renderOperator("HYBRID");
		const step2 = screen.getByTestId("workflow-step-2");
		expect(step2).toHaveTextContent("Step 2 — Creative Direction");
		expect(step2).toContainElement(
			screen.getByTestId("scene-strategy-summary"),
		);
		expect(step2).toContainElement(
			screen.getByTestId("copy-selection-panel-mock"),
		);
		expect(step2).toContainElement(
			screen.getByTestId("copywriting-readiness-mock"),
		);
		// No product selected in this fixture -> Creative Direction is NOT_READY.
		expect(step2).toHaveAttribute("data-state", "NOT_READY");
	});

	it("Step 3 is Generation Setup (compiler controls follow Creative Direction)", () => {
		renderOperator("HYBRID");
		const step3 = screen.getByTestId("workflow-step-3");
		expect(step3).toHaveTextContent("Step 3 — Generation Setup");
		expect(step3).toContainElement(
			screen.getByTestId("setting-generation-mode"),
		);
	});

	it("Step 4 is Compile & Review and contains both bridge actions", () => {
		renderOperator("HYBRID");
		const step4 = screen.getByTestId("workflow-step-4");
		expect(step4).toHaveTextContent("Step 4 — Compile & Review");
		expect(step4).toContainElement(
			screen.getByTestId("action-load-hybrid-package"),
		);
		expect(step4).toContainElement(
			screen.getByTestId("action-generate-final-prompt"),
		);
		expect(step4).toContainElement(screen.getByTestId("workflow-step-4-load"));
	});

	it("Step 5 stays the credit-bearing Generate Video stop", () => {
		renderOperator("HYBRID");
		const step5 = screen.getByTestId("workflow-step-5");
		expect(step5).toHaveTextContent("Step 5 — Generate Video");
		expect(step5).toHaveAttribute("data-rpa-stop", "true");
	});

	it("IMG mode keeps Steps 1-2 and hides the video-only Steps 3-5", () => {
		renderOperator("IMG");
		expect(screen.getByTestId("workflow-step-1")).toBeInTheDocument();
		expect(screen.getByTestId("workflow-step-2")).toBeInTheDocument();
		expect(screen.queryByTestId("workflow-step-3")).toBeNull();
		expect(screen.queryByTestId("workflow-step-4")).toBeNull();
		expect(screen.queryByTestId("workflow-step-5")).toBeNull();
	});
});

describe("OperatorPage V4 Bucket 1 rollout", () => {
	it.each(["F2V", "HYBRID", "I2V"] as const)(
		"renders the shared V4 shell and per-mode Reference step for %s",
		(mode) => {
			renderOperator(mode, "?v4=1");
			const root = screen.getByTestId("hybrid-workflow");
			const referenceStep = screen.getByRole("button", {
				name: /^Reference/,
			});

			expect(root).toHaveAttribute("data-variant", "v4");
			expect(referenceStep).toBeInTheDocument();

			fireEvent.click(referenceStep);

			if (mode === "HYBRID") {
				// HYBRID's anchor is auto-locked from the product's official image, so
				// the canonical picker is collapsed behind an explicit "Override anchor"
				// disclosure — it must NOT show until the operator opts to override.
				expect(screen.queryByTestId("v4-reference-binding")).toBeNull();
				fireEvent.click(screen.getByTestId("hybrid-override-anchor-toggle"));
			}

			expect(screen.getByTestId("v4-reference-binding")).toHaveTextContent(
				`${mode} reference controls`,
			);
		},
	);

	it("keeps the V4 main rail responsive and binds F2V presenter authority to the registry", () => {
		renderOperator("F2V", "?v4=1");
		const root = screen.getByTestId("hybrid-workflow");
		const main = root.querySelector("main");
		const layout = main?.parentElement;

		expect(layout).toHaveClass("lg:flex-row");
		expect(main).toHaveClass("lg:flex-1", "lg:overflow-y-auto");
		expect(main).not.toHaveClass("overflow-y-auto");
		fireEvent.click(screen.getByRole("button", { name: /^Presenter/ }));
		expect(screen.getByTestId("operator-presenter-source")).toHaveTextContent(
			"Avatar source: Avatar Registry",
		);
		expect(screen.getByTestId("operator-presenter-source")).toHaveTextContent(
			"F2V start/end slots remain frame references",
		);
	});

	it("keeps IMGModule inside the V4 Image setup step", () => {
		renderOperator("IMG", "?v4=1");
		const root = screen.getByTestId("hybrid-workflow");

		expect(root).toHaveAttribute("data-variant", "v4");
		expect(screen.getByText("Image setup")).toBeInTheDocument();
		expect(screen.getByTestId("v4-img-module")).toBeInTheDocument();
		expect(screen.queryByRole("button", { name: /^Reference/ })).toBeNull();
	});

	it("keeps non-T2V classic as the default until the lane is live-verified", () => {
		renderOperator("HYBRID");
		const root = screen.getByTestId("hybrid-workflow");

		expect(root).not.toHaveAttribute("data-variant", "v4");
		expect(screen.getByTestId("workflow-step-1")).toBeInTheDocument();
	});

	it("lets classic=1 override the V4 opt-in", () => {
		renderOperator("F2V", "?v4=1&classic=1");
		const root = screen.getByTestId("hybrid-workflow");

		expect(root).not.toHaveAttribute("data-variant", "v4");
		expect(screen.getByTestId("workflow-step-1")).toBeInTheDocument();
	});
});
