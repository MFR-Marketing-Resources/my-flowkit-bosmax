import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CopywritingLandbankDatabasePage from "./CopywritingLandbankDatabasePage";
import type {
	MaintenanceDetail,
	MaintenanceListResponse,
	MaintenanceRecord,
	MaintenanceStage,
} from "../api/copywritingLandbankMaintenance";

vi.mock("../api/copywritingLandbankMaintenance", () => ({
	deleteCopywritingLandbankDraft: vi.fn(),
	fetchCopywritingLandbankMaintenance: vi.fn(),
	fetchCopywritingLandbankMaintenanceDetail: vi.fn(),
	saveCopywritingLandbankRevision: vi.fn(),
}));

vi.mock("../api/storyboardLandbankV3Round2", () => ({
	reviewV3Entity: vi.fn(),
}));

import {
	fetchCopywritingLandbankMaintenance,
	fetchCopywritingLandbankMaintenanceDetail,
	saveCopywritingLandbankRevision,
} from "../api/copywritingLandbankMaintenance";
import { reviewV3Entity } from "../api/storyboardLandbankV3Round2";

const mockedList = vi.mocked(fetchCopywritingLandbankMaintenance);
const mockedDetail = vi.mocked(fetchCopywritingLandbankMaintenanceDetail);
const mockedSave = vi.mocked(saveCopywritingLandbankRevision);
const mockedReview = vi.mocked(reviewV3Entity);

const stages: MaintenanceStage[] = [
	{ stage_key: "hook", order: 0, formula_stage_key: "problem", semantic_class: "HOOK", authored_text: "Exact Hook" },
	{ stage_key: "body", order: 1, formula_stage_key: "agitate", semantic_class: "BODY_CORE", authored_text: "Exact Body" },
	{ stage_key: "cta", order: 2, formula_stage_key: "action", semantic_class: "CTA", authored_text: "Exact CTA" },
];

function record(overrides: Partial<MaintenanceRecord> = {}): MaintenanceRecord {
	return {
		product: { id: "product-1", name: "Product One" },
		master_id: "master-1",
		revision: 2,
		status: "VALIDATED",
		master: { master_id: "master-1", revision: 2, product_id: "product-1", stages },
		formula: { formula_id: "PAS", formula_version: "pas.v1" },
		angle: { entity_id: "angle-1", revision: 1 },
		storyline_family: { entity_id: "family-1", revision: 1 },
		stages,
		previews: { HOOK: "Exact Hook", BODY_CORE: "Exact Body", CTA: "Exact CTA" },
		quality: { hard_pass: true, formula_valid: true, evidence_valid: true, bridge_valid: true, claim_safety_valid: true, truth_current: true, wps_valid: true, issue_codes: [], novelty_signal: "NOVEL", novelty_score: 1, quality_dimensions: {}, quality_score: 0.88 },
		projection_count: 0,
		projections: [],
		projection_status: "NOT_MATERIALIZED",
		v2_materialization: "NOT_MATERIALIZED",
		production_ready: false,
		stale: false,
		stale_reasons: [],
		approval_receipt: null,
		created_at: "2026-08-21T00:00:00Z",
		created_by: "fixture",
		actions: { can_edit: true, edit_mode: "EDIT_DRAFT_REVISION", can_reject: true, can_delete: false, delete_reason: "Only an unreferenced DRAFT can be deleted.", delete_blockers: [] },
		provider_calls: 0,
		mutations: 0,
		...overrides,
	};
}

function listResponse(items: MaintenanceRecord[] = [record()]): MaintenanceListResponse {
	return {
		source: "V3_COPY_REGISTER_MAINTENANCE",
		items,
		total: items.length,
		limit: 25,
		offset: 0,
		has_more: false,
		summary: { total_products: 2, products_with_copy: 1, products_without_copy: 1, total_copy_masters: items.length, total_master_revisions: items.length, draft: 0, review_required: 0, validated: items.length, approved: 0, production_ready: 0, stale: 0 },
		count_basis: {},
		product_coverage: [{ product_id: "product-1", product_name: "Product One", copy_sets: 1, angles: 1, hooks: 1, body_core: 1, cta: 1, approved: 0, production_ready: 0, stale: 0 }, { product_id: "product-2", product_name: "Product Two", copy_sets: 0, angles: 0, hooks: 0, body_core: 0, cta: 0, approved: 0, production_ready: 0, stale: 0 }],
		filter_options: { formulas: ["PAS"], angles: ["angle-1"] },
		provider_calls: 0,
		mutations: 0,
	};
}

