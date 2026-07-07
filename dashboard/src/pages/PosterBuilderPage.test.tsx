import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import PosterBuilderPage from "./PosterBuilderPage";
import { fetchPosterReadiness } from "../api/posterReadiness";
import { posterReadinessFixtures } from "../poster/posterReadinessTestFixtures";

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
				product_short_name: "Test",
				source: "MANUAL",
				category: "Oil",
			},
		],
	}),
}));

vi.mock("../api/posterReadiness", () => ({
	fetchPosterReadiness: vi.fn(),
}));

const mockedFetch = vi.mocked(fetchPosterReadiness);

function renderPage(query = "?product_id=p1") {
	return render(
		<MemoryRouter initialEntries={[`/creative/poster-builder${query}`]}>
			<Routes>
				<Route path="/creative/poster-builder" element={<PosterBuilderPage />} />
			</Routes>
		</MemoryRouter>,
	);
}

async function waitForReadinessUi() {
	await waitFor(() => {
		expect(mockedFetch).toHaveBeenCalled();
	});
}

describe("PosterBuilderPage", () => {
	afterEach(() => {
		cleanup();
	});

	beforeEach(() => {
		mockedFetch.mockReset();
	});

	it("renders poster builder heading", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		expect(await screen.findByText("Poster Builder")).toBeInTheDocument();
	});

	it("calls fetchPosterReadiness when product_id query is present", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage("?product_id=p1");
		await waitFor(() => {
			expect(mockedFetch).toHaveBeenCalledWith("p1");
		});
	});

	it("POSTER_READY renders builder shell and disabled generate reason", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.ready());
		renderPage();
		await waitForReadinessUi();
		expect(
			(await screen.findAllByRole("heading", { name: "Poster builder shell" }))
				.length,
		).toBeGreaterThan(0);
		const generateBtn = await screen.findByTestId("generate-poster-button");
		expect(generateBtn).toBeDisabled();
		expect(generateBtn).toHaveAttribute(
			"title",
			"Generator not implemented in this PR",
		);
	});

	it("POSTER_REPAIR_REQUIRED renders repair center and hides builder shell", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.repairRequired());
		renderPage();
		await waitForReadinessUi();
		expect(
			await screen.findByRole("heading", { name: "Repair action center" }),
		).toBeInTheDocument();
		expect(screen.getByText("Run Safe Claim Clearance")).toBeInTheDocument();
		expect(
			screen.queryAllByRole("heading", { name: "Poster builder shell" }),
		).toHaveLength(0);
	});

	it("POSTER_BLOCKED renders human review panel and hides builder shell", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.blocked());
		renderPage();
		await waitForReadinessUi();
		expect(
			await screen.findByRole("heading", { name: "Human review required" }),
		).toBeInTheDocument();
		expect(
			screen.queryAllByRole("heading", { name: "Poster builder shell" }),
		).toHaveLength(0);
	});

	it("POSTER_READY_RESTRICTED renders restricted warning", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.restricted());
		renderPage();
		await waitForReadinessUi();
		expect(
			await screen.findByText(/Restricted safe poster rules apply/i),
		).toBeInTheDocument();
		expect(screen.getByText("Restricted mode")).toBeInTheDocument();
		const restrictedBtn = await screen.findByTestId("generate-poster-button");
		expect(restrictedBtn).toBeDisabled();
		expect(restrictedBtn).toHaveAttribute(
			"title",
			"Restricted generator not implemented in this PR",
		);
	});

	it("POSTER_PREVIEW_ONLY renders preview diagnostic shell", async () => {
		mockedFetch.mockResolvedValue(posterReadinessFixtures.previewOnly());
		renderPage();
		await waitForReadinessUi();
		expect(screen.getByText("Preview / diagnostic")).toBeInTheDocument();
		expect(
			(await screen.findAllByRole("heading", { name: "Poster builder shell" }))
				.length,
		).toBeGreaterThan(0);
		const previewBtn = await screen.findByTestId("generate-poster-button");
		expect(previewBtn).toBeDisabled();
		expect(previewBtn).toHaveAttribute(
			"title",
			"Production generation disabled (preview mode)",
		);
	});
});