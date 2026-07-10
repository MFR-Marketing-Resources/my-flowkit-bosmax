import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HandoffExtendPromptBlocks } from "../components/HandoffExtendPromptBlocks";

afterEach(() => cleanup());

beforeEach(() => {
	Object.assign(navigator, {
		clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
	});
});

describe("Handoff Bank extend prompt blocks (component)", () => {
	it("Block 2 extend copies flow_extend_prompt_text only", async () => {
		render(
			<HandoffExtendPromptBlocks
				blocks={[
					{
						block_index: 2,
						independent_block_prompt_text: "SECTION 1 You are generating an 8-second clip.",
						engine_prompt_text: "SECTION 1 You are generating an 8-second clip.",
						flow_extend_prompt_text: "Extend this video from the exact ending of Video 1.",
						duration_seconds: 8,
					},
				]}
			/>,
		);
		expect(screen.getByTestId("handoff-rep-2")).toHaveTextContent("EXTEND");
		const btn = screen.getByTestId("handoff-copy-primary-2");
		fireEvent.click(btn);
		expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
			"Extend this video from the exact ending of Video 1.",
		);
	});

	it("legacy block without extend shows Extend Not Available", async () => {
		render(
			<HandoffExtendPromptBlocks
				blocks={[
					{
						block_index: 2,
						engine_prompt_text: "LEGACY INDEPENDENT ONLY",
						flow_extend_prompt_text: null,
					},
				]}
			/>,
		);
		expect(screen.getByTestId("extend-not-available-2")).toBeInTheDocument();
		expect(screen.getByTestId("handoff-copy-primary-2")).toHaveAttribute(
			"aria-label",
			expect.stringContaining("Copy Independent Block Prompt"),
		);
		fireEvent.click(screen.getByTestId("handoff-copy-primary-2"));
		expect(navigator.clipboard.writeText).toHaveBeenCalledWith("LEGACY INDEPENDENT ONLY");
	});

	it("malformed extend fails closed", async () => {
		render(
			<HandoffExtendPromptBlocks
				blocks={[
					{
						block_index: 2,
						flow_extend_prompt_text: "You are generating an 8-second clip.",
						independent_block_prompt_text: "INDEPENDENT",
					},
				]}
			/>,
		);
		expect(screen.getByTestId("handoff-rep-2")).toHaveTextContent("INVALID");
		fireEvent.click(screen.getByTestId("handoff-copy-primary-2"));
		expect(navigator.clipboard.writeText).toHaveBeenCalledWith("INDEPENDENT");
	});
});