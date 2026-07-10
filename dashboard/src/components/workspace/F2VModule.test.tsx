import "@testing-library/jest-dom/vitest";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
	within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// F2V pulls creative assets + frame sources on mount / in handlers; stub them and
// the asset-slot child (its preview state would otherwise flap in jsdom and block
// SEND for reasons unrelated to the copy gate under test).
vi.mock("../../api/creativeAssets", () => ({
	fetchCreativeAssetEligibilityAudit: vi.fn(),
}));
vi.mock("../../api/imgFactory", () => ({ resolveF2vFrameSources: vi.fn() }));
vi.mock("../../api/assets", () => ({ handleAssetUpload: vi.fn() }));
vi.mock("./WorkspaceImageAssetSlot", () => ({ default: () => null }));

import F2VModule from "./F2VModule";
import { fetchCreativeAssetEligibilityAudit } from "../../api/creativeAssets";
import type {
	CreativeAssetEligibilityAuditResponse,
	WorkspaceExecutionPackage,
} from "../../types";

const mockedAudit = vi.mocked(fetchCreativeAssetEligibilityAudit);

function startFrame() {
	return {
		slot_key: "start_frame",
		media_id: "m-start",
		file_name: "start.png",
		label: "start",
		preview_url: "http://x/start.png",
		download_url: "http://x/start.png",
		asset_id: "a-start",
		asset_fingerprint: "f-start",
		asset_source: "PACKAGE",
		preview_renderable_status: "RENDERABLE",
	};
}

function audit(
	overrides: Partial<CreativeAssetEligibilityAuditResponse> = {},
): CreativeAssetEligibilityAuditResponse {
	return {
		surface: "F2V_START_FRAME_PICKER",
		surface_label: "F2V Start Frame Picker",
		recipe_id: null,
		required_semantic_role: "COMPOSITE_FRAME_REFERENCE",
		required_allowed_mode: "F2V",
		required_engine_slots: ["start_frame"],
		library_total_count: 0,
		total_assets_by_semantic_role: {},
		matching_role_total_count: 0,
		active_count: 0,
		approved_count: 0,
		eligible_count: 0,
		excluded_count: 0,
		review_status_counts: {},
		excluded_by_reason: {},
		eligible_assets: [],
		...overrides,
	};
}

// HYBRID reuses this exact module (OperatorPage mounts F2VModule for both F2V and
// HYBRID), so these cases cover the Hybrid surface too.
function pkg(bound: boolean): WorkspaceExecutionPackage {
	return {
		product_id: "p1",
		mode: "F2V",
		prompt_text: "Perut berangin, minyak angin disapu",
		model: "Veo",
		aspect_ratio: "9:16",
		resolved_assets: [startFrame()],
		request_lineage_payload: { asset_fingerprints: [] },
		copy_binding: bound
			? {
					copy_source: "selected_copy_set",
					copy_set_id: "cs1",
					copy_binding_status: "BOUND",
				}
			: { copy_source: "landbank_fallback", copy_set_id: null },
	} as unknown as WorkspaceExecutionPackage;
}

