import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BenefitCopySourceSection, {
	type BenefitCopyExecutionContext,
} from "./BenefitCopySourceSection";

// The renderer panel is exercised by its own tests; here we only need it to fire
// onCopySelected with a finalized {session, prepared} so we can assert the source
// section PROPAGATES the execution identity instead of collapsing it to copyReady.
vi.mock("./OnDemandCopyRendererPanel", () => ({
	default: (props: {
		onCopySelected?: (r: {
			session: { session_id: string; duration_seconds: number };
			prepared: { packages: Array<{ candidate_id: string; status: string }> };
		}) => void;
	}) => (
		<button
			type="button"
			data-testid="fire-selected"
			onClick={() =>
				props.onCopySelected?.({
					session: { session_id: "CRS_test", duration_seconds: 8 },
					prepared: {
						packages: [
							{ candidate_id: "CRC_first", status: "READY" },
							{ candidate_id: "CRC_second", status: "READY" },
						],
					},
				})
			}
		>
			fire
		</button>
	),
}));

vi.mock("../../api/creativeFactory", () => ({
	getProductCapacity: vi.fn(async () => ({
		per_benefit: [{ benefit_id: "BEN_1", benefit: "Relief", ready: true, combinations: 5 }],
	})),
}));

describe("BenefitCopySourceSection identity handoff (Round 4 regression)", () => {
	beforeEach(() => vi.clearAllMocks());
	afterEach(() => cleanup());

	async function selectBenefit() {
		await waitFor(() => expect(screen.getByRole("option", { name: /Relief/ })).toBeTruthy());
		fireEvent.change(screen.getByRole("combobox"), { target: { value: "BEN_1" } });
	}

	it("emits the finalized execution identity (candidate_id) — never just copyReady", async () => {
		const onSelectedCopyChange = vi.fn();
		const onReadyChange = vi.fn();
		render(
			<BenefitCopySourceSection
				productId="prod-1"
				lane="HYBRID"
				durationSeconds={8}
				onReadyChange={onReadyChange}
				onSelectedCopyChange={onSelectedCopyChange}
			/>,
		);
		await selectBenefit();
		fireEvent.click(screen.getByTestId("fire-selected"));

		const ctx = onSelectedCopyChange.mock.calls.at(-1)?.[0] as BenefitCopyExecutionContext;
		expect(ctx).toMatchObject({
			authority_kind: "BENEFIT_COPY_RENDER_V1",
			lane: "HYBRID",
			session_id: "CRS_test",
			candidate_id: "CRC_first", // first READY package, not dropped
			duration_seconds: 8,
		});
		expect(onReadyChange).toHaveBeenCalledWith(true);
	});

	it("clears the selected identity to null when the benefit changes", async () => {
		const onSelectedCopyChange = vi.fn();
		render(
			<BenefitCopySourceSection
				productId="prod-1"
				lane="HYBRID"
				durationSeconds={8}
				onSelectedCopyChange={onSelectedCopyChange}
			/>,
		);
		await selectBenefit();
		fireEvent.click(screen.getByTestId("fire-selected"));
		onSelectedCopyChange.mockClear();
		// changing the benefit invalidates the prior selection
		fireEvent.change(screen.getByRole("combobox"), { target: { value: "" } });
		expect(onSelectedCopyChange).toHaveBeenCalledWith(null);
	});
});
