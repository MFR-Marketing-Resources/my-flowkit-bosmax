import "@testing-library/jest-dom/vitest";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
	within,
} from "@testing-library/react";
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
				// Product has a usable reference image → poster can be product-anchored.
				image_url: "http://x/product.jpg",
				local_image_path: "/local/p.jpg",
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

vi.mock("../api/imgFactory", () => ({
	startImgGeneration: vi.fn(),
	pollImgGenerationJob: vi.fn(),
}));

const { RECIPE_FIXTURES } = vi.hoisted(() => {
	const zone = (over: Record<string, unknown>) => ({
		zone_id: "z",
		role: "HEADLINE",
		source_field: "hook",
		x: 0,
		y: 0,
		w: 100,
		h: 10,
		align: "left",
		font_role: "display",
		max_chars: 48,
		placeholder: "[x]",
		...over,
	});
	return {
		RECIPE_FIXTURES: [
			{
				recipe_id: "product_hero_night_routine",
				archetype: "PRODUCT_HERO",
				label: "Product Hero — Night Routine",
				description: "Hero in a warm bedside scene.",
				layout_template: "hero_center_vertical",
				product_placement: "Centered hero.",
				background_scene: "Warm bedside.",
				visual_style: "Premium.",
				typography_mood: "Warm.",
				icon_guidance: "",
				composition_rules: [],
				safe_zones: [],
				chip_slots: ["usp_1", "usp_2", "usp_3"],
				zones: [
					zone({ zone_id: "headline", role: "HEADLINE", source_field: "hook", max_chars: 48 }),
					zone({ zone_id: "cta", role: "CTA", source_field: "cta", max_chars: 24 }),
				],
				negative_prompt_additions: [],
				allowed_text_density: ["low", "medium"],
			},
			{
				recipe_id: "heritage_infographic",
				archetype: "HERITAGE_INFOGRAPHIC",
				label: "Heritage Infographic",
				description: "Packshot + use-case rows.",
				layout_template: "packshot_dominant_infographic",
				product_placement: "Packshot dominant.",
				background_scene: "Heritage frame.",
				visual_style: "Ornamental.",
				typography_mood: "Bold.",
				icon_guidance: "",
				composition_rules: [],
				safe_zones: [],
				chip_slots: ["usp_1", "usp_2", "usp_3"],
				zones: [
					zone({ zone_id: "headline", role: "HEADLINE", source_field: "hook", max_chars: 48 }),
					zone({ zone_id: "cta", role: "CTA", source_field: "cta", max_chars: 24 }),
					zone({ zone_id: "footer", role: "FOOTER", source_field: "", max_chars: 40, placeholder: "[Barisan warisan]" }),
				],
				negative_prompt_additions: [],
				allowed_text_density: ["medium", "high"],
			},
			{
				recipe_id: "product_scale_portability",
				archetype: "PRODUCT_SCALE",
				label: "Product Scale / Portability",
				description: "Product dominance + scale cue.",
				layout_template: "hero_scale_minimal",
				product_placement: "Product dominant.",
				background_scene: "Neutral studio.",
				visual_style: "Clean.",
				typography_mood: "Modern.",
				icon_guidance: "",
				composition_rules: [],
				safe_zones: [],
				chip_slots: ["usp_1", "usp_2"],
				zones: [
					zone({ zone_id: "headline", role: "HEADLINE", source_field: "hook", max_chars: 48 }),
					zone({ zone_id: "cta", role: "CTA", source_field: "cta", max_chars: 24 }),
				],
				negative_prompt_additions: [],
				allowed_text_density: ["low"],
			},
		],
	};
});

vi.mock("../api/posterRecipes", () => ({
	usePosterRecipes: () => ({ recipes: RECIPE_FIXTURES, error: "" }),
	fetchPosterRecipes: vi.fn().mockResolvedValue(RECIPE_FIXTURES),
}));

vi.mock("../api/posterCopyQuality", () => ({
	fetchPosterCopyQuality: vi.fn(),
}));

