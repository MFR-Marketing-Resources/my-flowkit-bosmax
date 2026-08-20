import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import CopyReviewQueuePage from "./CopyReviewQueuePage";

vi.mock("../api/copyRegisterV2", () => ({
	fetchCopyReviewQueue: vi.fn(),
	batchApproveCopyDrafts: vi.fn(),
}));

import {
	batchApproveCopyDrafts,
	fetchCopyReviewQueue,
} from "../api/copyRegisterV2";

const mockedQueue = vi.mocked(fetchCopyReviewQueue);
const mockedApprove = vi.mocked(batchApproveCopyDrafts);

const safeRow = {
	blueprint_id: "bp-safe",
	revision: 1,
	product_id: "product-safe",
	product_name: "Safe Product",
	formula_id: "PAS",
	claim_safe_copy_status: "CLAIM_SAFE_COPY_APPROVED",
	claim_risk_level: "LOW",
	truth_status: "DRAFT",
	truth_current: true,
	batch_approvable: true,
	draft_blocked_reason: null,
	current_authority_reason: "EXPLICIT_HUMAN_APPROVAL_REQUIRED",
	current_authority_mismatches: [],
	draft_preview: {
		angle: { angle_id: "angle-safe", definition: "A grounded safe angle" },
		stages: [{ stage_key: "stage-1", formula_stage_key: "problem", text: "Safe draft text", claim_bearing: false }],
	},
	individual_review_path: "/creative/copy-authority?product_id=product-safe&blueprint_id=bp-safe",
};

const riskyRow = {
	...safeRow,
	blueprint_id: "bp-risk",
	product_id: "product-risk",
	product_name: "Risky Product",
	claim_safe_copy_status: "CLAIM_REVIEW_REQUIRED",
	claim_risk_level: "HIGH",
	batch_approvable: false,
	draft_blocked_reason: "CLAIM_SAFETY_REVIEW_REQUIRED · CLAIM_RISK_HIGH",
	individual_review_path: "/creative/copy-authority?product_id=product-risk&blueprint_id=bp-risk",
};

function renderPage() {
	return render(
		<MemoryRouter initialEntries={["/creative/copy-review-queue"]}>
			<Routes>
				<Route path="/creative/copy-review-queue" element={<CopyReviewQueuePage />} />
			</Routes>
		</MemoryRouter>,
	);
}

describe("CopyReviewQueuePage", () => {
	afterEach(cleanup);

	beforeEach(() => {
		vi.clearAllMocks();
		mockedQueue.mockResolvedValue({
			items: [safeRow, riskyRow],
			total: 2,
			filters: { only_claim_safe: false, product_id: null },
			provider_calls: 0,
			credit_spend: 0,
			activation_mutations: 0,
		});
		mockedApprove.mockResolvedValue({
			results: [{ blueprint_id: "bp-safe", status: "APPROVED", production_status: "PRODUCTION_VALID", error_code: null }],
			approved_count: 1,
			failed_count: 0,
			automatic_approval: false,
			activation_mutations: 0,
			provider_calls: 0,
			credit_spend: 0,
		});
	});

	it("renders cross-product rows and makes claim-risk drafts non-selectable", async () => {
		renderPage();
		expect(await screen.findByTestId("review-queue-table")).toBeInTheDocument();
		expect(screen.getByTestId("queue-row-bp-safe")).toHaveTextContent("Safe Product");
		expect(screen.getByTestId("queue-row-bp-risk")).toHaveTextContent("Individual review required");
		expect(screen.getByTestId("queue-select-bp-risk")).toBeDisabled();
		expect(screen.getByTestId("queue-individual-review-bp-risk")).toHaveAttribute(
		"href",
		"/creative/copy-authority?product_id=product-risk&blueprint_id=bp-risk",
	);
	});

	it("keeps batch approval disabled until reviewer, checklist, rationale, and phrase are complete", async () => {
		renderPage();
		await screen.findByTestId("review-queue-table");
		fireEvent.click(screen.getByTestId("queue-select-bp-safe"));
		const approve = screen.getByTestId("approve-selected-drafts");
		expect(approve).toBeDisabled();

		fireEvent.change(screen.getByTestId("batch-reviewer-input"), { target: { value: "reviewer" } });
		fireEvent.change(screen.getByTestId("batch-rationale-input"), { target: { value: "Reviewed each selected draft." } });
		fireEvent.change(screen.getByTestId("batch-confirmation-phrase"), { target: { value: "APPROVE_COPY_DRAFTS_BATCH" } });
		for (const key of ["semantic", "provenance", "safety", "bridge", "duration"]) {
			fireEvent.click(screen.getByTestId(`batch-approval-check-${key}`));
		}
		expect(approve).toBeEnabled();

		fireEvent.click(approve);
		expect(await screen.findByTestId("batch-confirm-overlay")).toBeInTheDocument();
		expect(mockedApprove).not.toHaveBeenCalled();
		fireEvent.click(screen.getByTestId("batch-confirm"));
		await waitFor(() => expect(mockedApprove).toHaveBeenCalledWith(expect.objectContaining({ blueprint_ids: ["bp-safe"] })));
		expect(await screen.findByTestId("batch-results")).toHaveTextContent("APPROVED · PRODUCTION_VALID");
	});
});
