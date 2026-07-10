import { describe, expect, it } from "vitest";
import {
	hasValidFlowExtendPrompt,
	resolvePromptRepresentationPresentation,
} from "./promptRepresentationUi";

describe("promptRepresentationUi", () => {
	it("never infers extend from block_index alone", () => {
		const legacy = resolvePromptRepresentationPresentation({
			block_index: 2,
			engine_prompt_text: "SECTION 1 - ROLE & OBJECTIVE\nYou are generating an 8-second…",
			independent_block_prompt_text: "SECTION 1 - ROLE & OBJECTIVE\nYou are generating an 8-second…",
			flow_extend_prompt_text: null,
		});
		expect(hasValidFlowExtendPrompt({ block_index: 2, flow_extend_prompt_text: null })).toBe(
			false,
		);
		expect(legacy.kind).toBe("LEGACY_INDEPENDENT");
		expect(legacy.badgeLabel).toBe("INDEPENDENT BLOCK");
		expect(legacy.showExtendPrimary).toBe(false);
		expect(legacy.showExtendUnavailable).toBe(true);
		expect(legacy.primaryCopyLabel).toBe("Copy Independent Block Prompt");
		expect(legacy.primaryCopyText).toContain("You are generating");
		// Must not label as Extend or put independent text into extend primary.
		expect(legacy.primaryCopyLabel).not.toContain("Extend Prompt");
		expect(legacy.extendText).toBe("");
	});

	it("Block 1 uses initial generation primary", () => {
		const block1 = resolvePromptRepresentationPresentation({
			block_index: 1,
			initial_generation_prompt_text:
				"SECTION 8 - CTA & END FRAME\nDuring the final second, the presenter remains naturally speaking",
			independent_block_prompt_text:
				"SECTION 8 - CTA & END FRAME\nEnd on a seam-ready hold: the presenter mid-gesture",
			engine_prompt_text:
				"SECTION 8 - CTA & END FRAME\nEnd on a seam-ready hold: the presenter mid-gesture",
			flow_extend_prompt_text: null,
		});
		expect(block1.kind).toBe("INITIAL_GENERATION");
		expect(block1.primaryCopyLabel).toBe("Copy Initial Prompt");
		expect(block1.primaryCopyText).toContain("naturally speaking");
		expect(block1.showIndependentSecondary).toBe(true);
		expect(block1.independentText).toContain("seam-ready hold");
	});

	it("Block 2 Extend only when flow_extend_prompt_text is non-empty", () => {
		const extend =
			"Extend this video from the exact ending of Video 1.\n\nContinue immediately.";
		const block2 = resolvePromptRepresentationPresentation({
			block_index: 2,
			independent_block_prompt_text: "SECTION 1 - ROLE & OBJECTIVE\nYou are generating…",
			engine_prompt_text: "SECTION 1 - ROLE & OBJECTIVE\nYou are generating…",
			flow_extend_prompt_text: extend,
		});
		expect(block2.kind).toBe("GOOGLE_FLOW_EXTEND");
		expect(block2.showExtendPrimary).toBe(true);
		expect(block2.primaryCopyText).toBe(extend);
		expect(block2.primaryCopyText).not.toContain("You are generating");
		expect(block2.primaryCopyLabel).toBe("Copy Extend Prompt");
		expect(block2.showIndependentSecondary).toBe(true);
		expect(block2.independentText).toContain("You are generating");
	});

	it("does not fall back independent into extend primary when extend is empty string", () => {
		const p = resolvePromptRepresentationPresentation({
			block_index: 2,
			engine_prompt_text: "INDEPENDENT ONLY",
			flow_extend_prompt_text: "   ",
		});
		expect(p.showExtendPrimary).toBe(false);
		expect(p.showExtendUnavailable).toBe(true);
		expect(p.primaryCopyText).toBe("INDEPENDENT ONLY");
	});
});
