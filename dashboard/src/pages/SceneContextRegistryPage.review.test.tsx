import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SceneContextRegistryPage from "./SceneContextRegistryPage";

const mocks = vi.hoisted(() => ({
	fetchProductCatalog: vi.fn(),
	getScenePromotionProductReview: vi.fn(),
	submitScenePromotionReview: vi.fn(),
	submitScenePromotionBulkReview: vi.fn(),
	getRegistryCoverage: vi.fn(),
	getRegistryReconciliation: vi.fn(),
	getRegistryCleanupPlan: vi.fn(),
}));

vi.mock("../api/imageGenSettings", () => ({
	useImageGenSettings: () => ({ aspect_options: ["9:16"], models: [{ label: "Nano Banana 2" }] }),
}));
vi.mock("../api/products", () => ({ fetchProductCatalog: mocks.fetchProductCatalog }));
vi.mock("../api/creativeIntelligence", () => ({
	getScenePromotionProductReview: mocks.getScenePromotionProductReview,
	submitScenePromotionReview: mocks.submitScenePromotionReview,
	submitScenePromotionBulkReview: mocks.submitScenePromotionBulkReview,
	getRegistryCoverage: mocks.getRegistryCoverage,
	getRegistryReconciliation: mocks.getRegistryReconciliation,
	getRegistryCleanupPlan: mocks.getRegistryCleanupPlan,
}));
vi.mock("../components/workspace/SearchableProductSelect", () => ({
	default: ({ selectedProduct, onSelect }: { selectedProduct: { id: string; product_display_name: string } | null; onSelect: (product: { id: string; product_display_name: string; raw_product_title: string }) => void }) => (
		<div data-testid="product-selector">
			<button type="button" onClick={() => onSelect({ id: "p1", product_display_name: "Serum", raw_product_title: "Serum" })}>Select Serum</button>
			<button type="button" onClick={() => onSelect({ id: "p2", product_display_name: "Lotion", raw_product_title: "Lotion" })}>Select Lotion</button>
			<span>{selectedProduct?.product_display_name || "No product selected"}</span>
		</div>
	),
}));

const product = { id: "p1", source: "MANUAL", raw_product_title: "Serum", product_display_name: "Serum", product_short_name: "Serum" };
const secondProduct = { id: "p2", source: "MANUAL", raw_product_title: "Lotion", product_display_name: "Lotion", product_short_name: "Lotion" };
const candidate = {
	source_template_id: "SCN-BEAUTY-01", source_category: "Beauty", setting: "Vanity alcove", candidate_fingerprint: "fingerprint-current",
	proposed_scene_code: "SCN_BEAUTY_01", proposed_scene_name: "Beauty vanity alcove", background_prompt: "Background: vanity alcove",
	prompt_v1: "Empty background only.", safety_block: "EMPTY_BACKGROUND_ONLY", usage_tags: "cluster:beauty", decision: "PENDING",
	reviewer_note: null, reviewed_at: null, stale_review_required: false, activation_status: "NOT_ACTIVATED",
};

function review(overrides: Record<string, unknown> = {}) {
	return {
		dry_run: true, activation_allowed: false, registry_mutations: 0, product_id: "p1", product_name: "Serum", category: "Beauty & Personal Care",
		cluster: "Beauty", cluster_source: "EXACT", review_required: false, product_suitability_template_count: 1, candidate_count: 1, quarantine_count: 0,
		decision_counts: { PENDING: 1, APPROVED_FOR_FUTURE_PROMOTION: 0, REJECTED: 0, STALE_REVIEW_REQUIRED: 0 }, candidates: [candidate], quarantine: [], source: "TEST", ...overrides,
	};
}

function deferred<T>() {
	let resolve: (value: T) => void = () => {};
	const promise = new Promise<T>((resolvePromise) => {
		resolve = resolvePromise;
	});
	return { promise, resolve };
}

