import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import CreativeHandoffPreview, { handoffBlockedMessage } from "./CreativeHandoffPreview";
import { getCreativeHandoffForProduct } from "../../api/creativeIntelligence";

vi.mock("../../api/creativeIntelligence", () => ({
	getCreativeHandoffForProduct: vi.fn(),
}));

const mocked = vi.mocked(getCreativeHandoffForProduct);

describe("CreativeHandoffPreview", () => {
	afterEach(() => {
		cleanup();
		vi.resetAllMocks();
	});

	it("prepares a handoff preview on click and shows resolved prompt (no auto-generate)", async () => {
		mocked.mockResolvedValue({
			product_id: "p1", product_name: "Karpet Velvet", selection_id: "sel-1",
			selection_status: "APPROVED", cluster: "Home & Living", cluster_source: "EXACT",
			avatar: { avatar_code: "BOS_F_FARAH_02", character_name: "Farah", resolved_descriptor: "The presenter is a Malaysian adult woman" },
			scene_template: { template_id: "SCN-0001", variant: "V1", raw_prompt_template: "[AVATAR] holds [PRODUCT]" },
			camera_preset: { preset_code: "HOOK_A", shot_type: "PAIN", distance_angle: "MCU + EYE", movement: "STATIC" },
			resolved_prompt_preview: "The presenter is a Malaysian adult woman holds Karpet Velvet",
			placeholders_resolved: { "[AVATAR]": true, "[PRODUCT]": true },
			provenance: { source: "CREATIVE_HANDOFF_v1" },
			auto_generated: false, requires_confirmation: true,
			handoff_status: "PREVIEW_ONLY_REQUIRES_CONFIRMATION",
			note: "Generation handoff PREVIEW only. No generation.",
		});

		render(<CreativeHandoffPreview productId="p1" />);
		// nothing loaded until explicit action
		expect(screen.queryByTestId("creative-handoff-payload")).not.toBeInTheDocument();

		fireEvent.click(screen.getByTestId("creative-handoff-prepare"));
		await waitFor(() => expect(mocked).toHaveBeenCalledWith("p1"));

		const payload = await screen.findByTestId("creative-handoff-payload");
		expect(payload).toHaveTextContent("APPROVED");
		expect(payload).toHaveTextContent("BOS_F_FARAH_02");
		expect(payload).toHaveTextContent("HOOK_A");
		// resolved prompt has placeholders resolved
		const resolved = screen.getByTestId("creative-handoff-resolved-prompt");
		expect(resolved).toHaveTextContent("Karpet Velvet");
		expect(resolved.textContent).not.toContain("[AVATAR]");
		expect(resolved.textContent).not.toContain("[PRODUCT]");
		// preview banner present
		expect(screen.getByTestId("creative-handoff-banner")).toHaveTextContent(/PREVIEW_ONLY_REQUIRES_CONFIRMATION/);
		// no auto-generate / asset-creation control
		expect(screen.queryByRole("button", { name: /^generate|create asset|render video|start generation|produce/i })).not.toBeInTheDocument();
	});

	it("shows a clear blocked message when the selection is not APPROVED (DRAFT/REJECTED)", async () => {
		mocked.mockRejectedValue(new Error('API 409: {"detail":"SELECTION_NOT_APPROVED"}'));
		render(<CreativeHandoffPreview productId="p2" />);
		fireEvent.click(screen.getByTestId("creative-handoff-prepare"));
		const err = await screen.findByTestId("creative-handoff-error");
		expect(err).toHaveTextContent(/not APPROVED yet/i);
		expect(err).toHaveTextContent(/Approve the saved selection above/i);
		// raw error code is not shown to the user
		expect(err.textContent).not.toContain("SELECTION_NOT_APPROVED");
	});

	it("shows a clear blocked message when there is no saved selection", async () => {
		mocked.mockRejectedValue(new Error('API 404: {"detail":"SELECTION_NOT_FOUND"}'));
		render(<CreativeHandoffPreview productId="p3" />);
		fireEvent.click(screen.getByTestId("creative-handoff-prepare"));
		expect(await screen.findByTestId("creative-handoff-error")).toHaveTextContent(/No saved creative selection/i);
	});
});

describe("handoffBlockedMessage", () => {
	it("maps each fail-closed code to clear, code-free copy", () => {
		expect(handoffBlockedMessage('API 409: {"detail":"SELECTION_NOT_APPROVED"}')).toMatch(/not APPROVED yet/i);
		expect(handoffBlockedMessage('API 404: {"detail":"SELECTION_NOT_FOUND"}')).toMatch(/No saved creative selection/i);
		expect(handoffBlockedMessage('API 404: {"detail":"PRODUCT_NOT_FOUND"}')).toMatch(/Product not found/i);
		expect(handoffBlockedMessage('API 422: {"detail":"INVALID_AVATAR_CODE"}')).toMatch(/avatar is no longer valid/i);
		expect(handoffBlockedMessage('API 422: {"detail":"INVALID_SCENE_TEMPLATE_ID"}')).toMatch(/scene template is no longer valid/i);
		expect(handoffBlockedMessage('API 422: {"detail":"INVALID_CAMERA_PRESET_CODE"}')).toMatch(/camera preset is no longer valid/i);
		// none of the mapped messages leak the raw code
		for (const code of ["SELECTION_NOT_APPROVED", "SELECTION_NOT_FOUND", "INVALID_AVATAR_CODE"]) {
			expect(handoffBlockedMessage(`API 409: {"detail":"${code}"}`)).not.toContain(code);
		}
	});
});
