import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import RecommendedScenePromptsCard from "./RecommendedScenePromptsCard";
import { getScenePromptRecommendationForProduct } from "../../api/creativeIntelligence";

vi.mock("../../api/creativeIntelligence", () => ({
	getScenePromptRecommendationForProduct: vi.fn(),
}));

const mocked = vi.mocked(getScenePromptRecommendationForProduct);

describe("RecommendedScenePromptsCard", () => {
	afterEach(() => {
		cleanup();
		vi.resetAllMocks();
	});

	it("renders scene templates with cluster, preserves placeholders, no generate control", async () => {
		mocked.mockResolvedValue({
			product_id: "p1", product_name: "Rug", category: "Home & Living",
			cluster: "Home & Living", cluster_source: "EXACT", template_count: 1,
			templates: [
				{
					template_id: "SCN-0001", cluster: "Home & Living", source_category: "Home & Living",
					cluster_source: "EXACT", variant: "Variation 1",
					main_action: "Gently holding the [PRODUCT] with both hands",
					setting: "Bright cozy living room",
					full_prompt_template: "[AVATAR], photorealistic. Holding the [PRODUCT].",
				},
			],
			global_config: { style_suffix: "photorealistic, high detail", negative_prompt: "blurry, low quality" },
			cluster_has_templates: true,
		});

		render(<RecommendedScenePromptsCard productId="p1" />);

		const list = await screen.findByTestId("recommended-scene-prompts-list");
		expect(list).toHaveTextContent("SCN-0001");
		// placeholders must remain unresolved in the preview
		expect(list).toHaveTextContent("[AVATAR]");
		expect(list).toHaveTextContent("[PRODUCT]");
		expect(screen.getByTestId("recommended-scene-prompts-card")).toHaveTextContent(/cluster: Home & Living/);
		expect(screen.getByTestId("scene-global-style")).toHaveTextContent(/photorealistic/);
		await waitFor(() => expect(mocked).toHaveBeenCalledWith("p1"));
		// Read-only: no generate/create/approve control anywhere in the card.
		expect(screen.queryByRole("button", { name: /generate|create|approve/i })).not.toBeInTheDocument();
	});

	it("shows an empty state for a cluster with no templates", async () => {
		mocked.mockResolvedValue({
			cluster: "Pet Care", cluster_source: "EXACT", template_count: 0,
			templates: [], global_config: {}, cluster_has_templates: false,
		});
		render(<RecommendedScenePromptsCard productId="p2" />);
		expect(await screen.findByTestId("recommended-scene-prompts-empty")).toBeInTheDocument();
	});

	it("shows an error state without crashing", async () => {
		mocked.mockRejectedValue(new Error("API 500: boom"));
		render(<RecommendedScenePromptsCard productId="p3" />);
		expect(await screen.findByText(/Unable to load scene prompts:/i)).toBeInTheDocument();
	});
});
