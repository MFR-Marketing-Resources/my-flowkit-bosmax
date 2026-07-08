import type { PosterBuilderDraft } from "../types/posterReadiness";
import type { PosterCopyKit } from "../types/posterCopyRecommendations";

export const POSTER_AUTO_DEFAULT_DRAFT: PosterBuilderDraft = {
	poster_objective: "Product awareness",
	poster_type: "Product-only hero poster",
	visual_route: "Premium commercial",
	human_presence_mode: "No human / product-forward",
	frame_ratio: "9:16",
	language: "ms",
	text_density: "medium",
	hook: "",
	subhook: "",
	usp_1: "",
	usp_2: "",
	usp_3: "",
	cta: "",
	operator_notes: "",
	copy_source: "manual",
	copy_set_id: "",
	copy_fallback_confirmed: false,
	poster_recipe_id: "",
};

export function kitToDraft(
	kit: PosterCopyKit,
	current: PosterBuilderDraft,
): PosterBuilderDraft {
	return {
		...current,
		poster_objective: current.poster_objective || POSTER_AUTO_DEFAULT_DRAFT.poster_objective,
		poster_type: kit.poster_type || current.poster_type,
		visual_route: kit.visual_route || current.visual_route,
		human_presence_mode: kit.human_presence_mode || current.human_presence_mode,
		frame_ratio: kit.frame_ratio || current.frame_ratio,
		language: kit.language || current.language,
		text_density: kit.text_density || current.text_density,
		// NOTE: kit.angle is the STRATEGY angle (used by guided mode / dedupe), not a
		// poster copy field — deliberately NOT written into the draft.
		hook: kit.hook,
		subhook: kit.subhook,
		usp_1: kit.usp_1,
		usp_2: kit.usp_2,
		usp_3: kit.usp_3,
		cta: kit.cta,
		// Carry copy provenance so the prompt-draft governance knows whether this copy
		// is an approved (formula-validated) Copy Set or lower-trust ephemeral copy.
		copy_source: kit.source,
		copy_set_id: kit.copy_set_id ?? "",
		copy_fallback_confirmed: false,
	};
}