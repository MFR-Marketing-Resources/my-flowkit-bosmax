import type {
	PosterReadinessResponse,
	PosterReadinessStatus,
} from "../types/posterReadiness";

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

export function resolveGenerateButtonLabel(
	readiness: PosterReadinessResponse,
): string {
	if (readiness.poster_status === "POSTER_READY") {
		return "Generator not implemented in this PR";
	}
	if (readiness.poster_status === "POSTER_READY_RESTRICTED") {
		return "Restricted generator not implemented in this PR";
	}
	if (readiness.poster_status === "POSTER_PREVIEW_ONLY") {
		return "Production generation disabled (preview mode)";
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