import type {
	PosterBuilderDraft,
	PosterReadinessResponse,
	PosterReadinessStatus,
} from "../types/posterReadiness";

// The copy fields the backend REQUIRES before a poster prompt draft can be built
// (poster_prompt_draft_service CRITICAL_FIELDS). Angle is NOT a poster copy field.
const POSTER_REQUIRED_COPY: readonly [keyof PosterBuilderDraft, string][] = [
	["hook", "Hook"],
	["cta", "CTA"],
];

// Poster copy must FIT the poster — short, unlike video copywriting. Max characters
// per copy field (SSOT — MUST match agent/services/poster_prompt_draft_service.py
// POSTER_COPY_LIMITS).
export const POSTER_COPY_LIMITS = {
	hook: 48,
	subhook: 72,
	usp_1: 36,
	usp_2: 36,
	usp_3: 36,
	cta: 24,
} as const;

const POSTER_COPY_LABELS: Record<keyof typeof POSTER_COPY_LIMITS, string> = {
	hook: "Hook",
	subhook: "Subhook",
	usp_1: "USP 1",
	usp_2: "USP 2",
	usp_3: "USP 3",
	cta: "CTA",
};

/** Human labels of the required copy fields still empty on the draft (empty when ready). */
export function missingPosterCopyFields(draft: PosterBuilderDraft): string[] {
	return POSTER_REQUIRED_COPY.filter(
		([key]) => !String(draft[key] ?? "").trim(),
	).map(([, label]) => label);
}

/** Copy fields over their poster length limit, as "Label (len/limit)" (empty when OK). */
export function overLimitPosterCopyFields(draft: PosterBuilderDraft): string[] {
	return (Object.keys(POSTER_COPY_LIMITS) as (keyof typeof POSTER_COPY_LIMITS)[])
		.filter(
			(key) => String(draft[key] ?? "").trim().length > POSTER_COPY_LIMITS[key],
		)
		.map(
			(key) =>
				`${POSTER_COPY_LABELS[key]} (${String(draft[key] ?? "").trim().length}/${POSTER_COPY_LIMITS[key]})`,
		);
}

export type PosterBuilderShellMode =
	| "hidden"
	| "preview"
	| "full"
	| "restricted";

export function posterStatusOperatorLabel(
	status: PosterReadinessStatus,
): string {
	switch (status) {
		case "POSTER_READY":
			return "Ready";
		case "POSTER_READY_RESTRICTED":
			return "Restricted Ready";
		case "POSTER_REPAIR_REQUIRED":
			return "Repair Required";
		case "POSTER_PREVIEW_ONLY":
			return "Preview Only";
		case "POSTER_BLOCKED":
			return "Blocked";
		default:
			return status;
	}
}

/** UI visibility derived only from API response fields — no readiness inference. */
export function resolveBuilderShellMode(
	readiness: PosterReadinessResponse,
): PosterBuilderShellMode {
	if (readiness.poster_status === "POSTER_BLOCKED") return "hidden";
	if (readiness.poster_status === "POSTER_REPAIR_REQUIRED") return "hidden";
	if (readiness.poster_status === "POSTER_PREVIEW_ONLY") return "preview";
	if (readiness.poster_status === "POSTER_READY_RESTRICTED") return "restricted";
	if (readiness.poster_status === "POSTER_READY") return "full";
	return "hidden";
}

export function shouldShowRepairActionCenter(
	readiness: PosterReadinessResponse,
): boolean {
	return (
		readiness.poster_status === "POSTER_REPAIR_REQUIRED" ||
		readiness.poster_status === "POSTER_PREVIEW_ONLY" ||
		readiness.poster_status === "POSTER_BLOCKED" ||
		readiness.blockers.length > 0
	);
}

export function shouldShowHumanReviewPanel(
	readiness: PosterReadinessResponse,
): boolean {
	return readiness.poster_status === "POSTER_BLOCKED";
}

export function isImageGenerationDisabled(
	_readiness: PosterReadinessResponse,
): boolean {
	return true;
}

/** Prompt draft generation follows API readiness — no local inference. */
export function isPromptDraftGenerationEnabled(
	readiness: PosterReadinessResponse,
): boolean {
	return (
		readiness.poster_status === "POSTER_READY" ||
		readiness.poster_status === "POSTER_READY_RESTRICTED" ||
		readiness.poster_status === "POSTER_PREVIEW_ONLY"
	);
}

export function resolvePromptDraftButtonLabel(
	readiness: PosterReadinessResponse,
): string {
	if (readiness.poster_status === "POSTER_READY") {
		return "Generate poster prompt draft";
	}
	if (readiness.poster_status === "POSTER_READY_RESTRICTED") {
		return "Generate restricted-safe prompt draft";
	}
	if (readiness.poster_status === "POSTER_PREVIEW_ONLY") {
		return "Generate diagnostic prompt preview";
	}
	if (readiness.poster_status === "POSTER_REPAIR_REQUIRED") {
		return "Complete repairs before prompt draft";
	}
	if (readiness.poster_status === "POSTER_BLOCKED") {
		return "Prompt draft blocked";
	}
	return "Prompt draft unavailable";
}

export function resolveGenerateButtonLabel(
	readiness: PosterReadinessResponse,
): string {
	if (readiness.poster_status === "POSTER_READY") {
		return "External image generation disabled in this release";
	}
	if (readiness.poster_status === "POSTER_READY_RESTRICTED") {
		return "External image generation disabled in this release";
	}
	if (readiness.poster_status === "POSTER_PREVIEW_ONLY") {
		return "External image generation disabled (preview mode)";
	}
	if (readiness.poster_status === "POSTER_REPAIR_REQUIRED") {
		return "Complete repairs before generation";
	}
	if (readiness.poster_status === "POSTER_BLOCKED") {
		return "Poster generation blocked";
	}
	return "Generation unavailable";
}

export function isGenerateButtonDisabled(
	_readiness: PosterReadinessResponse,
): boolean {
	return true;
}

export function shouldShowHighRiskGuidance(
	readiness: PosterReadinessResponse,
): boolean {
	return readiness.blockers.includes("CLAIM_RISK_HIGH");
}

export function isBuilderFormEditable(mode: PosterBuilderShellMode): boolean {
	return mode === "full" || mode === "restricted" || mode === "preview";
}

export function statusToneClass(status: PosterReadinessStatus): string {
	switch (status) {
		case "POSTER_READY":
			return "border-emerald-500/40 bg-emerald-500/10 text-emerald-100";
		case "POSTER_READY_RESTRICTED":
			return "border-amber-500/40 bg-amber-500/10 text-amber-100";
		case "POSTER_REPAIR_REQUIRED":
			return "border-orange-500/40 bg-orange-500/10 text-orange-100";
		case "POSTER_PREVIEW_ONLY":
			return "border-sky-500/40 bg-sky-500/10 text-sky-100";
		case "POSTER_BLOCKED":
			return "border-rose-500/40 bg-rose-500/10 text-rose-100";
		default:
			return "border-slate-600 bg-slate-800 text-slate-200";
	}
}