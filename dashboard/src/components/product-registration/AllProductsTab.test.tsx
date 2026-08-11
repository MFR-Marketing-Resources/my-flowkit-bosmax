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
});
