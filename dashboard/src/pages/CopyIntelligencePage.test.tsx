import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CopyIntelligencePage from "./CopyIntelligencePage";
import {
	listCopyIntelligenceSeedLedger,
	runUploadedCopyIntelligenceDryRun,
	uploadCopyIntelligenceWorkbook,
} from "../api/copyIntelligence";

vi.mock("../api/copyIntelligence", () => ({
	uploadCopyIntelligenceWorkbook: vi.fn(),
	runUploadedCopyIntelligenceDryRun: vi.fn(),
	listCopyIntelligenceSeedLedger: vi.fn(),
}));

const mockedUpload = vi.mocked(uploadCopyIntelligenceWorkbook);
const mockedDryRun = vi.mocked(runUploadedCopyIntelligenceDryRun);
const mockedLedger = vi.mocked(listCopyIntelligenceSeedLedger);

describe("CopyIntelligencePage", () => {
	beforeEach(() => mockedLedger.mockResolvedValue({ total: 0, items: [] }));
	afterEach(() => {
		cleanup();
		vi.resetAllMocks();
	});

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

	it("renders seeded review records with confidence and status filters", async () => {
		cleanup();
		mockedLedger.mockResolvedValue({
			total: 1,
			items: [{
				seed_id: "seed-1", source_row: 12, source_product_name: "Ledger product",
				target_avatar: "Parents", pain_point: "Time", emotion_trigger: "Relief",
				dream_outcome: "Easier routine", key_ingredients_features: "Feature A",
				hook_script: "Hook", cta_script: "CTA", confidence: "HIGH",
				match_method: "TIKTOK_PRODUCT_ID_MATCH", status: "NEEDS_REVIEW",
				source_workbook: "seed.xlsx", source_sheet: "COPYWRITING HUB", provenance: { source_row: "12" },
			}],
		});

		render(<CopyIntelligencePage />);
		expect(await screen.findByTestId("copy-intelligence-seed-ledger")).toHaveTextContent("Ledger product");
		expect(screen.getAllByText("Hook")).toHaveLength(2);
		expect(screen.getAllByText("CTA")).toHaveLength(2);
		fireEvent.change(screen.getByLabelText("Ledger confidence"), { target: { value: "HIGH" } });
		await waitFor(() => expect(mockedLedger).toHaveBeenLastCalledWith({ confidence: "HIGH", status: undefined, search: undefined }));
	});

	it("shows a ledger-specific error instead of a false empty state", async () => {
		mockedLedger.mockRejectedValue(new Error('API 404: {"detail":"Not Found"}'));

		render(<CopyIntelligencePage />);

		expect(await screen.findByText(/Unable to load ledger:/)).toBeInTheDocument();
		expect(screen.queryByText("0 persisted review records")).not.toBeInTheDocument();
	});

	it("keeps an upload and dry-run error out of the ledger section", async () => {
		mockedUpload.mockRejectedValue(new Error("Upload failed"));
		render(<CopyIntelligencePage />);

		const workbook = new File(["workbook"], "Kalodata & Fastmoss 600.xlsx", {
			type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		});
		fireEvent.change(screen.getByLabelText("Full workbook (.xlsx)"), {
			target: { files: [workbook] },
		});
		fireEvent.click(screen.getByTestId("upload-copy-intelligence-workbook"));

		expect(await screen.findByText("Upload and dry-run error: Upload failed")).toBeInTheDocument();
		expect(screen.queryByText(/Unable to load ledger:/)).not.toBeInTheDocument();
	});
});
