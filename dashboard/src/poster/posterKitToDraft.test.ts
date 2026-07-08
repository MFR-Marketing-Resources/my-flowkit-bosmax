import { describe, expect, it } from "vitest";

import { POSTER_AUTO_DEFAULT_DRAFT, kitToDraft } from "./posterKitToDraft";
import { EMPTY_POSTER_DRAFT } from "../types/posterReadiness";
import type { PosterCopyKit } from "../types/posterCopyRecommendations";

function kit(overrides: Partial<PosterCopyKit> = {}): PosterCopyKit {
	return {
		kit_id: "k1",
		status: "approved",
		source: "APPROVED_COPY_SET",
		angle: "Segar",
		hook: "Hook",
		subhook: "Sub",
		usp_1: "a",
		usp_2: "b",
		usp_3: "c",
		cta: "Beli",
		poster_type: "hero",
		visual_route: "premium",
		human_presence_mode: "none",
		frame_ratio: "9:16",
		language: "ms",
		text_density: "medium",
		safety_notes: [],
		blocked_reasons: [],
		copy_set_id: "cs-1",
		formula_validated: true,
		...overrides,
	};
}

describe("poster copy provenance (Phase D)", () => {
	it("default drafts start as manual (non-approved) copy", () => {
		expect(POSTER_AUTO_DEFAULT_DRAFT.copy_source).toBe("manual");
		expect(EMPTY_POSTER_DRAFT.copy_source).toBe("manual");
		expect(POSTER_AUTO_DEFAULT_DRAFT.copy_fallback_confirmed).toBe(false);
	});

	it("kitToDraft carries the approved Copy Set provenance into the draft", () => {
		const draft = kitToDraft(kit(), EMPTY_POSTER_DRAFT);
		expect(draft.copy_source).toBe("APPROVED_COPY_SET");
		expect(draft.copy_set_id).toBe("cs-1");
		// A freshly applied kit is never pre-confirmed as fallback.
		expect(draft.copy_fallback_confirmed).toBe(false);
		expect(draft.hook).toBe("Hook");
	});

	it("kitToDraft carries a fallback/AI source verbatim so the draft is governed", () => {
		const draft = kitToDraft(
			kit({ source: "FALLBACK_TEMPLATE", copy_set_id: null }),
			EMPTY_POSTER_DRAFT,
		);
		expect(draft.copy_source).toBe("FALLBACK_TEMPLATE");
		expect(draft.copy_set_id).toBe("");
	});
});
