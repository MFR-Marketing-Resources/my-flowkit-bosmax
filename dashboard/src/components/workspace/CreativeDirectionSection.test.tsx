import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import CreativeDirectionSection, {
	EMPTY_CREATIVE_DIRECTION,
	type CreativeDirection,
} from "./CreativeDirectionSection";
import { getProductRecipes } from "../../api/creativeIntelligence";

vi.mock("../../api/creativeIntelligence", () => ({
	getProductRecipes: vi.fn(),
}));

function recipe(avatar: string, scene: string, variation: number, camera: string) {
	return {
		avatar_code: avatar,
		scene_template_id: scene,
		scene_variant: `Variation ${variation} - Sample`,
		variation,
		camera_preset_code: camera,
		camera_alts: [],
		block_purpose: "Body Block",
		content_type: "Product Demo",
		rationale: `${avatar} x ${scene} -> ${camera}`,
	};
}

const POOL = [
	recipe("BOS_F_AINA_01", "SCN-01", 1, "BODY_A"),
	recipe("BOS_F_AINA_01", "SCN-05", 5, "BODY_B"),
	recipe("BOS_M_AMIR_01", "SCN-01", 1, "BODY_A"),
];
const PRETICK = [POOL[0], POOL[1]];

const RESPONSE = {
	product_id: "p1",
	cluster: "Food & Beverage",
	cluster_source: "EXACT",
	review_required: false,
	recipes: POOL,
	recommended_pretick: PRETICK,
	counts: { avatars: 2, scenes: 2, recipes: 3, pretick: 2 },
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any;

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

describe("CreativeDirectionSection (recipe rows)", () => {
	it("renders coherent recipe rows and pre-fills the smart-suggest pretick", async () => {
		vi.mocked(getProductRecipes).mockResolvedValue(RESPONSE);
		const onChange = vi.fn();
		render(
			<CreativeDirectionSection
				productId="p1"
				value={EMPTY_CREATIVE_DIRECTION}
				onChange={onChange}
			/>,
		);
		await waitFor(() =>
			expect(screen.getByTestId("creative-direction-section")).toBeInTheDocument(),
		);
		// one row per pool recipe (camera shown = follows scene)
		expect(screen.getAllByTestId("creative-direction-recipe")).toHaveLength(3);
		expect(screen.getByTestId("creative-direction-smart-suggest")).toBeInTheDocument();
		// pre-fills the pretick, deriving the backward-compatible 3 lists
		await waitFor(() =>
			expect(onChange).toHaveBeenCalledWith(
				expect.objectContaining<Partial<CreativeDirection>>({
					recipes: PRETICK,
					avatarCodes: ["BOS_F_AINA_01"],
					sceneTemplateIds: ["SCN-01", "SCN-05"],
					cameraPresetCodes: ["BODY_A", "BODY_B"],
				}),
			),
		);
	});

	it("is descriptor-only — never renders image thumbnails", async () => {
		vi.mocked(getProductRecipes).mockResolvedValue(RESPONSE);
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
