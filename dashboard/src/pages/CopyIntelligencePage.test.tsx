import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CopyIntelligencePage from "./CopyIntelligencePage";
import {
	runUploadedCopyIntelligenceDryRun,
	uploadCopyIntelligenceWorkbook,
} from "../api/copyIntelligence";

vi.mock("../api/copyIntelligence", () => ({
	uploadCopyIntelligenceWorkbook: vi.fn(),
	runUploadedCopyIntelligenceDryRun: vi.fn(),
}));

const mockedUpload = vi.mocked(uploadCopyIntelligenceWorkbook);
const mockedDryRun = vi.mocked(runUploadedCopyIntelligenceDryRun);

describe("CopyIntelligencePage", () => {
	afterEach(() => vi.resetAllMocks());

	it("uploads the full workbook before an explicit review-only dry-run", async () => {
		mockedUpload.mockResolvedValue({
			source_id: "a".repeat(64),
			original_filename: "Kalodata & Fastmoss 600.xlsx",
			fingerprint: "a".repeat(64),
			sheet_names: ["MERGED PRODUCTS", "COPYWRITING HUB"],
			required_sheets: ["COPYWRITING HUB", "MERGED PRODUCTS"],
		});
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
		expect(screen.getByText("Upload the full Kalodata & Fastmoss workbook")).toBeInTheDocument();

		const workbook = new File(["workbook"], "Kalodata & Fastmoss 600.xlsx", {
			type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		});
		fireEvent.change(screen.getByLabelText("Full workbook (.xlsx)"), {
			target: { files: [workbook] },
		});
		fireEvent.click(screen.getByTestId("upload-copy-intelligence-workbook"));

		await waitFor(() => expect(mockedUpload).toHaveBeenCalledWith(workbook));
		await waitFor(() => expect(mockedDryRun).toHaveBeenCalledWith("a".repeat(64)));
		expect(screen.queryByLabelText("COPYWRITING HUB workbook path")).not.toBeInTheDocument();
		expect(screen.getByText(/Stored source: Kalodata & Fastmoss 600\.xlsx/)).toBeInTheDocument();
		expect(await screen.findByTestId("copy-intelligence-summary")).toHaveTextContent("High confidence");
		expect(screen.getByText("7 safe review records")).toBeInTheDocument();
		expect(screen.getByText("3 quarantined or low-confidence records")).toBeInTheDocument();
	});
});
