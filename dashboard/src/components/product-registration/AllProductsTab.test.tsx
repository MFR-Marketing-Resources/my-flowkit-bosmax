import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchProductRegistry, fetchProductStrategyTypeRegistry } from "../../api/products";
import AllProductsTab from "./AllProductsTab";

vi.mock("../../api/products", () => ({
	fetchProductRegistry: vi.fn(),
	fetchProductStrategyTypeRegistry: vi.fn(),
}));

describe("All Products per-product visual scope", () => {
	afterEach(() => {
		cleanup();
		vi.resetAllMocks();
	});

	beforeEach(() => {
		vi.mocked(fetchProductRegistry).mockResolvedValue({
			items: [],
			total_count: 0,
		} as never);
		vi.mocked(fetchProductStrategyTypeRegistry).mockResolvedValue({
			items: [],
			clusters: [],
		} as never);
	});

	it("keeps visual work per product and exposes no bulk cutout controls", async () => {
		render(<AllProductsTab />);

		expect(await screen.findByTestId("per-product-visual-workflow")).toHaveTextContent(
			"Visual work is per product",
		);
		const bodyText = document.body.textContent ?? "";
		expect(bodyText).not.toMatch(/bulk cutout|cutout queue|run all|queue all|pause all|resume all|cancel all/i);
	});

	it("shows the standard canvas note on each product visual row", async () => {
		vi.mocked(fetchProductRegistry).mockResolvedValueOnce({
			items: [
				{
					id: "product-1",
					source: "MANUAL",
					raw_product_title: "Canvas note product",
					product_display_name: "Canvas note product",
					product_short_name: "Canvas note",
					category: null,
					subcategory: null,
					type: null,
					shop_name: null,
					price: null,
					currency: null,
					commission_amount: null,
					commission_rate: null,
					image_url: null,
					lifecycle_status: "ACTIVE",
					visual_canvas_width: 1000,
					visual_canvas_height: 1000,
					visual_readiness: {
						visual_canvas_label: "1000×1000 px",
						visual_canvas_requirement: "Manual / Canva cutouts must be transparent PNG files on an exact 1000x1000 px canvas.",
						canonical_media_status: "AVAILABLE",
						cutout_status: "NOT_PREPARED",
						cutout_review_status: "NOT_STARTED",
						visual_grounding_status: "VISUAL_GROUNDING_READY_FALLBACK",
						can_start_canva_cutout: true,
					},
				} as never,
			],
			total_count: 1,
		} as never);

		render(<AllProductsTab />);

		expect(await screen.findByTestId("table-visual-canvas-requirement")).toHaveTextContent(
			"Canvas 1000×1000 px",
		);
	});
});
