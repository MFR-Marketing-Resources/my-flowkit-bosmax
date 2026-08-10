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

function makeCopySet(
	id: string,
	angle = "Problem-Agitate",
	status: CopySet["status"] = "COPY_APPROVED",
	opts: Partial<CopySet> = {},
): CopySet {
	const productionValid = status === "COPY_APPROVED" && opts.production_valid !== false;
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
		archived: 0,
		// #688 contract defaults: approved fixtures are production-valid unless overridden.
		workflow_status: status,
		production_valid: productionValid,
		validity_class: productionValid ? "APPROVED_COPY_VALID" : "APPROVED_COPY_STALE",
		validity_class_label: productionValid ? "VALID" : "STALE PI",
		validity_reasons: productionValid ? [] : ["PI_SNAPSHOT_MISMATCH"],
		recommended_action: productionValid ? "READY" : "REVALIDATE_APPROVED",
		validity_primary_reason: productionValid ? null : "STALE",
		validity_stale: !productionValid,
		...opts,
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

		// Collapsed view shows a one-line subhook PREVIEW (variant disambiguation)
		// but not the full details (USP/CTA stay behind the toggle).
		expect(screen.getByTestId("copy-subhook-preview")).toHaveTextContent(
			"Subhook for cs-1",
		);
		expect(screen.queryByText("USP 1 · USP 2")).not.toBeInTheDocument();

		const toggleBtn = screen.getByTestId("toggle-copy-details");
		fireEvent.click(toggleBtn);

		// Expanded: the details section owns the subhook; the preview collapses away.
		expect(screen.queryByTestId("copy-subhook-preview")).not.toBeInTheDocument();
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

describe("CopySelectionPanel — honest angle counts (anti-monoculture display)", () => {
	it("labels the ALL filter with BOTH distinct-angle and set counts for a monoculture", async () => {
		// Real-world shape (Sambal Nyet 2026-08-02): 3 sets, ONE angle, 2 hooks.
		const sets = [
			{ ...makeCopySet("cs-1", "Pedas Berapi"), hook: "Hook A" },
			{ ...makeCopySet("cs-2", "Pedas Berapi"), hook: "Hook B" },
			{ ...makeCopySet("cs-3", "Pedas Berapi"), hook: "Hook A" },
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
			expect(screen.getAllByTestId("copy-set-row")).toHaveLength(3);
		});

		// The old label read "All Angles (3)" here — implying 3 angles. It is 1.
		expect(
			screen.getByText("All Angles (1 angle · 3 sets)"),
		).toBeInTheDocument();
		expect(screen.getByText("Pedas Berapi (3 sets)")).toBeInTheDocument();
	});

	it("pluralizes both units when multiple distinct angles exist", async () => {
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

		expect(
			screen.getByText("All Angles (3 angles · 4 sets)"),
		).toBeInTheDocument();
		expect(screen.getByText("Empathy (2 sets)")).toBeInTheDocument();
		expect(screen.getByText("Urgency (1 set)")).toBeInTheDocument();
	});

	it("distinguishes same-angle same-hook rows by their subhook previews", async () => {
		const sets = [
			{
				...makeCopySet("cs-1", "Pedas Berapi"),
				hook: "Bosan dengan sambal viral",
				subhook: "Variant satu: rasa pedas sekadar lalu",
			},
			{
				...makeCopySet("cs-3", "Pedas Berapi"),
				hook: "Bosan dengan sambal viral",
				subhook: "Variant dua: tak pernah dapat kick",
			},
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
			expect(screen.getAllByTestId("copy-set-row")).toHaveLength(2);
		});

		const previews = screen.getAllByTestId("copy-subhook-preview");
		expect(previews).toHaveLength(2);
		expect(previews[0]).toHaveTextContent("Variant satu");
		expect(previews[1]).toHaveTextContent("Variant dua");
		expect(previews[0].textContent).not.toEqual(previews[1].textContent);
	});
});

describe("CopySelectionPanel — production validity contract (#688)", () => {
	it("blocks Select for Final Prompt when approved but not production-valid", async () => {
		const sets = [
			makeCopySet("stale-1", "Empathy", "COPY_APPROVED", {
				production_valid: false,
				validity_class: "APPROVED_COPY_STALE",
				validity_class_label: "STALE PI",
				validity_reasons: ["PI_SNAPSHOT_MISMATCH"],
				recommended_action: "REVALIDATE_APPROVED",
			}),
		];
		listCopySetsForProduct.mockResolvedValue({ items: sets });
		const onSelect = vi.fn();
		render(
			<CopySelectionPanel productId="p1" selectedCopySetId={null} onSelect={onSelect} />,
		);
		await waitFor(() => {
			expect(screen.getByTestId("copy-set-row")).toBeInTheDocument();
		});
		expect(screen.getByTestId("copy-select-blocked")).toBeInTheDocument();
		expect(screen.queryByTestId("select-copy-for-final-prompt")).not.toBeInTheDocument();
		expect(screen.getByTestId("copy-production-valid-count")).toHaveTextContent("0");
		expect(screen.getByTestId("copy-raw-approved-count")).toHaveTextContent("1");
	});

	it("allows Select for Final Prompt only for production-valid approved sets", async () => {
		const sets = [
			makeCopySet("good-1", "Empathy", "COPY_APPROVED", { production_valid: true }),
			makeCopySet("stale-1", "Empathy", "COPY_APPROVED", {
				production_valid: false,
				validity_class: "APPROVED_COPY_MISSING_REVIEW",
				validity_class_label: "MISSING REVIEW",
			}),
		];
		listCopySetsForProduct.mockResolvedValue({ items: sets });
		render(
			<CopySelectionPanel productId="p1" selectedCopySetId={null} onSelect={vi.fn()} />,
		);
		await waitFor(() => {
			expect(screen.getAllByTestId("copy-set-row")).toHaveLength(2);
		});
		expect(screen.getAllByTestId("select-copy-for-final-prompt")).toHaveLength(1);
		expect(screen.getAllByTestId("copy-select-blocked")).toHaveLength(1);
		expect(screen.getByTestId("copy-production-valid-count")).toHaveTextContent("1");
		expect(screen.getByTestId("copy-raw-approved-count")).toHaveTextContent("2");
	});
});
