import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// I2V rebuild must preserve the operator's approved Copy Set through the
// semantic package rebuild. This surface previously dropped copy_set_id,
// stripping the binding and risking silent generic-copy generation.
vi.mock("../../api/workspacePackages", () => ({
	createWorkspaceExecutionPackage: vi.fn(),
	resolveI2VSemanticSlots: vi.fn().mockResolvedValue({
		resolved_assets: [],
		blockers: [],
		warnings: [],
		engine_slot_mapping: {},
		compiler_context_summary: "",
	}),
}));
vi.mock("../../api/creativeAssets", () => ({
	fetchCreativeAssetEligibilityAudit: vi.fn(),
}));
vi.mock("../../api/assets", () => ({ handleAssetUpload: vi.fn() }));

import I2VModule from "./I2VModule";
import { fetchCreativeAssetEligibilityAudit } from "../../api/creativeAssets";
import { createWorkspaceExecutionPackage } from "../../api/workspacePackages";
import type {
	CreativeAssetEligibilityAuditResponse,
	WorkspaceExecutionPackage,
} from "../../types";

const mockedCreate = vi.mocked(createWorkspaceExecutionPackage);
const mockedAudit = vi.mocked(fetchCreativeAssetEligibilityAudit);

function slotAsset(slot: string) {
	return {
		slot_key: slot,
		media_id: `m-${slot}`,
		file_name: `${slot}.png`,
		label: slot,
		preview_url: `http://x/${slot}.png`,
		download_url: `http://x/${slot}.png`,
		asset_id: `a-${slot}`,
		asset_fingerprint: `f-${slot}`,
		asset_source: "PACKAGE",
		preview_renderable_status: "RENDERABLE",
	};
}

// Minimal hydrating package: prompt_text + 2 resolved assets (subject + scene)
// satisfy the I2V execute preconditions (manualPrompt set, >= 2 images).
const pkg = {
	product_id: "p1",
	mode: "I2V",
	prompt_text: "Bayi kembung perut menangis waktu malam",
	duration_seconds: 8,
	aspect_ratio: "9:16",
	resolved_assets: [slotAsset("subject"), slotAsset("scene")],
	request_lineage_payload: { asset_fingerprints: [] },
} as unknown as WorkspaceExecutionPackage;

