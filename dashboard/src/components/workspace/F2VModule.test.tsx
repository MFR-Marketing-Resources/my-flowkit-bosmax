import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// F2V pulls creative assets + frame sources on mount / in handlers; stub them and
// the asset-slot child (its preview state would otherwise flap in jsdom and block
// SEND for reasons unrelated to the copy gate under test).
vi.mock("../../api/creativeAssets", () => ({
	fetchCreativeAssets: vi.fn().mockResolvedValue({ items: [] }),
}));
vi.mock("../../api/imgFactory", () => ({ resolveF2vFrameSources: vi.fn() }));
vi.mock("../../api/assets", () => ({ handleAssetUpload: vi.fn() }));
vi.mock("./WorkspaceImageAssetSlot", () => ({ default: () => null }));

import F2VModule from "./F2VModule";
import type { WorkspaceExecutionPackage } from "../../types";

const MODELS = [{ key: "veo", label: "Veo" } as never];

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
	afterEach(() => cleanup());

	it("[gate] not copy-bound → SEND blocked until explicit fallback", async () => {
		const onExecute = vi.fn();
		render(
			<F2VModule
				onExecute={onExecute}
				isExecuting={false}
				workspacePackage={pkg(false)}
				videoModels={MODELS}
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
				videoModels={MODELS}
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
});
