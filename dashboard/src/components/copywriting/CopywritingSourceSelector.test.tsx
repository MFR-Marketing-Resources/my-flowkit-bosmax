import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CopyBlueprintV2Record } from "../../api/copyRegisterV2";
import CopywritingSourceSelector from "./CopywritingSourceSelector";

const mockApprovedBlueprint: CopyBlueprintV2Record = {
	version: "2",
	blueprint_id: "bp-1",
	product_id: "prod-1",
	revision: 1,
	status: "PRODUCTION_VALID",
	current_authority_activation_allowed: true,
	formula_id: "PAS",
	formula_version: "v1",
	objective: { objective_id: "conv", definition: "Conversion" },
	angle: { angle_id: "ang-1", definition: "Fast Relief" },
	stages: [
		{
			stage_key: "hook_1",
			order: 0,
			authored_text: "Are you suffering from daily back pain?",
			semantic_role: "HOOK",
			formula_stage_key: "hook",
			bridge: { entry: "", exit: "", continuity_requirements: [] },
			claim_bearing: true,
			fact_refs: [],
			validation: { valid: true, error_codes: [] },
		},
		{
			stage_key: "body_1",
			order: 1,
			authored_text: "Our herbal oil penetrates deeply within seconds.",
			semantic_role: "BODY",
			formula_stage_key: "problem",
			bridge: { entry: "", exit: "", continuity_requirements: [] },
			claim_bearing: true,
			fact_refs: [],
			validation: { valid: true, error_codes: [] },
		},
		{
			stage_key: "cta_1",
			order: 2,
			authored_text: "Order yours today with free shipping.",
			semantic_role: "CTA",
			formula_stage_key: "cta",
			bridge: { entry: "", exit: "", continuity_requirements: [] },
			claim_bearing: false,
			fact_refs: [],
			validation: { valid: true, error_codes: [] },
		},
	],
	evidence_refs: [],
	product_truth_lineage: {},
	approved_execution_text: [],
	estimated_word_count: 32,
	target_duration_seconds: 8,
	derived_projection: {
		derived_copy: {
			hook: "Are you suffering from daily back pain?",
			body: "Our herbal oil penetrates deeply within seconds.",
			cta: "Order yours today with free shipping.",
		},
	},
};

const mockDraftBlueprint: CopyBlueprintV2Record = {
	version: "2",
	blueprint_id: "bp-draft",
	product_id: "prod-1",
	revision: 1,
	status: "DRAFT",
	current_authority_activation_allowed: false,
	formula_id: "PAS",
	formula_version: "v1",
	objective: { objective_id: "conv", definition: "Conversion" },
	angle: { angle_id: "ang-2", definition: "Natural Heritage" },
	stages: [
		{
			stage_key: "hook_1",
			order: 0,
			authored_text: "Traditional remedies passed down generations.",
			semantic_role: "HOOK",
			formula_stage_key: "hook",
			bridge: { entry: "", exit: "", continuity_requirements: [] },
			claim_bearing: true,
			fact_refs: [],
			validation: { valid: false, error_codes: ["REVIEW_PENDING"] },
		},
		{
			stage_key: "body_1",
			order: 1,
			authored_text: "Cold-pressed from wild botanicals.",
			semantic_role: "BODY",
			formula_stage_key: "problem",
			bridge: { entry: "", exit: "", continuity_requirements: [] },
			claim_bearing: true,
			fact_refs: [],
			validation: { valid: false, error_codes: [] },
		},
		{
			stage_key: "cta_1",
			order: 2,
			authored_text: "Experience the tradition.",
			semantic_role: "CTA",
			formula_stage_key: "cta",
			bridge: { entry: "", exit: "", continuity_requirements: [] },
			claim_bearing: false,
			fact_refs: [],
			validation: { valid: false, error_codes: [] },
		},
	],
	evidence_refs: [],
	product_truth_lineage: {},
	approved_execution_text: [],
	estimated_word_count: 24,
	target_duration_seconds: 8,
	derived_projection: {
		derived_copy: {
			hook: "Traditional remedies passed down generations.",
			body: "Cold-pressed from wild botanicals.",
			cta: "Experience the tradition.",
		},
	},
};

