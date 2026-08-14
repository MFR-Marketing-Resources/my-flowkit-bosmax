import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CreativeAsset } from "../../types";

const fetchAPIMock = vi.fn();
const fetchAuditMock = vi.fn();

vi.mock("../../api/client", () => ({
	fetchAPI: (...args: unknown[]) => fetchAPIMock(...args),
}));
vi.mock("../../api/creativeAssets", () => ({
	fetchCreativeAssetEligibilityAudit: (...args: unknown[]) =>
		fetchAuditMock(...args),
}));
vi.mock("./VisualAssetPicker", () => ({ default: () => null }));

import CanonicalReferenceBindingControls, {
	EMPTY_BINDING,
	type CanonicalReferenceBinding,
} from "./CanonicalReferenceBindingControls";

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

function asset(assetId: string, displayName: string): CreativeAsset {
	return {
		asset_id: assetId,
		display_name: displayName,
		preview_url: `/preview/${assetId}`,
		review_status: "APPROVED",
		status: "ACTIVE",
	} as CreativeAsset;
}

function Harness({ mode }: { mode: "I2V" | "F2V" | "HYBRID" }) {
	const binding: CanonicalReferenceBinding = EMPTY_BINDING;
	return (
		<>
			<CanonicalReferenceBindingControls
				mode={mode}
				productId="product-1"
				productCluster="Food & Beverage"
				mappedAvatarCode="BOS_F_SARA_01"
				mappedSceneStrategyId="SCN-0078"
				binding={binding}
				onChange={(next) => {
					document.body.dataset.characterAsset =
						next.characterReferenceAssetId ?? "";
				}}
			/>
		</>
	);
}

describe("CanonicalReferenceBindingControls product authority", () => {
	it("shows only the mapped I2V avatar and product-cluster scene rows", async () => {
		fetchAPIMock.mockImplementation((url: string) => {
			if (url.includes("avatar-registry")) {
				return Promise.resolve({
					avatars: [
						{
							avatar_code: "BOS_F_FARAH_01",
							character_name: "Farah",
							generated_asset_id: "ca_farah",
						},
						{
							avatar_code: "BOS_F_SARA_01",
							character_name: "Sara",
							generated_asset_id: "ca_sara",
						},
					],
				});
			}
			return Promise.resolve({
				scenes: [
					{
						scene_code: "SCN_FOOD",
						scene_name: "Food Scene",
						generated_asset_id: "ca_food",
						primary_cluster: "Food & Beverage",
						compatible_clusters: ["Food & Beverage"],
					},
					{
						scene_code: "SCN_OFFICE",
						scene_name: "Office Scene",
						generated_asset_id: "ca_office",
						primary_cluster: "Office & Stationery",
						compatible_clusters: ["Office & Stationery"],
					},
				],
			});
		});
		fetchAuditMock.mockImplementation(({ surface }: { surface: string }) =>
			Promise.resolve({
				surface,
				library_total_count: 4,
				matching_role_total_count: 4,
				eligible_count: 4,
				excluded_count: 0,
				excluded_by_reason: {},
				review_status_counts: {},
				eligible_assets:
					surface === "I2V_CHARACTER_PICKER"
						? [asset("ca_farah", "Farah"), asset("ca_sara", "Sara")]
						: surface === "I2V_SCENE_PICKER"
							? [asset("ca_food", "Food Scene"), asset("ca_office", "Office Scene")]
							: [],
			}),
		);

		render(<Harness mode="I2V" />);

		expect(screen.getByTestId("i2v-required-image-plan")).toHaveTextContent(
			"I2V uses three required engine images",
		);
		expect(await screen.findByRole("option", { name: /Sara/ })).toBeInTheDocument();
		expect(screen.queryByRole("option", { name: /Farah/ })).toBeNull();
		expect(screen.getByRole("option", { name: /Food Scene/ })).toBeInTheDocument();
		expect(screen.queryByRole("option", { name: /Office Scene/ })).toBeNull();
		await waitFor(() =>
			expect(document.body.dataset.characterAsset).toBe("ca_sara"),
		);
	});

	it.each(["F2V", "HYBRID"] as const)(
		"does not expose Scene Registry configuration for %s",
		(mode) => {
			fetchAuditMock.mockResolvedValue({
				eligible_assets: [],
				library_total_count: 0,
				matching_role_total_count: 0,
				excluded_count: 0,
				excluded_by_reason: {},
				review_status_counts: {},
			});
			render(<Harness mode={mode} />);
			expect(screen.queryByText(/Scene Registry/i)).toBeNull();
		},
	);
});
