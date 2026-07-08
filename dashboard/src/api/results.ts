import { getAPI } from "./client";

// Results Hub API client — the DURABLE deliverable view for finished generations.
// Read-only: it composes the durable generation_result snapshot (prompt/settings
// for manual Flow fallback), the 48h artifact file (download), and the social
// caption rollup. Captions themselves are authored via socialCopyPackages /
// SocialCopyPackagePanel — this client never posts copy.

export interface CaptionSummary {
	count: number;
	approved: number;
}

export interface ResultListItem {
	media_id: string;
	mode: string | null;
	artifact_kind: "video" | "image";
	product_name: string | null;
	model_label: string | null;
	aspect_ratio: string | null;
	created_at: string;
	has_record: boolean;
	file_available: boolean;
	size_mb: number | null;
	retrieved_url: string | null;
	expires_at: string | null;
	expires_in_hours: number | null;
	caption_summary: CaptionSummary;
}

export interface ResultListResponse {
	results: ResultListItem[];
	count: number;
	retention_hours: number;
}

export interface ResultSnapshot {
	final_prompt_text: string;
	mode: string | null;
	model_label: string | null;
	aspect_ratio: string | null;
	duration_s: number | null;
	count_setting: number | null;
	reference_media_ids: string[];
	product_id: string | null;
	product_name: string | null;
	workspace_generation_package_id: string | null;
	project_id: string | null;
	job_id: string | null;
	request_id: string | null;
}

export interface ResultDetail {
	media_id: string;
	mode: string | null;
	artifact_kind: "video" | "image";
	has_record: boolean;
	product_name: string | null;
	created_at: string | null;
	file_available: boolean;
	retrieved_url: string | null;
	size_mb: number | null;
	expires_at: string | null;
	expires_in_hours: number | null;
	snapshot: ResultSnapshot | null;
	captions: Array<Record<string, unknown>>;
}

export async function listResults(params?: {
	kind?: "video" | "image";
	mode?: string;
	limit?: number;
}): Promise<ResultListResponse> {
	const qs = new URLSearchParams();
	if (params?.kind) qs.set("kind", params.kind);
	if (params?.mode) qs.set("mode", params.mode);
	if (params?.limit != null) qs.set("limit", String(params.limit));
	const q = qs.toString() ? `?${qs.toString()}` : "";
	return getAPI<ResultListResponse>(`/api/results${q}`);
}

export async function getResult(mediaId: string): Promise<ResultDetail> {
	return getAPI<ResultDetail>(`/api/results/${encodeURIComponent(mediaId)}`);
}
