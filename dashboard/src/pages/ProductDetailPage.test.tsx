import "@testing-library/jest-dom/vitest";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
	within,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchAPI, patchAPI } from "../api/client";
import {
	fetchProductDetail,
	fetchProductStrategyTypeRegistry,
	reviewProductStrategyTaxonomy,
} from "../api/products";
import {
	fetchCopywritingTaxonomyTree,
	fetchProductCopywritingTaxonomy,
	type CopywritingTaxonomyResolution,
	type CopywritingTaxonomyTree,
} from "../api/taxonomy";
import type { Product, ProductStrategyTypeRegistryResponse } from "../types";
import ProductDetailPage from "./ProductDetailPage";

vi.mock("../api/client", () => ({
	fetchAPI: vi.fn(),
	patchAPI: vi.fn(),
}));

vi.mock("../api/products", () => ({
	fetchProductDetail: vi.fn(),
	fetchProductStrategyTypeRegistry: vi.fn(),
	invalidateProductCatalogCache: vi.fn(),
	reviewProductStrategyTaxonomy: vi.fn(),
}));

vi.mock("../api/taxonomy", () => ({
	fetchCopywritingTaxonomyTree: vi.fn(),
	fetchProductCopywritingTaxonomy: vi.fn(),
}));

vi.mock(
	"../components/product-intelligence/ProductIntelligenceReviewDraftPanel",
	() => ({
		default: () => <div data-testid="pi-panel">Product Intelligence functions</div>,
	}),
);
vi.mock("../components/product-intelligence/CreativeSetupPanel", () => ({
	default: () => <div data-testid="creative-panel">Creative Setup functions</div>,
}));
vi.mock("../components/product-intelligence/RecommendedScenePromptsCard", () => ({
	default: () => <div data-testid="recommended-scenes">Scene recommendations</div>,
}));
vi.mock("../components/product-intelligence/RecommendedCameraPresetsCard", () => ({
	default: () => <div data-testid="recommended-cameras">Camera recommendations</div>,
}));
vi.mock("../components/product-intelligence/CreativeHandoffPreview", () => ({
	default: () => <div data-testid="creative-handoff">Generation Handoff</div>,
}));
vi.mock("../components/product-registration/ProductVisualReadinessPanel", () => ({
	default: () => <div data-testid="visual-panel">Visual / Canva workflow</div>,
}));

const productFixture: Product = {
	id: "p1",
	source: "MANUAL",
	raw_product_title: "Canonical Product",
	product_display_name: "Canonical Product",
	product_short_name: "Canonical",
	category: "Toys & Games",
	subcategory: "Creative Play",
	type: "3D Scene Sticker Books",
	copywriting_product_type_code: "3d_sticker_book",
	copywriting_angle:
		"Creativity-led city-scene storytelling, reusable play, and screen-free engagement",
	shop_name: "BOSMAX",
	price_min: 10,
	price_max: 12,
	commission: "10%",
	image_url: null,
	tiktok_product_url: null,
	fastmoss_source_file: null,
	asset_status: "UNRESOLVED",
	media_id: null,
	local_image_path: null,
	created_at: "2026-01-01T00:00:00Z",
	updated_at: "2026-01-01T00:00:00Z",
};

const registryFixture: ProductStrategyTypeRegistryResponse = {
	items: [],
	clusters: [],
	scene_strategy_ids: [],
};

const taxonomyRecord = {
	category: "Toys & Games",
	subcategory: "Creative Play",
	type: "3D Scene Sticker Books",
	product_type_code: "3d_sticker_book",
	copywriting_angle:
		"Creativity-led city-scene storytelling, reusable play, and screen-free engagement",
	cluster: "Toys & Hobbies",
	display_name: "3D Sticker Book",
};

const taxonomyTreeFixture: CopywritingTaxonomyTree = {
	categories: ["Beauty & Personal Care", "Toys & Games"],
	subcategoriesByCategory: {
		"Beauty & Personal Care": ["Facial Cleansing"],
		"Toys & Games": ["Creative Play"],
	},
	typesBySubcategory: {
		"Beauty & Personal Care::Facial Cleansing": [
			"Brightening Facial Soap",
		],
		"Toys & Games::Creative Play": ["3D Scene Sticker Books"],
	},
	recordByType: {
		"Beauty & Personal Care::Facial Cleansing::Brightening Facial Soap": {
			category: "Beauty & Personal Care",
			subcategory: "Facial Cleansing",
			type: "Brightening Facial Soap",
			product_type_code: "facial_cleansing_soap",
			copywriting_angle: "Glow-led cleansing",
			cluster: "Beauty",
			display_name: "Brightening Facial Soap",
		},
		"Toys & Games::Creative Play::3D Scene Sticker Books": taxonomyRecord,
	},
};

