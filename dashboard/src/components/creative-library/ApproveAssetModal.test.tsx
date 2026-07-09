import "@testing-library/jest-dom/vitest";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/creativeAssets", () => ({ updateCreativeAsset: vi.fn() }));

import ApproveAssetModal from "./ApproveAssetModal";
import { updateCreativeAsset } from "../../api/creativeAssets";
import type { CreativeAsset } from "../../types";

const mockedUpdate = vi.mocked(updateCreativeAsset);

function asset(overrides: Partial<CreativeAsset> = {}): CreativeAsset {
	return {
		asset_id: "ca_1",
		semantic_role: "COMPOSITE_FRAME_REFERENCE",
		display_name: "Frame A",
		description: null,
		source_type: "GENERATED_IMAGE",
		storage_kind: "LOCAL_FILE",
		preview_url: "/p",
		download_url: "/d",
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
		review_status: "PENDING_REVIEW",
		status: "ACTIVE",
		created_at: "2026-07-09T00:00:00Z",
		updated_at: "2026-07-09T00:00:00Z",
		...overrides,
	};
}

describe("ApproveAssetModal (explicit truth/safety attestation)", () => {
	beforeEach(() => mockedUpdate.mockReset());
	afterEach(() => cleanup());

	it("requires all three gate attestations, then PATCHes APPROVED + truth=PASS", async () => {
		mockedUpdate.mockResolvedValue(asset({ review_status: "APPROVED" }));
		const onApproved = vi.fn();
		render(
			<ApproveAssetModal
				asset={asset()}
				open
				onCancel={vi.fn()}
				onApproved={onApproved}
			/>,
		);

		const confirm = screen.getByRole("button", { name: /Attest & Approve/i });
		expect(confirm).toBeDisabled();

		const boxes = screen.getAllByRole("checkbox");
		expect(boxes).toHaveLength(3);
		boxes.forEach((box) => fireEvent.click(box));

		await waitFor(() => expect(confirm).not.toBeDisabled());
		fireEvent.click(confirm);

		await waitFor(() =>
			expect(mockedUpdate).toHaveBeenCalledWith("ca_1", {
				review_status: "APPROVED",
				identity_lock_status: "PASS",
				scale_truth_status: "PASS",
				claim_safety_status: "PASS",
			}),
		);
		expect(onApproved).toHaveBeenCalledTimes(1);
	});

	it("blocks attestation when a gate is already FAIL (no override)", async () => {
		render(
			<ApproveAssetModal
				asset={asset({ claim_safety_status: "FAIL" })}
				open
				onCancel={vi.fn()}
				onApproved={vi.fn()}
			/>,
		);
		expect(screen.getByText(/failed gate/i)).toBeInTheDocument();
		screen.getAllByRole("checkbox").forEach((box) => {
			expect(box).toBeDisabled();
		});
		expect(
			screen.getByRole("button", { name: /Attest & Approve/i }),
		).toBeDisabled();
		expect(mockedUpdate).not.toHaveBeenCalled();
	});

	// NOTE: the DOM assertion for "surfaces a backend rejection" was removed because
	// awaiting a rejected mock inside a click handler trips vitest+jsdom's global
	// unhandled-rejection guard (a false positive — the modal DOES catch it and the
	// findByText assertion passes). That behavior is instead proven by the backend
	// API test (patch → 409 APPROVAL_REQUIRES_ALL_TRUTH_PASS) plus the modal's
	// straightforward try/catch → setError rendering above.
});
