import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import T2VModule from "./T2VModule";
import SearchableProductSelect from "./SearchableProductSelect";
import { searchProducts } from "../../api/products";
import type { Product, WorkspaceExecutionPackage } from "../../types";

vi.mock("../../api/products", () => ({
	searchProducts: vi.fn(),
}));

// A T2V package compiled from an approved Copy Set — copy_binding proves the run
// carries approved copy (the SEND path does not rebuild, so this is the binding).
const boundPkg = {
	product_id: "p1",
	mode: "T2V",
	prompt_text: "Anak kembung perut, ibu urut dengan minyak",
	model: "Veo 3.1 - Lite",
	aspect_ratio: "9:16",
	request_lineage_payload: { asset_fingerprints: [] },
	copy_binding: {
		copy_source: "selected_copy_set",
		copy_set_id: "cs1",
		copy_binding_status: "BOUND",
	},
} as unknown as WorkspaceExecutionPackage;

describe("T2VModule copy-binding gate (Phase B enforcement)", () => {
	afterEach(() => cleanup());

	it("[gate] NOT READY / no copy-bound package → SEND blocked until explicit fallback", async () => {
		const onExecute = vi.fn();
		render(
			<T2VModule
				onExecute={onExecute}
				isExecuting={false}
				workspacePackage={null}
				copyReady={false}
			/>,
		);

		// Manual prompt present but no copy binding → gate visible, SEND blocked.
		fireEvent.change(screen.getByPlaceholderText(/No reference images/i), {
			target: { value: "manual generic copy" },
		});
		const btn = screen.getByRole("button", { name: /SEND TO FLOW EDITOR/i });
		expect(screen.getByTestId("copy-binding-gate")).toBeInTheDocument();
		expect(btn).toBeDisabled();

		// Explicit fallback confirmation unblocks SEND and is recorded in the payload.
		fireEvent.click(screen.getByTestId("copy-fallback-confirm"));
		await waitFor(() => expect(btn).not.toBeDisabled());
		fireEvent.click(btn);

		expect(onExecute).toHaveBeenCalledTimes(1);
		const call = onExecute.mock.calls[0][0];
		expect(call).toMatchObject({
			mode: "T2V",
			copy_set_id: null,
			copy_fallback_confirmed: true,
		});
		expect(call.request_lineage_payload.copy_binding_gate.copy_bound).toBe(false);
	});

	it("[allow] copy-bound package → no gate, SEND allowed, payload carries copy_set_id", async () => {
		const onExecute = vi.fn();
		render(
			<T2VModule
				onExecute={onExecute}
				isExecuting={false}
				workspacePackage={boundPkg}
				copyReady={true}
			/>,
		);

		// Package hydrates the prompt; copy-bound → no gate, SEND enabled immediately.
		const btn = await screen.findByRole("button", { name: /SEND TO FLOW EDITOR/i });
		expect(screen.queryByTestId("copy-binding-gate")).not.toBeInTheDocument();
		await waitFor(() => expect(btn).not.toBeDisabled());
		fireEvent.click(btn);

		expect(onExecute).toHaveBeenCalledTimes(1);
		expect(onExecute.mock.calls[0][0]).toMatchObject({
			mode: "T2V",
			copy_set_id: "cs1",
			copy_fallback_confirmed: false,
		});
	});
});

