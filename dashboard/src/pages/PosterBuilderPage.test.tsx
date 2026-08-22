import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPosterPromptDraft } from "../api/posterPromptDraft";
import { composePosterV2 } from "../api/posterV2";
import { pollImgGenerationJob, startImgGeneration } from "../api/imgFactory";
import PosterBuilderPage from "./PosterBuilderPage";

vi.mock("../api/staffIdentity", () => ({
	fetchStaffProfiles: vi.fn().mockResolvedValue({
		profiles: [
			{
				staff_id: "staff_test_operator",
				display_name: "Test Operator",
				active: true,
				created_at: "2026-08-01T00:00:00Z",
				updated_at: "2026-08-01T00:00:00Z",
			},
		],
	}),
	createStaffProfile: vi.fn(),
}));

vi.mock("../api/executionApproval", () => {
	const snap = (state: string, text: string) => ({
		snapshot_id: "eas_test",
		approval_state: state,
		surface: "poster_builder",
		logical_mode: "IMG",
		final_prompt_text: text,
		prompt_sha256: "aa",
		execution_envelope_sha256: "bb",
		scan_clean: 1,
	});
	return {
		createReviewSnapshot: vi.fn(async (env: { final_prompt_text: string }) =>
			snap("REVIEW_REQUIRED", env.final_prompt_text),
		),
		prepareDispatch: vi.fn(async (req: { prompt: string }) =>
			snap("REVIEW_REQUIRED", `GROUNDED::${req.prompt}`),
		),
		editSnapshot: vi.fn(async (_id: string, text: string) => snap("EDITED", text)),
		approveSnapshot: vi.fn(async () => snap("APPROVED", "approved prompt")),
	};
});

const fixtures = vi.hoisted(() => ({
	product: {
		id: "p1",
		raw_product_title: "Test Product",
		product_display_name: "Test Product",
		product_short_name: "Test",
		source: "MANUAL" as const,
	},
	recipe: {
		recipe_id: "product_hero",
		archetype: "PRODUCT_HERO",
		label: "Product Hero",
		description: "Hero poster",
		layout_template: "hero",
		product_placement: "center",
		background_scene: "studio",
		visual_style: "commercial",
		typography_mood: "bold",
		icon_guidance: "",
		composition_rules: [],
		safe_zones: [],
		chip_slots: [],
		zones: [],
		negative_prompt_additions: [],
		allowed_text_density: ["low"],
	},
}));

vi.mock("../components/workspace/SearchableProductSelect", () => ({
	default: ({ onSelect }: { onSelect: (value: typeof fixtures.product) => void }) => (
		<button type="button" onClick={() => onSelect(fixtures.product)}>Select Test Product</button>
	),
}));

vi.mock("../components/copywriting/CopyArchitectureV2LaneCard", () => ({
	default: ({ onReadyChange }: { onReadyChange?: (ready: boolean) => void }) => (
		<button type="button" onClick={() => onReadyChange?.(true)}>Prove V2 binding</button>
	),
}));

vi.mock("../api/products", () => ({
	fetchProductCatalog: vi.fn().mockResolvedValue({ items: [fixtures.product] }),
}));

vi.mock("../api/posterRecipes", () => ({
	usePosterRecipes: () => ({ recipes: [fixtures.recipe], error: "" }),
}));

vi.mock("../api/posterPromptDraft", () => ({
	createPosterPromptDraft: vi.fn(),
	formatPosterPromptDraftError: (error: unknown) => String(error),
}));

vi.mock("../api/posterV2", () => ({
	composePosterV2: vi.fn(),
	posterV2OutputUrl: (id: string) => `/api/poster/deliverables/${id}/output`,
}));

vi.mock("../api/imgFactory", () => ({
	startImgGeneration: vi.fn(),
	pollImgGenerationJob: vi.fn(),
}));

vi.mock("../api/exactProductOutput", () => ({
	resolveExactGenerationGate: vi.fn().mockResolvedValue({
		mode: "exact",
		policy: { exact_product_composite_required: true },
	}),
	buildExactSceneOnlyPrompt: vi.fn().mockResolvedValue({ prompt: "scene-only prompt" }),
}));

const promptResponse = {
	product_id: "p1",
	poster_status: "POSTER_READY",
	prompt_package_status: "DRAFT_READY" as const,
	generation_allowed: true,
	production_allowed: true,
	restricted_mode: false,
	poster_prompt: "prompt",
	negative_prompt: "",
	copy_layout: { hook: "Exact hook", subhook: "Exact body", usp: [], cta: "Buy" },
	visual_instruction: "",
	text_overlay_instruction: "",
	product_truth_lock: "locked",
	safety_guardrails: [],
	blocked_reasons: [],
	repair_actions: [],
	readiness_meta: {},
	operator_notes: "",
};

function renderPage() {
	return render(
		<MemoryRouter initialEntries={["/creative/poster-builder"]}>
			<Routes>
				<Route path="/creative/poster-builder" element={<PosterBuilderPage />} />
			</Routes>
		</MemoryRouter>,
	);
}