function detailResponse(overrides: Partial<MaintenanceDetail> = {}): MaintenanceDetail {
	return {
		...record(),
		exact_revision: { master_id: "master-1", revision: 2 },
		review_events: [],
		integrity: { exact_content_digest: "a".repeat(64) },
		maintenance: { editable_fields: ["stages[].authored_text"], immutable_fields: ["formula"], approved_edit_behavior: "new DRAFT" },
		...overrides,
	};
}

function renderAt(path = "/reporting/copywriting-landbank") {
	return render(<MemoryRouter initialEntries={[path]}><CopywritingLandbankDatabasePage /></MemoryRouter>);
}

describe("Copywriting Landbank Reporting maintenance console", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockedList.mockResolvedValue(listResponse());
		mockedDetail.mockResolvedValue(detailResponse());
		mockedSave.mockResolvedValue({ master: detailResponse().master, source_revision: 2, new_revision: 3, automatic_approval: false, approval_carried_forward: false, production_authority_carried_forward: false, projection_refresh_required: true, provider_calls: 0, credit_spend: 0 });
		mockedReview.mockResolvedValue({ master_id: "master-1", revision: 3 });
	});

	afterEach(() => cleanup());

	it("renders authoritative overview, coverage, and exact server-backed records", async () => {
		renderAt();
		expect(await screen.findByTestId("copywriting-landbank-maintenance-page")).toBeInTheDocument();
		expect(screen.getByText("Products with copy")).toBeInTheDocument();
		expect(screen.getAllByText("Product Two").length).toBeGreaterThan(0);
		expect(screen.getByTestId("maintenance-record-table")).toHaveTextContent("master-1");
		fireEvent.change(screen.getByTestId("maintenance-search"), { target: { value: "master-1" } });
		await waitFor(() => expect(mockedList).toHaveBeenLastCalledWith(expect.objectContaining({ search: "master-1", offset: 0 })));
	});

	it("opens an exact revision and saves only stage text as a new draft revision", async () => {
		renderAt();
		fireEvent.click(await screen.findByTestId("maintenance-row-master-1-2"));
		await waitFor(() => expect(mockedDetail).toHaveBeenCalledWith("master-1", 2));
		expect(await screen.findByText("Exact Master Storyboard drilldown")).toBeInTheDocument();
		fireEvent.click(screen.getByTestId("maintenance-edit-button"));
		fireEvent.change(screen.getByTestId("maintenance-stage-hook"), { target: { value: "Edited exact Hook" } });
		fireEvent.click(screen.getByTestId("maintenance-save-button"));
		await waitFor(() => expect(mockedSave).toHaveBeenCalledWith(expect.objectContaining({ masterId: "master-1", sourceRevision: 2, stages: expect.arrayContaining([{ stage_key: "hook", authored_text: "Edited exact Hook" }]) })));
		expect(await screen.findByTestId("maintenance-success")).toHaveTextContent("Saved as revision 3 · DRAFT · approval required");
	});

	it("shows the approved edit behavior without offering in-place approval mutation", async () => {
		mockedDetail.mockResolvedValue(detailResponse({ status: "APPROVED", actions: { can_edit: true, edit_mode: "CREATE_NEW_DRAFT", can_reject: false, can_delete: false, delete_reason: "Only an unreferenced DRAFT can be deleted.", delete_blockers: [] }, approval_receipt: { receipt_id: "receipt-1" } }));
		renderAt("/reporting/copywriting-landbank?master_id=master-1&revision=2");
		expect(await screen.findByText("Edit → Create new draft revision")).toBeInTheDocument();
		expect(screen.queryByTestId("maintenance-reject-button")).not.toBeInTheDocument();
	});

	it("routes Reject through existing V3 governance with the typed reason", async () => {
		renderAt("/reporting/copywriting-landbank?master_id=master-1&revision=2");
		await screen.findByTestId("maintenance-reject-button");
		fireEvent.click(screen.getByTestId("maintenance-reject-button"));
		fireEvent.change(screen.getByPlaceholderText("REJECT"), { target: { value: "REJECT" } });
		fireEvent.change(screen.getByPlaceholderText("Explain why this revision is rejected."), { target: { value: "Needs a safer claim." } });
		fireEvent.click(screen.getByRole("button", { name: "Reject revision" }));
		await waitFor(() => expect(mockedReview).toHaveBeenCalledWith("reject", "MASTER_STORYBOARD", "master-1", 2, "Needs a safer claim."));
	});

	it("paginates by exact revision count on the server", async () => {
		mockedList.mockResolvedValue({ ...listResponse(), total: 30, has_more: true });
		renderAt();
		fireEvent.click(await screen.findByText("Next"));
		await waitFor(() => expect(mockedList).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 25, limit: 25 })));
	});
});
