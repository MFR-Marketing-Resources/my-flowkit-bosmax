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
		product_name: "Sample capsules",
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
	},
	human_review_fields: [],
	blocked_fields: [],
	missing_required_evidence: ["SIZE_OR_VOLUME_EVIDENCE"],
	claim_gate: "CLAIM_REVIEW_REQUIRED",
	claim_tokens: [],
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
			"AI Fill Missing does not propose size or volume facts",
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
			expect(screen.getByText(/Missing evidence resolved/)).toHaveTextContent(
				"review status: NEEDS_HUMAN_REVIEW.",
			),
		);
		expect(onUpdate).toHaveBeenCalledWith(resolvedDraft);
	});
});
