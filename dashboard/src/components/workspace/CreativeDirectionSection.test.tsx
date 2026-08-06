import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import CreativeDirectionSection, {
	EMPTY_CREATIVE_DIRECTION,
	type CreativeDirection,
} from "./CreativeDirectionSection";
import { getCreativeSetupForProduct } from "../../api/creativeIntelligence";

vi.mock("../../api/creativeIntelligence", () => ({
	getCreativeSetupForProduct: vi.fn(),
}));

const SETUP = {
	product_id: "p1",
	cluster: "Food & Beverage",
	cluster_source: "EXACT",
	recommended_avatars: [],
	avatar_library: [
		{ avatar_code: "BOS_F_FARAH_01", character_name: "Farah", recommended: true },
		{ avatar_code: "BOS_F_AINA_01", character_name: "Aina", recommended: false },
	],
	default_selection: {
		selected_avatar_codes: ["BOS_F_FARAH_01"],
		selected_scene_template_ids: ["SCN-0078"],
		selected_camera_preset_codes: ["HOOK_A"],
	},
	recommended_scene_templates: [{ template_id: "SCN-0078", variant: "Variation 1" }],
	camera_block_recommendations: [],
	camera_library: {
		named_presets: [{ preset_code: "HOOK_A", preset_name: "Hook - Pain Question" }],
	},
	saved_selection: null,
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any;

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

describe("CreativeDirectionSection", () => {
	it("renders the 3 descriptor dropdowns and pre-fills from the smart default", async () => {
		vi.mocked(getCreativeSetupForProduct).mockResolvedValue(SETUP);
		const onChange = vi.fn();
		render(
			<CreativeDirectionSection
				productId="p1"
				value={EMPTY_CREATIVE_DIRECTION}
				onChange={onChange}
			/>,
		);
		await waitFor(() =>
			expect(screen.getByTestId("creative-direction-avatar")).toBeInTheDocument(),
		);
		expect(screen.getByTestId("creative-direction-scene")).toBeInTheDocument();
		expect(screen.getByTestId("creative-direction-camera")).toBeInTheDocument();
		expect(screen.getByText(/BOS_F_FARAH_01 · Farah/)).toBeInTheDocument();
		await waitFor(() =>
			expect(onChange).toHaveBeenCalledWith(
				expect.objectContaining<Partial<CreativeDirection>>({
					avatarCodes: ["BOS_F_FARAH_01"],
					sceneTemplateIds: ["SCN-0078"],
					cameraPresetCodes: ["HOOK_A"],
				}),
			),
		);
	});

	it("is descriptor-only — never renders image thumbnails", async () => {
		vi.mocked(getCreativeSetupForProduct).mockResolvedValue(SETUP);
		render(
			<CreativeDirectionSection
				productId="p1"
				value={EMPTY_CREATIVE_DIRECTION}
				onChange={vi.fn()}
			/>,
		);
		await waitFor(() =>
			expect(screen.getByTestId("creative-direction-section")).toBeInTheDocument(),
		);
		expect(
			screen.getByTestId("creative-direction-section").querySelectorAll("img").length,
		).toBe(0);
	});
});
