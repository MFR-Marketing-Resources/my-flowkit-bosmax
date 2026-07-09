import "@testing-library/jest-dom/vitest";
import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
	within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The page loads assets + mutates review_status through these; the save panel
// fetches IMG lanes on mount and is unrelated to the review flow under test.
vi.mock("../api/creativeAssets", () => ({
	fetchCreativeAssets: vi.fn(),
	updateCreativeAsset: vi.fn(),
	archiveCreativeAsset: vi.fn(),
}));
vi.mock("../components/creative-library/SaveToCreativeLibraryPanel", () => ({
	default: () => null,
}));

import CreativeLibraryPage from "./CreativeLibraryPage";
import { fetchCreativeAssets, updateCreativeAsset } from "../api/creativeAssets";
import type { CreativeAsset } from "../types";

const mockedFetch = vi.mocked(fetchCreativeAssets);
const mockedUpdate = vi.mocked(updateCreativeAsset);

function asset(overrides: Partial<CreativeAsset> = {}): CreativeAsset {
	return {
		asset_id: "ca_x",
		semantic_role: "COMPOSITE_FRAME_REFERENCE",
		display_name: "Asset X",
		description: null,
		source_type: "GENERATED_IMAGE",
		storage_kind: "LOCAL_FILE",
		preview_url: "/preview",
		download_url: "/download",
		media_id: null,
		local_file_path: "C:/tmp/x.png",
		remote_source_url: null,
		product_id: null,
		category: null,
		silo: null,
		product_type: null,
		allowed_modes: ["F2V"],
		engine_slot_eligibility: ["start_frame"],
		visual_dna_summary: null,
		character_dna: null,
		scene_context_dna: null,
		style_mood_dna: null,
		source_prompt_fingerprint: null,
		source_workspace_execution_package_id: null,
		source_prompt_package_snapshot_id: null,
		review_status: "PENDING_REVIEW",
		status: "ACTIVE",
		created_at: "2026-07-09T00:00:00Z",
		updated_at: "2026-07-09T00:00:00Z",
		...overrides,
	};
}

function renderPage() {
	return render(
		<MemoryRouter>
			<CreativeLibraryPage />
		</MemoryRouter>,
	);
}

describe("CreativeLibraryPage review + approval surface", () => {
	beforeEach(() => {
		mockedFetch.mockReset();
		mockedUpdate.mockReset();
		mockedFetch.mockResolvedValue({
			items: [
				asset({
					asset_id: "ca_pending",
					display_name: "Pending Frame",
					review_status: "PENDING_REVIEW",
				}),
				asset({
					asset_id: "ca_approved",
					display_name: "Approved Frame",
					review_status: "APPROVED",
				}),
			],
			total: 2,
		});
	});

	afterEach(() => cleanup());

	it("shows review_status in the table, distinct from ACTIVE/ARCHIVED lifecycle", async () => {
		renderPage();
		await screen.findByText("Pending Frame");
		expect(screen.getByText("Approved Frame")).toBeInTheDocument();

		// Scope to the table so the filter <option> values (PENDING_REVIEW /
		// APPROVED / ACTIVE) don't collide with the row badges under test.
		const table = screen.getByRole("table");
		expect(within(table).getByText("PENDING_REVIEW")).toBeInTheDocument();
		expect(within(table).getByText("APPROVED")).toBeInTheDocument();
		// Both rows are ACTIVE lifecycle — proves ACTIVE != APPROVED (two rows, one
		// APPROVED and one PENDING, but both lifecycle-ACTIVE).
		expect(within(table).getAllByText("ACTIVE")).toHaveLength(2);
	});

	it("approve routes through truth/safety attestation → PATCHes APPROVED + truth PASS", async () => {
		mockedUpdate.mockResolvedValue(
			asset({
				asset_id: "ca_pending",
				display_name: "Pending Frame",
				review_status: "APPROVED",
			}),
		);
		renderPage();
		await screen.findByText("Pending Frame");

		// Only the PENDING row exposes Approve; the APPROVED row does not.
		fireEvent.click(screen.getByRole("button", { name: "Approve" }));

		// The explicit attestation modal opens — approval is NOT a bare one-click.
		await screen.findByText("Approve asset for reuse");
		screen.getAllByRole("checkbox").forEach((box) => fireEvent.click(box));
		fireEvent.click(screen.getByRole("button", { name: /Attest & Approve/i }));

		await waitFor(() =>
			expect(mockedUpdate).toHaveBeenCalledWith("ca_pending", {
				review_status: "APPROVED",
				identity_lock_status: "PASS",
				scale_truth_status: "PASS",
				claim_safety_status: "PASS",
			}),
		);
	});

	it("does not expose an Approve button on already-APPROVED assets", async () => {
		mockedFetch.mockResolvedValue({
			items: [
				asset({
					asset_id: "ca_approved",
					display_name: "Approved Frame",
					review_status: "APPROVED",
				}),
			],
			total: 1,
		});
		renderPage();
		await screen.findByText("Approved Frame");
		expect(
			screen.queryByRole("button", { name: "Approve" }),
		).not.toBeInTheDocument();
		// It can still be rejected (revoked).
		expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
	});
});
