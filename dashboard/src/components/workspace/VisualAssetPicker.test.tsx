import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import VisualAssetPicker from "./VisualAssetPicker";

const items = [
	{ value: "BOS_A", title: "Aina", subtitle: "BOS_A", previewUrl: "/a.jpg" },
	{ value: "BOS_B", title: "Nadia", subtitle: "BOS_B" },
];

describe("VisualAssetPicker", () => {
	afterEach(cleanup);

	it("renders previews and opens and closes them without changing selection", () => {
		const onChange = vi.fn();
		render(<VisualAssetPicker items={items} label="Avatar" onChange={onChange} value="" />);

		expect(screen.getByRole("img", { name: "Preview of Aina" })).toBeTruthy();
		fireEvent.click(screen.getByRole("button", { name: "Preview Aina" }));
		expect(screen.getByRole("dialog", { name: "Image preview" })).toBeTruthy();
		expect(onChange).not.toHaveBeenCalled();

		fireEvent.click(screen.getByRole("button", { name: "Close preview" }));
		expect(screen.queryByRole("dialog", { name: "Image preview" })).toBeNull();
		expect(onChange).not.toHaveBeenCalled();
	});

	it("selects cards explicitly and retains the missing-preview fallback", () => {
		const onChange = vi.fn();
		render(<VisualAssetPicker items={items} label="Avatar" onChange={onChange} value="" />);

		fireEvent.click(screen.getByRole("button", { name: /Aina BOS_A/ }));
		expect(onChange).toHaveBeenCalledWith("BOS_A");

		fireEvent.change(screen.getByLabelText("Avatar search"), {
			target: { value: "Nadia" },
		});
		expect(screen.getByText("Preview unavailable")).toBeTruthy();
		fireEvent.click(screen.getByRole("button", { name: /Nadia BOS_B/ }));
		expect(onChange).toHaveBeenLastCalledWith("BOS_B");
	});
});
