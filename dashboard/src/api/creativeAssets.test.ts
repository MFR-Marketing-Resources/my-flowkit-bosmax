import { beforeEach, describe, expect, it, vi } from "vitest";

// updateCreativeAsset goes through patchAPI — mock the transport so we can assert the
// exact PATCH body (the metadata-clobber fix is a payload-shape guarantee).
vi.mock("./client", () => ({
	fetchAPI: vi.fn(),
	patchAPI: vi.fn(),
	postAPI: vi.fn(),
}));

import { updateCreativeAsset } from "./creativeAssets";
import { patchAPI } from "./client";

const mockedPatch = vi.mocked(patchAPI);

function lastBody(): Record<string, unknown> {
	return mockedPatch.mock.calls[0][1] as Record<string, unknown>;
}

describe("updateCreativeAsset payload safety (metadata clobber fix)", () => {
	beforeEach(() => {
		mockedPatch.mockReset();
		mockedPatch.mockResolvedValue({} as never);
	});

	it("review-only PATCH does NOT send mode_a_metadata_handoff", async () => {
		await updateCreativeAsset("ca_1", { review_status: "APPROVED" });
		const [url, body] = mockedPatch.mock.calls[0];
		expect(url).toBe("/api/creative-assets/ca_1");
		expect("mode_a_metadata_handoff" in (body as object)).toBe(false);
		expect(body).toEqual({ review_status: "APPROVED" });
	});

	it("attestation PATCH sends review_status + truth PASS, still no handoff key", async () => {
		await updateCreativeAsset("ca_1", {
			review_status: "APPROVED",
			identity_lock_status: "PASS",
			scale_truth_status: "PASS",
			claim_safety_status: "PASS",
		});
		const body = lastBody();
		expect(body.identity_lock_status).toBe("PASS");
		expect(body.scale_truth_status).toBe("PASS");
		expect(body.claim_safety_status).toBe("PASS");
		expect("mode_a_metadata_handoff" in body).toBe(false);
	});

	it("explicit metadata update still sends the normalized handoff", async () => {
		await updateCreativeAsset("ca_1", { mode_a_metadata_handoff: '{"a":1}' });
		const body = lastBody();
		expect(body.mode_a_metadata_handoff).toEqual({ a: 1 });
	});

	it("explicit metadata clear ('') still sends null", async () => {
		await updateCreativeAsset("ca_1", { mode_a_metadata_handoff: "" });
		const body = lastBody();
		expect("mode_a_metadata_handoff" in body).toBe(true);
		expect(body.mode_a_metadata_handoff).toBeNull();
	});
});
