import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProductReleaseControlPage from "./ProductReleaseControlPage";
import { useAuth } from "../auth/AuthContext";
import {
	bulkUpdateProductRelease,
	fetchProductReleaseControl,
	hideProduct,
	releaseProduct,
	type ProductReleaseResponse,
	type ProductReleaseRow,
} from "../api/productRelease";

vi.mock("../auth/AuthContext", () => ({
	useAuth: vi.fn(),
}));

vi.mock("../api/productRelease", () => ({
	bulkUpdateProductRelease: vi.fn(),
	fetchProductReleaseControl: vi.fn(),
	hideProduct: vi.fn(),
	releaseProduct: vi.fn(),
}));

function makeRow(index: number): ProductReleaseRow {
	const id = `p-${index}`;
	const visual = index === 1
		? {
			product_id: id,
			current_system_visual: { status: "OFFICIAL", card: "MANUAL_CUTOUT", label: "Manual / Canva Cutout" },
			active_visual_source: "APPROVED_MANUAL_CANONICAL_CUTOUT",
			active_cutout_preview_url: `/api/product-visual-onboarding/${id}/cutout/preview/active`,
			original_preview_url: `/api/product-visual-onboarding/${id}/cutout/preview/original`,
			exact_commerce_status: "EXACT_COMMERCE_CUTOUT_READY",
			canonical_media_status: "AVAILABLE",
		}
		: index === 3
			? {
				product_id: id,
				current_system_visual: { status: "BLOCKED", card: null, label: null },
				active_visual_source: "BLOCKED",
				exact_commerce_status: "EXACT_COMMERCE_BLOCKED",
				canonical_media_status: "MISSING",
			}
			: {
				product_id: id,
				current_system_visual: { status: "ORIGINAL_FALLBACK", card: "ORIGINAL_SOURCE", label: "Original Source" },
				active_visual_source: "SAME_PRODUCT_TRUSTED_SOURCE",
				original_preview_url: `/api/product-visual-onboarding/${id}/cutout/preview/original`,
				original_display_url: `https://cdn.example.test/${id}.jpg`,
				exact_commerce_status: "CUTOUT_REQUIRED",
				canonical_media_status: "AVAILABLE",
			};

	return {
		id,
		raw_product_title: `Product ${index}`,
		product_display_name: `Product ${index}`,
		product_short_name: `Product ${index}`,
		lifecycle_status: "ACTIVE",
		staff_release_status: "HIDDEN",
		minimum_eligibility_status: index === 3 ? "BLOCKED" : "ELIGIBLE",
		current_minimum_eligibility: index !== 3,
		operationally_visible: false,
		visibility_reason: index === 3 ? "HIDDEN_AND_BLOCKED" : "OWNER_RELEASE_REQUIRED",
		blocker_codes: index === 3 ? ["VISUAL_CUTOUT_NOT_READY"] : [],
		product_truth_status: "APPROVED",
		mapping_status: "READY",
		prompt_readiness_status: "READY",
		visual_readiness: visual,
	} as unknown as ProductReleaseRow;
}

function pageResponse(limit = 50, offset = 0): ProductReleaseResponse {
	const totalCount = 125;
	const count = Math.max(0, Math.min(limit, totalCount - offset));
	return {
		total_count: totalCount,
		returned_count: count,
		items: Array.from({ length: count }, (_, index) => makeRow(offset + index + 1)),
		limit,
		offset,
		has_pagination: offset + count < totalCount,
		summary: {
			hidden: 100,
			released: 25,
			visible_to_staff: 10,
			released_but_blocked: 5,
			eligible_to_release: 20,
		},
	};
}

function renderPage() {
	return render(
		<MemoryRouter>
			<ProductReleaseControlPage />
		</MemoryRouter>,
	);
}

