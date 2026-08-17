import "@testing-library/jest-dom/vitest";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
	CohortProduct,
	ProductVideoAllocation,
} from "../../api/creativeProduction";
import ProductAllocationPicker from "./ProductAllocationPicker";

const PRODUCTS: CohortProduct[] = [
	{
		product_id: "product-a",
		product_name: "Alpha Serum",
		product_type_group: "serum",
		scene_strategy_id: "SERUM",
		image_url: "https://example.com/alpha.jpg",
		image_readiness_status: "REMOTE_READY",
		readiness_status: "PRODUCTION_READY",
	},
	{
		product_id: "product-b",
		product_name: "Beta Balm",
		product_type_group: "balm",
		scene_strategy_id: "BALM",
		image_url: "",
		image_readiness_status: "IMAGE_CACHE_READY",
		readiness_status: "PRODUCTION_READY",
	},
];

function Harness({
	products = PRODUCTS,
	loading = false,
	error = "",
}: {
	products?: CohortProduct[];
	loading?: boolean;
	error?: string;
}) {
	const [allocations, setAllocations] = useState<ProductVideoAllocation[]>([]);
	return (
		<ProductAllocationPicker
			products={products}
			allocations={allocations}
			onChange={setAllocations}
			loading={loading}
			error={error}
		/>
	);
}

afterEach(cleanup);

