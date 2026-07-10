import { beforeEach, describe, expect, it, vi } from "vitest";

const { postAPI } = vi.hoisted(() => ({ postAPI: vi.fn() }));

vi.mock("./client", () => ({
	fetchAPI: vi.fn(),
	postAPI,
}));

import {
	compileWorkspacePromptPreview,
	createWorkspaceExecutionPackage,
} from "./workspacePackages";

describe("workspace package duration authority serialization", () => {
	beforeEach(() => postAPI.mockReset());

	it("omits legacy duration and raw blocks from EXTEND preview and execution payloads", async () => {
		const extendInput = {
			product_id: "prod-duration-authority",
			mode: "T2V" as const,
			generation_mode: "EXTEND" as const,
			engine_duration_target: "GOOGLE_FLOW" as const,
			requested_total_duration_seconds: 24,
		};

		await compileWorkspacePromptPreview(extendInput);
		await createWorkspaceExecutionPackage(extendInput);

		for (const [, payload] of postAPI.mock.calls) {
			expect(payload).toMatchObject({
				generation_mode: "EXTEND",
				engine_duration_target: "GOOGLE_FLOW",
				requested_total_duration_seconds: 24,
			});
			expect(payload).not.toHaveProperty("blocks");
			expect(payload).not.toHaveProperty("duration_seconds");
		}
	});

	it("keeps the explicit one-block SINGLE payload intact", async () => {
		await compileWorkspacePromptPreview({
			product_id: "prod-duration-authority",
			mode: "T2V",
			generation_mode: "SINGLE",
			duration_seconds: 10,
			blocks: [],
		});

		expect(postAPI).toHaveBeenCalledWith(
			"/api/workspace/ugc-video-prompt-compile",
			expect.objectContaining({
				generation_mode: "SINGLE",
				duration_seconds: 10,
				blocks: [],
			}),
		);
	});
});