describe("SceneContextRegistryPage product-first owner review", () => {
	afterEach(() => {
		cleanup();
		vi.unstubAllGlobals();
	});

	beforeEach(() => {
		vi.clearAllMocks();
		mocks.fetchProductCatalog.mockResolvedValue({ items: [product, secondProduct] });
		mocks.getScenePromotionProductReview.mockResolvedValue(review());
		mocks.submitScenePromotionReview.mockResolvedValue(review());
		mocks.submitScenePromotionBulkReview.mockResolvedValue(review());
		mocks.getRegistryCoverage.mockResolvedValue(null);
		mocks.getRegistryReconciliation.mockResolvedValue(null);
		mocks.getRegistryCleanupPlan.mockResolvedValue(null);
		vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ scenes: [], count: 0, generated_count: 0, bridge_active: false }) })));
	});

	it("defaults to Product Scene Review and loads the selected product review without admin requests", async () => {
		render(<SceneContextRegistryPage />);
		expect(screen.getByRole("tab", { name: "PRODUCT SCENE REVIEW" }).getAttribute("aria-selected")).toBe("true");
		expect(screen.getByTestId("product-selector")).toBeTruthy();
		expect(screen.queryByText("Create Scene")).toBeNull();
		fireEvent.click(screen.getByRole("button", { name: "Select Serum" }));
		await screen.findByText("Beauty vanity alcove");
		expect(mocks.getScenePromotionProductReview).toHaveBeenCalledWith("p1");
		expect(globalThis.fetch).not.toHaveBeenCalled();
	});

	it("fails closed for an unknown category without review actions", async () => {
		mocks.getScenePromotionProductReview.mockResolvedValue(review({ cluster: null, cluster_source: "REVIEW_REQUIRED_UNKNOWN_CATEGORY", review_required: true, candidate_count: 0, candidates: [], message: "Correct category first." }));
		render(<SceneContextRegistryPage />);
		fireEvent.click(screen.getByRole("button", { name: "Select Serum" }));
		await screen.findByText("PRODUCT CATEGORY REVIEW REQUIRED.");
		expect(screen.queryByRole("button", { name: "Approve for future promotion" })).toBeNull();
	});

	it("approves using the current fingerprint and labels the result as non-active", async () => {
		mocks.getScenePromotionProductReview.mockResolvedValueOnce(review()).mockResolvedValueOnce(review({ candidates: [{ ...candidate, decision: "APPROVED_FOR_FUTURE_PROMOTION" }], decision_counts: { PENDING: 0, APPROVED_FOR_FUTURE_PROMOTION: 1, REJECTED: 0, STALE_REVIEW_REQUIRED: 0 } }));
		render(<SceneContextRegistryPage />);
		fireEvent.click(screen.getByRole("button", { name: "Select Serum" }));
		await screen.findByText("Beauty vanity alcove");
		fireEvent.click(screen.getByRole("button", { name: "Approve for future promotion" }));
		await waitFor(() => expect(mocks.submitScenePromotionReview).toHaveBeenCalledWith(expect.objectContaining({ candidate_fingerprint: "fingerprint-current", decision: "APPROVED_FOR_FUTURE_PROMOTION" })));
		await screen.findByText("APPROVED FOR FUTURE PROMOTION · NOT ACTIVE IN REGISTRY");
	});

	it("submits reject and reset-to-pending with the current fingerprint", async () => {
		render(<SceneContextRegistryPage />);
		fireEvent.click(screen.getByRole("button", { name: "Select Serum" }));
		await screen.findByText("Beauty vanity alcove");
		fireEvent.click(screen.getByRole("button", { name: "Reject" }));
		await waitFor(() => expect(mocks.submitScenePromotionReview).toHaveBeenLastCalledWith(expect.objectContaining({ candidate_fingerprint: "fingerprint-current", decision: "REJECTED" })));
		fireEvent.click(screen.getByRole("button", { name: "Reset to pending" }));
		await waitFor(() => expect(mocks.submitScenePromotionReview).toHaveBeenLastCalledWith(expect.objectContaining({ candidate_fingerprint: "fingerprint-current", decision: "PENDING" })));
	});

	it("blocks stale candidates until refresh", async () => {
		mocks.getScenePromotionProductReview.mockResolvedValue(review({ candidates: [{ ...candidate, stale_review_required: true, decision: "STALE_REVIEW_REQUIRED" }] }));
		render(<SceneContextRegistryPage />);
		fireEvent.click(screen.getByRole("button", { name: "Select Serum" }));
		await screen.findByText(/Candidate content changed after the prior decision/);
		expect(screen.queryByRole("button", { name: "Approve for future promotion" })).toBeNull();
		fireEvent.click(screen.getByRole("button", { name: "Refresh candidate" }));
		expect(mocks.submitScenePromotionReview).not.toHaveBeenCalled();
	});

	it("submits explicitly selected candidates only in a bulk action", async () => {
		const second = { ...candidate, source_template_id: "SCN-BEAUTY-02", proposed_scene_code: "SCN_BEAUTY_02", proposed_scene_name: "Beauty shelf", candidate_fingerprint: "fingerprint-second" };
		mocks.getScenePromotionProductReview.mockResolvedValue(review({ candidate_count: 2, candidates: [candidate, second] }));
		render(<SceneContextRegistryPage />);
		fireEvent.click(screen.getByRole("button", { name: "Select Serum" }));
		await screen.findByText("Beauty shelf");
		fireEvent.click(screen.getByRole("checkbox", { name: "Select SCN-BEAUTY-02" }));
		fireEvent.click(screen.getByRole("button", { name: "Approve selected" }));
		await waitFor(() => expect(mocks.submitScenePromotionBulkReview).toHaveBeenCalledWith(expect.objectContaining({ reviewed_via_product_id: "p1", items: [expect.objectContaining({ source_template_id: "SCN-BEAUTY-02", candidate_fingerprint: "fingerprint-second" })] })));
	});

	it("keeps quarantine read-only and gates legacy controls behind Active Registry / Admin", async () => {
		mocks.getScenePromotionProductReview.mockResolvedValue(review({ quarantine_count: 1, quarantine: [{ source_template_id: "SCN-QUARANTINE", source_category: "Beauty", setting: "Unsafe product", reason: "PRODUCT_INSTRUCTION" }] }));
		render(<SceneContextRegistryPage />);
		fireEvent.click(screen.getByRole("button", { name: "Select Serum" }));
		await screen.findByText("Beauty vanity alcove");
		fireEvent.click(screen.getByRole("tab", { name: "PROMOTION QUARANTINE" }));
		await screen.findByTestId("promotion-quarantine");
		expect(screen.getByText(/Quarantine reason:/)).toBeTruthy();
		expect(screen.queryByRole("button", { name: "Approve for future promotion" })).toBeNull();
		fireEvent.click(screen.getByRole("tab", { name: "ACTIVE REGISTRY / ADMIN" }));
		expect(screen.getByText("Create Scene")).toBeTruthy();
	});

	it("surfaces API errors while preserving the selected product and never calls generation from review actions", async () => {
		mocks.submitScenePromotionReview.mockRejectedValue(new Error("STALE_CANDIDATE_FINGERPRINT"));
		render(<SceneContextRegistryPage />);
		fireEvent.click(screen.getByRole("button", { name: "Select Serum" }));
		await screen.findByText("Beauty vanity alcove");
		fireEvent.click(screen.getByRole("button", { name: "Reject" }));
		await screen.findByRole("alert");
		expect(screen.getAllByText("Serum").length).toBeGreaterThan(0);
		expect(globalThis.fetch).not.toHaveBeenCalled();
	});

	it("keeps the latest product review when an older request resolves after it", async () => {
		const firstReview = deferred<ReturnType<typeof review>>();
		const secondReview = deferred<ReturnType<typeof review>>();
		mocks.getScenePromotionProductReview
			.mockReturnValueOnce(firstReview.promise)
			.mockReturnValueOnce(secondReview.promise);
		render(<SceneContextRegistryPage />);
		fireEvent.click(screen.getByRole("button", { name: "Select Serum" }));
		fireEvent.click(screen.getByRole("button", { name: "Select Lotion" }));
		secondReview.resolve(review({ product_id: "p2", product_name: "Lotion", candidates: [{ ...candidate, proposed_scene_name: "Lotion shelf" }] }));
		await screen.findByText("Lotion shelf");
		firstReview.resolve(review({ candidates: [{ ...candidate, proposed_scene_name: "Serum shelf" }] }));
		await waitFor(() => expect(screen.queryByText("Serum shelf")).toBeNull());
		expect(screen.getByText("Lotion shelf")).toBeTruthy();
	});

	it("clears the reviewer note and selected candidates when the product changes", async () => {
		render(<SceneContextRegistryPage />);
		fireEvent.click(screen.getByRole("button", { name: "Select Serum" }));
		await screen.findByText("Beauty vanity alcove");
		fireEvent.click(screen.getByRole("checkbox", { name: "Select SCN-BEAUTY-01" }));
		fireEvent.change(screen.getByRole("textbox", { name: /Reviewer note/ }), { target: { value: "Keep this note only for Serum" } });
		fireEvent.click(screen.getByRole("button", { name: "Select Lotion" }));
		await waitFor(() => expect((screen.getByRole("textbox", { name: /Reviewer note/ }) as HTMLTextAreaElement).value).toBe(""));
		expect((screen.getByRole("checkbox", { name: "Select SCN-BEAUTY-01" }) as HTMLInputElement).checked).toBe(false);
	});
});