vi.mock("../api/imageGenSettings", () => ({
	useImageGenSettings: () => ({
		models: [
			{ key: "NANO_BANANA_2", label: "Nano Banana 2", pending: false },
			{ key: "NANO_BANANA_PRO", label: "Nano Banana Pro", pending: false },
		],
		default_model: "Nano Banana 2",
		aspect_options: ["9:16", "1:1", "16:9", "4:3", "3:4"],
		default_aspect: "9:16",
		count_options: [1, 2, 3, 4],
		default_count: 1,
	}),
	IMAGE_GEN_SETTINGS_FALLBACK: {},
}));

vi.mock("../api/posterBuilderSettings", () => {
	const settings = {
		poster_objectives: [
			{ id: "Product awareness", label: "Product awareness", default: true },
			{ id: "Sales conversion", label: "Sales conversion" },
		],
		poster_types: [
			{ id: "Product-only hero poster", label: "Product-only hero poster", default: true },
			{ id: "Lifestyle in-use", label: "Lifestyle in-use" },
		],
		languages: [
			{ id: "ms", label: "Malay", default: true },
			{ id: "en", label: "English" },
		],
		visual_routes: [
			{ id: "Premium commercial", label: "Premium commercial", default: true },
		],
		human_presence_modes: [
			{ id: "No human / product-forward", label: "No human / product-forward", default: true },
		],
		text_density_options: [{ id: "medium", label: "Medium", default: true }],
		flow_mirror: {
			aspect_ratios: ["9:16", "1:1", "16:9", "4:3", "3:4"],
			counts: [1, 2, 3, 4],
			image_models: [{ key: "NANO_BANANA_2", label: "Nano Banana 2", pending: false }],
			defaults: { aspect_ratio: "9:16", count: 1, image_model: "Nano Banana 2" },
			source: "models.json",
		},
		copy_components: {
			routes: ["DIRECT", "STEALTH", "REVIEW_REQUIRED"],
			copy_sets_scope: "product",
			copy_sets_endpoint: "/api/copy-sets/product/{product_id}",
			landbank_products: 0,
			source: "copy_signals+landbank",
		},
		ai_provider: {
			lane: "text_assist",
			configured: true,
			status: "configured",
			provider_id: "deepseek",
			model_id: "deepseek-chat",
			execution_enabled: true,
			source: "ai_provider",
		},
		sources: {
			poster_dimensions: "config",
			flow_mirror: "models.json",
			copy_components: "copy_signals+landbank",
			ai_provider: "ai_provider",
		},
	};
	return {
		usePosterBuilderSettings: () => settings,
		fetchPosterBuilderSettings: vi.fn().mockResolvedValue(settings),
		POSTER_BUILDER_SETTINGS_FALLBACK: settings,
		defaultOptionId: (opts: { id: string; default?: boolean }[]) =>
			(opts.find((o) => o.default) ?? opts[0])?.id ?? "",
	};
});

import { fetchPosterCopyRecommendations } from "../api/posterCopyRecommendations";
import { draftToPromptRequest } from "../api/posterPromptDraft";
import { pollImgGenerationJob, startImgGeneration } from "../api/imgFactory";
import { fetchProductCatalog } from "../api/products";
import { fetchPosterCopyQuality } from "../api/posterCopyQuality";

