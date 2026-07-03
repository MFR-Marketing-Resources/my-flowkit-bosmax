import { getAPI, postAPI } from "./client";

// ─── Postiz publishing adapter (feature-flagged backend) ─────
// All endpoints fail closed with 503 while POSTIZ_ENABLED != true.

export interface PostizHealth {
	enabled: boolean;
	base_url: string | null;
	api_key_present: boolean;
	upload_mode: string;
	default_post_type: string;
	ok: boolean;
	problems: string[];
}

export interface PostizIntegration {
	id: string;
	provider: string;
	name: string;
	picture?: string | null;
	disabled?: boolean;
	refresh_needed?: boolean;
	profile?: string | null;
	[key: string]: unknown;
}

export interface PostizIntegrationsResponse {
	integrations: PostizIntegration[];
	count: number;
}

export interface PostizProviderTemplatesResponse {
	templates: Record<string, Record<string, unknown>>;
	warnings: Record<string, string[]>;
}

export type PostizPostType = "draft" | "schedule" | "now";

export interface PostizPublishRequest {
	artifact_media_id: string;
	integration_ids: string[];
	post_type?: PostizPostType;
	schedule_at?: string; // ISO datetime, required for schedule
	content?: string;
	provider_settings?: Record<string, Record<string, unknown>>;
	dry_run?: boolean;
}

export interface PostizPublishSuccess {
	ok: boolean;
	record_id: string;
	post_type: string;
	postiz_media: { id?: string; path?: string; [key: string]: unknown };
	postiz_response: unknown;
	integration_ids: string[];
}

export interface PostizPublishDryRun {
	dry_run: true;
	payload: unknown;
	note: string;
}

export type PostizPublishResponse = PostizPublishSuccess | PostizPublishDryRun;

export type PostizRecordStatus =
	| "PENDING"
	| "UPLOADED"
	| "POST_CREATED"
	| "FAILED";

export interface PostizPublishRecord {
	record_id: string;
	artifact_media_id: string;
	post_type: string;
	status: PostizRecordStatus;
	error: string | null;
	postiz_media_id: string | null;
	integration_ids_json: string[] | null;
	created_at: string;
	[key: string]: unknown;
}

export interface PostizPublishRecordsResponse {
	records: PostizPublishRecord[];
	count: number;
}

export interface PostizSetupStatus {
	postiz_enabled: boolean;
	base_url_configured: boolean;
	base_url: string | null;
	api_key_present: boolean;
	upload_mode: string;
	default_post_type: string;
	api_prefix: string;
	health_ok: boolean;
	postiz_reachable: boolean | null;
	integrations_count: number | null;
	ready: boolean;
	problems: string[];
	next_steps: string[];
	start_commands: string[];
	restart_instruction: string;
	api_key_instructions: string;
	connect_channels_instruction: string;
	provider_warnings: Record<string, string[]>;
	docs_path: string;
	safe_env_example: Record<string, string>;
}

export async function getPostizHealth(): Promise<PostizHealth> {
	return getAPI<PostizHealth>("/api/postiz/health");
}

export async function getPostizSetupStatus(): Promise<PostizSetupStatus> {
	return getAPI<PostizSetupStatus>("/api/postiz/setup-status");
}

export async function getPostizIntegrations(): Promise<PostizIntegrationsResponse> {
	return getAPI<PostizIntegrationsResponse>("/api/postiz/integrations");
}

export async function getPostizProviderTemplates(): Promise<PostizProviderTemplatesResponse> {
	return getAPI<PostizProviderTemplatesResponse>(
		"/api/postiz/provider-templates",
	);
}

export async function publishToPostiz(
	input: PostizPublishRequest,
): Promise<PostizPublishResponse> {
	return postAPI<PostizPublishResponse>("/api/postiz/publish", input);
}

export async function getPostizPublishRecords(): Promise<PostizPublishRecordsResponse> {
	return getAPI<PostizPublishRecordsResponse>("/api/postiz/publish-records");
}
