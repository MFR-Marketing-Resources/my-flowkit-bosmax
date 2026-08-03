import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getAPI = vi.fn();
const postAPI = vi.fn();
const patchAPI = vi.fn();

vi.mock("../../api/client", () => ({
	getAPI: (...args: unknown[]) => getAPI(...args),
	postAPI: (...args: unknown[]) => postAPI(...args),
	patchAPI: (...args: unknown[]) => patchAPI(...args),
}));

import BulkFastMossConvertTab from "./BulkFastMossConvertTab";

function makeRow(overrides: Record<string, unknown> = {}) {
	return {
		reference_id: "ref-ui-001",
		raw_product_title: "UI Evidence Product",
		category: "Beauty",
		claim_risk_level: "LOW",
		image_readiness: "IMAGE_PRESENT",
		promotion_status: "PENDING_DRAFT",
		recompute_state: "UP_TO_DATE",
		recompute_reason: "CURRENT_RULESET_AND_INPUT_MATCH",
		draft_id: null,
		error_message: null,
		created_at: "2026-08-03T00:00:00Z",
		updated_at: "2026-08-03T00:00:00Z",
		...overrides,
	};
}

function primeQueue(row: Record<string, unknown>) {
	getAPI.mockImplementation((path: string) => {
		if (path.endsWith("/queue/stats")) {
			return Promise.resolve({
				total: 1,
				by_status: { [row.promotion_status as string]: 1 },
				by_recompute_state: { [row.recompute_state as string]: 1 },
			});
		}
		return Promise.resolve({ items: [row], total: 1, page: 1, page_size: 50 });
	});
}

describe("BulkFastMossConvertTab evidence and draft actions", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		postAPI.mockResolvedValue({});
		patchAPI.mockResolvedValue({});
	});

	afterEach(() => {
		cleanup();
	});

	it("connects Review / Add to draft creation when no draft exists", async () => {
		const row = makeRow({
			promotion_status: "MISSING_REQUIRED_FIELD",
			recompute_state: "BLOCKED_MISSING_EVIDENCE",
			recompute_reason: "MISSING:SIZE_OR_VOLUME_EVIDENCE",
		});
		primeQueue(row);
		postAPI.mockResolvedValueOnce({
			reference_id: row.reference_id,
			draft_id: "draft-created-for-evidence",
			promotion_status: "MISSING_REQUIRED_FIELD",
		});
		const onOpenDraft = vi.fn();

		render(<BulkFastMossConvertTab onOpenDraft={onOpenDraft} />);
		fireEvent.click(
			await screen.findByTestId(`review-add-evidence-${row.reference_id}`),
		);

		await waitFor(() => {
			expect(postAPI).toHaveBeenCalledWith(
				`/api/fastmoss-bulk/queue/${row.reference_id}/create-draft`,
				{},
			);
			expect(onOpenDraft).toHaveBeenCalledWith("draft-created-for-evidence");
		});
		expect(postAPI).not.toHaveBeenCalledWith(
			"/api/fastmoss-bulk/queue/recompute-selected",
			expect.anything(),
		);
	});

	it("opens an existing evidence draft without creating a duplicate", async () => {
		const row = makeRow({
			promotion_status: "MISSING_REQUIRED_FIELD",
			recompute_state: "BLOCKED_MISSING_EVIDENCE",
			draft_id: "draft-existing-evidence",
		});
		primeQueue(row);
		const onOpenDraft = vi.fn();

		render(<BulkFastMossConvertTab onOpenDraft={onOpenDraft} />);
		fireEvent.click(
			await screen.findByTestId(`review-add-evidence-${row.reference_id}`),
		);

		await waitFor(() => {
			expect(onOpenDraft).toHaveBeenCalledWith("draft-existing-evidence");
		});
		expect(postAPI).not.toHaveBeenCalled();
	});

	it("uses draft creation from the drawer instead of stale-only recompute", async () => {
		const row = makeRow();
		primeQueue(row);
		postAPI.mockResolvedValueOnce({
			reference_id: row.reference_id,
			draft_id: "draft-generated-from-drawer",
			promotion_status: "DRAFT_GENERATED",
		});
		const onOpenDraft = vi.fn();

		render(<BulkFastMossConvertTab onOpenDraft={onOpenDraft} />);
		fireEvent.click(await screen.findByTitle("Click to review details"));
		fireEvent.click(await screen.findByTestId("drawer-generate-draft"));

		await waitFor(() => {
			expect(postAPI).toHaveBeenCalledWith(
				`/api/fastmoss-bulk/queue/${row.reference_id}/create-draft`,
				{},
			);
			expect(onOpenDraft).toHaveBeenCalledWith("draft-generated-from-drawer");
		});
		expect(postAPI).not.toHaveBeenCalledWith(
			"/api/fastmoss-bulk/queue/recompute-selected",
			expect.anything(),
		);
	});

	it("wraps queue actions for compact layouts", () => {
		primeQueue(makeRow());

		render(<BulkFastMossConvertTab onOpenDraft={vi.fn()} />);

		const actionGroup = screen.getByRole("button", { name: "Sync Queue" })
			.parentElement;
		expect(actionGroup?.className).toContain("w-full");
		expect(actionGroup?.className).toContain("flex-wrap");
	});

	it("filters the queue by freshness state", async () => {
		const row = makeRow({ recompute_state: "BLOCKED_MISSING_EVIDENCE" });
		primeQueue(row);

		render(<BulkFastMossConvertTab onOpenDraft={vi.fn()} />);
		fireEvent.change(await screen.findByLabelText("Freshness"), {
			target: { value: "BLOCKED_MISSING_EVIDENCE" },
		});

		await waitFor(() => {
			expect(getAPI).toHaveBeenCalledWith(
				"/api/fastmoss-bulk/queue?recompute_state=BLOCKED_MISSING_EVIDENCE&page=1&page_size=50",
			);
		});
	});
});
