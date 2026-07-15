import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CopyIntelligencePage from "./CopyIntelligencePage";
import {
	approveCopyIntelligenceSeed,
	listCopyIntelligenceSeedLedger,
	rejectCopyIntelligenceSeed,
	runUploadedCopyIntelligenceDryRun,
	uploadCopyIntelligenceWorkbook,
	type CopyIntelligenceSeedLedgerRow,
} from "../api/copyIntelligence";

vi.mock("../api/copyIntelligence", () => ({
	uploadCopyIntelligenceWorkbook: vi.fn(),
	runUploadedCopyIntelligenceDryRun: vi.fn(),
	listCopyIntelligenceSeedLedger: vi.fn(),
	approveCopyIntelligenceSeed: vi.fn(),
	rejectCopyIntelligenceSeed: vi.fn(),
}));

const mockedUpload = vi.mocked(uploadCopyIntelligenceWorkbook);
const mockedDryRun = vi.mocked(runUploadedCopyIntelligenceDryRun);
const mockedLedger = vi.mocked(listCopyIntelligenceSeedLedger);
const mockedApprove = vi.mocked(approveCopyIntelligenceSeed);
const mockedReject = vi.mocked(rejectCopyIntelligenceSeed);

function seedRow(overrides: Partial<CopyIntelligenceSeedLedgerRow> = {}): CopyIntelligenceSeedLedgerRow {
	return {
		seed_id: "seed-1", source_row: 12, source_product_name: "Ledger product",
		target_avatar: "Parents", pain_point: "Time", emotion_trigger: "Relief",
		dream_outcome: "Easier routine", key_ingredients_features: "Feature A",
		hook_script: "Hook", cta_script: "CTA", confidence: "HIGH",
		match_method: "TIKTOK_PRODUCT_ID_MATCH", status: "NEEDS_REVIEW",
		source_workbook: "seed.xlsx", source_sheet: "COPYWRITING HUB",
		provenance: { source_row: "12" }, reviewed_by: null, reviewed_at: null, review_note: null,
		...overrides,
	};
}

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
		mockedLedger.mockResolvedValue({ total: 1, items: [seedRow()] });

		render(<CopyIntelligencePage />);
		expect(await screen.findByTestId("copy-intelligence-seed-ledger")).toHaveTextContent("Ledger product");
		expect(screen.getAllByText("Hook")).toHaveLength(2);
		expect(screen.getAllByText("CTA")).toHaveLength(2);
		fireEvent.change(screen.getByLabelText("Ledger confidence"), { target: { value: "HIGH" } });
		await waitFor(() => expect(mockedLedger).toHaveBeenLastCalledWith({ confidence: "HIGH", status: undefined, search: undefined }));
	});

	it("filters the ledger by APPROVED and REJECTED status", async () => {
		mockedLedger.mockResolvedValue({ total: 1, items: [seedRow({ status: "APPROVED" })] });

		render(<CopyIntelligencePage />);
		await screen.findByTestId("copy-intelligence-seed-ledger");

		const statusFilter = screen.getByLabelText("Ledger status");
		expect(screen.getByRole("option", { name: "APPROVED" })).toBeInTheDocument();
		expect(screen.getByRole("option", { name: "REJECTED" })).toBeInTheDocument();

		fireEvent.change(statusFilter, { target: { value: "APPROVED" } });
		await waitFor(() => expect(mockedLedger).toHaveBeenLastCalledWith({ confidence: undefined, status: "APPROVED", search: undefined }));

		fireEvent.change(statusFilter, { target: { value: "REJECTED" } });
		await waitFor(() => expect(mockedLedger).toHaveBeenLastCalledWith({ confidence: undefined, status: "REJECTED", search: undefined }));
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

	it("offers a Review action only for NEEDS_REVIEW rows and a status label for final rows", async () => {
		mockedLedger.mockResolvedValue({
			total: 2,
			items: [
				seedRow({ seed_id: "seed-open", source_product_name: "Open product" }),
				seedRow({ seed_id: "seed-done", source_product_name: "Approved product", status: "APPROVED", reviewed_by: "owner" }),
			],
		});

		render(<CopyIntelligencePage />);
		expect(await screen.findByTestId("review-seed-seed-open")).toBeInTheDocument();
		expect(screen.queryByTestId("review-seed-seed-done")).not.toBeInTheDocument();
		// No bulk approval control exists.
		expect(screen.queryByText(/approve all/i)).not.toBeInTheDocument();
		expect(screen.queryByTestId("bulk-approve")).not.toBeInTheDocument();
	});

	it("opens the modal with full evidence and no MEDIUM warning for HIGH rows", async () => {
		mockedLedger.mockResolvedValue({ total: 1, items: [seedRow()] });
		render(<CopyIntelligencePage />);
		fireEvent.click(await screen.findByTestId("review-seed-seed-1"));

		const modal = await screen.findByTestId("copy-intelligence-review-modal");
		expect(modal).toHaveTextContent("Parents");
		expect(modal).toHaveTextContent("Time");
		expect(modal).toHaveTextContent("Easier routine");
		expect(modal).toHaveTextContent("TIKTOK_PRODUCT_ID_MATCH");
		expect(screen.queryByTestId("medium-confidence-warning")).not.toBeInTheDocument();
	});

	it("shows the stronger MEDIUM warning and approves via the approve endpoint", async () => {
		mockedLedger.mockResolvedValue({ total: 1, items: [seedRow({ confidence: "MEDIUM", match_method: "UNIQUE_NORMALIZED_NAME_TO_SOURCE_REFERENCE" })] });
		mockedApprove.mockResolvedValue({
			seed_id: "seed-1", previous_status: "NEEDS_REVIEW", new_status: "APPROVED",
			confidence: "MEDIUM", reviewed_by: "owner", reviewed_at: "2026-07-15T00:00:00Z", review_note: "verified id",
		});

		render(<CopyIntelligencePage />);
		fireEvent.click(await screen.findByTestId("review-seed-seed-1"));
		expect(await screen.findByTestId("medium-confidence-warning")).toHaveTextContent("normalized product name");

		fireEvent.change(screen.getByLabelText("Reviewer identity"), { target: { value: "owner" } });
		fireEvent.change(screen.getByLabelText("Review note"), { target: { value: "verified id" } });
		fireEvent.change(screen.getByLabelText("Confirmation phrase"), { target: { value: "APPROVE MEDIUM CONFIDENCE COPY INTELLIGENCE" } });
		fireEvent.click(screen.getByTestId("approve-seed"));

		await waitFor(() => expect(mockedApprove).toHaveBeenCalledWith("seed-1", {
			reviewed_by: "owner", review_note: "verified id", confirmation_phrase: "APPROVE MEDIUM CONFIDENCE COPY INTELLIGENCE",
		}));
		// Ledger refreshes and the modal closes.
		await waitFor(() => expect(screen.queryByTestId("copy-intelligence-review-modal")).not.toBeInTheDocument());
		expect(mockedLedger.mock.calls.length).toBeGreaterThanOrEqual(2);
	});

	it("rejects via the reject endpoint", async () => {
		mockedLedger.mockResolvedValue({ total: 1, items: [seedRow()] });
		mockedReject.mockResolvedValue({
			seed_id: "seed-1", previous_status: "NEEDS_REVIEW", new_status: "REJECTED",
			confidence: "HIGH", reviewed_by: "owner", reviewed_at: "2026-07-15T00:00:00Z", review_note: "wrong mapping",
		});

		render(<CopyIntelligencePage />);
		fireEvent.click(await screen.findByTestId("review-seed-seed-1"));
		fireEvent.change(screen.getByLabelText("Reviewer identity"), { target: { value: "owner" } });
		fireEvent.change(screen.getByLabelText("Review note"), { target: { value: "wrong mapping" } });
		fireEvent.change(screen.getByLabelText("Confirmation phrase"), { target: { value: "REJECT COPY INTELLIGENCE" } });
		fireEvent.click(screen.getByTestId("reject-seed"));

		await waitFor(() => expect(mockedReject).toHaveBeenCalledWith("seed-1", {
			reviewed_by: "owner", review_note: "wrong mapping", confirmation_phrase: "REJECT COPY INTELLIGENCE",
		}));
	});

	it("surfaces a fail-closed backend error inside the modal", async () => {
		mockedLedger.mockResolvedValue({ total: 1, items: [seedRow()] });
		mockedApprove.mockRejectedValue(new Error('API 422: {"detail":{"error":"CONFIRMATION_PHRASE_MISMATCH"}}'));

		render(<CopyIntelligencePage />);
		fireEvent.click(await screen.findByTestId("review-seed-seed-1"));
		fireEvent.change(screen.getByLabelText("Reviewer identity"), { target: { value: "owner" } });
		fireEvent.change(screen.getByLabelText("Review note"), { target: { value: "note" } });
		fireEvent.change(screen.getByLabelText("Confirmation phrase"), { target: { value: "wrong" } });
		fireEvent.click(screen.getByTestId("approve-seed"));

		expect(await screen.findByText(/Review error:/)).toHaveTextContent("CONFIRMATION_PHRASE_MISMATCH");
		expect(screen.getByTestId("copy-intelligence-review-modal")).toBeInTheDocument();
	});
});
