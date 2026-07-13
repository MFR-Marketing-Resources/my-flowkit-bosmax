import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

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
	fetchPromptCompilerRuntimeConfig: vi.fn(
		() => new Promise<never>(() => {}),
	),
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
vi.mock("../components/reporting/RequestReportPanel", () => ({ default: () => null }));
vi.mock("../components/SocialCopyPackagePanel", () => ({ default: () => null }));
vi.mock("../components/workspace/CopySelectionPanel", () => ({ default: () => null }));
vi.mock("../components/workspace/F2VModule", () => ({ default: () => null }));
vi.mock("../components/workspace/I2VModule", () => ({ default: () => null }));
vi.mock("../components/workspace/IMGModule", () => ({ default: () => null }));
vi.mock("../components/workspace/SearchableProductSelect", () => ({ default: () => null }));
vi.mock("../components/workspace/T2VModule", () => ({
	default: ({ workspacePackage }: { workspacePackage?: { workspace_execution_package_id?: string } }) => (
		<output data-testid="mock-t2v-package">
			{workspacePackage?.workspace_execution_package_id ?? "none"}
		</output>
	),
}));

import OperatorPage from "./OperatorPage";

afterEach(() => cleanup());

function renderOperator(
	mode: "T2V" | "HYBRID" | "F2V" | "I2V",
	state?: unknown,
) {
	render(
		<MemoryRouter initialEntries={[{ pathname: `/operator/${mode}`, state }]}>
			<OperatorPage mode={mode} />
		</MemoryRouter>,
	);
}

describe("OperatorPage duration authority controls", () => {
	it.each(["T2V", "HYBRID", "F2V", "I2V"] as const)(
		"renders the shared derived EXTEND control surface for %s",
		(mode) => {
			renderOperator(mode);

			const generationMode = screen.getByTitle("Generation mode");
			expect(generationMode).toHaveValue("SINGLE");
			expect(screen.getByTitle("Video duration")).toBeInTheDocument();
			fireEvent.change(generationMode, { target: { value: "EXTEND" } });

			expect(screen.getByTitle("Total video duration")).toBeInTheDocument();
			expect(screen.queryByTitle("Video duration")).not.toBeInTheDocument();
			expect(
				screen.getByTestId("canonical-video-production-control"),
			).toBeInTheDocument();
			expect(
				screen.queryByTestId("mock-t2v-package"),
			).not.toBeInTheDocument();
			expect(screen.getByTestId("operator-duration-authority-summary")).toHaveTextContent(
				"Select one Total Video Duration",
			);
			expect(screen.queryByText("WPS Engine Vendor")).not.toBeInTheDocument();
			expect(screen.queryByText("WPS Total Duration")).not.toBeInTheDocument();
		},
	);

	it("clears a stale EXTEND total and keeps SINGLE outside the production route", async () => {
		renderOperator("T2V", {
			workspaceExecutionPackage: {
				mode: "T2V",
				generation_mode: "EXTEND",
				total_duration_seconds: 24,
				prompt_blocks: [],
				manual_fallback: { copy_prompt_available: false },
				workspace_execution_package_id: "exec-stale-extend",
			},
		});

		const generationMode = screen.getByTitle("Generation mode");
		await waitFor(() => expect(generationMode).toHaveValue("EXTEND"));
		expect(screen.getByTitle("Total video duration")).toHaveValue("24");

		fireEvent.change(generationMode, { target: { value: "SINGLE" } });

		expect(screen.getByTitle("Video duration")).toBeInTheDocument();
		expect(
			screen.getByTestId("canonical-video-production-requires-extend"),
		).toBeInTheDocument();
		fireEvent.change(generationMode, { target: { value: "EXTEND" } });
		expect(screen.getByTitle("Total video duration")).toHaveValue("");
	});
});
