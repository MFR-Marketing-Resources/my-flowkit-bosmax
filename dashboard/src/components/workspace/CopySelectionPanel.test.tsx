import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CopySet } from "../../types";

const listCopySetsForProduct = vi.fn();

vi.mock("../../api/copySets", () => ({
	approveCopySet: vi.fn(),
	generateAICopyCandidate: vi.fn(),
	generateCopySet: vi.fn(),
	listCopySetsForProduct: (...args: unknown[]) => listCopySetsForProduct(...args),
}));

import CopySelectionPanel from "./CopySelectionPanel";

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

function makeCopySet(id: string, angle = "Problem-Agitate", status: CopySet["status"] = "COPY_APPROVED"): CopySet {
	return {
		copy_set_id: id,
		product_id: "p1",
		angle,
		hook: `Hook for ${id}`,
		subhook: `Subhook for ${id}`,
		usp_set: ["USP 1", "USP 2"],
		cta: "Buy Now",
		platform: "TIKTOK",
		language: "MS",
		route_type: "UGC",
		formula_family: "PAS",
		status,
		dedupe_key: `dedupe-${id}`,
		source: "manual",
		provenance: {},
		claim_review: {},
		approved_by: status === "COPY_APPROVED" ? "operator" : undefined,
	} as CopySet;
}

describe("CopySelectionPanel — Angle Filtering & Pagination & Details Toggle", () => {
	it("paginates copy sets at 10 items per page by default", async () => {
		const sets = Array.from({ length: 25 }, (_, i) => makeCopySet(`cs-${i + 1}`));
		listCopySetsForProduct.mockResolvedValue({ items: sets });

		render(
			<CopySelectionPanel
				productId="p1"
				selectedCopySetId={null}
				onSelect={vi.fn()}
			/>,
		);

		await waitFor(() => {
			expect(screen.getAllByTestId("copy-set-row")).toHaveLength(10);
		});

		expect(screen.getByText("Showing 1–10 of 25")).toBeInTheDocument();
		expect(screen.getByText("1 / 3")).toBeInTheDocument();

		// Click Next to go to Page 2
		fireEvent.click(screen.getByRole("button", { name: "Next" }));
		expect(screen.getByText("Showing 11–20 of 25")).toBeInTheDocument();
		expect(screen.getByText("2 / 3")).toBeInTheDocument();

		// Click Next to go to Page 3
		fireEvent.click(screen.getByRole("button", { name: "Next" }));
		expect(screen.getAllByTestId("copy-set-row")).toHaveLength(5);
		expect(screen.getByText("Showing 21–25 of 25")).toBeInTheDocument();
	});

	it("filters copy sets by selected angle", async () => {
		const sets = [
			makeCopySet("cs-1", "Empathy"),
			makeCopySet("cs-2", "Empathy"),
			makeCopySet("cs-3", "Urgency"),
			makeCopySet("cs-4", "Social Proof"),
		];
		listCopySetsForProduct.mockResolvedValue({ items: sets });

		render(
			<CopySelectionPanel
				productId="p1"
				selectedCopySetId={null}
				onSelect={vi.fn()}
			/>,
		);

		await waitFor(() => {
			expect(screen.getAllByTestId("copy-set-row")).toHaveLength(4);
		});

		const filterSelect = screen.getByTestId("copy-angle-filter");
		fireEvent.change(filterSelect, { target: { value: "Empathy" } });

		expect(screen.getAllByTestId("copy-set-row")).toHaveLength(2);
		expect(screen.getByText("Showing 1–2 of 2")).toBeInTheDocument();
	});

	it("renders compact hook view by default and expands details on click", async () => {
		const sets = [makeCopySet("cs-1", "Empathy")];
		listCopySetsForProduct.mockResolvedValue({ items: sets });

		render(
			<CopySelectionPanel
				productId="p1"
				selectedCopySetId={null}
				onSelect={vi.fn()}
			/>,
		);

		await waitFor(() => {
			expect(screen.getByTestId("copy-set-row")).toBeInTheDocument();
		});

		// Subhook should not be visible before expanding (unless selected)
		expect(screen.queryByText("Subhook for cs-1")).not.toBeInTheDocument();

		const toggleBtn = screen.getByTestId("toggle-copy-details");
		fireEvent.click(toggleBtn);

		// Now details are visible
		expect(screen.getByText("Subhook for cs-1")).toBeInTheDocument();
		expect(screen.getByText("USP 1 · USP 2")).toBeInTheDocument();
	});

	it("enforces approved-only selection safety", async () => {
		const onSelect = vi.fn();
		const sets = [
			makeCopySet("cs-approved", "Empathy", "COPY_APPROVED"),
			makeCopySet("cs-draft", "Empathy", "DRAFT_COPY"),
		];
		listCopySetsForProduct.mockResolvedValue({ items: sets });

		render(
			<CopySelectionPanel
				productId="p1"
				selectedCopySetId={null}
				onSelect={onSelect}
			/>,
		);

		await waitFor(() => {
			expect(screen.getAllByTestId("copy-set-row")).toHaveLength(2);
		});

		// Approved row has select button
		const selectBtn = screen.getByRole("button", { name: "Select for Final Prompt" });
		fireEvent.click(selectBtn);
		expect(onSelect).toHaveBeenCalledWith("cs-approved");

		// Draft row has Approve button, NOT select button
		const approveBtn = screen.getByRole("button", { name: "Approve Copy Set" });
		expect(approveBtn).toBeInTheDocument();
	});
});