const mockedFetch = vi.mocked(fetchPosterReadiness);
const mockedPromptDraft = vi.mocked(createPosterPromptDraft);
const mockedRecs = vi.mocked(fetchPosterCopyRecommendations);
const mockedDraftToPrompt = vi.mocked(draftToPromptRequest);
const mockedStartGen = vi.mocked(startImgGeneration);
const mockedPollGen = vi.mocked(pollImgGenerationJob);
const mockedCatalog = vi.mocked(fetchProductCatalog);
const mockedQuality = vi.mocked(fetchPosterCopyQuality);

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
		mockedStartGen.mockReset();
		mockedPollGen.mockReset();
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

	it("fetchPosterReadiness is called once after stable product load", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		await waitForReadinessUi();
		await waitFor(() => {
			expect(mockedFetch).toHaveBeenCalledTimes(1);
			expect(mockedFetch).toHaveBeenCalledWith("p1");
		});
	});

	it("fetchPosterCopyRecommendations auto-loads once per product", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		await waitForReadinessUi();
		await waitFor(() => {
			expect(mockedRecs).toHaveBeenCalledTimes(1);
		});
		await new Promise((r) => setTimeout(r, 50));
		expect(mockedRecs).toHaveBeenCalledTimes(1);
	});

	it("changing Flow Mirror aspect does not refetch readiness or recommendations", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		await waitForReadinessUi();
		await waitFor(() => expect(mockedRecs).toHaveBeenCalledTimes(1));
		const ratioBtn = await screen.findByTestId("flow-aspect-1-1");
		ratioBtn.click();
		await new Promise((r) => setTimeout(r, 50));
		expect(mockedFetch).toHaveBeenCalledTimes(1);
		expect(mockedRecs).toHaveBeenCalledTimes(1);
	});

	it("POSTER_READY shows Flow Mirror Settings section", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		await waitForReadinessUi();
		expect(await screen.findByTestId("poster-flow-mirror-settings")).toBeInTheDocument();
		expect(screen.getByText("Flow Mirror Settings")).toBeInTheDocument();
		for (const ratio of ["9:16", "1:1", "16:9", "4:3", "3:4"]) {
			expect(screen.getByText(ratio)).toBeInTheDocument();
		}
		for (const c of ["1x", "2x", "3x", "4x"]) {
			expect(screen.getByText(c)).toBeInTheDocument();
		}
		expect(screen.getByTestId("flow-image-model")).toHaveValue("Nano Banana 2");
	});

	it("Auto mode Use for prompt draft sends selected kit fields atomically", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		mockedPromptDraft.mockResolvedValue({
			product_id: "p1",
			poster_status: "POSTER_READY",
			prompt_package_status: "DRAFT_READY",
			generation_allowed: true,
			production_allowed: true,
			restricted_mode: false,
			poster_prompt: "x",
			negative_prompt: "",
			copy_layout: { hook: "Safe hook", subhook: "Sub", usp: ["a", "b", "c"], cta: "Shop" },
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
		const useBtn = await screen.findByTestId("use-kit-prompt-k1");
		useBtn.click();
		await waitFor(() => {
			expect(mockedDraftToPrompt).toHaveBeenCalledWith(
				"p1",
				expect.objectContaining({
					hook: "Safe hook",
					subhook: "Sub",
					usp_1: "a",
					usp_2: "b",
					usp_3: "c",
					cta: "Shop",
					poster_type: "Product-only hero poster",
					visual_route: "Premium commercial",
					frame_ratio: "9:16",
					language: "ms",
				}),
			);
		});
	});

	it("changing Flow Mirror aspect ratio updates prompt draft payload", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		mockedPromptDraft.mockResolvedValue({
			product_id: "p1",
			poster_status: "POSTER_READY",
			prompt_package_status: "DRAFT_READY",
			generation_allowed: true,
			production_allowed: true,
			restricted_mode: false,
			poster_prompt: "x",
			negative_prompt: "",
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
		const ratioBtn = await screen.findByTestId("flow-aspect-1-1");
		ratioBtn.click();
		const useBtn = await screen.findByTestId("use-kit-prompt-k1");
		useBtn.click();
		await waitFor(() => {
			expect(mockedDraftToPrompt).toHaveBeenCalledWith(
				"p1",
				expect.objectContaining({ frame_ratio: "1:1", hook: "Safe hook" }),
			);
		});
	});

	it("image generation handoff button stays disabled", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		await waitForReadinessUi();
		const btn = await screen.findByTestId("generate-poster-button");
		expect(btn).toBeDisabled();
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
		const useBtn = await screen.findByTestId("use-kit-prompt-k1");
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

	it("Auto mode renders Objective / Poster Type / Language as dropdowns", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		await waitForReadinessUi();
		const obj = await screen.findByTestId("poster-objective-select");
		expect(obj.tagName).toBe("SELECT");
		expect(screen.getByTestId("poster-type-select").tagName).toBe("SELECT");
		expect(screen.getByTestId("poster-language-select").tagName).toBe("SELECT");
		expect(within(obj).getByText("Product awareness")).toBeInTheDocument();
	});

	it("Auto mode shows always-visible copy draft fields", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		await waitForReadinessUi();
		for (const key of ["hook", "subhook", "usp_1", "usp_2", "usp_3", "cta"]) {
			expect(await screen.findByTestId(`copy-field-${key}`)).toBeInTheDocument();
		}
	});

	it("keeps copy draft fields visible when recommendations fail", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		mockedRecs.mockRejectedValue(new Error("provider down"));
		renderPage();
		await waitForReadinessUi();
		expect(await screen.findByTestId("copy-field-hook")).toBeInTheDocument();
		expect(await screen.findByTestId("poster-ai-copy-assist")).toBeInTheDocument();
		expect(await screen.findByText("provider down")).toBeInTheDocument();
	});

	it("renders the AI Copy Assist section", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		await waitForReadinessUi();
		expect(await screen.findByTestId("poster-ai-copy-assist")).toBeInTheDocument();
		expect(screen.getByTestId("ai-assist-provider-status")).toBeInTheDocument();
	});

	it("auto-load uses refresh_ai=false; AI Copy Assist uses refresh_ai=true", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		await waitForReadinessUi();
		await waitFor(() => expect(mockedRecs).toHaveBeenCalledTimes(1));
		// Guardrail: the automatic load must NOT spend AI tokens.
		expect(mockedRecs.mock.calls[0][0]).toEqual(
			expect.objectContaining({ refresh_ai: false }),
		);
		const genBtn = await screen.findByTestId("refresh-poster-recommendations");
		genBtn.click();
		await waitFor(() => expect(mockedRecs).toHaveBeenCalledTimes(2));
		expect(mockedRecs.mock.calls[1][0]).toEqual(
			expect.objectContaining({ refresh_ai: true }),
		);
	});

	it("Apply suggestion fills the visible copy draft fields", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		await waitForReadinessUi();
		const applyBtn = await screen.findByTestId("select-kit-k1");
		applyBtn.click();
		await waitFor(() => {
			expect(screen.getByTestId("copy-field-hook")).toHaveValue("Safe hook");
		});
	});

	it("Auto mode generate-prompt-draft uses the visible copy fields", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		mockedPromptDraft.mockResolvedValue({
			product_id: "p1",
			poster_status: "POSTER_READY",
			prompt_package_status: "DRAFT_READY",
			generation_allowed: true,
			production_allowed: true,
			restricted_mode: false,
			poster_prompt: "x",
			negative_prompt: "",
			copy_layout: { hook: "", subhook: "", usp: [], cta: "" },
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
		const genBtn = await screen.findByTestId("auto-generate-prompt-draft");
		genBtn.click();
		await waitFor(() => {
			expect(mockedDraftToPrompt).toHaveBeenCalledWith(
				"p1",
				expect.objectContaining({ poster_objective: "Product awareness" }),
			);
		});
	});

	it("Generate poster image is gated behind a confirm and calls the one-door IMG lane", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		mockedPromptDraft.mockResolvedValue({
			product_id: "p1",
			poster_status: "POSTER_READY",
			prompt_package_status: "DRAFT_READY",
			generation_allowed: true,
			production_allowed: true,
			restricted_mode: false,
			poster_prompt: "POSTER PROMPT TEXT",
			negative_prompt: "",
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
		mockedStartGen.mockResolvedValue({ job_id: "job1" });
		mockedPollGen.mockResolvedValue({
			status: "DONE",
			media_id: "m1",
			url: "http://x/poster.jpg",
			size_mb: 0.5,
		});
		renderPage();
		await waitForReadinessUi();
		// Build a prompt package first — the generate button needs poster_prompt.
		const useBtn = await screen.findByTestId("use-kit-prompt-k1");
		useBtn.click();
		const genBtn = await screen.findByTestId("generate-poster-button");
		await waitFor(() => expect(genBtn).not.toBeDisabled());
		// With a valid product image, the fail-closed blocker is NOT shown.
		expect(screen.queryByTestId("poster-product-ref-required")).toBeNull();
		// Clicking opens the confirm modal — generation must NOT fire yet.
		genBtn.click();
		expect(mockedStartGen).not.toHaveBeenCalled();
		const confirmBtn = await screen.findByTestId("poster-gen-confirm");
		confirmBtn.click();
		await waitFor(() =>
			expect(mockedStartGen).toHaveBeenCalledWith(
				expect.objectContaining({
					prompt: "POSTER PROMPT TEXT",
					aspect: "9:16",
					// Product-anchor proof: the real product image is attached as a ref.
					refs: expect.objectContaining({
						subjectAsset: expect.objectContaining({
							downloadUrl: "http://x/product.jpg",
							assetSource: "PRODUCT_IMAGE_URL",
						}),
					}),
				}),
			),
		);
		expect(await screen.findByTestId("poster-gen-result")).toBeInTheDocument();
	});

	it("fail-closed: blocks poster generation when the product has no reference image", async () => {
		// Override the catalog with a product that has NO usable image reference.
		mockedCatalog.mockResolvedValueOnce({
			items: [
				{
					id: "p1",
					raw_product_title: "No Image Product",
					product_display_name: "No Image Product",
					source: "MANUAL",
					category: "Oil",
				},
			],
		} as never);
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		mockedPromptDraft.mockResolvedValue({
			product_id: "p1",
			poster_status: "POSTER_READY",
			prompt_package_status: "DRAFT_READY",
			generation_allowed: true,
			production_allowed: true,
			restricted_mode: false,
			poster_prompt: "POSTER PROMPT TEXT",
			negative_prompt: "",
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
		// The blocker is shown and the generate button is disabled.
		expect(
			await screen.findByTestId("poster-product-ref-required"),
		).toBeInTheDocument();
		// Even after producing a prompt package, generation stays blocked.
		const useBtn = await screen.findByTestId("use-kit-prompt-k1");
		useBtn.click();
		const genBtn = await screen.findByTestId("generate-poster-button");
		await waitFor(() => expect(genBtn).toBeDisabled());
		// No image generation was ever attempted without a product reference.
		expect(mockedStartGen).not.toHaveBeenCalled();
	});

	// ── PR B2: recipe-first UI ────────────────────────────────────────────────

	it("shows the recipe selector with recipe cards before any copy fields", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		await waitForReadinessUi();
		expect(await screen.findByTestId("poster-recipe-selector")).toBeInTheDocument();
		for (const id of [
			"product_hero_night_routine",
			"heritage_infographic",
			"product_scale_portability",
		]) {
			expect(screen.getByTestId(`poster-recipe-card-${id}`)).toBeInTheDocument();
		}
		// Before a recipe is chosen, copy slots are NOT shown — recipe-first is enforced.
		expect(screen.getByTestId("poster-recipe-required-hint")).toBeInTheDocument();
		expect(screen.queryByTestId("poster-recipe-slot-editor")).toBeNull();
	});

	it("Manual Expert is behind an advanced/legacy disclosure, not the primary form", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		await waitForReadinessUi();
		const advanced = await screen.findByTestId("poster-advanced-legacy");
		expect(advanced.tagName).toBe("DETAILS");
		expect(advanced).not.toHaveAttribute("open");
	});

	it("selecting a recipe reveals controlled dropdowns (not free text) and slot editor", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		await waitForReadinessUi();
		(await screen.findByTestId("poster-recipe-card-product_hero_night_routine")).click();
		// Controlled settings are SELECT elements, never text inputs.
		for (const key of [
			"poster_objective",
			"poster_type",
			"visual_route",
			"human_presence_mode",
			"frame_ratio",
			"language",
			"text_density",
		]) {
			const el = await screen.findByTestId(`ctrl-${key}`);
			expect(el.tagName).toBe("SELECT");
		}
		// Recipe slot editor renders zone-driven slots with counters.
		expect(await screen.findByTestId("poster-recipe-slot-editor")).toBeInTheDocument();
		expect(screen.getByTestId("slot-field-hook")).toBeInTheDocument();
		expect(screen.getByTestId("slot-field-cta")).toBeInTheDocument();
		expect(screen.getByTestId("slot-count-headline")).toBeInTheDocument();
	});

	it("recipe prompt-draft forwards poster_recipe_id and renders poster_spec / overlay_spec", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		mockedPromptDraft.mockResolvedValue({
			product_id: "p1",
			poster_status: "POSTER_READY",
			prompt_package_status: "DRAFT_READY",
			generation_allowed: true,
			production_allowed: true,
			restricted_mode: false,
			poster_prompt: "=== POSTER RECIPE ===",
			negative_prompt: "",
			copy_layout: { hook: "h", subhook: "", usp: [], cta: "c" },
			visual_instruction: "",
			text_overlay_instruction: "",
			product_truth_lock: "",
			safety_guardrails: [],
			blocked_reasons: [],
			repair_actions: [],
			readiness_meta: {},
			operator_notes: "",
			poster_spec: {
				recipe_id: "product_hero_night_routine",
				archetype: "PRODUCT_HERO",
				layout_template: "hero_center_vertical",
				product_placement: "Centered hero.",
				background_scene: "Warm bedside.",
				visual_style: "Premium.",
				typography_mood: "Warm.",
				icon_guidance: "",
				composition_rules: [],
				safe_zones: [],
				chip_slots: [],
			},
			overlay_spec: {
				schema_version: "poster-overlay-v1",
				frame_ratio: "9:16",
				typography_mood: "Warm.",
				safe_zones: [],
				zones: [
					{
						zone_id: "headline",
						role: "HEADLINE",
						x: 8,
						y: 8,
						w: 84,
						h: 18,
						align: "left",
						font_role: "display",
						max_chars: 48,
						text: "Malam tenang",
					},
				],
				renderer: "NONE_PHASE_2",
				disclaimer: "foundation only",
			},
		});
		renderPage();
		await waitForReadinessUi();
		(await screen.findByTestId("poster-recipe-card-product_hero_night_routine")).click();
		// Fill the required slots (hook + cta) so the generate button enables.
		fireEvent.change(await screen.findByTestId("slot-field-hook"), {
			target: { value: "Malam tenang" },
		});
		fireEvent.change(screen.getByTestId("slot-field-cta"), {
			target: { value: "Dapatkan" },
		});
		const genBtn = await screen.findByTestId("recipe-generate-prompt-draft");
		await waitFor(() => expect(genBtn).not.toBeDisabled());
		genBtn.click();
		await waitFor(() =>
			expect(mockedDraftToPrompt).toHaveBeenCalledWith(
				"p1",
				expect.objectContaining({
					poster_recipe_id: "product_hero_night_routine",
					hook: "Malam tenang",
					cta: "Dapatkan",
				}),
			),
		);
		// Structured spec + overlay preview renders, with the Phase-2 disclaimer.
		expect(await screen.findByTestId("poster-spec-preview")).toBeInTheDocument();
		expect(screen.getByTestId("poster-overlay-zones")).toBeInTheDocument();
		expect(screen.getByTestId("poster-overlay-disclaimer")).toBeInTheDocument();
	});

	it("poster copy quality check surfaces findings and BLOCK gates generation", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		mockedQuality.mockResolvedValue({
			ok: false,
			block_count: 1,
			warn_count: 1,
			findings: [
				{
					code: "MEDICAL_RELIEF_CLAIM",
					severity: "BLOCK",
					field: "overall",
					message: "bahasa perubatan/simptom.",
				},
				{
					code: "VIDEO_SCRIPT_STYLE",
					severity: "WARN",
					field: "overall",
					message: "gaya skrip video.",
				},
			],
		});
		renderPage();
		await waitForReadinessUi();
		(await screen.findByTestId("poster-recipe-card-product_hero_night_routine")).click();
		// Fill required slots so the ONLY reason to disable generate is the quality BLOCK.
		fireEvent.change(await screen.findByTestId("slot-field-hook"), {
			target: { value: "Tajuk pendek" },
		});
		fireEvent.change(screen.getByTestId("slot-field-cta"), {
			target: { value: "Dapatkan" },
		});
		// The expert quality panel is part of the recipe flow.
		expect(await screen.findByTestId("poster-copy-quality-panel")).toBeInTheDocument();
		(await screen.findByTestId("poster-quality-check")).click();
		// Findings render (a BLOCK and a WARN).
		await waitFor(() =>
			expect(screen.getByTestId("poster-quality-block")).toBeInTheDocument(),
		);
		expect(screen.getByTestId("poster-quality-warn")).toBeInTheDocument();
		// BLOCK gates the recipe generate button + shows the block note.
		expect(screen.getByTestId("poster-quality-block-note")).toBeInTheDocument();
		expect(screen.getByTestId("recipe-generate-prompt-draft")).toBeDisabled();
	});
});