import "@testing-library/jest-dom/vitest";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import CopySetRegistryPage from "./CopySetRegistryPage";

vi.mock("../components/workspace/SearchableProductSelect", () => ({
	default: () => <div data-testid="product-picker">Product picker</div>,
}));

vi.mock("../api/products", () => ({
	fetchProductCatalog: vi.fn().mockResolvedValue({
		items: [
			{
				id: "p1",
				raw_product_title: "Test Product",
				product_display_name: "Test Product",
				source: "MANUAL",
				category: "Oil",
			},
		],
	}),
}));

vi.mock("../api/copySets", () => ({
	listCopySetsForProduct: vi.fn(),
	generateCopySetBatch: vi.fn(),
	generateCopySet: vi.fn(),
	approveCopySet: vi.fn(),
	rejectCopySet: vi.fn(),
	patchCopySet: vi.fn(),
	deleteCopySet: vi.fn(),
	fetchCopyGrounding: vi.fn(),
}));

import {
	approveCopySet,
	deleteCopySet,
	fetchCopyGrounding,
	generateCopySetBatch,
	listCopySetsForProduct,
	rejectCopySet,
} from "../api/copySets";

const mockedList = vi.mocked(listCopySetsForProduct);
const mockedBatch = vi.mocked(generateCopySetBatch);
const mockedApprove = vi.mocked(approveCopySet);
const mockedReject = vi.mocked(rejectCopySet);
const mockedDelete = vi.mocked(deleteCopySet);
const mockedGrounding = vi.mocked(fetchCopyGrounding);

const sampleGrounding = {
	product_id: "p1",
	grounded: true,
	source: "FRAMEWORK_FAMILY",
	family: "MALE_HEALTH_SENSITIVE",
	is_stealth: true,
	effective_route: "STEALTH",
	copy_formula: "PAS / PESTA",
	angle_strategies: ["stealth_masculinity", "wrapped_readiness", "maruah_and_ego"],
	buyer_persona: {
		audience: "Lelaki dewasa yang jaga maruah",
		desires: ["yakin semula"],
		fears: ["malu"],
		pains: ["keyakinan menurun"],
		objections: ["selamat ke?"],
		triggers: ["ego", "maruah"],
		tone: "wrapped, ego-aware",
		pronoun: "aku / kau",
	},
	product_knowledge: {
		description: "",
		benefits: [],
		usps: [],
		ingredients: "",
		target_customer: "Lelaki dewasa yang jaga maruah",
	},
	claim_guardrails: {
		claim_gate: "CLAIM_REVIEW_REQUIRED",
		claim_risk_level: "HIGH",
		allowed_claims: [],
		blocked_claims: [],
		banned_terms: ["zakar", "cure"],
	},
	missing: ["approved product-intelligence snapshot"],
};

const sampleSet = {
	copy_set_id: "cs1",
	product_id: "p1",
	angle: "Trust",
	hook: "Safe hook",
	subhook: "Sub",
	usp_set: ["a", "b", "c"],
	cta: "Shop",
	platform: "TIKTOK",
	language: "BM_MS",
	route_type: "DIRECT",
	formula_family: "HSO",
	status: "COPY_REVIEW_REQUIRED" as const,
	dedupe_key: "k",
	source: "AI_COPY_ASSIST",
	provenance: {},
	claim_review: {},
	reviewer_note: null,
	approved_at: null,
	approved_by: null,
	created_at: "2026-07-07T00:00:00Z",
	updated_at: "2026-07-07T00:00:00Z",
};

function renderPage(query = "?product_id=p1") {
	return render(
		<MemoryRouter initialEntries={[`/creative/copy-registry${query}`]}>
			<Routes>
				<Route path="/creative/copy-registry" element={<CopySetRegistryPage />} />
			</Routes>
		</MemoryRouter>,
	);
}

