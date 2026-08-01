import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IntelligenceStagePanel } from "./IntelligenceStagePanel";

const BREAKDOWN = {
	NO_DRAFT: 194,
	CLAIM_BLOCKED: 16,
	CLAIM_REVIEW_REQUIRED: 6,
	DRAFT_INCOMPLETE: 0,
	READY_FOR_REVIEW: 0,
	APPROVED_SNAPSHOT: 0,
} as const;

const noop = () => {};

function renderPanel(over: Partial<Parameters<typeof IntelligenceStagePanel>[0]> = {}) {
	return render(
		<IntelligenceStagePanel
			breakdown={BREAKDOWN}
			stage=""
			risk=""
			copyBlocked=""
			onStage={noop}
			onRisk={noop}
			onCopyBlocked={noop}
			{...over}
		/>,
	);
}

describe("IntelligenceStagePanel", () => {
	afterEach(cleanup);

	it("renders every stage with its whole-cohort count", () => {
		renderPanel();
		expect(screen.getByTestId("stage-chip-NO_DRAFT")).toHaveTextContent("194");
		expect(screen.getByTestId("stage-chip-CLAIM_BLOCKED")).toHaveTextContent("16");
		expect(
			screen.getByTestId("stage-chip-CLAIM_REVIEW_REQUIRED"),
		).toHaveTextContent("6");
		// zero stages stay visible so the ladder never looks truncated
		expect(screen.getByTestId("stage-chip-READY_FOR_REVIEW")).toHaveTextContent("0");
	});

	it("totals the breakdown so it can be reconciled against the headline", () => {
		renderPanel();
		expect(screen.getByTestId("stage-total")).toHaveTextContent("216");
	});

	it("states that the headline still means no approved snapshot", () => {
		renderPanel();
		expect(screen.getByText(/no approved snapshot/i)).toBeInTheDocument();
	});

	it("selects a stage on chip click and clears it when clicked again", () => {
		const onStage = vi.fn();
		const { rerender } = renderPanel({ onStage });
		fireEvent.click(screen.getByTestId("stage-chip-CLAIM_BLOCKED"));
		expect(onStage).toHaveBeenCalledWith("CLAIM_BLOCKED");

		rerender(
			<IntelligenceStagePanel
				breakdown={BREAKDOWN}
				stage="CLAIM_BLOCKED"
				risk=""
				copyBlocked=""
				onStage={onStage}
				onRisk={noop}
				onCopyBlocked={noop}
			/>,
		);
		expect(screen.getByTestId("stage-chip-CLAIM_BLOCKED")).toHaveAttribute(
			"aria-pressed",
			"true",
		);
		fireEvent.click(screen.getByTestId("stage-chip-CLAIM_BLOCKED"));
		expect(onStage).toHaveBeenLastCalledWith("");
	});

	it("exposes the claim-risk and copy-blocked filters", () => {
		const onRisk = vi.fn();
		const onCopyBlocked = vi.fn();
		renderPanel({ onRisk, onCopyBlocked });
		fireEvent.change(screen.getByTestId("filter-claim-risk"), {
			target: { value: "HIGH" },
		});
		expect(onRisk).toHaveBeenCalledWith("HIGH");
		fireEvent.change(screen.getByTestId("filter-copy-blocked"), {
			target: { value: "yes" },
		});
		expect(onCopyBlocked).toHaveBeenCalledWith("yes");
	});

	it("renders zeroes rather than crashing when the server sends no breakdown", () => {
		renderPanel({ breakdown: undefined });
		expect(screen.getByTestId("stage-chip-NO_DRAFT")).toHaveTextContent("0");
		expect(screen.getByTestId("stage-total")).toHaveTextContent("0");
	});
});
