import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/products", () => ({
	searchProducts: vi.fn(),
}));

import { searchProducts } from "../../api/products";
import type { Product } from "../../types";
import SearchableProductSelect from "./SearchableProductSelect";

const mockedSearch = vi.mocked(searchProducts);

const baseProduct = (over: Partial<Product> = {}): Product =>
	({
		id: "p-local-1",
		raw_product_title: "Local Catalog Product",
		product_display_name: "Local Catalog Product",
		source: "MANUAL",
		reference_only: false,
		...over,
	}) as Product;

describe("SearchableProductSelect — server product search", () => {
	afterEach(() => {
		cleanup();
	});

	beforeEach(() => {
		mockedSearch.mockReset();
	});

	it("queries /api/products/search for text beyond the initial catalog page", async () => {
		mockedSearch.mockResolvedValue({
			items: [
				baseProduct({
					id: "p-beyond-250",
					raw_product_title: "Beyond First Page SKU",
					product_display_name: "Beyond First Page SKU",
				}),
			],
		} as never);

		const onSelect = vi.fn();
		render(
			<SearchableProductSelect
				products={[baseProduct()]}
				selectedProduct={null}
				onSelect={onSelect}
			/>,
		);

		fireEvent.click(screen.getByRole("button"));
		const input = screen.getByPlaceholderText(/search all products by name/i);
		fireEvent.change(input, { target: { value: "Beyond" } });

		await waitFor(
			() => {
				expect(mockedSearch).toHaveBeenCalled();
			},
			{ timeout: 3000 },
		);
		expect(mockedSearch.mock.calls[0]?.[0]).toBe("Beyond");
		// GENERATION lane keeps reference-only rows out of selectable search.
		expect(mockedSearch.mock.calls[0]?.[2]).toBe("GENERATION");

		await waitFor(() => {
			expect(screen.getByText(/Beyond First Page SKU/i)).toBeInTheDocument();
		});
	});

	it("disables reference-only products from selection", async () => {
		const onSelect = vi.fn();
		render(
			<SearchableProductSelect
				products={[
					baseProduct({
						id: "fastmoss-ref:xyz",
						raw_product_title: "Reference Only Item",
						reference_only: true,
					}),
				]}
				selectedProduct={null}
				onSelect={onSelect}
			/>,
		);
		fireEvent.click(screen.getByRole("button"));
		const option = screen.getByText(/Reference Only Item/i);
		fireEvent.click(option);
		expect(onSelect).not.toHaveBeenCalled();
	});
});
