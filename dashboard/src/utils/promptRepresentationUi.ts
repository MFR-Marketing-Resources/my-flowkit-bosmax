/**
 * Route-aware prompt representation helpers for Operator / Handoff Bank.
 *
 * CRITICAL: never infer GOOGLE FLOW EXTEND from block_index alone.
 * Extend UI/copy is only active when a non-empty flow_extend_prompt_text exists.
 */

export type PromptRepresentationKind =
	| "INITIAL_GENERATION"
	| "INDEPENDENT_BLOCK"
	| "GOOGLE_FLOW_EXTEND"
	| "LEGACY_INDEPENDENT";

export interface PromptRepresentationFields {
	block_index?: number | null;
	engine_prompt_text?: string | null;
	compiled_prompt_text?: string | null;
	initial_generation_prompt_text?: string | null;
	independent_block_prompt_text?: string | null;
	flow_extend_prompt_text?: string | null;
}

export interface PromptRepresentationPresentation {
	kind: PromptRepresentationKind;
	badgeLabel: string;
	independentText: string;
	initialText: string;
	extendText: string;
	/** Non-empty only when a real extend prompt exists — never falls back to independent. */
	primaryCopyText: string;
	primaryCopyLabel: string;
	primaryTestId: string;
	showExtendPrimary: boolean;
	showIndependentSecondary: boolean;
	showExtendUnavailable: boolean;
	helpText: string | null;
}

function clean(value: string | null | undefined): string {
	return (value ?? "").trim();
}

export function hasValidFlowExtendPrompt(
	block?: PromptRepresentationFields | null,
): boolean {
	return clean(block?.flow_extend_prompt_text).length > 0;
}

/**
 * Resolve operator/handoff presentation from package block fields only.
 * Does not use block_index to invent Extend mode.
 */
export function resolvePromptRepresentationPresentation(
	block?: PromptRepresentationFields | null,
	fallbackText?: string | null,
): PromptRepresentationPresentation {
	const independentText =
		clean(block?.independent_block_prompt_text) ||
		clean(block?.engine_prompt_text) ||
		clean(block?.compiled_prompt_text) ||
		clean(fallbackText);

	const extendText = clean(block?.flow_extend_prompt_text);
	const hasExtend = extendText.length > 0;
	const blockIndex = Number(block?.block_index ?? 1) || 1;
	const hasInitialField = block?.initial_generation_prompt_text != null;
	const initialText =
		clean(block?.initial_generation_prompt_text) ||
		(blockIndex <= 1 ? independentText : "");

	if (hasExtend) {
		return {
			kind: "GOOGLE_FLOW_EXTEND",
			badgeLabel: "GOOGLE FLOW EXTEND",
			independentText,
			initialText,
			extendText,
			primaryCopyText: extendText,
			primaryCopyLabel: "Copy Extend Prompt",
			primaryTestId: "copy-extend-prompt",
			showExtendPrimary: true,
			showIndependentSecondary: true,
			showExtendUnavailable: false,
			helpText:
				"Extend Prompt is for manual testing through Google Flow’s Extend function. Independent Block Prompt is the existing standalone-block fallback.",
		};
	}

	// Legacy Block 2+ packages without flow_extend_prompt_text.
	if (blockIndex > 1) {
		return {
			kind: "LEGACY_INDEPENDENT",
			badgeLabel: "INDEPENDENT BLOCK",
			independentText,
			initialText: "",
			extendText: "",
			primaryCopyText: independentText,
			primaryCopyLabel: "Copy Independent Block Prompt",
			primaryTestId: "copy-independent-block-prompt",
			showExtendPrimary: false,
			showIndependentSecondary: false,
			showExtendUnavailable: true,
			helpText:
				"Extend Not Available — this package has no flow_extend_prompt_text. Showing Independent Block Prompt only (legacy / production independent route).",
		};
	}

	// Block 1 (or unknown index with initial/independent only).
	const primary = initialText || independentText;
	const isResearchInitial =
		hasInitialField &&
		clean(block?.initial_generation_prompt_text) !== "" &&
		clean(block?.initial_generation_prompt_text) !== independentText;

	return {
		kind: "INITIAL_GENERATION",
		badgeLabel: isResearchInitial
			? "INITIAL GENERATION (research seam)"
			: "INITIAL GENERATION",
		independentText,
		initialText: primary,
		extendText: "",
		primaryCopyText: primary,
		primaryCopyLabel: "Copy Initial Prompt",
		primaryTestId: "copy-initial-prompt",
		showExtendPrimary: false,
		showIndependentSecondary:
			Boolean(independentText) &&
			Boolean(primary) &&
			independentText !== primary,
		showExtendUnavailable: false,
		helpText: null,
	};
}
