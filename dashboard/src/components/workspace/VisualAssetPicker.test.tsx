import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import VisualAssetPicker from "./VisualAssetPicker";

const items = [
	{
		value: "BOS_A",
		title: "Aina",
		subtitle: "BOS_A",
		previewUrl: "/a.jpg",
		status: "APPROVED",
	},
	{ value: "BOS_B", title: "Nadia", subtitle: "BOS_B", status: "APPROVED" },
];

describe("VisualAssetPicker", () => {
	afterEach(cleanup);

	it("renders a compact selected field and opens previews without changing selection", () => {
		const onChange = vi.fn();
		render(<VisualAssetPicker items={items} label="Avatar" onChange={onChange} value="" />);

		expect(screen.queryByRole("img", { name: "Preview of Aina" })).toBeNull();
		fireEvent.click(screen.getByRole("button", { name: "Avatar visual combobox" }));
		expect(screen.getByRole("img", { name: "Preview of Aina" })).toBeTruthy();
		fireEvent.click(screen.getByRole("button", { name: "Preview Aina" }));
		expect(screen.getByRole("dialog", { name: "Image preview" })).toBeTruthy();
		expect(onChange).not.toHaveBeenCalled();

		fireEvent.click(screen.getByRole("button", { name: "Close preview" }));
		expect(screen.queryByRole("dialog", { name: "Image preview" })).toBeNull();
		expect(onChange).not.toHaveBeenCalled();
	});

	it("filters rows, exposes status, and changes value only through explicit select", () => {
		const onChange = vi.fn();
		render(<VisualAssetPicker items={items} label="Avatar" onChange={onChange} value="" />);

		fireEvent.click(screen.getByRole("button", { name: "Avatar visual combobox" }));
		expect(screen.getAllByText("APPROVED")).toHaveLength(2);
		fireEvent.change(screen.getByLabelText("Avatar search"), {
			target: { value: "Aina" },
		});
		expect(screen.queryByText("Nadia")).toBeNull();
		fireEvent.click(screen.getByRole("button", { name: "Select Aina" }));
		expect(onChange).toHaveBeenCalledWith("BOS_A");
		expect(screen.queryByRole("listbox", { name: "Avatar options" })).toBeNull();
	});

	it("shows selected check state and keeps the missing-preview row selectable", () => {
		const onChange = vi.fn();
		render(<VisualAssetPicker items={items} label="Avatar" onChange={onChange} value="BOS_A" />);

		expect(screen.getByLabelText("Selected")).toBeTruthy();
		fireEvent.click(screen.getByRole("button", { name: "Avatar visual combobox" }));
		expect(screen.getByText("Preview unavailable")).toBeTruthy();
		fireEvent.click(screen.getByRole("button", { name: "Select Nadia" }));
		expect(onChange).toHaveBeenCalledWith("BOS_B");
	});

	it("renders loading, empty, and error states inside the bounded dropdown", () => {
		const { rerender } = render(
			<VisualAssetPicker
				isLoading
				items={[]}
				label="Scene"
				onChange={vi.fn()}
				value=""
			/>,
		);
		fireEvent.click(screen.getByRole("button", { name: "Scene visual combobox" }));
		expect(screen.getByText("Loading visual assets…")).toBeTruthy();

		rerender(
			<VisualAssetPicker
				items={[]}
				label="Scene"
				onChange={vi.fn()}
				value=""
			/>,
		);
		expect(screen.getByText("No visual assets available.")).toBeTruthy();

		rerender(
			<VisualAssetPicker
				error="Registry unavailable"
				items={[]}
				label="Scene"
				onChange={vi.fn()}
				value=""
			/>,
		);
		expect(screen.getByText("Registry unavailable")).toBeTruthy();
	});
});
