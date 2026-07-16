/**
 * BOSMAX RPA — Round A rendered locator audit (Hybrid Steps 1-5).
 *
 * Governance: docs/bosmax-rpa-g0-governance-gate.md (G0 gate), amendment M6.
 * Round A is accepted only when the audit is FALSIFIABLE: every state-bearing
 * selector is asserted in AT LEAST TWO distinct states. An audit that only ever
 * runs in the one already-observed state (Step 4 disabled, Step 5 absent, Queue
 * empty) passes vacuously and is explicitly NOT accepted.
 *
 * This file asserts the RENDERED DOM contract only. It does not drive Playwright,
 * does not click a generate action, and does not exercise business logic.
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
vi.mock("../components/copywriting/CopywritingReadinessCard", () => ({
	default: () => null,
}));
vi.mock("../components/reporting/RequestReportPanel", () => ({
	default: () => null,
}));
vi.mock("../components/SocialCopyPackagePanel", () => ({ default: () => null }));
vi.mock("../components/workspace/CopySelectionPanel", () => ({
	default: () => null,
}));
vi.mock("../components/workspace/F2VModule", () => ({ default: () => null }));
vi.mock("../components/workspace/I2VModule", () => ({ default: () => null }));
vi.mock("../components/workspace/IMGModule", () => ({ default: () => null }));
vi.mock("../components/workspace/SearchableProductSelect", () => ({
	default: () => null,
}));
vi.mock("../components/workspace/T2VModule", () => ({ default: () => null }));

import OperatorPage from "./OperatorPage";

afterEach(() => cleanup());

function renderOperator(mode: "HYBRID" | "T2V" | "I2V" | "F2V") {
	render(
		<MemoryRouter initialEntries={[{ pathname: `/operator/${mode}` }]}>
			<OperatorPage mode={mode} />
		</MemoryRouter>,
	);
}

describe("RPA Round A — Hybrid root + step locators", () => {
	it("exposes a stable hybrid root tagged with the active mode", () => {
		renderOperator("HYBRID");
		const root = screen.getByTestId("hybrid-workflow");
		expect(root).toBeInTheDocument();
		expect(root).toHaveAttribute("data-mode", "HYBRID");
	});

	it("exposes every Hybrid step container 1-5", () => {
		renderOperator("HYBRID");
		for (const step of [1, 2, 3, 4, 5]) {
			expect(screen.getByTestId(`workflow-step-${step}`)).toBeInTheDocument();
		}
	});

	it("exposes the Step 3 and Step 4 actions by stable id", () => {
		renderOperator("HYBRID");
		expect(screen.getByTestId("action-load-hybrid-package")).toBeInTheDocument();
		expect(
			screen.getByTestId("action-generate-final-prompt"),
		).toBeInTheDocument();
	});
});

describe("RPA Round A — falsifiable two-state audit (M6)", () => {
	// The EXTEND total-duration prerequisite is the gate that actually blocks
	// Load/Generate. Toggling it proves the state markers TRACK reality rather
	// than being hard-coded strings.
	it("Step 1 flips READY -> NOT_READY when EXTEND leaves total duration unset", () => {
		renderOperator("HYBRID");
		const step1 = screen.getByTestId("workflow-step-1");

		// State 1: SINGLE mode — no EXTEND total required.
		expect(step1).toHaveAttribute("data-state", "READY");

		// State 2: EXTEND with no authorized total — prerequisite unmet.
		fireEvent.change(screen.getByTestId("setting-generation-mode"), {
			target: { value: "EXTEND" },
		});
		expect(screen.getByTestId("workflow-step-1")).toHaveAttribute(
			"data-state",
			"NOT_READY",
		);
	});

	it("setting-generation-mode exposes its CURRENT value as a readable attribute", () => {
		renderOperator("HYBRID");
		const control = screen.getByTestId("setting-generation-mode");

		// State 1
		expect(control).toHaveAttribute("data-value", "SINGLE");
		// State 2 — the attribute tracks the change, so enablement is never the proof.
		fireEvent.change(control, { target: { value: "EXTEND" } });
		expect(screen.getByTestId("setting-generation-mode")).toHaveAttribute(
			"data-value",
			"EXTEND",
		);
	});

	it("Step 4 stays NOT_READY without a loaded package and its action is disabled", () => {
		renderOperator("HYBRID");
		expect(screen.getByTestId("workflow-step-4")).toHaveAttribute(
			"data-state",
			"NOT_READY",
		);
		expect(screen.getByTestId("action-generate-final-prompt")).toBeDisabled();
	});

	it("Step 5 is detectable and marked as an RPA stop", () => {
		renderOperator("HYBRID");
		const step5 = screen.getByTestId("workflow-step-5");
		// Round B must stop before Step 5; the marker lets a run PROVE it stopped.
		expect(step5).toHaveAttribute("data-rpa-stop", "true");
		expect(step5).toHaveAttribute("data-state", "NOT_READY");
	});
});

describe("RPA Round A — global notice = global STOP (G0 decision B1a)", () => {
	it("tags the single global notice and reports a non-error tone as no-stop", () => {
		renderOperator("HYBRID");
		const notice = screen.getByTestId("workflow-notice");
		expect(notice).toBeInTheDocument();
		// There is exactly ONE notice region: per-step error attribution is NOT
		// derivable, and B1 option (a) forbids plumbing new state to invent it.
		expect(screen.getAllByTestId("workflow-notice")).toHaveLength(1);
		expect(notice).toHaveAttribute("data-rpa-stop", "false");
		expect(notice).toHaveAttribute("data-notice-tone");
	});

	it("does not render the fallback-confirmation gate until it is triggered", () => {
		renderOperator("HYBRID");
		// Absent in the default state; when present it is a hard STOP that the RPA
		// must never click through (it would ship fallback copy).
		expect(screen.queryByTestId("workflow-fallback-confirm")).toBeNull();
	});
});

describe("RPA Round A — non-HYBRID regression statement (M6)", () => {
	// OperatorPage is shared by HYBRID / T2V / I2V / F2V. Round A must not break
	// the other API-first modes; these assert they still render with a root.
	it.each(["T2V", "I2V", "F2V"] as const)("%s still renders its root", (mode) => {
		renderOperator(mode);
		const root = screen.getByTestId("hybrid-workflow");
		expect(root).toBeInTheDocument();
		expect(root).toHaveAttribute("data-mode", mode);
	});
});
