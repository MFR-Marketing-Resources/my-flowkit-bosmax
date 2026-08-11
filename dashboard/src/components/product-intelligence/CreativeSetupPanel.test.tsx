import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import CreativeSetupPanel from "./CreativeSetupPanel";
import {
	getCreativeSetupForProduct,
	getProductRecipes,
	saveCreativeSelection,
	reviewCreativeSelection,
} from "../../api/creativeIntelligence";

vi.mock("../../api/creativeIntelligence", () => ({
	getCreativeSetupForProduct: vi.fn(),
	getProductRecipes: vi.fn(),
	saveCreativeSelection: vi.fn(),
	reviewCreativeSelection: vi.fn(),
}));

const mockedGet = vi.mocked(getCreativeSetupForProduct);
const mockedRecipes = vi.mocked(getProductRecipes);
const mockedSave = vi.mocked(saveCreativeSelection);
const mockedReview = vi.mocked(reviewCreativeSelection);

const setup = {
	product_id: "p1", product_name: "Rug", category: "Home & Living",
	cluster: "Home & Living", cluster_source: "EXACT",
	recommended_avatars: [{ avatar_code: "BOS_F_FARAH_02", character_name: "Farah", fit_score: 0.9, fit_source: "EXPLICIT_MAPPING" }],
	recommended_scene_templates: [{ template_id: "SCN-0001", cluster: "Home & Living", variant: "V1", full_prompt_template: "[AVATAR] holds [PRODUCT]" }],
	camera_block_recommendations: [{ block_purpose: "Hook Block", content_type: "Pain Point Question", alt_presets: [] }],
	camera_library: {
		shot_distances: [], camera_angles: [], camera_movements: [], ecomm_shot_types: [],
		named_presets: [{ preset_code: "HOOK_A", preset_name: "Hook - Pain Question", shot_type: "PAIN", distance_angle: "MCU + EYE", movement: "STATIC" }],
	},
	saved_selection: null,
};

