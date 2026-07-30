import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
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
	loading = false,
	error = "",
}: {
	loading?: boolean;
	error?: string;
}) {
	const [allocations, setAllocations] = useState<ProductVideoAllocation[]>([]);
	return (
		<ProductAllocationPicker
			products={PRODUCTS}
			allocations={allocations}
			onChange={setAllocations}
			loading={loading}
			error={error}
		/>
	);
}

afterEach(cleanup);

describe("P6 product allocation picker", () => {
	it("searches visual results and selects without creating duplicates", () => {
		render(<Harness />);
		fireEvent.click(screen.getByRole("button", { name: /Choose products/ }));
		const search = screen.getByLabelText("Search governed products");
		fireEvent.change(search, { target: { value: "Alpha" } });
		const option = screen.getByRole("option", { name: /Alpha Serum/ });
		expect(
			option.querySelector('img[src="https://example.com/alpha.jpg"]'),
		).not.toBeNull();
		fireEvent.click(option);
		expect(screen.getAllByTestId("p6-selected-product")).toHaveLength(1);
		expect(
			screen.getByRole("button", { name: /1 product selected/ }),
		).toBeInTheDocument();
		fireEvent.click(option);
		expect(screen.queryByTestId("p6-selected-product")).not.toBeInTheDocument();
	});

	it("supports Arrow navigation, Enter selection, Escape focus return and quantity edits", () => {
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
		fireEvent.change(quantity, { target: { value: "4" } });
		expect(quantity).toHaveValue(4);
		fireEvent.keyDown(search, { key: "Escape" });
		expect(trigger).toHaveFocus();
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

	it("removes a selected product with an accessible action", () => {
		render(<Harness />);
		fireEvent.click(screen.getByRole("button", { name: /Choose products/ }));
		fireEvent.click(screen.getByRole("option", { name: /Alpha Serum/ }));
		fireEvent.click(screen.getByRole("button", { name: "Remove Alpha Serum" }));
		expect(
			screen.queryByText("Ready for governed planning"),
		).not.toBeInTheDocument();
	});
});