async function waitForRequest(params: Partial<{ q: string; limit: number; offset: number }>) {
	await waitFor(() => {
		const calls = vi.mocked(fetchProductReleaseControl).mock.calls;
		const last = calls.at(-1)?.[0];
		expect(last).toMatchObject(params);
	});
}

describe("Product Release Control UX", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		vi.mocked(useAuth).mockReturnValue({ hasPermission: () => true } as unknown as ReturnType<typeof useAuth>);
		vi.mocked(fetchProductReleaseControl).mockImplementation(({ limit = 50, offset = 0 } = {}) => Promise.resolve(pageResponse(limit, offset)));
		vi.mocked(releaseProduct).mockResolvedValue({ ok: true, action: "RELEASE" });
		vi.mocked(hideProduct).mockResolvedValue({ ok: true, action: "HIDE" });
		vi.mocked(bulkUpdateProductRelease).mockResolvedValue({ ok: true, action: "RELEASE" });
	});

	afterEach(() => {
		cleanup();
	});

	it("uses the canonical resolver for official, fallback, and no-image cells", async () => {
		renderPage();

		expect(await screen.findByTestId("product-release-thumbnail-p-1")).toHaveAttribute(
			"src",
			"/api/product-visual-onboarding/p-1/cutout/preview/active",
		);
		expect(screen.getByText("OFFICIAL")).toBeInTheDocument();
		expect(screen.getByTestId("product-release-thumbnail-p-2")).toHaveAttribute(
			"src",
			"/api/product-visual-onboarding/p-2/cutout/preview/original",
		);
		expect(within(screen.getByTestId("product-release-visual-p-2")).getByText("ORIGINAL FALLBACK")).toBeInTheDocument();
		expect(screen.getByLabelText("No image available")).toBeInTheDocument();
		expect(screen.getByText("NO OFFICIAL VISUAL")).toBeInTheDocument();
	});

	it("keeps original fallback visibly non-official and readiness-blocked", async () => {
		renderPage();

		await screen.findByTestId("product-release-row-p-3");
		expect(screen.getByTestId("product-release-visual-p-3")).toHaveTextContent("NO OFFICIAL VISUAL");
		expect(screen.getByTestId("product-release-row-p-3")).toHaveTextContent("BLOCKED");
		expect(within(screen.getByTestId("product-release-row-p-3")).getByRole("button", { name: "Release" })).toBeDisabled();
	});

	it("renders full filtered summary counts while requesting only the default page", async () => {
		renderPage();

		expect(await screen.findByTestId("product-release-range")).toHaveTextContent("Showing 1–50 of 125");
		expect(screen.getByTestId("product-release-page")).toHaveTextContent("Page 1 of 3");
		expect(screen.getByTestId("product-release-summary-hidden")).toHaveTextContent("100");
		expect(screen.getByTestId("product-release-summary-released")).toHaveTextContent("25");
		await waitForRequest({ limit: 50, offset: 0 });
		expect(vi.mocked(fetchProductReleaseControl).mock.calls.at(-1)?.[0]?.limit).toBe(50);
	});

	it("moves through First, Previous, Next, and Last using server offsets", async () => {
		renderPage();
		await screen.findByTestId("product-release-range");

		fireEvent.click(screen.getByRole("button", { name: "Next" }));
		await waitForRequest({ limit: 50, offset: 50 });
		expect(screen.getByTestId("product-release-page")).toHaveTextContent("Page 2 of 3");

		fireEvent.click(screen.getByRole("button", { name: "Last" }));
		await waitForRequest({ limit: 50, offset: 100 });
		expect(screen.getByTestId("product-release-range")).toHaveTextContent("Showing 101–125 of 125");

		fireEvent.click(screen.getByRole("button", { name: "Previous" }));
		await waitForRequest({ limit: 50, offset: 50 });
		fireEvent.click(screen.getByRole("button", { name: "First" }));
		await waitForRequest({ limit: 50, offset: 0 });
	});

	it("supports 25/50/100 page sizes and resets page to one", async () => {
		renderPage();
		await screen.findByTestId("product-release-range");
		fireEvent.click(screen.getByRole("button", { name: "Next" }));
		await waitForRequest({ offset: 50 });

		fireEvent.change(screen.getByLabelText("Product release page size"), { target: { value: "25" } });
		await waitForRequest({ limit: 25, offset: 0 });
		expect(screen.getByTestId("product-release-page")).toHaveTextContent("Page 1 of 5");

		fireEvent.change(screen.getByLabelText("Product release page size"), { target: { value: "100" } });
		await waitForRequest({ limit: 100, offset: 0 });
		expect(screen.getByTestId("product-release-page")).toHaveTextContent("Page 1 of 2");
	});

	it("resets the offset for search and every release-control filter", async () => {
		renderPage();
		await screen.findByTestId("product-release-range");

		fireEvent.click(screen.getByRole("button", { name: "Next" }));
		await waitForRequest({ offset: 50 });
		fireEvent.change(screen.getByLabelText("Search products"), { target: { value: "serum" } });
		await waitForRequest({ q: "serum", offset: 0 });

		const filters: Array<[string, string]> = [
			["Release status filter", "HIDDEN"],
			["Visibility filter", "OWNER_RELEASE_REQUIRED"],
			["Eligibility filter", "ELIGIBLE"],
		];
		for (const [label, value] of filters) {
			fireEvent.click(screen.getByRole("button", { name: "Next" }));
			await waitForRequest({ offset: 50 });
			fireEvent.change(screen.getByLabelText(label), { target: { value } });
			await waitForRequest({ offset: 0 });
		}

		fireEvent.click(screen.getByRole("button", { name: "Next" }));
		await waitForRequest({ offset: 50 });
		fireEvent.change(screen.getByLabelText("Blocker filter"), { target: { value: "VISUAL_CUTOUT_NOT_READY" } });
		await waitForRequest({ offset: 0 });
	}, 15000);

	it("selects only the current page and bulk-actions only visible selections", async () => {
		renderPage();
		await screen.findByTestId("product-release-range");
		fireEvent.click(screen.getByLabelText("Select current page"));
		fireEvent.click(screen.getByRole("button", { name: "Next" }));
		await waitForRequest({ offset: 50 });
		await waitFor(() => expect(screen.getByTestId("product-release-range")).toHaveTextContent("Showing 51–100 of 125"));
		expect(screen.getByLabelText("Select current page")).not.toBeChecked();
		expect(screen.getByRole("button", { name: "Release selected" })).toBeDisabled();

		const pageRows = screen.getAllByTestId(/^product-release-row-p-/);
		const selectedIds = pageRows.slice(0, 2).map((row) => String(row.getAttribute("data-testid")).replace("product-release-row-", ""));
		fireEvent.click(within(pageRows[0]).getAllByRole("checkbox")[0]);
		fireEvent.click(within(pageRows[1]).getAllByRole("checkbox")[0]);
		fireEvent.click(screen.getByRole("button", { name: "Release selected" }));
		await waitFor(() => expect(bulkUpdateProductRelease).toHaveBeenCalledWith(selectedIds, "RELEASE", ""));
	}, 15000);

	it("preserves single release/hide actions and OWNER-only visibility", async () => {
		renderPage();
		await screen.findByTestId("product-release-range");
		fireEvent.click(screen.getAllByRole("button", { name: "Release" })[0]);
		await waitFor(() => expect(releaseProduct).toHaveBeenCalledWith("p-1", ""));

		vi.mocked(useAuth).mockReturnValue({ hasPermission: () => false } as unknown as ReturnType<typeof useAuth>);
		cleanup();
		vi.mocked(fetchProductReleaseControl).mockClear();
		renderPage();
		expect(screen.getByText("Only OWNER may view Product Release Control.")).toBeInTheDocument();
		expect(fetchProductReleaseControl).not.toHaveBeenCalled();
	});
});
