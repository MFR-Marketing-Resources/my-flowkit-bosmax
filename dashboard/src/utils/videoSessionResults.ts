import type { PlanDetail } from "../api/creativeProduction";
import type { SessionResult } from "../components/workspace/ResultsSidebar";

export interface PersistedGenerationJob {
	job_id: string;
	request_id?: string | null;
	mode?: string | null;
	created_at: number;
}

const GENERATION_JOBS_STORAGE_KEY = "bosmax.generation-jobs.v1";

function readStoredJobs(): PersistedGenerationJob[] {
	try {
		const raw = window.sessionStorage.getItem(GENERATION_JOBS_STORAGE_KEY);
		const parsed = raw ? JSON.parse(raw) : [];
		if (!Array.isArray(parsed)) return [];
		return parsed.filter(
			(item): item is PersistedGenerationJob =>
				Boolean(item && typeof item.job_id === "string" && item.job_id.trim()),
		);
	} catch {
		return [];
	}
}

function writeStoredJobs(jobs: PersistedGenerationJob[]) {
	try {
		window.sessionStorage.setItem(
			GENERATION_JOBS_STORAGE_KEY,
			JSON.stringify(jobs.slice(0, 32)),
		);
	} catch {
		// Private browsing/storage-disabled mode: in-memory polling remains valid.
	}
}

export function rememberGenerationJob(
	job: Omit<PersistedGenerationJob, "created_at"> & { created_at?: number },
): void {
	const jobs = readStoredJobs().filter((item) => item.job_id !== job.job_id);
	jobs.unshift({ ...job, created_at: job.created_at ?? Date.now() });
	writeStoredJobs(jobs);
}

export function readGenerationJobs(): PersistedGenerationJob[] {
	return readStoredJobs();
}

export function forgetGenerationJob(jobId: string): void {
	writeStoredJobs(readStoredJobs().filter((item) => item.job_id !== jobId));
}

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
