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
		raw_product_title: over.raw_product_title ?? "Local Catalog Product",
		product_display_name:
			over.product_display_name ??
			over.raw_product_title ??
			"Local Catalog Product",
		source: "MANUAL",
		reference_only: false,
		image_url: "https://example.test/product.jpg",
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

	it("previews a product without selecting and selects only through the explicit option", () => {
		const product = baseProduct();
		const onSelect = vi.fn();
		render(
			<SearchableProductSelect
				products={[product]}
				selectedProduct={product}
				onSelect={onSelect}
			/>,
		);

		fireEvent.click(
			screen.getByRole("button", { name: "Preview Local Catalog Product" }),
		);
		expect(screen.getByRole("dialog", { name: "Image preview" })).toBeInTheDocument();
		expect(onSelect).not.toHaveBeenCalled();
		fireEvent.click(screen.getByRole("button", { name: "Close preview" }));
		expect(screen.queryByRole("dialog", { name: "Image preview" })).toBeNull();

		fireEvent.click(
			screen.getByRole("button", { name: /Local Catalog Product MANUAL/i }),
		);
		fireEvent.click(screen.getByTestId("product-option"));
		expect(onSelect).toHaveBeenCalledWith(product);
	});

	it("uses a browser-safe remote image when no verified local cache exists", () => {
		const product = baseProduct({
			image_readiness_status: "LOCAL_CACHE_MISSING",
			local_image_path: "data/products/images/missing.jpg",
		});
		render(
			<SearchableProductSelect
				products={[product]}
				selectedProduct={product}
				onSelect={vi.fn()}
			/>,
		);

		expect(
			screen.getByRole("img", { name: "Preview of Local Catalog Product" }),
		).toHaveAttribute("src", "https://example.test/product.jpg");
	});

	it("uses the local product-image route only for a verified cache", () => {
		const product = baseProduct({
			image_readiness_status: "IMAGE_CACHE_READY",
			local_image_path: "data/products/images/p-local-1.jpg",
		});
		render(
			<SearchableProductSelect
				products={[product]}
				selectedProduct={product}
				onSelect={vi.fn()}
			/>,
		);

		expect(
			screen.getByRole("img", { name: "Preview of Local Catalog Product" }),
		).toHaveAttribute("src", "/api/products/p-local-1/image");
	});

	it("uses image analysis only when it provides a browser-safe URL", () => {
		const product = baseProduct({
			image_url: "UNKNOWN",
			image_analysis: {
				status: "READY",
				image_url: "https://example.test/analysis-product.jpg",
				local_image_path: null,
				detected_package: null,
				detected_text: [],
				visual_confidence: "HIGH",
				provider: "TEST",
			},
		});
		render(
			<SearchableProductSelect
				products={[product]}
				selectedProduct={product}
				onSelect={vi.fn()}
			/>,
		);

		expect(
			screen.getByRole("img", { name: "Preview of Local Catalog Product" }),
		).toHaveAttribute("src", "https://example.test/analysis-product.jpg");
	});

	it("displays OFFICIAL cutout preview when visual_readiness has approved official visual", () => {
		const product = baseProduct({
			id: "prod-official-99",
			product_display_name: "Official Minyak Warisan",
			image_url: "https://example.test/source-never-show.jpg",
			visual_readiness: {
				product_id: "prod-official-99",
				current_system_visual: {
					status: "OFFICIAL",
					card: "MANUAL_CUTOUT",
					label: "Manual / Canva Cutout",
				},
				active_visual_source: "APPROVED_MANUAL_CANONICAL_CUTOUT",
				active_cutout_preview_url: "/api/product-visual-onboarding/prod-official-99/cutout/preview/active",
				original_preview_url: "/api/product-visual-onboarding/prod-official-99/cutout/preview/original",
			} as unknown as Product["visual_readiness"],
		});
		render(
			<SearchableProductSelect
				products={[product]}
				selectedProduct={product}
				onSelect={vi.fn()}
			/>,
		);

		expect(
			screen.getByRole("img", { name: "Preview of Official Minyak Warisan" }),
		).toHaveAttribute(
			"src",
			"/api/product-visual-onboarding/prod-official-99/cutout/preview/active",
		);
		expect(screen.getByText("Official Minyak Warisan")).toBeInTheDocument();
	});

	it("can hide the legacy readiness badge when the page owns V2 truth readiness", () => {
		const product = baseProduct({
			raw_product_title: "Minyak Warisan Cap Burung 25ml",
			product_display_name: "Minyak Warisan Cap Burung 25ml",
		});
		render(
			<SearchableProductSelect
				products={[product]}
				selectedProduct={product}
				onSelect={vi.fn()}
				showReadinessBadge={false}
			/>,
		);

		expect(screen.getByText("MANUAL")).toBeInTheDocument();
		expect(screen.queryByText("UNKNOWN")).not.toBeInTheDocument();
	});

	it("falls back to original preview when candidate is pending and not official", () => {
		const product = baseProduct({
			id: "prod-pending-88",
			product_display_name: "Pending Minyak Warisan",
			image_url: "https://example.test/source-fallback.jpg",
			visual_readiness: {
				product_id: "prod-pending-88",
				cutout_status: "PENDING_REVIEW",
				current_system_visual: {
					status: "ORIGINAL_FALLBACK",
					card: "ORIGINAL_SOURCE",
					label: "Original Source",
				},
				active_visual_source: "SAME_PRODUCT_TRUSTED_SOURCE",
				manual_cutout_preview_url: "/api/product-visual-onboarding/prod-pending-88/cutout/preview/manual",
				original_preview_url: "/api/product-visual-onboarding/prod-pending-88/cutout/preview/original",
			} as unknown as Product["visual_readiness"],
		});
		render(
			<SearchableProductSelect
				products={[product]}
				selectedProduct={product}
				onSelect={vi.fn()}
			/>,
		);

		expect(
			screen.getByRole("img", { name: "Preview of Pending Minyak Warisan" }),
		).toHaveAttribute(
			"src",
			"/api/product-visual-onboarding/prod-pending-88/cutout/preview/original",
		);
	});
});