describe("P6 product allocation picker", () => {
	it("searches visual results and makes selection and quantity immediate", async () => {
		render(<Harness />);
		expect(
			screen.getByText("Select a product to set its video quantity"),
		).toBeInTheDocument();
		fireEvent.click(screen.getByRole("button", { name: /Choose products/ }));
		const search = screen.getByLabelText("Search governed products");
		fireEvent.change(search, { target: { value: "Alpha" } });
		const option = screen.getByRole("option", { name: /Alpha Serum/ });
		expect(option).toHaveTextContent("Select");
		expect(
			option.querySelector('img[src="https://example.com/alpha.jpg"]'),
		).not.toBeNull();
		fireEvent.click(option);
		expect(screen.getAllByTestId("p6-selected-product")).toHaveLength(1);
		const quantity = screen.getByLabelText("Video quantity for Alpha Serum");
		expect(quantity).toHaveValue(1);
		await waitFor(() => expect(quantity).toHaveFocus());
		expect(screen.getByTestId("p6-allocation-summary")).toHaveTextContent(
			"1 product · 1 total video",
		);
		expect(
			screen.getByRole("button", { name: /1 product selected/ }),
		).toBeInTheDocument();
		expect(
			screen.queryByLabelText("Search governed products"),
		).not.toBeInTheDocument();
		fireEvent.click(screen.getByRole("button", { name: /1 product selected/ }));
		const selectedOption = screen.getByRole("option", { name: /Alpha Serum/ });
		expect(selectedOption).toHaveTextContent("Selected");
		fireEvent.click(selectedOption);
		expect(screen.queryByTestId("p6-selected-product")).not.toBeInTheDocument();
	});

	it("supports Arrow navigation, Enter selection, Escape focus return and quantity edits", async () => {
		render(<Harness />);
		const trigger = screen.getByRole("button", { name: /Choose products/ });
		fireEvent.click(trigger);
		const search = screen.getByLabelText("Search governed products");
		fireEvent.keyDown(search, { key: "ArrowDown" });
		fireEvent.keyDown(search, { key: "Enter" });
		expect(screen.getByTestId("p6-selected-product")).toHaveTextContent(
			"Beta Balm",
		);
		const quantity = screen.getByLabelText("Video quantity for Beta Balm");
		await waitFor(() => expect(quantity).toHaveFocus());
		fireEvent.change(quantity, { target: { value: "4" } });
		expect(quantity).toHaveValue(4);
		expect(screen.getByTestId("p6-allocation-summary")).toHaveTextContent(
			"1 product · 4 total videos",
		);
		fireEvent.click(trigger);
		const reopenedSearch = screen.getByLabelText("Search governed products");
		fireEvent.keyDown(reopenedSearch, { key: "Escape" });
		expect(trigger).toHaveFocus();
	});

	it("uses authoritative cache and remote image sources", () => {
		render(<Harness />);
		fireEvent.click(screen.getByRole("button", { name: /Choose products/ }));
		expect(
			screen
				.getByRole("option", { name: /Alpha Serum/ })
				.querySelector('img[src="https://example.com/alpha.jpg"]'),
		).not.toBeNull();
		expect(
			screen
				.getByRole("option", { name: /Beta Balm/ })
				.querySelector('img[src="/api/products/product-b/image"]'),
		).not.toBeNull();
	});

	it("renders truthful broken and missing image fallbacks", () => {
		const missingProduct: CohortProduct = {
			product_id: "product-missing",
			product_name: "Missing Product",
			product_type_group: "serum",
			scene_strategy_id: "SERUM",
			image_url: "",
			image_readiness_status: "IMAGE_URL_MISSING",
			readiness_status: "PRODUCTION_READY",
		};
		render(<Harness products={[PRODUCTS[0], missingProduct]} />);
		fireEvent.click(screen.getByRole("button", { name: /Choose products/ }));
		const brokenImage = screen
			.getByRole("option", { name: /Alpha Serum/ })
			.querySelector("img");
		expect(brokenImage).not.toBeNull();
		fireEvent.error(brokenImage as HTMLImageElement);
		expect(
			screen.getByRole("img", {
				name: "Product image unavailable for Alpha Serum",
			}),
		).toHaveTextContent("Load failed");
		expect(
			screen.getByRole("img", {
				name: "No approved product image for Missing Product",
			}),
		).toHaveTextContent("No image");
	});

	it("renders both hero authority shapes through the product image endpoint", () => {
		const heroProducts: CohortProduct[] = [
			{
				product_id: "mwcb-product",
				product_name: "Minyak Warisan Cap Burung 25ml",
				product_type_group: "herbal_oil",
				scene_strategy_id: "HERBAL_OIL",
				image_url: "",
				image_readiness_status: "IMAGE_CACHE_READY",
				readiness_status: "PRODUCTION_READY",
			},
			{
				product_id: "bosmax-product",
				product_name: "Bosmax Herbs 5 ML",
				product_type_group: "herbal_oil",
				scene_strategy_id: "HERBAL_OIL",
				image_url: "UNKNOWN",
				image_readiness_status: "IMAGE_CACHE_READY",
				readiness_status: "PRODUCTION_READY",
			},
		];
		render(<Harness products={heroProducts} />);
		fireEvent.click(screen.getByRole("button", { name: /Choose products/ }));
		expect(
			screen
				.getByRole("option", { name: /Minyak Warisan Cap Burung 25ml/ })
				.querySelector('img[src="/api/products/mwcb-product/image"]'),
		).not.toBeNull();
		expect(
			screen
				.getByRole("option", { name: /Bosmax Herbs 5 ML/ })
				.querySelector('img[src="/api/products/bosmax-product/image"]'),
		).not.toBeNull();
	});

	it("shows truthful empty, loading and error states", () => {
		const { rerender } = render(<Harness loading />);
		fireEvent.click(screen.getByRole("button", { name: /Choose products/ }));
		expect(screen.getByText("Loading governed products…")).toBeInTheDocument();
		rerender(<Harness error="offline" />);
		expect(
			screen.getByText(/Products could not be loaded/),
		).toBeInTheDocument();
		rerender(<Harness />);
		fireEvent.change(screen.getByLabelText("Search governed products"), {
			target: { value: "No such product" },
		});
		expect(screen.getByText(/No governed product matches/)).toBeInTheDocument();
	});

	it("exposes bounded server search and pagination callbacks", () => {
		const onSearchChange = vi.fn();
		const onPageChange = vi.fn();
		render(
			<ProductAllocationPicker
				products={PRODUCTS}
				allocations={[]}
				onChange={vi.fn()}
				onSearchChange={onSearchChange}
				onPageChange={onPageChange}
				page={{ offset: 0, limit: 1, total: 2 }}
			/>,
		);

		fireEvent.click(screen.getByRole("button", { name: /Choose products/ }));
		fireEvent.change(screen.getByLabelText("Search governed products"), {
			target: { value: "Alpha" },
		});
		expect(onSearchChange).toHaveBeenCalledWith("Alpha");
		expect(screen.getByTestId("p6-product-pagination")).toHaveTextContent(
			"1–1 of 2",
		);
		fireEvent.click(screen.getByRole("button", { name: "Next" }));
		expect(onPageChange).toHaveBeenCalledWith(1);
	});

	it("removes a selected product with an accessible action", () => {
		render(<Harness />);
		fireEvent.click(screen.getByRole("button", { name: /Choose products/ }));
		fireEvent.click(screen.getByRole("option", { name: /Alpha Serum/ }));
		fireEvent.click(screen.getByRole("button", { name: "Remove Alpha Serum" }));
		expect(
			screen.queryByText("Ready for governed planning"),
		).not.toBeInTheDocument();
	});

	it("updates multi-product totals after quantity changes and removal", () => {
		render(<Harness />);
		fireEvent.click(screen.getByRole("button", { name: /Choose products/ }));
		fireEvent.click(screen.getByRole("option", { name: /Alpha Serum/ }));
		fireEvent.click(screen.getByRole("button", { name: /1 product selected/ }));
		fireEvent.click(screen.getByRole("option", { name: /Beta Balm/ }));
		fireEvent.change(screen.getByLabelText("Video quantity for Alpha Serum"), {
			target: { value: "3" },
		});
		fireEvent.change(screen.getByLabelText("Video quantity for Beta Balm"), {
			target: { value: "2" },
		});
		expect(screen.getByTestId("p6-allocation-summary")).toHaveTextContent(
			"2 products · 5 total videos",
		);
		fireEvent.click(screen.getByRole("button", { name: "Remove Alpha Serum" }));
		expect(screen.getByTestId("p6-allocation-summary")).toHaveTextContent(
			"1 product · 2 total videos",
		);
		fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
		expect(screen.queryByTestId("p6-selected-product")).not.toBeInTheDocument();
		expect(
			screen.queryByTestId("p6-allocation-summary"),
		).not.toBeInTheDocument();
	});
});
