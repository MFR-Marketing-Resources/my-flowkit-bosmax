import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CopyIntelligencePage from "./CopyIntelligencePage";
import { runCopyIntelligenceDryRun } from "../api/copyIntelligence";

vi.mock("../api/copyIntelligence", () => ({
	runCopyIntelligenceDryRun: vi.fn(),
}));

const mockedDryRun = vi.mocked(runCopyIntelligenceDryRun);

describe("CopyIntelligencePage", () => {
	afterEach(() => vi.resetAllMocks());

	it("runs only an explicit review-only dry-run and presents safe and quarantined counts", async () => {
		mockedDryRun.mockResolvedValue({
			source_workbook: "authorized.xlsx",
			total_source_rows: 10,
			usable_rows: 10,
			matched_high_confidence: 4,
			matched_medium_confidence: 3,
			low_confidence_quarantined: 3,
			unmatched: 0,
			duplicates: 1,
			conflicts: 0,
			blank_no_copy_rows: 0,
			suspicious_cross_product_copy: 0,
			records: [],
			examples: { quarantined: [] },
		});

		render(<CopyIntelligencePage />);
		expect(screen.getByTestId("copy-intelligence-page")).toHaveTextContent("review-only");
		expect(screen.queryByTestId("seed-copy-intelligence")).not.toBeInTheDocument();

		fireEvent.change(screen.getByLabelText("COPYWRITING HUB workbook path"), {
			target: { value: "C:\\authorized.xlsx" },
		});
		fireEvent.click(screen.getByTestId("run-copy-intelligence-dry-run"));

		await waitFor(() => expect(mockedDryRun).toHaveBeenCalledWith("C:\\authorized.xlsx"));
		expect(await screen.findByTestId("copy-intelligence-summary")).toHaveTextContent("High confidence");
		expect(screen.getByText("7 safe review records")).toBeInTheDocument();
		expect(screen.getByText("3 quarantined or low-confidence records")).toBeInTheDocument();
	});
});
