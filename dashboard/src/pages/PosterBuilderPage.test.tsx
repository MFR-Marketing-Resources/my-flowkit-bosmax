import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import PosterBuilderPage from "./PosterBuilderPage";
import { createPosterPromptDraft } from "../api/posterPromptDraft";
import { fetchPosterReadiness } from "../api/posterReadiness";
import { posterReadinessFixtures } from "../poster/posterReadinessTestFixtures";

vi.mock("../components/workspace/SearchableProductSelect", () => ({
	default: () => <div data-testid="product-picker">Product picker</div>,
}));

vi.mock("../api/products", () => ({
	fetchProductCatalog: vi.fn().mockResolvedValue({
		items: [
			{
				id: "p1",
				raw_product_title: "Test Product",
				product_display_name: "Test Product",
				product_short_name: "Test",
				source: "MANUAL",
				category: "Oil",
			},
		],
	}),
}));

vi.mock("../api/posterPromptDraft", () => ({
	createPosterPromptDraft: vi.fn(),
	draftToPromptRequest: vi.fn((id: string, draft: unknown) => ({
		product_id: id,
		...(draft as object),
	})),
}));

vi.mock("../api/posterReadiness", () => ({
	fetchPosterReadiness: vi.fn(),
}));

vi.mock("../api/posterCopyRecommendations", () => ({
	fetchPosterCopyRecommendations: vi.fn(),
}));

import { fetchPosterCopyRecommendations } from "../api/posterCopyRecommendations";

const mockedFetch = vi.mocked(fetchPosterReadiness);
const mockedPromptDraft = vi.mocked(createPosterPromptDraft);
const mockedRecs = vi.mocked(fetchPosterCopyRecommendations);

const sampleKit = {
	kit_id: "k1",
	status: "candidate" as const,
	source: "FALLBACK_TEMPLATE" as const,
	angle: "Trust",
	hook: "Safe hook",
	subhook: "Sub",
	usp_1: "a",
	usp_2: "b",
	usp_3: "c",
	cta: "Shop",
	poster_type: "Product-only hero poster",
	visual_route: "Premium commercial",
	human_presence_mode: "No human / product-forward",
	frame_ratio: "9:16",
	language: "ms",
	text_density: "medium",
	safety_notes: [],
	blocked_reasons: [],
};

function renderPage(query = "?product_id=p1") {
	return render(
		<MemoryRouter initialEntries={[`/creative/poster-builder${query}`]}>
			<Routes>
				<Route path="/creative/poster-builder" element={<PosterBuilderPage />} />
			</Routes>
		</MemoryRouter>,
	);
}

async function waitForReadinessUi() {
	await waitFor(() => {
		expect(mockedFetch).toHaveBeenCalled();
	});
}

describe("PosterBuilderPage", () => {
	afterEach(() => {
		cleanup();
	});

	beforeEach(() => {
		mockedFetch.mockReset();
		mockedPromptDraft.mockReset();
		mockedRecs.mockReset();
		mockedRecs.mockResolvedValue({
			product_id: "p1",
			poster_status: "POSTER_READY",
			generation_allowed: true,
			recommendation_source: "FALLBACK_TEMPLATE",
			recommendations: [sampleKit],
			blocked_reasons: [],
			repair_actions: [],
			ai_provider_status: {},
			warnings: [],
		});
	});

	it("renders poster builder heading", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		expect(await screen.findByText("Poster Builder")).toBeInTheDocument();
	});

	it("calls fetchPosterReadiness when product_id query is present", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage("?product_id=p1");
		await waitFor(() => {
			expect(mockedFetch).toHaveBeenCalledWith("p1");
		});
	});

	it("POSTER_READY shows working mode selector and auto panel by default", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		await waitForReadinessUi();
		expect(
			await screen.findByTestId("poster-working-mode-selector"),
		).toBeInTheDocument();
		expect(await screen.findByTestId("poster-auto-mode-panel")).toBeInTheDocument();
		expect(
			screen.queryAllByRole("heading", { name: "Poster builder shell" }),
		).toHaveLength(0);
		expect(mockedRecs).toHaveBeenCalled();
	});

	it("POSTER_REPAIR_REQUIRED renders repair center and hides builder shell", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.repairRequired());
		renderPage();
		await waitForReadinessUi();
		expect(
			await screen.findByRole("heading", { name: "Repair action center" }),
		).toBeInTheDocument();
		expect(screen.getByText("Run Safe Claim Clearance")).toBeInTheDocument();
		expect(
			screen.queryAllByRole("heading", { name: "Poster builder shell" }),
		).toHaveLength(0);
	});

	it("POSTER_BLOCKED renders human review panel and hides builder shell", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.blocked());
		renderPage();
		await waitForReadinessUi();
		expect(
			await screen.findByRole("heading", { name: "Human review required" }),
		).toBeInTheDocument();
		expect(
			screen.queryAllByRole("heading", { name: "Poster builder shell" }),
		).toHaveLength(0);
	});

	it("POSTER_READY_RESTRICTED renders restricted readiness badge", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.restricted());
		renderPage();
		await waitForReadinessUi();
		expect(
			await screen.findByText(/Restricted safe poster rules apply/i),
		).toBeInTheDocument();
		expect(screen.getByText("Restricted Ready")).toBeInTheDocument();
		expect(await screen.findByTestId("poster-auto-mode-panel")).toBeInTheDocument();
	});

	it("POSTER_PREVIEW_ONLY renders preview badge and working modes", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.previewOnly());
		renderPage();
		await waitForReadinessUi();
		expect(screen.getByText("Preview Only")).toBeInTheDocument();
		expect(await screen.findByTestId("poster-auto-mode-panel")).toBeInTheDocument();
		const handoff = await screen.findByTestId("poster-image-handoff");
		expect(handoff).toBeInTheDocument();
	});

	it("shows prompt package preview after successful prompt draft API", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		mockedPromptDraft.mockResolvedValue({
			product_id: "p1",
			poster_status: "POSTER_READY",
			prompt_package_status: "DRAFT_READY",
			generation_allowed: true,
			production_allowed: true,
			restricted_mode: false,
			poster_prompt: "LOCKED PRODUCT TRUTH",
			negative_prompt: "no blur",
			copy_layout: { hook: "h", subhook: "", usp: [], cta: "c" },
			visual_instruction: "",
			text_overlay_instruction: "",
			product_truth_lock: "",
			safety_guardrails: [],
			blocked_reasons: [],
			repair_actions: [],
			readiness_meta: {},
			operator_notes: "",
		});
		renderPage();
		await waitForReadinessUi();
		const useBtn = await screen.findByText("Use for prompt draft");
		useBtn.click();
		expect(
			await screen.findByTestId("poster-prompt-package-preview"),
		).toBeInTheDocument();
		expect(mockedPromptDraft).toHaveBeenCalled();
	});

	it("manual expert mode shows manual panel", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		await waitForReadinessUi();
		const manualBtn = await screen.findByTestId("working-mode-manual");
		manualBtn.click();
		expect(await screen.findByTestId("poster-manual-expert-panel")).toBeInTheDocument();
		expect(await screen.findByTestId("generate-prompt-draft-button")).toBeInTheDocument();
	});
});