const taxonomyResolutionFixture: CopywritingTaxonomyResolution = {
	product_id: "p1",
	product_display_name: "Canonical Product",
	match_status: "EXACT_CODE",
	matched_by: "PRODUCT_TYPE_CODE",
	product_fields: {
		category: "Toys & Games",
		subcategory: "Creative Play",
		type: "3D Scene Sticker Books",
		product_type_code: "3d_sticker_book",
		copywriting_angle: taxonomyRecord.copywriting_angle,
	},
	needs_reconciliation: false,
	current: {
		category: "Toys & Games",
		subcategory: "Creative Play",
		type: "3D Scene Sticker Books",
		product_type_code: "3d_sticker_book",
		copywriting_angle: taxonomyRecord.copywriting_angle,
	},
	match: taxonomyRecord,
	nearest_match: null,
	candidates: [taxonomyRecord],
};

function renderProductDetail() {
	return render(
		<MemoryRouter initialEntries={["/product/p1"]}>
			<Routes>
				<Route path="/product/:id" element={<ProductDetailPage />} />
			</Routes>
		</MemoryRouter>,
	);
}

describe("ProductDetailPage tab contract", () => {
	beforeEach(() => {
		vi.mocked(fetchAPI).mockReset();
		vi.mocked(fetchProductDetail).mockResolvedValue(productFixture);
		vi.mocked(patchAPI).mockResolvedValue({} as never);
		vi.mocked(fetchProductStrategyTypeRegistry).mockResolvedValue(registryFixture);
		vi.mocked(reviewProductStrategyTaxonomy).mockResolvedValue({} as never);
		vi.mocked(fetchCopywritingTaxonomyTree).mockResolvedValue(
			taxonomyTreeFixture,
		);
		vi.mocked(fetchProductCopywritingTaxonomy).mockResolvedValue(
			taxonomyResolutionFixture,
		);
	});

	afterEach(() => {
		cleanup();
		vi.resetAllMocks();
	});

	it("keeps all four primary tabs visible while showing only the selected tab", async () => {
		renderProductDetail();
		const tablist = await screen.findByRole("tablist", {
			name: "Product detail sections",
		});

		expect(within(tablist).getByRole("tab", { name: "Edit & Save" })).toHaveAttribute(
			"aria-selected",
			"true",
		);
		expect(within(tablist).getByRole("tab", { name: "Product Intelligence" })).toBeInTheDocument();
		expect(within(tablist).getByRole("tab", { name: "Creative Setup" })).toBeInTheDocument();
		expect(within(tablist).getByRole("tab", { name: "Visual / Canva" })).toBeInTheDocument();
		expect(screen.getByText("Identity & Commerce")).toBeInTheDocument();
		expect(screen.queryByTestId("pi-panel")).not.toBeInTheDocument();
		expect(screen.queryByTestId("creative-panel")).not.toBeInTheDocument();
		expect(screen.queryByTestId("visual-panel")).not.toBeInTheDocument();
	});

	it("mounts Product Intelligence only when its tab is selected", async () => {
		renderProductDetail();
		await screen.findByRole("tablist");

		fireEvent.click(screen.getByRole("tab", { name: "Product Intelligence" }));

		expect(await screen.findByTestId("pi-panel")).toHaveTextContent(
			"Product Intelligence functions",
		);
		expect(screen.queryByTestId("creative-panel")).not.toBeInTheDocument();
		expect(screen.queryByTestId("visual-panel")).not.toBeInTheDocument();
		expect(screen.getByRole("tab", { name: "Product Intelligence" })).toHaveAttribute(
			"aria-selected",
			"true",
		);
	});

	it("mounts the operator-first Creative Setup surface with advanced references collapsed", async () => {
		renderProductDetail();
		await screen.findByRole("tablist");

		fireEvent.click(screen.getByRole("tab", { name: "Creative Setup" }));

		expect(await screen.findByTestId("creative-panel")).toHaveTextContent(
			"Creative Setup functions",
		);
		expect(screen.getByTestId("recommended-scenes")).toBeInTheDocument();
		expect(screen.getByTestId("recommended-cameras")).toBeInTheDocument();
		expect(screen.getByTestId("creative-handoff")).toBeInTheDocument();
		expect(screen.getByTestId("creative-reference-library")).not.toHaveAttribute("open");
		expect(screen.getByTestId("creative-handoff-disclosure")).not.toHaveAttribute("open");
		expect(screen.queryByTestId("visual-panel")).not.toBeInTheDocument();
	});

	it("mounts Product Visual Readiness only inside the Visual / Canva tab", async () => {
		renderProductDetail();
		await screen.findByRole("tablist");

		fireEvent.click(screen.getByRole("tab", { name: "Visual / Canva" }));

		expect(await screen.findByTestId("visual-panel")).toHaveTextContent(
			"Visual / Canva workflow",
		);
		expect(screen.queryByText("Identity & Commerce")).not.toBeInTheDocument();
		expect(screen.queryByTestId("pi-panel")).not.toBeInTheDocument();
		expect(screen.queryByTestId("creative-panel")).not.toBeInTheDocument();
		expect(screen.getByRole("tab", { name: "Visual / Canva" })).toHaveAttribute(
			"aria-selected",
			"true",
		);
	});

	it("cascades Category → Subcategory → Type and resolves the canonical angle", async () => {
		renderProductDetail();
		const category = await screen.findByTestId(
			"copywriting-taxonomy-category-select",
		);
		const subcategory = screen.getByTestId(
			"copywriting-taxonomy-subcategory-select",
		);
		const type = screen.getByTestId("copywriting-taxonomy-type-select");

		fireEvent.change(category, {
			target: { value: "Beauty & Personal Care" },
		});
		expect(subcategory).toBeEnabled();
		expect(
			within(subcategory).getByRole("option", { name: "Facial Cleansing" }),
		).toBeInTheDocument();
		expect(type).toBeDisabled();

		fireEvent.change(subcategory, {
			target: { value: "Facial Cleansing" },
		});
		expect(type).toBeEnabled();
		fireEvent.change(type, {
			target: { value: "Brightening Facial Soap" },
		});

		const angle = screen.getByTestId("copywriting-taxonomy-angle");
		expect(angle).toHaveValue("Glow-led cleansing");
		expect(angle).toHaveAttribute("readonly");
		expect(
			screen.getByTestId("copywriting-taxonomy-angle-override"),
		).not.toBeChecked();
	});

	it("sends the selected SSOT code and override flag on Identity & Commerce save", async () => {
		renderProductDetail();
		await screen.findByTestId("copywriting-taxonomy-category-select");
		fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));

		await waitFor(() =>
			expect(patchAPI).toHaveBeenCalledWith(
				"/api/products/p1",
				expect.objectContaining({
					category: "Toys & Games",
					subcategory: "Creative Play",
					type: "3D Scene Sticker Books",
					copywriting_product_type_code: "3d_sticker_book",
					copywriting_angle:
						"Creativity-led city-scene storytelling, reusable play, and screen-free engagement",
					copywriting_angle_override_enabled: false,
				}),
			),
		);
	});

	it("saves identity fields while an unmapped legacy taxonomy needs reconciliation", async () => {
		vi.mocked(fetchProductCopywritingTaxonomy).mockResolvedValue({
			...taxonomyResolutionFixture,
			match_status: "NEEDS_RECONCILIATION",
			needs_reconciliation: true,
			current: {
				category: "Legacy",
				subcategory: "Unknown",
				type: "Invalid",
				copywriting_angle: "Old angle",
				product_type_code: null,
			},
			match: null,
			nearest_match: taxonomyRecord,
			candidates: [taxonomyRecord],
		});
		renderProductDetail();
		await screen.findByTestId("copywriting-taxonomy-reconciliation");

		fireEvent.change(screen.getByDisplayValue("Canonical"), {
			target: { value: "Updated Canonical" },
		});
		fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));

		await waitFor(() =>
			expect(patchAPI).toHaveBeenCalledWith(
				"/api/products/p1",
				expect.objectContaining({ product_short_name: "Updated Canonical" }),
			),
		);
		const payload = vi.mocked(patchAPI).mock.calls[0]?.[1] as Record<string, unknown>;
		expect(payload).not.toHaveProperty("category");
		expect(payload).not.toHaveProperty("subcategory");
		expect(payload).not.toHaveProperty("type");
		expect(payload).not.toHaveProperty("copywriting_product_type_code");
		expect(payload).not.toHaveProperty("copywriting_angle");
	});

	it("shows reconciliation evidence for legacy values instead of selecting silently", async () => {
		vi.mocked(fetchProductCopywritingTaxonomy).mockResolvedValueOnce({
			...taxonomyResolutionFixture,
			match_status: "NEEDS_RECONCILIATION",
			needs_reconciliation: true,
			current: {
				category: "Legacy",
				subcategory: "Unknown",
				type: "Invalid",
				copywriting_angle: "Old angle",
				product_type_code: null,
			},
			match: null,
			nearest_match: taxonomyRecord,
			candidates: [taxonomyRecord],
		});
		renderProductDetail();
		expect(
			await screen.findByTestId("copywriting-taxonomy-reconciliation"),
		).toHaveTextContent("Needs reconciliation");
		expect(
			screen.getByTestId("copywriting-taxonomy-category-select"),
		).toHaveValue("");
	});
});
