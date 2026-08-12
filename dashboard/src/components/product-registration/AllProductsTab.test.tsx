import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchProductRegistry, fetchProductStrategyTypeRegistry } from "../../api/products";
import AllProductsTab from "./AllProductsTab";

vi.mock("../../api/products", () => ({
	fetchProductRegistry: vi.fn(),
	fetchProductStrategyTypeRegistry: vi.fn(),
}));

describe("All Products per-product visual scope", () => {
	afterEach(() => {
		cleanup();
		vi.resetAllMocks();
	});

	beforeEach(() => {
		vi.mocked(fetchProductRegistry).mockResolvedValue({
			items: [],
			total_count: 0,
		} as never);
		vi.mocked(fetchProductStrategyTypeRegistry).mockResolvedValue({
			items: [],
			clusters: [],
		} as never);
	});

	it("keeps visual work per product and exposes no bulk cutout controls", async () => {
		render(<AllProductsTab />);

		expect(await screen.findByTestId("per-product-visual-workflow")).toHaveTextContent(
			"Visual work is per product",
		);
		const bodyText = document.body.textContent ?? "";
		expect(bodyText).not.toMatch(/bulk cutout|cutout queue|run all|queue all|pause all|resume all|cancel all/i);
	});

	it("shows the standard canvas note on each product visual row", async () => {
		vi.mocked(fetchProductRegistry).mockResolvedValueOnce({
			items: [
				{
					id: "product-1",
					source: "MANUAL",
					raw_product_title: "Canvas note product",
					product_display_name: "Canvas note product",
					product_short_name: "Canvas note",
					category: null,
					subcategory: null,
					type: null,
					shop_name: null,
					price: null,
					currency: null,
					commission_amount: null,
					commission_rate: null,
					image_url: null,
					lifecycle_status: "ACTIVE",
					visual_canvas_width: 1000,
					visual_canvas_height: 1000,
					visual_readiness: {
						visual_canvas_label: "1000×1000 px",
						visual_canvas_requirement: "Manual / Canva cutouts must be transparent PNG files on an exact 1000x1000 px canvas.",
						canonical_media_status: "AVAILABLE",
						cutout_status: "NOT_PREPARED",
						cutout_review_status: "NOT_STARTED",
						visual_grounding_status: "VISUAL_GROUNDING_READY_FALLBACK",
						can_start_canva_cutout: true,
					},
				} as never,
			],
			total_count: 1,
		} as never);

		render(<AllProductsTab />);

		expect(await screen.findByTestId("table-visual-canvas-requirement")).toHaveTextContent(
			"Canvas 1000×1000 px",
		);
	});

	it("shows the approved cutout in Visual while keeping the source thumbnail in Image", async () => {
		vi.mocked(fetchProductRegistry).mockResolvedValueOnce({
			items: [
				{
					id: "approved-manual-product",
					source: "MANUAL",
					raw_product_title: "Approved manual product",
					product_display_name: "Approved manual product",
					product_short_name: "Approved manual",
					image_url: "/images/original-source.png",
					lifecycle_status: "ACTIVE",
					visual_readiness: {
						visual_canvas_label: "1000×1000 px",
						canonical_media_status: "AVAILABLE",
						cutout_status: "APPROVED",
						cutout_review_status: "APPROVED",
						visual_grounding_status: "VISUAL_GROUNDING_READY",
						active_visual_source: "APPROVED_MANUAL_CANONICAL_CUTOUT",
						original_preview_url: "/api/product-visual-onboarding/approved-manual-product/cutout/preview/original",
						original_display_url: "/images/original-source.png",
						active_cutout_preview_url: "/api/product-visual-onboarding/approved-manual-product/cutout/preview/active",
						manual_cutout_preview_url: "/api/product-visual-onboarding/approved-manual-product/cutout/preview/manual",
						current_system_visual: {
							card: "MANUAL_CUTOUT",
							label: "Manual / Canva Cutout",
							status: "OFFICIAL",
						},
					},
				} as never,
			],
			total_count: 1,
		} as never);

		render(<AllProductsTab />);

		const visualSummary = await screen.findByTestId("table-visual-summary");
		expect(visualSummary.querySelector("img")).toHaveAttribute(
			"src",
			"/api/product-visual-onboarding/approved-manual-product/cutout/preview/active",
		);
		expect(document.querySelectorAll("img")[0]).toHaveAttribute(
			"src",
			"/images/original-source.png",
		);
	});

	it("keeps the original source visible until a cutout candidate is officially approved", async () => {
		vi.mocked(fetchProductRegistry).mockResolvedValueOnce({
			items: [
				{
					id: "pending-manual-product",
					source: "MANUAL",
					raw_product_title: "Pending manual product",
					product_display_name: "Pending manual product",
					product_short_name: "Pending manual",
					image_url: "/images/original-source.png",
					lifecycle_status: "ACTIVE",
					visual_readiness: {
						visual_canvas_label: "1000×1000 px",
						canonical_media_status: "AVAILABLE",
						cutout_status: "PENDING_REVIEW",
						cutout_review_status: "PENDING_REVIEW",
						visual_grounding_status: "VISUAL_GROUNDING_READY_FALLBACK",
						active_visual_source: "SAME_PRODUCT_TRUSTED_SOURCE",
						original_preview_url: "/api/product-visual-onboarding/pending-manual-product/cutout/preview/original",
						original_display_url: "/images/original-source.png",
						active_cutout_preview_url: "/api/product-visual-onboarding/pending-manual-product/cutout/preview/active",
						manual_cutout_preview_url: "/api/product-visual-onboarding/pending-manual-product/cutout/preview/manual",
						current_system_visual: {
							card: "ORIGINAL_SOURCE",
							label: "Original Source",
							status: "ORIGINAL_FALLBACK",
						},
					},
				} as never,
			],
			total_count: 1,
		} as never);

		render(<AllProductsTab />);

		const visualSummary = await screen.findByTestId("table-visual-summary");
		expect(visualSummary.querySelector("img")).toHaveAttribute(
			"src",
			"/api/product-visual-onboarding/pending-manual-product/cutout/preview/original",
		);
	});
});