function stubFetch(blueprintsList: CopyBlueprintV2Record[] = [mockApprovedBlueprint], activeBpId: string | null = null) {
	const fetchMock = vi.fn((url: string, _opts?: { method?: string }) => {
		const u = String(url);
		if (u.includes("/blueprints/generate")) {
			return Promise.resolve({
				ok: true,
				json: () =>
					Promise.resolve({
						blueprint: mockDraftBlueprint,
						production_valid: false,
					}),
			});
		}
		if (u.includes("/approve")) {
			return Promise.resolve({
				ok: true,
				json: () =>
					Promise.resolve({
						blueprint: { ...mockDraftBlueprint, status: "PRODUCTION_VALID" },
						production_valid: true,
						badge: "V2_APPROVED",
					}),
			});
		}
		if (u.includes("/activate")) {
			return Promise.resolve({
				ok: true,
				json: () =>
					Promise.resolve({
						blueprint_id: "bp-1",
						activated: true,
						bindings: [],
						required_lane_count: 8,
					}),
			});
		}
		if (u.includes("/blueprints")) {
			return Promise.resolve({
				ok: true,
				json: () =>
					Promise.resolve({
						product_id: "prod-1",
						items: blueprintsList,
						activation: {
							active_blueprint_id: activeBpId,
							active_revision: activeBpId ? 1 : null,
							active_lane_count: activeBpId ? 8 : 0,
							required_lane_count: 8,
							activated_at: activeBpId ? "2026-08-17T00:00:00Z" : null,
						},
					}),
			});
		}
		if (u.includes("/formulas")) {
			return Promise.resolve({
				ok: true,
				json: () =>
					Promise.resolve({
						formulas: [
							{
								formula_id: "PAS",
								formula_version: "v1",
								display_name: "Problem Agitate Solve",
							},
						],
					}),
			});
		}
		if (u.includes("/provider-status")) {
			return Promise.resolve({
				ok: true,
				json: () =>
					Promise.resolve({
						lane: "text_assist",
						status: "READY",
						configured: true,
						execution_enabled: true,
						provider_calls: 0,
					}),
			});
		}
		if (u.includes("/truth")) {
			return Promise.resolve({
				ok: true,
				json: () =>
					Promise.resolve({
						product_id: "prod-1",
						product: { display_name: "Test Oil" },
						product_truth: { approved: true, allowed_claims: ["natural"], blocked_claims: [], warnings: [] },
						facts: [],
						blockers: [],
						ready_for_copy: true,
					}),
			});
		}
		if (u.includes("/angle-options")) {
			return Promise.resolve({
				ok: true,
				json: () =>
					Promise.resolve({
						angles: [{ angle_id: "ang-1", definition: "Fast Relief", evidence_fact_ids: [] }],
						facts: [],
						formula_id: "PAS",
						formula_version: "v1",
					}),
			});
		}
		return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
	});
	vi.stubGlobal("fetch", fetchMock);
	return fetchMock;
}

