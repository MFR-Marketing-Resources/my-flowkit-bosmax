import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import RecommendedAvatarsCard from "./RecommendedAvatarsCard";
import { getAvatarRecommendationForProduct } from "../../api/creativeIntelligence";

vi.mock("../../api/creativeIntelligence", () => ({
	getAvatarRecommendationForProduct: vi.fn(),
}));

const mocked = vi.mocked(getAvatarRecommendationForProduct);

describe("RecommendedAvatarsCard", () => {
	afterEach(() => {
		cleanup();
		vi.resetAllMocks();
	});

	it("renders recommended BOS_ avatars with cluster + fit, and no generate control", async () => {
		mocked.mockResolvedValue({
			product_id: "p1", product_name: "Serum", category: "Beauty & Personal Care",
			cluster: "Beauty", cluster_source: "EXACT", avatar_count: 2,
			avatars: [
				{ avatar_code: "BOS_F_ALYA_08", character_name: "Alya", fit_score: 0.92, fit_source: "EXPLICIT_MAPPING", suitability_notes: "Beauty studio" },
				{ avatar_code: "BOS_F_ZARA_08", character_name: "Zara", fit_score: 0.9, fit_source: "EXPLICIT_MAPPING" },
			],
		});

		render(<RecommendedAvatarsCard productId="p1" />);

		const list = await screen.findByTestId("recommended-avatars-list");
		expect(list).toHaveTextContent("BOS_F_ALYA_08");
		expect(list).toHaveTextContent("BOS_F_ZARA_08");
		expect(screen.getByTestId("recommended-avatars-card")).toHaveTextContent(/cluster: Beauty/);
		await waitFor(() => expect(mocked).toHaveBeenCalledWith("p1"));
		// Read-only: no generate/create control anywhere in the card.
		expect(screen.queryByRole("button", { name: /generate|create|approve/i })).not.toBeInTheDocument();
	});

	it("shows an empty state when there are no recommendations", async () => {
		mocked.mockResolvedValue({
			cluster: "Home & Living", cluster_source: "FALLBACK", avatar_count: 0, avatars: [],
		});
		render(<RecommendedAvatarsCard productId="p2" />);
		expect(await screen.findByText(/No avatar recommendations available/i)).toBeInTheDocument();
	});

	it("shows an error state without crashing", async () => {
		mocked.mockRejectedValue(new Error("API 500: boom"));
		render(<RecommendedAvatarsCard productId="p3" />);
		expect(await screen.findByText(/Unable to load recommendations:/i)).toBeInTheDocument();
	});
});