describe("CreativeSetupPanel", () => {
	afterEach(() => {
		cleanup();
		vi.resetAllMocks();
	});

	it("renders recommendations and saves a coherent selection (camera follows scene)", async () => {
		mockedGet.mockResolvedValue(structuredClone(setup));
		// Recipes supply the deterministic scene→camera binding, shown read-only.
		mockedRecipes.mockResolvedValue({
			product_id: "p1", cluster: "Home & Living", cluster_source: "EXACT",
			review_required: false, recipes: [],
			recommended_pretick: [
				{
					avatar_code: "BOS_F_FARAH_02", scene_template_id: "SCN-0001",
					scene_variant: "Variation 1 - X", variation: 1,
					camera_preset_code: "BODY_A", camera_alts: [],
					block_purpose: "Body Block", content_type: "Product Demo", rationale: "x",
				},
			],
			counts: { avatars: 1, scenes: 1, recipes: 1, pretick: 1 },
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
		} as any);
		mockedSave.mockResolvedValue({
			product_id: "p1", selection_id: "sel-1", status: "DRAFT",
			selected_avatar_code: "BOS_F_FARAH_02",
			selected_avatar_codes: ["BOS_F_FARAH_02"],
			selected_scene_template_ids: ["SCN-0001"],
			selected_camera_preset_codes: ["BODY_A"],
			preview: { not_for_generation: true },
		});

		render(<CreativeSetupPanel productId="p1" />);
		await screen.findByTestId("creative-setup-panel");

		// avatar + scene lists populate; camera is NOT a separate pick list
		expect(screen.getByTestId("creative-setup-avatar")).toHaveTextContent("BOS_F_FARAH_02");
		expect(screen.getByTestId("creative-setup-scene")).toHaveTextContent("SCN-0001");
		// the camera shows read-only next to its scene (derived from the bridge)
		await waitFor(() =>
			expect(screen.getByTestId("creative-setup-scene")).toHaveTextContent("BODY_A"),
		);
		expect(screen.queryByTestId("creative-setup-camera")).not.toBeInTheDocument();

		// tick avatar + scene (the camera is derived, never ticked)
		fireEvent.click(within(screen.getByTestId("creative-setup-avatar")).getByRole("checkbox"));
		fireEvent.click(within(screen.getByTestId("creative-setup-scene")).getByRole("checkbox"));
		fireEvent.click(screen.getByTestId("creative-setup-save"));

		await waitFor(() => expect(mockedSave).toHaveBeenCalledWith(expect.objectContaining({
			product_id: "p1",
			selected_avatar_codes: ["BOS_F_FARAH_02"],
			selected_scene_template_ids: ["SCN-0001"],
			selected_camera_preset_codes: ["BODY_A"],
		})));

		// saved status appears
		expect(await screen.findByTestId("creative-setup-status")).toHaveTextContent("DRAFT");

		// planning only: no generation / asset-creation control
		expect(screen.queryByRole("button", { name: /generate|create asset|render|produce/i })).not.toBeInTheDocument();
	});

	it("fills a coherent recommendation locally and waits for an explicit save", async () => {
		mockedGet.mockResolvedValue(structuredClone(setup));
		// The recommendation is read-only; it fills the form and leaves review-gated
		// persistence to the explicit Save plan action.
		mockedRecipes.mockResolvedValue({
			product_id: "p1", cluster: "Home & Living", cluster_source: "EXACT",
			review_required: false,
			recipes: [],
			recommended_pretick: [
				{
					avatar_code: "BOS_F_FARAH_02", scene_template_id: "SCN-0001",
					scene_variant: "Variation 1 - X", variation: 1,
					camera_preset_code: "BODY_A", camera_alts: [],
					block_purpose: "Body Block", content_type: "Product Demo", rationale: "x",
				},
			],
			counts: { avatars: 1, scenes: 1, recipes: 1, pretick: 1 },
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
		} as any);
		mockedSave.mockResolvedValue({
			product_id: "p1", selection_id: "sel-1", status: "DRAFT",
			selected_avatar_codes: ["BOS_F_FARAH_02"],
			selected_scene_template_ids: ["SCN-0001"],
			selected_camera_preset_codes: ["BODY_A"],
		});

		render(<CreativeSetupPanel productId="p1" />);
		fireEvent.click(await screen.findByTestId("creative-setup-autofill"));

		await waitFor(() => expect(
			within(screen.getByTestId("creative-setup-avatar")).getByRole("checkbox"),
		).toBeChecked());
		expect(within(screen.getByTestId("creative-setup-scene")).getByRole("checkbox")).toBeChecked();
		expect(mockedSave).not.toHaveBeenCalled();
		expect(mockedReview).not.toHaveBeenCalled();

		fireEvent.click(screen.getByTestId("creative-setup-save"));
		await waitFor(() => expect(mockedSave).toHaveBeenCalledWith(expect.objectContaining({
			product_id: "p1",
			selected_avatar_codes: ["BOS_F_FARAH_02"],
			selected_scene_template_ids: ["SCN-0001"],
			selected_camera_preset_codes: ["BODY_A"],
		})));
		expect(mockedReview).not.toHaveBeenCalled();
		expect(await screen.findByTestId("creative-setup-status")).toHaveTextContent("DRAFT");
	});

	it("shows approve/reject on a DRAFT and transitions on approve", async () => {
		mockedGet.mockResolvedValue({
			...structuredClone(setup),
			saved_selection: {
				product_id: "p1", selection_id: "sel-1", status: "DRAFT",
				selected_avatar_code: "BOS_F_FARAH_02", preview: { not_for_generation: true },
				selected_scene_template_id: "SCN-0001",
			},
		});
		mockedReview.mockResolvedValue({
			product_id: "p1", selection_id: "sel-1", status: "APPROVED",
			selected_avatar_code: "BOS_F_FARAH_02", preview: { not_for_generation: true },
			selected_scene_template_id: "SCN-0001",
		});

		render(<CreativeSetupPanel productId="p1" />);
		fireEvent.click(await screen.findByTestId("creative-setup-approve"));
		await waitFor(() => expect(mockedReview).toHaveBeenCalledWith("p1", "APPROVE"));
		expect(await screen.findByTestId("creative-setup-status")).toHaveTextContent("APPROVED");
	});

	it("shows an error state without crashing", async () => {
		mockedGet.mockRejectedValue(new Error("API 500: boom"));
		render(<CreativeSetupPanel productId="p3" />);
		expect(await screen.findByText(/Unable to load creative setup:/i)).toBeInTheDocument();
	});

	it("keeps recommended avatars unique and locks review until approved edits are saved", async () => {
		mockedGet.mockResolvedValue({
			...structuredClone(setup),
			avatar_library: [
				{ avatar_code: "BOS_F_FARAH_02", character_name: "Farah", recommended: true },
				{ avatar_code: "BOS_F_ALYA_08", character_name: "Alya", recommended: false },
			],
			saved_selection: {
				product_id: "p1", selection_id: "sel-1", status: "APPROVED",
				selected_avatar_codes: ["BOS_F_FARAH_02"],
				selected_scene_template_ids: ["SCN-0001"],
				notes: "Existing plan",
			},
		});
		mockedRecipes.mockResolvedValue({
			product_id: "p1", cluster: "Home & Living", cluster_source: "EXACT",
			review_required: false, recipes: [], recommended_pretick: [],
			counts: { avatars: 1, scenes: 1, recipes: 1, pretick: 0 },
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
		} as any);

		render(<CreativeSetupPanel productId="p1" />);
		const avatarPicker = await screen.findByTestId("creative-setup-avatar");
		expect(within(avatarPicker).getAllByRole("checkbox")).toHaveLength(2);
		expect(screen.getAllByText("BOS_F_FARAH_02", { exact: true })).toHaveLength(1);
		expect(screen.queryByTestId("creative-setup-camera")).not.toBeInTheDocument();

		fireEvent.change(screen.getByTestId("creative-setup-notes"), {
			target: { value: "Updated reviewer note" },
		});
		expect(screen.getByTestId("creative-setup-status")).toHaveTextContent("UNSAVED");
		expect(screen.queryByTestId("creative-setup-approve")).not.toBeInTheDocument();
		expect(screen.getByTestId("creative-setup-save")).not.toBeDisabled();
	});
});
