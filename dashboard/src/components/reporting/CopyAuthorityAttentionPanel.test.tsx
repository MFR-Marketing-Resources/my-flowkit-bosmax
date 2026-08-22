import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CopyAuthorityAttentionPanel } from "./CopyAuthorityAttentionPanel";

vi.mock("../../api/client", () => ({
	getAPI: vi.fn(),
}));

import { getAPI } from "../../api/client";

const mockedGetAPI = vi.mocked(getAPI);

const readyCandidate = {
	blueprint_id: "bp-ready",
	revision: 1,
	product_id: "product-ready",
	product_name: "Ready Product",
	status: "PRODUCTION_VALID",
	formula_id: "PAS",
	activatable: true,
	current_authority_state: "NONE",
	blocked_reason: null,
	current_authority_reason: null,
};

const currentCandidate = {
	...readyCandidate,
	blueprint_id: "bp-current",
	product_id: "product-current",
	product_name: "Current Product",
	current_authority_state: "CURRENT",
};

const staleCandidate = {
	blueprint_id: "bp-stale",
	revision: 2,
	product_id: "product-stale",
	product_name: "Stale Product",
	status: "PRODUCTION_VALID",
	formula_id: "PAS",
	angle: { angle_id: "angle-stale", definition: "Stale angle" },
	activatable: false,
	activation_allowed: false,
	current_authority_state: "STALE",
	blocked_reason: "COPY_V2_TAXONOMY_AUTHORITY_STALE",
	current_authority_reason: "COPY_V2_TAXONOMY_AUTHORITY_STALE",
	current_authority_mismatches: [],
	active_blueprint_id: null,
	active_revision: null,
	active_lane_count: 0,
	required_lane_count: 8,
};

describe("CopyAuthorityAttentionPanel", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockedGetAPI.mockResolvedValue({
			items: [staleCandidate, currentCandidate, readyCandidate],
			total: 3,
			view: "diagnostics",
			max_batch_size: 50,
			provider_calls: 0,
			credit_spend: 0,
			activation_mutations: 0,
		});
	});

	afterEach(cleanup);

	it("keeps stale copy-authority diagnostics read-only with a replacement Landbank link", async () => {
		render(<CopyAuthorityAttentionPanel />);

		expect(await screen.findByText("Stale Product")).toBeInTheDocument();
		await waitFor(() =>
			expect(mockedGetAPI).toHaveBeenCalledWith(
				"/api/copy-register/v2/bulk/activation-candidates?view=diagnostics",
			),
		);
		expect(screen.getByText(/Taxonomy authority changed after this copy was approved/i)).toBeInTheDocument();
		expect(screen.getByText("COPY_V2_TAXONOMY_AUTHORITY_STALE")).toBeInTheDocument();
		expect(screen.queryByText("Current Product")).not.toBeInTheDocument();
		expect(screen.queryByText("Ready Product")).not.toBeInTheDocument();
		expect(screen.getByTestId("copy-authority-attention-safety")).toHaveTextContent(
			"provider calls: 0 · credit spend: 0 · activation mutations: 0",
		);
		expect(screen.getByRole("link", { name: /Create Replacement in Copywriting Landbank/i })).toHaveAttribute(
			"href",
			"/creative/storyboard-landbank-v3?product_id=product-stale",
		);
	});

	it("shows a clean reporting state when no copy-authority attention is required", async () => {
		mockedGetAPI.mockResolvedValue({
			items: [],
			total: 0,
			view: "diagnostics",
			max_batch_size: 50,
			provider_calls: 0,
			credit_spend: 0,
			activation_mutations: 0,
		});

		render(<CopyAuthorityAttentionPanel />);

		expect(
			await screen.findByText("No stale or blocked copy-authority items."),
		).toBeInTheDocument();
	});
});