function audit(
	overrides: Partial<CreativeAssetEligibilityAuditResponse> = {},
): CreativeAssetEligibilityAuditResponse {
	return {
		surface: "I2V_CHARACTER_PICKER",
		surface_label: "I2V Character Picker",
		recipe_id: "PRODUCT_HELD_BY_CHARACTER_IN_SCENE",
		required_semantic_role: "CHARACTER_REFERENCE",
		required_allowed_mode: "I2V",
		required_engine_slots: ["scene"],
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

describe("I2VModule copy-set binding (CRITICAL)", () => {
	beforeEach(() => {
		mockedCreate.mockReset();
		mockedCreate.mockResolvedValue({
			...pkg,
			request_lineage_payload: { asset_fingerprints: [] },
		} as unknown as WorkspaceExecutionPackage);
		mockedAudit.mockReset();
		mockedAudit.mockImplementation(async ({ surface }) =>
			audit({
				surface,
				surface_label:
					surface === "I2V_CHARACTER_PICKER"
						? "I2V Character Picker"
						: surface === "I2V_SCENE_PICKER"
							? "I2V Scene Context Picker"
							: "I2V Style Picker",
			}),
		);
		vi.stubGlobal(
			"fetch",
			vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [] }) }),
		);
		vi.stubGlobal("alert", vi.fn());
	});
	afterEach(() => {
		cleanup();
		vi.unstubAllGlobals();
	});

	it("[CRITICAL] preserves the selected copy_set_id through the semantic rebuild", async () => {
		render(
			<I2VModule
				onExecute={vi.fn()}
				isExecuting={false}
				workspacePackage={pkg}
				onWorkspacePackageUpdated={vi.fn()}
				videoModels={[{ key: "nano-banana", label: "Nano Banana" } as never]}
				selectedCopySetId="cs-approved-1"
			/>,
		);

		const btn = await screen.findByRole("button", { name: /SEND TO FLOW EDITOR/i });
		// A bound Copy Set means the gate is not shown and SEND is allowed.
		expect(screen.queryByTestId("copy-binding-gate")).not.toBeInTheDocument();
		await waitFor(() => expect(btn).not.toBeDisabled());
		fireEvent.click(btn);

		await waitFor(() => expect(mockedCreate).toHaveBeenCalledTimes(1));
		expect(mockedCreate).toHaveBeenCalledWith(
			expect.objectContaining({
				copy_set_id: "cs-approved-1",
				copy_fallback_confirmed: false,
				mode: "I2V",
			}),
		);
	});

	it("[gate] no Copy Set → SEND blocked until explicit fallback confirmation", async () => {
		render(
			<I2VModule
				onExecute={vi.fn()}
				isExecuting={false}
				workspacePackage={pkg}
				onWorkspacePackageUpdated={vi.fn()}
				videoModels={[{ key: "nano-banana", label: "Nano Banana" } as never]}
				selectedCopySetId={null}
			/>,
		);

		// Gate visible + SEND blocked (no approved Copy Set is bound).
		const btn = await screen.findByRole("button", { name: /SEND TO FLOW EDITOR/i });
		expect(screen.getByTestId("copy-binding-gate")).toBeInTheDocument();
		await waitFor(() => expect(btn).toBeDisabled());

		// Explicit fallback confirmation unblocks SEND; the rebuild then carries the
		// (null) binding + copy_fallback_confirmed=true so backend records fallback.
		fireEvent.click(screen.getByTestId("copy-fallback-confirm"));
		await waitFor(() => expect(btn).not.toBeDisabled());
		fireEvent.click(btn);

		await waitFor(() => expect(mockedCreate).toHaveBeenCalledTimes(1));
		const call = mockedCreate.mock.calls[0][0] as Record<string, unknown>;
		expect(call).toHaveProperty("copy_set_id", null);
		expect(call).toHaveProperty("copy_fallback_confirmed", true);
	});

	it("shows eligibility counts for ingredient pickers", async () => {
		mockedAudit.mockImplementation(async ({ surface }) =>
			audit({
				surface,
				library_total_count: 5,
				matching_role_total_count: 2,
				eligible_count: 1,
				excluded_count: 4,
				review_status_counts: { PENDING_REVIEW: 1 },
				excluded_by_reason: {
					NOT_APPROVED_FOR_REUSE: 1,
					ENGINE_SLOT_NOT_ALLOWED: 1,
				},
			}),
		);

		render(
			<I2VModule
				onExecute={vi.fn()}
				isExecuting={false}
				workspacePackage={pkg}
				onWorkspacePackageUpdated={vi.fn()}
				videoModels={[{ key: "nano-banana", label: "Nano Banana" } as never]}
				selectedCopySetId="cs-approved-1"
			/>,
		);

		expect(
			await screen.findAllByText(
				"Library has 5 assets; 1 eligible for this surface; 4 excluded.",
			),
		).toHaveLength(3);
	});

	it("shows visible API fetch failure instead of silent empty ingredient selectors", async () => {
		mockedAudit.mockRejectedValue(new Error("API 500: audit failed"));

		render(
			<I2VModule
				onExecute={vi.fn()}
				isExecuting={false}
				workspacePackage={pkg}
				onWorkspacePackageUpdated={vi.fn()}
				videoModels={[{ key: "nano-banana", label: "Nano Banana" } as never]}
				selectedCopySetId="cs-approved-1"
			/>,
		);

		expect(
			await screen.findAllByText(/API fetch failed: API 500: audit failed/i),
		).toHaveLength(3);
	});
});
