import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import T2VModule from "./T2VModule";
import type { WorkspaceExecutionPackage } from "../../types";

const MODELS = [{ key: "veo", label: "Veo 3.1 - Lite" } as never];

// A T2V package compiled from an approved Copy Set — copy_binding proves the run
// carries approved copy (the SEND path does not rebuild, so this is the binding).
const boundPkg = {
	product_id: "p1",
	mode: "T2V",
	prompt_text: "Anak kembung perut, ibu urut dengan minyak",
	model: "Veo 3.1 - Lite",
	aspect_ratio: "9:16",
	request_lineage_payload: { asset_fingerprints: [] },
	copy_binding: {
		copy_source: "selected_copy_set",
		copy_set_id: "cs1",
		copy_binding_status: "BOUND",
	},
} as unknown as WorkspaceExecutionPackage;

describe("T2VModule copy-binding gate (Phase B enforcement)", () => {
	afterEach(() => cleanup());

	it("[gate] NOT READY / no copy-bound package → SEND blocked until explicit fallback", async () => {
		const onExecute = vi.fn();
		render(
			<T2VModule
				onExecute={onExecute}
				isExecuting={false}
				workspacePackage={null}
				videoModels={MODELS}
				copyReady={false}
			/>,
		);

		// Manual prompt present but no copy binding → gate visible, SEND blocked.
		fireEvent.change(screen.getByPlaceholderText(/No reference images/i), {
			target: { value: "manual generic copy" },
		});
		const btn = screen.getByRole("button", { name: /SEND TO FLOW EDITOR/i });
		expect(screen.getByTestId("copy-binding-gate")).toBeInTheDocument();
		expect(btn).toBeDisabled();

		// Explicit fallback confirmation unblocks SEND and is recorded in the payload.
		fireEvent.click(screen.getByTestId("copy-fallback-confirm"));
		await waitFor(() => expect(btn).not.toBeDisabled());
		fireEvent.click(btn);

		expect(onExecute).toHaveBeenCalledTimes(1);
		const call = onExecute.mock.calls[0][0];
		expect(call).toMatchObject({
			mode: "T2V",
			copy_set_id: null,
			copy_fallback_confirmed: true,
		});
		expect(call.request_lineage_payload.copy_binding_gate.copy_bound).toBe(false);
	});

	it("[allow] copy-bound package → no gate, SEND allowed, payload carries copy_set_id", async () => {
		const onExecute = vi.fn();
		render(
			<T2VModule
				onExecute={onExecute}
				isExecuting={false}
				workspacePackage={boundPkg}
				videoModels={MODELS}
				copyReady={true}
			/>,
		);

		// Package hydrates the prompt; copy-bound → no gate, SEND enabled immediately.
		const btn = await screen.findByRole("button", { name: /SEND TO FLOW EDITOR/i });
		expect(screen.queryByTestId("copy-binding-gate")).not.toBeInTheDocument();
		await waitFor(() => expect(btn).not.toBeDisabled());
		fireEvent.click(btn);

		expect(onExecute).toHaveBeenCalledTimes(1);
		expect(onExecute.mock.calls[0][0]).toMatchObject({
			mode: "T2V",
			copy_set_id: "cs1",
			copy_fallback_confirmed: false,
		});
	});
});
