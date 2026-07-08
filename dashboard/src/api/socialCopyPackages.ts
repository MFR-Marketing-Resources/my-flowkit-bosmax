import { getAPI, patchAPI, postAPI } from "./client";

// ─── Social Copy Package (platform-specific caption/comment copy) ─────
// Authored on the generator pages against a finished artifact (media_id),
// approved, then prefilled into Postiz Publish. No social OAuth / no posting
// happens through this API — it only persists copy.

export type SocialPlatform =
	| "tiktok"
	| "facebook"
	| "instagram"
	| "threads"
	| "x";

export type SocialCopyStatus =
	| "DRAFT"
	| "READY"
	| "APPROVED"
	| "REJECTED"
	| "PUBLISHED";

export type SocialComplianceStatus = "OK" | "WARN" | "BLOCKED";

export const SOCIAL_PLATFORMS: SocialPlatform[] = [
	"tiktok",
	"instagram",
	"facebook",
	"threads",
	"x",
];

export interface SocialCopyPackage {
	package_id: string;
	artifact_media_id: string;
	source_mode: string | null;
	platform: SocialPlatform;
	caption: string;
	first_comment: string;
	hashtags_json: string[];
	call_to_action: string;
	tone: string;
	language: string;
	status: SocialCopyStatus;
	compliance_status: SocialComplianceStatus;
	blockers_json: string[];
	warnings_json: string[];
	approval_note: string | null;
	approved_at: string | null;
	postiz_record_id: string | null;
	created_at: string;
	updated_at: string;
	[key: string]: unknown;
}

export interface SocialCopyPackagesResponse {
	packages: SocialCopyPackage[];
	count: number;
}

export interface SocialCopySuggestion {
	platform: SocialPlatform;
	tone: string;
	supports_first_comment: boolean;
	first_comment_label: string;
	caption: string;
	first_comment: string;
	hashtags: string[];
	call_to_action: string;
	cta_options: string[];
	caption_hint: string;
	source_mode: string | null;
}

export interface AICaptionCandidate {
	platform: SocialPlatform;
	caption: string;
	first_comment: string;
	hashtags: string[];
	call_to_action: string;
	tone: string;
	rationale: string;
	risk_notes: string[];
	compliance_status: SocialComplianceStatus;
	blockers: string[];
	warnings: string[];
}

export interface AICaptionAssistResponse {
	provider: {
		lane: string;
		configured: boolean;
		provider_id: string | null;
		model_id: string | null;
		execution_enabled: boolean;
	};
	grounding: {
		source: string;
		grounded: boolean;
		is_stealth: boolean;
		product_name: string | null;
		has_campaign_copy: boolean;
	};
	candidates: AICaptionCandidate[];
}

export interface GenerateSocialCopyRequest {
	artifact_media_id: string;
	platform: SocialPlatform;
	caption?: string;
	first_comment?: string;
	hashtags?: string[];
	call_to_action?: string;
	tone?: string;
	language?: string;
	source_mode?: string | null;
}

export interface UpdateSocialCopyRequest {
	caption?: string;
	first_comment?: string;
	hashtags?: string[];
	call_to_action?: string;
	tone?: string;
	language?: string;
}

const BASE = "/api/social-copy-packages";

export async function listSocialCopyPackages(params?: {
	artifact_media_id?: string;
	platform?: SocialPlatform;
	status?: SocialCopyStatus;
	limit?: number;
}): Promise<SocialCopyPackagesResponse> {
	const qs = new URLSearchParams();
	if (params?.artifact_media_id)
		qs.set("artifact_media_id", params.artifact_media_id);
	if (params?.platform) qs.set("platform", params.platform);
	if (params?.status) qs.set("status", params.status);
	if (params?.limit != null) qs.set("limit", String(params.limit));
	const q = qs.toString() ? `?${qs.toString()}` : "";
	return getAPI<SocialCopyPackagesResponse>(`${BASE}${q}`);
}

export async function suggestSocialCopy(
	platform: SocialPlatform,
	opts?: { source_mode?: string | null; product_name?: string | null },
): Promise<SocialCopySuggestion> {
	const qs = new URLSearchParams({ platform });
	if (opts?.source_mode) qs.set("source_mode", opts.source_mode);
	if (opts?.product_name) qs.set("product_name", opts.product_name);
	return getAPI<SocialCopySuggestion>(`${BASE}/suggest?${qs.toString()}`);
}

export async function generateSocialCopyPackage(
	input: GenerateSocialCopyRequest,
): Promise<SocialCopyPackage> {
	return postAPI<SocialCopyPackage>(`${BASE}/generate`, input);
}

// AI Caption Assist — grounded AI caption candidate(s) for review. Reuses the
// text_assist lane; fails closed (HTTP 409) when the provider is not configured.
// Governance: returns suggestions only — the operator still Saves + Approves.
export async function aiAssistSocialCopy(input: {
	platform: SocialPlatform;
	artifact_media_id?: string;
	product_id?: string;
	source_mode?: string | null;
	language?: string;
	tone?: string;
	operator_notes?: string;
	candidate_count?: number;
}): Promise<AICaptionAssistResponse> {
	return postAPI<AICaptionAssistResponse>(`${BASE}/ai-assist`, input);
}

export async function updateSocialCopyPackage(
	packageId: string,
	input: UpdateSocialCopyRequest,
): Promise<SocialCopyPackage> {
	return patchAPI<SocialCopyPackage>(
		`${BASE}/${encodeURIComponent(packageId)}`,
		input,
	);
}

export async function approveSocialCopyPackage(
	packageId: string,
	approvalNote?: string,
): Promise<SocialCopyPackage> {
	return postAPI<SocialCopyPackage>(
		`${BASE}/${encodeURIComponent(packageId)}/approve`,
		{ approval_note: approvalNote ?? null },
	);
}

export async function rejectSocialCopyPackage(
	packageId: string,
	approvalNote?: string,
): Promise<SocialCopyPackage> {
	return postAPI<SocialCopyPackage>(
		`${BASE}/${encodeURIComponent(packageId)}/reject`,
		{ approval_note: approvalNote ?? null },
	);
}
