import "@testing-library/jest-dom/vitest";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchAPI, patchAPI, postAPI } from "../../api/client";
import type { RegistrationReviewDraft } from "../../types";
import RegistrationReviewDraftPanel from "./RegistrationReviewDraftPanel";

vi.mock("../../api/client", () => ({
	fetchAPI: vi.fn(),
	patchAPI: vi.fn(),
	postAPI: vi.fn(),
}));

const reviewDraft: RegistrationReviewDraft = {
	review_draft_id: "draft-9cb8ab2d",
	review_status: "NEEDS_HUMAN_REVIEW",
	source_lane: "FASTMOSS_PROMOTED",
	storage_backend: "SQLITE_DATABASE",
	storage_location: "flow_agent.db:product_registration_review_draft",
	declared_evidence_fields: {
		product_name: "Sample capsules, tersedia dalam 30 / 60 / 120 Softgels",
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
	strategy_taxonomy: {
		product_id: "draft-9cb8ab2d",
		taxonomy_version: "product_strategy_taxonomy_v1",
		product_fingerprint: "fingerprint",
		cluster: "sensitive_wellness",
		product_type_group: "female_wellness",
		matched_scene_strategy_id: "SENSITIVE_WELLNESS",
		scene_coverage_status: "COVERED",
		fallback_used: false,
		specific_strategy: true,
		classification_confidence: "LOW",
		review_status: "REVIEW_REQUIRED",
		consumer_status: "BLOCKED_REVIEW_REQUIRED",
		authority_source: "AUTO_DERIVED",
		materialization_status: "PREVIEW",
		review_reasons: ["INTELLIGENCE_LOW"],
		is_stale: false,
	},
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

function StatefulReviewDraftPanel({
	draft,
}: {
	draft: RegistrationReviewDraft;
}) {
	const [currentDraft, setCurrentDraft] = useState(draft);
	return (
		<RegistrationReviewDraftPanel
			draft={currentDraft}
			onUpdate={setCurrentDraft}
			onClear={vi.fn()}
		/>
	);
}

describe("RegistrationReviewDraftPanel next-action guidance", () => {
	beforeEach(() => {
		vi.mocked(fetchAPI).mockResolvedValue({
			items: [
				{
					cluster: "sensitive_wellness",
					product_type_group: "female_wellness",
					display_name: "Female Wellness",
					matched_scene_strategy_id: "SENSITIVE_WELLNESS",
					scene_coverage_status: "COVERED",
					registry_status: "ACTIVE",
					auto_classification_enabled: true,
					authority_source: "SYSTEM_SEED",
				},
			],
			clusters: ["sensitive_wellness", "generic_unclassified"],
			scene_strategy_ids: ["GENERIC_FALLBACK", "SENSITIVE_WELLNESS"],
		});
	});

	afterEach(() => {
		cleanup();
		vi.clearAllMocks();
	});

	it("explains size evidence and focuses the existing manual field", () => {
		renderPanel();

		const nextAction = screen.getByTestId("registration-next-action");
		expect(nextAction).toHaveTextContent("Fill size or volume evidence");
		expect(nextAction).toHaveTextContent(
			"Save & Recompute may use the configured text_assist lane to propose missing evidence.",
		);
		expect(nextAction).toHaveTextContent(
			"AI suggestions remain review-only, never replace declared evidence, and never approve a field.",
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

	it("renders the deterministic product strategy taxonomy gate", () => {
		renderPanel();

		const taxonomy = screen.getByTestId("registration-strategy-taxonomy");
		expect(taxonomy).toHaveTextContent("Product Strategy Taxonomy");
		expect(taxonomy).toHaveTextContent("sensitive_wellness");
		expect(taxonomy).toHaveTextContent("female_wellness");
		expect(taxonomy).toHaveTextContent("SENSITIVE_WELLNESS");
		expect(taxonomy).toHaveTextContent("COVERED / BLOCKED_REVIEW_REQUIRED");
		expect(taxonomy).toHaveTextContent("INTELLIGENCE_LOW");
	});

	it("labels AI suggestions, unavailable fallbacks, warnings, and provenance", () => {
		const evidenceDraft = {
			...reviewDraft,
			canonical_candidate_fields: {
				...reviewDraft.canonical_candidate_fields,
				benefits: ["Melengkapkan rasa masakan"],
				size_or_volume: "N/A",
			},
			human_review_fields: [
				...reviewDraft.human_review_fields,
				"benefits",
				"size_or_volume",
			],
			evidence_field_status: {
				benefits: {
					status: "AI_SUGGESTED",
					confidence: "MEDIUM",
					provenance: ["text_assist:deepseek:deepseek-v4-pro:review_only"],
					needs_review: true,
				},
				size_or_volume: {
					status: "NOT_AVAILABLE",
					confidence: "NOT_APPLICABLE",
					provenance: [
						"product_knowledge_completion_service:deterministic_fallback",
					],
					needs_review: true,
				},
			},
			warnings: ["TEXT_ASSIST_SUGGESTIONS_REQUIRE_REVIEW"],
			provenance: [
				"product_knowledge_completion_service:v2",
				"text_assist:deepseek:deepseek-v4-pro:review_only",
			],
		} as RegistrationReviewDraft & {
			evidence_field_status: Record<string, unknown>;
		};
		renderPanel(evidenceDraft);

		expect(screen.getAllByText("AI SUGGESTED").length).toBeGreaterThan(0);
		expect(screen.getAllByText("NOT AVAILABLE").length).toBeGreaterThan(0);
		expect(screen.getByText(/Confidence: MEDIUM/)).toHaveTextContent(
			"text_assist:deepseek:deepseek-v4-pro:review_only",
		);
		expect(
			screen.getByText("TEXT_ASSIST_SUGGESTIONS_REQUIRE_REVIEW"),
		).toBeInTheDocument();
		expect(
			screen.getAllByText("text_assist:deepseek:deepseek-v4-pro:review_only")
				.length,
		).toBeGreaterThan(0);
	});

	it("saves a registry-backed manual taxonomy preview for commit", async () => {
		const baseTaxonomy = reviewDraft.strategy_taxonomy;
		if (!baseTaxonomy) {
			throw new Error("TEST_FIXTURE_TAXONOMY_REQUIRED");
		}
		const savedDraft: RegistrationReviewDraft = {
			...reviewDraft,
			strategy_taxonomy: {
				...baseTaxonomy,
				review_status: "VERIFIED",
				consumer_status: "BLOCKED_REVIEW_REQUIRED",
				authority_source: "MANUAL_OVERRIDE",
				reviewer_id: "admin-1",
				reviewer_note: "Reviewed registry binding.",
				review_reasons: [],
			},
		};
		vi.mocked(postAPI).mockResolvedValue(savedDraft);
		const { onUpdate } = renderPanel();

		await screen.findByRole("option", { name: "Female Wellness · ACTIVE" });
		fireEvent.change(screen.getByLabelText("Reviewer ID"), {
			target: { value: "admin-1" },
		});
		fireEvent.change(screen.getByLabelText("Reviewer Note"), {
			target: { value: "Reviewed registry binding." },
		});
		fireEvent.click(
			screen.getByRole("button", { name: "Verify Draft Assignment" }),
		);

		await waitFor(() =>
			expect(postAPI).toHaveBeenCalledWith(
				"/api/product-registration/review-drafts",
				expect.objectContaining({
					strategy_taxonomy: expect.objectContaining({
						product_type_group: "female_wellness",
						review_status: "VERIFIED",
						consumer_status: "BLOCKED_REVIEW_REQUIRED",
						authority_source: "MANUAL_OVERRIDE",
					}),
				}),
			),
		);
		expect(onUpdate).toHaveBeenCalledWith(savedDraft);
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
		fireEvent.click(screen.getByRole("button", { name: "Jump to Benefits" }));
		expect(benefitsField).toHaveFocus();

		const candidatesHeading = screen.getByRole("heading", {
			name: "Canonical Candidates",
		});
		const candidatesSection = candidatesHeading.closest("section");
		fireEvent.click(
			screen.getByRole("button", { name: "Jump to candidate approvals" }),
		);
		expect(candidatesSection).toHaveFocus();
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
		expect(
			screen.getByTestId("registration-variant-candidates"),
		).toHaveTextContent("30 softgels");
		expect(
			screen.getByTestId("registration-variant-candidates"),
		).toHaveTextContent("60 softgels");
		expect(
			screen.getByTestId("registration-variant-candidates"),
		).toHaveTextContent("120 softgels");

		fireEvent.click(screen.getByRole("button", { name: "Use 120 softgels" }));
		expect(screen.getByPlaceholderText("5 ML")).toHaveValue("120 softgels");
		expect(patchAPI).not.toHaveBeenCalled();
		expect(screen.getByText(/no approval was changed/i)).toBeInTheDocument();
	});

	it("reports why recompute leaves missing evidence unchanged", async () => {
		vi.mocked(patchAPI).mockResolvedValue(reviewDraft);
		renderPanel();

		fireEvent.click(
			screen.getByRole("button", { name: "Analyze & Repair Draft" }),
		);

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

	it("shows the SQLite record and warns when provider output is truncated", async () => {
		const truncatedDraft: RegistrationReviewDraft = {
			...reviewDraft,
			warnings: [
				"TEXT_ASSIST_INVALID_RESPONSE",
				"TEXT_ASSIST_DIAGNOSTIC_TRUNCATED_RESPONSE",
				"TEXT_ASSIST_FINISH_REASON:length",
			],
		};
		vi.mocked(patchAPI).mockResolvedValue(truncatedDraft);
		const { onUpdate } = renderPanel();

		const storage = screen.getByTestId("registration-draft-storage-status");
		expect(storage).toHaveAttribute("data-storage-backend", "SQLITE_DATABASE");
		expect(storage).toHaveTextContent(
			"SQLite database · flow_agent.db:product_registration_review_draft",
		);

		fireEvent.click(
			screen.getByRole("button", { name: "Analyze & Repair Draft" }),
		);

		const warning = await screen.findByRole("alert");
		expect(warning).toHaveTextContent(
			"Draft saved to flow_agent.db:product_registration_review_draft",
		);
		expect(warning).toHaveTextContent(
			"the provider response reached its output limit and was rejected",
		);
		expect(warning).toHaveTextContent(
			"Existing evidence was preserved; no AI repair proposal was applied.",
		);
		expect(onUpdate).toHaveBeenCalledWith(truncatedDraft);
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
		fireEvent.click(
			screen.getByRole("button", { name: "Analyze & Repair Draft" }),
		);

		await waitFor(() =>
			expect(
				screen.getByText(
					/Evidence saved. Still requires human review because:/,
				),
			).toHaveTextContent(
				"Review and approve candidate fields: Category, Subcategory, BOSMAX product family.",
			),
		);
		expect(
			screen.getByText(/Evidence saved. Still requires human review because:/),
		).toHaveTextContent("Sensitive claims require human verification.");
		expect(onUpdate).toHaveBeenCalledWith(resolvedDraft);
	});

	it("preserves unsaved evidence when a candidate decision refreshes the same draft", async () => {
		const decisionDraft: RegistrationReviewDraft = {
			...reviewDraft,
			human_review_fields: reviewDraft.human_review_fields.filter(
				(field) => field !== "category",
			),
			approval_checklist: {
				...reviewDraft.approval_checklist,
				category: true,
			},
		};
		vi.mocked(patchAPI).mockResolvedValue(decisionDraft);
		render(<StatefulReviewDraftPanel draft={reviewDraft} />);

		const warnings = screen.getByPlaceholderText(
			"Warnings, pantang, or restrictions.",
		);
		fireEvent.change(warnings, {
			target: { value: "Keep away from an open flame." },
		});
		fireEvent.change(screen.getByLabelText("Reviewer ID"), {
			target: { value: "operator-7" },
		});
		fireEvent.change(screen.getByLabelText("Reviewer Note"), {
			target: { value: "Keep this pending review note." },
		});

		expect(
			screen.getByTestId("registration-unsaved-evidence-changes"),
		).toBeInTheDocument();
		fireEvent.click(screen.getByRole("button", { name: "Approve category" }));

		await waitFor(() =>
			expect(
				screen.getByRole("button", { name: "Approved category" }),
			).toBePressed(),
		);
		expect(warnings).toHaveValue("Keep away from an open flame.");
		expect(screen.getByLabelText("Reviewer ID")).toHaveValue("operator-7");
		expect(screen.getByLabelText("Reviewer Note")).toHaveValue(
			"Keep this pending review note.",
		);
		expect(
			screen.getByTestId("registration-unsaved-evidence-changes"),
		).toBeInTheDocument();
	});

	it("renders curtain-specific labels and the convergence decision trail", () => {
		const curtainDraft = {
			...reviewDraft,
			declared_evidence_fields: {
				...reviewDraft.declared_evidence_fields,
				product_name: "HOT Langsir Kabinet Fabrik Tingkap Berpetak Soft Cotton",
				benefits_text: "#LangsirViral\n15-30s\nMakeover music",
				ingredients_text: "Kitchen glow-up! Order now!",
			},
			canonical_candidate_fields: {
				...reviewDraft.canonical_candidate_fields,
				category: "Textiles & Soft Furnishings",
				subcategory: "Household Textiles",
				type: "Curtains",
				bosmax_product_family: "HOME_TEXTILE",
				physics_class: "HOME_TEXTILE_SOFT_GOOD",
				copy_formula: "TEXTURE_COMFORT",
				materials_or_components: "fabric; soft cotton",
				ingredients_applicability: "NOT_APPLICABLE",
			},
			evidence_quality_status: "REVIEW_REQUIRED",
			evidence_quality_issues: ["EVIDENCE_BENEFITS_PRODUCTION_METADATA"],
			consistency_status: "CONSISTENT",
			consistency_issues: [],
			authority_fingerprint: "authority-fingerprint",
			hook_cta_input_fingerprint: "hook-fingerprint",
			recompute_required_reasons: [],
			evidence_field_status: {
				benefits: {
					status: "AI_SUGGESTED",
					confidence: "MEDIUM",
					provenance: ["text_assist:review_only"],
					needs_review: true,
					reason_codes: ["EVIDENCE_BENEFITS_PRODUCTION_METADATA"],
					evidence_used: ["product_name:Soft Cotton"],
					raw_value: "#LangsirViral\n15-30s\nMakeover music",
					repair_candidate: ["Soft cotton curtain for cabinet coverage"],
					repair_action: "REPAIR_INVALID_OR_PLACEHOLDER",
					applicability: "APPLICABLE",
				},
			},
		} as RegistrationReviewDraft & {
			evidence_field_status: Record<string, unknown>;
		};

		renderPanel(curtainDraft);

		expect(
			screen.getByText("Autonomous Convergence Pipeline"),
		).toBeInTheDocument();
		expect(
			screen.getAllByText("HOME_TEXTILE_SOFT_GOOD").length,
		).toBeGreaterThan(0);
		expect(screen.getAllByText("TEXTURE_COMFORT").length).toBeGreaterThan(0);
		expect(
			screen.getByLabelText("Materials / Components Text"),
		).toBeInTheDocument();
		expect(screen.getByLabelText("Dimensions / Size")).toHaveAttribute(
			"placeholder",
			"e.g. 120 × 45 cm",
		);
		expect(
			screen.getByRole("button", { name: "Analyze & Repair Draft" }),
		).toBeInTheDocument();
		const decisions = screen.getByTestId(
			"registration-evidence-quality-decisions",
		);
		expect(decisions).toHaveTextContent(
			"Raw: #LangsirViral 15-30s Makeover music",
		);
		expect(decisions).toHaveTextContent(
			"Repair candidate: Soft cotton curtain for cabinet coverage",
		);
		expect(decisions).toHaveTextContent("REPAIR_INVALID_OR_PLACEHOLDER");
	});
});

describe("B-08A-01 candidate approval affordance", () => {
	beforeEach(() => {
		vi.mocked(fetchAPI).mockResolvedValue({
			items: [],
			clusters: ["sensitive_wellness", "generic_unclassified"],
			scene_strategy_ids: ["GENERIC_FALLBACK", "SENSITIVE_WELLNESS"],
		});
	});

	afterEach(() => {
		cleanup();
		vi.clearAllMocks();
	});

	it("labels the approve control in text and for assistive tech", () => {
		// Previously an icon-only button whose two SVGs were both aria-hidden, so it had
		// no accessible name at all and Approve looked identical to Approved.
		renderPanel();
		const approve = screen.getByTestId("approve-normalized_name");
		expect(approve).toHaveAccessibleName(/approve normalized_name/i);
		expect(approve).toHaveTextContent(/approve/i);
		expect(approve).toHaveAttribute("aria-pressed", "false");
	});

	it("shows Approved state and offers an explicit Reject once approved", () => {
		renderPanel({
			...reviewDraft,
			approval_checklist: {
				...reviewDraft.approval_checklist,
				normalized_name: true,
			},
		});
		const approve = screen.getByTestId("approve-normalized_name");
		expect(approve).toHaveAttribute("aria-pressed", "true");
		expect(approve).toHaveTextContent(/approved/i);
		const reject = screen.getByTestId("reject-normalized_name");
		expect(reject).toHaveAccessibleName(/reject normalized_name/i);
	});

	it("offers no Reject while a candidate is still unapproved", () => {
		renderPanel();
		expect(screen.queryByTestId("reject-normalized_name")).toBeNull();
	});
});
