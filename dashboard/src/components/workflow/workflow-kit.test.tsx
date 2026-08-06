/**
 * V4 workflow kit — contract smoke tests. These pin the behaviours the T2V V4
 * layout (and later every lane) relies on: progressive disclosure on
 * WorkflowStep, the AUTO marker + escape hatch on ResolvedChip, the storyboard
 * empty/filled states, queue status/progress, and the cockpit's plan + Generate
 * + Debug drawer. Pure presentational components — queried by text/role.
 */
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
	OperatorCockpit,
	QueueRow,
	ResolvedChip,
	StoryboardStrip,
	WorkflowStep,
} from "./index";

afterEach(() => cleanup());

describe("WorkflowStep — progressive disclosure", () => {
	it("shows its body while active and reveals the number badge", () => {
		render(
			<WorkflowStep index={4} title="Length & quantity" status="active">
				<div>duration controls</div>
			</WorkflowStep>,
		);
		expect(screen.getByText("Length & quantity")).toBeVisible();
		expect(screen.getByText("duration controls")).toBeVisible();
		expect(screen.getByText("4")).toBeVisible();
	});

	it("collapses a done step to its summary, hiding the body", () => {
		render(
			<WorkflowStep
				index={4}
				title="Length & quantity"
				status="done"
				open={false}
				summary="8s · 3 videos"
			>
				<div>duration controls</div>
			</WorkflowStep>,
		);
		expect(screen.getByText("8s · 3 videos")).toBeVisible();
		expect(screen.queryByText("duration controls")).toBeNull();
		// done badge is a check, not the number
		expect(screen.getByText("✓")).toBeVisible();
	});

	it("fires onToggleOpen when the header is clicked (controlled)", () => {
		const onToggle = vi.fn();
		render(
			<WorkflowStep
				index={5}
				title="Creative direction"
				status="done"
				open={false}
				summary="Close-up · ECU"
				onToggleOpen={onToggle}
			>
				<div>recipe picker</div>
			</WorkflowStep>,
		);
		fireEvent.click(screen.getByRole("button", { expanded: false }));
		expect(onToggle).toHaveBeenCalledTimes(1);
	});
});

describe("ResolvedChip — knowledge-resolved value", () => {
	it("renders label + value and the AUTO marker by default", () => {
		render(<ResolvedChip label="Scene → camera" value="Close-up · ECU" />);
		expect(screen.getByText("Scene → camera")).toBeVisible();
		expect(screen.getByText("Close-up · ECU")).toBeVisible();
		expect(screen.getByText("Auto")).toBeVisible();
	});

	it("hides the AUTO marker when auto is false", () => {
		render(<ResolvedChip label="Presenter" value="Farah" auto={false} />);
		expect(screen.queryByText("Auto")).toBeNull();
	});

	it("exposes a Tweak escape hatch that fires onTweak", () => {
		const onTweak = vi.fn();
		render(
			<ResolvedChip label="Presenter" value="Farah" onTweak={onTweak} />,
		);
		fireEvent.click(screen.getByRole("button", { name: "Tweak" }));
		expect(onTweak).toHaveBeenCalledTimes(1);
	});
});

describe("StoryboardStrip — storyboard before compile", () => {
	it("shows the empty hint when there are no shots", () => {
		render(<StoryboardStrip shots={[]} />);
		expect(screen.getByText(/Storyboard appears/i)).toBeVisible();
	});

	it("renders one card per shot", () => {
		render(
			<StoryboardStrip
				shots={[
					{ label: "Present → Close-up", sub: "Farah · ECU" },
					{ label: "Cook → Benefit", sub: "Nadia · CTA" },
				]}
			/>,
		);
		expect(screen.getByText("Present → Close-up")).toBeVisible();
		expect(screen.getByText("Cook → Benefit")).toBeVisible();
	});
});

describe("QueueRow — status + live progress", () => {
	it("renders the status label", () => {
		render(<QueueRow title="Present → Close-up" status="ready" />);
		expect(screen.getByText("Ready")).toBeVisible();
	});

	it("shows a percentage while running", () => {
		render(
			<QueueRow title="Present → Close-up" status="running" progress={72} />,
		);
		expect(screen.getByText("72%")).toBeVisible();
	});
});

describe("OperatorCockpit — plan, generate, debug", () => {
	it("renders the lane label and plan rows", () => {
		render(
			<OperatorCockpit
				laneLabel="Text to Video"
				plan={[
					{ k: "Presenter", v: "Farah" },
					{ k: "Length", v: "8s · 3 videos" },
				]}
			/>,
		);
		expect(screen.getByText("Text to Video")).toBeVisible();
		expect(screen.getByText("Farah")).toBeVisible();
		expect(screen.getByText("8s · 3 videos")).toBeVisible();
	});

	it("fires the Generate CTA and honours disabled", () => {
		const onClick = vi.fn();
		const { rerender } = render(
			<OperatorCockpit
				laneLabel="Text to Video"
				generate={{ label: "Generate 3 videos", onClick }}
			/>,
		);
		fireEvent.click(screen.getByRole("button", { name: "Generate 3 videos" }));
		expect(onClick).toHaveBeenCalledTimes(1);

		rerender(
			<OperatorCockpit
				laneLabel="Text to Video"
				generate={{ label: "Generate 3 videos", onClick, disabled: true }}
			/>,
		);
		fireEvent.click(screen.getByRole("button", { name: "Generate 3 videos" }));
		expect(onClick).toHaveBeenCalledTimes(1); // still once — disabled swallowed it
	});

	it("keeps diagnostics in a Debug drawer", () => {
		render(
			<OperatorCockpit
				laneLabel="Text to Video"
				debug={<div>runtime status</div>}
			/>,
		);
		expect(screen.getByText("Debug")).toBeVisible();
		expect(screen.getByText("runtime status")).toBeInTheDocument();
	});
});
