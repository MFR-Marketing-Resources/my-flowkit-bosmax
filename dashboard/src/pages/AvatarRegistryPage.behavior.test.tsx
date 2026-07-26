import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AvatarRegistryPage from "./AvatarRegistryPage";

vi.mock("../api/imageGenSettings", () => ({
	useImageGenSettings: () => ({ aspect_options: ["9:16"], models: [{ label: "Nano Banana 2" }] }),
}));
vi.mock("../api/products", () => ({
	fetchProductCatalog: vi.fn().mockResolvedValue({ items: [{ id: "p1", product_display_name: "Visible Product", raw_product_title: "Visible Product", category: "Beauty" }] }),
}));
vi.mock("../api/creativeIntelligence", () => ({
	getAvatarRecommendationForCategory: vi.fn().mockResolvedValue({ avatars: [] }),
	getCreativeSetupForProduct: vi.fn().mockResolvedValue({ review_required: false, cluster: "Beauty", recommended_avatars: [], saved_selection: null }),
	getProductClusterAudit: vi.fn().mockResolvedValue({ product_total: 1, canonical_clusters: ["Beauty"], unknown_review_required: 0, cluster_counts: { Beauty: 1 } }),
	getRegistryCleanupPlan: vi.fn().mockResolvedValue(null),
	getRegistryCoverage: vi.fn().mockResolvedValue(null),
	getRegistryReconciliation: vi.fn().mockResolvedValue(null),
	patchCreativeSelectionAvatar: vi.fn(),
}));
vi.mock("../api/bulkGeneration", () => ({
	createAvatarImageBulk: vi.fn(), cancelBulkRun: vi.fn(), getBulkRun: vi.fn(),
	listBulkRuns: vi.fn().mockResolvedValue({ runs: [] }), registerBulkAvatarAssets: vi.fn(),
	retryFailedBulkRun: vi.fn(), startBulkRun: vi.fn(),
}));
vi.mock("../components/workspace/SearchableProductSelect", () => ({ default: () => <div data-testid="product-selector">Product selector</div> }));
vi.mock("../components/ui", () => ({ DataTable: ({ rows }: { rows: Array<{ avatar_code: string; age_band: string }> }) => <div data-testid="legacy-table">{rows.map((r) => <div key={r.avatar_code}>{r.avatar_code} {r.age_band}</div>)}</div> }));

const legacy = { avatar_code: "BOS_F_LEGACY_99", character_name: "Legacy", variant: "Old", age_band: "Adult (30-54)", skin_tone: "", hair_style: "", wardrobe: "", environment: "", lighting: "", camera: "", expression: "", usage_tags: [], image_generated: false, generated_asset_id: null };
const active = { ...legacy, avatar_code: "BOS_F_ACTIVE_01", character_name: "Active", age_band: "Adult (30-54)", product_clusters: ["beauty"], best_fit_score: 0.9, saved_selection_reference_count: 0 };

describe("AvatarRegistryPage live UX", () => {
	let fetchMock: ReturnType<typeof vi.fn>;
	beforeEach(() => {
		vi.stubGlobal("scrollTo", vi.fn());
		fetchMock = vi.fn(async (url: string) => ({ ok: true, json: async () => {
			if (url.includes("active-product-fit")) return { avatars: [active], count: 1, source: "repo-seed.csv", bridge_active: false };
			if (url.includes("/pool")) return { avatars: [active, legacy], count: 2, bridge_active: false };
			if (url.includes("/vocab")) return { vocab: { age_band: ["Adult (30-54)"], skin_tone: [], hair_style: [], wardrobe: [], expression: [], environment: [], lighting: [], camera: [], usage_tags: [] }, personas: [] };
			return {};
		} }));
		vi.stubGlobal("fetch", fetchMock);
	});
	afterEach(() => vi.unstubAllGlobals());

	it("defaults to product planning, exposes the selector, and never generates while switching views", async () => {
		render(<MemoryRouter><AvatarRegistryPage /></MemoryRouter>);
		await screen.findByTestId("product-selector");
		expect(screen.getByRole("tab", { name: "PRODUCT PLANNING" }).getAttribute("aria-selected")).toBe("true");
		expect(screen.getByTestId("all-registry-legacy-pool").className).toContain("hidden");
		expect(screen.queryByText("Shared image-gen settings — applied to every avatar generate below.")).toBeNull();
		expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, left: 0, behavior: "auto" });

		fireEvent.click(screen.getByRole("tab", { name: "ACTIVE PRODUCT-FIT AVATARS" }));
		await screen.findByTestId("active-product-fit-avatars");
		expect(screen.getByText("BOS_F_ACTIVE_01").textContent).toBe("BOS_F_ACTIVE_01");
		expect(within(screen.getByTestId("active-product-fit-avatars")).getByText("Adult (30-54)").textContent).toBe("Adult (30-54)");
		expect(screen.queryByText("BOS_F_LEGACY_99")).toBeNull();

		fireEvent.click(screen.getByRole("tab", { name: "ALL REGISTRY / LEGACY POOL" }));
		await waitFor(() => expect(screen.getByTestId("all-registry-legacy-pool").className).not.toContain("hidden"));
		expect(screen.getByTestId("legacy-table").textContent).toContain("BOS_F_LEGACY_99");
		expect(screen.getByText("Shared image-gen settings — applied to every avatar generate below.").textContent).toContain("Shared image-gen settings");
		expect(fetchMock.mock.calls.some(([url]) => String(url).includes("generate-image") || String(url).includes("/flow/generate"))).toBe(false);
	});
});
