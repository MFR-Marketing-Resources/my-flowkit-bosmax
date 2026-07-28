import "@testing-library/jest-dom/vitest";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { patchAPI } from "../../api/client";
import type { RegistrationReviewDraft } from "../../types";
import RegistrationReviewDraftPanel from "./RegistrationReviewDraftPanel";

vi.mock("../../api/client", () => ({
	patchAPI: vi.fn(),
	postAPI: vi.fn(),
}));

const reviewDraft: RegistrationReviewDraft = {
	review_draft_id: "draft-9cb8ab2d",
	review_status: "NEEDS_HUMAN_REVIEW",
	source_lane: "FASTMOSS_PROMOTED",
	declared_evidence_fields: {
		product_name:
			"Sample capsules, tersedia dalam 30 / 60 / 120 Softgels",
		product_knowledge_text: "",
		benefits_text:
			"#NaturalEnhancement #HerbalSupplement\n15-30s\nFeminine soft music",
		usage_text: "Take only according to the verified label.",
		ingredients_text: "Natural beauty! Grab now!",
		warnings_text: "",
		paste_anything_about_product:
			"Product: Sample capsules, tersedia dalam 30 / 60 / 120 Softgels | Category: Health | Usage: Take only according to the verified label.",
		size_or_volume: "",
		image_url: "https://example.com/product.jpg",
	},
	system_inferred_fields: {
		image_analysis_status: "ANALYSIS_SKIPPED",
		image_analysis_provider: "execution_disabled",
	},
	canonical_candidate_fields: {
		normalized_name: "Sample capsules",
		size_or_volume: "",
		category: "Health",
		subcategory: "Supplements",
		bosmax_product_family: "FEMALE_HEALTH_SENSITIVE",
	},
	human_review_fields: [
		"category",
		"subcategory",
		"bosmax_product_family",
		"claims",
	],
	blocked_fields: [],
	missing_required_evidence: ["SIZE_OR_VOLUME_EVIDENCE"],
	claim_gate: "CLAIM_REVIEW_REQUIRED",
	claim_tokens: ["supplement"],
	claim_risk_level: "HIGH",
	copy_safety_notes: "Human review required.",
	taxonomy_status: "NEEDS_REVIEW",
	taxonomy_conflict: false,
	taxonomy_conflict_reason: null,
	product_family_status: "NEEDS_REVIEW",
	physics_status: "READY",
	scale_truth_status: "NEEDS_REVIEW",
	registration_gate_status: "NEEDS_HUMAN_REVIEW",
	write_back_allowed: false,
	write_back_performed: false,
	write_back_status: "READ_ONLY_REVIEW_PREVIEW",
	user_actions: [],
	approval_checklist: {
		normalized_name: false,
		size_or_volume: false,
		category: false,
		subcategory: false,
		bosmax_product_family: false,
	},
	readiness_by_mode: {},
	provenance: [],
	warnings: [],
	errors: [],
	draft_freshness_status: "FRESH",
	last_evidence_edit_at: "2026-07-28T11:53:19Z",
	last_recomputed_at: "2026-07-28T11:53:20Z",
	image_asset_status: "IMAGE_REFERENCE_READY",
	image_asset_detail: "Image URL is available for draft review.",
	rejection_checklist: {
		normalized_name: false,
		size_or_volume: false,
		category: false,
		subcategory: false,
		bosmax_product_family: false,
	},
};

function renderPanel(draft: RegistrationReviewDraft = reviewDraft) {
	const onUpdate = vi.fn();
	render(
		<RegistrationReviewDraftPanel
			draft={draft}
			onUpdate={onUpdate}
			onClear={vi.fn()}
		/>,
	);
	return { onUpdate };
}

