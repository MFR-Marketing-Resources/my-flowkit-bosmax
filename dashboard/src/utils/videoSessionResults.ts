import type { PlanDetail } from "../api/creativeProduction";
import type { SessionResult } from "../components/workspace/ResultsSidebar";

function uniqueVideoResults(candidates: string[]): SessionResult[] {
	const seen = new Set<string>();
	return candidates.flatMap((candidate) => {
		const mediaId = candidate.trim();
		if (!mediaId || seen.has(mediaId)) return [];
		seen.add(mediaId);
		return [{ media_id: mediaId, kind: "video" as const }];
	});
}

export function collectMontageSessionResults(
	run: { scenes?: Array<{ video_media_id?: string | null }> } | null,
	assembly: { concat?: Record<string, unknown> } | null,
): SessionResult[] {
	const finalMediaId =
		typeof assembly?.concat?.final_media_id === "string"
			? assembly.concat.final_media_id
			: "";
	return uniqueVideoResults([
		finalMediaId,
		...(run?.scenes ?? []).map((scene) =>
			String(scene.video_media_id || ""),
		),
	]);
}

export function collectProductionSessionResults(
	detail: PlanDetail | null,
): SessionResult[] {
	if (!detail) return [];
	const videoItemIds = new Set(
		detail.items
			.filter((item) => item.media_type === "VIDEO")
			.map((item) => item.item_id),
	);
	return uniqueVideoResults([
		...detail.items
			.filter((item) => item.media_type === "VIDEO")
			.map((item) => String(item.output_media_id || "")),
		...detail.attempts
			.filter((attempt) => videoItemIds.has(attempt.item_id))
			.map((attempt) => String(attempt.artifact_media_id || "")),
	]);
}
