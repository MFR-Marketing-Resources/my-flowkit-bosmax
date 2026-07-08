import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ProductIntelligenceReviewDraftPanel from "./ProductIntelligenceReviewDraftPanel";

vi.mock("../../api/products", () => ({
	fetchProductIntelligenceReviewDrafts: vi
		.fn()
		.mockResolvedValue({ product_id: "p1", items: [] }),
	fetchProductIntelligenceReviewDraft: vi.fn(),
	createProductIntelligenceReviewDraft: vi.fn(),
	prepareProductForCopywriting: vi.fn(),
	updateProductIntelligenceReviewDraft: vi.fn(),
	validateProductIntelligenceReviewDraft: vi.fn(),
	approveProductIntelligenceReviewDraft: vi.fn(),
	rejectProductIntelligenceReviewDraft: vi.fn(),
}));

describe("ProductIntelligenceReviewDraftPanel", () => {
	afterEach(() => cleanup());

	it("[UI smoke] renders the Prepare with AI (DeepSeek) button next to Create", async () => {
		render(
			<ProductIntelligenceReviewDraftPanel
				productId="p1"
				onApproved={async () => {}}
			/>,
		);
		expect(
			await screen.findByRole("button", { name: /Prepare with AI/i }),
		).toBeInTheDocument();
		expect(
			await screen.findByRole("button", { name: /Create Review Draft/i }),
		).toBeInTheDocument();
	});
});
