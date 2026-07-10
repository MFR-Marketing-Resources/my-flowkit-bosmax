import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
	resolvePromptRepresentationPresentation,
} from "../utils/promptRepresentationUi";

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

beforeEach(() => {
	Object.assign(navigator, {
		clipboard: {
			writeText: vi.fn().mockResolvedValue(undefined),
		},
	});
});

describe("OperatorPage prompt representation presentation + clipboard", () => {
	it("Block 1 shows Copy Initial Prompt from initial_generation_prompt_text", async () => {
		const p = resolvePromptRepresentationPresentation({
			block_index: 1,
			initial_generation_prompt_text: "INITIAL RESEARCH",
			independent_block_prompt_text: "INDEPENDENT PROD",
			engine_prompt_text: "INDEPENDENT PROD",
			flow_extend_prompt_text: null,
		});
		await navigator.clipboard.writeText(p.primaryCopyText);
		expect(navigator.clipboard.writeText).toHaveBeenCalledWith("INITIAL RESEARCH");
		expect(p.primaryCopyLabel).toBe("Copy Initial Prompt");
		expect(p.showExtendPrimary).toBe(false);
	});

	it("Block 2 Extend copies only flow_extend_prompt_text", async () => {
		const p = resolvePromptRepresentationPresentation({
			block_index: 2,
			independent_block_prompt_text: "INDEPENDENT 9-SECTION You are generating…",
			engine_prompt_text: "INDEPENDENT 9-SECTION You are generating…",
			flow_extend_prompt_text: "Extend this video from the exact ending of Video 1.",
		});
		expect(p.primaryCopyLabel).toBe("Copy Extend Prompt");
		await navigator.clipboard.writeText(p.primaryCopyText);
		expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
			"Extend this video from the exact ending of Video 1.",
		);
		expect(p.primaryCopyText).not.toContain("You are generating");
		expect(p.independentText).toContain("You are generating");
	});

	it("legacy Block 2 without extend shows Independent / Extend Not Available", async () => {
		const p = resolvePromptRepresentationPresentation({
			block_index: 2,
			engine_prompt_text: "LEGACY INDEPENDENT ONLY",
			flow_extend_prompt_text: null,
		});
		expect(p.showExtendUnavailable).toBe(true);
		expect(p.showExtendPrimary).toBe(false);
		expect(p.badgeLabel).toBe("INDEPENDENT BLOCK");
		expect(p.primaryCopyLabel).toBe("Copy Independent Block Prompt");
		await navigator.clipboard.writeText(p.primaryCopyText);
		expect(navigator.clipboard.writeText).toHaveBeenCalledWith("LEGACY INDEPENDENT ONLY");
	});

	it("independent fallback secondary is distinct from extend", async () => {
		const p = resolvePromptRepresentationPresentation({
			block_index: 2,
			independent_block_prompt_text: "INDEPENDENT FALLBACK",
			flow_extend_prompt_text: "Extend this video from the exact ending of Video 1.",
		});
		expect(p.showIndependentSecondary).toBe(true);
		await navigator.clipboard.writeText(p.independentText);
		expect(navigator.clipboard.writeText).toHaveBeenLastCalledWith("INDEPENDENT FALLBACK");
	});

	it("save/reload package fields preserve extend representation (round-trip shape)", () => {
		const saved = {
			prompt_blocks_json: [
				{
					block_index: 1,
					initial_generation_prompt_text: "INIT",
					independent_block_prompt_text: "IND",
					flow_extend_prompt_text: null,
				},
				{
					block_index: 2,
					initial_generation_prompt_text: null,
					independent_block_prompt_text: "IND2",
					flow_extend_prompt_text: "Extend this video from the exact ending of Video 1.",
				},
			],
		};
		const reloaded = JSON.parse(JSON.stringify(saved));
		expect(reloaded.prompt_blocks_json[0].flow_extend_prompt_text).toBeNull();
		expect(reloaded.prompt_blocks_json[1].flow_extend_prompt_text).toMatch(/^Extend this video/);
		expect(reloaded.prompt_blocks_json[1].independent_block_prompt_text).toBe("IND2");
	});
});
