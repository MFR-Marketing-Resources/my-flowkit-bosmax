import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import RecommendedCameraPresetsCard from "./RecommendedCameraPresetsCard";
import { getCameraPresetRecommendationForProduct } from "../../api/creativeIntelligence";

vi.mock("../../api/creativeIntelligence", () => ({
	getCameraPresetRecommendationForProduct: vi.fn(),
}));

const mocked = vi.mocked(getCameraPresetRecommendationForProduct);

const fullLibrary = {
	shot_distances: [{ code: "ECU" }],
	camera_angles: [{ code: "EYE" }],
	camera_movements: [{ code: "STATIC" }],
	ecomm_shot_types: [{ code: "HERO" }],
	named_presets: [{ preset_code: "HOOK_A" }],
};

describe("RecommendedCameraPresetsCard", () => {
	afterEach(() => {
		cleanup();
		vi.resetAllMocks();
	});

	it("renders camera presets with cluster, preset detail, and no generate control", async () => {
		mocked.mockResolvedValue({
			product_id: "p1", product_name: "Rug", category: "Home & Living",
			cluster: "Home & Living", cluster_source: "EXACT",
			block_groups: ["HOOK", "BODY", "CTA", "TRANS"], block_recommendation_count: 1,
			block_recommendations: [{
				block_purpose: "Hook Block", content_type: "Pain Point Question",
				recommended_preset: {
					preset_code: "HOOK_A", preset_name: "Hook - Pain Question",
					shot_type: "PAIN", distance_angle: "MCU + EYE", movement: "STATIC",
				},
				alt_presets: [{ preset_code: "HOOK_C" }],
			}],
			library: fullLibrary,
			filtered_by: { block: null, content_type: null },
			has_recommendations: true,
		});

		render(<RecommendedCameraPresetsCard productId="p1" />);

		const list = await screen.findByTestId("recommended-camera-presets-list");
		expect(list).toHaveTextContent("HOOK_A");
		expect(list).toHaveTextContent("Hook Block");
		expect(list).toHaveTextContent("PAIN");
		expect(list).toHaveTextContent("MCU + EYE");
		expect(screen.getByTestId("recommended-camera-presets-card")).toHaveTextContent(/cluster: Home & Living/);
		await waitFor(() => expect(mocked).toHaveBeenCalledWith("p1"));
		// Read-only: no generate/create/approve control anywhere in the card.
		expect(screen.queryByRole("button", { name: /generate|create|approve/i })).not.toBeInTheDocument();
	});

	it("shows an empty state when there are no recommendations", async () => {
		mocked.mockResolvedValue({
			cluster: "Pet Care", cluster_source: "EXACT", block_groups: [],
			block_recommendation_count: 0, block_recommendations: [],
			library: fullLibrary, filtered_by: { block: null, content_type: null },
			has_recommendations: false,
		});
		render(<RecommendedCameraPresetsCard productId="p2" />);
		expect(await screen.findByTestId("recommended-camera-presets-empty")).toBeInTheDocument();
	});

	it("shows an error state without crashing", async () => {
		mocked.mockRejectedValue(new Error("API 500: boom"));
		render(<RecommendedCameraPresetsCard productId="p3" />);
		expect(await screen.findByText(/Unable to load camera presets:/i)).toBeInTheDocument();
	});
});
