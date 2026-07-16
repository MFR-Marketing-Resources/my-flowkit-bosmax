/**
 * BOSMAX RPA — Round A rendered locator audit (Copy Set rows + product options).
 *
 * Governance: docs/bosmax-rpa-g0-governance-gate.md (G0 gate), amendment M6.
 * Round A's acceptance proof is a FALSIFIABLE rendered locator audit for
 * "Copy Set and Hybrid Steps 1-5". Steps 1-5 are covered by
 * pages/OperatorPage.rpaSelectors.component.test.tsx; this file covers the two
 * child surfaces that carry the immutable-ID-keyed locators.
 *
 * Every state-bearing selector is asserted in AT LEAST TWO distinct states.
 * Read-only DOM contract: no clicking of generate actions, no approval writes.
 */
import "@testing-library/jest-dom/vitest";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CopySet } from "../../types";

const listCopySetsForProduct = vi.fn();
vi.mock("../../api/copySets", () => ({
	approveCopySet: vi.fn(),
	generateAICopyCandidate: vi.fn(),
	generateCopySet: vi.fn(),
	listCopySetsForProduct: (...args: unknown[]) =>
		listCopySetsForProduct(...args),
}));

import CopySelectionPanel from "./CopySelectionPanel";
import SearchableProductSelect from "./SearchableProductSelect";

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

function copySet(over: Partial<CopySet> & { copy_set_id: string }): CopySet {
	return {
		product_id: "p1",
		angle: "a",
		hook: "h",
		subhook: "s",
		usp_set: [],
		cta: "c",
		platform: "TIKTOK",
		language: "MS",
		route_type: "UGC",
		formula_family: "F",
		status: "DRAFT_COPY",
		dedupe_key: "d",
		source: "manual",
		provenance: {},
		claim_review: {},
		...over,
	} as CopySet;
}

describe("RPA Round A — Copy Set row locators", () => {
	it("keys each row by immutable copy_set_id and exposes status + approval + selected in TWO states", async () => {
		listCopySetsForProduct.mockResolvedValue({
			items: [
				copySet({
					copy_set_id: "cs-approved",
					status: "COPY_APPROVED",
					approved_by: "operator",
				} as Partial<CopySet> & { copy_set_id: string }),
				copySet({ copy_set_id: "cs-draft", status: "DRAFT_COPY" }),
			],
		});

		render(
			<CopySelectionPanel
				productId="p1"
				selectedCopySetId="cs-approved"
				onSelect={vi.fn()}
			/>,
		);

		await waitFor(() =>
			expect(screen.getAllByTestId("copy-set-row")).toHaveLength(2),
		);
		const rows = screen.getAllByTestId("copy-set-row");
		const byId = new Map(
			rows.map((r) => [r.getAttribute("data-copy-set-id"), r]),
		);

		// State 1 — approved AND selected.
		const approved = byId.get("cs-approved");
		expect(approved).toBeDefined();
		expect(approved).toHaveAttribute("data-status", "COPY_APPROVED");
		expect(approved).toHaveAttribute("data-approved", "true");
		expect(approved).toHaveAttribute("data-selected", "true");

		// State 2 — NOT approved AND NOT selected. Two distinct states => falsifiable.
		const draft = byId.get("cs-draft");
		expect(draft).toBeDefined();
		expect(draft).toHaveAttribute("data-status", "DRAFT_COPY");
		expect(draft).toHaveAttribute("data-approved", "false");
		expect(draft).toHaveAttribute("data-selected", "false");
	});

	it("exposes the approval actor so an RPA run is forensically distinguishable", async () => {
		// G0 amendment M7: approval carries no server-side actor identity today.
		// Surfacing approved_by does not fix that; it makes the gap auditable.
		listCopySetsForProduct.mockResolvedValue({
			items: [
				copySet({
					copy_set_id: "cs-1",
					status: "COPY_APPROVED",
					approved_by: "operator",
				} as Partial<CopySet> & { copy_set_id: string }),
			],
		});
		render(
			<CopySelectionPanel
				productId="p1"
				selectedCopySetId={null}
				onSelect={vi.fn()}
			/>,
		);
		await waitFor(() =>
			expect(screen.getByTestId("copy-set-row")).toBeInTheDocument(),
		);
		expect(screen.getByTestId("copy-set-row")).toHaveAttribute(
			"data-approved-by",
			"operator",
		);
	});
});

describe("RPA Round A — product option locators", () => {
	const products = [
		{
			id: "prod-1",
			raw_product_title: "Alpha",
			product_display_name: "Alpha",
			product_short_name: "Alpha",
		},
		{
			id: "prod-2",
			raw_product_title: "Beta",
			product_display_name: "Beta",
			product_short_name: "Beta",
		},
	];

	it("keys each option by the IMMUTABLE product id, in TWO selection states", () => {
		render(
			// biome-ignore lint/suspicious/noExplicitAny: test fixture is a partial Product
			<SearchableProductSelect
				products={products as any}
				selectedProduct={products[0] as any}
				onSelect={vi.fn()}
				readinessByProductId={{}}
				isLoadingReadiness={false}
			/>,
		);

		// The option list is collapsed until the picker is opened — this is also
		// state 0 of the audit: the locator must NOT exist while closed.
		expect(screen.queryAllByTestId("product-option")).toHaveLength(0);
		fireEvent.click(screen.getAllByRole("button")[0]);

		const options = screen.getAllByTestId("product-option");
		expect(options.length).toBeGreaterThanOrEqual(2);
		const byId = new Map(
			options.map((o) => [o.getAttribute("data-product-id"), o]),
		);

		// State 1 — selected. State 2 — not selected. Never matched by title text.
		expect(byId.get("prod-1")).toHaveAttribute("data-selected", "true");
		expect(byId.get("prod-2")).toHaveAttribute("data-selected", "false");
	});
});