describe("RegistrationReviewDraftPanel next-action guidance", () => {
	afterEach(() => {
		cleanup();
		vi.clearAllMocks();
	});

	it("explains size evidence and focuses the existing manual field", () => {
		renderPanel();

		const nextAction = screen.getByTestId("registration-next-action");
		expect(nextAction).toHaveTextContent("Fill size or volume evidence");
		expect(nextAction).toHaveTextContent(
			"Recompute validates current evidence; it will not fill missing evidence.",
		);
		expect(nextAction).toHaveTextContent(
			"Product Intelligence AI Fill remains a separate review-only provider action",
		);
		expect(nextAction).toHaveTextContent(
			"semantic vision analysis was skipped because provider execution is disabled",
		);

		const sizeField = screen.getByPlaceholderText("5 ML");
		fireEvent.click(
			screen.getByRole("button", {
				name: "Edit size or volume evidence",
			}),
		);
		expect(sizeField).toHaveFocus();
	});

	it("keeps next action visible after required evidence resolves and focuses weak fields", () => {
		const resolvedDraft: RegistrationReviewDraft = {
			...reviewDraft,
			declared_evidence_fields: {
				...reviewDraft.declared_evidence_fields,
				size_or_volume: "120",
				package_notes: "capsule bottle",
			},
			missing_required_evidence: [],
			scale_truth_status: "READY",
		};
		renderPanel(resolvedDraft);

		const nextAction = screen.getByTestId("registration-next-action");
		expect(nextAction).toHaveTextContent(
			"Review weak evidence and gated candidates",
		);
		expect(nextAction).toHaveTextContent(
			"Review and approve candidate fields: Category, Subcategory, BOSMAX product family.",
		);
		expect(nextAction).toHaveTextContent(
			"Sensitive claims require human verification.",
		);
		expect(nextAction).toHaveTextContent("Product Knowledge (Missing)");
		expect(nextAction).toHaveTextContent("Benefits (Placeholder)");
		expect(nextAction).toHaveTextContent("Ingredients (Placeholder)");
		expect(nextAction).toHaveTextContent("Warnings (Missing)");

		const benefitsField = screen.getByPlaceholderText(
			"Benefits and USP from the seller or product owner.",
		);
		fireEvent.click(
			screen.getByRole("button", { name: "Jump to Benefits" }),
		);
		expect(benefitsField).toHaveFocus();
	});

	it("extracts only stored evidence into reviewable fields and exposes explicit variant choices", () => {
		renderPanel();

		fireEvent.click(
			screen.getByRole("button", {
				name: "Extract from existing evidence",
			}),
		);

		expect(
			screen.getByPlaceholderText(
				"Core product description, source facts, and owned narrative.",
			),
		).toHaveValue(
			String(reviewDraft.declared_evidence_fields.paste_anything_about_product),
		);
		expect(
			screen.getByPlaceholderText(
				"Ingredients, materials, or formulation notes.",
			),
		).toHaveValue("Natural beauty! Grab now!");
		expect(
			screen.getByPlaceholderText("Warnings, pantang, or restrictions."),
		).toHaveValue("");
		expect(screen.getByTestId("registration-variant-candidates")).toHaveTextContent(
			"30 softgels",
		);
		expect(screen.getByTestId("registration-variant-candidates")).toHaveTextContent(
			"60 softgels",
		);
		expect(screen.getByTestId("registration-variant-candidates")).toHaveTextContent(
			"120 softgels",
		);

		fireEvent.click(
			screen.getByRole("button", { name: "Use 120 softgels" }),
		);
		expect(screen.getByPlaceholderText("5 ML")).toHaveValue("120 softgels");
		expect(patchAPI).not.toHaveBeenCalled();
		expect(
			screen.getByText(/no approval was changed/i),
		).toBeInTheDocument();
	});

	it("reports why recompute leaves missing evidence unchanged", async () => {
		vi.mocked(patchAPI).mockResolvedValue(reviewDraft);
		renderPanel();

		fireEvent.click(screen.getByRole("button", { name: "Save & Recompute" }));

		await waitFor(() =>
			expect(
				screen.getByText(/Recompute validated current evidence/),
			).toHaveTextContent("Still missing: SIZE_OR_VOLUME_EVIDENCE."),
		);
		expect(patchAPI).toHaveBeenCalledWith(
			"/api/product-registration/review-drafts/draft-9cb8ab2d/evidence",
			expect.objectContaining({ recompute: true, size_or_volume: "" }),
		);
	});

	it("reports when saved evidence resolves the missing-evidence gate", async () => {
		const resolvedDraft: RegistrationReviewDraft = {
			...reviewDraft,
			declared_evidence_fields: {
				...reviewDraft.declared_evidence_fields,
				size_or_volume: "30 softgels",
				package_notes: "capsule bottle",
			},
			missing_required_evidence: [],
			scale_truth_status: "READY",
		};
		vi.mocked(patchAPI).mockResolvedValue(resolvedDraft);
		const { onUpdate } = renderPanel();

		fireEvent.change(screen.getByPlaceholderText("5 ML"), {
			target: { value: "30 softgels" },
		});
		fireEvent.click(screen.getByRole("button", { name: "Save & Recompute" }));

		await waitFor(() =>
			expect(
				screen.getByText(/Evidence saved. Still requires human review because:/),
			).toHaveTextContent(
				"Review and approve candidate fields: Category, Subcategory, BOSMAX product family.",
			),
		);
		expect(
			screen.getByText(/Evidence saved. Still requires human review because:/),
		).toHaveTextContent("Sensitive claims require human verification.");
		expect(onUpdate).toHaveBeenCalledWith(resolvedDraft);
	});
});
