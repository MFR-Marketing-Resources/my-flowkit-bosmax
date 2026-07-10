import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

const MATRIX = {
	capability_matrix_version: "video-capability-v1",
	default_engine: "GOOGLE_FLOW",
	engines: [
		{
			id: "GOOGLE_FLOW",
			label: "Google Flow",
			supported: true,
			unsupported_reason: null,
			transport: "flow_creation_agent",
			description: "",
			single_duration_policy: [8, 10],
			default_single_duration: 8,
			models: [
				{ key: "veo_3_1_lite", ui_label: "Veo 3.1 - Lite", allowed_durations_s: [4, 6, 8], default_duration_s: 8 },
				{ key: "omni_flash", ui_label: "Omni Flash", allowed_durations_s: [4, 6, 8, 10], default_duration_s: 10 },
			],
			single_models_by_duration: { "8": ["veo_3_1_lite", "omni_flash"], "10": ["omni_flash"] },
			default_model_by_duration: { "8": "veo_3_1_lite", "10": "omni_flash" },
		},
		{
			id: "GROK",
			label: "Grok",
			supported: false,
			unsupported_reason: "Runtime not yet integrated.",
			transport: null,
			description: "",
			single_duration_policy: [6, 10],
			default_single_duration: 6,
			models: [],
			single_models_by_duration: {},
			default_model_by_duration: {},
		},
	],
};

vi.mock("../api/client", () => ({
	fetchAPI: vi.fn((url: string) => {
		if (typeof url === "string" && url.includes("video-capability-matrix")) {
			return Promise.resolve(MATRIX);
		}
		return Promise.resolve({ models: [] });
	}),
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
	fetchPromptCompilerRuntimeConfig: vi.fn().mockResolvedValue({
		defaults: {
			generation_mode: "SINGLE",
			target_language: "BM_MS",
			camera_style: "UGC_IPHONE_RAW",
			character_presence: "VISIBLE_CREATOR",
			creator_persona: "DEFAULT_CREATOR",
			block_duration_seconds: 8,
		},
		allowed_block_durations_seconds: [6, 8, 10, 12, 15, 20, 25],
		shot_count_policy: {},
		language_wps_policy: { BM_MS: {}, EN_US: {} },
		persona_registry: [],
	}),
	fetchWorkspacePackageReadiness: vi.fn().mockResolvedValue({ items: [] }),
}));
vi.mock("../api/workspaceGenerationPackages", () => ({
	createF2VGenerationPackage: vi.fn(),
	createI2VGenerationPackage: vi.fn(),
}));
vi.mock("../components/BackendVersionBanner", () => ({ default: () => null }));
vi.mock("../components/copywriting/CopywritingReadinessCard", () => ({ default: () => null }));
vi.mock("../components/reporting/RequestReportPanel", () => ({ default: () => null }));
vi.mock("../components/SocialCopyPackagePanel", () => ({ default: () => null }));
vi.mock("../components/workspace/CopySelectionPanel", () => ({ default: () => null }));
vi.mock("../components/workspace/F2VModule", () => ({ default: () => null }));
vi.mock("../components/workspace/I2VModule", () => ({ default: () => null }));
vi.mock("../components/workspace/IMGModule", () => ({ default: () => null }));
vi.mock("../components/workspace/T2VModule", () => ({ default: () => null }));
vi.mock("../components/workspace/SearchableProductSelect", () => ({ default: () => null }));

import OperatorPage from "./OperatorPage";

afterEach(() => cleanup());

function renderOperator(mode: "T2V" | "HYBRID" | "F2V" | "I2V") {
	render(
		<MemoryRouter initialEntries={[`/operator/${mode}`]}>
			<OperatorPage mode={mode} />
		</MemoryRouter>,
	);
}

function durationOptionTexts() {
	const select = screen.getByTitle("Video duration");
	return within(select)
		.getAllByRole("option")
		.map((o) => o.textContent);
}

describe("OperatorPage engine/model/duration capability controls", () => {
	it.each(["T2V", "HYBRID", "F2V", "I2V"] as const)(
		"SINGLE + Google Flow exposes exactly 8s and 10s for %s",
		async (mode) => {
			renderOperator(mode);
			await waitFor(() =>
				expect(screen.getByTitle("Engine")).toHaveValue("GOOGLE_FLOW"),
			);
			await waitFor(() => expect(durationOptionTexts()).toEqual(["8s", "10s"]));
		},
	);

	it("Grok engine option is present but disabled (runtime not integrated)", async () => {
		renderOperator("T2V");
		const engine = await screen.findByTitle("Engine");
		const options = within(engine).getAllByRole("option");
		const grok = options.find((o) => (o.textContent ?? "").includes("Grok")) as HTMLOptionElement;
		expect(grok).toBeTruthy();
		expect(grok.disabled).toBe(true);
		expect(grok.textContent).toMatch(/Runtime not yet integrated/i);
	});

	it("selecting 10s filters models to Omni Flash and auto-adjusts the model", async () => {
		renderOperator("T2V");
		const durationSelect = await screen.findByTitle("Video duration");
		const modelSelect = screen.getByTitle("Video model");
		// 8s default: both models available, Veo default.
		await waitFor(() =>
			expect(
				within(modelSelect)
					.getAllByRole("option")
					.map((o) => o.textContent),
			).toEqual(["Veo 3.1 - Lite", "Omni Flash"]),
		);
		expect(modelSelect).toHaveValue("Veo 3.1 - Lite");

		fireEvent.change(durationSelect, { target: { value: "10" } });

		// 10s: only Omni is offered and the incompatible Veo selection is repaired.
		await waitFor(() =>
			expect(
				within(modelSelect)
					.getAllByRole("option")
					.map((o) => o.textContent),
			).toEqual(["Omni Flash"]),
		);
		expect(modelSelect).toHaveValue("Omni Flash");
		expect(screen.getByText(/Model adjusted to match the selected duration/i)).toBeInTheDocument();
	});

	it("EXTEND replaces the SINGLE duration control with Total Video Duration", async () => {
		renderOperator("T2V");
		const generationMode = await screen.findByTitle("Generation mode");
		expect(screen.getByTitle("Video duration")).toBeInTheDocument();
		fireEvent.change(generationMode, { target: { value: "EXTEND" } });
		expect(screen.getByTitle("Total video duration")).toBeInTheDocument();
		expect(screen.queryByTitle("Video duration")).not.toBeInTheDocument();
	});

	it("resolved-capability summary reflects the selected tuple", async () => {
		renderOperator("T2V");
		const summary = await screen.findByTestId("operator-resolved-capability");
		await waitFor(() => expect(summary).toHaveTextContent("Engine Google Flow"));
		expect(summary).toHaveTextContent("Model Veo 3.1 - Lite");
		expect(summary).toHaveTextContent("Duration 8s");
		expect(summary).toHaveTextContent("capability vvideo-capability-v1");
	});
});
