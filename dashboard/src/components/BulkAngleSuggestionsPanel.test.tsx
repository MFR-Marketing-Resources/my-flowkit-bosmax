import "@testing-library/jest-dom/vitest";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import BulkAngleSuggestionsPanel from "./BulkAngleSuggestionsPanel";

vi.mock("../api/copyComponents", () => ({
	fetchEligibleProducts: vi.fn(),
	bulkSuggestAngles: vi.fn(),
	addAngles: vi.fn(),
}));

import {
	addAngles,
	bulkSuggestAngles,
	fetchEligibleProducts,
} from "../api/copyComponents";

const mockedEligible = vi.mocked(fetchEligibleProducts);
const mockedBulk = vi.mocked(bulkSuggestAngles);
const mockedAdd = vi.mocked(addAngles);

function primeEligible() {
	mockedEligible.mockResolvedValue({
		items: [
			{ product_id: "p1", name: "Produk Satu", angle_count: 1, room: 11 },
			{ product_id: "p2", name: "Produk Dua", angle_count: 2, room: 10 },
		],
		count: 2,
	} as never);
}

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

describe("BulkAngleSuggestionsPanel", () => {
	it("loads and shows the eligible count", async () => {
		primeEligible();
		render(<BulkAngleSuggestionsPanel />);
		expect(await screen.findByTestId("bulk-remaining")).toHaveTextContent(
			"2 not yet suggested",
		);
	});

	it("runs a batch after confirming and shows the review list", async () => {
		primeEligible();
		mockedBulk.mockResolvedValue({
			results: [
				{ product_id: "p1", ok: true, suggestions: ["lampin bocor", "kembung perut"] },
				{ product_id: "p2", ok: true, suggestions: ["sengal badan"] },
			],
			products: 2,
			ok_products: 2,
			total_suggestions: 3,
		});
		render(<BulkAngleSuggestionsPanel />);
		fireEvent.click(await screen.findByTestId("bulk-run"));
		// Confirm modal — spends nothing until confirmed.
		expect(mockedBulk).not.toHaveBeenCalled();
		fireEvent.click(screen.getByRole("button", { name: /Yes, suggest 2/ }));
		await waitFor(() => expect(mockedBulk).toHaveBeenCalled());
		const list = await screen.findByTestId("bulk-review-list");
		expect(list).toHaveTextContent("Produk Satu");
		expect(list).toHaveTextContent("lampin bocor");
	});

	it("accepts selected suggestions via addAngles (free commit)", async () => {
		primeEligible();
		mockedBulk.mockResolvedValue({
			results: [{ product_id: "p1", ok: true, suggestions: ["lampin bocor"] }],
			products: 1,
			ok_products: 1,
			total_suggestions: 1,
		});
		mockedAdd.mockResolvedValue({ ok: true, added: 1, angle_count: 2 });
		render(<BulkAngleSuggestionsPanel />);
		fireEvent.click(await screen.findByTestId("bulk-run"));
		fireEvent.click(screen.getByRole("button", { name: /Yes, suggest/ }));
		await screen.findByTestId("bulk-review-list");
		fireEvent.click(screen.getByTestId("bulk-accept-all"));
		await waitFor(() =>
			expect(mockedAdd).toHaveBeenCalledWith(
				expect.objectContaining({ product_id: "p1", pains: ["lampin bocor"] }),
			),
		);
		expect(await screen.findByTestId("bulk-success")).toHaveTextContent(
			/added to 1 product/i,
		);
	});

	it("surfaces a not-configured provider without throwing", async () => {
		primeEligible();
		mockedBulk.mockRejectedValue(
			new Error("409 AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED"),
		);
		render(<BulkAngleSuggestionsPanel />);
		fireEvent.click(await screen.findByTestId("bulk-run"));
		fireEvent.click(screen.getByRole("button", { name: /Yes, suggest/ }));
		expect(await screen.findByTestId("bulk-error")).toHaveTextContent(
			/not configured/i,
		);
	});
});
