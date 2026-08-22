import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import CopyAuthorityActivationReport from "./CopyAuthorityActivationReport";

vi.mock("../../api/copyRegisterV2", () => ({
	fetchCopyActivationCandidates: vi.fn(),
	batchActivateCopyBlueprints: vi.fn(),
}));

import {
	batchActivateCopyBlueprints,
	fetchCopyActivationCandidates,
	type CopyActivationCandidateV2,
} from "../../api/copyRegisterV2";

const mockedCandidates = vi.mocked(fetchCopyActivationCandidates);
const mockedActivate = vi.mocked(batchActivateCopyBlueprints);

function candidate(
	blueprintId: string,
	state: CopyActivationCandidateV2["current_authority_state"] = "NONE",
	overrides: Partial<CopyActivationCandidateV2> = {},
): CopyActivationCandidateV2 {
	return {
		blueprint_id: blueprintId,
		revision: 1,
		product_id: `product-${blueprintId}`,
		product_name: blueprintId === "bp-stale" ? "Stale Product" : "Ready Product",
		status: "PRODUCTION_VALID",
		formula_id: "PAS",
		angle: null,
		activatable: state !== "STALE",
		activation_allowed: state !== "STALE",
		current_authority_state: state,
		blocked_reason: state === "STALE" ? "COPY_V2_TAXONOMY_AUTHORITY_STALE" : null,
		current_authority_reason: state === "STALE" ? "COPY_V2_TAXONOMY_AUTHORITY_STALE" : null,
		current_authority_mismatches: [],
		active_blueprint_id: state === "CURRENT" ? blueprintId : null,
		active_revision: state === "CURRENT" ? 1 : null,
		active_lane_count: state === "CURRENT" ? 8 : 0,
		required_lane_count: 8,
		...overrides,
	};
}

const response = (items: CopyActivationCandidateV2[]) => ({
	items,
	total: items.length,
	max_batch_size: 50,
	provider_calls: 0 as const,
	credit_spend: 0 as const,
	activation_mutations: 0 as const,
});

function renderReport(initialEntries = ["/reporting/operations?section=copy-authority-activation"]) {
	return render(
		<MemoryRouter initialEntries={initialEntries}>
			<CopyAuthorityActivationReport />
		</MemoryRouter>,
	);
}

describe("Copy Authority activation report", () => {
	afterEach(cleanup);

	beforeEach(() => {
		vi.clearAllMocks();
		mockedActivate.mockResolvedValue({
			results: [{
				blueprint_id: "bp-ready",
				activated: true,
				idempotent: false,
				status: "ACTIVATED",
				lane_count: 8,
				error_code: null,
			}],
			activated_count: 1,
			idempotent_count: 0,
			failed_count: 0,
			activation_mutations: 1,
			bound_lane_count: 8,
			provider_calls: 0,
			credit_spend: 0,
		});
	});

	it("keeps stale authority entries in Reporting", async () => {
		mockedCandidates.mockResolvedValue(response([
			candidate("bp-stale", "STALE"),
			candidate("bp-ready", "NONE"),
		]));
		renderReport();
		expect(await screen.findByTestId("copy-authority-activation-report")).toBeInTheDocument();
		expect(screen.getByTestId("activation-candidate-bp-stale")).toHaveTextContent("Stale Product");
		expect(screen.getByTestId("activation-candidate-bp-stale")).toHaveTextContent("COPY_V2_TAXONOMY_AUTHORITY_STALE");
		expect(screen.getByTestId("activation-select-bp-stale")).toBeDisabled();
		expect(screen.getByTestId("activation-select-bp-ready")).toBeEnabled();
	});

	it("preselects a linked blueprint and preserves the guarded activation contract", async () => {
		mockedCandidates.mockResolvedValue(response([candidate("bp-ready", "NONE")]));
		renderReport(["/reporting/operations?section=copy-authority-activation&blueprint_id=bp-ready"]);
		expect(await screen.findByTestId("activation-select-bp-ready")).toBeInTheDocument();
		expect((screen.getByTestId("activation-select-bp-ready") as HTMLInputElement).checked).toBe(true);

		fireEvent.change(screen.getByTestId("activation-confirmation-phrase"), {
			target: { value: "ACTIVATE_COPY_AUTHORITY_BATCH" },
		});
		fireEvent.click(screen.getByTestId("activation-owner-authorization"));
		fireEvent.click(screen.getByTestId("activation-review-selection"));
		expect(await screen.findByTestId("activation-confirm-overlay")).toBeInTheDocument();
		fireEvent.click(screen.getByTestId("activation-confirm-submit"));

		await waitFor(() =>
			expect(mockedActivate).toHaveBeenCalledWith({
			blueprint_ids: ["bp-ready"],
			confirmation_phrase: "ACTIVATE_COPY_AUTHORITY_BATCH",
			owner_authorization: true,
		}),
		);
		expect(await screen.findByTestId("activation-results")).toHaveTextContent("ACTIVATED");
		expect(await screen.findByTestId("copy-authority-activation-success")).toHaveTextContent("1 blueprint bound");
	});
});