describe("SearchableProductSelect generation safety", () => {
	const canonicalProduct = {
		id: "canonical-mwtcb",
		raw_product_title: "Minyak Warisan Tok Cap Burung 25ml",
		product_display_name: "Minyak Warisan Tok Cap Burung 25ml",
		product_short_name: "Minyak Cap Burung",
		source: "MANUAL",
	} as Product;
	const referenceProduct = {
		id: "fastmoss-ref:515b48d0d43fe085",
		raw_product_title: "FastMoss Reference Oil",
		product_display_name: "FastMoss Reference Oil",
		product_short_name: "FastMoss Reference Oil",
		source: "FASTMOSS",
		reference_only: true,
	} as Product;

	afterEach(() => {
		cleanup();
		vi.clearAllMocks();
	});

	it("does not select a reference-only product", () => {
		const onSelect = vi.fn();
		render(
			<SearchableProductSelect
				products={[referenceProduct]}
				selectedProduct={null}
				onSelect={onSelect}
			/>,
		);

		fireEvent.click(screen.getByRole("button", { name: /Search and select product/i }));
		fireEvent.click(screen.getByText("FastMoss Reference Oil"));

		expect(onSelect).not.toHaveBeenCalled();
	});

	it("clears prior-query server rows before the next search resolves", async () => {
		vi.mocked(searchProducts).mockResolvedValueOnce({
			items: [canonicalProduct],
		} as Awaited<ReturnType<typeof searchProducts>>);
		const onSelect = vi.fn();
		render(
			<SearchableProductSelect products={[]} selectedProduct={null} onSelect={onSelect} />,
		);

		fireEvent.click(screen.getByRole("button", { name: /Search and select product/i }));
		const input = screen.getByPlaceholderText("Search all products by name...");
		fireEvent.change(input, { target: { value: "warisan" } });
		await waitFor(() => expect(searchProducts).toHaveBeenCalledWith("warisan", 25, "GENERATION"));
		await screen.findByText("Minyak Warisan Tok Cap Burung 25ml");

		fireEvent.change(input, { target: { value: "serum" } });

		expect(screen.queryByText("Minyak Warisan Tok Cap Burung 25ml")).not.toBeInTheDocument();
	});

	it("ignores a delayed prior-query response after a newer query resolves", async () => {
		let resolveFirstQuery: (value: Awaited<ReturnType<typeof searchProducts>>) => void;
		const firstQuery = new Promise<Awaited<ReturnType<typeof searchProducts>>>(
			(resolve) => {
				resolveFirstQuery = resolve;
			},
		);
		const serumProduct = {
			...canonicalProduct,
			id: "canonical-serum",
			raw_product_title: "BOSMAX Serum",
			product_display_name: "BOSMAX Serum",
		} as Product;
		vi.mocked(searchProducts)
			.mockReturnValueOnce(firstQuery)
			.mockResolvedValueOnce({
				items: [serumProduct],
			} as Awaited<ReturnType<typeof searchProducts>>);

		render(
			<SearchableProductSelect products={[]} selectedProduct={null} onSelect={vi.fn()} />,
		);
		fireEvent.click(screen.getByRole("button", { name: /Search and select product/i }));
		const input = screen.getByPlaceholderText("Search all products by name...");
		fireEvent.change(input, { target: { value: "warisan" } });
		await waitFor(() => expect(searchProducts).toHaveBeenCalledWith("warisan", 25, "GENERATION"));

		fireEvent.change(input, { target: { value: "serum" } });
		await waitFor(() => expect(searchProducts).toHaveBeenCalledWith("serum", 25, "GENERATION"));
		await screen.findByText("BOSMAX Serum");

		resolveFirstQuery!({
			items: [canonicalProduct],
		} as Awaited<ReturnType<typeof searchProducts>>);
		await new Promise((resolve) => window.setTimeout(resolve, 0));

		expect(screen.queryByText("Minyak Warisan Tok Cap Burung 25ml")).not.toBeInTheDocument();
		expect(screen.getByText("BOSMAX Serum")).toBeInTheDocument();
	});

	it("clears stale results and displays the current-query search error", async () => {
		vi.mocked(searchProducts)
			.mockResolvedValueOnce({
				items: [canonicalProduct],
			} as Awaited<ReturnType<typeof searchProducts>>)
			.mockRejectedValueOnce(new Error("Catalog unavailable"));

		render(
			<SearchableProductSelect products={[]} selectedProduct={null} onSelect={vi.fn()} />,
		);
		fireEvent.click(screen.getByRole("button", { name: /Search and select product/i }));
		const input = screen.getByPlaceholderText("Search all products by name...");
		fireEvent.change(input, { target: { value: "warisan" } });
		await screen.findByText("Minyak Warisan Tok Cap Burung 25ml");

		fireEvent.change(input, { target: { value: "broken" } });
		await screen.findByText("Catalog unavailable");

		expect(screen.queryByText("Minyak Warisan Tok Cap Burung 25ml")).not.toBeInTheDocument();
	});
});
