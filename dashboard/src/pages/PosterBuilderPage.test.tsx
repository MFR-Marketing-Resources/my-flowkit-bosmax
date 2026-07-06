import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import PosterBuilderPage from "./PosterBuilderPage";

vi.mock("../components/workspace/SearchableProductSelect", () => ({
	default: () => <div data-testid="product-picker">Product picker</div>,
}));

vi.mock("../api/products", () => ({
	fetchProductCatalog: vi.fn().mockResolvedValue({
		items: [
			{
				id: "p1",
				raw_product_title: "Test Product",
				product_display_name: "Test Product",
				product_short_name: "Test",
				source: "MANUAL",
				category: "Oil",
			},
		],
	}),
}));

vi.mock("../api/posterReadiness", () => ({
	fetchPosterReadiness: vi.fn().mockResolvedValue({
		product_id: "p1",
		product_display_name: "Test Product",
		poster_status: "POSTER_READY",
		generation_allowed: true,
		restricted_generation_required: false,
		preview_allowed: true,
		production_allowed: true,
		blockers: [],
		repair_actions: [],
		image_tier: "PRODUCT_HERO_POSTER_READY",
		claim_route: {
			safe_claim_clearance_required: false,
			safe_claim_clearance_status: "NOT_REQUIRED",
			restricted_safe_poster_route_verified: false,
		},
		mapping_route: { mapping_ready: true },
		approval_route: { img_approved: true, approved_modes: ["IMG"] },
		recheck_required_after_repair: false,
		notes: [],
	}),
}));

describe("PosterBuilderPage", () => {
	it("renders poster builder heading", async () => {
		render(
			<MemoryRouter initialEntries={["/creative/poster-builder?product_id=p1"]}>
				<PosterBuilderPage />
			</MemoryRouter>,
		);
		await waitFor(() => {
			expect(screen.getByText("Poster Builder")).toBeInTheDocument();
		});
	});
});