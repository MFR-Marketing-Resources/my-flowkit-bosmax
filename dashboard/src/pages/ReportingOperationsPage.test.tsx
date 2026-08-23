import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ReportingOperationsPage from "./ReportingOperationsPage";
import { useExceptionPage, useExceptions, usePiQuality } from "../api/reporting";

// Mission-08D: the INTEL QUALITY DEBT card is the operator-visible face of the four-way
// PI classification. These tests pin the contract: backend numbers rendered verbatim
// (no frontend counting), legacy never relabelled, click drills into the matching kind.

const SUMMARY = {
	total_real_products: 651,
	test_fixtures_excluded: 8,
	classes: {
		FULLY_COMPLETE: { total: 121, active: 100, archived: 21 },
		APPROVED_WITH_GOVERNED_ABSENCE: { total: 1, active: 1, archived: 0 },
		LEGACY_APPROVED_INCOMPLETE: { total: 319, active: 300, archived: 19 },
		MISSING_APPROVED_INTELLIGENCE: { total: 210, active: 20, archived: 190 },
	},
	drill_down_kinds: {
		FULLY_COMPLETE: "pi_fully_complete",
		APPROVED_WITH_GOVERNED_ABSENCE: "pi_governed_absence",
		LEGACY_APPROVED_INCOMPLETE: "pi_legacy_incomplete",
		MISSING_APPROVED_INTELLIGENCE: "pi_missing_approved",
	},
} as const;

const ACTIVE_SUMMARY = {
	total_real_products: 421,
	test_fixtures_excluded: 5,
	classes: {
		FULLY_COMPLETE: { total: 100, active: 100, archived: 0 },
		APPROVED_WITH_GOVERNED_ABSENCE: { total: 1, active: 1, archived: 0 },
		LEGACY_APPROVED_INCOMPLETE: { total: 300, active: 300, archived: 0 },
		MISSING_APPROVED_INTELLIGENCE: { total: 20, active: 20, archived: 0 },
	},
	drill_down_kinds: SUMMARY.drill_down_kinds,
} as const;


vi.mock("../api/reporting", async (importOriginal) => {
	const actual = await importOriginal<typeof import("../api/reporting")>();
	return {
		...actual,
		usePiQuality: vi.fn((lifecycle: "ACTIVE" | "ALL") => ({
			data: lifecycle === "ALL" ? SUMMARY : ACTIVE_SUMMARY,
			loading: false,
			error: null,
		})),
		useExceptions: vi.fn(() => ({ data: null, loading: false, error: null })),
		useExceptionPage: vi.fn((kind: string, filters: { lifecycle_status: string }) => {
			const legacyTotal = filters.lifecycle_status === "ALL" ? 319 : 300;
			return {
				data: {
					total: kind === "pi_legacy_incomplete" ? legacyTotal : 1,
					items: [], stage_breakdown: {},
				},
				loading: false,
				error: null,
			};
		}),
		useFailedGenerations: vi.fn(() => ({ data: null, loading: false, error: null })),
	};
});

const renderPage = () =>
	render(
		<MemoryRouter>
			<ReportingOperationsPage />
		</MemoryRouter>,
	);

describe("Operations — INTEL QUALITY DEBT (08D)", () => {
	beforeEach(() => {
		vi.mocked(useExceptionPage).mockClear();
		vi.mocked(useExceptions).mockClear();
		vi.mocked(usePiQuality).mockClear();
	});

	afterEach(() => cleanup());

	it("keeps Operations on ACTIVE scope and removes the archived selector", async () => {
		renderPage();
		const card = await screen.findByTestId("intel-quality-debt-card");
		await waitFor(() => expect(usePiQuality).toHaveBeenCalledWith("ACTIVE"));
		expect(card).toHaveTextContent("300");
		expect(card).toHaveTextContent("20");
		expect(screen.queryByRole("button", { name: /All \(incl\. archived\)/i })).not.toBeInTheDocument();
		expect(vi.mocked(usePiQuality).mock.calls.every(([lifecycle]) => lifecycle === "ACTIVE")).toBe(true);
		expect(vi.mocked(useExceptions).mock.calls.every(([, filters]) => filters.lifecycle_status === "ACTIVE")).toBe(true);
		expect(vi.mocked(useExceptionPage).mock.calls.every(([, filters]) => filters.lifecycle_status === "ACTIVE")).toBe(true);
	});

	it("renames the copy card while preserving the missing_copy drill-down", async () => {
		renderPage();
		const copyCard = await screen.findByRole("button", {
			name: /Missing production copy authority/i,
		});
		expect(screen.queryByText("Missing copywriting")).not.toBeInTheDocument();
		fireEvent.click(copyCard);
		await waitFor(() => {
			const call = vi.mocked(useExceptionPage).mock.calls.at(-1);
			expect(call?.[0]).toBe("missing_copy");
			expect(call?.[1]).toMatchObject({ lifecycle_status: "ACTIVE" });
		});
	});

	it("keeps the other operational cards present", async () => {
		renderPage();
		for (const label of [
			"Missing product intel",
			"Missing image",
			"Missing cluster",
			"Missing product type",
			"Mapping blocked",
			"Prompt not ready",
			"Scene strategy gaps",
		]) {
			expect(await screen.findByRole("button", { name: new RegExp(label) })).toBeInTheDocument();
		}
	});

	it("maps a class to the exact server kind and keeps card/table totals equal", async () => {
		renderPage();
		const card = await screen.findByTestId("intel-quality-debt-card");
		fireEvent.click(
			(await screen.findAllByText("Legacy approved incomplete"))[0],
		);
		expect(card).toHaveTextContent("300");
		expect(
			await screen.findByRole("heading", { name: /Legacy approved incomplete/i }),
		).toBeInTheDocument();
		expect(screen.getByTestId("exception-range")).toHaveTextContent("1–15 of 300");
		await waitFor(() => {
			const call = vi.mocked(useExceptionPage).mock.calls.at(-1);
			expect(call?.[0]).toBe("pi_legacy_incomplete");
			expect(call?.[1]).toMatchObject({ lifecycle_status: "ACTIVE" });
			expect(call?.[2]).toMatchObject({ limit: 15, offset: 0 });
		});
	});

	it("forwards server pagination, search, and sort over the whole class cohort", async () => {
		renderPage();
		fireEvent.click(
			(await screen.findAllByText("Legacy approved incomplete"))[0],
		);
		fireEvent.click(await screen.findByRole("button", { name: "Next" }));
		await waitFor(() => {
			const call = vi.mocked(useExceptionPage).mock.calls.at(-1);
			expect(call?.[2]).toMatchObject({ offset: 15 });
		});

		fireEvent.change(screen.getByLabelText("Search all products"), {
			target: { value: "nakamichi" },
		});
		await waitFor(() => {
			const call = vi.mocked(useExceptionPage).mock.calls.at(-1);
			expect(call?.[2]).toMatchObject({ q: "nakamichi", offset: 0 });
		});

		fireEvent.click(screen.getByRole("button", { name: /^Product$/i }));
		await waitFor(() => {
			const call = vi.mocked(useExceptionPage).mock.calls.at(-1);
			expect(call?.[2]).toMatchObject({
				sort_by: "product_display_name",
				sort_dir: "asc",
				offset: 0,
			});
		});
	});
});