describe("F2VModule copy-binding gate (Phase B enforcement; covers HYBRID)", () => {
	beforeEach(() => {
		mockedAudit.mockReset();
		mockedAudit.mockResolvedValue(audit());
	});

	afterEach(() => cleanup());

	it("[gate] not copy-bound → SEND blocked until explicit fallback", async () => {
		const onExecute = vi.fn();
		render(
			<F2VModule
				onExecute={onExecute}
				isExecuting={false}
				workspacePackage={pkg(false)}
				copyReady={false}
			/>,
		);

		// Prompt + start frame hydrate from the package, so the ONLY remaining SEND
		// blocker is the copy gate.
		const btn = await screen.findByRole("button", { name: /SEND TO FLOW EDITOR/i });
		expect(screen.getByTestId("copy-binding-gate")).toBeInTheDocument();
		await waitFor(() => expect(btn).toBeDisabled());

		fireEvent.click(screen.getByTestId("copy-fallback-confirm"));
		await waitFor(() => expect(btn).not.toBeDisabled());
		fireEvent.click(btn);

		expect(onExecute).toHaveBeenCalledTimes(1);
		const call = onExecute.mock.calls[0][0];
		expect(call).toMatchObject({ copy_set_id: null, copy_fallback_confirmed: true });
		expect(call.request_lineage_payload.copy_binding_gate.copy_bound).toBe(false);
	});

	it("[allow] copy-bound package → no gate, SEND allowed, payload carries copy_set_id", async () => {
		const onExecute = vi.fn();
		render(
			<F2VModule
				onExecute={onExecute}
				isExecuting={false}
				workspacePackage={pkg(true)}
				copyReady={true}
			/>,
		);

		const btn = await screen.findByRole("button", { name: /SEND TO FLOW EDITOR/i });
		expect(screen.queryByTestId("copy-binding-gate")).not.toBeInTheDocument();
		await waitFor(() => expect(btn).not.toBeDisabled());
		fireEvent.click(btn);

		expect(onExecute).toHaveBeenCalledTimes(1);
		expect(onExecute.mock.calls[0][0]).toMatchObject({
			copy_set_id: "cs1",
			copy_fallback_confirmed: false,
		});
	});

	it("shows HYBRID eligibility label and audited counts", async () => {
		mockedAudit.mockImplementation(async ({ surface }) =>
			audit({
				surface,
				library_total_count: 3,
				matching_role_total_count: 2,
				eligible_count: 1,
				excluded_count: 2,
				review_status_counts: { PENDING_REVIEW: 1 },
				excluded_by_reason: {
					NOT_APPROVED_FOR_REUSE: 1,
					RENDERED_TEXT_NOT_ALLOWED_FOR_VIDEO_FRAME: 1,
				},
				eligible_assets: [
					{
						asset_id: "ca_frame",
						display_name: "Composite A",
						semantic_role: "COMPOSITE_FRAME_REFERENCE",
						description: null,
						source_type: "UPLOAD",
						storage_kind: "LOCAL_FILE",
						preview_url: "/preview",
						download_url: "/download",
						media_id: null,
						local_file_path: "C:/tmp/a.png",
						remote_source_url: null,
						product_id: null,
						category: null,
						silo: null,
						product_type: null,
						allowed_modes: ["F2V"],
						engine_slot_eligibility: ["start_frame"],
						visual_dna_summary: null,
						character_dna: null,
						scene_context_dna: null,
						style_mood_dna: null,
						source_prompt_fingerprint: null,
						source_workspace_execution_package_id: null,
						source_prompt_package_snapshot_id: null,
						review_status: "APPROVED",
						status: "ACTIVE",
						created_at: "2026-07-09T00:00:00Z",
						updated_at: "2026-07-09T00:00:00Z",
					},
				],
			}),
		);

		render(
			<F2VModule
				onExecute={vi.fn()}
				isExecuting={false}
				workspacePackage={pkg(true)}
				copyReady={true}
				surfaceMode="HYBRID"
			/>,
		);

		expect(
			await screen.findByText("Hybrid uses F2V frame eligibility."),
		).toBeInTheDocument();
		expect(
			screen.getAllByText("Library has 3 assets; 1 eligible for this surface; 2 excluded.")
				.length,
		).toBeGreaterThan(0);
	});

	it("shows visible API fetch failure instead of a silent empty picker", async () => {
		mockedAudit.mockRejectedValue(new Error("API 500: audit failed"));

		render(
			<F2VModule
				onExecute={vi.fn()}
				isExecuting={false}
				workspacePackage={pkg(true)}
				copyReady={true}
			/>,
		);

		expect(
			await screen.findAllByText(/API fetch failed: API 500: audit failed/i),
		).toHaveLength(2);
	});

	it("[cta] 0 eligible but composites exist → links to Creative Library review", async () => {
		mockedAudit.mockResolvedValue(
			audit({
				library_total_count: 2,
				matching_role_total_count: 2,
				eligible_count: 0,
				excluded_count: 2,
				review_status_counts: { PENDING_REVIEW: 2 },
				excluded_by_reason: { NOT_APPROVED_FOR_REUSE: 2 },
			}),
		);

		render(
			<F2VModule
				onExecute={vi.fn()}
				isExecuting={false}
				workspacePackage={pkg(true)}
				copyReady={true}
			/>,
		);

		// START + END audit cards each surface the approval CTA — the operator is
		// never left at a blind "none eligible" dropdown with no next step.
		const links = await screen.findAllByRole("link", {
			name: /Open Creative Library review/i,
		});
		expect(links).toHaveLength(2);
		expect(links[0]).toHaveAttribute("href", "/assets/creative-library");
	});

	it("[cta] eligible composites present → no approval CTA", async () => {
		mockedAudit.mockResolvedValue(
			audit({
				library_total_count: 1,
				matching_role_total_count: 1,
				eligible_count: 1,
				excluded_count: 0,
			}),
		);

		render(
			<F2VModule
				onExecute={vi.fn()}
				isExecuting={false}
				workspacePackage={pkg(true)}
				copyReady={true}
			/>,
		);

		await screen.findByRole("button", { name: /SEND TO FLOW EDITOR/i });
		expect(
			screen.queryByRole("link", { name: /Open Creative Library review/i }),
		).not.toBeInTheDocument();
	});
});

