import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CopywritingSourceSelector from "./CopywritingSourceSelector";

const mockBlueprints = [
	{
		blueprint_id: "bp-1",
		product_id: "prod-1",
		revision: 1,
		status: "PRODUCTION_VALID",
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
	},
];

function stubFetch(activeBpId: string | null = null) {
	const fetchMock = vi.fn((url: string, _opts?: { method?: string }) => {
		if (String(url).includes("/blueprints/generate")) {
			return Promise.resolve({
				ok: true,
				json: () =>
					Promise.resolve({
						blueprint: mockBlueprints[0],
						production_valid: true,
					}),
			});
		}
		if (String(url).includes("/approve")) {
			return Promise.resolve({
				ok: true,
				json: () =>
					Promise.resolve({
						blueprint: { ...mockBlueprints[0], status: "PRODUCTION_VALID" },
						production_valid: true,
						badge: "V2_APPROVED",
					}),
			});
		}
		if (String(url).includes("/activate")) {
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
		if (String(url).includes("/blueprints")) {
			return Promise.resolve({
				ok: true,
				json: () =>
					Promise.resolve({
						product_id: "prod-1",
						items: mockBlueprints,
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
		if (String(url).includes("/formulas")) {
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
		if (String(url).includes("/provider-status")) {
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
		if (String(url).includes("/truth")) {
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
		if (String(url).includes("/angle-options")) {
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

describe("CopywritingSourceSelector", () => {
	afterEach(() => {
		cleanup();
		vi.unstubAllGlobals();
	});

	it("renders copy selection choices and displays eligible copy sets with human content", async () => {
		stubFetch(null);
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

		// Ensure raw technical metadata is not on default surface
		expect(screen.queryByText(/Copy Architecture V2/i)).not.toBeInTheDocument();
		expect(screen.queryByText(/Universal adapter/i)).not.toBeInTheDocument();
	});

	it("switches to AI Copy Assistant tab", async () => {
		stubFetch(null);
		render(<CopywritingSourceSelector productId="prod-1" productName="Test Oil" lane="HYBRID" />);

		await waitFor(() => {
			expect(screen.getByTestId("copy-source-ai")).toBeInTheDocument();
		});

		fireEvent.click(screen.getByTestId("copy-source-ai"));

		await waitFor(() => {
			expect(screen.getByTestId("ai-copy-assistant-panel")).toBeInTheDocument();
		});
	});

	it("selects and activates copy when clicking 'Use This Copy'", async () => {
		stubFetch(null);
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
	});
});
