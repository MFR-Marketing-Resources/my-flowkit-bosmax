import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ProductIntelligenceReviewDraftPanel, {
	describeApprovalBlockers,
	formatReviewDraftError,
} from "./ProductIntelligenceReviewDraftPanel";
import type { ProductIntelligenceReviewDraftValidationResponse } from "../../types";

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

	it("formatReviewDraftError turns a raw 409 into a human, actionable message", () => {
		const raw = new Error(
			'API 409: {"detail":"DRAFT_NOT_APPROVABLE:MISSING_REQUIRED_FIELDS:source_urls_json|CLAIM_BLOCKED:rawat,penyakit,ubat"}',
		);
		const msg = formatReviewDraftError(raw, "fallback");
		// No raw JSON / no "API 409" dumped at the operator.
		expect(msg).not.toContain("API 409");
		expect(msg).not.toContain("{");
		// Both blockers are explained with their specifics.
		expect(msg).toContain("source_urls_json");
		expect(msg).toContain("rawat,penyakit,ubat");
		expect(msg.toLowerCase()).toContain("belum boleh diluluskan");
	});

	it("formatReviewDraftError passes a non-approval error through unchanged", () => {
		expect(
			formatReviewDraftError(new Error("Source URLs must be valid JSON."), "fallback"),
		).toBe("Source URLs must be valid JSON.");
		expect(formatReviewDraftError("not-an-error", "fallback")).toBe("fallback");
	});

	const baseReport = (
		over: Partial<ProductIntelligenceReviewDraftValidationResponse>,
	): ProductIntelligenceReviewDraftValidationResponse =>
		({
			draft: {} as never,
			missing_required_fields: [],
			present_required_fields: [],
			completeness_score: 1,
			readiness_status: "READY_FOR_APPROVAL",
			claim_gate: "CLAIM_SAFE",
			claim_risk_level: "LOW",
			claim_tokens_json: [],
			allowed_claims_json: [],
			blocked_claims_json: [],
			approval_blockers: [],
			...over,
		}) as ProductIntelligenceReviewDraftValidationResponse;

	it("describeApprovalBlockers summarises structured blockers, or null when clean", () => {
		expect(describeApprovalBlockers(baseReport({}))).toBeNull();

		const msg = describeApprovalBlockers(
			baseReport({
				missing_required_fields: ["source_urls_json"],
				claim_gate: "CLAIM_BLOCKED",
				claim_risk_level: "HIGH",
				claim_tokens_json: ["rawat", "penyakit", "ubat"],
				approval_blockers: [
					"MISSING_REQUIRED_FIELDS:source_urls_json",
					"CLAIM_BLOCKED:rawat,penyakit,ubat",
				],
			}),
		);
		expect(msg).not.toBeNull();
		expect(msg as string).toContain("source_urls_json");
		expect(msg as string).toContain("rawat, penyakit, ubat");
	});
});