describe("F2VModule HYBRID vs FRAMES surface separation", () => {
	beforeEach(() => {
		mockedAudit.mockReset();
		mockedAudit.mockResolvedValue(audit());
	});

	afterEach(() => cleanup());

	it("[hybrid] renders product-first, no composite required, composite picker demoted to advanced override", async () => {
		render(
			<F2VModule
				onExecute={vi.fn()}
				isExecuting={false}
				workspacePackage={pkg(true)}
				copyReady={true}
				surfaceMode="HYBRID"
			/>,
		);

		// Product-first identity, not "Frames renamed".
		expect(
			await screen.findByText("1. Product Anchor + AI Presenter"),
		).toBeInTheDocument();
		expect(
			screen.getByText("No composite frame is required."),
		).toBeInTheDocument();
		expect(screen.getByText("Auto Product Anchor")).toBeInTheDocument();
		// The F2V primary header must NOT be shown on the HYBRID surface.
		expect(
			screen.queryByText("1. Visual Assets (F2V Slots)"),
		).not.toBeInTheDocument();

		// The Creative Library composite picker is preserved but demoted into a
		// collapsed advanced-override <details> (not the primary/default step).
		const summary = screen.getByText(
			/Advanced override: use a pre-composited frame/i,
		);
		const details = summary.closest("details");
		expect(details).not.toBeNull();
		expect(details).not.toHaveAttribute("open");
		// The composite picker lives INSIDE that collapsed override.
		expect(
			within(details as HTMLElement).getByText(
				"Or pick a saved composite frame from the Creative Library",
			),
		).toBeInTheDocument();
	});

	it("[frames] renders F2V primary, composite picker inline (no advanced-override wrapper)", async () => {
		render(
			<F2VModule
				onExecute={vi.fn()}
				isExecuting={false}
				workspacePackage={pkg(true)}
				copyReady={true}
				surfaceMode="F2V"
			/>,
		);

		expect(
			await screen.findByText("1. Visual Assets (F2V Slots)"),
		).toBeInTheDocument();
		// Composite picker is primary (inline), not hidden behind an override.
		const picker = screen.getByText(
			"Or pick a saved composite frame from the Creative Library",
		);
		expect(picker).toBeInTheDocument();
		expect(picker.closest("details")).toBeNull();
		expect(
			screen.queryByText(/Advanced override: use a pre-composited frame/i),
		).not.toBeInTheDocument();
		// HYBRID-only product-anchor chrome must be absent on FRAMES.
		expect(
			screen.queryByText("1. Product Anchor + AI Presenter"),
		).not.toBeInTheDocument();
		expect(screen.queryByText("Auto Product Anchor")).not.toBeInTheDocument();
	});
});