describe("CopySetRegistryPage", () => {
	afterEach(() => cleanup());

	beforeEach(() => {
		mockedList.mockReset();
		mockedBatch.mockReset();
		mockedApprove.mockReset();
		mockedReject.mockReset();
		mockedDelete.mockReset();
		mockedGrounding.mockReset();
		mockedGrounding.mockResolvedValue(sampleGrounding);
		mockedList.mockResolvedValue({ product_id: "p1", items: [sampleSet] });
		mockedBatch.mockResolvedValue({
			batch_id: "b1",
			product_id: "p1",
			requested_count: 5,
			created_count: 5,
			deduped_count: 0,
			rejected_count: 0,
			provider: { lane: "text_assist", configured: true, provider_id: "deepseek" },
			candidates: [],
			warnings: [],
			dry_run: false,
		});
	});

	it("renders the registry and loads sets for the product", async () => {
		renderPage();
		expect(await screen.findByTestId("copy-set-registry-page")).toBeInTheDocument();
		await waitFor(() => expect(mockedList).toHaveBeenCalledWith("p1"));
		expect(await screen.findByTestId("generate-copy-sets")).toBeInTheDocument();
		expect(await screen.findByText("Safe hook")).toBeInTheDocument();
	});

	it("shows the copy grounding banner with avatar + angle strategies", async () => {
		renderPage();
		await waitFor(() => expect(mockedGrounding).toHaveBeenCalledWith("p1"));
		const banner = await screen.findByTestId("copy-grounding-banner");
		expect(banner).toBeInTheDocument();
		expect(banner).toHaveTextContent("MALE_HEALTH_SENSITIVE");
		expect(banner).toHaveTextContent("stealth_masculinity");
		expect(banner).toHaveTextContent(/Lelaki dewasa/);
		// framework tier → prompts the operator to author a snapshot
		expect(banner).toHaveTextContent(/Product Knowledge snapshot/i);
	});

	it("does NOT auto-generate on product select (AI is click-only)", async () => {
		renderPage();
		await waitFor(() => expect(mockedList).toHaveBeenCalled());
		await new Promise((r) => setTimeout(r, 30));
		expect(mockedBatch).not.toHaveBeenCalled();
	});

	it("Generate calls generateCopySetBatch with requested_count 5", async () => {
		renderPage();
		const btn = await screen.findByTestId("generate-copy-sets");
		btn.click();
		await waitFor(() =>
			expect(mockedBatch).toHaveBeenCalledWith(
				expect.objectContaining({ product_id: "p1", requested_count: 5 }),
			),
		);
	});

	it("Approve calls approveCopySet", async () => {
		mockedApprove.mockResolvedValue({ ...sampleSet, status: "COPY_APPROVED" });
		renderPage();
		const btn = await screen.findByTestId("approve-cs1");
		btn.click();
		await waitFor(() => expect(mockedApprove).toHaveBeenCalledWith("cs1", { approved_by: "operator" }));
	});

	it("Reject prompts for a note and calls rejectCopySet", async () => {
		vi.spyOn(window, "prompt").mockReturnValue("not suitable");
		mockedReject.mockResolvedValue({ ...sampleSet, status: "COPY_REJECTED" });
		renderPage();
		const btn = await screen.findByTestId("reject-cs1");
		btn.click();
		await waitFor(() => expect(mockedReject).toHaveBeenCalledWith("cs1", "not suitable"));
	});

	it("Delete requires the confirm phrase before deleteCopySet fires", async () => {
		mockedDelete.mockResolvedValue({ deleted: true, copy_set_id: "cs1" });
		renderPage();
		const del = await screen.findByTestId("delete-cs1");
		del.click();
		// Modal open; deletion must not fire until the phrase is typed.
		const confirmBtn = await screen.findByText("Delete permanently");
		confirmBtn.click();
		expect(mockedDelete).not.toHaveBeenCalled();
		const input = screen.getByPlaceholderText("DELETE");
		fireEvent.change(input, { target: { value: "DELETE" } });
		screen.getByText("Delete permanently").click();
		await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith("cs1"));
	});

	it("surfaces a friendly error when the AI lane is not configured; rows stay", async () => {
		mockedBatch.mockRejectedValue(
			new Error("API 409: AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED"),
		);
		renderPage();
		const btn = await screen.findByTestId("generate-copy-sets");
		btn.click();
		expect(await screen.findByTestId("copy-registry-error")).toHaveTextContent(
			/belum dikonfigur/i,
		);
		expect(screen.getByText("Safe hook")).toBeInTheDocument();
	});
});
