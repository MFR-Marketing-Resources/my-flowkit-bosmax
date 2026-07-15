import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import CreativeSetupPanel from "./CreativeSetupPanel";
import {
	getCreativeSetupForProduct,
	saveCreativeSelection,
	reviewCreativeSelection,
} from "../../api/creativeIntelligence";

vi.mock("../../api/creativeIntelligence", () => ({
	getCreativeSetupForProduct: vi.fn(),
	saveCreativeSelection: vi.fn(),
	reviewCreativeSelection: vi.fn(),
}));

const mockedGet = vi.mocked(getCreativeSetupForProduct);
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

	it("renders recommendations and saves a selection (no generate control)", async () => {
		mockedGet.mockResolvedValue(structuredClone(setup));
		mockedSave.mockResolvedValue({
			product_id: "p1", selection_id: "sel-1", status: "DRAFT",
			selected_avatar_code: "BOS_F_FARAH_02", selected_scene_template_id: "SCN-0001",
			selected_camera_preset_code: "HOOK_A",
			preview: {
				not_for_generation: true,
				avatar: { avatar_code: "BOS_F_FARAH_02", character_name: "Farah" },
				scene_template: { template_id: "SCN-0001", cluster: "Home & Living", main_action: "holds [PRODUCT]" },
				camera_preset: { preset_code: "HOOK_A", shot_type: "PAIN", distance_angle: "MCU + EYE", movement: "STATIC" },
			},
		});

		render(<CreativeSetupPanel productId="p1" />);
		await screen.findByTestId("creative-setup-panel");

		// recommendations populate the selects
		expect(screen.getByTestId("creative-setup-avatar")).toHaveTextContent("BOS_F_FARAH_02");
		expect(screen.getByTestId("creative-setup-scene")).toHaveTextContent("SCN-0001");
		expect(screen.getByTestId("creative-setup-camera")).toHaveTextContent("HOOK_A");

		fireEvent.change(screen.getByTestId("creative-setup-avatar"), { target: { value: "BOS_F_FARAH_02" } });
		fireEvent.change(screen.getByTestId("creative-setup-scene"), { target: { value: "SCN-0001" } });
		fireEvent.change(screen.getByTestId("creative-setup-camera"), { target: { value: "HOOK_A" } });
		fireEvent.click(screen.getByTestId("creative-setup-save"));

		await waitFor(() => expect(mockedSave).toHaveBeenCalledWith(expect.objectContaining({
			product_id: "p1", selected_avatar_code: "BOS_F_FARAH_02",
			selected_scene_template_id: "SCN-0001", selected_camera_preset_code: "HOOK_A",
		})));

		// saved status + preview appear
		expect(await screen.findByTestId("creative-setup-status")).toHaveTextContent("DRAFT");
		const preview = await screen.findByTestId("creative-setup-preview");
		expect(preview).toHaveTextContent("BOS_F_FARAH_02");
		expect(preview).toHaveTextContent("SCN-0001");
		expect(preview).toHaveTextContent("HOOK_A");

		// planning only: no generation / asset-creation control
		expect(screen.queryByRole("button", { name: /generate|create asset|render|produce/i })).not.toBeInTheDocument();
	});

	it("shows approve/reject on a DRAFT and transitions on approve", async () => {
		mockedGet.mockResolvedValue({
			...structuredClone(setup),
			saved_selection: {
				product_id: "p1", selection_id: "sel-1", status: "DRAFT",
				selected_avatar_code: "BOS_F_FARAH_02", preview: { not_for_generation: true },
			},
		});
		mockedReview.mockResolvedValue({
			product_id: "p1", selection_id: "sel-1", status: "APPROVED",
			selected_avatar_code: "BOS_F_FARAH_02", preview: { not_for_generation: true },
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
});