describe("CopywritingSourceSelector Governance & Features", () => {
	afterEach(() => {
		cleanup();
		vi.unstubAllGlobals();
	});

	it("renders copy selection choices and displays approved copy sets with human content", async () => {
		stubFetch([mockApprovedBlueprint], null);
		render(<CopywritingSourceSelector productId="prod-1" productName="Test Oil" lane="HYBRID" />);

		await waitFor(() => {
			expect(screen.getByTestId("copy-source-register")).toBeInTheDocument();
			expect(screen.getByTestId("copy-source-ai")).toBeInTheDocument();
		});

		// Check human content
		expect(screen.getByText(/Are you suffering from daily back pain/i)).toBeInTheDocument();
		expect(screen.getByText(/Our herbal oil penetrates deeply/i)).toBeInTheDocument();
		expect(screen.getByText(/Order yours today with free shipping/i)).toBeInTheDocument();
		expect(screen.getAllByText(/Fast Relief/i).length).toBeGreaterThan(0);
		expect(screen.getByTestId("copy-status-approved")).toHaveTextContent("APPROVED");

		// Ensure raw technical metadata is not on default surface
		expect(screen.queryByText(/Copy Architecture V2/i)).not.toBeInTheDocument();
		expect(screen.queryByText(/Universal adapter/i)).not.toBeInTheDocument();
	});

	it("prevents selecting/auto-approving DRAFT copy: shows NEEDS APPROVAL badge and link to Copy Register", async () => {
		const fetchMock = stubFetch([mockDraftBlueprint], null);
		render(<CopywritingSourceSelector productId="prod-1" productName="Test Oil" lane="HYBRID" />);

		await waitFor(() => {
			expect(screen.getByTestId("copy-status-needs-approval")).toBeInTheDocument();
		});

		// Ensure "Use This Copy" button is NOT rendered for draft copy
		expect(screen.queryByTestId("use-this-copy-button")).not.toBeInTheDocument();

		// Ensure "Review in Copy Register" link is rendered
		const reviewLink = screen.getByTestId("review-in-copy-register-link");
		expect(reviewLink).toBeInTheDocument();
		expect(reviewLink).toHaveAttribute("href", expect.stringContaining("blueprint_id=bp-draft"));

		// Ensure no approval or activation API calls were made
		const approveCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/approve"));
		const activateCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/activate"));
		expect(approveCalls.length).toBe(0);
		expect(activateCalls.length).toBe(0);
	});

	it("selects and activates approved copy when clicking 'Use This Copy'", async () => {
		const fetchMock = stubFetch([mockApprovedBlueprint], null);
		const onCopySelected = vi.fn();
		render(
			<CopywritingSourceSelector
				productId="prod-1"
				productName="Test Oil"
				lane="HYBRID"
				onCopySelected={onCopySelected}
			/>,
		);

		await waitFor(() => {
			expect(screen.getByTestId("use-this-copy-button")).toBeInTheDocument();
		});

		fireEvent.click(screen.getByTestId("use-this-copy-button"));

		await waitFor(() => {
			expect(screen.getByTestId("copywriting-selected-summary")).toBeInTheDocument();
		});

		expect(screen.getByText(/Copywriting Selected/i)).toBeInTheDocument();
		expect(screen.getByTestId("change-copy-button")).toBeInTheDocument();
		expect(onCopySelected).toHaveBeenCalled();

		// Verify activate API was called but NOT approve
		const activateCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/activate"));
		const approveCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/approve"));
		expect(activateCalls.length).toBe(1);
		expect(approveCalls.length).toBe(0);
	});

	it("AI Copy generation leaves generated copy in DRAFT state and DOES NOT auto-approve", async () => {
		const fetchMock = stubFetch([mockApprovedBlueprint], null);
		render(<CopywritingSourceSelector productId="prod-1" productName="Test Oil" lane="HYBRID" />);

		await waitFor(() => {
			expect(screen.getByTestId("copy-source-ai")).toBeInTheDocument();
		});

		fireEvent.click(screen.getByTestId("copy-source-ai"));

		await waitFor(() => {
			expect(screen.getByTestId("ai-copy-assistant-panel")).toBeInTheDocument();
		});

		// Select formula
		const formulaSelect = screen.getByRole("combobox");
		fireEvent.change(formulaSelect, { target: { value: "PAS" } });

		// Click generate angle options
		const genAnglesBtn = await screen.findByRole("button", { name: /Generate Angle Options/i });
		fireEvent.click(genAnglesBtn);

		// Click generate copy draft
		const genCopyBtn = await screen.findByTestId("generate-ai-copy-button");
		fireEvent.click(genCopyBtn);

		// Verify draft preview is shown with review notice
		await waitFor(() => {
			expect(screen.getByTestId("ai-generated-draft-preview")).toBeInTheDocument();
		});

		expect(screen.getByText(/Governance Review Required/i)).toBeInTheDocument();
		expect(screen.getByTestId("open-ai-draft-in-register")).toBeInTheDocument();

		// CRITICAL GOVERNANCE CHECK: Approve & Activate were NOT called!
		const approveCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/approve"));
		const activateCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/activate"));
		expect(approveCalls.length).toBe(0);
		expect(activateCalls.length).toBe(0);
	});
});
