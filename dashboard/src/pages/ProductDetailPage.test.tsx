import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchAPI, patchAPI } from "../api/client";
import {
	fetchProductStrategyTypeRegistry,
	reviewProductStrategyTaxonomy,
} from "../api/products";
import type { Product, ProductStrategyTypeRegistryResponse } from "../types";
import ProductDetailPage from "./ProductDetailPage";

vi.mock("../api/client", () => ({
	fetchAPI: vi.fn(),
	patchAPI: vi.fn(),
}));

vi.mock("../api/products", () => ({
	fetchProductStrategyTypeRegistry: vi.fn(),
	reviewProductStrategyTaxonomy: vi.fn(),
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
vi.mock("../components/product-intelligence/RecommendedAvatarsCard", () => ({
	default: () => <div data-testid="recommended-avatars">Avatar recommendations</div>,
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
	category: "Food",
	subcategory: "Snacks",
	type: "Jar",
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
		vi.mocked(fetchAPI).mockImplementation(async (path: string) => {
			if (path === "/api/products/p1") return productFixture as never;
			throw new Error(`Unexpected ProductDetailPage fetch: ${path}`);
		});
		vi.mocked(patchAPI).mockResolvedValue({} as never);
		vi.mocked(fetchProductStrategyTypeRegistry).mockResolvedValue(registryFixture);
		vi.mocked(reviewProductStrategyTaxonomy).mockResolvedValue({} as never);
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

	it("mounts the complete Creative Setup surface without moving it into the visual tab", async () => {
		renderProductDetail();
		await screen.findByRole("tablist");

		fireEvent.click(screen.getByRole("tab", { name: "Creative Setup" }));

		expect(await screen.findByTestId("creative-panel")).toHaveTextContent(
			"Creative Setup functions",
		);
		expect(screen.getByTestId("recommended-avatars")).toBeInTheDocument();
		expect(screen.getByTestId("recommended-scenes")).toBeInTheDocument();
		expect(screen.getByTestId("recommended-cameras")).toBeInTheDocument();
		expect(screen.getByTestId("creative-handoff")).toBeInTheDocument();
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
});