describe("PosterBuilderPage V2-only cutover", () => {
	afterEach(() => {
		window.localStorage.removeItem("bosmax.staff_identity.v1");
		cleanup();
	});

	beforeEach(() => {
		window.localStorage.setItem("bosmax.staff_identity.v1", "staff_test_operator");
		vi.mocked(createPosterPromptDraft).mockReset().mockResolvedValue(promptResponse);
		vi.mocked(composePosterV2).mockReset().mockResolvedValue({
				deliverable: {
					poster_deliverable_id: "pd1",
					product_id: "p1",
					copy_blueprint_id_v2: "bp1",
					copy_blueprint_revision_v2: 1,
					copy_execution_binding_id_v2: "binding:bp1:1:POSTER_BUILDER",
					copy_approval_snapshot_id_v2: "approval:bp1:1",
				recipe_id: "product_hero",
				template_version: "1",
				composition_strategy: "deterministic",
				background_media_id: "media1",
				output_path: "out.png",
				output_sha256: "sha",
				creative_asset_id: "",
				status: "POSTER_COMPOSED",
			},
			render_report: {},
			qa_report: { ok: true, findings: [], block_count: 0, warn_count: 0 },
		});
		vi.mocked(startImgGeneration).mockReset().mockResolvedValue({ job_id: "img-job-1" });
		vi.mocked(pollImgGenerationJob).mockReset().mockResolvedValue({
			status: "COMPLETED",
			media_id: "generated-background-1",
			url: "/api/flow/retrieved/generated-background-1",
		});
	});

	it("contains no legacy controls and never opens live confirmation automatically", () => {
		renderPage();
		expect(screen.getByTestId("poster-builder-v2-only")).toBeInTheDocument();
		expect(screen.queryByText(/classic view/i)).not.toBeInTheDocument();
		expect(screen.queryByText(/legacy compatibility/i)).not.toBeInTheDocument();
		expect(screen.queryByTestId("poster-gen-confirm")).not.toBeInTheDocument();
		expect(startImgGeneration).not.toHaveBeenCalled();
	});

	it("preserves the explicit live-action confirmation gate", async () => {
		renderPage();
		await waitFor(() =>
			expect(screen.getByTestId("staff-identity-select")).toHaveValue("staff_test_operator"),
		);
		fireEvent.click(screen.getByRole("button", { name: "Select Test Product" }));
		fireEvent.click(screen.getByRole("button", { name: "Prove V2 binding" }));
		fireEvent.click(screen.getByRole("button", { name: "Resolve approved V2 copy" }));
		await screen.findByText("Exact hook");

		fireEvent.click(screen.getByTestId("poster-live-background-button"));
		const confirm = screen.getByTestId("poster-gen-confirm");
		expect(confirm).toBeDisabled();
		expect(startImgGeneration).not.toHaveBeenCalled();
		fireEvent.click(screen.getByTestId("poster-img-live-action-confirm-checkbox"));
		expect(confirm).toBeEnabled();
		fireEvent.click(confirm);

		// The Final Prompt Approval Gate intercepts before the credit-bearing call;
		// approve the reviewed prompt to proceed.
		const approveBtn = await screen.findByTestId("final-prompt-approve-generate");
		await waitFor(() => expect(approveBtn).toBeEnabled());
		fireEvent.click(approveBtn);

		await waitFor(() => expect(startImgGeneration).toHaveBeenCalledTimes(1));
		expect(startImgGeneration).toHaveBeenCalledWith(
			expect.objectContaining({
				product_id: "p1",
				visual_lane_id: "POSTER_BUILDER",
				maximum_provider_operations: 1,
				max_retry_operations: 0,
			}),
		);
		await waitFor(() =>
			expect(screen.getByLabelText("Background media ID")).toHaveValue(
				"generated-background-1",
			),
		);
	});

	it("uses exact V2 prompt and compose routes without a legacy copy id", async () => {
		renderPage();
		await waitFor(() =>
			expect(screen.getByTestId("staff-identity-select")).toHaveValue("staff_test_operator"),
		);
		fireEvent.click(screen.getByRole("button", { name: "Select Test Product" }));
		fireEvent.click(screen.getByRole("button", { name: "Prove V2 binding" }));
		fireEvent.click(screen.getByRole("button", { name: "Resolve approved V2 copy" }));

		await waitFor(() => expect(createPosterPromptDraft).toHaveBeenCalledTimes(1));
		expect(createPosterPromptDraft).toHaveBeenCalledWith(
			expect.not.objectContaining({ copy_set_id: expect.anything(), poster_copy_set_id: expect.anything() }),
		);
		expect(await screen.findByText("Exact hook")).toBeInTheDocument();

		fireEvent.change(screen.getByLabelText("Background media ID"), {
			target: { value: "media1" },
		});
		fireEvent.click(screen.getByRole("button", { name: /Compose with V2 copy/i }));
		await waitFor(() => expect(composePosterV2).toHaveBeenCalledTimes(1));
		expect(composePosterV2).toHaveBeenCalledWith(
			expect.not.objectContaining({ poster_copy_set_id: expect.anything() }),
		);
		expect(await screen.findByText("Composed: pd1")).toBeInTheDocument();
	});
});
