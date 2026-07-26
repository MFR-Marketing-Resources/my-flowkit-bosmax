import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./client", () => ({
	getAPI: vi.fn(),
	postAPI: vi.fn(),
	patchAPI: vi.fn(),
}));

import { patchAPI } from "./client";
import { patchCreativeSelectionAvatar } from "./creativeIntelligence";

const mockedPatch = vi.mocked(patchAPI);

describe("patchCreativeSelectionAvatar", () => {
	beforeEach(() => {
		mockedPatch.mockReset();
		mockedPatch.mockResolvedValue({
			status: "DRAFT",
			selected_avatar_code: "BOS_F_ALYA_01",
			selected_scene_template_id: "SCN-0015",
		});
	});

	it("calls the avatar-only PATCH contract (not full save)", async () => {
		await patchCreativeSelectionAvatar({
			product_id: "prod-1",
			selected_avatar_code: "BOS_F_ALYA_01",
			notes_append: "from registry",
		});
		expect(mockedPatch).toHaveBeenCalledTimes(1);
		expect(mockedPatch).toHaveBeenCalledWith(
			"/api/creative-intelligence/creative-selection/avatar",
			{
				product_id: "prod-1",
				selected_avatar_code: "BOS_F_ALYA_01",
				notes_append: "from registry",
			},
		);
	});
});
